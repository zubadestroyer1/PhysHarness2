"""Native Responses context management and clean continuation boundaries."""

import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI

from physharness.execution import (
    ExecutionError,
    ModelConfig,
    ResponsesRuntime,
    RuntimeCheckpoint,
    RuntimeLimits,
    RuntimeSession,
    SQLiteRuntimeStore,
    ToolDispatcher,
)
from physharness.execution.parameters import validate_responses_parameters


def response(items, response_id, input_tokens=10, output_tokens=5, status="completed"):
    return {
        "id": response_id,
        "object": "response",
        "created_at": 1,
        "model": "exact-model",
        "status": status,
        "output": items,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def text_item(value):
    return {
        "id": "message-" + value,
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": value, "annotations": []}],
    }


def call_item(call_id):
    return {
        "id": "fc-" + call_id,
        "type": "function_call",
        "call_id": call_id,
        "name": "observe",
        "arguments": "{}",
        "status": "completed",
    }


def compaction_item(label):
    return {"id": "compact-" + label, "type": "compaction", "encrypted_content": "opaque-" + label}


def sdk_client(responses, requests, *, count=10):
    def handle(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(
                200,
                json={
                    "object": "response.input_tokens",
                    "input_tokens": count.pop(0) if isinstance(count, list) else count,
                },
            )
        return httpx.Response(200, json=responses.pop(0))

    return AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )


def test_context_management_is_typed_and_rejects_invalid_threshold():
    assert validate_responses_parameters(
        {"context_management": [{"type": "compaction", "compact_threshold": 80}]}
    ) == {"context_management": [{"type": "compaction", "compact_threshold": 80}]}
    with pytest.raises(ExecutionError) as error:
        validate_responses_parameters(
            {"context_management": [{"type": "compaction", "compact_threshold": 0}]}
        )
    assert error.value.code == "INVALID_CONFIG"


@pytest.mark.parametrize(
    "provider_code,provider_param,expected",
    [
        ("invalid_function_parameters", "tools[0].parameters", "PROVIDER_TOOL_SCHEMA_INVALID"),
        ("unsupported_parameter", "reasoning.effort", "MODEL_REQUEST_INVALID"),
    ],
)
async def test_input_token_schema_400_is_safe_and_pre_generation(
    tmp_path, provider_code, provider_param, expected
):
    requests, events = [], []

    def handle(request):
        requests.append((request.url.path, json.loads(request.content)))
        assert request.url.path.endswith("/input_tokens")
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "sensitive request and schema text must stay private",
                    "type": "invalid_request_error",
                    "param": provider_param,
                    "code": provider_code,
                }
            },
        )

    client = AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")

    async def emit(event):
        events.append(event)

    runtime = ResponsesRuntime(store=store, client=client, event_sink=emit)
    with pytest.raises(ExecutionError) as error:
        await runtime.start("private prompt", ModelConfig(model="exact-model"), RuntimeLimits())
    assert error.value.code == expected
    assert error.value.operation_id
    assert "sensitive" not in str(error.value)
    assert len(requests) == 1
    assert not events
    checkpoint = RuntimeCheckpoint.model_validate_json(
        store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0]
    )
    assert checkpoint.session.status == "failed"
    assert checkpoint.session.input_tokens == checkpoint.session.output_tokens == 0
    assert checkpoint.native_state["pending_operation"] is None
    assert checkpoint.native_state["responses"] == []
    assert checkpoint.native_state["preflight_error"] == {
        "stage": "input_token_count",
        "operation_id": error.value.operation_id,
        "provider_code": provider_code,
        "provider_param": provider_param,
    }
    assert "sensitive" not in checkpoint.model_dump_json()
    await client.close()
    store.close()


async def test_input_token_400_drops_unbounded_provider_fields(tmp_path):
    secret = "SECRET" * 100

    def handle(request):
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": secret,
                    "type": "invalid_request_error",
                    "code": secret,
                    "param": "tools[0].parameters\n" + secret,
                }
            },
        )

    client = AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client)
    with pytest.raises(ExecutionError) as error:
        await runtime.start("target", ModelConfig(model="exact-model"), RuntimeLimits())
    assert error.value.code == "MODEL_REQUEST_INVALID"
    saved = store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0]
    assert secret not in str(error.value) and secret not in saved
    assert json.loads(saved)["native_state"]["preflight_error"]["provider_param"] is None
    await client.close()
    store.close()


