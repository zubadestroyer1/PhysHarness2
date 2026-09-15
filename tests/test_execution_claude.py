"""Actual Claude SDK control protocol over scripted test-only I/O; no provider calls."""

import asyncio
import json

import pytest

from physharness.execution.storage import SQLiteRuntimeStore
from physharness.execution.types import ExecutionError, ModelConfig, RuntimeLimits

sdk = pytest.importorskip("claude_agent_sdk", reason="optional Claude SDK contract tests")
Transport = pytest.importorskip("claude_agent_sdk._internal.transport").Transport

MODEL = "claude-sonnet-4-5-20250929"


def api():
    import importlib.util

    assert importlib.util.find_spec("physharness.execution.claude"), "Claude adapter is absent"
    return importlib.import_module("physharness.execution.claude")


class ScriptedTransport(Transport):
    def __init__(
        self,
        options,
        *,
        usage=None,
        model=None,
        wrong_session=False,
        hang=False,
        subtype="success",
        tool_use=None,
    ):
        self.options = options
        self.queue = asyncio.Queue()
        self.ready = False
        self.writes = []
        self.usage = (
            usage
            if usage is not None
            else {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 2,
                "cache_read_input_tokens": 3,
            }
        )
        self.model = model or options.model
        self.sid = "wrong-session" if wrong_session else options.resume or options.session_id
        self.hang = hang
        self.subtype = subtype
        self.tool_use = tool_use

    async def connect(self):
        self.ready = True

    async def write(self, data):
        message = json.loads(data)
        self.writes.append(message)
        if message["type"] == "control_request":
            await self.queue.put(
                {
                    "type": "control_response",
                    "response": {
                        "subtype": "success",
                        "request_id": message["request_id"],
                        "response": {},
                    },
                }
            )
        if message["type"] == "user":
            await self.queue.put(
                {
                    "type": "system",
                    "subtype": "init",
                    "session_id": self.sid,
                    "model": self.model,
                    "tools": list(self.options.tools),
                }
            )
            if self.hang:
                return
            content = [{"type": "text", "text": "synthetic response"}]
            if self.tool_use:
                content.append(
                    {"type": "tool_use", "id": "tool-1", "name": self.tool_use, "input": {}}
                )
            await self.queue.put(
                {
                    "type": "assistant",
                    "message": {"role": "assistant", "model": self.model, "content": content},
                }
            )
            await self.queue.put(
                {
                    "type": "result",
                    "subtype": self.subtype,
                    "duration_ms": 1,
                    "duration_api_ms": 1,
                    "is_error": self.subtype != "success",
                    "num_turns": 1,
                    "session_id": self.sid,
                    "total_cost_usd": 0.01,
                    "usage": self.usage,
                    "result": "synthetic response",
                    "terminal_reason": "completed",
                }
            )

    async def read_messages(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self):
        self.ready = False
        await self.queue.put(None)

    def is_ready(self):
        return self.ready

    async def end_input(self):
        pass


@pytest.fixture
def store(tmp_path):
    value = SQLiteRuntimeStore(tmp_path / "sessions.sqlite")
    yield value
    value.close()


def runtime(store, tmp_path, monkeypatch, **transport_options):
    instance = api().ClaudeRuntime(
        store=store,
        cwd=tmp_path,
        execution_boundary="trusted_development",
        allow_inherited_environment=True,
        allow_unbounded_provider_tokens=True,
    )
    transports = []

    def make_client(options):
        wire = ScriptedTransport(options, **transport_options)
        transports.append(wire)
        return sdk.ClaudeSDKClient(options=options, transport=wire)

    monkeypatch.setattr(instance, "_make_client", make_client)
    return instance, transports


@pytest.mark.asyncio
async def test_default_runtime_refuses_host_execution(store, tmp_path):
    instance = api().ClaudeRuntime(store=store, cwd=tmp_path)
    assert not instance.capabilities.available
    with pytest.raises(ExecutionError, match="explicit"):
        await instance.start("hello", ModelConfig(model=MODEL), RuntimeLimits())


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["allow_inherited_environment", "allow_unbounded_provider_tokens"])
async def test_unsafe_or_unenforceable_contracts_require_opt_in(store, tmp_path, flag):
    options = dict(
        execution_boundary="trusted_development",
        allow_inherited_environment=True,
        allow_unbounded_provider_tokens=True,
    )
    options[flag] = False
    instance = api().ClaudeRuntime(store=store, cwd=tmp_path, **options)
    with pytest.raises(ExecutionError):
        await instance.start("hello", ModelConfig(model=MODEL), RuntimeLimits())


