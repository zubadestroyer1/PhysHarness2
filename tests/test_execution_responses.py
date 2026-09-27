import asyncio
import json
import time
from copy import deepcopy

import httpx
import pytest
from openai import AsyncOpenAI

from physharness.domain import canonical_json
from physharness.execution import (
    ExecutionError,
    ModelConfig,
    ResponsesRuntime,
    RuntimeLimits,
    SQLiteRuntimeStore,
    ToolDispatcher,
)
from physharness.execution.admission import TokenRateGovernor
from physharness.execution.responses import STORED_RESPONSE_FIELDS
from physharness.execution.stagnation import observe as observe_stagnation


def response(items, text="", response_id="resp_1"):
    return {
        "id": response_id,
        "object": "response",
        "created_at": 1,
        "model": "exact-model",
        "status": "completed",
        "output": items,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def message(text):
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def client_for(responses, requests):
    def handler(request):
        payload = json.loads(request.content)
        requests.append((str(request.url), payload))
        if str(request.url).endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        value = responses.pop(0)
        return httpx.Response(200, json=value)

    return AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_real_sdk_tool_loop_preserves_items_usage_and_checkpoint(tmp_path):
    requests, events = [], []
    call = {
        "id": "fc_1",
        "type": "function_call",
        "call_id": "call_1",
        "name": "double",
        "arguments": '{"value":2}',
        "status": "completed",
    }
    dispatcher = ToolDispatcher()

    async def double(arguments, operation_id):
        return {"value": arguments["value"] * 2, "operation": operation_id}

    dispatcher.register(
        "double",
        {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        double,
    )

    async def emit(event):
        events.append(event)

    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    client = client_for(
        [response([call]), response([message("4")], response_id="resp_2")], requests
    )
    runtime = ResponsesRuntime(store=store, dispatcher=dispatcher, client=client, event_sink=emit)
    result = await runtime.start("compute", ModelConfig(model="exact-model"), RuntimeLimits())
    assert result.output_text == "4"
    assert result.session.input_tokens == 20
    assert result.session.output_tokens == 10
    assert len([e for e in events if e.kind == "usage"]) == 2
    creates = [p for url, p in requests if not url.endswith("/input_tokens")]
    assert all(p["model"] == "exact-model" for p in creates)
    assert creates[1]["input"][1] == call
    assert creates[1]["input"][2]["call_id"] == "call_1"
    assert result.artifacts[0].content == "4"
    checkpoint = await runtime.checkpoint(result.session.id)
    restored = ResponsesRuntime(store=store, dispatcher=dispatcher, client=client)
    assert (await restored.resume(checkpoint)).id == result.session.id
    changed = checkpoint.model_copy(deep=True)
    changed.session.model.model = "substituted"
    with pytest.raises(ExecutionError, match="identity"):
        await restored.resume(changed)
    await client.close()
    store.close()


def echo_dispatcher(result):
    dispatcher = ToolDispatcher()

    async def echo(arguments, operation_id):
        return result

    dispatcher.register(
        "echo",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        echo,
    )
    return dispatcher


async def test_lone_surrogates_in_a_tool_result_are_escaped_so_the_session_saves(tmp_path):
    requests = []
    result = {
        "out": "a\ud800b",
        "nested": [{"k\udc00": "x"}],
        "pair": ("ok", "\udfff"),
        "clean": {"text": "∀"},
    }
    dispatcher = echo_dispatcher(result)
    scrubbed = await dispatcher.dispatch("echo", {}, "operation")
    assert scrubbed == {
        "out": "a\\ud800b",
        "nested": [{"k\\udc00": "x"}],
        "pair": ["ok", "\\udfff"],
        "clean": {"text": "∀"},
    }
    assert scrubbed["clean"] is result["clean"]  # an untouched branch is the same object
    call = {
        "id": "fc_1",
        "type": "function_call",
        "call_id": "call_1",
        "name": "echo",
        "arguments": "{}",
        "status": "completed",
    }
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    client = client_for(
        [response([call]), response([message("done")], response_id="resp_2")], requests
    )
    runtime = ResponsesRuntime(store=store, dispatcher=dispatcher, client=client)
    run = await runtime.start("echo", ModelConfig(model="exact-model"), RuntimeLimits())
    assert run.output_text == "done"
    creates = [p for url, p in requests if not url.endswith("/input_tokens")]
    assert json.loads(creates[1]["input"][2]["output"]) == scrubbed
    saved = await runtime.checkpoint(run.session.id)
    assert saved.native_state["tool_results"][f"{run.session.id}:call_1"]["result"] == scrubbed
    await client.close()
    store.close()


async def test_escaping_that_would_merge_two_result_keys_fails_the_tool():
    kept = await echo_dispatcher({"a\ud800": 1, "a\\udc00": 2}).dispatch("echo", {}, "operation")
    assert kept == {"a\\ud800": 1, "a\\udc00": 2}  # distinct after escaping, so both stay
    with pytest.raises(ExecutionError) as error:
        await echo_dispatcher({"a\ud800": 1, "a\\ud800": 2}).dispatch("echo", {}, "operation")
    assert error.value.code == "TOOL_FAILED"


async def test_a_tool_result_without_lone_surrogates_is_returned_as_is():
    result = {"text": "∀ ε > 0", "items": [{"k": "v", "n": 1}, None, True, 2.5]}
    assert await echo_dispatcher(result).dispatch("echo", {}, "operation") is result


async def test_token_preflight_prevents_generation(tmp_path):
    requests = []
    client = client_for([], requests)
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client)
    with pytest.raises(ExecutionError) as error:
        await runtime.start(
            "x", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=10)
        )
    assert error.value.code == "BUDGET_EXHAUSTED"
    assert len(requests) == 1
    await client.close()


async def test_synchronous_event_persistence_cannot_outlive_generation_deadline(tmp_path):
    requests, events = [], []
    client = client_for([response([message("late")])], requests)
    await client.responses.input_tokens.count(model="exact-model", input="warm SDK transport")

    async def persist(event):
        events.append(event.kind)
        if event.kind == "generation_started":
            time.sleep(0.2)

    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "deadline.db"), client=client, event_sink=persist
    )
    with pytest.raises(ExecutionError) as error:
        await runtime.start(
            "x", ModelConfig(model="exact-model"), RuntimeLimits(timeout_seconds=0.1)
        )
    assert error.value.code == "TIMEOUT"
    assert "generation_started" in events
    assert [url for url, _ in requests if url.endswith("/responses")] == []
    await client.close()