async def test_inline_compaction_preserves_archive_and_reduces_only_active_input(tmp_path):
    requests, calls, events, anchors = [], [], [], []
    dispatcher = ToolDispatcher()

    async def observe(arguments, operation_id):
        calls.append(operation_id)
        return {"seen": len(calls)}

    dispatcher.register(
        "observe",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        observe,
    )
    client = sdk_client(
        [
            response([compaction_item("one"), call_item("a")], "r1"),
            response([compaction_item("two"), call_item("b")], "r2"),
            response([text_item("done")], "r3"),
        ],
        requests,
    )
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")

    async def emit(event):
        events.append(event)

    async def anchor():
        anchors.append(f"fresh-{len(anchors) + 1}")
        return anchors[-1]

    runtime = ResponsesRuntime(
        store=store,
        client=client,
        dispatcher=dispatcher,
        event_sink=emit,
        context_anchor=anchor,
    )
    result = await runtime.start(
        "work",
        ModelConfig(
            model="exact-model",
            parameters={"context_management": [{"type": "compaction", "compact_threshold": 80}]},
        ),
        RuntimeLimits(max_context_tokens=100, max_output_tokens=10, max_total_tokens=300),
    )
    checkpoint = await runtime.checkpoint(result.session.id)
    creates = [payload for path, payload in requests if path.endswith("/responses")]
    assert len(creates) == 3
    assert all(p["context_management"][0]["compact_threshold"] == 80 for p in creates)
    assert creates[1]["input"][0] == compaction_item("one")
    assert creates[1]["input"][1]["call_id"] == "a"
    assert creates[1]["input"][2]["call_id"] == "a"
    assert creates[2]["input"][0] == compaction_item("two")
    assert len(checkpoint.native_state["responses"]) == 1
    assert len(checkpoint.native_state["archives"]) == 2
    first = await store.load_archive(result.session.id, checkpoint.native_state["archives"][0])
    second = await store.load_archive(result.session.id, checkpoint.native_state["archives"][1])
    assert first["responses"][0]["output"][0] == compaction_item("one")
    assert second["responses"][0]["output"][0] == compaction_item("two")
    assert len(first["tool_results"]) == len(second["tool_results"]) == 1
    reconstructed = (
        first["input_prefix"] + second["input_prefix"] + checkpoint.native_state["input"]
    )
    assert [item.get("type", "user") for item in reconstructed] == [
        "user",
        "compaction",
        "function_call",
        "function_call_output",
        "user",
        "compaction",
        "function_call",
        "function_call_output",
        "user",
        "message",
    ]
    assert [item["content"] for item in reconstructed if item.get("role") == "user"] == [
        "work",
        "fresh-1",
        "fresh-2",
    ]
    assert [
        json.loads(item["output"])
        for item in reconstructed
        if item.get("type") == "function_call_output"
    ] == [
        {"seen": 1},
        {"seen": 2},
    ]
    assert result.session.input_tokens == 30 and result.session.output_tokens == 15
    assert calls == [f"{result.session.id}:a", f"{result.session.id}:b"]
    assert len([e for e in events if e.kind == "usage"]) == 3
    started = [e for e in events if e.kind == "generation_started"]
    assert [e.payload["input_tokens_reserved"] for e in started] == [100, 100, 100]
    await client.close()
    store.close()


async def test_compaction_does_not_split_function_call_from_its_output(tmp_path):
    requests = []
    dispatcher = ToolDispatcher()

    async def observe(arguments, operation_id):
        return {"seen": True}

    dispatcher.register(
        "observe",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        observe,
    )
    client = sdk_client(
        [
            response([call_item("a"), compaction_item("late")], "r1"),
            response([text_item("done")], "r2"),
        ],
        requests,
    )
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client, dispatcher=dispatcher)
    await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    creates = [payload for path, payload in requests if path.endswith("/responses")]
    assert creates[1]["input"][0]["call_id"] == "a"
    assert creates[1]["input"][1]["type"] == "compaction"
    assert creates[1]["input"][2]["call_id"] == "a"
    await client.close()
    store.close()


