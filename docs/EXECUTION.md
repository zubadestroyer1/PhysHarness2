# Execution subsystem

The execution package is independent of API/database models. It exposes Pydantic request,
result, checkpoint, event, and capability records plus asynchronous runtime and sandbox
protocols. Import public interfaces from `physharness.execution`.

## Runtime contract

`RuntimeAdapter` provides:

```python
async def start(prompt: str, model: ModelConfig, limits: RuntimeLimits) -> RuntimeResult
async def continue_session(session_id: str, prompt: str) -> RuntimeResult
async def interrupt(session_id: str) -> bool
async def checkpoint(session_id: str) -> RuntimeCheckpoint
async def resume(checkpoint: RuntimeCheckpoint) -> RuntimeSession
async def export(session_id: str) -> RuntimeCheckpoint
```

`ModelConfig(model, parameters={})` keeps the exact requested identifier. Unknown/reserved
adapter parameters fail rather than modifying the model selection. `RuntimeLimits` sets
provider turns, output tokens per generation, cumulative input+output tokens, and wall time.
Capabilities identify which limits an adapter can enforce. They are qualification/configuration
statements, not live service health checks.

The limits have different scopes when a research task hands off to a successor session:

- `max_turns` bounds one native session. Every continuation, native or portable, starts a
  fresh session with its own turn count, so a long task can take many more turns in total.
- A numeric `max_total_tokens` caps the task's whole continuation lineage. Successors start
  from the cumulative input+output usage of every predecessor, so a handoff never replenishes
  the guard. When the lineage reaches it, the runtime stops with `BUDGET_EXHAUSTED` and the task
  blocks instead of handing off again. `max_total_tokens: null` removes this guard and leaves
  the ceiling to the experiment's shared dollar, time and optional token budget.
- A portable successor carries the lineage count only when the runtime's `start` accepts a
  keyword `predecessor` (the handed-off source `RuntimeCheckpoint`) or `**kwargs`.
  `ResponsesRuntime` does. The protocol `start(prompt, model, limits)` above, and the Claude,
  Codex and OpenHands adapters, do not. With such a runtime the research executor starts a
  portable successor without `predecessor` when `max_total_tokens` is null. When it is numeric,
  the executor refuses with `CONTINUATION_TOKEN_GUARD_UNSUPPORTED` rather than silently
  resetting the guard. It checks this, and that the source checkpoint still matches the ticket
  digest (`CONTINUATION_STALE`), before consuming the continuation ticket. The task ends
  `blocked` with `execution_failure` evidence, the ticket and its link stay `issued`, and the
  worker slot is released.

`examples/research_runs/plan.template.json` sets `max_total_tokens: 32768`. Tasks launched from
that template stop after about 32K tokens in total across all their continuations. Every turn
re-sends its input context, and each of those input tokens counts toward the cap. For
long-horizon runs, raise the value or set it to null and rely on the experiment budget.

`RuntimeSession` contains its own ID, runtime, exact model configuration, limits, status,
native provider/session ID, turn count, and cumulative input/output usage.
`RuntimeResult` contains that session, output text, SHA-256-addressed output artifacts with
provider provenance, and native output items. Model output is not a verified scientific result.

`RuntimeStore.save(checkpoint)` and `.load(session_id)` are externally supplied async hooks.
`SQLiteRuntimeStore(path)` is a durable local implementation; it must be closed with `.close()`.
A production store must serialize ownership of each session across workers and retain the
checkpoint transactionally. The reference store is a single-owner development store; it does
not supply distributed leases or compare-and-swap revisions.

`RuntimeCheckpoint` includes the full session, provider state, format version and content
digest. Digest verification detects accidental corruption; it is not a signature or an
authorization boundary. Treat checkpoints as trusted project-scoped records. Resume retains
the same session identity and refuses an older/different checkpoint for an existing identity.
No adapter claims portable VM forks. An in-flight operation remains uncertain after a crash;
there is no automatic blind retry.

`ExecutionError` exposes `code`, `operation_id`, `retryable`, `remediation`, and `.as_dict()`.
Underlying provider exceptions are chained for internal diagnosis; public messages omit provider
exception bodies, which can contain credentials. Cancellation of an HTTP request does not prove
that remote billable work stopped.

## OpenAI Responses

```python
store = SQLiteRuntimeStore("runtime.db")
runtime = ResponsesRuntime(store=store, dispatcher=ToolDispatcher(), event_sink=on_event)
result = await runtime.start(
    "State an explicit conjecture and its assumptions.",
    ModelConfig(model="YOUR_EXACT_MODEL", parameters={"reasoning": {"effort": "high"}}),
    RuntimeLimits(max_turns=4, max_output_tokens=2000, max_total_tokens=12000),
)
```

