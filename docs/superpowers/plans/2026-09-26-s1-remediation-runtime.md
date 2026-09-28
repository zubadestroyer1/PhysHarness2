# S1 Remediation: Runtime and Provider Throughput Implementation Plan

> **As shipped (2026-09-27).** The lane was rebased onto origin/main 9333b25 before review. It differs from the text below in three ways:
> - **Task 11b was added by the controller.** `ToolDispatcher.dispatch` escapes a lone surrogate in any tool result, keys included, before the result is stored, so every store can save it; escaping that would merge two keys fails the call with `TOOL_FAILED`.
> - **Tasks 11 and 12 carry review fixes.** Budget-mode tool output escapes lone surrogates, so later requests stay encodable. An output is elided only when its stub is shorter. `context_elided` is announced only after the save that holds its stubs.
> - **Task 13 also fixed the integration audits' minor findings.** Admission uses the reservation's margin-inclusive input, the create sends the tools the P1 digests describe, the deadline abort emits before it clears the marker, and per-session caches end with their run.
>
> - **The merge audit (2026-09-27) bounded recall.** A recall page is sized by its escaped length, which is what the model reads; quote-heavy pages had reached about 32,000 characters. Stale recall pages are elided like any output, with a stub that names the stored call ID and offset, so recalls no longer grow the context for good.
> - **The merge audit (2026-09-27) added a cache-write rate.** A price with `cached_input_usd_per_million` must also give `cache_write_usd_per_million`. Reported cache writes settle at it, and reservations charge input at the higher of the input and cache-write rates. Without it, list prices ($2/M input, $2.50/M writes) would have left cache writes under-settled once cached reads stopped over-counting.
>
> `docs/EXECUTION.md` describes the shipped behaviour.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the per-turn runtime costs that the S1 audit measured. Crash consistency and the sticky overrun rule must not weaken. The costs are:
- silent 429 waits;
- $1.28 reservations against a $0.13 median turn;
- a full-context token count every turn;
- about 6.5 full-state checkpoint saves per turn;
- cached input billed at the full rate;
- stale tool outputs re-sent every turn.

**Architecture:** Task 1 splits `ResponsesRuntime._loop` into phases without changing behaviour. Tasks 2–12 then follow ruling R2's order.
- **Opt-in (defaults keep today's behaviour):** changes to what the model sees, namely the context budget, the TPM governor, `parallel_tool_calls` and the cached-input price.
- **Always on:** persistence and accounting changes. They keep the write-ahead markers.
- **Storage:** new state is JSON, so there are no migrations.

**Base:** origin/main 7202266. `responses.py` there already has `_resend_rate_limited(send, deadline, *, operation_id, abandon)` (both `input_tokens.count` and `responses.create` go through it) and `ResponsesRuntime._abandon_refused`, which emits `generation_aborted(reason="rate_limited")` and only then clears `pending_operation`. Every new abort path keeps that order: emit, then clear. Line numbers cite 7202266; once an earlier task has moved code, find it by the quoted content.

**Cross-lane (F8):** this lane lands first. When its final review is clean, the society lane rebases onto it at its next task boundary, so the society's hot-zone tasks build on this code.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2 (SQLite/PostgreSQL), OpenAI SDK `AsyncOpenAI` mocked with `httpx.MockTransport`, pytest (`asyncio_mode = "auto"`), ruff.

**Spec:** `work/society-s1/audit-2026-09-26/AUDIT.md` (merged in PR #33). The relevant sections are §3A, §3B, §3G, §5 Tier 0 #4, #6 and the `responses.py` half of #5, and Tier 1 #7–#11. The measurements are in `timecost.md` in the same directory. The binding rulings (Global and Runtime lane) are restated below. The design inputs were private remediation maps of the runtime and of the workbench tools (§5e). Where a ruling and a map disagree, the ruling wins.

## Global Constraints

- **G1.** Non-society ("legacy") experiments stay byte-identical, and every legacy freeze test passes unmodified. The freeze tests include `test_worker_legacy_prompt_unchanged` (with `LEGACY_RUNTIME_KWARGS`), `test_legacy_export_is_byte_identical` and `test_legacy_discussion_delivery_shape_unchanged`. Two consequences:
  - pass a new runtime keyword only when its feature is configured;
  - drop a new experiment field from the stored payload when it is `None`.

  "Byte-identical" covers the bytes the model sees and the pinned freeze tests (F7). Stored ledger and event shapes are G3 infrastructure and may change for every experiment: new `usage` and `generation_started` keys, slimmer stored responses, fewer saves, smaller reservations and no per-chunk `artifact.created`. Each task that makes such a change adds a line to the "Stored shape changes" list in `docs/EXECUTION.md` (Task 2 creates the list).
- **G3.** A change to what the model sees is opt-in config, and its default keeps today's behaviour. This covers `context_budget` (elision, the output cap and literal Unicode #5e), the TPM governor, `parallel_tool_calls` and the cached price. Pure infrastructure is always on, provided the invariants below hold: slimming, redundancy removal, coalescing, WAL, preflight skipping (with an exact count near limits) and throttle events.
- **G4.** A reservation must stay a sound upper bound. An overrun sets a sticky experiment-wide halt (`service.py:1177-1206`, and `_active` at `:994-1009`).
  - The bound (P1, F2) is `B + max(2048, ceil(0.02·B))`, where `B` is the last billed input plus the canonical UTF-8 bytes of every request element that is not byte-identical to the element at the same position in the previous request. The elements are the instructions, the tools array (one element) and each input item. Removed content is never credited. The previous request's element digests are kept in memory per session, not in native state; after a restart the first request counts exactly (R3), which re-establishes the baseline.
  - The same margin-inclusive bound is used everywhere a bound is used: the reservation, the count-skip decision and governor admission.
  - It is reserved only while server compaction cannot fire, meaning `bound + 8192 <= compact_threshold`; otherwise reserve today's full window. A compaction item in a response to a request reserved below the window raises the alarm event `bound_reservation_compacted` (F4).
  - Validate the bound offline on the S1 audit's per-arm extract (`<data>/<arm>/turns.jsonl` and `messages.jsonl`). The extract is private and not in the repo. The gate (F3) stops only if the raw ratio of actual to bound (no margin) exceeds 1. The ratio with the margin, expected at about 0.98, is recorded and reported but never stops the task. Put both in the task report and the PR.
  - Lowering `max_output_tokens` is a documentation recommendation, not code.
- **G5.** No DB migrations; state goes in JSON payloads. Stored S1 records must stay readable, so read with `.get` and treat a missing key as the legacy value.
- **G6.** Out of scope; list these as PR next steps:
  - #25;
  - the paid A/B;
  - #12d;
  - warm-REPL reuse;
  - the org TPM limit (an operator action);
  - checkpoint encoding off the event loop (per R4);
  - carrying the P1 bound across a byte-identical native handoff, so a native wake need not count (F9).
- **G7.** Working rules:
  - No `uv sync`. Run everything from the worktree root.
  - Tests: `PYTHONPATH=src .venv/bin/python -m pytest <files> -q` (written `... -m pytest` below).
  - Before each commit, run `.venv/bin/ruff format <changed files>`. Then `ruff check` and `ruff format --check` on `src tests tools infra migrations` must be clean. The code blocks below are written compactly; ruff reflows them.
  - No absolute home-directory path or local username in anything committed.
  - Commit with `git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "<subject>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.
  - Never push, never touch other worktrees or branches, never call a paid API, and no Docker or Colima.
- **G8.** The suite stays green after every task. Docs that describe changed behaviour are updated in the same task: `docs/EXECUTION.md`, `work/society-s1/RUN_PLAN.md` and `PLAN.md`.
- **R1.** Task 1 splits `_loop` into `_prepare_request`, `_send`, `_run_calls` and `_find_tool_result`, with no change in behaviour.
- **R2.** The order is #6, #10a/b/g/h, #9, #4a, #4b, #8, #11, #10c–f, #5e, #7.
- **R3.** Count exactly on the first request of every `_run` (start, continue, resume, recovery, handoff), and whenever the estimate is within `CONTEXT_MARGIN` (8,192) of a limit. Otherwise estimate from the last usage. A 400 from `responses.create` means "not sent". Every native wake is a new `_run`, so it counts (F9, accepted for now).
- **R4.** For checkpoints:
  - never thread the JSON encode;
  - slim the checkpoint, replacing the request echo with a digest;
  - remove redundant serializations and the extra builds made for hooks;
  - make at most 4 saves per single-call turn, and 3 + k for a turn with k calls (F5), without weakening the write-ahead markers;
  - use WAL with `synchronous=FULL`, and one transaction per save;
  - move an fsync out of the write lock only where the ordering is provably kept.
- **R5.** The governor is a per-process token bucket over estimated input plus output (cached tokens count).
  - It admits by priority, with the critical path and roots first.
  - It is off unless `provider_tokens_per_minute` is set.
  - A 429 pauses all admission. Only a 429 on `responses.create` re-queues; a 429 on `input_tokens.count` calls `throttled(wait)`, which only pauses (F10).
  - The operator splits the org limit across processes.
- **R6.** `parallel_tool_calls` is a validated model parameter. The calls in a batch run sequentially, in order, and each has its own pending marker.
- **R7.** The experiment field `context_budget` (not `RuntimeLimits`) makes #7 opt-in. It covers:
  - block elision keyed by a lineage-wide counter;
  - a built-in `recall_output` tool;
  - a cap on whole-file reads, implemented as a uniform per-output cap (`max_output_chars`, default 24,000, minimum 20,000) that applies only under `context_budget` (F6);
  - a lower compaction profile.
- **R8.** `cached_input_usd_per_million` is optional. Absent means costs are unchanged, and it must not exceed the input rate. Price provenance is dumped with `exclude_none`.
- **Invariants.** These come from `docs/EXECUTION.md` and the existing tests.
  - **I1.** `pending_operation` is durable before every provider request (save A) and before each tool dispatch (save D). A crash while it is set blocks automatic resume.
  - **I2.** The response is durable before `usage` (save B). The generation marker clears only after `usage` succeeds.
  - **I3.** A peer delivery is saved before its acknowledgement.
  - **I4.** A manifest publishes only after its chunks are durable. The pointer and `session.saved` commit together under the fence.
  - **I6.** `state_digest`, `resume`'s rewind refusal and the `runtime-save:{state_digest}` key are unchanged.
  - **I7.** Recovery reads the `id`, `model`, `status`, `output` and `usage` keys of `responses[-1]`. Replay reads `tool_results[*]`: `identity`, `result` and `.get("visible_output")`.

---

### Task 1: Split `ResponsesRuntime._loop` without changing behaviour (R1)

**Files:**
- Modify `src/physharness/execution/responses.py`, lines 3–13 (imports) and 743–1134 (`_loop`).
- Test in `tests/test_execution_responses.py`.

**Interfaces (produced):**
- In `responses.py`:
  - `@dataclass(frozen=True, kw_only=True) _Prepared(params, input_tokens: int, input_reservation: int, output_reservation: int, remaining: int | None)`;
  - `@dataclass(frozen=True, kw_only=True) _Sent(response, operation_id: str)`;
  - `_prepare_request(self, session, state, client, deadline) -> _Prepared | RuntimeResult`;
  - `_send(self, session, state, client, prepared, deadline) -> _Sent | RuntimeResult`;
  - `_run_calls(self, session, state, native, calls) -> None`;
  - `_find_tool_result(self, session, state, key) -> dict | None`.
- Test helpers: `DOUBLE_SCHEMA`, `double_dispatcher(seen=None)`, `double_call(call_id="call_1", value=2)`, `RecordingStore` (with `.pending` and `.shapes`, where a shape is `(pending kind, settled_boundary, status)`) and `TODAY_SAVE_SHAPES`.

- [ ] **Step 1: Write the characterization test.** Append this to `tests/test_execution_responses.py`:
```python
DOUBLE_SCHEMA = {"type": "object", "properties": {"value": {"type": "integer"}},
                 "required": ["value"], "additionalProperties": False}

def double_dispatcher(seen=None):
    dispatcher = ToolDispatcher()
    async def double(arguments, operation_id):
        if seen is not None:
            seen.append(operation_id)
        return {"value": arguments["value"] * 2}
    dispatcher.register("double", DOUBLE_SCHEMA, double)
    return dispatcher

def double_call(call_id="call_1", value=2):
    return {"id": "fc_" + call_id, "type": "function_call", "call_id": call_id, "name": "double",
            "arguments": json.dumps({"value": value}), "status": "completed"}

class RecordingStore(SQLiteRuntimeStore):
    """Records every committed save: its pending operation and its shape."""
    def __init__(self, path):
        super().__init__(path)
        self.pending, self.shapes = [], []
    async def save(self, checkpoint):
        await super().save(checkpoint)
        state = checkpoint.native_state
        pending = state.get("pending_operation")
        self.pending.append(pending)
        kind = None if pending is None else "tool" if ":" in pending else "generation"
        self.shapes.append((kind, state.get("settled_boundary"), checkpoint.session.status))

TODAY_SAVE_SHAPES = [  # one tool turn, then a final turn
    (None, True, "ready"), (None, True, "running"),
    ("generation", True, "running"), ("generation", False, "running"), (None, False, "running"),
    ("tool", False, "running"), (None, False, "running"), (None, True, "running"),
    ("generation", True, "running"), ("generation", False, "running"), (None, False, "running"),
    (None, True, "running"), (None, True, "running"), (None, True, "completed")]

async def test_tool_turn_save_sequence_is_pinned(tmp_path):
    requests = []
    client = client_for([response([double_call()]), response([message("4")], response_id="resp_2")],
                        requests)
    store = RecordingStore(tmp_path / "s.db")
    runtime = ResponsesRuntime(store=store, dispatcher=double_dispatcher(), client=client)
    assert (await runtime.start("compute", ModelConfig(model="exact-model"),
                                RuntimeLimits())).output_text == "4"
    assert store.shapes == TODAY_SAVE_SHAPES
    assert [u.rsplit("/", 1)[-1] for u, _ in requests] == [
        "input_tokens", "responses", "input_tokens", "responses"]
    await client.close()
```
- [ ] **Step 2: Record the baseline.** Run `... -m pytest tests/test_execution_responses.py tests/test_execution_context.py tests/test_research_context_policy.py tests/test_society_scaffolding.py tests/test_research_loop_integration.py -q`. It should PASS on the unchanged code; record the count. The rate-limit tests already on main (`test_rate_limit_refusal_resends_the_same_generation`, `test_rate_limit_give_up_releases_the_reservation_at_zero`, `test_interrupting_a_rate_limit_wait_is_definite`, `test_rate_limited_token_count_is_resent`, plus `test_rate_limit_give_up_releases_the_model_reservation`, `test_rate_limit_resends_one_operation_until_giving_up` and `test_stopping_the_team_during_a_rate_limit_wait_releases_the_reservation` in `test_research_loop_integration.py`) pin `_resend_rate_limited` and `_abandon_refused` through the split.
- [ ] **Step 3: Refactor.**
  1. Add `from dataclasses import dataclass` to the imports. Define `_Prepared` and `_Sent` (one-line docstrings) right after `lineage_token_usage` (lines 113–119). Use `kw_only=True`, so later tasks can add defaulted fields in any order; every construction uses keywords.
  2. `_prepare_request(self, session, state, client, deadline)` is lines 754–841, moved verbatim: from `params = dict(session.model.parameters)` through the `output_reservation` assignment. It takes `deadline` because the count already resends through `_resend_rate_limited(partial(client.responses.input_tokens.count, ...), deadline)`.
     - After the count, bind `input_tokens = count.input_tokens` and use `input_tokens` wherever the code used `count.input_tokens`.
     - The context-pressure branch keeps `return handoff`.
     - End with `return _Prepared(params=params, input_tokens=input_tokens, input_reservation=input_reservation, output_reservation=output_reservation, remaining=remaining)`.
  3. `_send` is lines 842–889, moved verbatim: from the second `pre_generation_guard` check through the `response = await _resend_rate_limited(partial(client.responses.create, ...), deadline, operation_id=operation_id, abandon=partial(self._abandon_refused, session, state, operation_id))` call.
     - It reads `prepared.params`, `prepared.input_reservation` and `prepared.output_reservation`.
     - The guard returns `await self._complete_verified(session, state)`.
     - End with `return _Sent(response=response, operation_id=operation_id)`.
  4. `_find_tool_result` replaces lines 1060–1074 (the three lookups of `previous`):
```python
    async def _find_tool_result(self, session, state, key):
        """A committed tool result: active state, then own archives, then inherited ones."""
        found = state.get("tool_results", {}).get(key)
        for archive_id in reversed(state.get("archives", [])) if found is None else ():
            found = (await self.store.load_archive(session.id, archive_id))["tool_results"].get(key)
            if found is not None:
                break
        for ref in reversed(state.get("archive_refs", [])) if found is None else ():
            archive = await self.store.load_archive(ref["session_id"], ref["archive_id"])
            if (found := archive["tool_results"].get(key)) is not None:
                break
        return found
```
  5. `_run_calls` is the `for call in calls:` loop at lines 1048–1127, moved verbatim, with `previous = await self._find_tool_result(session, state, tool_operation)`. Keep `results = state.setdefault("tool_results", {})` on the line before it; the state digest depends on that key.
  6. `_loop` keeps lines 746–753 (`client = self._get_client()`, `while True:`, the guard, the turn cap, `_receive_updates`, `_receive_turn_note`). It then runs `prepared = await self._prepare_request(session, state, client, deadline)` and `sent = await self._send(session, state, client, prepared, deadline)`, returning either one if it is a `RuntimeResult`, and sets `response, operation_id = sent.response, sent.operation_id`. Next come lines 890–1047 unchanged (from `native = response.model_dump(...)` through the terminal `return RuntimeResult(...)`, reading `prepared.input_reservation` and `prepared.output_reservation`), then `await self._run_calls(session, state, native, calls)`, then lines 1129–1134 unchanged.
- [ ] **Step 4: Check the count.** Rerun Step 2 and expect the same count, with no test edited.
- [ ] **Step 5: Commit** (G7): `refactor: split the Responses tool loop into prepare, send and call phases`.

---

### Task 2: `provider_throttled` events and wait totals (#6, telemetry only)

Main already has the rest of #6, so this task neither re-implements nor re-tests it: the resend of a refused count or create, the give-up at the deadline (a definite, retryable `PROVIDER_RATE_LIMITED`), `_abandon_refused` (emit `generation_aborted(reason="rate_limited")`, then clear `pending_operation`) and abandon-on-interrupt. Main's tests `test_rate_limit_give_up_releases_the_reservation_at_zero`, `test_interrupting_a_rate_limit_wait_is_definite` and `test_rate_limited_token_count_is_resent` pin that behaviour. This task adds telemetry only, through an `on_wait` hook on `_resend_rate_limited`.

**Files:**
- Modify `responses.py`: the imports and a logger; `_rate_limit_wait` (45–64); `_resend_rate_limited` (67–103); new header parsing; `_Sent`, `_prepare_request` (the count call), `_send` (the create call) and the `usage` emit.
- Modify `docs/EXECUTION.md:101-105`.
- Test in `tests/test_execution_responses.py`.

**Interfaces:**
- Consumes `_prepare_request`, `_send` and `_Sent` from Task 1. Also consumes main's `_resend_rate_limited`, `_abandon_refused`, `rate_limited_client(replies, requests, counts=())` and `refusal(code)`.
- Produces:
  - `_rate_limit_wait(error, fallback) -> tuple[float, str] | None`, where the source is `retry-after-ms`, `retry-after` or `backoff`;
  - `_resend_rate_limited(send, deadline, *, operation_id=None, abandon=None, on_wait=None)`. When given, `on_wait(attempt, seconds, source, error)` performs each wait in place of `asyncio.sleep(seconds)`, under the same abandon-on-interrupt guard. Task 7 re-queues through it;
  - `_duration_seconds(value) -> float | None`;
  - `_rate_limit_headers(error) -> dict`;
  - `ResponsesRuntime._emit_telemetry(kind, session, operation_id=None, **payload)`;
  - `ResponsesRuntime._throttle_hook(session, operation_id, waits) -> on_wait`. The hook appends each wait to `waits`, emits `provider_throttled`, then sleeps. The hook performs the wait (default `asyncio.sleep`) rather than running before a fixed sleep, so Task 7 can replace the sleep with a governor re-queue without waiting twice;
  - `_Sent.rate_limit_waits: int = 0` and `_Sent.rate_limit_wait_seconds: float = 0.0`, the create's waits;
  - the event `provider_throttled`, with `attempt`, `wait_seconds`, `wait_source` and optionally `limit_tokens`, `remaining_tokens`, `limit_requests`, `remaining_requests`, `reset_tokens_seconds` and `reset_requests_seconds`. A create's event carries the generation's operation id. A count's event carries `operation_id=None`, and its waits stay out of the totals, because a count has no operation and no reservation (F11);
  - `usage.rate_limit_waits` and `usage.rate_limit_wait_seconds`.

- [ ] **Step 1: Write the failing tests.**
```python
async def test_rate_limit_wait_emits_provider_throttled_event(tmp_path):
    events = []
    async def emit(event):
        events.append(event)
    leaky = {"error": {"message": "Rate limit reached for org-SECRET123", "type": "tokens",
                       "param": None, "code": "rate_limit_exceeded"}}
    headers = {"retry-after-ms": "5", "x-ratelimit-limit-tokens": "2000000",
               "x-ratelimit-remaining-tokens": "0", "x-ratelimit-reset-tokens": "6m0s",
               "x-ratelimit-reset-requests": "20ms"}
    client = rate_limited_client([(429, leaky, headers),
                                  (429, refusal("rate_limit_exceeded"), {"retry-after": "0.01"}),
                                  (200, response([message("done")]), {})], [])
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client, event_sink=emit)
    await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    throttled = [e for e in events if e.kind == "provider_throttled"]
    assert throttled[0].payload == {"attempt": 1, "wait_seconds": 0.005, "wait_source": "retry-after-ms",
                                    "limit_tokens": 2000000, "remaining_tokens": 0,
                                    "reset_tokens_seconds": 360.0, "reset_requests_seconds": 0.02}
    assert throttled[1].payload == {"attempt": 2, "wait_seconds": 0.01, "wait_source": "retry-after"}
    assert {e.operation_id for e in throttled} == {events[0].operation_id}
    assert "SECRET" not in json.dumps([e.payload for e in events])
    usage = next(e for e in events if e.kind == "usage").payload
    assert (usage["rate_limit_waits"], usage["rate_limit_wait_seconds"]) == (2, 0.015)
    await client.close()

async def test_rate_limited_count_is_announced_but_not_totalled(tmp_path):
    events = []
    async def emit(event):
        events.append(event)
    client = rate_limited_client([(200, response([message("done")]), {})], [],
                                 counts=[(429, refusal("rate_limit_exceeded"), {"retry-after-ms": "5"})])
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client, event_sink=emit)
    await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    # A count has no operation and no reservation: its wait is announced, not added to usage (F11).
    assert [(e.operation_id, e.payload) for e in events if e.kind == "provider_throttled"] == [
        (None, {"attempt": 1, "wait_seconds": 0.005, "wait_source": "retry-after-ms"})]
    usage = next(e for e in events if e.kind == "usage").payload
    assert (usage["rate_limit_waits"], usage["rate_limit_wait_seconds"]) == (0, 0.0)
    await client.close()