async def test_a_failed_timeout_abort_leaves_the_generation_uncertain(tmp_path):
    requests, events = [], []
    client = client_for([response([message("late")])], requests)
    await client.responses.input_tokens.count(model="exact-model", input="warm SDK transport")

    async def persist(event):
        events.append(event.kind)
        if event.kind == "generation_started":
            time.sleep(0.2)
        if event.kind == "generation_aborted":
            raise RuntimeError("ledger unavailable")

    store = SQLiteRuntimeStore(tmp_path / "deadline.db")
    runtime = ResponsesRuntime(store=store, client=client, event_sink=persist)
    with pytest.raises(ExecutionError) as error:
        await runtime.start(
            "x", ModelConfig(model="exact-model"), RuntimeLimits(timeout_seconds=0.1)
        )
    (session_id,) = [row[0] for row in store.db.execute("SELECT id FROM runtime_sessions")]
    checkpoint = await runtime.checkpoint(session_id)
    # Nothing was sent, but the release failed, so the reservation may still be held: the marker
    # stays and the session is uncertain, not failed.
    assert events == ["generation_started", "generation_aborted"]
    assert (checkpoint.session.status, checkpoint.native_state["pending_operation"]) == (
        "uncertain",
        error.value.operation_id,
    )
    assert [url for url, _ in requests if url.endswith("/responses")] == []
    await client.close()


async def test_tool_error_never_becomes_success(tmp_path):
    requests = []
    call = {
        "id": "fc",
        "type": "function_call",
        "call_id": "call",
        "name": "unknown",
        "arguments": "{}",
        "status": "completed",
    }
    client = client_for([response([call])], requests)
    events = []

    async def emit(event):
        events.append(event)

    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client, event_sink=emit
    )
    with pytest.raises(ExecutionError) as error:
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert error.value.code == "TOOL_UNAVAILABLE"
    assert any(e.kind == "usage" for e in events)
    await client.close()


async def test_reserved_parameter_override_rejected(tmp_path):
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"))
    with pytest.raises(ExecutionError) as error:
        await runtime.start(
            "x", ModelConfig(model="exact", parameters={"model": "other"}), RuntimeLimits()
        )
    assert error.value.code == "INVALID_CONFIG"


async def test_unconfigured_runtime_reports_unavailable(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"))
    assert not runtime.capabilities.available


async def test_usage_survives_restart_after_tool_failure(tmp_path):
    path = tmp_path / "s.db"
    requests, events = [], []
    call = {
        "id": "fc",
        "type": "function_call",
        "call_id": "call",
        "name": "missing",
        "arguments": "{}",
    }
    client = client_for([response([call])], requests)

    async def emit(event):
        events.append(event)

    store = SQLiteRuntimeStore(path)
    runtime = ResponsesRuntime(store=store, client=client, event_sink=emit)
    with pytest.raises(ExecutionError):
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    session_id = next(e.session_id for e in events if e.kind == "usage")
    store.close()
    restored = ResponsesRuntime(store=SQLiteRuntimeStore(path), client=client)
    checkpoint = await restored.checkpoint(session_id)
    assert checkpoint.session.input_tokens == 10
    assert checkpoint.native_state["responses"][0]["id"] == "resp_1"
    with pytest.raises(ExecutionError) as error:
        await restored.resume(checkpoint)
    assert error.value.code == "OPERATION_UNCERTAIN"
    await client.close()


async def test_missing_model_output_is_not_a_successful_fallback(tmp_path):
    requests = []
    client = client_for([response([])], requests)
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client)
    with pytest.raises(ExecutionError) as error:
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert error.value.code == "MODEL_OUTPUT_MISSING"
    await client.close()


async def test_duplicate_provider_tool_call_is_dispatched_once_across_turns(tmp_path):
    requests, effects = [], []
    call = {
        "id": "fc",
        "type": "function_call",
        "call_id": "stable-call",
        "name": "effect",
        "arguments": "{}",
        "status": "completed",
    }
    dispatcher = ToolDispatcher()

    async def effect(arguments, operation_id):
        effects.append(operation_id)
        return {"canonical_result": len(effects)}

    dispatcher.register(
        "effect",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        effect,
    )
    client = client_for(
        [
            response([call]),
            response([call], response_id="r2"),
            response([message("done")], response_id="r3"),
        ],
        requests,
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"), dispatcher=dispatcher, client=client
    )
    result = await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert len(effects) == 1
    assert result.session.input_tokens == 30
    await client.close()


async def test_usage_hook_failure_retains_correlated_pending_generation(tmp_path):
    client = client_for([response([message("done")])], [])
    events = []

    async def failed_accounting(event):
        events.append(event)
        if event.kind == "usage":
            raise OSError("ledger unavailable")

    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client, event_sink=failed_accounting
    )
    with pytest.raises(ExecutionError):
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    started = next(event for event in events if event.kind == "generation_started")
    checkpoint = await runtime.checkpoint(started.session_id)
    assert checkpoint.session.status == "uncertain"
    assert checkpoint.native_state["pending_operation"] == started.operation_id
    assert checkpoint.session.input_tokens == 10
    with pytest.raises(ExecutionError, match="unresolved"):
        await runtime.resume(checkpoint)
    await client.close()


def test_checkpoint_snapshots_native_state_without_mutable_alias():
    from physharness.execution import RuntimeCheckpoint, RuntimeSession

    state = {"input": [{"content": "exact assumptions"}]}
    session = RuntimeSession(
        runtime="openai_responses", model=ModelConfig(model="exact-model"), limits=RuntimeLimits()
    )
    checkpoint = RuntimeCheckpoint.build(session, state)
    state["input"][0]["content"] = "changed"
    checkpoint.verify()
    assert checkpoint.native_state["input"][0]["content"] == "exact assumptions"


def test_build_copies_state_through_json():
    from physharness.execution import RuntimeCheckpoint, RuntimeSession
    from physharness.execution.types import digest

    session = RuntimeSession(
        runtime="openai_responses", model=ModelConfig(model="exact-model"), limits=RuntimeLimits()
    )
    state = {"pair": (1, 2), "input": [{"content": "x"}]}
    checkpoint = RuntimeCheckpoint.build(session, state)
    assert checkpoint.native_state["pair"] == [1, 2]
    assert checkpoint.state_digest == digest(
        {"session": session.model_dump(mode="json"), "native_state": state}
    )


