"""Native Responses context management and clean continuation boundaries."""

import asyncio
import hashlib
import json

import httpx
import pytest
from openai import AsyncOpenAI

from physharness.domain import ContextBudget, canonical_json
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
                and (state.get("pending_operation") or "").endswith(":a")
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
            if not self.tripped and (state.get("pending_operation") or "").endswith(":a"):
                self.tripped = True
                raise asyncio.CancelledError()

    store = InterruptedStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(store=store, client=client)
    with pytest.raises(asyncio.CancelledError):
        await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    checkpoint = store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0]
    native = json.loads(checkpoint)
    assert native["session"]["status"] == "uncertain"
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


def observe_dispatcher(result=None):
    dispatcher = ToolDispatcher()

    async def observe(arguments, operation_id):
        return result if result is not None else {"seen": True}

    dispatcher.register(
        "observe",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        observe,
    )
    return dispatcher


COMPACTING = {"context_management": [{"type": "compaction", "compact_threshold": 40_000}]}

WIDE = RuntimeLimits(max_context_tokens=64_000, max_output_tokens=1_000, max_total_tokens=None)


async def test_compaction_epoch_invalidates_the_estimate(tmp_path):
    requests = []
    client = sdk_client(
        [
            response([compaction_item("one"), call_item("a")], "r1"),
            response([call_item("b")], "r2"),
            response([text_item("done")], "r3"),
        ],
        requests,
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "sessions.db"),
        client=client,
        dispatcher=observe_dispatcher(),
    )
    await runtime.start("work", ModelConfig(model="exact-model", parameters=COMPACTING), WIDE)
    assert [p.rsplit("/", 1)[-1] for p, _ in requests] == [
        "input_tokens",
        "responses",
        "input_tokens",
        "responses",
        "responses",
    ]
    await client.close()


async def run_reserved(tmp_path, threshold, window, final_input=10):
    requests, events, error = [], [], None

    async def emit(event):
        events.append(event)

    client = sdk_client(
        [
            response([call_item("a")], "r1"),
            response([text_item("done")], "r2", input_tokens=final_input),
        ],
        requests,
    )
    tmp_path.mkdir()
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "sessions.db"),
        client=client,
        dispatcher=observe_dispatcher(),
        event_sink=emit,
    )
    params = {"context_management": [{"type": "compaction", "compact_threshold": threshold}]}
    try:
        await runtime.start(
            "work",
            ModelConfig(model="exact-model", parameters=params),
            RuntimeLimits(
                max_context_tokens=window, max_output_tokens=1_000, max_total_tokens=None
            ),
        )
    except ExecutionError as caught:
        error = caught
    await client.close()
    creates = [p for path, p in requests if path.endswith("/responses")]
    return (
        creates,
        [e.payload["input_tokens_reserved"] for e in events if e.kind == "generation_started"],
        error,
    )


async def test_reservation_bound_window_fallback_and_violation(tmp_path):
    creates, reserved, error = await run_reserved(tmp_path / "bound", 40_000, 64_000)
    appended = creates[1]["input"][len(creates[0]["input"]) :]
    assert error is None and reserved == [
        10 + 2048,  # the count plus the P1 margin
        10 + sum(len(canonical_json(i).encode("utf-8")) for i in appended) + 2048,  # P1 bound
    ]
    # count + margin + 8,192 > threshold
    _, reserved, error = await run_reserved(tmp_path / "near", 8_200, 10_000)
    assert error is None and reserved == [10_000, 10_000]
    _, reserved, error = await run_reserved(tmp_path / "over", 40_000, 64_000, final_input=5_000)
    assert reserved[1] < 5_000 and error.code == "PROVIDER_LIMIT_VIOLATION"


async def test_compaction_on_a_request_reserved_below_the_window_raises_an_alarm(tmp_path):
    requests, events = [], []

    async def emit(event):
        events.append(event)

    client = sdk_client(
        [
            response([compaction_item("one"), call_item("a")], "r1"),
            response([text_item("done")], "r2"),
        ],
        requests,
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "sessions.db"),
        client=client,
        dispatcher=observe_dispatcher(),
        event_sink=emit,
    )
    await runtime.start("work", ModelConfig(model="exact-model", parameters=COMPACTING), WIDE)
    assert [e.payload for e in events if e.kind == "bound_reservation_compacted"] == [
        {
            "response_id": "r1",
            "input_tokens_reserved": 10 + 2048,
            "input_tokens": 10,
            "compact_threshold": 40_000,
        }
    ]
    await client.close()