async def test_crossing_call_keeps_entire_response_reasoning_group(tmp_path):
    requests = []
    dispatcher = ToolDispatcher()

    async def observe(arguments, operation_id):
        return {"seen": True}

    dispatcher.register(
        "observe",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        observe,
    )
    reasoning = {"id": "reason-1", "type": "reasoning", "encrypted_content": "secret-opaque"}
    client = sdk_client(
        [
            response([reasoning, call_item("a"), compaction_item("late")], "r1"),
            response([text_item("done")], "r2"),
        ],
        requests,
    )
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client, dispatcher=dispatcher)
    await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    creates = [payload for path, payload in requests if path.endswith("/responses")]
    assert creates[1]["input"][0] == reasoning
    assert creates[1]["input"][1]["call_id"] == "a"
    assert creates[1]["input"][2] == compaction_item("late")
    assert creates[1]["input"][3]["call_id"] == "a"
    await client.close()
    store.close()


async def test_boundary_hook_yields_only_after_tools_and_forbids_source_reuse(tmp_path):
    requests, seen = [], []
    dispatcher = ToolDispatcher()

    async def observe(arguments, operation_id):
        return {"seen": True}

    dispatcher.register(
        "observe",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        observe,
    )
    client = sdk_client([response([call_item("a")], "r1")], requests)
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")

    async def boundary(checkpoint):
        seen.append(checkpoint)
        assert checkpoint.session.status == "running"
        assert checkpoint.native_state["pending_operation"] is None
        assert checkpoint.native_state["settled_boundary"] is True
        assert checkpoint.native_state["input"][-1]["call_id"] == "a"
        return {"reason": "wait_for_children"}

    runtime = ResponsesRuntime(
        store=store, client=client, dispatcher=dispatcher, boundary_hook=boundary
    )
    result = await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    assert len(seen) == 1
    assert result.output_text == "" and result.artifacts == []
    assert result.session.status == "handed_off"
    checkpoint = await runtime.checkpoint(result.session.id)
    assert result.continuation == {
        "reason": "wait_for_children",
        "source_session_id": result.session.id,
        "source_checkpoint_digest": checkpoint.state_digest,
    }
    with pytest.raises(ExecutionError):
        await runtime.resume(checkpoint)
    with pytest.raises(ExecutionError):
        await runtime.continue_session(result.session.id, "repeat")
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 1
    await client.close()
    store.close()


async def test_active_context_limit_is_independent_of_cumulative_budget(tmp_path):
    requests = []
    client = sdk_client([], requests, count=95)
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client)
    with pytest.raises(ExecutionError) as error:
        await runtime.start(
            "work",
            ModelConfig(model="exact-model"),
            RuntimeLimits(max_context_tokens=100, max_output_tokens=10, max_total_tokens=1000),
        )
    assert error.value.code == "CONTEXT_LIMIT"
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 0
    await client.close()
    store.close()


@pytest.mark.parametrize("with_hook", [True, False])
async def test_context_pressure_handoff_after_settled_tool_output(tmp_path, with_hook):
    requests, effects, pressures = [], [], []
    dispatcher = ToolDispatcher()

    async def observe(arguments, operation_id):
        effects.append(operation_id)
        return {"large": "x" * 200}

    dispatcher.register(
        "observe",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        observe,
    )
    client = sdk_client([response([call_item("a")], "r1")], requests, count=[10, 95])
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")

    async def boundary(checkpoint):
        pressure = checkpoint.native_state.get("context_pressure")
        if pressure:
            pressures.append(pressure)
            assert checkpoint.native_state["settled_boundary"] is True
            assert checkpoint.native_state["input"][-1]["call_id"] == "a"
            return {"reason": "automatic_context_boundary"}
        return None

    runtime = ResponsesRuntime(
        store=store,
        client=client,
        dispatcher=dispatcher,
        boundary_hook=boundary if with_hook else None,
    )
    if with_hook:
        result = await runtime.start(
            "work",
            ModelConfig(model="exact-model"),
            RuntimeLimits(max_context_tokens=100, max_output_tokens=10, max_total_tokens=1000),
        )
        assert result.session.status == "handed_off"
        assert result.continuation["reason"] == "automatic_context_boundary"
        assert pressures == [
            {"input_tokens": 95, "max_context_tokens": 100, "max_output_tokens": 10}
        ]
    else:
        with pytest.raises(ExecutionError) as error:
            await runtime.start(
                "work",
                ModelConfig(model="exact-model"),
                RuntimeLimits(max_context_tokens=100, max_output_tokens=10, max_total_tokens=1000),
            )
        assert error.value.code == "CONTEXT_LIMIT"
    assert len(effects) == 1
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 1
    await client.close()
    store.close()


