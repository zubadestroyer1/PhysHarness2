"""Official OpenHands 1.47.0 client/parser with controlled HTTP and WS transport."""

import json
import time
from dataclasses import replace

import httpx
import pytest

from physharness.execution.openhands import OpenHandsRuntime, RemoteVMQualification
from physharness.execution.storage import SQLiteRuntimeStore
from physharness.execution.types import ExecutionError, ModelConfig, RuntimeLimits, digest

MODEL = "openai/exact-test-model"
HOST = "https://qualified-vm.example"
SERVER_INFO = {"test_only_protocol_fixture": True, "sdk_version": "1.47.0"}


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    monkeypatch.setenv("OPENHANDS_SUPPRESS_BANNER", "1")
    monkeypatch.setenv("LOG_AUTO_CONFIG", "false")
    pytest.importorskip("openhands.sdk")
    from openhands.sdk.conversation.impl import remote_conversation
    from openhands.sdk.event import MessageEvent
    from openhands.sdk.llm import Message, TextContent

    class WebSocketFixture:
        def __init__(self, **kwargs):
            self._thread = None

        def start(self):
            pass

        def wait_until_ready(self, timeout):
            return True

        def stop(self):
            pass

    monkeypatch.setattr(remote_conversation, "WebSocketCallbackClient", WebSocketFixture)

    class Server:
        def __init__(self):
            self.requests, self.conversations, self.events = [], {}, {}
            self.missing_stats = False
            self.fail_events = False
            self.stay_running = False
            self.altered_model = False
            self.disappear_on_attach = False
            self.attach_reads = 0
            self.finish_tool = False
            self.paused_on_finish = False
            self.calls = 0

        def handle(self, request):
            self.requests.append((request.method, request.url.path))
            path = request.url.path
            if path == "/server_info":
                return httpx.Response(200, json=SERVER_INFO)
            if path == "/api/conversations" and request.method == "POST":
                data = json.loads(request.content)
                identifier = data["conversation_id"]
                self.conversations[identifier] = {
                    **data,
                    "id": identifier,
                    "execution_status": "idle",
                }
                self.events[identifier] = []
                if self.altered_model:
                    self.conversations[identifier]["agent"]["llm"]["model"] = "openai/wrong-model"
                return httpx.Response(201, json=self.conversations[identifier])
            parts = path.split("/")
            identifier = parts[3] if len(parts) > 3 else ""
            if identifier not in self.conversations:
                return httpx.Response(404, json={"error": "not found"})
            state = self.conversations[identifier]
            if len(parts) == 4 and request.method == "GET":
                if self.disappear_on_attach:
                    self.attach_reads += 1
                    if self.attach_reads == 2:
                        del self.conversations[identifier]
                        return httpx.Response(404, json={})
                return httpx.Response(200, json=state)
            if path.endswith("/events/search"):
                return httpx.Response(
                    503 if self.fail_events and self.calls else 200,
                    json={"items": self.events[identifier], "next_page_id": None},
                )
            if path.endswith("/events") and request.method == "POST":
                return httpx.Response(200, json={})
            if path.endswith("/run"):
                self.calls += 1
                event = MessageEvent(
                    source="agent",
                    llm_response_id=f"response-{self.calls}",
                    llm_message=Message(
                        role="assistant", content=[TextContent(text=f"result {self.calls}")]
                    ),
                )
                if self.finish_tool:
                    from openhands.sdk.event import ActionEvent
                    from openhands.sdk.llm import MessageToolCall
                    from openhands.sdk.tool.builtins.finish import FinishAction

                    event = ActionEvent(
                        thought=[],
                        action=FinishAction(message="Finished via actual tool"),
                        tool_name="finish",
                        tool_call_id="tool-call",
                        llm_response_id="finish-response",
                        tool_call=MessageToolCall(
                            id="tool-call",
                            name="finish",
                            origin="completion",
                            arguments='{"message":"Finished via actual tool"}',
                        ),
                    )
                self.events[identifier].append(event.model_dump(mode="json"))
                state["execution_status"] = "running" if self.stay_running else "finished"
                if not self.missing_stats:
                    state["stats"] = {
                        "usage_to_metrics": {
                            "default": {
                                "model_name": MODEL,
                                "accumulated_cost": 0.01 * self.calls,
                                "accumulated_token_usage": {
                                    "prompt_tokens": 10 * self.calls,
                                    "completion_tokens": 5 * self.calls,
                                    "model": MODEL,
                                    "response_id": f"response-{self.calls}",
                                },
                            }
                        }
                    }
                if self.paused_on_finish:
                    state["execution_status"] = "paused"
                return httpx.Response(200, json={})
            if path.endswith("/interrupt") or path.endswith("/pause"):
                state["execution_status"] = "paused"
                return httpx.Response(200, json={})
            raise AssertionError((request.method, path))

    return Server()