This is a genuine `AsyncOpenAI.responses.create` tool loop. The real SDK's
`responses.input_tokens.count` counts the first request of every start, continuation, resume or
handoff; a native wake is a new run, so it counts too. It also counts any request whose estimate
plus the output cap comes within 8,192 tokens (`CONTEXT_MARGIN`) of the context window or of the
cumulative guard. Otherwise the input is bounded without a count. The bound is the last billed
input, plus the canonical UTF-8 bytes of every request element that differs from the element at
the same position in the previous request, plus a margin of the larger of 2,048 tokens and 2% of
that sum. The elements are the instructions, the tools array and each input item, and removed
content earns no credit. The previous request's element digests stay in runtime memory for the
current run only, so a restart counts again. A compaction voids the bound. The budget and context
checks use the count when one was taken and the bound otherwise. The same value is the input
reservation, except under `context_management`. There a count is reserved with the bound's margin
added, and the count plus margin, or the bound, is reserved only while it plus 8,192 is at most
`compact_threshold`; otherwise the whole window (`max_context_tokens`) is. The output reservation,
which is also the output cap sent, is `max_output_tokens`, or the remaining cumulative tokens when
fewer remain. A 400 from `create` means the request was not sent: it is recorded as
`preflight_error` (stage `create`), then `generation_aborted(reason="request_invalid")` releases
the reservation at zero, and the session fails rather than being left uncertain, unless that
release itself fails. A provider consumption discrepancy raises a limit violation and stops
further turns.
No aliases or substitute models are selected by the adapter. Parameters supported here are
`instructions`, `reasoning`, `text`, `temperature`, `top_p`, `service_tier`,
`context_management`, and `parallel_tool_calls`. Unsupported provider parameter/model combinations
fail at the provider.

Reserving less than the window under `context_management` rests on two provider assumptions.
- **Compaction fires only above the threshold.** Server compaction fires only when a request's
  input exceeds `compact_threshold`, so a request under the gate cannot compact, and every
  compaction pass, which may bill more than the counted or bounded input, falls on a request that
  reserved the whole window. If a response to a request reserved below the window does carry a
  compaction item, the runtime logs a warning and emits `bound_reservation_compacted`
  (`response_id`, `input_tokens_reserved`, `input_tokens` and `compact_threshold`). It does so
  once the response is durable and before `usage` is emitted, so before the ledger settles it
  and before any limit check. A compaction that billed past the reservation still stops, through
  the ledger's sticky reconciliation halt (`BUDGET_RECONCILIATION_REQUIRED`) when settlement
  finds the overrun, or else through `PROVIDER_LIMIT_VIOLATION`; the alarm names the cause.
- **`context_management` adds no billed input.** `responses.input_tokens.count` does not accept
  `context_management`, so a request is counted without it but billed with it. The runtime
  assumes it adds no input tokens while compaction does not fire. The margin added to a counted
  reservation covers a small gap. S1 cannot confirm this, because every S1 request under
  `context_management` reserved the whole window; the first paid run checks it
  (`work/society-s1/RUN_PLAN.md`, "Reservation smoke check").

`tools/reservation_bound.py` re-checks the bound offline on audit-extracted turns. Its bound sums
the characters of the appended items. That never exceeds the runtime's bound, which sums their
canonical UTF-8 bytes, so a turn that passes offline would also pass at runtime. On S1's 3,651
consecutive completed turn pairs, the billed input was at most 0.9996 of the offline bound without
its margin and 0.980 with it. That leaves little raw headroom: the runtime's safety comes mainly
from the JSON syntax its byte count adds over those characters and from the margin.

`parallel_tool_calls` defaults to `false`, as today. With `true`, a response's function calls
still run one at a time, in the order the provider emitted them: the calls in a batch are never
executed concurrently, and each call's pending marker is durable before that call's dispatch. A
fatal tool error stops the batch, leaving its later calls undispatched and the session
`uncertain`; a tool error envelope (a normal failed result returned to the model, not raised) does
not stop the batch. Handoff and wait intents from the boundary hook apply only after the whole
batch settles. There is no per-response call cap beyond the output cap.

The adapter uses `store=False`, requests encrypted reasoning content, and replays native output
items in subsequent inputs, preserving item IDs and function `call_id`. Native responses are
stored before usage callbacks. `ToolDispatcher.register(name, json_schema, async_handler,
description="")` exposes only registered functions; handlers receive `(arguments, operation_id)`
and must return JSON objects. JSON Schema validates every argument. Tool errors fail loudly.
Handlers are trusted control-plane code: they must authorize project access and reserve their
own budgets before starting children or external work. There is no implicit native subagent tool.