async def test_context_pressure_does_not_handoff_oversized_initial_prompt(tmp_path):
    requests, hook_calls = [], []
    client = sdk_client([], requests, count=95)
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")

    async def boundary(checkpoint):
        hook_calls.append(checkpoint)
        return {"reason": "automatic_context_boundary"}

    runtime = ResponsesRuntime(store=store, client=client, boundary_hook=boundary)
    with pytest.raises(ExecutionError) as error:
        await runtime.start(
            "oversized",
            ModelConfig(model="exact-model"),
            RuntimeLimits(max_context_tokens=100, max_output_tokens=10, max_total_tokens=1000),
        )
    assert error.value.code == "CONTEXT_LIMIT"
    assert not hook_calls
    assert not [path for path, _ in requests if path.endswith("/responses")]
    await client.close()
    store.close()


async def test_duplicate_call_after_compaction_reuses_archived_result(tmp_path):
    requests, effects = [], []
    dispatcher = ToolDispatcher()

    async def observe(arguments, operation_id):
        effects.append(operation_id)
        return {"stable": len(effects)}

    dispatcher.register(
        "observe",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        observe,
    )
    client = sdk_client(
        [
            response([compaction_item("one"), call_item("same")], "r1"),
            response([call_item("same")], "r2"),
            response([text_item("done")], "r3"),
        ],
        requests,
    )
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client, dispatcher=dispatcher)
    result = await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    assert effects == [f"{result.session.id}:same"]
    creates = [payload for path, payload in requests if path.endswith("/responses")]
    assert json.loads(creates[2]["input"][-1]["output"]) == {"stable": 1}
    await client.close()
    store.close()


async def test_many_compactions_keep_small_checkpoint_and_all_history(tmp_path):
    requests = []
    dispatcher = ToolDispatcher()

    async def observe(arguments, operation_id):
        return {"seen": True}

    dispatcher.register(
        "observe",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        observe,
    )
    responses = [
        response(
            [
                {"id": f"reason-{i}", "type": "reasoning", "encrypted_content": "X" * 10000},
                compaction_item(str(i)),
                call_item(str(i)),
            ],
            f"r{i}",
        )
        for i in range(20)
    ]
    responses.append(response([text_item("done")], "final"))
    client = sdk_client(responses, requests)
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client, dispatcher=dispatcher)
    result = await runtime.start(
        "work", ModelConfig(model="exact-model"), RuntimeLimits(max_turns=30)
    )
    checkpoint = await runtime.checkpoint(result.session.id)
    assert len(checkpoint.native_state["archives"]) == 20
    assert len(checkpoint.model_dump_json()) < 20000
    history = [
        await store.load_archive(result.session.id, archive_id)
        for archive_id in checkpoint.native_state["archives"]
    ]
    assert [part["responses"][0]["id"] for part in history] == [f"r{i}" for i in range(20)]
    assert history[0]["responses"][0]["output"][0]["encrypted_content"] == "X" * 10000
    await client.close()
    store.close()


async def test_malformed_compaction_does_not_prune_or_run_boundary_hook(tmp_path):
    requests, hooks = [], []
    malformed = {"id": "compact-empty", "type": "compaction", "encrypted_content": ""}
    client = sdk_client([response([malformed, call_item("a")], "r1")], requests)
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    dispatcher = ToolDispatcher()

    async def observe(arguments, operation_id):
        return {"seen": True}

    async def boundary(checkpoint):
        hooks.append(checkpoint)
        return {"reason": "handoff"}

    dispatcher.register(
        "observe",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        observe,
    )
    runtime = ResponsesRuntime(
        store=store, client=client, dispatcher=dispatcher, boundary_hook=boundary
    )
    with pytest.raises(ExecutionError) as error:
        await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    assert error.value.code == "INVALID_COMPACTION"
    assert hooks == []
    assert store.db.execute("SELECT COUNT(*) FROM runtime_archives").fetchone()[0] == 0
    await client.close()
    store.close()