```
  Test 1 is the plan's original test, unchanged. The second test covers F11's count rule; it does not overlap main's `test_rate_limited_token_count_is_resent`, which checks only the resent URLs. Do not add a give-up or interrupt test; main's tests cover both. One of them changes, because a wait now announces itself first. In `test_interrupting_a_rate_limit_wait_is_definite`, the last assertion becomes `assert events == ["generation_started", "provider_throttled", "generation_aborted"]`. `test_rate_limit_give_up_releases_the_reservation_at_zero` stays unmodified: its only refusal gives up without waiting, so it emits no `provider_throttled`.
- [ ] **Step 2: Run the new test.** `... -m pytest tests/test_execution_responses.py -q -k "throttled or totalled or interrupting_a_rate_limit"` should FAIL.
- [ ] **Step 3: Implement.**
  1. Add `import logging` and `log = logging.getLogger(__name__)`. `_rate_limit_wait` returns `(min(hinted, MAX_RATE_LIMIT_WAIT_SECONDS), name)` for a header hint, and otherwise `(min(fallback, MAX_RATE_LIMIT_WAIT_SECONDS), "backoff")`. Update its return annotation and docstring to match. Add:
```python
_DURATION_PART = re.compile(r"([0-9]+(?:\.[0-9]+)?)(ms|h|m|s)")

_DURATION_SCALE = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}

_RATE_LIMIT_COUNTS = (("x-ratelimit-limit-tokens", "limit_tokens"),
                      ("x-ratelimit-remaining-tokens", "remaining_tokens"),
                      ("x-ratelimit-limit-requests", "limit_requests"),
                      ("x-ratelimit-remaining-requests", "remaining_requests"))

_RATE_LIMIT_RESETS = (("x-ratelimit-reset-tokens", "reset_tokens_seconds"),
                      ("x-ratelimit-reset-requests", "reset_requests_seconds"))

def _duration_seconds(value: Any) -> float | None:
    """Seconds in a provider duration such as ``6m0s`` or ``20ms``; None if malformed."""
    if not isinstance(value, str) or not 0 < len(value) <= 32:
        return None
    parts = _DURATION_PART.findall(value)
    if not parts or "".join(number + unit for number, unit in parts) != value:
        return None
    return round(sum(float(number) * _DURATION_SCALE[unit] for number, unit in parts), 3)

def _rate_limit_headers(error: Exception) -> dict[str, int | float]:
    """Bounded numbers from rate-limit headers; never the message, which names the org."""
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    fields: dict[str, int | float] = {}
    for header, name in _RATE_LIMIT_COUNTS:
        if isinstance(value := headers.get(header), str) and re.fullmatch(r"[0-9]{1,15}", value):
            fields[name] = int(value)
    for header, name in _RATE_LIMIT_RESETS:
        if (seconds := _duration_seconds(headers.get(header))) is not None:
            fields[name] = seconds
    return fields
```
  2. `_resend_rate_limited` becomes the version below. Only three things change: the `on_wait` parameter, the attempt count and the wait line. The give-up, `abandon` and the interrupt guard stay as they are on main.
```python
async def _resend_rate_limited(
    send: Callable[[], Awaitable[Any]],
    deadline: float,
    *,
    operation_id: str | None = None,
    abandon: Callable[[], Awaitable[None]] | None = None,
    on_wait: Callable[[int, float, str, Exception], Awaitable[None]] | None = None,
) -> Any:
    """Await `send`, resending it while the provider refuses it for rate limiting.

    A refusal did no work, so nothing is in flight while waiting. When the next wait would
    pass the deadline, or the wait is interrupted, `abandon` runs before the error
    propagates; giving up raises a definite, retryable PROVIDER_RATE_LIMITED. When given,
    `on_wait(attempt, seconds, source, error)` performs each wait instead of `asyncio.sleep`,
    under the same interrupt guard, so an error it raises also abandons the request.
    """
    backoff, attempt = 1.0, 0
    while True:
        try:
            return await send()
        except Exception as error:
            hint = _rate_limit_wait(error, backoff)
            if hint is None:
                raise
            wait, source = hint
            if asyncio.get_running_loop().time() + wait >= deadline:
                if abandon is not None:
                    await abandon()
                raise ExecutionError(
                    "PROVIDER_RATE_LIMITED",
                    "Provider rate limit refused the request until the wall-clock limit",
                    operation_id=operation_id,
                    retryable=True,
                ) from error
            attempt, refused = attempt + 1, error  # `error` is unbound after this block
        try:
            await (on_wait(attempt, wait, source, refused) if on_wait else asyncio.sleep(wait))
        except BaseException:
            if abandon is not None:
                await abandon()
            raise
        backoff *= 2
```
  3. Add `rate_limit_waits: int = 0` and `rate_limit_wait_seconds: float = 0.0` to `_Sent`. Add two methods:
```python
    async def _emit_telemetry(self, kind, session, operation_id=None, **payload) -> None:
        """Observability only: a sink failure is logged and never turns a request that was
        certainly not sent into an uncertain one."""
        try:
            await self._emit(kind, session, operation_id, **payload)
        except Exception:
            log.warning("runtime_telemetry_failed", extra={
                "event_kind": kind, "session_id": session.id, "operation_id": operation_id})

    def _throttle_hook(self, session, operation_id, waits):
        """The on_wait hook of one provider call: record and announce each rate-limit wait,
        then wait it out."""
        async def on_wait(attempt: int, wait: float, source: str, error: Exception) -> None:
            waits.append(wait)
            await self._emit_telemetry("provider_throttled", session, operation_id, attempt=attempt,
                                       wait_seconds=round(wait, 3), wait_source=source,
                                       **_rate_limit_headers(error))
            await asyncio.sleep(wait)
        return on_wait
```
  4. In `_prepare_request`, pass `on_wait=self._throttle_hook(session, None, [])` to the count's `_resend_rate_limited` call (main's `:759-769`). Its waits are announced with no operation id and are discarded, not totalled (F11).
  5. In `_send`, set `waits: list[float] = []` before the create, and pass `on_wait=self._throttle_hook(session, operation_id, waits)` to its `_resend_rate_limited` call (main's `:873-889`). Keep `operation_id=` and `abandon=partial(self._abandon_refused, session, state, operation_id)` exactly as on main. Return `_Sent(response=response, operation_id=operation_id, rate_limit_waits=len(waits), rate_limit_wait_seconds=round(sum(waits), 3))`.
  6. Add `rate_limit_waits=sent.rate_limit_waits, rate_limit_wait_seconds=sent.rate_limit_wait_seconds` to `usage`.
  7. Add to `docs/EXECUTION.md`, after the event-sink paragraph at lines 101–105:
     - A 429 with code `rate_limit_exceeded` did no work, whether it refused the count or the create, so the same request is resent. The wait follows the provider's hint (`retry-after-ms`, then `retry-after`) or a doubling backoff, capped at 30 s per wait.
     - `provider_throttled` is emitted once per wait. It carries the attempt, the wait, its source and bounded header numbers, never the error text. A sink failure is logged and ignored. A create's event carries the generation's operation id. A count's event has none.
     - `usage` reports the create's wait totals. A count has no operation or reservation, so its waits appear only as events.
     - The runtime gives up when the next wait would outlast the deadline or when the wait is interrupted. The give-up is definite: `generation_aborted(reason="rate_limited")` releases the reservation at zero, and only then is the marker cleared. The session fails with retryable `PROVIDER_RATE_LIMITED`, and the executor blocks the task for an operator to resume.
     - Start a "Stored shape changes (G3 infrastructure, all experiments)" list. Say that G1 covers the bytes the model sees and the pinned freeze tests (F7), so these changes reach legacy experiments too. Its first entries are the `usage` wait totals and the `provider_throttled` events. Later tasks add their own lines.
- [ ] **Step 4: Run the suite.** `... -m pytest tests/test_execution_responses.py tests/test_research_loop_integration.py -q` should PASS. All of main's rate-limit tests except the one changed in Step 1 pass unmodified.
- [ ] **Step 5: Commit** (G7): `feat: report provider throttling as events and usage wait totals`.

---

### Task 3: Slim stored responses, deduplicate tool results, enable WAL and reuse saved checkpoints (#10a, 10b, 10g, 10h)

**Files:**
- Modify `responses.py`: new `STORED_RESPONSE_FIELDS` and `_response_record`, plus `_save` (287–288), `_receive_updates` (the `update_source` call at 314), `_maybe_handoff` (1142–1190) and its callers, and the `tool_results` write.
- Modify `storage.py:193-196`, `docs/EXECUTION.md:94` and `docs/OPERATIONS.md` (near line 93).
- Tests in `tests/test_execution_responses.py` and a new `tests/test_sqlite_durability.py`.

**Interfaces (produced):**
- `STORED_RESPONSE_FIELDS`.
- `_response_record(native) -> dict`, which adds `request_echo_sha256`.
- `_save(...) -> RuntimeCheckpoint`, which also records `self._saved[session.id]`.
- `_maybe_handoff(..., checkpoint: RuntimeCheckpoint | None = None)`.
- `tool_results` entries hold `visible_output` only when it differs from `result`.

- [ ] **Step 1: Write the failing tests.** Import `STORED_RESPONSE_FIELDS` from `physharness.execution.responses`.
```python
async def test_stored_response_omits_request_echo_and_duplicate_output(tmp_path):
    tools = [{"type": "function", "name": "double", "parameters": {"type": "object"}, "strict": True}]
    first = {**response([double_call()]), "tools": tools, "instructions": "echoed", "tool_choice": "auto"}
    client = client_for([first, {**response([message("4")], response_id="resp_2"), "tools": tools * 2}], [])
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"),
                               dispatcher=double_dispatcher(), client=client)
    result = await runtime.start("compute", ModelConfig(model="exact-model"), RuntimeLimits())
    state = (await runtime.checkpoint(result.session.id)).native_state
    stored = state["responses"]
    assert all(set(r) <= STORED_RESPONSE_FIELDS | {"request_echo_sha256"} for r in stored)
    assert stored[0]["request_echo_sha256"] != stored[1]["request_echo_sha256"]
    assert stored[0]["output"] == [double_call()]
    assert set(state["tool_results"][f"{result.session.id}:call_1"]) == {"identity", "result"}
    await client.close()

async def test_hooks_reuse_saved_checkpoint(tmp_path, monkeypatch):
    from physharness.execution import RuntimeCheckpoint
    builds, hooked, original = [], [], RuntimeCheckpoint.build.__func__
    monkeypatch.setattr(RuntimeCheckpoint, "build", classmethod(
        lambda cls, session, state: builds.append(1) or original(cls, session, state)))
    async def boundary(checkpoint):
        hooked.append(checkpoint.state_digest)
    async def source(checkpoint):
        return {"delivery_id": None, "items": []}
    async def ack(delivery_id):
        raise AssertionError("nothing to acknowledge")
    client = client_for([response([double_call()]), response([message("4")], response_id="resp_2")], [])
    store = RecordingStore(tmp_path / "s.db")
    runtime = ResponsesRuntime(store=store, dispatcher=double_dispatcher(), client=client,
                               boundary_hook=boundary, update_source=source, update_ack=ack)
    await runtime.start("compute", ModelConfig(model="exact-model"), RuntimeLimits())
    assert len(hooked) == 2 and len(builds) == len(store.shapes)
    await client.close()
```
`tests/test_sqlite_durability.py`:
```python
"""The canonical SQLite database commits through a write-ahead log with full fsync."""
from sqlalchemy import text
from physharness.storage import Database

def test_sqlite_database_uses_wal_and_full_sync(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'records.db'}")
    with db.engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert connection.execute(text("PRAGMA synchronous")).scalar() == 2
```
- [ ] **Step 2: Run the new tests.** `... -m pytest tests/test_execution_responses.py tests/test_sqlite_durability.py -q` should FAIL.
- [ ] **Step 3: Implement.**
  1. **10a.** Add:
```python
# Response fields a checkpoint keeps. The rest is the provider's echo of the request (tools,
# instructions, settings): kept as a digest; the session record holds the tool digest.
STORED_RESPONSE_FIELDS = frozenset({"id", "object", "created_at", "completed_at", "model", "status",
                                    "output", "usage", "incomplete_details", "error", "service_tier"})

def _response_record(native: dict[str, Any]) -> dict[str, Any]:
    """The billing- and recovery-relevant fields plus a digest of the request echo."""
    record = {key: value for key, value in native.items() if key in STORED_RESPONSE_FIELDS}
    record["request_echo_sha256"] = digest(
        {key: value for key, value in native.items() if key not in STORED_RESPONSE_FIELDS})
    return record
```
     The normal path appends `_response_record(native)`. The `PROVIDER_MODEL_MISMATCH` branch keeps appending the full `native` as evidence. Every other use keeps `native`, which shares the same `output` list.
  2. **10b.** Change the write in `_run_calls`:
     - `entry = {"identity": identity, "result": result}`;
     - `if visible_output is not result: entry["visible_output"] = visible_output`;
     - `results[tool_operation] = entry`.
  3. **10g.** In `configure_sqlite`, after the two existing pragmas, add `connection.execute("PRAGMA journal_mode=WAL")` and `connection.execute("PRAGMA synchronous=FULL")`. Comment: `# WAL fsyncs one log per commit; FULL keeps a committed write-ahead marker across power loss.`
  4. **10h.**
     - In `__init__`, set `self._saved: dict[str, RuntimeCheckpoint] = {}`. `_save` builds the checkpoint, stores it, sets `self._saved[session.id] = checkpoint` and returns it.
     - Line 314 (`batch = await self.update_source(RuntimeCheckpoint.build(session, state))`) becomes `saved = self._saved.get(session.id)` followed by `batch = await self.update_source(saved if saved is not None else RuntimeCheckpoint.build(session, state))`. Only the top of `_loop` calls `_receive_updates`, right after `_run`'s save, save F or the compaction-only save.
     - `_maybe_handoff` gains `checkpoint=None` and calls `self.boundary_hook(checkpoint if checkpoint is not None else RuntimeCheckpoint.build(session, state))`. Its handed-off branch uses `terminal = await self._save(session, state)`.
     - Every call that directly follows a save passes `checkpoint=` (the value returned by `_save`): save F, the compaction-only branch (main's 1008–1011), the terminal branch (main's 1029–1033), context pressure, and `recover_compaction` (595–598) when it saved. Tasks 1–2 moved the `_loop` lines; find them by content.
  5. **Docs.**
     - `docs/EXECUTION.md`: a stored response keeps `STORED_RESPONSE_FIELDS` plus `request_echo_sha256`, and old full echoes still load. `visible_output` is stored only when a signal changed it. `update_source` and `boundary_hook` receive the checkpoint that was just saved. Add to the stored-shape list (F7): stored responses keep only `STORED_RESPONSE_FIELDS` plus `request_echo_sha256`, and a `tool_results` entry omits an unchanged `visible_output`.
     - `docs/OPERATIONS.md`: SQLite runs in WAL mode, which creates `-wal` and `-shm` files and needs a local filesystem. Back up with the SQLite backup API, or run `PRAGMA wal_checkpoint(TRUNCATE)` first; never copy `harness.db` alone.
- [ ] **Step 4: Run the tests.** `... -m pytest tests/test_execution_responses.py tests/test_execution_context.py tests/test_research_context_policy.py tests/test_native_checkpoint_chunks.py tests/test_session_events.py tests/test_sqlite_durability.py tests/test_society_tools.py -q` should PASS.
- [ ] **Step 5: Commit** (G7): `perf: slim stored responses, drop duplicate tool outputs, reuse saved checkpoints, enable WAL`.

---

### Task 4: Estimate the input instead of counting it every turn (#9, R3)

**Files:**
- Modify `responses.py`: import `CONTEXT_MARGIN` from `.context_policy`; add `BOUND_MARGIN_FLOOR`, `BOUND_MARGIN_PERCENT`, `_request_elements`, `_input_bound` and `_provider_rejection`; change `__init__`, `_abandon_refused` (290–299, a `reason=` parameter), `_run` (its `finally`), `_Prepared`, `_prepare_request`, `_send` (the create 400 path) and `_loop` (the baseline at save B).
- Modify one test's limits in `tests/test_society_scaffolding.py`.
- Modify `docs/EXECUTION.md:86-90,299`.
- Tests in `tests/test_execution_responses.py` and `tests/test_execution_context.py`.

**Interfaces:**
- Consumes Tasks 1–2, and main's `_resend_rate_limited` and `_abandon_refused`.
- Produces:
  - `_request_elements(params, tools, items) -> list[tuple[str, int]]`: the P1 positional elements as (sha256, UTF-8 size) of their canonical JSON. They are the instructions (null when absent), the tools array, then each input item;
  - `_input_bound(previous, elements, epoch) -> int | None`: the margin-inclusive P1 bound that Tasks 6 and 7 use, or None to count. The bound is `B + max(BOUND_MARGIN_FLOOR, ceil(BOUND_MARGIN_PERCENT% of B))`, with `BOUND_MARGIN_FLOOR = 2_048` and `BOUND_MARGIN_PERCENT = 2`;
  - `ResponsesRuntime._last_request: dict[str, dict]`, mapping a session id to `{"epoch", "digests", "tokens"}` for its previous request. It lives in memory only and is dropped when `_run` exits (F2), so native state gains no key;
  - `_provider_rejection(error) -> (code, provider_code, provider_param)`;
  - `_abandon_refused(session, state, operation_id, *, reason="rate_limited")`. It still emits `generation_aborted` first and clears `pending_operation` second (F1);
  - `_Prepared.counted: bool` and `_Prepared.digests: tuple[str, ...]`. `_prepare_request` keeps Task 1's signature;
  - the staticmethod `ResponsesRuntime._near_limit(session, state, tokens) -> bool`;
  - `generation_started.input_tokens_estimate` and `generation_started.input_tokens_counted`;
  - `preflight_error.stage == "create"`;
  - the test helpers `observe_dispatcher(result=None)`, `COMPACTING` and `WIDE` in `tests/test_execution_context.py`.