A stored response keeps only `STORED_RESPONSE_FIELDS` (`id`, `object`, `created_at`,
`completed_at`, `model`, `status`, `output`, `usage`, `incomplete_details`, `error` and
`service_tier`) plus `request_echo_sha256`, a digest of the rest: the provider's echo of the
request (tools, instructions and settings). A response from a different model than requested is
kept whole as evidence. Checkpoints saved with full echoes still load. A `tool_results` entry
stores `visible_output` only when a stagnation signal changed it; replay otherwise uses `result`.
`update_source` and `boundary_hook` receive the checkpoint that was just saved, not a rebuilt copy.

Optional async `event_sink(RuntimeEvent)` receives `generation_started`, `generation_aborted`,
`usage`, `tool_completed`, and `completed`. The generation-start event contains the input/output
token reservation and fires before billable generation. A core ledger can veto generation by
raising. If the runtime deadline expires before the provider request, `generation_aborted` releases
that reservation with zero usage, and only then is the marker cleared, so a failed release leaves
the session uncertain.

A 429 with code `rate_limit_exceeded` did no work, whether it refused the count or the create, so
the same request is resent. The wait follows the provider's hint (`retry-after-ms`, then
`retry-after`) or a doubling backoff, capped at 30 s per wait. `provider_throttled` is emitted once
per wait. It carries the attempt, the wait, its source and bounded header numbers, never the error
text. A sink failure is logged and ignored. A create's event carries the generation's operation id.
A count's event has none. `usage` reports the create's wait totals. A count has no operation or
reservation, so its waits appear only as events. The runtime gives up when the next wait would
outlast the deadline or when the wait is interrupted. A count holds no reservation, so its give-up
aborts nothing. A create's give-up is definite: `generation_aborted(reason="rate_limited")`
releases the reservation at zero, and only then is the marker cleared. Giving up at the deadline
fails the session with retryable `PROVIDER_RATE_LIMITED`, and the executor blocks the task for an
operator to resume. An interrupted wait leaves the session `interrupted`, or `failed` with
`TIMEOUT` when the runtime's own deadline cancelled it.

The usage event includes the stable operation ID and actual native usage; reconciliation should
be idempotent by operation ID. If the provider response was persisted but delivery of a usage
callback failed, reconcile from the saved native response. The adapter does not implement a
transactional outbox or monetary pricing; those belong to the controller/ledger. `usage` also
carries `cached_input_tokens`, the provider's reported cache hits (0 when absent or inconsistent).
The ledger settles them at the price's optional `cached_input_usd_per_million`, which may not
exceed the input rate, and at the full input rate without one. Every reservation stays at the full
input rate, since a cache hit is never guaranteed in advance, so a reservation still bounds its
settlement (`docs/FIRST_LIVE_RUN.md`).

The session is checkpointed before each external request and host tool. A turn saves at:
- **A**, the generation marker, which also carries any turn note;
- **B**, the response, before `usage`;
- **D**, one per dispatched call: its marker, the settlement and the earlier calls' outputs;
- **F**, the last output and the settled boundary.

A one-call turn makes 4 saves, and a k-call turn makes 3 + k. A final text response instead saves
the settled terminal response, then its completion. A peer delivery adds its save before the
acknowledgement, and a compaction adds its marker and prune saves. Settlement after `usage` is not
saved on its own: until the next save the durable state is B, which holds the generation marker,
so a crash stays uncertain. A fatal tool error, a cancellation or a failed settlement is recorded
by `_run`'s failure save. `tool_completed` and any stagnation signal are emitted after the save
that made the call's output durable. When that is `_run`'s failure save, they follow it
best-effort, in call order, and a sink error is only logged so the original failure propagates. If
the failure save itself fails, nothing is announced.

The controller's store verifies each checkpoint's digest once, then encodes it into
content-addressed chunks; encoding stays on the event loop by design. A save first stores its new
chunk and manifest bytes, then commits their artifact rows, the session pointer and one
`session.saved` event in one `runtime.save` transaction. A committed row therefore never references
missing bytes, and an interrupted save publishes nothing and leaves only orphan bytes. Chunks carry
no `artifact.created` event. A crash or tool failure with a pending marker prohibits automatic
resume. Provider usage absent from a response also requires reconciliation. A session's total token
budget persists across `continue_session`.
`start_from_handoff` and `start(..., predecessor=checkpoint)` seed a successor with its
lineage's cumulative usage, so the budget also persists across a task's continuations.
`interrupt` cancels the active local coroutine; provider completion/billing may remain uncertain.

### Provider rate governance

