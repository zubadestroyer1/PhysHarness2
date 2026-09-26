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
`responses.input_tokens.count` preflights each request. The next output cap is bounded by
remaining cumulative tokens. A provider consumption discrepancy raises a limit violation and
stops further turns. No aliases or substitute models are selected by the adapter. Parameters
supported here are `instructions`, `reasoning`, `text`, `temperature`, `top_p`, and `service_tier`.
Unsupported provider parameter/model combinations fail at the provider.

The adapter uses `store=False`, requests encrypted reasoning content, and replays native output
items in subsequent inputs, preserving item IDs and function `call_id`. Native responses are
stored before usage callbacks. `ToolDispatcher.register(name, json_schema, async_handler,
description="")` exposes only registered functions; handlers receive `(arguments, operation_id)`
and must return JSON objects. JSON Schema validates every argument. Tool errors fail loudly.
Handlers are trusted control-plane code: they must authorize project access and reserve their
own budgets before starting children or external work. There is no implicit native subagent tool.

Optional async `event_sink(RuntimeEvent)` receives `generation_started`, `generation_aborted`,
`usage`, `tool_completed`, and `completed`. The generation-start event contains the input/output
token reservation and fires before billable generation. A core ledger can veto generation by
raising. If the runtime deadline expires before the provider request, `generation_aborted` releases
that reservation with zero usage.
The usage event includes the stable operation ID and actual native usage; reconciliation should
be idempotent by operation ID. If the provider response was persisted but delivery of a usage
callback failed, reconcile from the saved native response. The adapter does not implement a
transactional outbox or monetary pricing; those belong to the controller/ledger.

The session is checkpointed before each external request and host tool. A crash or tool failure
with a pending marker prohibits automatic resume. Provider usage absent from a response also
requires reconciliation. A session's total token budget persists across `continue_session`.
`start_from_handoff` and `start(..., predecessor=checkpoint)` seed a successor with its
lineage's cumulative usage, so the budget also persists across a task's continuations.
`interrupt` cancels the active local coroutine; provider completion/billing may remain uncertain.

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
awaiting input-token preflight. The in-process active-session guard prevents concurrent calls
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