- [ ] **Step 1: Write the failing tests.** Import `canonical_json` from `physharness.domain`.

In `tests/test_execution_responses.py`:
```python
async def test_count_runs_once_per_run_then_estimates(tmp_path):
    requests, events = [], []
    async def emit(event):
        events.append(event)
    client = client_for([response([double_call("c1")]), response([double_call("c2")], response_id="r2"),
                         response([message("8")], response_id="r3")], requests)
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"),
                               dispatcher=double_dispatcher(), client=client, event_sink=emit)
    await runtime.start("compute", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None))
    assert [u.rsplit("/", 1)[-1] for u, _ in requests] == ["input_tokens"] + ["responses"] * 3
    creates = [p for u, p in requests if u.endswith("/responses")]
    started = [e.payload for e in events if e.kind == "generation_started"]
    assert [p["input_tokens_counted"] for p in started] == [True, False, False]
    for n in (1, 2):  # instructions and tools are unchanged, so only appended items count (P1)
        appended = creates[n]["input"][len(creates[n - 1]["input"]):]
        assert started[n]["input_tokens_estimate"] == 10 + sum(
            len(canonical_json(item).encode("utf-8")) for item in appended) + 2048  # margin floor
    await client.close()

def test_input_bound_counts_changed_elements_and_credits_nothing_removed():
    from physharness.execution.responses import _input_bound, _request_elements
    def size(element):
        return len(canonical_json(element).encode("utf-8"))
    tools, items = [{"name": "a"}], [{"n": 1}, {"n": 2}, {"n": 3}]
    before = _request_elements({}, tools, items)
    previous = {"epoch": 0, "digests": [sha for sha, _ in before], "tokens": 100}
    replaced = [{"n": 1}, {"elided": True}, {"n": 3}, {"n": 4}]  # an elided item and a new one
    assert _input_bound(previous, _request_elements({}, tools, replaced), 0) == (
        100 + size({"elided": True}) + size({"n": 4}) + 2048)
    wider = [*tools, {"name": "recall_output"}]  # new instructions and tools; two items removed
    assert _input_bound(previous, _request_elements({"instructions": "new"}, wider, items[:1]), 0) == (
        100 + size("new") + size(wider) + 2048)
    assert _input_bound(previous, before, 1) is None  # a compaction epoch voids the bound
    assert _input_bound({**previous, "tokens": 200_000}, before, 0) == 204_000  # 2% above the floor

async def test_cumulative_budget_near_limit_counts_exactly(tmp_path):
    requests = []
    client = client_for([response([double_call()]), response([message("4")], response_id="r2")], requests)
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"),
                               dispatcher=double_dispatcher(), client=client)
    # 12,400 - 15 used - a ~2,300-token estimate (2,048 of it margin) leaves less
    # than max_output + 8,192.
    await runtime.start("compute", ModelConfig(model="exact-model"),
                        RuntimeLimits(max_total_tokens=12_400, max_output_tokens=4_096))
    assert [u.rsplit("/", 1)[-1] for u, _ in requests] == ["input_tokens", "responses"] * 2
    await client.close()
```
Also change the URL list in `test_tool_turn_save_sequence_is_pinned` to `["input_tokens", "responses", "responses"]`. The shapes stay the same.

In `tests/test_execution_context.py`:
```python
def observe_dispatcher(result=None):
    dispatcher = ToolDispatcher()
    async def observe(arguments, operation_id):
        return result if result is not None else {"seen": True}
    dispatcher.register("observe", {"type": "object", "properties": {}, "required": [],
                                    "additionalProperties": False}, observe)
    return dispatcher

COMPACTING = {"context_management": [{"type": "compaction", "compact_threshold": 40_000}]}

WIDE = RuntimeLimits(max_context_tokens=64_000, max_output_tokens=1_000, max_total_tokens=None)

async def test_compaction_epoch_invalidates_the_estimate(tmp_path):
    requests = []
    client = sdk_client([response([compaction_item("one"), call_item("a")], "r1"),
                         response([call_item("b")], "r2"), response([text_item("done")], "r3")], requests)
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "sessions.db"), client=client,
                               dispatcher=observe_dispatcher())
    await runtime.start("work", ModelConfig(model="exact-model", parameters=COMPACTING), WIDE)
    assert [p.rsplit("/", 1)[-1] for p, _ in requests] == [
        "input_tokens", "responses", "input_tokens", "responses", "responses"]
    await client.close()

async def test_create_400_is_pre_generation_not_uncertain(tmp_path):
    events = []
    def handle(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        return httpx.Response(400, json={"error": {
            "message": "private schema text", "type": "invalid_request_error",
            "param": "tools[0].parameters", "code": "invalid_function_parameters"}})
    async def emit(event):
        events.append(event)
    client = AsyncOpenAI(api_key="test-only", max_retries=0,
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    with pytest.raises(ExecutionError) as error:
        await ResponsesRuntime(store=store, client=client, event_sink=emit).start(
            "work", ModelConfig(model="exact-model"), RuntimeLimits())
    assert error.value.code == "PROVIDER_TOOL_SCHEMA_INVALID"
    assert [(e.kind, e.payload.get("reason")) for e in events] == [
        ("generation_started", None), ("generation_aborted", "request_invalid")]
    saved = RuntimeCheckpoint.model_validate_json(
        store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0])
    assert (saved.session.status, saved.native_state["pending_operation"]) == ("failed", None)
    assert saved.native_state["preflight_error"] == {
        "stage": "create", "operation_id": events[0].operation_id,
        "provider_code": "invalid_function_parameters", "provider_param": "tools[0].parameters"}
    assert "private" not in saved.model_dump_json()
    await client.close()
```
- [ ] **Step 2: Run the new tests.** `... -m pytest tests/test_execution_responses.py tests/test_execution_context.py -q -k "count or estimate or input_bound or epoch or create_400 or pinned"` should FAIL.
- [ ] **Step 3: Implement.**
  1. Add the constants and helpers. `hashlib` and `canonical_json` are already imported.