`PHYSHARNESS_PROVIDER_TOKENS_PER_MINUTE` (`Settings.provider_tokens_per_minute`) enables one
`TokenRateGovernor` (`execution/admission.py`) per process. The worker and `run-team` share it
across every runtime on the process's event loop. Unset, there is no governor and nothing changes.
The governor is a token bucket that holds 15 s of tokens (a quarter of the limit;
`DEFAULT_BURST_SECONDS`), so a cold start or an idle spell cannot spend a whole minute's tokens at
once. A request's estimate is its input bound plus the `max_output_tokens` it sends (its output
reservation), because the provider counts the requested max output toward the limit. The input
bound is the value the reservation uses below the window: the exact count, the margin-inclusive
bound, or under `context_management` the count plus the bound's margin (G4). Cached tokens count,
since the provider's limit counts them. Admission comes before
`generation_started`, so a request waiting for its first admission holds no dollar reservation,
and a target verified while it is queued sends nothing. A re-queued create keeps its reservation,
as a rate-limit wait always did. `generation_started` then carries `admission_wait_seconds`. Once
`usage` is emitted, the governor settles at the billed input plus output, refunding the unused
output and any overestimate, or charging an underestimate. Any other exit after the send keeps the
estimate charged.

Roots and joined children, which a parent waits on, are admitted first, then referees, then
everything else. A waiting request ages one class per 30 s, so nothing starves.

Every 429 pauses all admission for its wait. That includes a 429 the runtime gives up on at once
because the wait would pass the deadline. A 429 also cuts the rate by 20%, but at most once per
30 s (`CUT_COOLDOWN_SECONDS`). A 429 that arrives while admission is paused, or within 30 s of the
last cut, only extends the pause if its wait is longer. A burst of refusals therefore cuts once,
and isolated refusals from traffic the governor cannot see cannot ratchet the rate down. The rate
recovers additively by 5% of the limit every 10 s, so one cut is gone in 40 s. With one isolated
429 a minute the rate stays at or above 80% of the limit. A 429 on `responses.create` also
releases its admission and re-queues the request behind the pause instead of sleeping. The
re-queued request keeps the queue age it had built up, so it waits in the priority queue with
every other request without starting over. A 429 on `input_tokens.count` holds no admission, so
it pauses and may cut but does not re-queue (F10). A re-queued request must be admitted one second before
the deadline. Otherwise the give-up is definite, as without a governor:
`generation_aborted(reason="rate_limited")`, then the marker clears, and the session fails with
retryable `PROVIDER_RATE_LIMITED`. These exits return the admission, because they certainly sent
nothing:
- a target verified while queued;
- a timeout before the send;
- a failed `generation_started`;
- a 400;
- a rate-limit give-up.

Any other exit keeps the estimate charged until the bucket refills.

The governor adds no throughput. It spreads requests under the limit, in priority order, instead
of letting them all meet 429s. It cannot see other processes, so set it to about 90% of the org
limit divided by the number of processes that share it. Cross-process governance belongs to the
model router (`PLAN.md` §6.1). The estimate follows OpenAI's rate-limit guidance, which counts
the requested max output toward TPM. Validate it in a dev calibration before a paid arm enables
the governor: compare `provider_throttled.limit_tokens` and `remaining_tokens` with the
governor's `snapshot()`.

### Context budget (opt-in)

An experiment or run plan may set `context_budget`. When it is absent, requests, tool outputs and
native state are exactly as described above. The fields and their defaults are:
- `elide_min_chars`: 4,000 (at least 500);
- `elide_after_turns`: 5 (at least 1);
- `elide_every_turns`: 10 (at least 1);
- `max_output_chars`: 24,000 (at least 20,000), or `null` for no cap. A truncated view may exceed
  it by its envelope, about 150 characters plus the tool name and call ID.

The executor passes `ResponsesRuntime(context_budget=...)` only when the field is set. `start`
stores the policy in native state under `context_budget`, and `start_from_handoff` copies it, so a
continuation keeps the policy its lineage started with, even when its own runtime was built
without one. Under a budget:
- **Literal Unicode (#5e).** Tool outputs are serialized with `ensure_ascii=False`, so non-ASCII
  text reaches the model as literal characters, not `\uXXXX` escapes. A lone surrogate is the
  exception: UTF-8 cannot encode it, and left literal it would make every later request of the
  lineage fail, so it keeps the `\udXXX` escape that legacy output uses. In every experiment,
  `ToolDispatcher.dispatch` also rewrites a lone surrogate in a tool result (keys included) as
  that escape before the result is stored, so checkpoints always save, and returns a result that
  has none unchanged. Two keys that would escape to the same key fail the call with
  `TOOL_FAILED` rather than lose a value.
- **Output cap.** An output whose serialized text is longer than `max_output_chars` is replaced in
  the model's input by a view. The view is `{"truncated": true, "tool", "total_chars", "head",
  "recall": {"tool": "recall_output", "call_id", "next_offset"}}`, and its `head` holds the first
  `max_output_chars // 2` characters. The head and every recall page serialize the output with
  sorted keys, the order a reloaded checkpoint keeps, so they join exactly. The full result stays
  in `tool_results`, and replay is unchanged. This one per-output cap also covers whole-file
  reads (R7).