async def test_compaction_on_a_request_reserved_at_the_window_raises_no_alarm(tmp_path):
    events = []

    async def emit(event):
        events.append(event)

    client = sdk_client([response([compaction_item("one"), text_item("done")], "r1")], [])
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "sessions.db"), client=client, event_sink=emit
    )
    params = {"context_management": [{"type": "compaction", "compact_threshold": 8_200}]}
    await runtime.start(
        "work",
        ModelConfig(model="exact-model", parameters=params),
        RuntimeLimits(max_context_tokens=10_000, max_output_tokens=1_000, max_total_tokens=None),
    )
    assert [
        e.payload["input_tokens_reserved"] for e in events if e.kind == "generation_started"
    ] == [10_000]
    assert "bound_reservation_compacted" not in [e.kind for e in events]
    await client.close()


@pytest.mark.parametrize("settles", [False, True])
async def test_the_alarm_precedes_usage_so_a_halt_on_settlement_still_names_the_cause(
    tmp_path, settles
):
    events = []

    async def emit(event):
        events.append(event)
        if settles and event.kind == "usage":
            # As the worker's accounting sink does when settlement finds an overrun.
            raise ExecutionError("BUDGET_RECONCILIATION_REQUIRED", "Usage exceeds reservation")

    client = sdk_client(
        [response([compaction_item("one"), call_item("a")], "r1", input_tokens=5_000)], []
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "sessions.db"),
        client=client,
        dispatcher=observe_dispatcher(),
        event_sink=emit,
    )
    with pytest.raises(ExecutionError) as error:
        await runtime.start("work", ModelConfig(model="exact-model", parameters=COMPACTING), WIDE)
    assert error.value.code == (
        "BUDGET_RECONCILIATION_REQUIRED" if settles else "PROVIDER_LIMIT_VIOLATION"
    )
    assert [e.kind for e in events] == [
        "generation_started",
        "bound_reservation_compacted",
        "usage",
    ]
    await client.close()


@pytest.mark.parametrize(
    ("threshold", "count", "reserved"),
    [
        (None, 10, 10),  # without compaction a count is reserved exactly
        (183_808, 10, 10 + 2_048),
        (183_808, 150_000, 150_000 + 3_000),  # 2% of the count exceeds the 2,048 floor
        (183_808, 175_000, 256_000),  # count + 8,192 fits the gate, count + margin does not
    ],
)
async def test_a_counted_request_under_compaction_reserves_the_count_plus_the_margin(
    tmp_path, threshold, count, reserved
):
    events = []

    async def emit(event):
        events.append(event)

    client = sdk_client([response([text_item("done")], "r1", input_tokens=count)], [], count=count)
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "sessions.db"), client=client, event_sink=emit
    )
    params = (
        {"context_management": [{"type": "compaction", "compact_threshold": threshold}]}
        if threshold
        else {}
    )
    await runtime.start(
        "work",
        ModelConfig(model="exact-model", parameters=params),
        RuntimeLimits(max_context_tokens=256_000, max_output_tokens=1_000, max_total_tokens=None),
    )
    assert [
        (e.payload["input_tokens_estimate"], e.payload["input_tokens_reserved"])
        for e in events
        if e.kind == "generation_started"
    ] == [(count, reserved)]
    await client.close()


async def test_create_400_is_pre_generation_not_uncertain(tmp_path):
    events = []

    def handle(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "private schema text",
                    "type": "invalid_request_error",
                    "param": "tools[0].parameters",
                    "code": "invalid_function_parameters",
                }
            },
        )

    async def emit(event):
        events.append(event)

    client = AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    with pytest.raises(ExecutionError) as error:
        await ResponsesRuntime(store=store, client=client, event_sink=emit).start(
            "work", ModelConfig(model="exact-model"), RuntimeLimits()
        )
    assert error.value.code == "PROVIDER_TOOL_SCHEMA_INVALID"
    assert [(e.kind, e.payload.get("reason")) for e in events] == [
        ("generation_started", None),
        ("generation_aborted", "request_invalid"),
    ]
    saved = RuntimeCheckpoint.model_validate_json(
        store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0]
    )
    assert (saved.session.status, saved.native_state["pending_operation"]) == ("failed", None)
    assert saved.native_state["preflight_error"] == {
        "stage": "create",
        "operation_id": events[0].operation_id,
        "provider_code": "invalid_function_parameters",
        "provider_param": "tools[0].parameters",
    }
    assert "private" not in saved.model_dump_json()
    await client.close()


BUDGET = ContextBudget(max_output_chars=20_000)


def big_result(size):
    return {"text": "∀" + "x" * size}


def recall_item(call_id, target, offset):
    return {
        "id": "fc-" + call_id,
        "type": "function_call",
        "call_id": call_id,
        "name": "recall_output",
        "arguments": json.dumps({"call_id": target, "offset": offset}),
        "status": "completed",
    }


