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