async def test_compaction_reanchors_fresh_scientific_context_before_next_request(tmp_path):
    requests, anchors = [], []
    dispatcher = ToolDispatcher()

    async def observe(arguments, operation_id):
        return {"seen": True}

    async def anchor():
        anchors.append(1)
        return "Exact target digest T; current obligation O"

    dispatcher.register(
        "observe",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        observe,
    )
    client = sdk_client(
        [
            response([compaction_item("one"), call_item("a")], "r1"),
            response([text_item("done")], "r2"),
        ],
        requests,
    )
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(
        store=store, client=client, dispatcher=dispatcher, context_anchor=anchor
    )
    await runtime.start("original target", ModelConfig(model="exact-model"), RuntimeLimits())
    creates = [payload for path, payload in requests if path.endswith("/responses")]
    assert anchors == [1]
    assert creates[1]["input"][-1] == {
        "role": "user",
        "content": "Exact target digest T; current obligation O",
    }
    await client.close()
    store.close()


async def test_stale_context_anchor_stops_before_next_paid_request(tmp_path):
    requests = []
    dispatcher = ToolDispatcher()

    async def observe(arguments, operation_id):
        return {"seen": True}

    async def stale_anchor():
        raise ExecutionError("TARGET_CHANGED", "Reviewed target changed")

    dispatcher.register(
        "observe",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        observe,
    )
    client = sdk_client([response([compaction_item("one"), call_item("a")], "r1")], requests)
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(
        store=store, client=client, dispatcher=dispatcher, context_anchor=stale_anchor
    )
    with pytest.raises(ExecutionError) as error:
        await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    assert error.value.code == "TARGET_CHANGED"
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 1
    checkpoint_data = store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0]
    checkpoint = json.loads(checkpoint_data)
    assert checkpoint["native_state"]["responses"][0]["id"] == "r1"
    assert checkpoint["native_state"]["pending_operation"] is None
    await client.close()
    store.close()


async def test_inline_compaction_requires_finite_active_context_cap(tmp_path):
    requests = []
    client = sdk_client([], requests)
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client)
    with pytest.raises(ExecutionError) as error:
        await runtime.start(
            "work",
            ModelConfig(
                model="exact-model",
                parameters={
                    "context_management": [{"type": "compaction", "compact_threshold": 80}]
                },
            ),
            RuntimeLimits(max_output_tokens=10, max_total_tokens=1000),
        )
    assert error.value.code == "INVALID_CONFIG"
    assert requests == []
    await client.close()
    store.close()


async def test_provider_usage_over_reservation_is_recorded_then_stops(tmp_path):
    requests, events = [], []
    client = sdk_client(
        [response([text_item("done")], "r1", input_tokens=101, output_tokens=5)], requests
    )
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")

    async def emit(event):
        events.append(event)

    runtime = ResponsesRuntime(store=store, client=client, event_sink=emit)
    with pytest.raises(ExecutionError) as error:
        await runtime.start(
            "work",
            ModelConfig(
                model="exact-model",
                parameters={
                    "context_management": [{"type": "compaction", "compact_threshold": 80}]
                },
            ),
            RuntimeLimits(max_context_tokens=100, max_output_tokens=10, max_total_tokens=1000),
        )
    assert error.value.code == "PROVIDER_LIMIT_VIOLATION"
    assert events[0].payload["input_tokens_reserved"] == 100
    assert events[1].kind == "usage" and events[1].payload["input_tokens"] == 101
    checkpoint = await runtime.checkpoint(events[0].session_id)
    assert checkpoint.session.input_tokens == 101
    assert checkpoint.native_state["pending_operation"] is None
    await client.close()
    store.close()


async def test_failed_generation_reservation_is_known_unsent(tmp_path):
    requests = []
    client = sdk_client([], requests)
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")

    async def reject_reservation(event):
        if event.kind == "generation_started":
            raise ExecutionError("BUDGET_EXCEEDED", "No experiment headroom")

    runtime = ResponsesRuntime(store=store, client=client, event_sink=reject_reservation)
    with pytest.raises(ExecutionError) as error:
        await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    assert error.value.code == "BUDGET_EXCEEDED"
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 0
    checkpoint = json.loads(store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0])
    assert checkpoint["session"]["status"] == "failed"
    assert checkpoint["native_state"]["pending_operation"] is None
    await client.close()
    store.close()