def outputs_of(payload):
    return {
        i["call_id"]: i["output"]
        for i in payload["input"]
        if i.get("type") == "function_call_output"
    }


def creates_of(requests):
    return [payload for path, payload in requests if path.endswith("/responses")]


async def test_oversized_output_is_truncated_and_recalled_exactly(tmp_path):
    requests = []
    client = sdk_client(
        [
            response([call_item("a")], "r1"),
            response([recall_item("p1", "a", 0)], "r2"),
            response([recall_item("p2", "a", 16_000)], "r3"),
            response([recall_item("p3", "a", 32_000)], "r4"),
            response([text_item("done")], "r5"),
        ],
        requests,
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "sessions.db"),
        client=client,
        dispatcher=observe_dispatcher(big_result(40_000)),
        context_budget=BUDGET,
    )
    await runtime.start(
        "work", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
    )
    creates = creates_of(requests)
    assert creates[0]["tools"][-1]["name"] == "recall_output"
    outputs, original = outputs_of(creates[-1]), json.dumps(big_result(40_000), ensure_ascii=False)
    view = json.loads(outputs["a"])
    assert (view["truncated"], view["total_chars"], view["head"]) == (
        True,
        len(original),
        original[:10_000],
    )
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
    source = ResponsesRuntime(
        store=store,
        client=first,
        dispatcher=observe_dispatcher(big_result(100)),
        boundary_hook=boundary,
        context_budget=BUDGET,
    )
    handed = await source.start("work", model, limits)
    second = sdk_client(
        [response([recall_item("p1", "a", 0)], "r2"), response([text_item("done")], "r3")],
        requests,
    )
    successor = ResponsesRuntime(
        store=store, client=second, dispatcher=observe_dispatcher(big_result(100))
    )
    await successor.start_from_handoff(
        await source.checkpoint(handed.session.id), "continue", model, limits
    )
    final = creates_of(requests)[-1]
    assert final["tools"][-1]["name"] == "recall_output"
    assert json.loads(outputs_of(final)["p1"])["text"] == json.dumps(
        big_result(100), ensure_ascii=False
    )
    await first.close()
    await second.close()


async def test_no_context_budget_keeps_requests_and_state_unchanged(tmp_path):
    requests = []
    client = sdk_client(
        [response([call_item("a")], "r1"), response([text_item("done")], "r2")], requests
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "sessions.db"),
        client=client,
        dispatcher=observe_dispatcher(big_result(30_000)),
    )
    result = await runtime.start(
        "work", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
    )
    creates = creates_of(requests)
    assert all(tool["name"] != "recall_output" for p in creates for tool in p["tools"])
    assert outputs_of(creates[1])["a"] == json.dumps(
        big_result(30_000), allow_nan=False
    )  # escaped, uncapped
    assert "context_budget" not in (await runtime.checkpoint(result.session.id)).native_state
    await client.close()


async def test_a_registered_recall_output_is_rejected_under_a_budget(tmp_path):
    requests, dispatcher = [], ToolDispatcher()

    async def recall(arguments, operation_id):
        return {}

    dispatcher.register("recall_output", {"type": "object", "properties": {}}, recall)
    client = sdk_client([], requests)
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "sessions.db"),
        client=client,
        dispatcher=dispatcher,
        context_budget=BUDGET,
    )
    with pytest.raises(ExecutionError) as error:
        await runtime.start("work", ModelConfig(model="exact-model"), RuntimeLimits())
    assert error.value.code == "INVALID_CONFIG" and requests == []
    await client.close()


async def test_a_recall_is_unstored_but_announced_like_any_call(tmp_path):
    requests, events = [], []

    async def emit(event):
        events.append(event)

    recalls = [response([recall_item(f"p{n}", "a", 0)], f"r{n}") for n in range(1, 5)]
    client = sdk_client(
        [response([call_item("a")], "r0"), *recalls, response([text_item("done")], "r5")],
        requests,
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "sessions.db"),
        client=client,
        dispatcher=observe_dispatcher(big_result(100)),
        event_sink=emit,
        context_budget=BUDGET,
    )
    result = await runtime.start(
        "work", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
    )
    announced = [
        (e.kind, e.operation_id.rsplit(":", 1)[-1])
        for e in events
        if e.kind in {"tool_completed", "stagnation_warning"}
    ]
    assert announced == [
        *[("tool_completed", call_id) for call_id in ("a", "p1", "p2", "p3", "p4")],
        ("stagnation_warning", "p4"),
    ]
    names = [e.payload["name"] for e in events if e.kind == "tool_completed"]
    assert names == ["observe", *["recall_output"] * 4]
    state = (await runtime.checkpoint(result.session.id)).native_state
    assert list(state["tool_results"]) == [f"{result.session.id}:a"]
    assert "_research_runtime_signal" in json.loads(outputs_of(creates_of(requests)[-1])["p4"])
    await client.close()