@pytest.fixture
def instance(tmp_path, remote):
    qualification = RemoteVMQualification(
        endpoint=HOST,
        execution_id="test-only-vm",
        image_digest="sha256:" + "a" * 64,
        qualification_id="controlled-fixture-not-live-evidence",
        server_info_sha256=digest(SERVER_INFO),
        expires_at=time.time() + 3600,
    )
    return OpenHandsRuntime(
        store=SQLiteRuntimeStore(tmp_path / "openhands.db"),
        qualification=qualification,
        qualification_check=lambda q: q == qualification,
        server_api_key="test-only-server-key",
        llm_api_key="test-only-provider-key",
        allow_unbounded_provider_tokens=True,
        http_transport=httpx.MockTransport(remote.handle),
    )


def test_no_boundary_means_unavailable_without_sdk_or_host_fallback(tmp_path):
    runtime = OpenHandsRuntime(store=SQLiteRuntimeStore(tmp_path / "absent.db"))
    assert runtime.capabilities.available is False
    assert runtime.capabilities.hard_token_limit is False
    assert runtime.capabilities.controlled_spawning is False
    assert runtime.capabilities.portable_checkpoint is False


@pytest.mark.asyncio
async def test_actual_sdk_round_trip_preserves_model_usage_provider_id_and_resume(instance, remote):
    events = []

    async def sink(event):
        events.append(event)

    instance.event_sink = sink
    result = await instance.start("first question", ModelConfig(model=MODEL), RuntimeLimits())
    assert result.output_text == "result 1"
    assert result.session.model.model == MODEL
    assert (result.session.input_tokens, result.session.output_tokens) == (10, 5)
    checkpoint = await instance.checkpoint(result.session.id)
    assert checkpoint.session.native_session_id in remote.conversations
    assert "test-only-provider-key" not in checkpoint.model_dump_json()
    assert "test-only-server-key" not in checkpoint.model_dump_json()
    assert result.native_items[-1]["llm_response_id"] == "response-1"
    await instance.resume(checkpoint)
    continued = await instance.continue_session(result.session.id, "follow up")
    assert continued.output_text == "result 2"
    assert continued.session.native_session_id == result.session.native_session_id
    assert (continued.session.input_tokens, continued.session.output_tokens) == (20, 10)
    assert [event.payload["input_tokens"] for event in events if event.kind == "usage"] == [10, 10]
    assert remote.requests.count(("POST", "/api/conversations")) == 1
    config = next(iter(remote.conversations.values()))
    assert config["agent"]["tools"] == []
    assert config["agent"]["mcp_config"] == {}
    assert config["client_tools"] == [] and config["agent_definitions"] == []
    assert config["agent"]["include_default_tools"] == ["FinishTool"]
    assert config["agent"]["llm"]["model"] == MODEL
    assert config["agent"]["llm"].get("fallback_strategy") is None


@pytest.mark.asyncio
async def test_missing_native_conversation_does_not_trigger_sdk_recreation(instance, remote):
    result = await instance.start("question", ModelConfig(model=MODEL), RuntimeLimits())
    checkpoint = await instance.export(result.session.id)
    remote.conversations.clear()
    before = remote.requests.count(("POST", "/api/conversations"))
    with pytest.raises(ExecutionError) as exc:
        await instance.resume(checkpoint)
    assert exc.value.code == "NATIVE_SESSION_MISSING"
    assert remote.requests.count(("POST", "/api/conversations")) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing_stats", "fail_events", "altered_model"])