async def test_compaction_only_completed_response_can_continue(tmp_path):
    requests = []
    client = sdk_client(
        [
            response([compaction_item("one")], "r1"),
            response([text_item("done")], "r2"),
        ],
        requests,
    )
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client)
    result = await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    assert result.output_text == "done"
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 2
    checkpoint = await runtime.checkpoint(result.session.id)
    assert len(checkpoint.native_state["archives"]) == 1
    await client.close()
    store.close()


async def test_settled_usage_before_compaction_prune_crash_is_locally_identifiable(tmp_path):
    requests = []
    client = sdk_client([response([compaction_item("one")], "r1")], requests)

    class CrashAfterSettlement(SQLiteRuntimeStore):
        tripped = False

        async def save(self, checkpoint):
            await super().save(checkpoint)
            state = checkpoint.native_state
            if (
                not self.tripped
                and state.get("pending_operation") is None
                and state.get("settled_boundary") is False
                and state.get("responses")
            ):
                self.tripped = True
                raise asyncio.CancelledError()

    store = CrashAfterSettlement(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client)
    with pytest.raises(asyncio.CancelledError):
        await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    checkpoint = RuntimeCheckpoint.model_validate_json(
        store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0]
    )
    assert checkpoint.session.status == "interrupted"
    assert checkpoint.native_state["pending_operation"] is None
    assert checkpoint.native_state["settled_boundary"] is False
    assert checkpoint.native_state["responses"][-1]["id"] == "r1"
    assert checkpoint.session.input_tokens == 10
    assert checkpoint.session.output_tokens == 5
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 1
    with pytest.raises(ExecutionError, match="unsettled"):
        await runtime.resume(checkpoint)
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 1
    replay_state = checkpoint.native_state.copy()
    await runtime._advance_active_input(
        checkpoint.session, replay_state, replay_state["responses"][-1]
    )
    assert replay_state["last_compaction_id"] == "compact-one"
    assert replay_state["active_input_epoch"] == 1
    assert len(replay_state["archives"]) == 1
    assert replay_state["responses"] == []
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 1
    await client.close()
    store.close()


async def test_compaction_recovery_survives_second_crash_without_reissuing_paid_turn(tmp_path):
    requests = []
    client = sdk_client(
        [response([compaction_item("one")], "r1"), response([text_item("done")], "r2")],
        requests,
    )

    class TwiceInterruptedStore(SQLiteRuntimeStore):
        stage = 0

        async def save(self, checkpoint):
            await super().save(checkpoint)
            state = checkpoint.native_state
            if (
                self.stage == 0
                and state.get("pending_operation") is None
                and state.get("settled_boundary") is False
                and state.get("responses")
            ):
                self.stage = 1
                raise asyncio.CancelledError()
            if (
                self.stage == 1
                and state.get("last_compaction_id") == "compact-one"
                and state.get("settled_boundary") is False
            ):
                self.stage = 2
                raise asyncio.CancelledError()

    store = TwiceInterruptedStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client)
    with pytest.raises(asyncio.CancelledError):
        await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    first = await store.load(store.db.execute("SELECT id FROM runtime_sessions").fetchone()[0])
    assert first.native_state["pending_operation"] is None
    assert first.native_state["settled_boundary"] is False
    assert runtime.compaction_recovery_candidate(first)
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 1
    with pytest.raises(asyncio.CancelledError):
        await runtime.recover_compaction(first)
    second = await store.load(first.session.id)
    assert second.native_state["responses"] == []
    assert second.native_state["settled_boundary"] is False
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 1
    result = await runtime.recover_compaction(second)
    assert result.output_text == "done"
    creates = [body for path, body in requests if path.endswith("/responses")]
    assert len(creates) == 2
    assert creates[0]["input"][-1] == {"role": "user", "content": "work"}
    assert creates[1]["input"].count({"role": "user", "content": "work"}) == 1
    assert creates[1]["input"][0] == compaction_item("one")
    assert len((await store.load(result.session.id)).native_state["archives"]) == 1
    await client.close()
    store.close()