async def test_continuation_marks_session_running_before_awaiting_preflight(tmp_path):
    """A second adapter must observe the in-progress continuation in the shared store."""
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []
    client = client_for([response([message("first")])], requests)
    store = SQLiteRuntimeStore(tmp_path / "s.db")
    runtime = ResponsesRuntime(store=store, client=client)
    first = await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())

    async def blocked_handler(request):
        if request.url.path.endswith("/input_tokens"):
            entered.set()
            await release.wait()
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        return httpx.Response(200, json=response([message("second")], response_id="resp_2"))

    waiting_client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(blocked_handler)),
    )
    runtime.client = waiting_client
    running = asyncio.create_task(runtime.continue_session(first.session.id, "next"))
    await entered.wait()
    try:
        checkpoint = await store.load(first.session.id)
        assert checkpoint.session.status == "running"
        other = ResponsesRuntime(store=store, client=waiting_client)
        with pytest.raises(ExecutionError) as error:
            await other.continue_session(first.session.id, "concurrent")
        assert error.value.code == "SESSION_NOT_READY"
    finally:
        release.set()
        await running
        await client.close()
        await waiting_client.close()


async def test_duplicate_tool_identity_cannot_change_effect_arguments(tmp_path):
    calls = [
        {
            "id": "fc",
            "type": "function_call",
            "call_id": "same",
            "name": "effect",
            "arguments": json.dumps({"value": value}),
        }
        for value in (1, 2)
    ]
    dispatcher, effects = ToolDispatcher(), []

    async def effect(arguments, operation_id):
        effects.append(arguments["value"])
        return {"result": arguments["value"]}

    dispatcher.register(
        "effect",
        {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        effect,
    )
    client = client_for([response([calls[0]]), response([calls[1]], response_id="resp_2")], [])
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client, dispatcher=dispatcher
    )
    with pytest.raises(ExecutionError) as error:
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert error.value.code == "COMMAND_MISMATCH" and effects == [1]
    await client.close()


async def test_explicit_resume_can_continue_interruption_before_billable_request(tmp_path):
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.Event().wait()

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    store = SQLiteRuntimeStore(tmp_path / "s.db")
    runtime = ResponsesRuntime(store=store, client=client)
    running = asyncio.create_task(
        runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    )
    await entered.wait()
    session_id = next(iter(runtime._active))
    assert await runtime.interrupt(session_id)
    with pytest.raises(asyncio.CancelledError):
        await running
    checkpoint = await runtime.checkpoint(session_id)
    assert checkpoint.session.status == "interrupted"
    assert checkpoint.native_state["pending_operation"] is None
    restored = ResponsesRuntime(
        store=store, client=client_for([response([message("continued")])], [])
    )
    session = await restored.resume(checkpoint)
    assert session.status == "ready"
    result = await restored.continue_session(session_id, "Continue the unresolved work")
    assert result.output_text == "continued" and result.session.turns == 1
    await client.close()
    await restored.client.close()


def rate_limited_client(replies, requests, counts=()):
    """Replies are (status, body, headers); input-token counts succeed once `counts` is spent."""
    counts = list(counts)

    def handler(request):
        requests.append((str(request.url), request.headers.get("X-Client-Request-Id")))
        if str(request.url).endswith("/input_tokens"):
            if counts:
                status, body, headers = counts.pop(0)
                return httpx.Response(status, json=body, headers=headers)
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        status, body, headers = replies.pop(0)
        return httpx.Response(status, json=body, headers=headers)

    return AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def refusal(code):
    return {"error": {"message": "limit", "type": "tokens", "param": None, "code": code}}


async def test_rate_limit_refusal_resends_the_same_generation(tmp_path):
    requests, events = [], []

    async def emit(event):
        events.append(event)

    client = rate_limited_client(
        [
            (429, refusal("rate_limit_exceeded"), {"retry-after-ms": "5"}),
            (429, refusal("rate_limit_exceeded"), {}),
            (200, response([message("done")]), {}),
        ],
        requests,
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client, event_sink=emit
    )
    started = time.monotonic()
    result = await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert result.output_text == "done"
    assert result.session.status == "completed"
    assert result.session.input_tokens == 10
    creates = [ident for url, ident in requests if not url.endswith("/input_tokens")]
    # One generation: three sends under one operation, one start, one usage.
    assert len(creates) == 3 and len(set(creates)) == 1
    assert len([e for e in events if e.kind == "generation_started"]) == 1
    assert len([e for e in events if e.kind == "usage"]) == 1
    # The second refusal has no hint; the fallback has doubled once, to 2 s.
    assert time.monotonic() - started >= 1.0
    await client.close()


async def test_quota_exhaustion_is_not_resent(tmp_path):
    requests = []
    client = rate_limited_client(
        [(429, refusal("insufficient_quota"), {"retry-after-ms": "5"})], requests
    )
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client)
    with pytest.raises(ExecutionError):
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert len([url for url, _ in requests if not url.endswith("/input_tokens")]) == 1
    await client.close()


async def test_rate_limit_wait_never_passes_the_deadline(tmp_path):
    requests = []
    client = rate_limited_client(
        [(429, refusal("rate_limit_exceeded"), {"retry-after": "20"})], requests
    )
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client)
    started = time.monotonic()
    with pytest.raises(ExecutionError) as error:
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits(timeout_seconds=2))
    assert error.value.code == "PROVIDER_RATE_LIMITED" and error.value.retryable
    assert time.monotonic() - started < 2.0
    assert len([url for url, _ in requests if not url.endswith("/input_tokens")]) == 1
    await client.close()


async def test_rate_limit_give_up_releases_the_reservation_at_zero(tmp_path):
    requests, events = [], []

    async def emit(event):
        events.append(event.kind)

    client = rate_limited_client(
        [(429, refusal("rate_limit_exceeded"), {"retry-after": "20"})], requests
    )
    store = SQLiteRuntimeStore(tmp_path / "s.db")
    runtime = ResponsesRuntime(store=store, client=client, event_sink=emit)
    with pytest.raises(ExecutionError) as error:
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits(timeout_seconds=2))
    (session_id,) = [row[0] for row in store.db.execute("SELECT id FROM runtime_sessions")]
    checkpoint = await runtime.checkpoint(session_id)
    # Every send was refused and none is in flight, so the outcome is definite.
    assert error.value.code == "PROVIDER_RATE_LIMITED"
    assert checkpoint.session.status == "failed"
    assert checkpoint.native_state["pending_operation"] is None
    assert events == ["generation_started", "generation_aborted"]
    await client.close()