- **`recall_output(call_id, offset)`.** This built-in tool is appended to the tools array that is
  sent. It returns up to 16,000 characters of a stored output's text from `offset`, with
  `next_offset` (null at the end) and `total_chars`. It searches the active `tool_results`, then
  the session's own archives, then the inherited ones, and matches the call ID from any session
  in the lineage; the latest match wins. An unknown ID returns a `RECALL_NOT_FOUND` error
  envelope. A recall is a pure read. It sets no pending marker, never reaches the dispatcher, is
  never stored in `tool_results` and is never capped. Like any call, it emits `tool_completed`
  (and any stagnation signal, since stagnation counts it as a read) after the save that holds its
  output, so tool-call metrics count recalls. It is not part of the society tool catalog, and a
  dispatcher that registers its own `recall_output` under a budget fails with `INVALID_CONFIG`.
- **Block elision.** Every `elide_every_turns` provider responses, at the settled boundary before
  the next request is prepared, each tool output longer than `elide_min_chars` characters from a
  response at least `elide_after_turns` responses old is replaced in place by a stub,
  `{"elided":true,"tool","chars","sha256","head","recall":{"tool":"recall_output","call_id"}}`.
  `chars` is the replaced text's length, `sha256` the first 16 hex digits of its digest and
  `head` its first 160 characters. The full result stays in `tool_results`, so `recall_output`
  on the stub's call ID pages it back. An output is replaced only when its stub is strictly
  shorter, so elision never lengthens an output and `chars_removed` is always positive. Never
  elided are recall pages, stubs, outputs stored without a `seq` (before this feature), and
  outputs whose `tool_results` entries a compaction archived. Between blocks the input only
  grows, so its prefix is byte-stable and provider prefix caching holds; a block breaks the
  prefix once, at its first newly elided item. A block that elides anything emits
  `context_elided` with `count`, `chars_removed`, `first_index` (the input index of the first new
  stub) and `seq`. It is emitted only after the save that holds the stubs, normally the
  generation marker save and otherwise the save that ends the run. A crash before that save
  replays the block with the same payload, and `(session_id, seq)` identifies a block, so
  consumers can dedupe on it.
- **Elision state.** `elision = {"seq", "last_block_seq"}` in native state. `seq` counts the
  lineage's provider responses: it grows with each response and is saved with it (save B), and
  `start_from_handoff` copies it, so a native successor keeps the block schedule; a portable
  successor starts a fresh context at 0. Every stored `tool_results` entry records its response's
  `seq` and the tool `name`. The stubs and `last_block_seq` are saved with the next generation
  marker, so a restart never elides twice. Checkpoints without `elision` never elide.
- **Elision and the bound.** A stub is not byte-identical to the output it replaces, so the P1
  bound counts it at its full size and credits nothing for the removed output: a block's request
  adds every new stub to its bound, and the requests between blocks bound only their appended
  items. The text the model sees shrinks by `chars_removed`.
- **Not a default yet.** Elision changes what the model sees. Making it a default needs a quality
  A/B; block sizes (`elide_every_turns`) of 8 to 20 are recommended for it. Larger blocks break
  the cache less often but keep stale outputs longer.
- **Tool digest.** The session record's `tool_definition_digest` covers the tools actually sent,
  including `recall_output`. If the digest changes between a joined-children wait and its wake,
  for example because the runtime stops accepting the budget, that in-flight native handoff falls
  back to a portable continuation. A budgeted wait whose digest is unchanged still resumes
  natively. The bound above treats the tools array as one element, so adding the recall tool is
  counted once, at its full size.

The `research_lean` context profile sets the compaction threshold to
`min(96,000, window − max_output − 8,192)`. It is independent of `context_budget`, but is meant to
be paired with it.

### Stored shape changes (G3 infrastructure, all experiments)

G1 covers the bytes the model sees and the pinned freeze tests (F7), so these changes reach legacy
experiments too.
- The `usage` wait totals (`rate_limit_waits`, `rate_limit_wait_seconds`).
- The `provider_throttled` events.
- Stored responses keep only `STORED_RESPONSE_FIELDS` plus `request_echo_sha256`.
- A `tool_results` entry omits an unchanged `visible_output`.
- `generation_started` carries `input_tokens_estimate` (the exact count or the margin-inclusive
  bound) and `input_tokens_counted`.
- `preflight_error.stage` may be `create`, with the generation's operation ID, after a 400 from
  `create`; its `generation_aborted` has `reason="request_invalid"`.
- `usage.cached_input_tokens`: the provider's reported cache hit (0 when absent or inconsistent).
  The controller/ledger settles those tokens at an optional cached rate, while every reservation
  stays at the full input rate, since a cache hit is never guaranteed in advance.
- A checkpoint chunk has no `artifact.created` event and no command row of its own; each save is
  one `runtime.save` transaction.