@pytest.mark.asyncio
async def test_actual_sdk_options_disable_opaque_tools_and_settings(store, tmp_path, monkeypatch):
    instance, wires = runtime(store, tmp_path, monkeypatch)
    result = await instance.start("hello", ModelConfig(model=MODEL), RuntimeLimits())
    opts = wires[0].options
    assert opts.model == MODEL and opts.fallback_model is None
    assert opts.tools == [] and {"Agent", "Task", "Bash"} <= set(opts.disallowed_tools)
    assert opts.strict_mcp_config and opts.mcp_servers == {} and opts.setting_sources == []
    assert opts.skills == [] and opts.plugins == [] and opts.permission_mode == "dontAsk"
    assert (
        not instance.capabilities.hard_token_limit and not instance.capabilities.controlled_spawning
    )
    assert not instance.capabilities.portable_checkpoint
    assert result.output_text == "synthetic response"
    assert result.session.input_tokens == 15 and result.session.output_tokens == 5
    assert not wires[0].ready


@pytest.mark.asyncio
async def test_native_continuation_keeps_id_and_adds_per_query_usage(store, tmp_path, monkeypatch):
    instance, wires = runtime(store, tmp_path, monkeypatch)
    first = await instance.start("hello", ModelConfig(model=MODEL), RuntimeLimits())
    second = await instance.continue_session(first.session.id, "continue")
    assert wires[1].options.resume == first.session.native_session_id
    assert wires[1].options.session_id is None
    assert second.session.input_tokens == 30 and second.session.output_tokens == 10
    checkpoint = await instance.export(second.session.id)
    assert checkpoint.native_state["sdk_version"] == sdk.__version__
    assert checkpoint.native_state["pending_operation"] is None
    assert checkpoint.native_state["estimated_cost_usd"] == pytest.approx(0.02)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "problem,code",
    [
        ({"model": "other-model"}, "MODEL_MISMATCH"),
        ({"wrong_session": True}, "CHECKPOINT_MISMATCH"),
        ({"usage": {"input_tokens": 1}}, "USAGE_UNAVAILABLE"),
        ({"tool_use": "Agent"}, "UNCONTROLLED_TOOL"),
        ({"subtype": "error_max_turns"}, "PROVIDER_INCOMPLETE"),
    ],
)
async def test_invalid_native_outcomes_fail_loudly(store, tmp_path, monkeypatch, problem, code):
    instance, _ = runtime(store, tmp_path, monkeypatch, **problem)
    with pytest.raises(ExecutionError) as exc:
        await instance.start("hello", ModelConfig(model=MODEL), RuntimeLimits())
    assert exc.value.code == code


@pytest.mark.asyncio
async def test_timeout_records_uncertainty_and_attempts_interrupt(store, tmp_path, monkeypatch):
    instance, wires = runtime(store, tmp_path, monkeypatch, hang=True)
    with pytest.raises(ExecutionError) as exc:
        await instance.start("hello", ModelConfig(model=MODEL), RuntimeLimits(timeout_seconds=0.03))
    assert exc.value.code == "TIMEOUT"
    sid = wires[0].options.session_id
    checkpoint = await store.load(sid)
    assert checkpoint.session.status == "uncertain"
    assert checkpoint.native_state["pending_operation"]
    assert any(m.get("request", {}).get("subtype") == "interrupt" for m in wires[0].writes)


@pytest.mark.asyncio
async def test_resume_refuses_other_worker_and_stale_checkpoint(store, tmp_path, monkeypatch):
    instance, _ = runtime(store, tmp_path, monkeypatch)
    first = await instance.start("hello", ModelConfig(model=MODEL), RuntimeLimits())
    old = await instance.checkpoint(first.session.id)
    await instance.continue_session(first.session.id, "next")
    with pytest.raises(ExecutionError, match="rewind"):
        await instance.resume(old)
    another = tmp_path / "other"
    another.mkdir()
    other = api().ClaudeRuntime(store=store, cwd=another)
    with pytest.raises(ExecutionError, match="worker"):
        await other.resume(old)