async def test_interrupting_a_rate_limit_wait_is_definite(tmp_path):
    requests, events = [], []

    async def emit(event):
        events.append(event.kind)

    client = rate_limited_client(
        [(429, refusal("rate_limit_exceeded"), {"retry-after": "20"})], requests
    )
    store = SQLiteRuntimeStore(tmp_path / "s.db")
    runtime = ResponsesRuntime(store=store, client=client, event_sink=emit)
    running = asyncio.create_task(
        runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    )
    while not any(url.endswith("/responses") for url, _ in requests):
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    session_id = next(iter(runtime._active))
    assert await runtime.interrupt(session_id)
    with pytest.raises(asyncio.CancelledError):
        await running
    checkpoint = await runtime.checkpoint(session_id)
    assert checkpoint.session.status == "interrupted"
    assert checkpoint.native_state["pending_operation"] is None
    assert events == ["generation_started", "provider_throttled", "generation_aborted"]
    await client.close()


async def test_rate_limited_token_count_is_resent(tmp_path):
    requests = []
    client = rate_limited_client(
        [(200, response([message("done")]), {})],
        requests,
        counts=[(429, refusal("rate_limit_exceeded"), {"retry-after-ms": "5"})],
    )
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client)
    result = await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert result.output_text == "done"
    assert [url.rsplit("/", 1)[-1] for url, _ in requests] == [
        "input_tokens",
        "input_tokens",
        "responses",
    ]
    await client.close()


async def test_rate_limit_wait_emits_provider_throttled_event(tmp_path):
    events = []

    async def emit(event):
        events.append(event)

    leaky = {
        "error": {
            "message": "Rate limit reached for org-SECRET123",
            "type": "tokens",
            "param": None,
            "code": "rate_limit_exceeded",
        }
    }
    headers = {
        "retry-after-ms": "5",
        "x-ratelimit-limit-tokens": "2000000",
        "x-ratelimit-remaining-tokens": "0",
        "x-ratelimit-reset-tokens": "6m0s",
        "x-ratelimit-reset-requests": "20ms",
    }
    client = rate_limited_client(
        [
            (429, leaky, headers),
            (429, refusal("rate_limit_exceeded"), {"retry-after": "0.01"}),
            (200, response([message("done")]), {}),
        ],
        [],
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client, event_sink=emit
    )
    await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    throttled = [e for e in events if e.kind == "provider_throttled"]
    assert throttled[0].payload == {
        "attempt": 1,
        "wait_seconds": 0.005,
        "wait_source": "retry-after-ms",
        "limit_tokens": 2000000,
        "remaining_tokens": 0,
        "reset_tokens_seconds": 360.0,
        "reset_requests_seconds": 0.02,
    }
    assert throttled[1].payload == {
        "attempt": 2,
        "wait_seconds": 0.01,
        "wait_source": "retry-after",
    }
    assert {e.operation_id for e in throttled} == {events[0].operation_id}
    assert "SECRET" not in json.dumps([e.payload for e in events])
    usage = next(e for e in events if e.kind == "usage").payload
    assert (usage["rate_limit_waits"], usage["rate_limit_wait_seconds"]) == (2, 0.015)
    await client.close()


async def test_rate_limited_count_is_announced_but_not_totalled(tmp_path):
    events = []

    async def emit(event):
        events.append(event)

    client = rate_limited_client(
        [(200, response([message("done")]), {})],
        [],
        counts=[(429, refusal("rate_limit_exceeded"), {"retry-after-ms": "5"})],
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client, event_sink=emit
    )
    await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    # A count has no operation and no reservation: its wait is announced, not added to usage (F11).
    assert [(e.operation_id, e.payload) for e in events if e.kind == "provider_throttled"] == [
        (None, {"attempt": 1, "wait_seconds": 0.005, "wait_source": "retry-after-ms"})
    ]
    usage = next(e for e in events if e.kind == "usage").payload
    assert (usage["rate_limit_waits"], usage["rate_limit_wait_seconds"]) == (0, 0.0)
    await client.close()


async def test_rate_limits_pause_the_governor_and_only_a_create_requeues(tmp_path):
    calls, requests, events, admitted = [], [], [], []

    class Counting(TokenRateGovernor):
        async def admit(self, **kwargs):
            calls.append("admit")
            admitted.append((kwargs, await super().admit(**kwargs)))
            return admitted[-1][1]

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

    client = rate_limited_client(
        [
            (429, refusal("rate_limit_exceeded"), {"retry-after-ms": "5"}),
            (200, response([message("done")]), {}),
        ],
        requests,
        counts=[(429, refusal("rate_limit_exceeded"), {"retry-after-ms": "5"})],
    )
    governor = Counting(tokens_per_minute=1_000_000)
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"),
        client=client,
        event_sink=emit,
        token_governor=governor,
    )
    await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    # F10: the count's 429 only pauses admission; the create's pauses, releases and re-admits.
    assert calls == [
        "throttled",
        "admit",
        "generation_started",
        "throttled",
        "release",
        "admit",
        "settle",
    ]
    started = next(e for e in events if e.kind == "generation_started")
    assert started.payload["admission_wait_seconds"] >= 0
    assert len({ident for url, ident in requests if not url.endswith("/input_tokens")}) == 1
    # The re-queue keeps the create's original queue time, so it keeps its age.
    assert admitted[1][0]["enqueued"] == admitted[0][1].enqueued
    # A full default bucket holds 15 s of tokens; settled at the 15 tokens used.
    assert governor.snapshot()["level"] >= 249_985
    await client.close()


@pytest.mark.parametrize(
    ("max_total_tokens", "counted", "sent"),
    [
        (None, [True, False], [3_000, 3_000]),  # the second request is admitted on the P1 bound
        (2_000, [True, True], [1_990, 1_975]),  # near the guard: counted, output cut to fit
    ],
)
async def test_admission_is_the_input_bound_plus_the_output_sent(
    tmp_path, max_total_tokens, counted, sent
):
    admitted, started, requests = [], [], []

    class Recording(TokenRateGovernor):
        async def admit(self, **kwargs):
            admitted.append(kwargs["tokens"])
            return await super().admit(**kwargs)

    async def emit(event):
        if event.kind == "generation_started":
            started.append(event.payload)

    client = client_for(
        [response([double_call()]), response([message("4")], response_id="resp_2")], requests
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"),
        dispatcher=double_dispatcher(),
        client=client,
        event_sink=emit,
        token_governor=Recording(tokens_per_minute=1_000_000),
    )
    limits = RuntimeLimits(max_output_tokens=3_000, max_total_tokens=max_total_tokens)
    await runtime.start("compute", ModelConfig(model="exact-model"), limits)
    # The provider charges the requested max output against TPM, so admission takes the
    # max_output_tokens each create actually sent, not an average of past outputs.
    assert [p["max_output_tokens"] for u, p in requests if u.endswith("/responses")] == sent
    assert [s["input_tokens_counted"] for s in started] == counted
    # Without context_management the reserved input is the input bound.
    assert admitted == [
        s["input_tokens_reserved"] + out for s, out in zip(started, sent, strict=True)
    ]
    await client.close()