- Smaller input reservations under `context_management`: `generation_started.input_tokens_reserved`
  and `settled_response.input_reserved` hold the count plus the bound's margin, or the bound, not
  the whole window, while that value plus 8,192 is at most `compact_threshold`.
- The `bound_reservation_compacted` alarm event.
- Fewer saves per turn: 4 for a single call, 3 + k for k calls. `tool_completed` is emitted after
  the save that made its output durable. Settlement rides on the next save, so a crash between
  `usage` and that save leaves the session `uncertain` (save B holds the generation marker).
- A deadline abort before the send emits `generation_aborted` before it clears the marker, so a
  failed release leaves the session `uncertain`, not `failed`.
- `ToolDispatcher.dispatch` escapes a lone surrogate in a tool result, keys included, as
  `\udXXX`. This changes no stored shape for any input that saved before: no store could save a
  result holding one.

Under `context_budget` only (opt-in):
- Native state holds `context_budget` and `elision = {"seq", "last_block_seq"}`.
- Each `tool_results` entry records its response's `seq` and the tool `name`.
- Model-visible tool output text keeps a lone surrogate as its `\udXXX` escape, while other
  Unicode stays literal.
- The `context_elided` event.

## Official Codex SDK

`CodexRuntime` uses official `openai_codex.AsyncCodex`, `CodexConfig`, `thread_start`,
`thread_resume`, `AsyncThread.turn`, and `AsyncTurnHandle.run/interrupt`, verified against
`openai-codex 0.154.0`. It retains native thread/turn IDs, items and usage. Its native checkpoint
requires the same worker directory and provider-local thread store; the exported Python snapshot
alone cannot migrate native Codex state to another host.

The SDK starts a local app-server and inherits the host environment. It must run on a trusted,
dedicated worker. This adapter requires `allow_local_execution=True` and
`allow_unbounded_provider_tokens=True`; defaults refuse to launch. The official SDK does not
expose a hard per-turn token cap. Its `hard_token_limit=False` means it cannot be used where the
controller requires hard token reservations. Observed cumulative usage stops later turns, but
one native turn can exceed the requested limit. Native provider calls inside a turn are opaque.

The adapter explicitly sets `features.multi_agent=false` and `features.multi_agent_v2=false`
in launch/thread configuration, uses `Sandbox.read_only` and `ApprovalMode.deny_all`, and exposes
`controlled_spawning=False`. Model parameters accepted are `effort`, `output_schema`,
`service_tier`, and `summary`. All other parameters fail. Optional SDK import failures include
installation guidance. No live model generation was used to qualify this adapter.

`ClaudeRuntime` and `OpenHandsRuntime` implement native continuation/checkpoint contracts against
the pinned SDKs. See [Claude](CLAUDE_RUNTIME.md) and [OpenHands](OPENHANDS_RUNTIME.md) for their
specific authority and isolation requirements. Claude requires a dedicated trusted worker;
OpenHands accepts only externally qualified remote VM endpoints. Both require explicit
acknowledgment of native token-budget uncertainty. Neither is integrated into the distributed
research executor yet. The unconfigured capability registry correctly reports them unavailable;
it does not infer live qualification from an installed SDK.

## Sandboxes

`SandboxExecutor.run(CommandRequest)` returns `CommandResult`, including operation and execution
IDs, real exit code, bounded returned stdout/stderr, and truncation flags. Nonzero command exits
are actual results rather than model success. `cancel(operation_id)` requests termination.

`LocalShellExecutor(root, allow_local_execution=False)` is **development only**. It validates
working directories, rejects traversal and symlink components beneath the configured root,
starts a new POSIX process group, kills that group on timeout/cancellation/completion, drains
stdout/stderr with byte caps, supplies a minimal environment, and prevents concurrent reuse of
an active operation ID. stdin is closed. Use absolute executable paths outside the minimal PATH.

Cwd validation is not filesystem isolation: a command can still open other host paths, create
symlinks, access the network, or detach from its process group. This is not a VM security boundary
or an executor for hostile production code. It must never be used to run model-written research
JavaScript on the control plane. The JS runner checks and rejects this executor.

`E2BSandboxProvider(api_key=..., template_id=..., timeout_seconds=300)` requires an explicit exact,
qualified template ID and key; `.create()` calls actual `e2b.AsyncSandbox.create`. It sets
`secure=True`, `allow_internet_access=False`, and supplies no environment secrets. There is no
default-template fallback. Its native sandbox ID is the execution identity. One command runs at
a time per VM; timeout/cancellation attempts bounded termination of the whole VM. Failed or
uncertain termination preserves the exact VM identity, quarantines further commands, and reports
an unresolved outcome. Native pause/resume/snapshot/fork and bounded portable file archives are
implemented and contract-tested; the canonical broker intentionally refuses native child
allocation until child budget/lifecycle integration exists. See [workspace contracts](VM_WORKSPACES.md).