async def test_a_truncated_head_and_its_recall_join_exactly_after_a_reload(tmp_path):
    # Checkpoints store results with sorted keys, so the head must use the same key order.
    requests, store = [], SQLiteRuntimeStore(tmp_path / "sessions.db")
    model, limits = ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
    unsorted = {"z": "x" * 20_000, "a": "∀" * 5_000}

    async def boundary(checkpoint):
        return {"reason": "test_handoff"}

    first = sdk_client([response([call_item("a")], "r1")], requests)
    source = ResponsesRuntime(
        store=store,
        client=first,
        dispatcher=observe_dispatcher(unsorted),
        boundary_hook=boundary,
        context_budget=BUDGET,
    )
    handed = await source.start("work", model, limits)
    second = sdk_client(
        [response([recall_item("p1", "a", 10_000)], "r2"), response([text_item("done")], "r3")],
        requests,
    )
    successor = ResponsesRuntime(store=store, client=second, dispatcher=observe_dispatcher())
    await successor.start_from_handoff(
        await source.checkpoint(handed.session.id), "continue", model, limits
    )
    outputs = outputs_of(creates_of(requests)[-1])
    view, page = json.loads(outputs["a"]), json.loads(outputs["p1"])
    assert page["next_offset"] is None
    assert json.loads(view["head"] + page["text"]) == unsorted
    await first.close()
    await second.close()


class ObjectStore:
    """Keeps checkpoint objects. The SQLite and chunk encoders reject a lone surrogate anywhere in
    a checkpoint, for every experiment; this isolates what the runtime renders and sends."""

    def __init__(self):
        self.saved = {}

    async def save(self, checkpoint):
        checkpoint.verify()
        self.saved[checkpoint.session.id] = checkpoint


async def test_a_lone_surrogate_under_a_budget_keeps_the_lineage_sendable():
    # UTF-8 cannot encode a lone surrogate, so it keeps the escape legacy output uses.
    # ToolDispatcher escapes its own results; this covers a dispatch override that does not.
    requests = []
    result = {"path": "notes/\ud800∀.md", "text": "x" * 30_000}
    dispatcher = observe_dispatcher()

    async def unscrubbed(name, arguments, operation_id):
        return result

    dispatcher.dispatch = unscrubbed
    client = sdk_client(
        [
            response([call_item("a")], "r1"),
            response([recall_item("p1", "a", 0)], "r2"),
            response([text_item("done")], "r3"),
        ],
        requests,
    )
    runtime = ResponsesRuntime(
        store=ObjectStore(),
        client=client,
        dispatcher=dispatcher,
        context_budget=BUDGET,
    )
    await runtime.start(
        "work", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
    )
    creates = creates_of(requests)
    assert len(creates) == 3
    outputs = outputs_of(creates[-1])
    original = json.dumps(result, ensure_ascii=False, sort_keys=True)
    for call_id in ("a", "p1"):
        assert "notes/\\ud800∀.md" in outputs[call_id]  # escaped surrogate, literal ∀
    assert json.loads(outputs["a"])["head"] == original[:10_000]
    assert json.loads(outputs["p1"])["text"] == original[:16_000]
    await client.close()


ELIDE = ContextBudget(
    elide_min_chars=500, elide_after_turns=1, elide_every_turns=3, max_output_chars=None
)


async def run_elided(tmp_path, requests, events, calls, store=None):
    async def emit(event):
        events.append(event)

    client = sdk_client(
        [
            *[response([call_item(f"c{i}")], f"r{i}") for i in range(1, calls + 1)],
            response([text_item("done")], "rt"),
        ],
        requests,
    )
    runtime = ResponsesRuntime(
        store=store or SQLiteRuntimeStore(tmp_path / "sessions.db"),
        client=client,
        dispatcher=observe_dispatcher(big_result(2_000)),
        event_sink=emit,
        context_budget=ELIDE,
    )
    result = await runtime.start(
        "work", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
    )
    await client.close()
    return runtime, result


async def test_elision_blocks_keep_the_prefix_stable_between_boundaries(tmp_path):
    requests, events = [], []
    await run_elided(tmp_path, requests, events, calls=6)
    inputs = [p["input"] for p in creates_of(requests)]
    assert [inputs[n + 1][: len(inputs[n])] == inputs[n] for n in range(6)] == [
        True,
        True,
        False,
        True,
        True,
        False,
    ]
    assert [e.payload["count"] for e in events if e.kind == "context_elided"] == [2, 3]
    fourth = outputs_of({"input": inputs[3]})
    assert json.loads(fourth["c1"])["recall"] == {"tool": "recall_output", "call_id": "c1"}
    assert fourth["c3"].startswith('{"text"')