async def test_a_governed_throttle_event_carries_the_governor_snapshot(tmp_path):
    events = []

    async def emit(event):
        events.append(event)

    headers = {
        "retry-after-ms": "5",
        "x-ratelimit-limit-tokens": "2000000",
        "x-ratelimit-remaining-tokens": "0",
    }
    client = rate_limited_client(
        [(429, refusal("rate_limit_exceeded"), headers), (200, response([message("done")]), {})],
        [],
    )
    # About 1 token/s, so the level barely moves while the test runs.
    governor = TokenRateGovernor(tokens_per_minute=60, burst_tokens=5_000)
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"),
        client=client,
        event_sink=emit,
        token_governor=governor,
    )
    await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    (throttled,) = [e.payload for e in events if e.kind == "provider_throttled"]
    # The governor's view when the 429 arrived, before it paused and cut, next to the provider's
    # own: the bucket held 5,000 less the 4,106-token admission (10 input + 4,096 output).
    assert (throttled["limit_tokens"], throttled["remaining_tokens"]) == (2_000_000, 0)
    assert throttled["governor"] == {
        "tokens_per_minute": 60,
        "effective_tokens_per_minute": 60,
        "level": 894,
        "waiting": 0,
        "paused_seconds": 0.0,
    }
    await client.close()


async def test_governor_requeue_past_the_deadline_gives_up_definitely(tmp_path):
    events = []

    async def emit(event):
        events.append(event.kind)

    client = rate_limited_client(
        [(429, refusal("rate_limit_exceeded"), {"retry-after": "1.1"})], []
    )
    # A slow bucket that holds the whole estimate: within the test only a release refills it.
    governor = TokenRateGovernor(tokens_per_minute=60, burst_tokens=5_000)
    store = SQLiteRuntimeStore(tmp_path / "s.db")
    runtime = ResponsesRuntime(store=store, client=client, event_sink=emit, token_governor=governor)
    with pytest.raises(ExecutionError) as error:
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits(timeout_seconds=2))
    (session_id,) = [row[0] for row in store.db.execute("SELECT id FROM runtime_sessions")]
    checkpoint = await runtime.checkpoint(session_id)
    # The 1.1 s pause outlasts the re-admission budget (deadline - 1 s): the give-up runs
    # main's _abandon_refused (emit, then clear) and every admitted token comes back.
    assert error.value.code == "PROVIDER_RATE_LIMITED" and error.value.retryable
    assert (checkpoint.session.status, checkpoint.native_state["pending_operation"]) == (
        "failed",
        None,
    )
    assert events == ["generation_started", "provider_throttled", "generation_aborted"]
    assert governor.snapshot()["level"] == 5_000
    await client.close()


@pytest.mark.parametrize("governed", [False, True])
async def test_a_400_after_a_rate_limit_wait_aborts_once_as_request_invalid(tmp_path, governed):
    events = []

    async def emit(event):
        events.append((event.kind, event.payload.get("reason")))

    invalid = {
        "error": {
            "message": "bad",
            "type": "invalid_request_error",
            "param": "reasoning.effort",
            "code": "unsupported_parameter",
        }
    }
    client = rate_limited_client(
        [(429, refusal("rate_limit_exceeded"), {"retry-after-ms": "5"}), (400, invalid, {})], []
    )
    # A slow bucket that holds the whole estimate: within the test only a release refills it.
    governor = TokenRateGovernor(tokens_per_minute=60, burst_tokens=5_000) if governed else None
    store = SQLiteRuntimeStore(tmp_path / "s.db")
    runtime = ResponsesRuntime(store=store, client=client, event_sink=emit, token_governor=governor)
    with pytest.raises(ExecutionError) as error:
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    (session_id,) = [row[0] for row in store.db.execute("SELECT id FROM runtime_sessions")]
    checkpoint = await runtime.checkpoint(session_id)
    state = checkpoint.native_state
    # The resend's 400 is not a rate limit, so the wait does not abandon; the 400 abandons once.
    assert error.value.code == "MODEL_REQUEST_INVALID"
    assert events == [
        ("generation_started", None),
        ("provider_throttled", None),
        ("generation_aborted", "request_invalid"),
    ]
    assert (checkpoint.session.status, state["pending_operation"]) == ("failed", None)
    assert state["preflight_error"]["stage"] == "create"
    if governed:
        assert governor.snapshot()["level"] == 5_000  # the re-admitted estimate came back
    await client.close()


@pytest.mark.parametrize("refused", ["create", "count"])
async def test_immediate_rate_limit_give_up_still_pauses_the_governor(tmp_path, refused):
    order = []

    class Recording(TokenRateGovernor):
        def throttled(self, wait_seconds):
            order.append("throttled")
            super().throttled(wait_seconds)

        def release(self, admission):
            order.append("release")
            super().release(admission)

    async def emit(event):
        order.append(event.kind)

    hopeless = (429, refusal("rate_limit_exceeded"), {"retry-after": "20"})
    client = rate_limited_client(
        [hopeless] if refused == "create" else [],
        [],
        counts=[hopeless] if refused == "count" else [],
    )
    # A slow bucket that holds the whole estimate: within the test only a release refills it.
    governor = Recording(tokens_per_minute=60, burst_tokens=5_000)
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"),
        client=client,
        event_sink=emit,
        token_governor=governor,
    )
    with pytest.raises(ExecutionError) as error:
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits(timeout_seconds=2))
    snapshot = governor.snapshot()
    # The 20 s wait would pass the 2 s deadline, so the runtime gives up without waiting; the
    # refusal still pauses and cuts the governor, before main's abandon (emit, then clear).
    assert error.value.code == "PROVIDER_RATE_LIMITED"
    assert 19 < snapshot["paused_seconds"] <= 20 and snapshot["effective_tokens_per_minute"] == 48
    assert snapshot["level"] == 5_000
    assert order == (
        ["generation_started", "throttled", "generation_aborted", "release"]
        if refused == "create"
        else ["throttled"]
    )
    await client.close()