@pytest.mark.asyncio
async def test_read_tool_hook_blocks_path_escape(store, tmp_path):
    instance = api().ClaudeRuntime(store=store, cwd=tmp_path, native_tools=["Read"])
    denied = await instance._tool_gate(
        {"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}}, None, {}
    )
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    with pytest.raises(ExecutionError):
        api().ClaudeRuntime(store=store, cwd=tmp_path, native_tools=["Bash"])


@pytest.mark.asyncio
async def test_observed_budget_overrun_persists_usage_and_blocks_continue(
    store, tmp_path, monkeypatch
):
    instance, wires = runtime(store, tmp_path, monkeypatch)
    with pytest.raises(ExecutionError) as exc:
        await instance.start("hello", ModelConfig(model=MODEL), RuntimeLimits(max_total_tokens=10))
    assert exc.value.code == "BUDGET_OVERRUN"
    checkpoint = await store.load(wires[0].options.session_id)
    assert checkpoint.session.input_tokens == 15 and checkpoint.session.output_tokens == 5
    with pytest.raises(ExecutionError):
        await instance.continue_session(checkpoint.session.id, "continue")
    assert len(wires) == 1


@pytest.mark.asyncio
async def test_result_cleanup_failure_is_not_reported_as_completed(store, tmp_path, monkeypatch):
    instance, wires = runtime(store, tmp_path, monkeypatch)
    original = instance._make_client

    def failed_cleanup(options):
        client = original(options)
        disconnect = client.disconnect

        async def fail():
            await disconnect()
            raise RuntimeError("scripted cleanup uncertainty")

        client.disconnect = fail
        return client

    monkeypatch.setattr(instance, "_make_client", failed_cleanup)
    with pytest.raises(ExecutionError) as exc:
        await instance.start("hello", ModelConfig(model=MODEL), RuntimeLimits())
    assert exc.value.code == "CLEANUP_UNCERTAIN"
    checkpoint = await store.load(wires[0].options.session_id)
    assert checkpoint.session.status == "uncertain"
    assert checkpoint.native_state["cleanup_error"] == "RuntimeError"


@pytest.mark.asyncio
async def test_interrupt_is_acknowledgment_not_completed_operation(store, tmp_path, monkeypatch):
    instance, wires = runtime(store, tmp_path, monkeypatch, hang=True)
    task = asyncio.create_task(instance.start("hello", ModelConfig(model=MODEL), RuntimeLimits()))
    for _ in range(100):
        if wires and any(row.get("type") == "user" for row in wires[0].writes):
            break
        await asyncio.sleep(0.001)
    assert wires
    sid = wires[0].options.session_id
    assert await instance.interrupt(sid)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await store.load(sid)).session.status == "uncertain"
    assert not await instance.interrupt(sid)


@pytest.mark.asyncio
async def test_tool_hook_denies_symlink_and_allows_confined_read(store, tmp_path):
    instance = api().ClaudeRuntime(store=store, cwd=tmp_path, native_tools=["Read", "Glob"])
    (tmp_path / "escape").symlink_to("/etc")
    denied = await instance._tool_gate(
        {"tool_name": "Read", "tool_input": {"file_path": "escape/passwd"}}, None, {}
    )
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert (
        await instance._tool_gate(
            {"tool_name": "Read", "tool_input": {"file_path": "local.txt"}}, None, {}
        )
        == {}
    )
    glob = await instance._tool_gate(
        {"tool_name": "Glob", "tool_input": {"pattern": "../*"}}, None, {}
    )
    assert glob["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["sonnet", "--dangerous-option"])
async def test_model_aliases_and_cli_flag_tokens_are_rejected(store, tmp_path, monkeypatch, model):
    instance, wires = runtime(store, tmp_path, monkeypatch)
    with pytest.raises(ExecutionError) as exc:
        await instance.start("hello", ModelConfig(model=model), RuntimeLimits())
    assert exc.value.code == "INVALID_CONFIG"
    assert wires == []


@pytest.mark.asyncio
async def test_version_drift_and_parameter_policy_override_block(store, tmp_path, monkeypatch):
    instance, wires = runtime(store, tmp_path, monkeypatch)
    with pytest.raises(ExecutionError) as exc:
        await instance.start(
            "hello", ModelConfig(model=MODEL, parameters={"tools": ["Bash"]}), RuntimeLimits()
        )
    assert exc.value.code == "INVALID_CONFIG"
    monkeypatch.setattr(sdk, "__version__", "0.0.0")
    with pytest.raises(ExecutionError) as exc:
        await instance.start("hello", ModelConfig(model=MODEL), RuntimeLimits())
    assert exc.value.code == "SDK_UNQUALIFIED"
    assert wires == []


@pytest.mark.asyncio
async def test_real_sdk_command_builder_keeps_restriction_flags(store, tmp_path, monkeypatch):
    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

    instance, wires = runtime(store, tmp_path, monkeypatch)
    await instance.start("hello", ModelConfig(model=MODEL), RuntimeLimits())
    transport = SubprocessCLITransport(prompt="hello", options=wires[0].options)
    transport._cli_path = "/test-only/claude"
    argv = transport._build_command()
    assert argv[argv.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert "--setting-sources=" in argv
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert "Agent" in argv[argv.index("--disallowedTools") + 1]
    assert "--fallback-model" not in argv