E2B output is capped in returned results, but the provider SDK may internally buffer full
streams. Provider-side resource/output controls remain necessary for adversarial workloads.
VM creation/cancellation, native lifecycle operations and template isolation require live
qualification; this repository's
unit suite makes no claims that such live qualification has passed.

## Durable JavaScript research programs

`ResearchProgramRunner(journal, executor=vm, dispatcher=tools)` runs untrusted source in a
separate Node process inside the configured provider VM. It never evaluates JavaScript in the
trusted Python process, nor uses Node `vm` as a security boundary. The Node template must have no
control-plane filesystem mounts, credentials, or network egress. Model code may access its own
VM filesystem; the security boundary is the configured VM, not the JavaScript wrapper.

The exposed helper is `await host(operationId, commandName, arguments)`. Each new host operation
ends the VM subprocess, reaches a schema-checked Python broker, and records the result durably.
The next subprocess replays source with prior host results. Programs must be deterministic
between host calls and use stable operation IDs. There is a finite host-command and subprocess
wall-time limit. This mechanism is replay of orchestration, not a serialized JavaScript heap or
recovery of arbitrary filesystem/network side effects.

`CommandJournal(path)` supplies independent durable Python replay even when VM execution is
unavailable. `begin(program_id, operation_id, command, arguments)` atomically records a pending
command and returns `None` for first dispatch or the prior JSON-object result for a completed
replay. Changed command/arguments produce `COMMAND_MISMATCH`; an unresolved dispatch produces
`OPERATION_UNCERTAIN`. `complete(...)` records the JSON-object result. `.export(program_id)` returns
journal records. The runner also binds a program ID to a source digest.

A crash after a side effect but before journal commit remains uncertain. The operator/controller
must reconcile the authoritative external operation and record a result; it must not delete the
pending record and hope a retry is safe. Host handlers should themselves use the supplied stable
operation ID with providers that support idempotency. Core distributed locks and project/budget
authorization remain required for multi-worker deployment.

## Sources and qualification