async def test_verified_target_during_admission_wait_sends_nothing(tmp_path):
    requests, checks = [], []
    governor = TokenRateGovernor(tokens_per_minute=60_000, burst_tokens=100)
    await governor.admit(key="other", tokens=100, priority=0)

    async def guard():
        checks.append(True)
        return len(checks) >= 2  # verified by the time admission is granted

    client = client_for([], requests)
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"),
        client=client,
        pre_generation_guard=guard,
        token_governor=governor,
        admission_priority=0,
    )
    result = await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert result.completion_reason == "target_verified"
    assert not [u for u, _ in requests if u.endswith("/responses")]
    # Released: the bucket is back to full although this runtime's ~1,000-token admission
    # overdrew it.
    assert (governor.snapshot()["waiting"], governor.snapshot()["level"]) == (0, 100)
    await client.close()


DOUBLE_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}


def double_dispatcher(seen=None):
    dispatcher = ToolDispatcher()

    async def double(arguments, operation_id):
        if seen is not None:
            seen.append(operation_id)
        return {"value": arguments["value"] * 2}

    dispatcher.register("double", DOUBLE_SCHEMA, double)
    return dispatcher


def double_call(call_id="call_1", value=2):
    return {
        "id": "fc_" + call_id,
        "type": "function_call",
        "call_id": call_id,
        "name": "double",
        "arguments": json.dumps({"value": value}),
        "status": "completed",
    }


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


COALESCED_SAVE_SHAPES = [  # one tool turn, then a final turn
    (None, True, "ready"),
    (None, True, "running"),
    ("generation", True, "running"),  # A
    ("generation", False, "running"),  # B
    ("tool", False, "running"),  # D1 (settlement + marker)
    (None, True, "running"),  # F
    ("generation", True, "running"),  # A
    ("generation", False, "running"),  # B
    (None, True, "running"),  # terminal pending
    (None, True, "completed"),
]


async def test_tool_turn_save_sequence_is_pinned(tmp_path):
    requests = []
    client = client_for(
        [response([double_call()]), response([message("4")], response_id="resp_2")], requests
    )
    store = RecordingStore(tmp_path / "s.db")
    runtime = ResponsesRuntime(store=store, dispatcher=double_dispatcher(), client=client)
    assert (
        await runtime.start("compute", ModelConfig(model="exact-model"), RuntimeLimits())
    ).output_text == "4"
    assert store.shapes == COALESCED_SAVE_SHAPES
    assert [u.rsplit("/", 1)[-1] for u, _ in requests] == ["input_tokens", "responses", "responses"]
    await client.close()


async def test_a_requeued_create_keeps_the_coalesced_save_sequence(tmp_path):
    requests, settled = [], []

    class Settling(TokenRateGovernor):
        def settle(self, admission, actual_tokens):
            settled.append(actual_tokens)
            super().settle(admission, actual_tokens)

    client = rate_limited_client(
        [
            (429, refusal("rate_limit_exceeded"), {"retry-after-ms": "5"}),
            (200, response([double_call()]), {}),
            (200, response([message("4")], response_id="resp_2"), {}),
        ],
        requests,
    )
    store = RecordingStore(tmp_path / "s.db")
    runtime = ResponsesRuntime(
        store=store,
        dispatcher=double_dispatcher(),
        client=client,
        token_governor=Settling(tokens_per_minute=1_000_000),
    )
    result = await runtime.start("compute", ModelConfig(model="exact-model"), RuntimeLimits())
    assert result.output_text == "4"
    # The re-queue saves nothing: the resend goes out under A's durable marker.
    assert store.shapes == COALESCED_SAVE_SHAPES
    assert settled == [15, 15]  # one settlement per turn
    creates = [ident for url, ident in requests if url.endswith("/responses")]
    assert len(creates) == 3 and creates[0] == creates[1] != creates[2]
    await client.close()


class OutputCounting(RecordingStore):
    """Also records how many tool outputs the latest committed save holds."""

    async def save(self, checkpoint):
        await super().save(checkpoint)
        self.outputs = sum(
            item.get("type") == "function_call_output" for item in checkpoint.native_state["input"]
        )


def read_dispatcher():
    dispatcher = ToolDispatcher()

    async def read(arguments, operation_id):
        return {"text": "unchanged"}

    dispatcher.register(
        "read_file",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        read,
    )
    return dispatcher


def read_call(call_id, path):
    return {
        "id": "fc_" + call_id,
        "type": "function_call",
        "call_id": call_id,
        "name": "read_file",
        "arguments": json.dumps({"path": path}),
        "status": "completed",
    }


async def test_multi_call_turn_saves_one_marker_per_call_and_announces_after_saving(tmp_path):
    completed_at = []
    store = OutputCounting(tmp_path / "s.db")

    async def emit(event):
        if event.kind == "tool_completed":
            completed_at.append(store.outputs)

    client = client_for(
        [
            response([double_call("call_1"), double_call("call_2")]),
            response([message("done")], response_id="resp_2"),
        ],
        [],
    )
    await ResponsesRuntime(
        store=store, dispatcher=double_dispatcher(), client=client, event_sink=emit
    ).start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert store.shapes[2:7] == [
        ("generation", True, "running"),
        ("generation", False, "running"),
        ("tool", False, "running"),
        ("tool", False, "running"),
        (None, True, "running"),
    ]
    assert completed_at == [1, 2]
    await client.close()


async def test_batched_stagnation_signal_reports_the_state_at_its_call(tmp_path):
    signals = []

    async def emit(event):
        if event.kind == "stagnation_warning":
            signals.append(deepcopy(event.payload["stagnation_state"]))

    # The fourth identical read warns; the fifth, a new read, is announced after it.
    calls = [read_call(f"call_{i}", "a") for i in range(4)] + [read_call("call_4", "b")]
    client = client_for([response(calls), response([message("done")], response_id="resp_2")], [])
    await ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"),
        dispatcher=read_dispatcher(),
        client=client,
        event_sink=emit,
    ).start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert [sorted(state["read_counts"].values()) for state in signals] == [[4]]
    await client.close()