async def test_missing_usage_partial_history_or_changed_model_never_returns_success(
    instance, remote, fault
):
    setattr(remote, fault, True)
    with pytest.raises(ExecutionError):
        await instance.start("question", ModelConfig(model=MODEL), RuntimeLimits())
    states = instance.store.db.execute("SELECT data FROM runtime_sessions").fetchall()
    assert json.loads(states[-1][0])["session"]["status"] == "uncertain"


@pytest.mark.asyncio
async def test_timeout_is_durable_uncertainty_and_cannot_be_blindly_resumed(instance, remote):
    remote.stay_running = True
    with pytest.raises(ExecutionError) as exc:
        await instance.start(
            "question", ModelConfig(model=MODEL), RuntimeLimits(timeout_seconds=0.1)
        )
    assert exc.value.code == "REMOTE_EXECUTION_UNCERTAIN"
    saved = json.loads(instance.store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0])
    with pytest.raises(ExecutionError) as exc:
        await instance.continue_session(saved["session"]["id"], "repeat")
    assert exc.value.code == "RECOVERY_RECONCILIATION_REQUIRED"
    assert remote.calls == 1


@pytest.mark.asyncio
async def test_boundary_revocation_blocks_calls_and_host_code_tools_are_never_installed(
    instance, remote
):
    instance.qualification_check = lambda q: False
    with pytest.raises(ExecutionError) as exc:
        await instance.start("question", ModelConfig(model=MODEL), RuntimeLimits())
    assert exc.value.code == "VM_UNQUALIFIED"
    assert remote.requests == []


@pytest.mark.asyncio
async def test_server_pin_mismatch_refuses_before_conversation_creation(instance, remote):
    instance.qualification = replace(instance.qualification, server_info_sha256="b" * 64)
    instance.qualification_check = lambda q: True  # test-only attestation fixture
    with pytest.raises(ExecutionError) as exc:
        await instance.start("question", ModelConfig(model=MODEL), RuntimeLimits())
    assert exc.value.code == "REMOTE_IDENTITY_MISMATCH"
    assert ("POST", "/api/conversations") not in remote.requests


@pytest.mark.asyncio
async def test_opaque_token_budget_requires_explicit_optin(instance, remote):
    instance.allow_unbounded_provider_tokens = False
    with pytest.raises(ExecutionError) as exc:
        await instance.start("question", ModelConfig(model=MODEL), RuntimeLimits())
    assert exc.value.code == "CAPABILITY_UNAVAILABLE"
    assert remote.requests == []


@pytest.mark.asyncio
async def test_reattach_race_cannot_recreate_deleted_conversation(instance, remote):
    result = await instance.start("question", ModelConfig(model=MODEL), RuntimeLimits())
    checkpoint = await instance.checkpoint(result.session.id)
    remote.disappear_on_attach = True
    before = remote.requests.count(("POST", "/api/conversations"))
    with pytest.raises(ExecutionError) as exc:
        await instance.resume(checkpoint)
    assert exc.value.code == "NATIVE_SESSION_MISSING"
    assert remote.requests.count(("POST", "/api/conversations")) == before


@pytest.mark.asyncio
async def test_sdk_finish_action_yields_final_message(instance, remote):
    remote.finish_tool = True
    result = await instance.start("question", ModelConfig(model=MODEL), RuntimeLimits())
    assert result.output_text == "Finished via actual tool"
    assert result.native_items[0]["llm_response_id"] == "finish-response"