async def test_later_tool_response_clears_stale_compaction_recovery_marker(tmp_path):
    requests = []
    client = sdk_client(
        [response([compaction_item("one")], "r1"), response([call_item("a")], "r2")],
        requests,
    )

    class CrashOnSecondResponse(SQLiteRuntimeStore):
        tripped = False

        async def save(self, checkpoint):
            await super().save(checkpoint)
            state = checkpoint.native_state
            if (
                not self.tripped
                and checkpoint.session.turns == 2
                and state.get("pending_operation") is None
                and state.get("settled_boundary") is False
            ):
                self.tripped = True
                raise asyncio.CancelledError()

    store = CrashOnSecondResponse(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client)
    with pytest.raises(asyncio.CancelledError):
        await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    saved = await store.load(store.db.execute("SELECT id FROM runtime_sessions").fetchone()[0])
    assert saved.native_state.get("compaction_replay_pending") is None
    assert not runtime.compaction_recovery_candidate(saved)
    with pytest.raises(ExecutionError) as error:
        await runtime.recover_compaction(saved)
    assert error.value.code == "COMPACTION_RECOVERY_INVALID"
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 2
    await client.close()
    store.close()


async def test_overreserved_compaction_usage_cannot_recover(tmp_path):
    requests = []
    client = sdk_client([response([compaction_item("one")], "r1", input_tokens=100)], requests)

    class CrashAfterSettlement(SQLiteRuntimeStore):
        tripped = False

        async def save(self, checkpoint):
            await super().save(checkpoint)
            state = checkpoint.native_state
            if (
                not self.tripped
                and state.get("pending_operation") is None
                and state.get("settled_boundary") is False
                and state.get("responses")
            ):
                self.tripped = True
                raise asyncio.CancelledError()

    store = CrashAfterSettlement(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client)
    with pytest.raises(asyncio.CancelledError):
        await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    saved = await store.load(store.db.execute("SELECT id FROM runtime_sessions").fetchone()[0])
    assert saved.native_state["settled_response"]["input_reserved"] == 10
    with pytest.raises(ExecutionError) as error:
        await runtime.recover_compaction(saved)
    assert error.value.code == "COMPACTION_RECOVERY_INVALID"
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 1
    await client.close()
    store.close()


@pytest.mark.parametrize("tamper", ["usage", "marker", "input", "tool", "text"])
async def test_compaction_recovery_rejects_unbound_or_effectful_evidence(tmp_path, tamper):
    requests = []
    client = sdk_client([response([compaction_item("one")], "r1")], requests)

    class InterruptedStore(SQLiteRuntimeStore):
        tripped = False

        async def save(self, checkpoint):
            await super().save(checkpoint)
            state = checkpoint.native_state
            if (
                not self.tripped
                and state.get("pending_operation") is None
                and state.get("settled_boundary") is False
                and state.get("responses")
            ):
                self.tripped = True
                raise asyncio.CancelledError()

    store = InterruptedStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client)
    with pytest.raises(asyncio.CancelledError):
        await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    saved = await store.load(store.db.execute("SELECT id FROM runtime_sessions").fetchone()[0])
    session, state = saved.session.model_copy(deep=True), saved.native_state.copy()
    if tamper == "usage":
        session.input_tokens = 0
    elif tamper == "marker":
        state["compaction_replay_pending"] = {
            "response_id": "r1",
            "latest_item_id": "other",
        }
    elif tamper == "input":
        state["input"] = [{"role": "user", "content": "changed"}]
    elif tamper == "tool":
        state["responses"] = [{**state["responses"][-1], "output": [call_item("a")]}]
    else:
        state["responses"] = [{**state["responses"][-1], "output": [text_item("done")]}]
    changed = RuntimeCheckpoint.build(session, state)
    await store.save(changed)
    with pytest.raises(ExecutionError) as error:
        await runtime.recover_compaction(changed)
    assert error.value.code == "COMPACTION_RECOVERY_INVALID"
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 1
    await client.close()
    store.close()


