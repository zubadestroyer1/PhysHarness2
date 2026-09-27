import asyncio
import json
import time

import httpx
import pytest
from openai import AsyncOpenAI

from physharness.execution import (
    ExecutionError,
    ModelConfig,
    ResponsesRuntime,
    RuntimeLimits,
    SQLiteRuntimeStore,
    ToolDispatcher,
)
from physharness.execution.responses import STORED_RESPONSE_FIELDS


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


TODAY_SAVE_SHAPES = [  # one tool turn, then a final turn
    (None, True, "ready"),
    (None, True, "running"),
    ("generation", True, "running"),
    ("generation", False, "running"),
    (None, False, "running"),
    ("tool", False, "running"),
    (None, False, "running"),
    (None, True, "running"),
    ("generation", True, "running"),
    ("generation", False, "running"),
    (None, False, "running"),
    (None, True, "running"),
    (None, True, "running"),
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
    assert store.shapes == TODAY_SAVE_SHAPES
    assert [u.rsplit("/", 1)[-1] for u, _ in requests] == [
        "input_tokens",
        "responses",
        "input_tokens",
        "responses",
    ]
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