@pytest.mark.asyncio
async def test_cleanup_failure_never_produces_completed_checkpoint(instance, remote, monkeypatch):
    from openhands.sdk import RemoteConversation

    def fail_close(self):
        raise RuntimeError("controlled SDK cleanup fault")

    monkeypatch.setattr(RemoteConversation, "close", fail_close)
    with pytest.raises(ExecutionError):
        await instance.start("question", ModelConfig(model=MODEL), RuntimeLimits())
    state = json.loads(instance.store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0])
    assert state["session"]["status"] == "uncertain"
    assert state["native_state"]["pending"] is not None


@pytest.mark.asyncio
async def test_iteration_allowance_cannot_overrun_remaining_turns(instance, remote):
    result = await instance.start("question", ModelConfig(model=MODEL), RuntimeLimits(max_turns=1))
    with pytest.raises(ExecutionError) as exc:
        await instance.continue_session(result.session.id, "one more")
    assert exc.value.code == "BUDGET_EXCEEDED"
    assert remote.calls == 1


@pytest.mark.asyncio
async def test_native_checkpoint_can_import_into_new_journal_for_same_vm(
    instance, remote, tmp_path
):
    result = await instance.start("question", ModelConfig(model=MODEL), RuntimeLimits())
    checkpoint = await instance.export(result.session.id)
    instance.store = SQLiteRuntimeStore(tmp_path / "import.db")
    restored = await instance.resume(checkpoint)
    assert restored.native_session_id == result.session.native_session_id
    assert (await instance.store.load(restored.id)).state_digest == checkpoint.state_digest
    assert remote.requests.count(("POST", "/api/conversations")) == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://vm.example",
        "https://localhost",
        "https://127.0.0.1",
        "https://[::1]",
        "https://user:key@vm.example",
    ],
)
def test_local_or_credential_bearing_origins_are_not_vm_qualification(endpoint):
    qualification = RemoteVMQualification(
        endpoint=endpoint,
        execution_id="vm",
        image_digest="sha256:" + "a" * 64,
        qualification_id="fixture",
        server_info_sha256=digest(SERVER_INFO),
        expires_at=time.time() + 3600,
    )
    with pytest.raises(ExecutionError) as exc:
        qualification.validate()
    assert exc.value.code == "VM_UNQUALIFIED"


@pytest.mark.asyncio
async def test_unsuccessful_native_run_keeps_reported_usage(instance, remote):
    remote.paused_on_finish = True
    with pytest.raises(ExecutionError) as exc:
        await instance.start("question", ModelConfig(model=MODEL), RuntimeLimits())
    assert exc.value.code == "REMOTE_EXECUTION_FAILED"
    saved = json.loads(instance.store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0])
    assert saved["native_state"]["usage"]["input_tokens"] == 10
    assert saved["session"]["input_tokens"] == 10
    assert saved["session"]["status"] == "uncertain"


@pytest.mark.asyncio
async def test_native_terminal_configuration_does_not_invoke_host_workspace(
    instance, remote, monkeypatch
):
    from openhands.sdk.workspace import LocalWorkspace

    def forbidden(*args, **kwargs):
        raise AssertionError("host execution is forbidden")

    monkeypatch.setattr(LocalWorkspace, "execute_command", forbidden)
    monkeypatch.setattr(LocalWorkspace, "file_upload", forbidden)
    instance.native_tools = ["TerminalTool"]
    await instance.start("question", ModelConfig(model=MODEL), RuntimeLimits())
    config = next(iter(remote.conversations.values()))
    assert config["agent"]["tools"] == [{"name": "TerminalTool", "params": {}}]