async def test_interrupted_response_before_tool_output_is_not_safe_to_resume(tmp_path):
    requests = []
    client = sdk_client([response([call_item("a")], "r1")], requests)

    class InterruptedStore(SQLiteRuntimeStore):
        tripped = False

        async def save(self, checkpoint):
            await super().save(checkpoint)
            state = checkpoint.native_state
            if (
                not self.tripped
                and state.get("pending_operation") is None
                and state.get("responses")
                and not any(item.get("type") == "function_call_output" for item in state["input"])
            ):
                self.tripped = True
                raise asyncio.CancelledError()

    store = InterruptedStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client)
    with pytest.raises(asyncio.CancelledError):
        await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    checkpoint = store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0]
    native = json.loads(checkpoint)
    assert native["session"]["status"] == "interrupted"
    assert native["native_state"]["settled_boundary"] is False
    with pytest.raises(ExecutionError) as error:
        await runtime.resume(await runtime.checkpoint(native["session"]["id"]))
    assert error.value.code == "OPERATION_UNCERTAIN"
    await client.close()
    store.close()


async def test_running_checkpoint_can_be_adopted_only_at_settled_boundary(tmp_path):
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=object())
    session = RuntimeSession(
        runtime="openai_responses", model=ModelConfig(model="exact-model"), limits=RuntimeLimits()
    )
    session.status = "running"
    state = {
        "input": [{"role": "user", "content": "work"}],
        "responses": [],
        "pending_operation": None,
        "settled_boundary": True,
    }
    checkpoint = RuntimeCheckpoint.build(session, state)
    await store.save(checkpoint)
    adopted = await runtime.resume(checkpoint)
    assert adopted.status == "ready"
    assert (await store.load(session.id)).session.status == "ready"
    for field, value in [("settled_boundary", False), ("pending_tool_call", "tool-1")]:
        unsafe = dict(state, **{field: value})
        unsafe_checkpoint = RuntimeCheckpoint.build(session, unsafe)
        with pytest.raises(ExecutionError) as error:
            await runtime.resume(unsafe_checkpoint)
        assert error.value.code == "OPERATION_UNCERTAIN"
    store.close()


async def test_completed_result_reconstructs_exact_output_without_provider(tmp_path):
    requests = []
    final_items = [
        {"id": "reason-final", "type": "reasoning", "encrypted_content": "opaque"},
        text_item("first"),
        text_item("second"),
    ]
    client = sdk_client([response(final_items, "final-response")], requests)
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client)
    original = await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    checkpoint = await runtime.checkpoint(original.session.id)
    request_count = len(requests)
    recovered = ResponsesRuntime.completed_result(checkpoint)
    assert recovered.output_text == original.output_text == "firstsecond"
    assert recovered.native_items == final_items
    assert recovered.artifacts == original.artifacts
    assert recovered.artifacts[0].provenance == {
        "runtime": "openai_responses",
        "model": "exact-model",
        "session_id": original.session.id,
        "response_id": "final-response",
    }
    assert len(requests) == request_count
    await client.close()
    store.close()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s, n: setattr(s, "status", "running"),
        lambda s, n: n.update(settled_boundary=False),
        lambda s, n: n.update(pending_operation="unknown"),
        lambda s, n: n.update(pending_tool_call="unknown"),
        lambda s, n: n.update(responses=[]),
        lambda s, n: setattr(s, "native_session_id", "different"),
        lambda s, n: n["responses"][-1].update(id="different"),
        lambda s, n: n["responses"][-1].update(output=[]),
        lambda s, n: n["responses"][-1].update(status="incomplete"),
    ],
)
def test_completed_result_rejects_unsafe_or_inconsistent_checkpoint(mutation):
    native = response([text_item("done")], "final-response")
    session = RuntimeSession(
        runtime="openai_responses",
        model=ModelConfig(model="exact-model"),
        limits=RuntimeLimits(),
        status="completed",
        native_session_id="final-response",
        turns=1,
        input_tokens=10,
        output_tokens=5,
    )
    state = {
        "input": [{"role": "user", "content": "work"}, *native["output"]],
        "responses": [native],
        "settled_boundary": True,
        "pending_operation": None,
    }
    mutation(session, state)
    with pytest.raises(ExecutionError) as error:
        ResponsesRuntime.completed_result(RuntimeCheckpoint.build(session, state))
    assert error.value.code == "COMPLETED_RESULT_INVALID"