async def test_batch_failing_before_a_marker_announces_earlier_results_after_the_failure_save(
    tmp_path,
):
    seed = {}
    for _ in range(3):  # the batch's first read is then the fourth, which warns
        observe_stagnation(seed, "read_file", {"path": "a"}, {"text": "unchanged"})
    announced = []
    store = OutputCounting(tmp_path / "s.db")

    async def emit(event):
        if event.kind in {"tool_completed", "stagnation_warning"}:
            call_id = event.operation_id.rsplit(":", 1)[-1]
            announced.append((event.kind, call_id, store.shapes[-1], store.outputs))

    malformed = {**read_call("call_2", "b"), "arguments": "not json"}
    client = client_for([response([read_call("call_1", "a"), malformed])], [])
    runtime = ResponsesRuntime(
        store=store,
        dispatcher=read_dispatcher(),
        client=client,
        event_sink=emit,
        stagnation_state=seed,
    )
    with pytest.raises(ExecutionError) as error:
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert error.value.code == "INVALID_TOOL_ARGUMENTS"
    failure_save = (None, False, "failed")
    assert announced == [
        ("tool_completed", "call_1", failure_save, 1),
        ("stagnation_warning", "call_1", failure_save, 1),
    ]
    await client.close()


class RefusingSettledSaves(RecordingStore):
    """Refuses the next ``refusals`` saves of a settled first turn: F, then the failure save."""

    def __init__(self, path, refusals):
        super().__init__(path)
        self.refusals = refusals

    async def save(self, checkpoint):
        state = checkpoint.native_state
        if (
            self.refusals
            and checkpoint.session.turns == 1
            and state.get("settled_boundary") is True
            and state.get("pending_operation") is None
        ):
            self.refusals -= 1
            raise RuntimeError("disk full")
        await super().save(checkpoint)


async def test_failed_settled_save_announces_the_last_result_after_the_failure_save(tmp_path):
    announced = []
    store = RefusingSettledSaves(tmp_path / "s.db", refusals=1)

    async def emit(event):
        if event.kind == "tool_completed":
            announced.append(store.shapes[-1])
            raise RuntimeError("sink down")  # must not mask the original failure

    client = client_for([response([double_call()])], [])
    runtime = ResponsesRuntime(
        store=store, dispatcher=double_dispatcher(), client=client, event_sink=emit
    )
    with pytest.raises(ExecutionError) as error:
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert error.value.code == "PROVIDER_FAILED"
    assert announced == [(None, True, "failed")]
    await client.close()


async def test_failed_failure_save_announces_nothing(tmp_path):
    announced = []
    store = RefusingSettledSaves(tmp_path / "s.db", refusals=2)

    async def emit(event):
        if event.kind == "tool_completed":
            announced.append(store.shapes[-1])

    client = client_for([response([double_call()])], [])
    runtime = ResponsesRuntime(
        store=store, dispatcher=double_dispatcher(), client=client, event_sink=emit
    )
    with pytest.raises(RuntimeError, match="disk full"):
        await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert store.refusals == 0
    assert announced == []
    await client.close()


async def test_turn_note_rides_on_the_generation_marker_save(tmp_path):
    requests = []

    async def note(turns):
        return "Check in now." if turns == 1 else None

    client = client_for(
        [response([double_call()]), response([message("4")], response_id="resp_2")], requests
    )
    store = RecordingStore(tmp_path / "s.db")
    await ResponsesRuntime(
        store=store, dispatcher=double_dispatcher(), client=client, turn_note=note
    ).start("compute", ModelConfig(model="exact-model"), RuntimeLimits())
    assert store.shapes == COALESCED_SAVE_SHAPES
    creates = [payload for url, payload in requests if url.endswith("/responses")]
    assert "research_runtime_note" in creates[1]["input"][-1]["content"]
    await client.close()


async def test_count_runs_once_per_run_then_estimates(tmp_path):
    requests, events = [], []

    async def emit(event):
        events.append(event)

    client = client_for(
        [
            response([double_call("c1")]),
            response([double_call("c2")], response_id="r2"),
            response([message("8")], response_id="r3"),
        ],
        requests,
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"),
        dispatcher=double_dispatcher(),
        client=client,
        event_sink=emit,
    )
    await runtime.start(
        "compute", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
    )
    assert [u.rsplit("/", 1)[-1] for u, _ in requests] == ["input_tokens"] + ["responses"] * 3
    creates = [p for u, p in requests if u.endswith("/responses")]
    started = [e.payload for e in events if e.kind == "generation_started"]
    assert [p["input_tokens_counted"] for p in started] == [True, False, False]
    for n in (1, 2):  # instructions and tools are unchanged, so only appended items count (P1)
        appended = creates[n]["input"][len(creates[n - 1]["input"]) :]
        # The last billed input, plus the appended bytes, plus the 2,048 margin floor.
        assert (
            started[n]["input_tokens_estimate"]
            == 10 + sum(len(canonical_json(item).encode("utf-8")) for item in appended) + 2048
        )
    await client.close()


async def test_every_run_counts_its_first_request(tmp_path):
    requests, events = [], []

    async def emit(event):
        events.append(event)

    client = client_for(
        [response([message("first")]), response([message("second")], response_id="r2")],
        requests,
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client, event_sink=emit
    )
    first = await runtime.start(
        "compute", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
    )
    # Same runtime, same session: the first run's last request must not bound the next run's.
    await runtime.continue_session(first.session.id, "next")
    assert [u.rsplit("/", 1)[-1] for u, _ in requests] == ["input_tokens", "responses"] * 2
    started = [e.payload for e in events if e.kind == "generation_started"]
    assert [p["input_tokens_counted"] for p in started] == [True, True]
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
        100 + size({"elided": True}) + size({"n": 4}) + 2048
    )
    wider = [*tools, {"name": "recall_output"}]  # new instructions and tools; two items removed
    assert _input_bound(
        previous, _request_elements({"instructions": "new"}, wider, items[:1]), 0
    ) == (100 + size("new") + size(wider) + 2048)
    assert _input_bound(previous, before, 1) is None  # a compaction epoch voids the bound
    assert _input_bound({**previous, "tokens": 200_000}, before, 0) == 204_000  # 2% above the floor


async def test_cumulative_budget_near_limit_counts_exactly(tmp_path):
    requests = []
    client = client_for(
        [response([double_call()]), response([message("4")], response_id="r2")], requests
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"), dispatcher=double_dispatcher(), client=client
    )
    # 12,400 - 15 used - a ~2,300-token estimate (2,048 of it margin) leaves less
    # than max_output + 8,192.
    await runtime.start(
        "compute",
        ModelConfig(model="exact-model"),
        RuntimeLimits(max_total_tokens=12_400, max_output_tokens=4_096),
    )
    assert [u.rsplit("/", 1)[-1] for u, _ in requests] == ["input_tokens", "responses"] * 2
    await client.close()