async def test_elision_skips_small_recent_and_legacy_outputs(tmp_path):
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "sessions.db"), client=object())
    session = RuntimeSession(
        runtime="openai_responses", model=ModelConfig(model="exact-model"), limits=RuntimeLimits()
    )
    big = json.dumps({"text": "x" * 1_000})
    outputs = {"legacy": big, "small": "{}", "recent": big, "old": big}
    seqs = {"small": 1, "recent": 3, "old": 1}
    state = {
        "input": [
            {"type": "function_call_output", "call_id": k, "output": v} for k, v in outputs.items()
        ],
        "tool_results": {
            f"{session.id}:{k}": {
                "identity": "i",
                "result": {},
                **({"seq": seqs[k], "name": "observe"} if k in seqs else {}),
            }
            for k in outputs
        },
        "context_budget": ELIDE.model_dump(mode="json"),
        "elision": {"seq": 3, "last_block_seq": 0},
    }
    await runtime._elide_block(session, state)
    after = {i["call_id"]: i["output"] for i in state["input"]}
    assert (after["legacy"], after["small"], after["recent"]) == (big, "{}", big)
    assert json.loads(after["old"])["elided"] is True and state["elision"]["last_block_seq"] == 3


async def test_a_stub_longer_than_the_threshold_is_never_elided_again(tmp_path):
    runtime = ResponsesRuntime(store=SQLiteRuntimeStore(tmp_path / "sessions.db"), client=object())
    session = RuntimeSession(
        runtime="openai_responses", model=ModelConfig(model="exact-model"), limits=RuntimeLimits()
    )
    call_id = "c" * 120  # a long ID and an escaped head make the stub longer than elide_min_chars
    state = {
        "input": [
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps({"text": "\\" * 1_000}),
            }
        ],
        "tool_results": {
            f"{session.id}:{call_id}": {"identity": "i", "result": {}, "seq": 1, "name": "observe"}
        },
        "context_budget": ELIDE.model_dump(mode="json"),
        "elision": {"seq": 3, "last_block_seq": 0},
    }
    await runtime._elide_block(session, state)
    stub = state["input"][0]["output"]
    assert json.loads(stub)["elided"] is True and len(stub) > ELIDE.elide_min_chars
    state["elision"]["seq"] = 6
    await runtime._elide_block(session, state)
    assert state["input"][0]["output"] == stub and state["elision"]["last_block_seq"] == 6


async def test_elision_state_survives_resume_without_reeliding(tmp_path):
    requests, events = [], []
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime, result = await run_elided(tmp_path, requests, events, calls=3, store=store)
    saved = (await runtime.checkpoint(result.session.id)).native_state
    assert saved["elision"] == {"seq": 4, "last_block_seq": 3}
    second = sdk_client([response([text_item("again")], "r5")], requests)

    async def emit(event):
        events.append(event)

    resumed = ResponsesRuntime(
        store=store,
        client=second,
        dispatcher=observe_dispatcher(big_result(2_000)),
        event_sink=emit,
    )
    assert (await resumed.continue_session(result.session.id, "next")).output_text == "again"
    assert creates_of(requests)[-1]["input"][:-1] == saved["input"]
    assert len([e for e in events if e.kind == "context_elided"]) == 1
    await second.close()


async def test_an_elided_output_recalls_in_full_and_a_recall_page_is_never_elided(tmp_path):
    requests, events = [], []

    async def emit(event):
        events.append(event)

    client = sdk_client(
        [
            *[response([call_item(f"c{i}")], f"r{i}") for i in (1, 2, 3)],
            response([recall_item("p4", "c1", 0)], "r4"),
            *[response([call_item(f"c{i}")], f"r{i}") for i in (5, 6)],
            response([text_item("done")], "rt"),
        ],
        requests,
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "sessions.db"),
        client=client,
        dispatcher=observe_dispatcher(big_result(2_000)),
        event_sink=emit,
        context_budget=ELIDE,
    )
    result = await runtime.start(
        "work", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
    )
    original = json.dumps(big_result(2_000), ensure_ascii=False)
    outputs = outputs_of(creates_of(requests)[-1])
    assert json.loads(outputs["c1"]) == {
        "elided": True,
        "tool": "observe",
        "chars": len(original),
        "sha256": hashlib.sha256(original.encode("utf-8")).hexdigest()[:16],
        "head": original[:160],
        "recall": {"tool": "recall_output", "call_id": "c1"},
    }
    # The recall reads the full stored output, and its 2,000-character page is kept whole.
    page = json.loads(outputs["p4"])
    assert (page["text"], page["next_offset"]) == (original, None)
    # Block 1 (seq 3): c1 and c2. Block 2 (seq 6): c3 and c5, not the page from response 4.
    assert [e.payload["count"] for e in events if e.kind == "context_elided"] == [2, 2]
    assert [call_id for call_id, text in outputs.items() if text.startswith('{"elided"')] == [
        "c1",
        "c2",
        "c3",
        "c5",
    ]
    state = (await runtime.checkpoint(result.session.id)).native_state
    assert {
        k.split(":", 1)[1]: (v["seq"], v["name"]) for k, v in state["tool_results"].items()
    } == {f"c{n}": (n, "observe") for n in (1, 2, 3, 5, 6)}
    await client.close()