@pytest.mark.parametrize("sdk_first", [True, False])
def test_sdk_and_temporal_sandbox_coexist_in_either_import_order(sdk_first, monkeypatch):
    """Fresh processes exercise the import hook without test-order or cache dependence."""
    import importlib.metadata
    import os
    import subprocess
    import sys
    import textwrap

    try:
        importlib.metadata.version("openhands-sdk")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("Official OpenHands SDK optional extra is absent")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    monkeypatch.setenv("OPENHANDS_SUPPRESS_BANNER", "1")
    monkeypatch.setenv("LOG_AUTO_CONFIG", "false")
    script = textwrap.dedent("""
        import asyncio
        import importlib
        import sys
        from temporalio import workflow
        from temporalio.worker.workflow_sandbox import (
            RestrictedWorkflowAccessError, SandboxRestrictions,
        )
        from temporalio.worker.workflow_sandbox._importer import Importer
        from temporalio.worker.workflow_sandbox._restrictions import RestrictionContext

        if SDK_FIRST:
            import openhands.sdk
        from physharness.orchestration.sandbox import workflow_runner
        from physharness.orchestration import workflows
        if not SDK_FIRST:
            import openhands.sdk
        hooks = tuple(sys.path_hooks)
        runner = workflow_runner()
        assert tuple(sys.path_hooks) == hooks  # Do not remove dependency type checking.
        assert runner.restrictions.passthrough_modules == (
            SandboxRestrictions.default.passthrough_modules | {"beartype"}
        )
        assert not runner.restrictions.passthrough_all_modules
        assert "physharness" not in runner.restrictions.passthrough_modules
        assert "openhands" not in runner.restrictions.passthrough_modules

        async def prepare():
            for cls in (
                workflows.ExperimentWorkflow, workflows.TaskWorkflow,
                workflows.VerificationWorkflow,
            ):
                runner.prepare_workflow(workflow._Definition.must_from_class(cls))
        asyncio.run(prepare())

        context = RestrictionContext()
        importer = Importer(runner.restrictions, context)
        with importer.applied():
            reloaded = importlib.import_module("physharness.orchestration.workflows")
            assert reloaded is not workflows
        context.is_runtime = True
        for code, blocked in (
            ("import datetime; datetime.datetime.now()", "datetime.datetime.now.__call__"),
            ("open('sandbox-must-not-create.txt', 'w')", "__builtins__.open"),
            ("import socket; socket.socket()", "socket.socket.__call__"),
        ):
            try:
                with importer.applied():
                    exec(code, {})
            except RestrictedWorkflowAccessError as exc:
                assert exc.qualified_name == blocked
            else:
                raise AssertionError("Sandbox restriction was disabled: " + code)
    """).replace("SDK_FIRST", repr(sdk_first))
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def test_sdk_logging_autoconfiguration_requires_explicit_opt_out(
    instance, remote, monkeypatch
):
    monkeypatch.delenv("LOG_AUTO_CONFIG")
    with pytest.raises(ExecutionError) as raised:
        await instance.start("must not dispatch", ModelConfig(model=MODEL), RuntimeLimits())
    assert raised.value.code == "SDK_ENVIRONMENT_UNQUALIFIED"
    assert remote.requests == []


def test_late_logging_opt_out_cannot_undo_prior_sdk_initialization(monkeypatch):
    import importlib.metadata
    import subprocess
    import sys
    import textwrap

    try:
        importlib.metadata.version("openhands-sdk")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("Official OpenHands SDK optional extra is absent")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    monkeypatch.setenv("OPENHANDS_SUPPRESS_BANNER", "1")
    script = textwrap.dedent("""
        import os
        import time
        os.environ["LOG_AUTO_CONFIG"] = "true"
        import openhands.sdk
        os.environ["LOG_AUTO_CONFIG"] = "false"
        from physharness.execution.openhands import OpenHandsRuntime, RemoteVMQualification
        from physharness.execution.types import ExecutionError
        runtime = OpenHandsRuntime(
            store=None,
            qualification=RemoteVMQualification(
                endpoint="https://qualified-vm.example", execution_id="fixture",
                image_digest="sha256:" + "a" * 64, qualification_id="fixture",
                server_info_sha256="b" * 64, expires_at=time.time() + 600,
            ),
            qualification_check=lambda q: True,
            server_api_key="fixture", llm_api_key="fixture",
            allow_unbounded_provider_tokens=True,
        )
        try:
            runtime._gate()
        except ExecutionError as exc:
            assert exc.code == "SDK_ENVIRONMENT_UNQUALIFIED"
            assert "already imported" in str(exc)
        else:
            raise AssertionError("SDK import-time logging state was ignored")
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