```python
# P1: the input bound's safety margin is max(2,048 tokens, ceil(2% of the bound)).
BOUND_MARGIN_FLOOR = 2_048

BOUND_MARGIN_PERCENT = 2

def _provider_rejection(error: Exception) -> tuple[str, str | None, str | None]:
    """The harness code plus the bounded provider code and parameter of an HTTP 400."""
    provider_code = _safe_provider_field(getattr(error, "code", None), maximum=80)
    provider_param = _safe_provider_field(getattr(error, "param", None), maximum=160)
    schema = provider_code == "invalid_function_parameters" or bool(
        provider_param and provider_param.startswith("tools"))
    return ("PROVIDER_TOOL_SCHEMA_INVALID" if schema else "MODEL_REQUEST_INVALID",
            provider_code, provider_param)

def _request_elements(params: dict[str, Any], tools: list[dict[str, Any]],
                      items: list[Any]) -> list[tuple[str, int]]:
    """P1's positional request elements as (sha256, UTF-8 size) of their canonical JSON: the
    instructions (null when absent), the tools array, then each input item."""
    elements = []
    for element in (params.get("instructions"), tools, *items):
        raw = canonical_json(element).encode("utf-8")
        elements.append((hashlib.sha256(raw).hexdigest(), len(raw)))
    return elements

def _input_bound(previous: dict[str, Any] | None, elements: list[tuple[str, int]],
                 epoch: int) -> int | None:
    """A sound upper bound on a request's input tokens, margin included (G4, P1), or None to count.
    ``previous`` is this session's last request in the current ``_run``: its element digests, its
    compaction epoch and the input tokens the provider billed for it. Each element that is not
    byte-identical to the element at the same position adds at most its canonical UTF-8 size (a
    byte-level tokenizer emits no more tokens than bytes); removed content earns no credit. A
    compaction rewrites the input (a new epoch), which voids the bound.
    """
    if previous is None or previous["epoch"] != epoch:
        return None
    old = previous["digests"]
    raw = previous["tokens"] + sum(size for index, (sha, size) in enumerate(elements)
                                   if index >= len(old) or old[index] != sha)
    return raw + max(BOUND_MARGIN_FLOOR, (raw * BOUND_MARGIN_PERCENT + 99) // 100)
```
  2. Add `counted: bool` and `digests: tuple[str, ...]` to `_Prepared` (keyword-only, so field order does not matter). Add a `@staticmethod _near_limit(session, state, tokens) -> bool` (docstring: "Whether an estimate is close enough to a limit that only an exact count may decide."). It returns True if `max_context_tokens` is set and `tokens + max_output_tokens > max_context_tokens - CONTEXT_MARGIN`. It also returns True if `max_total_tokens` is set and `max_total_tokens - used - tokens < max_output_tokens + CONTEXT_MARGIN`, where `used` is the two `cumulative_*_offset` values plus the session's input and output tokens. Otherwise it returns False.
  3. In `__init__`, set `self._last_request: dict[str, dict[str, Any]] = {}`. In `_run`'s `finally`, next to `self._active.pop(session.id, None)`, add `self._last_request.pop(session.id, None)`. This drop is what makes the first request of every `_run` count exactly (R3), and a native wake is a new `_run` (F9). No `first_request` flag is needed.
  4. In `_prepare_request`:
     - Right after `params`, set `tools = self.dispatcher.definitions` and use it for the count's `tools=`. Then set `elements = _request_elements(params, tools, state["input"])` and `bound = _input_bound(self._last_request.get(session.id), elements, state.get("active_input_epoch", 0))`.
     - If `bound is None or self._near_limit(session, state, bound)`, run the existing count block (main's `:758-795`). A count give-up raises an `ExecutionError` with no `status_code`, so the 400 handler re-raises it as today. The 400 handler starts with `code, provider_code, provider_param = _provider_rejection(exc)`. Set `input_tokens, counted = count.input_tokens, True`.
     - Otherwise set `input_tokens, counted = bound, False`. From here on, every use of `input_tokens` is the exact count or the margin-inclusive bound, never the raw bound: `remaining`, the context-pressure check, the reservation and, in Task 7, admission (F2).
     - Pass `counted=counted, digests=tuple(sha for sha, _ in elements)` to `_Prepared`.
  5. In `_loop`, just before `state["input"].extend(native["output"])` (save B, main's `:917`), record the baseline: `self._last_request[session.id] = {"epoch": state.get("active_input_epoch", 0), "digests": prepared.digests, "tokens": response.usage.input_tokens}`.
  6. `_abandon_refused` gains a keyword `reason: str = "rate_limited"` and emits `generation_aborted` with `reason=reason`. Keep its body order: emit first, then `state["pending_operation"] = None` (F1). Main's `abandon=partial(self._abandon_refused, session, state, operation_id)` keeps the default.
  7. In `_send`, add `input_tokens_estimate=prepared.input_tokens, input_tokens_counted=prepared.counted` to `generation_started`. Non-429 errors escape `_resend_rate_limited`, so wrap the create call (main's `:873-889`; there is no inline resend loop any more). This is R3: a refused request did no work, so it is definite and its reservation is released at zero.
```python
        try:
            response = await _resend_rate_limited(...)  # Task 2's call, arguments as they are
        except Exception as error:
            if getattr(error, "status_code", None) != 400:
                raise
            code, provider_code, provider_param = _provider_rejection(error)
            state["preflight_error"] = {"stage": "create", "operation_id": operation_id,
                                        "provider_code": provider_code, "provider_param": provider_param}
            # Emit, then clear, as for a rate-limit give-up: a failed release stays uncertain.
            await self._abandon_refused(session, state, operation_id, reason="request_invalid")
            raise ExecutionError(code, "Provider rejected the model request before generation",
                                 operation_id=operation_id) from error
```
     Do not write your own clear-and-emit block here.
  8. In `test_turn_note_not_repeated_after_resume_at_same_boundary` (`tests/test_society_scaffolding.py`), use `RuntimeLimits(max_total_tokens=12_400)` and add the comment `# Near the cumulative guard every request is counted, so count 2 still fails.` The assertions do not change.
  9. `docs/EXECUTION.md:86-88`:
     - The count runs on the first request of every start, continuation, resume or handoff (a native wake included, F9). It also runs within 8,192 tokens of the window or of the cumulative guard.
     - Otherwise the input is bounded without a count. The bound is the last billed input, plus the canonical UTF-8 bytes of every request element that differs from the element at the same position in the previous request, plus `max(2,048, 2%)`. The elements are the instructions, the tools array and each input item, and removed content earns no credit. The previous request's element digests stay in runtime memory for the current `_run` only. A compaction voids the bound.
     - A 400 from `create` is recorded as `preflight_error` (stage `create`). `generation_aborted(reason="request_invalid")` then releases the reservation, and the session is never left uncertain.
     - At line 299, change "awaiting input-token preflight" to "its first provider call".
     - Add to the stored-shape list (F7): `generation_started.input_tokens_estimate` and `input_tokens_counted`, and `preflight_error.stage == "create"`.
- [ ] **Step 4: Run the tests.** `... -m pytest tests/test_execution_responses.py tests/test_execution_context.py tests/test_research_context_policy.py tests/test_society_scaffolding.py tests/test_controller_continuation.py tests/test_joined_delegation.py tests/test_network_runtime.py tests/test_society_tools.py -q` should PASS.
- [ ] **Step 5: Commit** (G7): `perf: count input tokens only on first and near-limit requests; a create 400 is not uncertain`.

---

### Task 5: Price cached input (#4a, R8)

**Files:**
- Modify `orchestration/pricing.py` (the whole file).
- Modify `responses.py`: add `_cached_input_tokens` and extend the `usage` emit.
- Modify `research_worker.py:1289,1339`, `docs/FIRST_LIVE_RUN.md:108-111` and `docs/EXECUTION.md:106-110`.
- Tests in `tests/test_orchestration.py` and `tests/test_execution_responses.py`.

**Interfaces (produced):**
- `ModelPrice.cached_input_usd_per_million: Decimal | None`.
- `ModelPrice.cost(input_tokens, output_tokens, cached_input_tokens=0)`.
- `usage.cached_input_tokens`.
- Test helpers in `tests/test_orchestration.py`: `PRICES`, `started_task(lab, experiment=None) -> (service, actor, experiment, task)` and `UsageRuntime` (class attribute `usage`). Tasks 7 and 11 use them.

- [ ] **Step 1: Write the failing tests.** Add `from decimal import Decimal` to `tests/test_orchestration.py`:
```python
PRICES = {"explicit-test-model": {"input_usd_per_million": "1", "output_usd_per_million": "2"}}

def started_task(lab, experiment=None):
    """A started experiment with one root task."""
    from physharness.domain import BranchCreate, TaskCreate
    service, actor, _ = lab
    experiment = experiment or setup_experiment(lab)[0]
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(experiment["id"], BranchCreate(title="B", objective="Explore"),
                                   actor, "branch")
    task = service.create_task(TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task")
    return service, actor, experiment, task

class UsageRuntime:
    """Emits one reserved generation with the class's usage payload, then completes."""
    usage = {"input_tokens": 10, "output_tokens": 5}
    def __init__(self, store, dispatcher, event_sink):
        self.store, self.event_sink = store, event_sink
    async def start(self, prompt, model, limits):
        from physharness.execution import RuntimeCheckpoint, RuntimeEvent, RuntimeResult, RuntimeSession
        session = RuntimeSession(runtime="responses", model=model, limits=limits)
        await self.store.save(RuntimeCheckpoint.build(session, {"source": "usage fixture"}))
        for kind, payload in (("generation_started", {"input_tokens_reserved": 10,
                                                      "output_tokens_reserved": 20}), ("usage", self.usage)):
            await self.event_sink(RuntimeEvent(kind=kind, session_id=session.id,
                                               operation_id="usage-call", payload=payload))
        session.status = "completed"
        await self.store.save(RuntimeCheckpoint.build(session, {"result": "Unresolved"}))
        return RuntimeResult(session=session, output_text="No proof; remaining assumptions need review.")

def price_provenance(service, actor):
    return [a["provenance"]["price"] for a in service.list_records("artifact", actor)
            if a["artifact_kind"] == "runtime_event"]

def test_cached_input_rate_is_optional_bounded_and_exact():
    plain = ModelPrice(input_usd_per_million="2.50", output_usd_per_million="10", source="s1")
    assert plain.cost(1000, 10, 900) == plain.cost(1000, 10)
    assert plain.model_dump(mode="json", exclude_none=True) == {
        "input_usd_per_million": "2.50", "output_usd_per_million": "10", "source": "s1"}
    cached = ModelPrice(input_usd_per_million="2.50", output_usd_per_million="10",
                        cached_input_usd_per_million="0.25")
    assert cached.cost(1000, 10, 900) == Decimal("0.000575")  # 100·2.50 + 900·0.25 + 10·10
    with pytest.raises(ValueError):
        ModelPrice(input_usd_per_million="1", output_usd_per_million="1", cached_input_usd_per_million="2")
    for bad in (11, -1):
        with pytest.raises(ValueError):
            plain.cost(10, 1, bad)

@pytest.mark.asyncio
async def test_worker_settles_cached_input_at_the_cached_rate(lab):
    from physharness.orchestration.research_worker import ResearchTaskExecutor
    class CachedUsage(UsageRuntime):
        usage = {"input_tokens": 10, "output_tokens": 5, "cached_input_tokens": 8}
    service, actor, experiment, task = started_task(lab)
    prices = {"explicit-test-model": {**PRICES["explicit-test-model"], "cached_input_usd_per_million": "0.1"}}
    await ResearchTaskExecutor(service, prices=prices, runtime_factory=CachedUsage).execute(
        task["id"], actor.project_id)
    ledger = service.ledger(experiment["id"], actor)
    assert ledger["spent_cost_usd"] == "0.000013"  # (2·1 + 8·0.1 + 5·2)/1e6, rounded up
    assert (ledger["tokens_spent"], ledger["tokens_reserved"]) == (15, 0)
    assert all(p["cached_input_usd_per_million"] == "0.1" for p in price_provenance(service, actor))
```
In `tests/test_execution_responses.py`:
```python
@pytest.mark.parametrize("reported,expected", [(8, 8), (-1, 0), (11, 0)])
async def test_usage_event_carries_cached_input_tokens(tmp_path, reported, expected):
    events = []
    async def emit(event):
        events.append(event)
    reply = response([message("done")])
    reply["usage"]["input_tokens_details"]["cached_tokens"] = reported
    client = client_for([reply], [])
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client, event_sink=emit)
    await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert next(e for e in events if e.kind == "usage").payload["cached_input_tokens"] == expected
    await client.close()
```
- [ ] **Step 2: Run the new tests.** `... -m pytest tests/test_orchestration.py tests/test_execution_responses.py -q -k "cached or provenance"` should FAIL.
- [ ] **Step 3: Implement.**
  1. Replace `pricing.py` with:
```python
"""Experiment prices are explicit inputs.
Cached input is billed at ``cached_input_usd_per_million`` when an operator records one; without it
every input token bills at the input rate, as before. The cached rate may not exceed the input rate,
so a reservation at the full rate bounds every settlement. Provider cache writes are not modelled.
"""
from decimal import ROUND_CEILING, Decimal
from pydantic import Field, model_validator
from ..domain import StrictModel

class ModelPrice(StrictModel):
    input_usd_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    output_usd_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    cached_input_usd_per_million: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    source: str = "operator-supplied"
    @model_validator(mode="after")
    def cached_rate_within_input_rate(self):
        cached = self.cached_input_usd_per_million
        if cached is not None and cached > self.input_usd_per_million:
            raise ValueError("cached_input_usd_per_million cannot exceed input_usd_per_million")
        return self
    def cost(self, input_tokens, output_tokens, cached_input_tokens=0):
        if input_tokens < 0 or output_tokens < 0 or cached_input_tokens < 0:
            raise ValueError("Token counts cannot be negative")
        if cached_input_tokens > input_tokens:
            raise ValueError("Cached input tokens cannot exceed input tokens")
        rate = self.cached_input_usd_per_million
        cached_rate = self.input_usd_per_million if rate is None else rate
        value = (self.input_usd_per_million * (input_tokens - cached_input_tokens)
                 + cached_rate * cached_input_tokens + self.output_usd_per_million * output_tokens) / 1_000_000
        return value.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
```
  2. In `responses.py`, add the helper below, then add `cached_input_tokens=_cached_input_tokens(response.usage)` to `usage`. Leave `settled_response` untouched.
```python
def _cached_input_tokens(usage: Any) -> int:
    """Provider-reported cache hits, or 0 (the full input rate) if absent or inconsistent."""
    cached = getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", None)
    return cached if type(cached) is int and 0 <= cached <= usage.input_tokens else 0
```
  3. In `research_worker.py`:
     - Line 1289 becomes `price.cost(inp, out, event.payload.get("cached_input_tokens", 0))`.
     - The reservation at 1264 stays `price.cost(inp, out)`, because no cache hit is guaranteed.
     - Line 1339 uses `price.model_dump(mode="json", exclude_none=True)`.
  4. **Docs.**
     - `docs/FIRST_LIVE_RUN.md`: document the optional `cached_input_usd_per_million`, which must not exceed the input rate. Add: "Do not change prices while an experiment runs; a replayed settlement with a new amount fails with `IDEMPOTENCY_CONFLICT`."
     - `docs/EXECUTION.md`: `cached_input_tokens` settles at the cached rate, and reservations stay at the full rate. Add to the stored-shape list (F7): `usage.cached_input_tokens`.
- [ ] **Step 4: Run the tests.** `... -m pytest tests/test_orchestration.py tests/test_research_budget_wait.py tests/test_run_control.py tests/test_execution_responses.py tests/test_reproduction.py -q` should PASS.
- [ ] **Step 5: Commit** (G7): `feat: bill cached input at an optional cached rate`.

---

### Task 6: Size input reservations from the sound bound, after offline validation (#4b, G4)

**Files:**
- Modify the reservation in `_prepare_request` and add the compaction alarm in `_loop` (`responses.py`).
- Create `tools/reservation_bound.py` and `tests/test_reservation_bound_tool.py`.
- Modify `docs/EXECUTION.md:102-103` and `work/society-s1/RUN_PLAN.md`.
- Test in `tests/test_execution_context.py`.

**Interfaces:**
- Consumes from Task 4: `_input_bound` (the margin-inclusive P1 bound, carried in `_Prepared.input_tokens` when not counted), `observe_dispatcher`, `COMPACTING` and `WIDE`. Consumes `log` and `_emit_telemetry` from Task 2.
- Produces `tools/reservation_bound.check(data_dir, *, threshold, margin, margin_floor=2048, margin_percent=2) -> dict` and `main(argv=None) -> int`.
- Produces the reservation rule (F4). With `context_management`, reserve `input_tokens` (the exact count or the margin-inclusive bound) when `input_tokens + CONTEXT_MARGIN <= compact_threshold`; otherwise reserve `max_context_tokens`.
- Produces the alarm event `bound_reservation_compacted` (`response_id`, `input_tokens_reserved`, `input_tokens`, `compact_threshold`). It fires when a response to a request reserved below the window carries a compaction item (F4).

- [ ] **Step 1: Write the offline tool and its test.** The test goes in `tests/test_reservation_bound_tool.py`:
```python
"""tools/reservation_bound.py on synthetic audit data (the S1 data is private)."""
import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "reservation_bound_tool", Path(__file__).resolve().parents[1] / "tools/reservation_bound.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

def turn(session, number, tokens, *, completed=True, items=("reasoning", "function_call")):
    return {"session_id": session, "turn": number, "completed": completed, "input_tokens": tokens,
            "output_item_types": list(items), "compaction_events": []}

def item(session, number, direction, chars, encrypted=None):
    return {"session_id": session, "turn": number, "direction": direction, "inherited": False,
            "chars": chars, "encrypted_chars": encrypted}

def write(arm, turns, messages):
    arm.mkdir(parents=True)
    (arm / "turns.jsonl").write_text("".join(json.dumps(r) + "\n" for r in turns))
    (arm / "messages.jsonl").write_text("".join(json.dumps(r) + "\n" for r in messages))

def test_bound_passes_when_growth_fits_the_appended_bytes(tmp_path):
    write(tmp_path / "A", [turn("s", 1, 1000), turn("s", 2, 1100)],
          [item("s", 1, "model_input", 4000), item("s", 1, "model_output", 20, 300),
           item("s", 2, "model_input", 200)])
    report = tool.check(tmp_path, threshold=183_808, margin=8_192)
    assert (report["pairs"], report["violations"], report["passed"]) == (1, 0, True)
    assert report["max_ratio_raw"] == 1100 / (1000 + 320 + 200)
    assert report["max_ratio"] == 1100 / (1520 + 2048)  # the 2,048 floor exceeds 2% of 1,520
    assert report["margin_expected_met"] and report["reserved_by_bound"] == 1

def test_gate_passes_on_the_raw_ratio_and_only_reports_the_margin_ratio(tmp_path):
    write(tmp_path / "A", [turn("s", 1, 199_000), turn("s", 2, 199_990)],
          [item("s", 2, "model_input", 1_000)])
    report = tool.check(tmp_path, threshold=183_808, margin=8_192)
    assert (report["passed"], report["margin_expected_met"], report["reserved_by_bound"]) == (True, False, 0)
    assert report["max_ratio"] == 199_990 / (200_000 + 4_000)  # above 0.98, recorded, not a failure
    assert tool.main([str(tmp_path)]) == 0

def test_bound_reports_violations_and_skips_compaction_and_failed_turns(tmp_path):
    write(tmp_path / "A",
          [turn("s", 1, 1000), turn("s", 2, 5000), turn("t", 1, 1000, items=("compaction",)),
           turn("t", 2, 10), turn("u", 1, 1000, completed=False), turn("u", 2, 9000)],
          [item("s", 1, "model_output", 10), item("s", 2, "model_input", 10)])
    report = tool.check(tmp_path, threshold=183_808, margin=8_192)
    assert (report["pairs"], report["violations"], report["passed"]) == (1, 1, False)
    assert tool.main([str(tmp_path)]) == 1
```
The tool goes in `tools/reservation_bound.py`:
```python
"""Offline check that the runtime's input-reservation bound held on recorded turns (G4, P1).
Usage: python tools/reservation_bound.py DATA_DIR [--threshold 183808] [--margin 8192]
       [--margin-floor 2048] [--margin-percent 2]
DATA_DIR has one directory per arm with the audit extraction's turns.jsonl and messages.jsonl.
For consecutive completed turns of a session whose first response had no compaction, the
runtime bounds the second request's input by the first request's billed input plus the
canonical UTF-8 bytes of every request element that differs from the element at the same
position in the first request, plus a margin of max(floor, percent of that sum). The extraction
cannot see re-rendered instructions or tools, or items replaced in place (S1 had none), so the
changed elements here are the items appended since, that response's output included. It keeps
characters, not item bytes, so this sums ``chars`` + ``encrypted_chars``: item JSON contains
those strings and more, and UTF-8 has at least one byte per character, so this never exceeds
the runtime's bound. The gate is the raw ratio of actual to bound, without the margin, which
must stay <= 1. The ratio with the margin (expected <= 0.98) is reported, never enforced.
Prints JSON; exits 1 when a raw ratio exceeds 1. Stdlib only.
"""
from __future__ import annotations
import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]

def check(data_dir: Path, *, threshold: int, margin: int, margin_floor: int = 2_048,
          margin_percent: int = 2) -> dict:
    pairs = []
    for arm in sorted(path for path in data_dir.iterdir() if path.is_dir()):
        appended: dict = defaultdict(int)  # (session, turn) -> chars first sent that turn
        produced: dict = defaultdict(int)  # (session, turn) -> chars of that turn's output
        for entry in _rows(arm / "messages.jsonl"):
            if entry.get("inherited") or entry.get("turn") is None:
                continue
            target = appended if entry["direction"] == "model_input" else produced
            target[(entry["session_id"], entry["turn"])] += (
                (entry.get("chars") or 0) + (entry.get("encrypted_chars") or 0))
        turns = {(row["session_id"], row["turn"]): row for row in _rows(arm / "turns.jsonl")}
        for (session, number), row in sorted(turns.items()):
            nxt = turns.get((session, number + 1))
            if (not row["completed"] or nxt is None or not nxt["completed"]
                    or "compaction" in (row.get("output_item_types") or []) or row.get("compaction_events")):
                continue
            raw = row["input_tokens"] + produced[(session, number)] + appended[(session, number + 1)]
            bound = raw + max(margin_floor, (raw * margin_percent + 99) // 100)  # as the runtime
            pairs.append({"arm": arm.name, "session": session[:8], "turn": number + 1,
                          "input_tokens": nxt["input_tokens"], "bound_raw": raw, "bound": bound,
                          "ratio_raw": nxt["input_tokens"] / raw, "ratio": nxt["input_tokens"] / bound,
                          "reserved_by_bound": bound + margin <= threshold})
    raws, ratios = [pair["ratio_raw"] for pair in pairs], [pair["ratio"] for pair in pairs]
    max_ratio, max_ratio_raw = max(ratios, default=0.0), max(raws, default=0.0)
    return {"pairs": len(pairs), "max_ratio": max_ratio, "max_ratio_raw": max_ratio_raw,
            "median_ratio": statistics.median(ratios) if ratios else None,
            "violations": sum(ratio > 1 for ratio in raws),
            "reserved_by_bound": sum(pair["reserved_by_bound"] for pair in pairs),
            "margin_expected_met": max_ratio <= 0.98,
            "worst": sorted(pairs, key=lambda pair: pair["ratio_raw"], reverse=True)[:5],
            "passed": bool(pairs) and max_ratio_raw <= 1.0}

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--threshold", type=int, default=183_808)
    parser.add_argument("--margin", type=int, default=8_192)
    parser.add_argument("--margin-floor", type=int, default=2_048)
    parser.add_argument("--margin-percent", type=int, default=2)
    args = parser.parse_args(argv)
    report = check(args.data_dir, threshold=args.threshold, margin=args.margin,
                   margin_floor=args.margin_floor, margin_percent=args.margin_percent)
    json.dump(report, sys.stdout, indent=1)
    print()
    return 0 if report["passed"] else 1
if __name__ == "__main__":
    raise SystemExit(main())
```
Run `... -m pytest tests/test_reservation_bound_tool.py -q`; it should PASS.

- [ ] **Step 2: Pass the G4 gate** (read-only; private data). Run `.venv/bin/python tools/reservation_bound.py <data>`, where `<data>` is the private per-arm extract named in G4.
  - **Pass criterion (F3):** the exit code is 0, meaning `violations == 0` and `max_ratio_raw <= 1`. The raw ratio is the only thing that can stop this task.
  - The ratio with the margin, `max_ratio`, is expected at about 0.98 (`margin_expected_met`). Record it and report it, but do not stop on it, even if it is slightly above 0.98.
  - Record `pairs`, `max_ratio_raw`, `max_ratio`, `margin_expected_met`, `violations` and `reserved_by_bound` for the report and the PR. Do not commit the output.
  - For reference, a probe of the same formula, run while this plan was reviewed, found:
    - 3,651 pairs, with a raw max ratio of about 0.99955 (S-r2, turn 126) and a with-margin max of about 0.97995;
    - 31 pairs routed to the full window, because bound + margin + 8,192 > 183,808;
    - one compaction-firing pair, skipped (the runtime reserves the full window there).

    If the numbers differ materially, check the path first.
  - **If the raw gate fails, STOP.** Skip Steps 3–4 and send the `worst` pairs to the lead.
- [ ] **Step 3: Write the failing runtime tests** in `tests/test_execution_context.py`, importing `canonical_json`:
```python
async def run_reserved(tmp_path, threshold, window, final_input=10):
    requests, events, error = [], [], None
    async def emit(event):
        events.append(event)
    client = sdk_client([response([call_item("a")], "r1"),
                         response([text_item("done")], "r2", input_tokens=final_input)], requests)
    tmp_path.mkdir()
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "sessions.db"), client=client,
                               dispatcher=observe_dispatcher(), event_sink=emit)
    params = {"context_management": [{"type": "compaction", "compact_threshold": threshold}]}
    try:
        await runtime.start("work", ModelConfig(model="exact-model", parameters=params), RuntimeLimits(
            max_context_tokens=window, max_output_tokens=1_000, max_total_tokens=None))
    except ExecutionError as caught:
        error = caught
    await client.close()
    creates = [p for path, p in requests if path.endswith("/responses")]
    return creates, [e.payload["input_tokens_reserved"] for e in events if e.kind == "generation_started"], error

async def test_reservation_bound_window_fallback_and_violation(tmp_path):
    creates, reserved, error = await run_reserved(tmp_path / "bound", 40_000, 64_000)
    appended = creates[1]["input"][len(creates[0]["input"]):]
    assert error is None and reserved == [
        10, 10 + sum(len(canonical_json(i).encode("utf-8")) for i in appended) + 2048]  # P1 margin
    _, reserved, error = await run_reserved(tmp_path / "near", 8_200, 10_000)  # count + 8,192 > threshold
    assert error is None and reserved == [10_000, 10_000]
    _, reserved, error = await run_reserved(tmp_path / "over", 40_000, 64_000, final_input=5_000)
    assert reserved[1] < 5_000 and error.code == "PROVIDER_LIMIT_VIOLATION"

async def test_compaction_on_a_request_reserved_below_the_window_raises_an_alarm(tmp_path):
    requests, events = [], []
    async def emit(event):
        events.append(event)
    client = sdk_client([response([compaction_item("one"), call_item("a")], "r1"),
                         response([text_item("done")], "r2")], requests)
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "sessions.db"), client=client,
                               dispatcher=observe_dispatcher(), event_sink=emit)
    await runtime.start("work", ModelConfig(model="exact-model", parameters=COMPACTING), WIDE)
    assert [e.payload for e in events if e.kind == "bound_reservation_compacted"] == [
        {"response_id": "r1", "input_tokens_reserved": 10, "input_tokens": 10, "compact_threshold": 40_000}]
    await client.close()
```
Run `... -m pytest tests/test_execution_context.py -q -k "reservation or alarm"`; it should FAIL (64,000 is reserved twice, and no alarm is emitted).

- [ ] **Step 4: Implement, only after Step 2 passes.**
  1. The `input_reservation` in `_prepare_request` becomes:
```python
        context = params.get("context_management")
        if context:
            # A compaction pass may bill more than the counted or bounded input, so the count or
            # the margin-inclusive bound is reserved only while compaction cannot fire (G4, F4).
            input_reservation = (input_tokens if input_tokens + CONTEXT_MARGIN <= context[0]["compact_threshold"]
                                 else session.limits.max_context_tokens)
        else:
            input_reservation = input_tokens
```
  The output reservation stays at the cap, and the `PROVIDER_LIMIT_VIOLATION` checks are unchanged.
  2. The alarm (F4). In `_loop`, after the `usage` emit and its settlement bookkeeping, and **before** the two `PROVIDER_LIMIT_VIOLATION` checks (so it also fires when the compaction overran), add:
```python
            context = prepared.params.get("context_management")
            if (context and prepared.input_reservation < session.limits.max_context_tokens
                    and any(item.get("type") == "compaction" for item in native["output"])):
                # F4: compaction was assumed impossible below the gate, and the reservation's
                # soundness depends on it. Name the cause before any limit check can stop the run.
                log.warning("bound_reservation_compacted",
                            extra={"session_id": session.id, "operation_id": operation_id})
                await self._emit_telemetry(
                    "bound_reservation_compacted", session, operation_id, response_id=response.id,
                    input_tokens_reserved=prepared.input_reservation,
                    input_tokens=response.usage.input_tokens,
                    compact_threshold=context[0]["compact_threshold"])
```
  If another existing test asserts an exact event-kind list around a compaction item on a request reserved below the window, add `bound_reservation_compacted` to that list and report it.
  3. **`docs/EXECUTION.md`:**
     - The input reservation is the exact count or the margin-inclusive P1 bound while `input + 8,192 <= compact_threshold`, and otherwise the whole window. The output reservation is `max_output_tokens`.
     - Document the provider assumption (F4). Server compaction fires only when a request's input exceeds `compact_threshold`, so a request under the gate cannot compact. If a response to such a request does carry a compaction item, the runtime logs a warning and emits `bound_reservation_compacted`. A compaction that billed past the reservation still stops through `PROVIDER_LIMIT_VIOLATION` and the ledger's sticky halt; the alarm names the cause.
     - Add to the stored-shape list (F7): smaller input reservations, and the `bound_reservation_compacted` event.
  4. **`work/society-s1/RUN_PLAN.md`:** recommend `runtime_limits.max_output_tokens: 16000` for society plans (S1 max 3,234, p99 1,680). Warn that a response that hits the cap raises `PROVIDER_INCOMPLETE`. This stays a documented recommendation only (G4, F4): do not edit `run-plan.example.json` or any code default.
- [ ] **Step 5: Run the tests and commit.** Run `... -m pytest tests/test_execution_context.py tests/test_execution_responses.py tests/test_reservation_bound_tool.py tests/test_research_context_policy.py tests/test_orchestration.py tests/test_research_budget_wait.py tests/test_network_evaluation.py -q`; it should PASS. Commit (G7) as `feat: reserve input from the sound usage bound while compaction cannot fire`, with a second `-m "G4 offline check: <pairs> pairs, max ratio raw <max_ratio_raw>, with margin <max_ratio>"`.

---

### Task 7: Per-process TPM governor (#8, R5)

**Files:**
- Create `src/physharness/execution/admission.py` and `tests/test_execution_admission.py`.
- Modify `responses.py`: `__init__` (207–261), `_Sent`, `_throttle_hook` (Task 2), `_send` (admission, releases, the 429 re-queue) and `_loop` (settle).
- Modify `research_worker.py`: lines 912–921, lines 1696–1749, and a new `_admission_priority` after `_task_contract` (399–419).
- Modify `config.py:48`, `cli.py:241-243` and `worker.py:157-164`.
- Update docs: `docs/EXECUTION.md`, `docs/DEPLOYMENT.md:58` and `PLAN.md` §6.3.
- Tests in `tests/test_execution_responses.py` and `tests/test_orchestration.py`.

**Interfaces:**
- **Consumes:**
  - Task 2: `_throttle_hook(session, operation_id, waits)` and `_resend_rate_limited(..., on_wait=)`. The hook performs each 429 wait inside `_resend_rate_limited`'s abandon-on-interrupt guard;
  - main's give-up and `_abandon_refused` (emit `generation_aborted`, then clear `pending_operation`). This task adds no abort block of its own. On main the sleep being replaced is at `responses.py:97-102`, inside `_resend_rate_limited`, which cannot see the governor, so the re-queue has to arrive through the hook;
  - Task 4: `_Prepared.input_tokens` (the exact count or the margin-inclusive P1 bound) and the create's `except Exception as error:` 400 branch;
  - Task 5: `started_task` and `PRICES`.
- **Produces:**
  - `Admission(key, tokens, waited_seconds, open=True)`.
  - `TokenRateGovernor(*, tokens_per_minute, burst_tokens=None, aging_seconds=30.0)` with:
    - `async admit(*, key, tokens, priority) -> Admission`;
    - `settle(admission, actual_tokens)`;
    - `release(admission)`;
    - `throttled(wait_seconds)`;
    - `snapshot() -> {"tokens_per_minute", "effective_tokens_per_minute", "level", "waiting", "paused_seconds"}`.
  - `ResponsesRuntime(..., token_governor=None, admission_priority=1)` and `_Sent.admission`.
  - `_throttle_hook(..., requeue=None)`. Every 429 calls `throttled(wait)`; only a create, which holds an admission, re-queues through `requeue`, and a count 429 only pauses (F10).
  - `generation_started.admission_wait_seconds`, present only with a governor.
  - `ResearchTaskExecutor(..., token_governor=None)` and `_admission_priority(task, branch)`.
  - `Settings.provider_tokens_per_minute` (env `PHYSHARNESS_PROVIDER_TOKENS_PER_MINUTE`).
  - `KeywordRuntime` in `tests/test_orchestration.py`, which Task 11 reuses.

- [ ] **Step 1: Write the failing governor tests.** They run in real loop time with short waits.
```python
"""TokenRateGovernor: one priority token bucket per process."""
import asyncio
import pytest
from physharness.config import ConfigurationError, Settings
from physharness.execution.admission import TokenRateGovernor

async def drained(**kwargs):
    governor = TokenRateGovernor(tokens_per_minute=60_000, burst_tokens=1_000, **kwargs)  # 1,000/s
    await governor.admit(key="drain", tokens=1_000, priority=0)
    return governor

async def test_rate_priority_and_aging():
    governor = TokenRateGovernor(tokens_per_minute=60_000, burst_tokens=1_000)
    assert (await governor.admit(key="a", tokens=1_000, priority=1)).waited_seconds < 0.05
    assert (await governor.admit(key="a", tokens=500, priority=1)).waited_seconds >= 0.4
    order = []
    async def request(bucket, name, priority, delay, tokens):
        await asyncio.sleep(delay)
        await bucket.admit(key=name, tokens=tokens, priority=priority)
        order.append(name)
    bucket = await drained()
    await asyncio.gather(request(bucket, "low", 2, 0, 300), request(bucket, "high", 0, 0.01, 300),
                         request(bucket, "mid", 1, 0.02, 300))
    assert order == ["high", "mid", "low"]
    order.clear()
    aging = await drained(aging_seconds=0.1)  # "old" has aged 3 classes when "new" arrives
    await asyncio.gather(request(aging, "old", 3, 0, 500), request(aging, "new", 0, 0.35, 500))
    assert order == ["old", "new"]

async def test_settle_refunds_or_charges_and_release_returns_everything():
    governor = TokenRateGovernor(tokens_per_minute=60, burst_tokens=1_000)  # ~1 token/s
    first = await governor.admit(key="a", tokens=800, priority=1)
    governor.settle(first, 300)
    assert 699 <= governor.snapshot()["level"] <= 702
    second = await governor.admit(key="a", tokens=400, priority=1)
    governor.settle(second, 900)
    governor.settle(second, 0)  # settles once only
    assert -202 <= governor.snapshot()["level"] <= -198
    fresh = TokenRateGovernor(tokens_per_minute=60, burst_tokens=1_000)
    held = await fresh.admit(key="b", tokens=500, priority=1)
    fresh.release(held)
    fresh.release(held)
    assert fresh.snapshot()["level"] == 1_000

async def test_throttle_pauses_and_cuts_rate_and_cancelled_waiters_leave():
    governor = TokenRateGovernor(tokens_per_minute=60_000, burst_tokens=1_000)
    governor.throttled(0.3)
    assert (await governor.admit(key="a", tokens=10, priority=0)).waited_seconds >= 0.29
    assert 47_900 <= governor.snapshot()["effective_tokens_per_minute"] <= 48_100
    slow = TokenRateGovernor(tokens_per_minute=60, burst_tokens=100)
    await slow.admit(key="drain", tokens=100, priority=0)
    waiter = asyncio.create_task(slow.admit(key="b", tokens=50, priority=0))
    await asyncio.sleep(0.01)
    assert slow.snapshot()["waiting"] == 1
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert slow.snapshot()["waiting"] == 0

def test_settings_read_the_process_token_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("PHYSHARNESS_PROVIDER_TOKENS_PER_MINUTE", "1800000")
    assert Settings(auth_file=tmp_path / "none.json").provider_tokens_per_minute == 1_800_000
    monkeypatch.setenv("PHYSHARNESS_PROVIDER_TOKENS_PER_MINUTE", "0")
    with pytest.raises(ConfigurationError):
        Settings(auth_file=tmp_path / "none.json")
```
Run `... -m pytest tests/test_execution_admission.py -q`; it should FAIL because the module does not exist.

- [ ] **Step 2: Create `admission.py`.** Also add `provider_tokens_per_minute: int | None = Field(default=None, ge=1)` after `model_prices` in `Settings`.
```python
"""Process-wide admission of provider requests by estimated tokens per minute (R5).
One token bucket per process, shared by every runtime on its event loop. The runtime gives the
estimate (input, cached tokens included, plus expected output) and a priority. The bucket cannot
see other processes: operators give each process a share of the organisation limit.
"""
from __future__ import annotations
import asyncio
import itertools
from dataclasses import dataclass, field

THROTTLE_RATE_FACTOR = 0.8  # multiplicative cut on a provider 429

RECOVERY_FRACTION_PER_MINUTE = 0.05  # additive recovery per clean minute, of the limit

@dataclass
class Admission:
    key: str
    tokens: int
    waited_seconds: float
    open: bool = True

@dataclass
class _Waiter:
    key: str
    tokens: int
    priority: int
    sequence: int
    enqueued: float
    future: asyncio.Future = field(repr=False)

class TokenRateGovernor:
    """Priority token bucket: lower numbers first, waiting ages a request one class per
    ``aging_seconds`` so nothing starves, and a request larger than the bucket is admitted once
    the bucket is full."""
    def __init__(self, *, tokens_per_minute: int, burst_tokens: int | None = None,
                 aging_seconds: float = 30.0) -> None:
        if tokens_per_minute < 1 or (burst_tokens is not None and burst_tokens < 1) or aging_seconds <= 0:
            raise ValueError("Token rate, burst and aging must be positive")
        self.limit, self.aging_seconds = tokens_per_minute, aging_seconds
        self.capacity = float(burst_tokens or tokens_per_minute)
        self.level, self.paused_until = self.capacity, 0.0
        self._cut_rate, self._cut_at = float(tokens_per_minute), None
        self._updated: float | None = None
        self._waiters: list[_Waiter] = []
        self._sequence = itertools.count()
        self._timer: asyncio.TimerHandle | None = None
    @staticmethod
    def _now() -> float:
        return asyncio.get_running_loop().time()
    def _rate(self, now: float) -> float:
        if self._cut_at is None:
            return float(self.limit)
        minutes = max(0.0, now - self._cut_at) / 60
        return min(float(self.limit), self._cut_rate + RECOVERY_FRACTION_PER_MINUTE * self.limit * minutes)
    def _refill(self, now: float) -> None:
        if self._updated is not None and now > self._updated:
            self.level = min(self.capacity, self.level + (now - self._updated) * self._rate(now) / 60)
        self._updated = now
    async def admit(self, *, key: str, tokens: int, priority: int) -> Admission:
        if tokens < 0:
            raise ValueError("Admission tokens cannot be negative")
        loop = asyncio.get_running_loop()
        waiter = _Waiter(key, tokens, priority, next(self._sequence), loop.time(), loop.create_future())
        self._waiters.append(waiter)
        self._pump()
        try:
            await waiter.future
        except asyncio.CancelledError:
            if waiter in self._waiters:
                self._waiters.remove(waiter)
                self._pump()
            elif waiter.future.done() and not waiter.future.cancelled():
                self._credit(tokens)  # granted just as the caller was cancelled
            raise
        return Admission(key=key, tokens=tokens, waited_seconds=loop.time() - waiter.enqueued)
    def settle(self, admission: Admission, actual_tokens: int) -> None:
        """Charge actual use: refund an overestimate or take an underestimate."""
        if admission.open:
            admission.open = False
            self._credit(admission.tokens - max(0, actual_tokens))
    def release(self, admission: Admission) -> None:
        """Return every admitted token: the request was never sent."""
        if admission.open:
            admission.open = False
            self._credit(admission.tokens)
    def throttled(self, wait_seconds: float) -> None:
        """A provider 429: pause every admission and cut the rate (AIMD)."""
        now = self._now()
        self._refill(now)
        self._cut_rate, self._cut_at = max(1.0, self._rate(now) * THROTTLE_RATE_FACTOR), now
        self.paused_until = max(self.paused_until, now + max(0.0, wait_seconds))
        self._pump()
    def snapshot(self) -> dict:
        now = self._now()
        self._refill(now)
        return {"tokens_per_minute": self.limit, "effective_tokens_per_minute": round(self._rate(now)),
                "level": int(self.level), "waiting": len(self._waiters),
                "paused_seconds": round(max(0.0, self.paused_until - now), 3)}
    def _credit(self, tokens: float) -> None:
        self._refill(self._now())
        self.level = min(self.capacity, self.level + tokens)
        self._pump()
    def _pump(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        now = self._now()
        self._refill(now)
        while self._waiters:
            if now < self.paused_until:
                return self._schedule(self.paused_until - now)
            head = min(self._waiters, key=lambda w: (
                w.priority - int((now - w.enqueued) // self.aging_seconds), w.sequence))
            if head.future.done():
                self._waiters.remove(head)
                continue
            need = min(float(head.tokens), self.capacity)
            if self.level < need:
                return self._schedule((need - self.level) * 60 / self._rate(now))
            self._waiters.remove(head)
            self.level -= head.tokens
            head.future.set_result(None)
    def _schedule(self, delay: float) -> None:
        self._timer = asyncio.get_running_loop().call_later(max(delay, 0.001), self._pump)
```
Rerun Step 1; it should PASS.

- [ ] **Step 3: Write the failing runtime and executor tests.** Import `TokenRateGovernor` in `tests/test_execution_responses.py`:
```python
async def test_rate_limits_pause_the_governor_and_only_a_create_requeues(tmp_path):
    calls, requests, events = [], [], []
    class Counting(TokenRateGovernor):
        async def admit(self, **kwargs):
            calls.append("admit")
            return await super().admit(**kwargs)
        def release(self, admission):
            calls.append("release")
            super().release(admission)
        def throttled(self, wait_seconds):
            calls.append("throttled")
            super().throttled(wait_seconds)
        def settle(self, admission, actual_tokens):
            calls.append("settle")
            super().settle(admission, actual_tokens)
    async def emit(event):
        if event.kind == "generation_started":
            calls.append(event.kind)
        events.append(event)
    client = rate_limited_client([(429, refusal("rate_limit_exceeded"), {"retry-after-ms": "5"}),
                                  (200, response([message("done")]), {})], requests,
                                 counts=[(429, refusal("rate_limit_exceeded"), {"retry-after-ms": "5"})])
    governor = Counting(tokens_per_minute=1_000_000)
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client,
                               event_sink=emit, token_governor=governor)
    await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    # F10: the count's 429 only pauses admission; the create's pauses, releases and re-admits.
    assert calls == ["throttled", "admit", "generation_started", "throttled", "release", "admit", "settle"]
    started = next(e for e in events if e.kind == "generation_started")
    assert started.payload["admission_wait_seconds"] >= 0
    assert len({ident for url, ident in requests if not url.endswith("/input_tokens")}) == 1
    assert governor.snapshot()["level"] >= 999_985  # settled at the 15 tokens used
    await client.close()

async def test_governor_requeue_past_the_deadline_gives_up_definitely(tmp_path):
    events = []
    async def emit(event):
        events.append(event.kind)
    client = rate_limited_client([(429, refusal("rate_limit_exceeded"), {"retry-after": "1.5"})], [])
    governor = TokenRateGovernor(tokens_per_minute=1_000_000)
    store = SQLiteRuntimeStore(tmp_path / "s.db")
    runtime = ResponsesRuntime(store=store, client=client, event_sink=emit, token_governor=governor)
    with pytest.raises(ExecutionError) as error:
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits(timeout_seconds=2))
    (session_id,) = [row[0] for row in store.db.execute("SELECT id FROM runtime_sessions")]
    checkpoint = await runtime.checkpoint(session_id)
    # The 1.5 s pause outlasts the re-admission budget (deadline - 1 s): the give-up runs
    # main's _abandon_refused (emit, then clear) and every admitted token comes back.
    assert error.value.code == "PROVIDER_RATE_LIMITED" and error.value.retryable
    assert (checkpoint.session.status, checkpoint.native_state["pending_operation"]) == ("failed", None)
    assert events == ["generation_started", "provider_throttled", "generation_aborted"]
    assert governor.snapshot()["level"] == 1_000_000
    await client.close()

async def test_verified_target_during_admission_wait_sends_nothing(tmp_path):
    requests, checks = [], []
    governor = TokenRateGovernor(tokens_per_minute=60_000, burst_tokens=100)
    await governor.admit(key="other", tokens=100, priority=0)
    async def guard():
        checks.append(True)
        return len(checks) >= 2  # verified by the time admission is granted
    client = client_for([], requests)
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client,
                               pre_generation_guard=guard, token_governor=governor, admission_priority=0)
    result = await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert result.completion_reason == "target_verified"
    assert not [u for u, _ in requests if u.endswith("/responses")] and governor.snapshot()["waiting"] == 0
    await client.close()
```
In `tests/test_orchestration.py`:
```python
class KeywordRuntime:
    """Accepts every runtime keyword, records them, and completes without a model call."""
    seen: dict = {}
    def __init__(self, **kwargs):
        KeywordRuntime.seen = kwargs
        self.store = kwargs["store"]
    async def start(self, prompt, model, limits):
        from physharness.execution import RuntimeCheckpoint, RuntimeResult, RuntimeSession
        session = RuntimeSession(runtime="responses", model=model, limits=limits)
        await self.store.save(RuntimeCheckpoint.build(session, {"source": "keyword fixture"}))
        session.status = "completed"
        await self.store.save(RuntimeCheckpoint.build(session, {"result": "Unresolved"}))
        return RuntimeResult(session=session, output_text="No proof; remaining assumptions need review.")

@pytest.mark.asyncio
async def test_executor_passes_shared_governor_and_role_priority(lab):
    from physharness.execution.admission import TokenRateGovernor
    from physharness.orchestration.research_worker import ResearchTaskExecutor
    service, actor, _, task = started_task(lab)
    governor = TokenRateGovernor(tokens_per_minute=1_000_000)
    executor = ResearchTaskExecutor(service, prices=PRICES, runtime_factory=KeywordRuntime,
                                    token_governor=governor)
    assert (await executor.execute(task["id"], actor.project_id))["status"] == "completed"
    assert KeywordRuntime.seen["token_governor"] is governor
    assert KeywordRuntime.seen["admission_priority"] == 0  # a root is on the critical path
```
Run `... -m pytest tests/test_execution_responses.py tests/test_orchestration.py -q -k "governor or admission_wait"`; it should FAIL.

- [ ] **Step 4: Wire the runtime.**
  1. Import `Admission` and `TokenRateGovernor` from `.admission`, and add `REQUEUE_MARGIN_SECONDS = 1.0` and `OUTPUT_ESTIMATE_SEED = 1_000`.
  2. `__init__` gains `token_governor=None` and `admission_priority: int = 1`.
     - Unless `type(admission_priority) is int and 0 <= admission_priority <= 3`, raise `ExecutionError("INVALID_CONFIG", "Admission priority must be 0-3")`.
     - Store both, and set `self._output_ema: dict[str, float] = {}`.
     - Add the helpers:
```python
    def _expected_output(self, session: RuntimeSession) -> int:
        """Admission output estimate: a per-session moving average, never the cap."""
        return min(session.limits.max_output_tokens, int(self._output_ema.get(session.id, OUTPUT_ESTIMATE_SEED)))
    def _release(self, admission: Admission | None) -> None:
        if admission is not None:
            self.token_governor.release(admission)
```
  3. Give `_Sent` a field `admission: Admission | None = None`. Start `_send`, before the pre-generation guard it opens with, as below. `prepared.input_tokens` is Task 4's exact count or margin-inclusive bound, so admission uses the same bound as the reservation (F2).
```python
        admission, estimate = None, prepared.input_tokens + self._expected_output(session)
        if self.token_governor is not None:
            # Admission precedes the dollar reservation: a queued request holds no money, and a
            # target verified while queued sends nothing.
            admission = await self.token_governor.admit(key=session.id, tokens=estimate,
                                                        priority=self.admission_priority)
```
  4. Call `self._release(admission)` wherever the request is certainly not sent:
     - before the guard's `_complete_verified`;
     - in the `except BaseException:` around `generation_started`;
     - before both `TIMEOUT` raises;
     - in Task 4's create 400 branch, before its `_abandon_refused` call;
     - when `_resend_rate_limited` gives up. At the top of Task 4's `except Exception as error:` around the create, before the 400 check re-raises, add `if isinstance(error, ExecutionError) and error.code == "PROVIDER_RATE_LIMITED": self._release(admission)`.
  5. Add `**({"admission_wait_seconds": round(admission.waited_seconds, 3)} if admission else {})` to `generation_started`. Then route 429 waits through the governor. Do not add a sleep loop or an abort block to `_send`. The re-queue runs inside Task 2's hook, and main's guard in `_resend_rate_limited` covers it: an interrupt or an error during re-admission runs `_abandon_refused` (emit `generation_aborted`, then clear the marker).
     - `_throttle_hook` gains a last parameter `requeue=None`. Its `on_wait` keeps recording and emitting as in Task 2, but its final `await asyncio.sleep(wait)` becomes:
```python
            if self.token_governor is not None:
                self.token_governor.throttled(wait)  # every 429 pauses admission (R5, F10)
            # Only a create holds an admission, so only a create re-queues; a count 429 just
            # waits out the pause.
            await (requeue() if requeue is not None else asyncio.sleep(wait))
```
     - The count's hook call in `_prepare_request` is unchanged, so a count 429 calls `throttled(wait)` and sleeps.
     - In `_send`, define `requeue` right before the create call and pass `on_wait=self._throttle_hook(session, operation_id, waits, requeue if self.token_governor is not None else None)`:
```python
        async def requeue() -> None:
            # Re-queue behind the global pause instead of a private sleep, so waiting requests
            # resume in priority order rather than all at once.
            nonlocal admission
            self._release(admission)
            admission = None
            budget = deadline - asyncio.get_running_loop().time() - REQUEUE_MARGIN_SECONDS
            try:
                admission = await asyncio.wait_for(self.token_governor.admit(
                    key=session.id, tokens=estimate, priority=self.admission_priority),
                    timeout=max(budget, 0.0))
            except TimeoutError:
                # Raised inside _resend_rate_limited's wait guard, so its abandon runs
                # _abandon_refused first: generation_aborted, then the marker clears.
                raise ExecutionError("PROVIDER_RATE_LIMITED",
                                     "Provider rate limit outlasted the runtime deadline",
                                     operation_id=operation_id, retryable=True) from None
```
  6. Return `_Sent(..., admission=admission)`. In `_loop`, once `usage` has been emitted successfully:
```python
            if sent.admission is not None:
                usage = response.usage
                self.token_governor.settle(sent.admission, usage.input_tokens + usage.output_tokens)
                ema = self._output_ema.get(session.id, OUTPUT_ESTIMATE_SEED)
                self._output_ema[session.id] = 0.8 * ema + 0.2 * usage.output_tokens
```
  Any other exit after the send (unknown outcome, failed usage, or missing usage) keeps the estimate charged.
- [ ] **Step 5: Wire the executor and the entry points.**
  1. In `research_worker.py`, add this after `_task_contract`:
```python
def _admission_priority(task, branch):
    """TPM admission class: roots and children a parent waits on first, then referees."""
    if is_referee_task(task):
        return 1
    return 0 if _task_contract(task, branch)["kind"] in {"root", "joined_child"} else 2
```
  2. `ResearchTaskExecutor.__init__` gains `token_governor=None`, stored as `self.token_governor`.
  3. In `execute`, add `accepts_any = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())` right after `parameters = ...` (line 1696), and delete the duplicate inside `if society:`. Then, after the `update_source` block:
```python
            if self.token_governor is not None and ("token_governor" in parameters or accepts_any):
                runtime_kwargs["token_governor"] = self.token_governor
                runtime_kwargs["admission_priority"] = _admission_priority(task, branch)
```
  4. `cli.py` (`run-team`) and `worker.py` (`main`, on the worker's loop) import `TokenRateGovernor` locally. They pass `token_governor=TokenRateGovernor(tokens_per_minute=settings.provider_tokens_per_minute) if settings.provider_tokens_per_minute else None`.
  5. **Docs.**
     - `docs/EXECUTION.md` gets a "Provider rate governance" section:
       - `PHYSHARNESS_PROVIDER_TOKENS_PER_MINUTE` enables one governor per process;
       - the estimate is input (cached tokens count) plus the average output;
       - roots and joined children go first, then referees, then others, and waiting requests age;
       - every 429 pauses admission and cuts the rate by 20%. A 429 on `responses.create` also releases its admission and re-queues it; a 429 on `input_tokens.count` only pauses (F10);
       - a give-up while re-queued is definite, as without a governor;
       - the governor adds no throughput;
       - set it to about 90% of the org limit divided by the number of processes that share it.
     - `docs/DEPLOYMENT.md:58`: add the variable.
     - `PLAN.md` §6.3: "a per-process client-side TPM governor; cross-process governance belongs to the model router (§6.1)".
- [ ] **Step 6: Run the tests and commit.** Run `... -m pytest tests/test_execution_admission.py tests/test_execution_responses.py tests/test_research_loop_integration.py tests/test_orchestration.py tests/test_society_tools.py tests/test_config_security.py tests/test_run_cli.py -q`. It should PASS; `LEGACY_RUNTIME_KWARGS` is unchanged because no governor is configured. Commit (G7): `feat: optional per-process TPM governor with priority admission and 429 re-queue`.

---

### Task 8: `parallel_tool_calls` as a validated model parameter (#11, R6)

**Files:**
- Modify `parameters.py:60-69` and `responses.py` (`_Prepared`, `_prepare_request`, `_send`).
- Update `docs/EXECUTION.md:89-99`.
- Tests in `tests/test_execution_parameters.py`, `tests/test_execution_responses.py` and `tests/test_execution_context.py`.

**Interfaces:**
- Consumes from Task 1: `RecordingStore`, `DOUBLE_SCHEMA` and `double_call`. Consumes `observe_dispatcher` from Task 4.
- Produces `ResponsesParameters.parallel_tool_calls: bool | None` and `_Prepared.parallel_tool_calls: bool`.

- [ ] **Step 1: Write the failing tests.**
  - In `tests/test_execution_parameters.py`, add `{"parallel_tool_calls": "yes"}` and `{"parallel_tool_calls": 1}` to `INVALID`. Also add a test asserting that `validate_responses_parameters({"parallel_tool_calls": True}) == {"parallel_tool_calls": True}` and `validate_responses_parameters({}) == {}`.
  - In `tests/test_execution_responses.py`:
```python
PARALLEL = ModelConfig(model="exact-model", parameters={"parallel_tool_calls": True})

@pytest.mark.parametrize("parameters,expected", [({}, False), ({"parallel_tool_calls": True}, True)])
async def test_parallel_flag_sent_to_count_and_create(tmp_path, parameters, expected):
    requests = []
    client = client_for([response([message("done")])], requests)
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client)
    await runtime.start("x", ModelConfig(model="exact-model", parameters=parameters), RuntimeLimits())
    assert [payload["parallel_tool_calls"] for _, payload in requests] == [expected, expected]
    await client.close()

async def test_parallel_calls_run_in_order_each_after_its_marker(tmp_path):
    requests, dispatched = [], []
    store, dispatcher = RecordingStore(tmp_path / "s.db"), ToolDispatcher()
    async def double(arguments, operation_id):
        dispatched.append((operation_id, store.pending[-1]))
        return {"value": arguments["value"] * 2}
    dispatcher.register("double", DOUBLE_SCHEMA, double)
    client = client_for([response([double_call("call_1", 2), double_call("call_2", 3)]),
                         response([message("done")], response_id="resp_2")], requests)
    result = await ResponsesRuntime(store=store, dispatcher=dispatcher, client=client).start(
        "x", PARALLEL, RuntimeLimits())
    sid = result.session.id
    assert dispatched == [(f"{sid}:call_1", f"{sid}:call_1"), (f"{sid}:call_2", f"{sid}:call_2")]
    second = [p for u, p in requests if u.endswith("/responses")][1]["input"]
    assert [json.loads(i["output"]) for i in second if i.get("type") == "function_call_output"] == [
        {"value": 4}, {"value": 6}]
    await client.close()

async def test_fatal_tool_error_mid_batch_stops_later_calls(tmp_path):
    dispatched, dispatcher = [], ToolDispatcher()
    async def fatal(arguments, operation_id):
        dispatched.append(operation_id)
        raise ExecutionError("STALE_LEASE", "lease lost", operation_id=operation_id)
    dispatcher.register("double", DOUBLE_SCHEMA, fatal)
    client = client_for([response([double_call("call_1"), double_call("call_2")])], [])
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"), dispatcher=dispatcher, client=client)
    with pytest.raises(ExecutionError) as error:
        await runtime.start("x", PARALLEL, RuntimeLimits())
    assert error.value.code == "STALE_LEASE" and len(dispatched) == 1
    checkpoint = await runtime.checkpoint(dispatched[0].split(":")[0])
    assert (checkpoint.session.status, checkpoint.native_state["pending_operation"]) == ("uncertain", dispatched[0])
    await client.close()
```
- [ ] **Step 2: Run the new tests.** `... -m pytest tests/test_execution_parameters.py tests/test_execution_responses.py tests/test_execution_context.py -q -k "parallel or batch"` should FAIL with `INVALID_CONFIG`.
- [ ] **Step 3: Implement.**
  1. Add `parallel_tool_calls: bool | None = None` to `ResponsesParameters`; strict mode rejects anything that is not a bool.
  2. In `_prepare_request`, right after `params = dict(...)`, add `parallel = bool(params.pop("parallel_tool_calls", False))`. This avoids a clash with the explicit keyword.
  3. Pass `parallel_tool_calls=parallel` to the count and to the new last field `_Prepared.parallel_tool_calls`. `_send` passes `parallel_tool_calls=prepared.parallel_tool_calls`.
  4. `_run_calls` does not change: it already runs a response's calls in emitted order, each after its own marker save.
  5. **Docs.** In `docs/EXECUTION.md`, add `parallel_tool_calls` and `context_management` to the parameter list (line 90), and describe batches:
     - the default is `false`, as today;
     - with `true`, the calls still run one at a time, in emitted order;
     - each call's marker is durable before its dispatch;
     - a fatal tool error stops the batch and leaves the session uncertain, while an error envelope does not stop it;
     - handoff and wait intents apply after the whole batch;
     - there is no per-response call cap beyond the output cap.
- [ ] **Step 4: Run the tests and commit.** Run `... -m pytest tests/test_execution_parameters.py tests/test_execution_responses.py tests/test_execution_context.py tests/test_society_tools.py -q`; it should PASS. Commit (G7): `feat: parallel_tool_calls as a validated model parameter with ordered batch execution`.

---

### Task 9: Single-pass checkpoint encoding and one transaction per save (#10c, #10f)

**Files:**
- Modify `types.py:124-131` (`build`), `checkpoint_chunks.py:74-197` (`encode`), `service.py:1353-1424` (plus new methods) and `research_worker.py:157-328` (`CanonicalRuntimeStore`).
- Create `tests/fixtures/native_checkpoint_golden.json` in Step 2.
- Update `docs/EXECUTION.md:111-114`.
- Tests in `tests/test_native_checkpoint_chunks.py` and `tests/test_execution_responses.py`.

**Interfaces (produced):**
- `checkpoint_chunks._serialized_size(item, sizes) -> int`.
- `HarnessService._artifact_record(session, request, actor, digest, size, *, record_id=None) -> dict`.
- `HarnessService.commit_native_checkpoint(actor, key, inputs, artifacts, publish) -> dict`, where `artifacts: list[tuple[str, ArtifactCreate, str, int]]` and `publish(session, op, records) -> dict`.
- `CanonicalRuntimeStore._warm_chunk_cache(session_id)`.

**Design decisions** (put these in the docstrings):
- A save verifies the digest exactly **once**, at the store boundary. `encode` then derives every byte from that object in the same synchronous call.
- The decode round-trip is dropped. A golden byte-identity test and a round-trip test pin the encoder instead.
- Chunk and manifest bytes are stored **before** the single transaction. A committed row therefore never references missing bytes, and a failed or replayed transaction leaves only harmless orphan bytes. This is the ordered fsync move R4 allows.
- `create_artifact` keeps its in-transaction write.
- Encoding is not threaded.

- [ ] **Step 1: Write the tests.** Import `hashlib`, `Path`, `canonical_json`, and `decode` and `encode` from `physharness.execution.checkpoint_chunks`:
```python
GOLDEN = Path(__file__).parent / "fixtures" / "native_checkpoint_golden.json"

GOLDEN_SESSION = RuntimeSession(id="golden-session", runtime="openai_responses",
                                model=ModelConfig(model="exact-model"), limits=RuntimeLimits())

def golden_cases():
    unicode, tool = "∀ ε > 0, ∃ δ ≥ 0 — ℝ", {"type": "string", "description": "d" * 300}
    return {"small": {"input": [{"role": "user", "content": "hi"}], "settled_boundary": True},
            "paged_list": {"input": [{"id": str(i), "content": "x" * 4096} for i in range(40)]},
            "nested_map": {"tool_results": {f"s:{i}": {"result": {"text": unicode * 200}} for i in range(30)}},
            "long_text": {"initial_anchor": ("é" * 3000 + "a") * 20},
            "legacy_response": {"responses": [{"id": "r1", "output": [], "tools": [
                {"name": f"t{i}", "parameters": tool} for i in range(40)]}]}}

def encode_to_memory(state):
    chunks, order = {}, []
    def put(content):
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        chunks[digest] = content.encode("utf-8")
        order.append(digest)
        return {"id": digest, "sha256": digest}
    checkpoint = RuntimeCheckpoint.build(GOLDEN_SESSION, state)
    return checkpoint, encode(checkpoint, put), chunks, order

def chunk_digests(state):
    _, manifest, _, order = encode_to_memory(state)
    return {"chunks": order, "manifest": hashlib.sha256(canonical_json(manifest).encode()).hexdigest()}

def test_encoder_is_byte_identical_to_golden_and_round_trips():
    assert {n: chunk_digests(s) for n, s in golden_cases().items()} == json.loads(GOLDEN.read_text())
    for state in golden_cases().values():
        checkpoint, manifest, chunks, _ = encode_to_memory(state)
        assert decode(canonical_json(manifest).encode(), lambda ref: chunks[ref["sha256"]]) == checkpoint

@pytest.mark.asyncio
async def test_save_verifies_the_checkpoint_digest_exactly_once(native_store, monkeypatch):
    _, _, _, _, store, session = native_store
    calls, original = [], RuntimeCheckpoint.verify
    checkpoint = RuntimeCheckpoint.build(session, {"input": [{"content": "x" * 4096, "id": str(i)}
                                                             for i in range(80)]})
    monkeypatch.setattr(RuntimeCheckpoint, "verify",
                        lambda self, runtime=None: calls.append(1) or original(self, runtime))
    await store.save(checkpoint)
    assert len(calls) == 1

@pytest.mark.asyncio
async def test_single_transaction_commit_is_atomic(native_store, monkeypatch):
    service, actor, _, _, store, session = native_store
    first = RuntimeCheckpoint.build(session, {"input": ["first"]})
    await store.save(first)
    before = (service.list_records("session", actor)[0], service.list_records("artifact", actor))
    original = service._artifact_record
    def fail_manifest(db_session, request, *args, **kwargs):
        if request.kind == "native_checkpoint":
            raise RuntimeError("crash before manifest")
        return original(db_session, request, *args, **kwargs)
    monkeypatch.setattr(service, "_artifact_record", fail_manifest)
    with pytest.raises(RuntimeError, match="crash before manifest"):
        await store.save(RuntimeCheckpoint.build(
            session, {"input": [{"content": "x" * 4096, "id": str(i)} for i in range(80)]}))
    assert (service.list_records("session", actor)[0], service.list_records("artifact", actor)) == before
    assert await store.load(session.id) == first

@pytest.mark.asyncio
async def test_restart_dedupes_existing_chunks_without_cache(native_store):
    service, actor, experiment, task, store, session = native_store
    history = [{"content": "x" * 4096, "id": str(i)} for i in range(80)]
    await store.save(RuntimeCheckpoint.build(session, {"input": history}))
    def chunk_rows():
        return sum(a["artifact_kind"] == "native_checkpoint_chunk" for a in service.list_records("artifact", actor))
    before = chunk_rows()
    restarted = CanonicalRuntimeStore(service, actor, experiment["id"], task["id"], "worker", store.fence)
    await restarted.save(RuntimeCheckpoint.build(session, {"input": [*history, {"content": "y", "id": "80"}]}))
    assert chunk_rows() - before <= 6  # new last page, sequence, map leaf, root; not all 11 pages
    assert (await restarted.load(session.id)).native_state["input"][-1] == {"content": "y", "id": "80"}
```
Delete `test_interrupted_chunk_save_does_not_publish_manifest`, which the atomic test supersedes. In `test_save_and_load_sql_cost_scales_with_new_chunks_not_history`, tighten the bound to `sql <= 2 * new + 40`. In `tests/test_execution_responses.py`:
```python
def test_build_copies_state_through_json():
    from physharness.execution import RuntimeCheckpoint, RuntimeSession
    from physharness.execution.types import digest
    session = RuntimeSession(runtime="openai_responses", model=ModelConfig(model="exact-model"),
                             limits=RuntimeLimits())
    state = {"pair": (1, 2), "input": [{"content": "x"}]}
    checkpoint = RuntimeCheckpoint.build(session, state)
    assert checkpoint.native_state["pair"] == [1, 2]
    assert checkpoint.state_digest == digest({"session": session.model_dump(mode="json"), "native_state": state})
```
- [ ] **Step 2: Record the golden with the unchanged encoder, then run.**
```bash
PYTHONPATH=src:tests .venv/bin/python -c "import json, test_native_checkpoint_chunks as t; print(json.dumps({n: t.chunk_digests(s) for n, s in t.golden_cases().items()}, indent=1, sort_keys=True))" > tests/fixtures/native_checkpoint_golden.json
PYTHONPATH=src .venv/bin/python -m pytest tests/test_native_checkpoint_chunks.py tests/test_execution_responses.py -q
```
  - Expected to PASS: the golden/round-trip test and restart dedupe (which idempotency keys already satisfy).
  - Expected to FAIL: verify-once (today it verifies 3 times), atomic, the SQL bound, and the `build` copy.
- [ ] **Step 3: Rewrite the encoder and `build`.**
  1. In `types.py`, `build` computes `raw = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)` and returns `cls(session=session.model_copy(deep=True), native_state=json.loads(raw)["native_state"], state_digest=hashlib.sha256(raw.encode()).hexdigest())`. Add the comment `# One serialization yields both the digest and an independent copy of JSON state.` Drop the `deepcopy` import if nothing else uses it.
  2. In `checkpoint_chunks.py`, add:
```python
def _serialized_size(item: Any, sizes: dict[int, int]) -> int:
    """UTF-8 length of ``canonical_json(item)``, computed once per container (by id)."""
    if isinstance(item, (dict, list)):
        key = id(item)
        if key not in sizes:
            parts = ([len(canonical_json(k).encode("utf-8")) + 1 + _serialized_size(v, sizes)
                      for k, v in item.items()] if isinstance(item, dict)
                     else [_serialized_size(v, sizes) for v in item])
            sizes[key] = 2 + max(len(parts) - 1, 0) + sum(parts)
        return sizes[key]
    return len(canonical_json(item).encode("utf-8"))
```
  3. Change `encode`:
     - Delete `checkpoint.verify()`.
     - Add `sizes = {}` and `session_value = checkpoint.session.model_dump(mode="json")`, and use `session_value` for the root.
     - Replace the size check with `_serialized_size({"native_state": ..., "session": session_value, "state_digest": ..., "version": ...}, sizes) > MAX_BYTES`.
     - In `value()`, compute `byte_size = _serialized_size(item, sizes)` instead of serializing. The decisions and stored nodes do not change, so the chunks stay byte-identical.
     - Delete the decode self-check (lines 191–196) and the `written` dict.

  Rerun the golden test; it should PASS.
- [ ] **Step 4: Implement the one-transaction save.**
  1. Add to `service.py`:
```python
    def _artifact_record(self, session, request: ArtifactCreate, actor: Principal, digest: str,
                         size: int, *, record_id: str | None = None) -> dict:
        """Insert one artifact row for bytes already in the object store (no event)."""
        return self._insert(session, "artifact", actor, {
            **request.model_dump(mode="json", exclude={"content"}), "artifact_kind": request.kind,
            "sha256": digest, "size_bytes": size, "submitted_by": actor.id}, record_id=record_id)
    def commit_native_checkpoint(self, actor, key, inputs, artifacts, publish):
        """Commit a checkpoint's new artifact rows and its session pointer atomically.
        Callers store every artifact's bytes first, so a committed row never references missing
        bytes. One command inserts the rows (no per-chunk event or command row) and runs
        ``publish(session, op, records)``, which writes the session record and ``session.saved``.
        """
        require_role(actor, "operator", "admin")
        if any(r.kind not in {"native_checkpoint", "native_checkpoint_chunk"} for _, r, _, _ in artifacts):
            raise HarnessError("ARTIFACT_KIND_RESERVED", "Only native checkpoint artifacts commit with a save.",
                               status=403)
        def action(session, op):
            for experiment_id in {r.experiment_id for _, r, _, _ in artifacts} - {None}:
                self._get(session, "experiment", experiment_id, actor)
            return publish(session, op, {rid: self._artifact_record(session, r, actor, sha, size, record_id=rid)
                                         for rid, r, sha, size in artifacts})
        return self._execute(actor, key, "runtime.save", inputs, action)
```
  2. `create_artifact`'s action keeps the experiment `_get`, then runs `digest = self.artifacts.put(content)` and `record = self._artifact_record(session, request, actor, digest, len(content))`, followed by the unchanged `artifact.created` event and `return record`.
  3. In `CanonicalRuntimeStore.__init__`, add `self._warm_sessions: set[str] = set()`, then add:
```python
    def _warm_chunk_cache(self, session_id):
        """After a restart, learn this session's stored chunks once so they are reused."""
        if session_id in self._warm_sessions:
            return
        with self.service.db.sessions() as session:
            for row in session.scalars(select(RecordRow).where(
                RecordRow.project_id == self.actor.project_id, RecordRow.kind == "artifact",
                RecordRow.payload["artifact_kind"].as_string() == "native_checkpoint_chunk",
                RecordRow.payload["experiment_id"].as_string() == self.experiment_id,
                RecordRow.payload["provenance"]["task_id"].as_string() == self.task_id,
                RecordRow.payload["provenance"]["session_id"].as_string() == session_id,
            ).order_by(RecordRow.id)):
                digest = row.payload["sha256"]
                self._chunk_cache.setdefault((session_id, digest), {"id": row.id, "sha256": digest})
        self._warm_sessions.add(session_id)
```
  4. The head of `_save_checkpoint` becomes:
```python
    def _save_checkpoint(self, checkpoint):
        # The one digest check per save; encoding derives every byte from this object in the
        # same synchronous call, so nothing can change it in between.
        checkpoint.verify()
        session_id = checkpoint.session.id
        self._warm_chunk_cache(session_id)
        provenance, rows, written = {"task_id": self.task_id, "session_id": session_id}, [], {}
        def artifact(kind, content):
            return ArtifactCreate(experiment_id=self.experiment_id, kind=kind, content=content,
                                  media_type="application/json", provenance=provenance)
        def put_chunk(content):
            raw = content.encode("utf-8")
            digest = hashlib.sha256(raw).hexdigest()
            if (known := self._chunk_cache.get((session_id, digest)) or written.get(digest)) is not None:
                return known
            self.service.artifacts.put(raw)  # durable before any row can reference it
            written[digest] = {"id": new_id(), "sha256": digest}
            rows.append((written[digest]["id"], artifact("native_checkpoint_chunk", content), digest, len(raw)))
            return written[digest]
        data = encode_native_checkpoint(checkpoint, put_chunk)
        manifest, manifest_id = canonical_json(data), new_id()
        raw_manifest = manifest.encode("utf-8")
        rows.append((manifest_id, artifact("native_checkpoint", manifest),
                     self.service.artifacts.put(raw_manifest), len(raw_manifest)))
```
  5. Rename the nested `action(session, op)` to `publish(session, op, records)`, keeping its body verbatim except that `artifact["id"]` becomes `records[manifest_id]["id"]`. Replace the final `_execute` with:
```python
        record = self.service.commit_native_checkpoint(
            self.actor, f"runtime-save:{checkpoint.state_digest}", data, rows, publish)
        # A replayed save returns the earlier record without inserting these rows; only a save
        # that committed this manifest may teach the cache new chunk ids.
        if record.get("checkpoint_artifact_id") == manifest_id:
            self._chunk_cache.update({(session_id, d): ref for d, ref in written.items()})
```
  The key and inputs are unchanged, so saves made before the upgrade still replay idempotently.
  6. **Docs.** Update `docs/EXECUTION.md`:
     - a save stores new chunk and manifest bytes, then commits the new rows, the pointer and one `session.saved` event in one transaction;
     - chunks carry no `artifact.created` event;
     - encoding stays on the loop by design;
     - add to the stored-shape list (F7): no per-chunk `artifact.created` event or command row, and one `runtime.save` transaction per save.
- [ ] **Step 5: Run the tests and commit.** Run `... -m pytest tests/test_native_checkpoint_chunks.py tests/test_session_events.py tests/test_execution_responses.py tests/test_execution_context.py tests/test_controller_continuation.py tests/test_reproduction.py tests/test_private_artifact_kinds.py -q`; it should PASS. Commit (G7), including the fixture: `perf: encode checkpoints in one pass and commit each save in one transaction`.

---

### Task 10: Coalesce saves to four per single-call turn (#10d)

**Files:**
- Modify `responses.py`: `_receive_turn_note` (369–394), `_loop` (the settlement and terminal saves), `_run_calls`, and a new `_emit_completed`.
- Modify the pinned test, two crash trips in `tests/test_execution_context.py`, and `docs/EXECUTION.md:111-114`.

**Interfaces:**
- Consumes from Task 3: `_save -> RuntimeCheckpoint` and `_maybe_handoff(checkpoint=)`.
- Produces:
  - `_run_calls(...) -> list[tuple[str, str, str | None, dict | None]]`, the unsaved tuples of (operation, name, signal, stagnation snapshot);
  - `_emit_completed(session, completed)`;
  - `COALESCED_SAVE_SHAPES`.

**Save points.** Each turn saves at:
- **A**, the generation marker, which now also carries any turn note;
- **B**, the response, before `usage`;
- **D_k**, one per dispatched call: its marker, the settlement and the earlier outputs;
- **F**, the last output and the settled boundary.

A one-call turn therefore makes 4 saves, and a k-call turn makes 3 + k; the ruling accepts this, since R6 needs a marker per call (F5). A peer delivery adds U (I3), and a compaction adds its marker and prune saves. Until the next save the durable state is B, which holds the generation marker, so a crash stays uncertain (I1 and I2 hold).

- [ ] **Step 1: Write the failing tests.** Change the pinned test to `assert store.shapes == COALESCED_SAVE_SHAPES`, and add:
```python
COALESCED_SAVE_SHAPES = [
    (None, True, "ready"), (None, True, "running"),
    ("generation", True, "running"), ("generation", False, "running"),  # A, B
    ("tool", False, "running"), (None, True, "running"),  # D1 (settlement + marker), F
    ("generation", True, "running"), ("generation", False, "running"),  # A, B
    (None, True, "running"), (None, True, "completed")]  # terminal pending, completed

async def test_multi_call_turn_saves_one_marker_per_call_and_announces_after_saving(tmp_path):
    completed_at = []
    class OutputCounting(RecordingStore):
        async def save(self, checkpoint):
            await super().save(checkpoint)
            self.outputs = sum(i.get("type") == "function_call_output" for i in checkpoint.native_state["input"])
    store = OutputCounting(tmp_path / "s.db")
    async def emit(event):
        if event.kind == "tool_completed":
            completed_at.append(store.outputs)
    client = client_for([response([double_call("call_1"), double_call("call_2")]),
                         response([message("done")], response_id="resp_2")], [])
    await ResponsesRuntime(store=store, dispatcher=double_dispatcher(), client=client, event_sink=emit).start(
        "x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert store.shapes[2:7] == [("generation", True, "running"), ("generation", False, "running"),
                                 ("tool", False, "running"), ("tool", False, "running"), (None, True, "running")]
    assert completed_at == [1, 2]
    await client.close()

async def test_turn_note_rides_on_the_generation_marker_save(tmp_path):
    requests = []
    async def note(turns):
        return "Check in now." if turns == 1 else None
    client = client_for([response([double_call()]), response([message("4")], response_id="resp_2")], requests)
    store = RecordingStore(tmp_path / "s.db")
    await ResponsesRuntime(store=store, dispatcher=double_dispatcher(), client=client, turn_note=note).start(
        "compute", ModelConfig(model="exact-model"), RuntimeLimits())
    assert store.shapes == COALESCED_SAVE_SHAPES
    assert "research_runtime_note" in [p for u, p in requests if u.endswith("/responses")][1]["input"][-1]["content"]
    await client.close()
```
  In `tests/test_execution_context.py`, move the two trips that aimed at the old settlement save of a tool response onto the first tool marker:
  - `test_interrupted_response_before_tool_output_is_not_safe_to_resume` trips on `not self.tripped and (state.get("pending_operation") or "").endswith(":a")` and asserts `native["session"]["status"] == "uncertain"`.
  - `test_later_tool_response_clears_stale_compaction_recovery_marker` trips on `not self.tripped and checkpoint.session.turns == 2 and (state.get("pending_operation") or "").endswith(":a")`.
  - The compaction recovery trips stay as they are; they now match the compaction-marker save.
- [ ] **Step 2: Run the new tests.** `... -m pytest tests/test_execution_responses.py tests/test_execution_context.py -q -k "pinned or marker or note or interrupted or stale_compaction"` should FAIL.
- [ ] **Step 3: Implement.**
  1. `_receive_turn_note` deletes its final `_save`. The note is then durable in save A, before the provider sees it, or in `_run`'s failure save.
  2. After the `usage` emit, keep the marker clear, `settled_response` and the `compaction_replay_pending` pop, but delete the save that followed them. Comment: `# The next save records settlement (compaction marker, first tool marker, terminal save or _run's failure save); until then B still holds the generation marker, so a crash stays uncertain.`
  3. In the terminal branch, set `settled_boundary = True` and `terminal_response_pending = True`, build the `artifact`, then run `checkpoint = await self._save(session, state)` and `_maybe_handoff(..., output_text=text, artifacts=[artifact], checkpoint=checkpoint)`. The completion that follows is unchanged.
  4. In `_run_calls`:
     - Keep `unsaved = []` and return it.
     - After the marker save D_k, call `await self._emit_completed(session, unsaved)` and reset `unsaved = []`.
     - After appending the output and clearing the marker, delete the old save and emits. Append `(tool_operation, call["name"], signal, dict(state["stagnation"]) if signal else None)` to `unsaved`.
  5. Add:
```python
    async def _emit_completed(self, session, completed) -> None:
        """Announce tool results only after the save that made them durable."""
        for tool_operation, name, signal, snapshot in completed:
            await self._emit("tool_completed", session, tool_operation, name=name)
            if signal is not None:
                await self._emit(signal, session, tool_operation, stagnation_state=snapshot)
```
  6. The tail of `_loop` becomes: `completed = await self._run_calls(...)`, then `_advance_active_input`, then `settled_boundary = True`, then `checkpoint = await self._save(...)`, then `await self._emit_completed(session, completed)`, then `_maybe_handoff(..., checkpoint=checkpoint)`.
  7. **Docs.** `docs/EXECUTION.md:111-114` lists the save points above. A fatal tool error, a cancellation or a failed settlement is recorded by `_run`'s failure save. Add to the stored-shape list (F7): fewer saves per turn (4 for a single call, 3 + k for k calls), and `tool_completed` is emitted after the save that made its output durable.
- [ ] **Step 4: Run the tests and commit.** Run `... -m pytest tests/test_execution_responses.py tests/test_execution_context.py tests/test_research_context_policy.py tests/test_society_scaffolding.py tests/test_controller_continuation.py tests/test_joined_delegation.py tests/test_network_runtime.py tests/test_society_tools.py -q`; it should PASS. If some other test's crash trip aimed at a removed save, move it to the next durable point, keep its assertions, and report it. Commit (G7): `perf: coalesce runtime saves to four per single-call turn`.

---

### Task 11: Context budget, part 1: policy, literal Unicode, output cap and `recall_output` (#5e, #7, R7)

**Files:**
- Modify `domain.py:120-137`, `service.py:904-908`, `run_control.py:55-100,205-221`, `context_policy.py` and `stagnation.py:10-51`.
- Modify `responses.py`: new constants and helpers; `__init__`, `start`, `start_from_handoff` and `_run`; the tools argument; `_find_tool_result` and `_run_calls`.
- Modify `research_worker.py:1682-1749`.
- Update `docs/EXECUTION.md` and `work/society-s1/RUN_PLAN.md`.
- Tests in `tests/test_execution_context.py`, `tests/test_research_context_policy.py`, `tests/test_orchestration.py` and `tests/test_joined_delegation.py`.

**Interfaces:**
- **Consumes:**
  - Task 10: `_run_calls` and `unsaved`;
  - Task 4: `_request_elements`, which digests the tools array this task changes;
  - Task 4: `observe_dispatcher`, `COMPACTING` and `WIDE`;
  - Task 7: `KeywordRuntime`;
  - Task 5: `started_task` and `PRICES`.
- **Produces:**
  - `domain.ContextBudget`, with `elide_min_chars` = 4000 (≥ 500), `elide_after_turns` = 5 (≥ 1), `elide_every_turns` = 10 (≥ 1) and `max_output_chars: int | None` = 24000 (≥ 20000). R7's "cap whole-file reads" is this uniform per-output cap, and it applies only under `context_budget` (F6);
  - `ExperimentCreate.context_budget` and `RunPlan.context_budget`;
  - the profile `"research_lean"`;
  - `RECALL_OUTPUT_TOOL` and `request_tools(definitions, budget) -> list[dict]`;
  - `ResponsesRuntime(..., context_budget=None)`;
  - the native-state key `context_budget`, which continuations keep;
  - `_find_tool_result(..., *, match_suffix=False)`;
  - the test helpers `big_result(size)`, `recall_item(call_id, target, offset)`, `outputs_of(payload)` and `creates_of(requests)`.

- [ ] **Step 1: Write the failing tests.** Import `ContextBudget` from `physharness.domain`:
```python
BUDGET = ContextBudget(max_output_chars=20_000)

def big_result(size):
    return {"text": "∀" + "x" * size}

def recall_item(call_id, target, offset):
    return {"id": "fc-" + call_id, "type": "function_call", "call_id": call_id, "name": "recall_output",
            "arguments": json.dumps({"call_id": target, "offset": offset}), "status": "completed"}

def outputs_of(payload):
    return {i["call_id"]: i["output"] for i in payload["input"] if i.get("type") == "function_call_output"}

def creates_of(requests):
    return [payload for path, payload in requests if path.endswith("/responses")]

async def test_oversized_output_is_truncated_and_recalled_exactly(tmp_path):
    requests = []
    client = sdk_client([response([call_item("a")], "r1"), response([recall_item("p1", "a", 0)], "r2"),
                         response([recall_item("p2", "a", 16_000)], "r3"),
                         response([recall_item("p3", "a", 32_000)], "r4"), response([text_item("done")], "r5")],
                        requests)
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "sessions.db"), client=client,
                               dispatcher=observe_dispatcher(big_result(40_000)), context_budget=BUDGET)
    await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None))
    creates = creates_of(requests)
    assert creates[0]["tools"][-1]["name"] == "recall_output"
    outputs, original = outputs_of(creates[-1]), json.dumps(big_result(40_000), ensure_ascii=False)
    view = json.loads(outputs["a"])
    assert (view["truncated"], view["total_chars"], view["head"]) == (True, len(original), original[:10_000])
    assert view["recall"] == {"tool": "recall_output", "call_id": "a", "next_offset": 10_000}
    pages = [json.loads(outputs[p]) for p in ("p1", "p2", "p3")]
    assert "".join(p["text"] for p in pages) == original
    assert [p["next_offset"] for p in pages] == [16_000, 32_000, None]
    await client.close()

async def test_recall_output_after_native_handoff_uses_the_stored_policy(tmp_path):
    requests, store = [], SQLiteRuntimeStore(tmp_path / "sessions.db")
    model, limits = ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
    async def boundary(checkpoint):
        return {"reason": "test_handoff"}
    first = sdk_client([response([call_item("a")], "r1")], requests)
    source = ResponsesRuntime(store=store, client=first, dispatcher=observe_dispatcher(big_result(100)),
                              boundary_hook=boundary, context_budget=BUDGET)
    handed = await source.start("work", model, limits)
    second = sdk_client([response([recall_item("p1", "a", 0)], "r2"), response([text_item("done")], "r3")],
                        requests)
    successor = ResponsesRuntime(store=store, client=second, dispatcher=observe_dispatcher(big_result(100)))
    await successor.start_from_handoff(await source.checkpoint(handed.session.id), "continue", model, limits)
    final = creates_of(requests)[-1]
    assert final["tools"][-1]["name"] == "recall_output"
    assert json.loads(outputs_of(final)["p1"])["text"] == json.dumps(big_result(100), ensure_ascii=False)
    await first.close()
    await second.close()

async def test_no_context_budget_keeps_requests_and_state_unchanged(tmp_path):
    requests = []
    client = sdk_client([response([call_item("a")], "r1"), response([text_item("done")], "r2")], requests)
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "sessions.db"), client=client,
                               dispatcher=observe_dispatcher(big_result(30_000)))
    result = await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None))
    creates = creates_of(requests)
    assert all(tool["name"] != "recall_output" for p in creates for tool in p["tools"])
    assert outputs_of(creates[1])["a"] == json.dumps(big_result(30_000), allow_nan=False)  # escaped, uncapped
    assert "context_budget" not in (await runtime.checkpoint(result.session.id)).native_state
    await client.close()
```
  In `tests/test_research_context_policy.py` (import `ContextBudget`, `ExperimentCreate`, `NON_PROGRESS_TOOLS` and `READ_TOOLS`):
```python
def test_research_lean_profile_and_recall_read():
    model = ModelConfig(model="exact-model")
    def threshold(window, output):
        limits = RuntimeLimits(max_context_tokens=window, max_output_tokens=output, max_total_tokens=None)
        return apply_context_profile(model, limits, "research_lean").parameters[
            "context_management"][0]["compact_threshold"]
    assert (threshold(256_000, 64_000), threshold(100_000, 4_096)) == (96_000, 87_712)
    assert "recall_output" in READ_TOOLS and "recall_output" in NON_PROGRESS_TOOLS

def test_context_budget_bounds_and_opt_in_experiment_payload(lab):
    from test_core import setup_experiment
    with pytest.raises(ValueError):
        ContextBudget(max_output_chars=1_000)
    service, actor, _ = lab
    experiment, problem = setup_experiment(lab)
    assert "context_budget" not in experiment
    budgeted = service.create_experiment(ExperimentCreate(
        campaign_id=problem["campaign_id"], problem_id=problem["id"],
        models=[{"runtime": "responses", "model": "explicit-test-model"}],
        budget={"max_cost_usd": "1.00", "max_concurrency": 1, "max_runtime_seconds": 600},
        context_budget={"elide_every_turns": 8}), actor, "budgeted")
    assert budgeted["context_budget"] == {"elide_min_chars": 4000, "elide_after_turns": 5,
                                          "elide_every_turns": 8, "max_output_chars": 24000}
```
  In `tests/test_orchestration.py`:
```python
@pytest.mark.asyncio
async def test_executor_passes_context_budget_and_digests_recall_tool(lab):
    from physharness.domain import ExperimentCreate, digest_json
    from physharness.execution.responses import RECALL_OUTPUT_TOOL
    from physharness.orchestration.research_worker import ResearchTaskExecutor
    service, actor, _ = lab
    _, problem = setup_experiment(lab)
    budgeted = service.create_experiment(ExperimentCreate(
        campaign_id=problem["campaign_id"], problem_id=problem["id"],
        models=[{"runtime": "responses", "model": "explicit-test-model"}],
        budget={"max_cost_usd": "1.00", "max_concurrency": 2, "max_runtime_seconds": 600},
        context_budget={"elide_every_turns": 8}), actor, "budgeted-experiment")
    service, actor, experiment, task = started_task(lab, budgeted)
    executor = ResearchTaskExecutor(service, prices=PRICES, runtime_factory=KeywordRuntime)
    assert (await executor.execute(task["id"], actor.project_id))["status"] == "completed"
    assert KeywordRuntime.seen["context_budget"].elide_every_turns == 8
    record = service.list_records("session", actor, experiment["id"])[0]
    assert record["tool_definition_digest"] == digest_json(
        [*KeywordRuntime.seen["dispatcher"].definitions, RECALL_OUTPUT_TOOL])
```
  In `tests/test_joined_delegation.py`, guard the cross-lane order (F8): a wait under a `context_budget` must still resume natively. On main the only native wait reason is `joined_children`. Parametrize `test_parent_final_response_joins_child_with_one_slot_and_no_paid_replay` with `@pytest.mark.parametrize("context_budget", [None, {}])` and add the `context_budget` argument. The test's route already asserts that the woken parent's request still holds the `parent-delegate` output, and only a native resume keeps it, because a portable successor starts a fresh context. The budgeted case therefore fails if `native_compatible` sees a different tool digest after the wait than the one stored before it. Change the test in three places:
  - Replace `experiment, _ = setup_experiment(lab, concurrency=1)` with:
```python
    experiment, problem = setup_experiment(lab, concurrency=1)
    if context_budget is not None:  # F8: a budgeted wait must still resume natively
        experiment = service.create_experiment(ExperimentCreate(
            campaign_id=problem["campaign_id"], problem_id=problem["id"],
            models=[{"runtime": "responses", "model": "explicit-test-model"}],
            budget={"max_cost_usd": "1.00", "max_concurrency": 1, "max_runtime_seconds": 600},
            context_budget=context_budget), actor, "budgeted-experiment")
```
  - Add `seen_tools = []` next to `seen_joined = []`, and `seen_tools.append([tool["name"] for tool in payload["tools"]])` next to `seen_joined.append(...)`.
  - After the existing assertions, add `assert ("recall_output" in seen_tools[0]) == (context_budget is not None)`.

  The society lane rebases onto this lane, and this test is what keeps its edits to the same `execute` block from turning budgeted waits portable.
- [ ] **Step 2: Run the new tests.** `... -m pytest tests/test_execution_context.py tests/test_research_context_policy.py tests/test_orchestration.py tests/test_joined_delegation.py -q -k "recall or budget or lean or truncated or joins_child"` should FAIL (the budgeted join case cannot build its experiment yet).
- [ ] **Step 3: Configuration.**
  1. In `domain.py`, add before `ExperimentCreate`:
```python
class ContextBudget(StrictModel):
    """Opt-in context shaping for a Responses session (R7); absent means today's behaviour."""
    elide_min_chars: int = Field(default=4000, ge=500, le=1_000_000)
    elide_after_turns: int = Field(default=5, ge=1, le=1000)
    elide_every_turns: int = Field(default=10, ge=1, le=1000)
    max_output_chars: int | None = Field(default=24_000, ge=20_000, le=1_000_000)
```
     In `ExperimentCreate`, set `context_profile: Literal["research", "research_lean", "stress8192"] = "research"` and add `context_budget: ContextBudget | None = None`.
  2. In `service.create_experiment`, next to the `society` pop, add `if data.get("context_budget") is None: data.pop("context_budget", None)`. Legacy payloads and fingerprints stay byte-identical.
  3. `RunPlan` gets the same literal and field. `recorded()` uses `exclude = {n for n in ("society", "context_budget") if getattr(self, n) is None}` with `exclude=exclude or None`, and line 217 passes `context_budget=plan.context_budget`.
  4. In `context_policy.py`:
     - Set `ContextProfile = Literal["research", "research_lean", "stress8192"]` and `LEAN_THRESHOLD = 96_000`.
     - Accept all three profiles.
     - `research_lean` uses the threshold `min(LEAN_THRESHOLD, maximum)`.
  5. In `stagnation.py`, add `"recall_output"` to `READ_TOOLS` with the comment `# Re-reading an elided or truncated output (context budget).`
- [ ] **Step 4: Change the runtime.** Import `ContextBudget` from `..domain`, and add at module level:
```python
RECALL_PAGE_CHARS = 16_000

RECALL_OUTPUT_TOOL = {
    "type": "function", "name": "recall_output", "strict": True,
    "description": "Re-read the full output of an earlier tool call that was shortened in context. "
                   "Returns up to 16,000 characters from offset; pass next_offset to continue.",
    "parameters": {"type": "object", "additionalProperties": False, "required": ["call_id", "offset"],
                   "properties": {"call_id": {"type": "string", "description": "The shortened output's call_id."},
                                  "offset": {"type": "integer", "minimum": 0, "description": "Start at 0."}}},
}

def request_tools(definitions: list[dict[str, Any]], budget: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Tool definitions actually sent: the registered tools, plus recall under a budget."""
    return [*definitions, RECALL_OUTPUT_TOOL] if budget else list(definitions)

def _tool_output_text(budget: dict[str, Any] | None, call: dict[str, Any], visible: dict[str, Any]) -> str:
    """Model-visible output. Under a budget Unicode stays literal (#5e) and a long output becomes a
    head plus a recall handle; the full value stays in tool_results."""
    text = json.dumps(visible, allow_nan=False, ensure_ascii=not budget)
    limit = budget.get("max_output_chars") if budget else None
    if limit is None or call["name"] == "recall_output" or len(text) <= limit:
        return text
    head = limit // 2  # an escaped head is at most twice as long, so the view fits the cap
    return json.dumps({"truncated": True, "tool": call["name"], "total_chars": len(text), "head": text[:head],
                       "recall": {"tool": "recall_output", "call_id": call["call_id"], "next_offset": head}},
                      ensure_ascii=False)
```
  1. `__init__` gains `context_budget=None`. `start` stores `state["context_budget"] = self.context_budget.model_dump(mode="json")` when it is set, and `start_from_handoff` deep-copies `prior["context_budget"]` when present.
  2. At the top of `_run`, when the state has a budget and a registered tool is named `recall_output`, raise `ExecutionError("INVALID_CONFIG", "recall_output is reserved for the context budget")`.
  3. Both the count and the create send `tools=request_tools(self.dispatcher.definitions, state.get("context_budget"))`. In `_prepare_request`, Task 4's local `tools` becomes that value, so the count and `_request_elements` see exactly the array the create sends. Under P1 the tools array is one positional element: a change to it is counted at its full size, and the element is otherwise constant within a session.
  4. `_find_tool_result` gains `match_suffix=False`, and all three lookups go through a local `pick(results)`. With `match_suffix`, `pick` returns `next((v for k, v in reversed(list(results.items())) if k.endswith(f":{key}")), None)`; otherwise it returns `results.get(key)`. Then add `_recall`:
```python
    async def _recall(self, session, state, arguments) -> dict[str, Any]:
        """A page of a stored tool output. A pure read: no marker and no dispatcher."""
        call_id, offset = arguments.get("call_id"), arguments.get("offset")
        if not isinstance(call_id, str) or not 0 < len(call_id) <= 200 or type(offset) is not int or offset < 0:
            return {"error": {"code": "INVALID_TOOL_ARGUMENTS", "message": "Give call_id and offset >= 0."}}
        if (entry := await self._find_tool_result(session, state, call_id, match_suffix=True)) is None:
            return {"error": {"code": "RECALL_NOT_FOUND", "message": "No stored output has this call_id."}}
        text = json.dumps(entry.get("visible_output", entry["result"]), allow_nan=False, ensure_ascii=False)
        page = text[offset : offset + RECALL_PAGE_CHARS]
        end = offset + len(page)
        return {"call_id": call_id, "offset": offset, "next_offset": end if end < len(text) else None,
                "total_chars": len(text), "text": page}
```
  5. After `identity = digest(...)`, the `_run_calls` loop body becomes:
```python
            recall = call["name"] == "recall_output" and bool(state.get("context_budget"))
            results = state.setdefault("tool_results", {})
            previous = None if recall else await self._find_tool_result(session, state, tool_operation)
            if previous is not None:
                ...  # identity check and replay, unchanged
            else:
                if recall:
                    result = await self._recall(session, state, arguments)
                else:
                    state["pending_operation"] = tool_operation
                    await self._save(session, state)
                    await self._emit_completed(session, unsaved)
                    unsaved = []
                    result = await self.dispatcher.dispatch(call["name"], arguments, tool_operation)
                signal = observe_stagnation(state.setdefault("stagnation", {}), call["name"], arguments, result)
                visible_output = ...  # signal wrapping, unchanged
                if not recall:
                    entry = {"identity": identity, "result": result}
                    if visible_output is not result:
                        entry["visible_output"] = visible_output
                    results[tool_operation] = entry
            state["input"].append({"type": "function_call_output", "call_id": call["call_id"],
                                   "output": _tool_output_text(state.get("context_budget"), call, visible_output)})
            state["pending_operation"] = None
            unsaved.append((tool_operation, call["name"], signal, dict(state["stagnation"]) if signal else None))
```
  6. In the worker:
     - Move `parameters = ...` and Task 7's `accepts_any` above `store.tool_definition_digest`, and import `ContextBudget` and `request_tools`. The resulting order is binding, because the society lane rebases onto it (F8): `parameters` → `accepts_any` → the budget-inclusive tool digest → `native_compatible` → the hooks → the governor → `context_budget`. The digest must be set before `native_compatible` reads it, or every budgeted wait silently goes portable.
     - Set `context_budget = experiment.get("context_budget")` and `pass_budget = bool(context_budget) and ("context_budget" in parameters or accepts_any)`.
     - Set `store.tool_definition_digest = digest_json(request_tools(dispatcher.definitions, context_budget if pass_budget else None))`.
     - After the governor block, add `if pass_budget: runtime_kwargs["context_budget"] = ContextBudget.model_validate(context_budget)`.
  7. **Docs.**
     - `docs/EXECUTION.md` gets a "Context budget (opt-in)" section. It covers:
       - the field and its defaults, stored in native state so that continuations keep it;
       - literal Unicode;
       - the cap: head plus recall handle, with the full output kept in `tool_results`;
       - `recall_output`, which returns 16,000-character pages and searches active results, then own archives, then inherited archives;
       - `research_lean`, whose threshold is `min(96,000, window − max_output − 8,192)`;
       - that a changed `tool_definition_digest` makes in-flight native handoffs fall back to portable ones.
     - `work/society-s1/RUN_PLAN.md`: give an example A/B arm (`"context_budget": {}`, `"context_profile": "research_lean"`, `max_context_tokens: 128000`), marked opt-in until a quality A/B has run.
- [ ] **Step 5: Run the tests and commit.** Run `... -m pytest tests/test_execution_context.py tests/test_execution_responses.py tests/test_research_context_policy.py tests/test_orchestration.py tests/test_joined_delegation.py tests/test_run_control.py tests/test_society_tools.py tests/test_reproduction.py tests/test_society_scaffolding.py -q`. It should PASS, with the freeze tests unmodified. Commit (G7): `feat: opt-in context budget with literal Unicode, output cap and recall_output`.

---

### Task 12: Context budget, part 2: block-wise elision (#7, R7)

**Files:**
- Modify `responses.py`: `start` and `start_from_handoff`, the counter at save B, the call in `_loop`, the entry fields, and new `_elision_stub`, `_is_elision_stub` and `_elide_block`.
- Update `docs/EXECUTION.md`.
- Test in `tests/test_execution_context.py`.

**Interfaces:**
- Consumes Task 11's budget state and helpers, Task 2's `_emit_telemetry`, and Task 4's `_last_request` baseline and P1 bound.
- Produces:
  - the state `elision = {"seq", "last_block_seq"}`, where `seq` counts provider responses across the whole lineage;
  - the entry fields `seq` and `name`;
  - the event `context_elided`, with `count`, `chars_removed`, `first_index` and `seq`;
  - `_elide_block(session, state)`.

- [ ] **Step 1: Write the failing tests.**
```python
ELIDE = ContextBudget(elide_min_chars=500, elide_after_turns=1, elide_every_turns=3, max_output_chars=None)

async def run_elided(tmp_path, requests, events, calls, store=None):
    async def emit(event):
        events.append(event)
    client = sdk_client([*[response([call_item(f"c{i}")], f"r{i}") for i in range(1, calls + 1)],
                         response([text_item("done")], "rt")], requests)
    runtime = ResponsesRuntime(store=store or SQLiteRuntimeStore(tmp_path / "sessions.db"), client=client,
                               dispatcher=observe_dispatcher(big_result(2_000)), event_sink=emit, context_budget=ELIDE)
    result = await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None))
    await client.close()
    return runtime, result

async def test_elision_blocks_keep_the_prefix_stable_between_boundaries(tmp_path):
    requests, events = [], []
    await run_elided(tmp_path, requests, events, calls=6)
    inputs = [p["input"] for p in creates_of(requests)]
    assert [inputs[n + 1][: len(inputs[n])] == inputs[n] for n in range(6)] == [True, True, False, True, True, False]
    assert [e.payload["count"] for e in events if e.kind == "context_elided"] == [2, 3]
    fourth = outputs_of({"input": inputs[3]})
    assert json.loads(fourth["c1"])["recall"] == {"tool": "recall_output", "call_id": "c1"}
    assert fourth["c3"].startswith('{"text"')

async def test_elision_skips_small_recent_and_legacy_outputs(tmp_path):
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "sessions.db"), client=object())
    session = RuntimeSession(runtime="openai_responses", model=ModelConfig(model="exact-model"),
                             limits=RuntimeLimits())
    big = json.dumps({"text": "x" * 1_000})
    outputs, seqs = {"legacy": big, "small": "{}", "recent": big, "old": big}, {"small": 1, "recent": 3, "old": 1}
    state = {"input": [{"type": "function_call_output", "call_id": k, "output": v} for k, v in outputs.items()],
             "tool_results": {f"{session.id}:{k}": {"identity": "i", "result": {},
                                                    **({"seq": seqs[k], "name": "observe"} if k in seqs else {})}
                              for k in outputs},
             "context_budget": ELIDE.model_dump(mode="json"), "elision": {"seq": 3, "last_block_seq": 0}}
    await runtime._elide_block(session, state)
    after = {i["call_id"]: i["output"] for i in state["input"]}
    assert (after["legacy"], after["small"], after["recent"]) == (big, "{}", big)
    assert json.loads(after["old"])["elided"] is True and state["elision"]["last_block_seq"] == 3

async def test_elision_state_survives_resume_without_reeliding(tmp_path):
    requests, events = [], []
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime, result = await run_elided(tmp_path, requests, events, calls=3, store=store)
    saved = (await runtime.checkpoint(result.session.id)).native_state
    assert saved["elision"] == {"seq": 4, "last_block_seq": 3}
    second = sdk_client([response([text_item("again")], "r5")], requests)
    resumed = ResponsesRuntime(store=store, client=second, dispatcher=observe_dispatcher(big_result(2_000)))
    assert (await resumed.continue_session(result.session.id, "next")).output_text == "again"
    assert creates_of(requests)[-1]["input"][:-1] == saved["input"]
    assert len([e for e in events if e.kind == "context_elided"]) == 1
    await second.close()
```
- [ ] **Step 2: Run the new tests.** `... -m pytest tests/test_execution_context.py -q -k elision` should FAIL.
- [ ] **Step 3: Implement.**
  1. `start` sets `state["elision"] = {"seq": 0, "last_block_seq": 0}` next to `context_budget`. `start_from_handoff` deep-copies `prior["elision"]`, because the counter is lineage-wide.
  2. In `_loop`, right after Task 4's `self._last_request[session.id] = ...` baseline at save B, add `if isinstance(state.get("elision"), dict): state["elision"]["seq"] += 1`.
  3. In `_run_calls`, for a non-recall entry, add `if isinstance(state.get("elision"), dict): entry.update(seq=state["elision"]["seq"], name=call["name"])`. Entries without `seq` are never elided.
  4. Add the helpers and the method:
```python
def _elision_stub(tool: str, call_id: str, output: str) -> str:
    return json.dumps({"elided": True, "tool": tool, "chars": len(output),
                       "sha256": hashlib.sha256(output.encode("utf-8")).hexdigest()[:16], "head": output[:160],
                       "recall": {"tool": "recall_output", "call_id": call_id}},
                      separators=(",", ":"), ensure_ascii=False)

def _is_elision_stub(output: Any) -> bool:
    return isinstance(output, str) and output.startswith('{"elided":true')
```
```python
    async def _elide_block(self, session, state) -> None:
        """Replace old large tool outputs with recall stubs, once per block of responses.
        Between blocks the input prefix is byte-stable, so provider prefix caching holds; a block
        breaks it once, at its first newly elided item. Full outputs stay in tool_results for
        recall_output. Runs at a settled boundary before request preparation; the generation
        marker save persists it.
        """
        budget, elision = state.get("context_budget"), state.get("elision")
        if not budget or not isinstance(elision, dict):
            return
        seq = elision["seq"]
        if seq - elision["last_block_seq"] < budget["elide_every_turns"]:
            return
        entries = {key.split(":", 1)[1]: entry for key, entry in state.get("tool_results", {}).items()}
        count = removed = 0
        first = None
        for index, item in enumerate(state["input"]):
            entry, output = entries.get(item.get("call_id")), item.get("output")
            if (item.get("type") != "function_call_output" or not isinstance(entry, dict)
                    or type(entry.get("seq")) is not int or entry["seq"] > seq - budget["elide_after_turns"]
                    or not isinstance(output, str) or len(output) <= budget["elide_min_chars"]
                    or _is_elision_stub(output)):
                continue
            item["output"] = _elision_stub(entry.get("name", "unknown"), item["call_id"], output)
            count, removed = count + 1, removed + len(output) - len(item["output"])
            first = index if first is None else first
        elision["last_block_seq"] = seq
        if count:
            await self._emit_telemetry("context_elided", session, count=count, chars_removed=removed,
                                       first_index=first, seq=seq)
```
  5. In `_loop`, call `await self._elide_block(session, state)` right after `_receive_turn_note`, so `_prepare_request` sees the stubs. Task 4's P1 bound stays sound without special handling. Each replaced output is no longer byte-identical to the element at its position, so it counts at its new (stub) size, and the removed bytes earn no credit. A block's first request therefore adds every stub's size to its bound; the requests between blocks bound only their appended items.
  6. **Docs.** `docs/EXECUTION.md` describes:
     - the rule: every `elide_every_turns` responses, each output longer than `elide_min_chars` from a response at least `elide_after_turns` old becomes a recall stub;
     - that the prefix is byte-stable between blocks;
     - the `context_elided` event;
     - the state keys;
     - that making it a default needs a quality A/B, with block sizes of 8–20 recommended.
- [ ] **Step 4: Run the tests and commit.** Run `... -m pytest tests/test_execution_context.py tests/test_execution_responses.py tests/test_research_context_policy.py tests/test_society_scaffolding.py -q`; it should PASS. Commit (G7): `feat: block-wise elision of stale tool outputs under the context budget`.

---

### Task 13: Documentation sweep, full suite and lint

**Files:** `docs/EXECUTION.md`, `docs/DEPLOYMENT.md`, `docs/FIRST_LIVE_RUN.md`, `docs/OPERATIONS.md`, `docs/IMPLEMENTATION_STATUS.md`, `work/society-s1/RUN_PLAN.md` and `PLAN.md` (§6.2, §6.3).

- [ ] **Step 1: Sweep for stale text.** Run `grep -n "preflights each request\|input_tokens.count\|256000\|64000\|conservatively omitted\|one action per turn" docs/*.md work/society-s1/RUN_PLAN.md PLAN.md` and fix every hit that describes old behaviour. Then check coverage:
  - `EXECUTION.md` covers throttling and the give-up, the count policy, the P1 bound, reservations and the provider compaction assumption with `bound_reservation_compacted` (F4), cached pricing, the governor (a count 429 only pauses, F10), parallel calls, save points, one transaction per save, slim responses and the context budget. Its "Stored shape changes" list names every stored ledger and event change from Tasks 2–10 (F7): the `usage` and `generation_started` keys, slim stored responses, fewer saves, smaller reservations and no per-chunk `artifact.created`.
  - `DEPLOYMENT.md` covers the new env variable, the cached-rate field and WAL.
  - `OPERATIONS.md` covers WAL backups.
  - `RUN_PLAN.md` covers:
    - `max_output_tokens: 16000`;
    - governor sizing: about 0.55M TPM per agent, set at 90% of the org limit ÷ processes;
    - the opt-in budget and profile;
    - no price changes mid-run;
    - re-pricing S1 before any S1-vs-S2 cost comparison once a cached rate is set (`tools/society_metrics.py` reads the ledger).
  - `PLAN.md` §6.2 says saves are slim, coalesced and one transaction each, and that encoding off the loop is future work.
- [ ] **Step 2: Add a status entry.** Add "S1 runtime remediation — 2026-09-26" to `docs/IMPLEMENTATION_STATUS.md`, with one line per task, the Task 6 G4 result (the raw and the with-margin max ratios, F3), the suite count from Step 3, and the G6 next steps (including F9's bound carry across a native handoff).
- [ ] **Step 3: Run the full suite and lint.**
```bash
PYTHONPATH=src .venv/bin/python -m pytest -m "not integration and not lean" -q
.venv/bin/ruff check src tests tools infra migrations
.venv/bin/ruff format --check src tests tools infra migrations
git diff origin/main | grep -n "/Use[r]s/\|$(whoami)" || true
```
  Expected: all tests pass (report the counts), ruff is clean, and the grep prints nothing.
- [ ] **Step 4: Commit** (G7): `docs: runtime remediation limits, pricing, governor, checkpoints and context budget`.

---

## Spec coverage

- Tier 0 #6 is main's give-up plus Task 2's telemetry, #4 is Tasks 5–6, and #5 (`ensure_ascii` in `responses.py`) is Task 11, where it is opt-in under `context_budget` (G1/G3).
- Tier 1: #9 is Task 4; #10a/b/g/h is Task 3; #10c/f is Task 9; #10d is Task 10; #8 is Task 7 (the org limit is G6); #11 is Task 8; #7 is Tasks 11–12.
- #10e (off-loop saves) is not done, per R4; it is a G6 next step.
- §3A is covered by Tasks 2 and 7, §3B by Tasks 11–12, and §3G by Tasks 3, 4, 9 and 10.

## Controller rulings applied (2026-09-27)

- **F1.** The plan is re-based onto origin/main 7202266:
  - Tasks 1, 2, 3, 4, 7 and 10 now cite main's line ranges. Task 1's `_prepare_request` takes `deadline`.
  - Task 2 is cut to telemetry through an `on_wait` hook. Its duplicate give-up code and test are dropped, and main's interrupt test gains `provider_throttled`.
  - Task 4's create 400 branch wraps `_resend_rate_limited` and reuses `_abandon_refused(reason=)`.
  - Task 7 re-queues inside the same hook and keeps abandon-on-interrupt.
  - Main's order holds everywhere: emit `generation_aborted`, then clear `pending_operation`.
- **F2.** P1 is a positional diff over the instructions, the tools and each input item. The per-session digests live in memory in `_last_request`, dropped when `_run` exits. The margin is `max(2048, ceil(2%·B))`, and the same margin-inclusive bound drives the reservation, the count skip and admission (Global G4; Tasks 4, 6, 7, 11 and 12).
- **F3.** The Task 6 gate stops only when `max_ratio_raw > 1`. `max_ratio` (about 0.98) is recorded and reported through `margin_expected_met` (Task 6's tool, test and Step 2; Task 13).
- **F4.** The rule "margin-inclusive `bound + 8192 <= compact_threshold`" is kept. Task 6 adds the `bound_reservation_compacted` alarm with a test and documents the provider assumption. `max_output_tokens: 16000` stays a documented recommendation.
- **F5.** A single-call turn makes 4 saves, and a turn with k calls makes 3 + k (Global R4, Task 10).
- **F6.** A uniform per-output cap, `max_output_chars`, applies only under `context_budget` (Global R7, Task 11).
- **F7.** G1 covers model-visible bytes and the freeze tests. Task 2 starts a "Stored shape changes" list in `docs/EXECUTION.md`; Tasks 3, 4, 5, 6, 9 and 10 extend it, and Task 13 checks it (Global G1).
- **F8.** The runtime lane lands first (header). Task 11 fixes the order in `execute` and adds the native-resume test for a budgeted `joined_children` wait in `tests/test_joined_delegation.py`.
- **F9.** R3 counts on every native wake (Global R3, Task 4 docs). Carrying the bound across a native handoff is a G6 next step (Global G6, Task 13).
- **F10.** A count 429 calls `throttled(wait)` and only pauses; only a create 429 re-queues (Global R5; Task 7's hook, test and docs).
- **F11.** Task 2 keeps only what main lacks, and its line references come from preflight §0 (as do Task 1's and Task 4's):
  - kept: the logger, `_rate_limit_wait` returning `(seconds, source)`, `_duration_seconds` and `_rate_limit_headers`, `_emit_telemetry`, the keyword-only `on_wait(attempt, wait, source, error)` hook, the `_Sent` and `usage` wait totals, the original test 1 and the `docs/EXECUTION.md` docs;
  - dropped: the give-up rewrite and duplicate test 2;
  - count 429s emit `provider_throttled` with `operation_id=None` and are left out of the totals, and a small test covers this.
- **P1.** The bound is the last billed input, plus the bytes of the changed elements, plus `max(2048, 2%)`. Removed content earns no credit. Task 6 reports the ratio with and without the margin (Global G4; Tasks 4, 6 and 12).