async def test_an_output_is_elided_only_when_its_stub_is_shorter(tmp_path):
    from physharness.execution.responses import _elision_stub

    # A 64-character tool name, a 29-character call ID and a backslash-heavy head: this
    # 502-character output would get a 528-character stub.
    requests, events, name, tight = [], [], "t" * 64, "call_" + "0" * 24
    dispatcher = observe_dispatcher(big_result(2_000))

    async def backslashes(arguments, operation_id):
        return {"text": "\\" * 245}

    dispatcher.register(
        name,
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        backslashes,
    )

    async def emit(event):
        events.append(event)

    client = sdk_client(
        [
            response([{**call_item(tight), "name": name}], "r1"),
            response([call_item("c2")], "r2"),
            response([call_item("c3")], "r3"),
            response([text_item("done")], "rt"),
        ],
        requests,
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "sessions.db"),
        client=client,
        dispatcher=dispatcher,
        event_sink=emit,
        context_budget=ELIDE,
    )
    await runtime.start(
        "work", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
    )
    outputs = outputs_of(creates_of(requests)[-1])
    assert (len(outputs[tight]), len(_elision_stub(name, tight, outputs[tight]))) == (502, 528)
    assert json.loads(outputs[tight]) == {"text": "\\" * 245}  # kept whole
    original = json.dumps(big_result(2_000), ensure_ascii=False)
    assert json.loads(outputs["c2"])["elided"] is True
    assert [e.payload for e in events if e.kind == "context_elided"] == [
        {
            "count": 1,
            "chars_removed": len(original) - len(outputs["c2"]),
            "first_index": 4,
            "seq": 3,
        }
    ]
    await client.close()


class LastSavedStore(SQLiteRuntimeStore):
    """Remembers the last committed checkpoint, after refusing the first saves of a block."""

    def __init__(self, path, refusals=0):
        super().__init__(path)
        self.refusals, self.last = refusals, None

    async def save(self, checkpoint):
        if self.refusals and checkpoint.native_state.get("elision", {}).get("last_block_seq"):
            self.refusals -= 1
            raise RuntimeError("disk full")
        await super().save(checkpoint)
        self.last = checkpoint


def saved_block(store):
    """What the last committed save holds of a block: status, last_block_seq and stub count."""
    state = store.last.native_state
    stubs = [text for text in outputs_of(state).values() if text.startswith('{"elided"')]
    return store.last.session.status, state["elision"]["last_block_seq"], len(stubs)


@pytest.mark.parametrize(
    ("refusals", "announced"),
    [
        (0, [(3, ("running", 3, 2))]),  # after the generation marker save (A)
        (1, [(3, ("uncertain", 3, 2))]),  # A was refused: after the failure save
        (2, []),  # the failure save was refused too: never
    ],
)
async def test_context_elided_follows_the_save_that_holds_its_stubs(tmp_path, refusals, announced):
    requests, events, seen = [], [], []
    store = LastSavedStore(tmp_path / "sessions.db", refusals)

    async def emit(event):
        events.append(event.kind)
        if event.kind == "context_elided":
            seen.append((event.payload["seq"], saved_block(store)))

    client = sdk_client(
        [
            *[response([call_item(f"c{i}")], f"r{i}") for i in (1, 2, 3)],
            response([text_item("done")], "rt"),
        ],
        requests,
    )
    runtime = ResponsesRuntime(
        store=store,
        client=client,
        dispatcher=observe_dispatcher(big_result(2_000)),
        event_sink=emit,
        context_budget=ELIDE,
    )
    if refusals:
        with pytest.raises((ExecutionError, RuntimeError)):
            await runtime.start(
                "work", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
            )
    else:
        await runtime.start(
            "work", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
        )
        started = [n for n, kind in enumerate(events) if kind == "generation_started"]
        assert events[started[3] - 1] == "context_elided"  # announced before its request
    assert seen == announced
    await client.close()