- [OpenAI Codex SDK](https://developers.openai.com/codex/sdk/) documents the official Python SDK.
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
  documents native function calls and call-result correlation.
- [E2B async Python SDK](https://docs.e2b.dev/sdk-reference/python-sdk/v2.5.0/sandbox_async)
  documents VM creation, commands and lifecycle.
- Installed interfaces inspected: `openai 2.54.0`, `openai-codex 0.154.0`, `e2b 2.49.1`.

Run `.venv/bin/python -m pytest tests/test_execution*.py -q`. The suite uses actual local
subprocesses, actual Node for trusted wrapper fixtures, SQLite close/reopen replay, real OpenAI
SDK calls with mocked HTTP only, and optional real installed-SDK signature checks. It does not
spend API credits or create live E2B VMs. Passing it does not establish production VM or provider
availability.


OpenHands client processes must set `LOG_AUTO_CONFIG=false` before their first SDK import,
alongside `LITELLM_LOCAL_MODEL_COST_MAP=True`. A late logging opt-out cannot undo SDK
initialization and is refused. Temporal workers use
`physharness.orchestration.sandbox.workflow_runner()` to share only Beartype's global
import machinery; ordinary workflow module isolation and file/network/time restrictions
remain active. See [OpenHands runtime compatibility](OPENHANDS_RUNTIME.md#temporal-import-compatibility).

## Finite research teams

`ResearchTeamRunner` executes existing canonical tasks, with one manifest governing the
supervisor's concurrency, task count, verification count, and elapsed time:

```python
from physharness.orchestration.research_worker import (
    ResearchTaskExecutor, ResearchTeamRunner, TeamRunManifest,
)

executor = ResearchTaskExecutor(service, prices=recorded_prices)
report = await ResearchTeamRunner(service, executor=executor).run(
    TeamRunManifest(
        project_id=project_id,
        experiment_id=experiment_id,
        task_ids=[root_task_id],
        mode="live",
        max_concurrency=2,
        max_tasks=8,
        timeout_seconds=300,
        include_delegated=True,
        process_verifications=True,
        max_verifications=8,
    )
)
```

The experiment must already exist and have been explicitly started against its reviewed
problem. Live mode requires `OPENAI_API_KEY` and the ordinary Responses executor. Replay mode
requires an explicitly injected provider fixture; it cannot silently select the paid provider.
The executor reads each branch's exact recorded model and parameters. It does not prescribe a
mathematical method. Manifest and report artifacts retain the mode and run identity. A report's
`completed` status means its selected tasks finished; scientific acceptance is established
separately through canonical receipts and reviews.

The supervisor discovers helper, collaborator, and competing descendant branches, including
children created by a running model, and starts their tasks only when their canonical dependency
tasks are completed. Same-branch delegation records the parent task so a later supervisor run
continues its queued children without taking unrelated tasks on that branch. A failed parent
does not cancel independently runnable children. Every
worker uses the experiment's shared ledger and its own task lease. Repeated dispatch of a
completed task returns its canonical status without another model request. A running task with
prior native state requires explicit reconciliation and is never silently restarted.

The local supervisor does not replace Temporal or a distributed process manager. Its loss leaves
canonical child tasks, artifacts, checkpoints, reservations, and receipts available to another
controller. An abruptly lost process can leave worker slots and model requests reserved until
operator reconciliation; absence of a process does not prove a remote request or VM stopped.
The report lists queued tasks left by a task-count limit or unmet dependencies.

When enabled, one independent verification worker at a time calls the existing canonical
`process_verification` route under a verifier identity. It handles receipts on the selected
branches and is separately bounded by `max_verifications`. Models can use
`wait_for_verification(receipt_id, timeout_seconds)` for an interruptible wait of at most 30
seconds without another model generation. The wait returns the actual canonical receipt,
including `queued` when the deadline expires. Verifier dispatch errors are reported separately;
they cannot manufacture a receipt status.

A supervisor timeout cancels local model coroutines and preserves unresolved monetary/token
reservations. Python cannot terminate an already running verifier thread. In that case the
report explicitly sets `verification_worker_continues=true` and lists pending receipt IDs.
The underlying checker must have its own bounded execution and containment; Python process
shutdown can wait for that checker. This report does not claim that the verifier stopped.
Temporal's independently supervised verification activities remain the deployment path for
process isolation and durable delivery.

## Continuation, duplicate calls, and authority

Responses checkpoints are independent snapshots. Every continuation saves `running` before
its first provider call. The in-process active-session guard prevents concurrent calls
through one adapter, and canonical research workers additionally acquire a durable task lease.
Custom shared runtime stores must provide controller-side serialization; the generic
`RuntimeStore` protocol is not a distributed lock.

A provider function-call ID binds its name, arguments, and committed result in native state.
Repeating the same ID reuses the saved result; changing its intent raises `COMMAND_MISMATCH`.
The Responses adapter attaches its durable generation operation ID as `X-Client-Request-Id` for
correlation. This header is not a provider idempotency guarantee. Provider retries remain
disabled, and ambiguous requests remain blocked.

The pending generation marker clears only after usage settlement succeeds. A failed accounting
hook retains the response, actual usage, and correlation ID for reconciliation. Explicit resume
can reopen a local interruption with no pending external operation, preserving cumulative token
and turn limits. Running or uncertain checkpoints cannot resume automatically.

Every model tool executes within a controller-issued `worker_effects` binding. The service
checks its task/identity/lease and active experiment in the same transaction before replaying
an idempotent result and again before committing mutations. A stale lease or cancelled
experiment stops the model loop. Operator checkpoint writes have the narrow exception of
retaining final uncertain evidence after cancellation; they still require the current fence.
Monetary settlement and failure evidence remain possible after cancellation.

Temporal delivery validates canonical memo identity for both active and completed duplicate
workflow IDs. Active experiment signals are sent only after that validation; task workflows
with uncertain provider effects do not receive automatic activity retries.

Model-facing `verify_candidate` requests the service's `publication=True` assurance tier so
actual successful checks can produce independently replayed, reusable lemma evidence. That
legacy flag selects the independent-kernel check; it does not approve publication, novelty,
or scientific interpretation. Missing independent-checker configuration blocks acceptance and
never falls back to ordinary kernel assurance for this tool.

## Responses parameter preflight

`execution.parameters.validate_responses_parameters(dict)` is shared by launch preflight,
worker allocation, and the runtime. It returns independent JSON values containing only supplied
fields; invalid input raises `ExecutionError(code="INVALID_CONFIG")` without echoing unknown
keys, parameter values, or schema contents. `ResponsesParameters` defines the typed structure.
Runtime start validates before saving a checkpoint, and the research worker validates before
reserving a slot or leasing a task. Continuation validates older checkpoint parameters too.

The contract follows the installed OpenAI SDK's reasoning context/effort/summary fields, its
open string reasoning mode, text format/verbosity, optional instructions, service tiers, and
finite temperature/top-p ranges. Nested protocol fields reject unknown keys. A JSON Schema
format retains general JSON schema values and extension keywords. Provider support for a
particular model, reasoning mode, or structured-output schema remains provider-checked; this
validation does not infer model capabilities.

`TeamRunLimits(max_concurrency=..., max_tasks=..., timeout_seconds=...)` validates supervisor
limits before task IDs exist. `TeamRunManifest` inherits those fields. Invalid or nonfinite
elapsed-time limits are rejected before seeding a team.