PARALLEL = ModelConfig(model="exact-model", parameters={"parallel_tool_calls": True})


@pytest.mark.parametrize(
    "parameters,expected", [({}, False), ({"parallel_tool_calls": True}, True)]
)
async def test_parallel_flag_sent_to_count_and_create(tmp_path, parameters, expected):
    requests = []
    client = client_for([response([message("done")])], requests)
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client)
    await runtime.start(
        "x", ModelConfig(model="exact-model", parameters=parameters), RuntimeLimits()
    )
    assert [payload["parallel_tool_calls"] for _, payload in requests] == [expected, expected]
    await client.close()


async def test_parallel_calls_run_in_order_each_after_its_marker(tmp_path):
    requests, dispatched = [], []
    store, dispatcher = RecordingStore(tmp_path / "s.db"), ToolDispatcher()

    async def double(arguments, operation_id):
        dispatched.append((operation_id, store.pending[-1]))
        return {"value": arguments["value"] * 2}

    dispatcher.register("double", DOUBLE_SCHEMA, double)
    client = client_for(
        [
            response([double_call("call_1", 2), double_call("call_2", 3)]),
            response([message("done")], response_id="resp_2"),
        ],
        requests,
    )
    result = await ResponsesRuntime(store=store, dispatcher=dispatcher, client=client).start(
        "x", PARALLEL, RuntimeLimits()
    )
    sid = result.session.id
    assert dispatched == [(f"{sid}:call_1", f"{sid}:call_1"), (f"{sid}:call_2", f"{sid}:call_2")]
    second = [p for u, p in requests if u.endswith("/responses")][1]["input"]
    assert [json.loads(i["output"]) for i in second if i.get("type") == "function_call_output"] == [
        {"value": 4},
        {"value": 6},
    ]
    await client.close()


async def test_fatal_tool_error_mid_batch_stops_later_calls(tmp_path):
    dispatched, dispatcher = [], ToolDispatcher()

    async def fatal(arguments, operation_id):
        dispatched.append(operation_id)
        raise ExecutionError("STALE_LEASE", "lease lost", operation_id=operation_id)

    dispatcher.register("double", DOUBLE_SCHEMA, fatal)
    client = client_for([response([double_call("call_1"), double_call("call_2")])], [])
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"), dispatcher=dispatcher, client=client
    )
    with pytest.raises(ExecutionError) as error:
        await runtime.start("x", PARALLEL, RuntimeLimits())
    assert error.value.code == "STALE_LEASE" and len(dispatched) == 1
    checkpoint = await runtime.checkpoint(dispatched[0].split(":")[0])
    assert (checkpoint.session.status, checkpoint.native_state["pending_operation"]) == (
        "uncertain",
        dispatched[0],
    )
    await client.close()


async def test_the_create_sends_the_tools_its_bound_describes(tmp_path):
    requests, checks = [], []
    dispatcher = double_dispatcher()

    async def guard():
        checks.append(True)
        if len(checks) == 2:  # the send's check, after the request was prepared
            dispatcher.register("late", DOUBLE_SCHEMA, dispatcher._tools["double"][1])
        return False

    client = client_for([response([message("done")])], requests)
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"),
        dispatcher=dispatcher,
        client=client,
        pre_generation_guard=guard,
    )
    await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    # The P1 digests describe the prepared tools, so the create sends exactly those.
    assert [[tool["name"] for tool in payload["tools"]] for _, payload in requests] == [
        ["double"],
        ["double"],
    ]
    await client.close()


async def test_per_session_caches_are_dropped_when_a_run_ends(tmp_path):
    client = client_for(
        [response([double_call()]), response([message("4")], response_id="resp_2")], []
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"),
        dispatcher=double_dispatcher(),
        client=client,
        token_governor=TokenRateGovernor(tokens_per_minute=1_000_000),
    )

    def caches():
        return [
            runtime._active,
            runtime._saved,
            runtime._last_request,
            runtime._unannounced,
            runtime._elided,
        ]

    first = await runtime.start("compute", ModelConfig(model="exact-model"), RuntimeLimits())
    assert caches() == [{}] * 5
    with pytest.raises(ExecutionError):  # the provider has no reply left
        await runtime.continue_session(first.session.id, "again")
    assert caches() == [{}] * 5
    await client.close()


@pytest.mark.parametrize("reported,expected", [(8, 8), (-1, 0), (11, 0)])
async def test_usage_event_carries_cached_input_tokens(tmp_path, reported, expected):
    events = []

    async def emit(event):
        events.append(event)

    reply = response([message("done")])
    reply["usage"]["input_tokens_details"]["cached_tokens"] = reported
    client = client_for([reply], [])
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"), client=client, event_sink=emit
    )
    await runtime.start("x", ModelConfig(model="exact-model"), RuntimeLimits())
    assert next(e for e in events if e.kind == "usage").payload["cached_input_tokens"] == expected
    await client.close()


async def test_stored_response_omits_request_echo_and_duplicate_output(tmp_path):
    tools = [
        {"type": "function", "name": "double", "parameters": {"type": "object"}, "strict": True}
    ]
    first = {
        **response([double_call()]),
        "tools": tools,
        "instructions": "echoed",
        "tool_choice": "auto",
    }
    client = client_for(
        [first, {**response([message("4")], response_id="resp_2"), "tools": tools * 2}], []
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"),
        dispatcher=double_dispatcher(),
        client=client,
    )
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
    monkeypatch.setattr(
        RuntimeCheckpoint,
        "build",
        classmethod(lambda cls, session, state: builds.append(1) or original(cls, session, state)),
    )

    async def boundary(checkpoint):
        hooked.append(checkpoint.state_digest)

    async def source(checkpoint):
        return {"delivery_id": None, "items": []}

    async def ack(delivery_id):
        raise AssertionError("nothing to acknowledge")

    client = client_for(
        [response([double_call()]), response([message("4")], response_id="resp_2")], []
    )
    store = RecordingStore(tmp_path / "s.db")
    runtime = ResponsesRuntime(
        store=store,
        dispatcher=double_dispatcher(),
        client=client,
        boundary_hook=boundary,
        update_source=source,
        update_ack=ack,
    )
    await runtime.start("compute", ModelConfig(model="exact-model"), RuntimeLimits())
    assert len(hooked) == 2 and len(builds) == len(store.shapes)
    await client.close()