@pytest.mark.parametrize("ending", ["context_pressure", "target_verified"])
async def test_a_block_whose_run_ends_before_its_request_is_announced_after_saving(
    tmp_path, ending
):
    # The first run ends at seq 3, so the second run opens with a block, then stops before
    # sending: a context-pressure handoff after the count, or a target verified during send.
    requests, seen, guard_calls = [], [], []
    store = LastSavedStore(tmp_path / "sessions.db")

    async def emit(event):
        if event.kind == "context_elided":
            seen.append((event.payload["seq"], saved_block(store)))

    async def boundary(checkpoint):
        return (
            {"reason": "context_pressure"}
            if "context_pressure" in checkpoint.native_state
            else None
        )

    async def guard():
        guard_calls.append(True)
        return ending == "target_verified" and len(guard_calls) == 8  # the second run's send

    client = sdk_client(
        [
            response([call_item("c1")], "r1"),
            response([call_item("c2")], "r2"),
            response([text_item("done")], "rt"),
        ],
        requests,
        count=[10, 50_000 if ending == "context_pressure" else 10],
    )
    runtime = ResponsesRuntime(
        store=store,
        client=client,
        dispatcher=observe_dispatcher(big_result(2_000)),
        event_sink=emit,
        boundary_hook=boundary,
        pre_generation_guard=guard,
        context_budget=ELIDE,
    )
    limits = RuntimeLimits(
        max_context_tokens=20_000, max_output_tokens=1_000, max_total_tokens=None
    )
    first = await runtime.start("work", ModelConfig(model="exact-model"), limits)
    assert seen == [] and len(creates_of(requests)) == 3
    result = await runtime.continue_session(first.session.id, "next")
    assert len(creates_of(requests)) == 3  # the block's request was never sent
    if ending == "context_pressure":
        assert result.continuation["reason"] == "context_pressure"
        assert seen == [(3, ("running", 3, 2))]
    else:
        assert result.completion_reason == "target_verified"
        assert seen == [(3, ("completed", 3, 2))]
    await client.close()


async def test_a_refused_block_request_keeps_its_stubs_and_resumes_without_a_second_block(
    tmp_path,
):
    requests, events = [], []
    scripted = [
        *[response([call_item(f"c{i}")], f"r{i}") for i in (1, 2, 3)],
        None,  # the block's request is refused before generation
        response([text_item("done")], "rt"),
    ]

    def handle(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        if (scripted_response := scripted.pop(0)) is None:
            refusal = {"message": "refused", "type": "invalid_request_error", "param": None}
            return httpx.Response(400, json={"error": {**refusal, "code": None}})
        return httpx.Response(200, json=scripted_response)

    async def emit(event):
        events.append(event)

    client = AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    runtime = ResponsesRuntime(
        store=store,
        client=client,
        dispatcher=observe_dispatcher(big_result(2_000)),
        event_sink=emit,
        context_budget=ELIDE,
    )
    with pytest.raises(ExecutionError) as error:
        await runtime.start(
            "work", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
        )
    assert error.value.code == "MODEL_REQUEST_INVALID"
    failed = await runtime.checkpoint(events[0].session_id)
    saved = failed.native_state
    assert (failed.session.status, saved["elision"]) == ("failed", {"seq": 3, "last_block_seq": 3})
    assert saved["input"] == creates_of(requests)[-1]["input"]  # the refused request's stubs
    assert [k for k, text in outputs_of(saved).items() if text.startswith('{"elided"')] == [
        "c1",
        "c2",
    ]
    resumed = ResponsesRuntime(
        store=store,
        client=client,
        dispatcher=observe_dispatcher(big_result(2_000)),
        event_sink=emit,
    )
    await resumed.resume(failed)
    assert (await resumed.continue_session(failed.session.id, "next")).output_text == "done"
    assert creates_of(requests)[-1]["input"][:-1] == saved["input"]
    assert [e.payload["seq"] for e in events if e.kind == "context_elided"] == [3]  # just one
    assert [p.rsplit("/", 1)[-1] for p, _ in requests[-2:]] == ["input_tokens", "responses"]
    assert [e.payload for e in events if e.kind == "generation_started"][-1][
        "input_tokens_counted"
    ] is True
    await client.close()


async def test_a_native_handoff_carries_the_lineage_wide_elision_counter(tmp_path):
    requests, events, store = [], [], SQLiteRuntimeStore(tmp_path / "sessions.db")
    model, limits = ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)

    async def emit(event):
        events.append(event)

    async def boundary(checkpoint):
        return {"reason": "test_handoff"}

    first = sdk_client([response([call_item("c1")], "r1")], requests)
    source = ResponsesRuntime(
        store=store,
        client=first,
        dispatcher=observe_dispatcher(big_result(2_000)),
        boundary_hook=boundary,
        context_budget=ELIDE,
    )
    handed = await source.start("work", model, limits)
    second = sdk_client(
        [
            response([call_item("c2")], "r2"),
            response([call_item("c3")], "r3"),
            response([text_item("done")], "rt"),
        ],
        requests,
    )
    successor = ResponsesRuntime(
        store=store,
        client=second,
        dispatcher=observe_dispatcher(big_result(2_000)),
        event_sink=emit,
    )
    result = await successor.start_from_handoff(
        await source.checkpoint(handed.session.id), "continue", model, limits
    )
    # The lineage's third response is the successor's second, so its third request elides the
    # source's c1 and its own c2.
    assert [e.payload["count"] for e in events if e.kind == "context_elided"] == [2]
    outputs = outputs_of(creates_of(requests)[-1])
    assert [call_id for call_id, text in outputs.items() if text.startswith('{"elided"')] == [
        "c1",
        "c2",
    ]
    state = (await successor.checkpoint(result.session.id)).native_state
    assert state["elision"] == {"seq": 4, "last_block_seq": 3}
    assert (await source.checkpoint(handed.session.id)).native_state["elision"] == {
        "seq": 1,
        "last_block_seq": 0,
    }
    await first.close()
    await second.close()


def request_elements(payload):
    """P1's positional elements of a sent request, as canonical UTF-8 bytes."""
    elements = (payload.get("instructions"), payload["tools"], *payload["input"])
    return [canonical_json(element).encode("utf-8") for element in elements]


async def test_the_input_bound_stays_sound_through_elision_blocks(tmp_path):
    # The provider bills one token per canonical byte of every element: the most P1 admits.
    requests, events = [], []
    scripted = [*[[call_item(f"c{i}")] for i in range(1, 8)], [text_item("done")]]

    def handle(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        tokens = sum(len(element) for element in request_elements(payload))
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(
                200, json={"object": "response.input_tokens", "input_tokens": tokens}
            )
        items = scripted.pop(0)
        return httpx.Response(200, json=response(items, f"r{len(requests)}", input_tokens=tokens))

    async def emit(event):
        events.append(event)

    client = AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "sessions.db"),
        client=client,
        dispatcher=observe_dispatcher(big_result(2_000)),
        event_sink=emit,
        context_budget=ELIDE,
    )
    result = await runtime.start(
        "work",
        ModelConfig(model="exact-model"),
        RuntimeLimits(max_turns=10, max_total_tokens=None),
    )
    assert result.output_text == "done"  # no request billed past its reservation
    assert [e.payload["count"] for e in events if e.kind == "context_elided"] == [2, 3]
    creates = [request_elements(p) for p in creates_of(requests)]
    started = [e.payload for e in events if e.kind == "generation_started"]
    assert [s["input_tokens_counted"] for s in started] == [True] + [False] * 7
    rewritten = []
    for n in range(1, len(creates)):
        before, after = creates[n - 1], creates[n]
        billed_before, billed = sum(map(len, before)), sum(map(len, after))
        changed = [e for i, e in enumerate(after) if i >= len(before) or before[i] != e]
        raw = billed_before + sum(map(len, changed))  # P1, without the margin
        assert started[n]["input_tokens_reserved"] == raw + max(2_048, -(-raw * 2 // 100))
        assert billed <= raw
        # Only a block rewrites earlier elements, and the bytes it removes earn no credit.
        replaced = [i for i in range(len(before)) if before[i] != after[i]]
        assert raw - billed == sum(len(before[i]) for i in replaced)
        rewritten.append(len(replaced))
    assert rewritten == [0, 0, 2, 0, 0, 3, 0]
    await client.close()


# The creates of a 7-call run without a budget, as BASE (c1f16af) sent them.
UNBUDGETED_REQUESTS_SHA256 = "765670738ca10f826d661a232eac444b8a15f4f0c82017342baa63612f52dde2"


async def test_without_a_budget_long_runs_send_frozen_requests_and_state(tmp_path):
    requests = []
    client = sdk_client(
        [
            *[response([call_item(f"c{i}")], f"r{i}") for i in range(1, 8)],
            response([text_item("done")], "rt"),
        ],
        requests,
    )
    runtime = ResponsesRuntime(
        store=SQLiteRuntimeStore(tmp_path / "sessions.db"),
        client=client,
        dispatcher=observe_dispatcher(big_result(2_000)),
    )
    result = await runtime.start(
        "work", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
    )
    creates = creates_of(requests)
    assert len(creates) == 8
    assert (
        hashlib.sha256(canonical_json(creates).encode("utf-8")).hexdigest()
        == UNBUDGETED_REQUESTS_SHA256
    )
    state = (await runtime.checkpoint(result.session.id)).native_state
    assert "elision" not in state
    assert all(set(entry) == {"identity", "result"} for entry in state["tool_results"].values())
    await client.close()
