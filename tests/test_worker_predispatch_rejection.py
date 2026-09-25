"""A bad local command request must remain a model-visible tool refusal."""

import base64
import json

import pytest
from test_core import setup_experiment
from test_execution_responses import client_for, message, response
from test_workspace_service import FakeVM, setup

from physharness.domain import BranchCreate, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import (
    ExecutionError,
    ModelConfig,
    ResponsesRuntime,
    RuntimeLimits,
    RuntimeResult,
    RuntimeSession,
    SQLiteRuntimeStore,
    ToolDispatcher,
)
from physharness.execution.local_docker import LocalDockerWorkspaceProvider
from physharness.execution.types import CommandRequest
from physharness.execution.workspace_archive import checked_path
from physharness.orchestration.research_worker import ResearchTaskExecutor
from physharness.orchestration.workspace_tools import WorkspacePolicy, WorkspaceTools
from physharness.orchestration.workspaces import WorkspaceBroker


async def test_pure_predispatch_path_rejection_allows_next_tool_and_task_completion(lab):
    service, actor, _ = lab
    experiment, problem = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start-predispatch")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Research", objective="Explore"), actor, "branch"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Use workbench"), actor, "task"
    )
    calls = []
    policy = WorkspacePolicy(
        template_id="qualified-template",
        environment_digest=problem["environment_digest"],
        qualification_report_sha256="a" * 64,
        timeout_seconds=60,
        cost_bound_usd="0.2",
        cost_source="synthetic test bound",
    )

    class CheckedVM(FakeVM):
        def validate_command(self, request):
            if request.cwd == "/work":
                raise ExecutionError("UNSAFE_PATH", "Workspace path is not canonical")

    def vm_factory(service, agent, task_id, holder, fence, worker_slot_id):
        def provider_factory(*, journal):
            return CheckedVM(journal, calls)

        broker = WorkspaceBroker(
            service,
            actor=agent,
            task_id=task_id,
            holder=holder,
            fence=fence,
            worker_slot_id=worker_slot_id,
            provider_factory=provider_factory,
            provider_spec={
                "provider": "e2b",
                "template_id": "qualified-template",
                "timeout_seconds": 60,
            },
        )
        return WorkspaceTools(broker, policy)

    class ScriptedRuntime:
        def __init__(self, store, dispatcher, event_sink):
            self.dispatcher = dispatcher

        async def start(self, prompt, model, limits):
            rejected = await self.dispatcher.dispatch(
                "run_command",
                {"argv": ["true"], "cwd": "/work", "timeout_seconds": 10},
                "bad-cwd",
            )
            assert rejected["error"]["code"] == "UNSAFE_PATH"
            workspaces = service.list_records("workspace", actor, experiment["id"])
            assert len(workspaces) == 1
            assert workspaces[0]["status"] == "ready"
            assert workspaces[0]["active_operation_id"] is None
            assert service.ledger(experiment["id"], actor)["uncertain_operations"] == 0
            assert len(service.list_records("workspace_operation", actor, experiment["id"])) == 1
            valid = await self.dispatcher.dispatch(
                "run_command",
                {"argv": ["true"], "cwd": ".", "timeout_seconds": 10},
                "valid-cwd",
            )
            assert valid["exit_code"] == 0
            return RuntimeResult(
                session=RuntimeSession(runtime="responses", model=model, limits=limits),
                output_text="Partial work; no proof receipt claimed.",
            )

    executor = ResearchTaskExecutor(
        service,
        prices={
            "explicit-test-model": {"input_usd_per_million": "1", "output_usd_per_million": "1"}
        },
        runtime_factory=ScriptedRuntime,
        workspace_factory=vm_factory,
    )
    result = await executor.execute(task["id"], actor.project_id)
    assert result["status"] == "completed"
    assert calls == ["create", "run", "close"]
    assert service.get_record("task", task["id"], actor)["status"] == "completed"


async def test_native_response_loop_persists_rejection_then_valid_result(lab, tmp_path):
    broker, service, experiment, calls, made, args = setup(lab)
    original = broker.provider_factory

    class CheckedVM(FakeVM):
        def validate_command(self, request):
            if request.cwd == "/work":
                raise ExecutionError("UNSAFE_PATH", "Workspace path is not canonical")

    def factory(**kwargs):
        base = original(**kwargs)
        return CheckedVM(base.journal, calls)

    broker.provider_factory = factory
    problem = service.get_record("problem", experiment["problem_id"], broker.actor)
    policy = WorkspacePolicy(
        template_id="qualified-template",
        environment_digest=problem["environment_digest"],
        qualification_report_sha256="a" * 64,
        timeout_seconds=60,
        cost_bound_usd="0.1",
        cost_source="synthetic test bound",
    )
    tools = WorkspaceTools(broker, policy)
    dispatcher = ToolDispatcher()

    async def wrapped(arguments, operation_id):
        try:
            return await tools.run(arguments, operation_id)
        except HarnessError as error:
            return error.envelope()

    dispatcher.register(
        "run_command",
        {
            "type": "object",
            "properties": {
                "argv": {"type": "array", "items": {"type": "string"}},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "integer"},
            },
            "required": ["argv", "cwd", "timeout_seconds"],
            "additionalProperties": False,
        },
        wrapped,
    )

    def call(label, cwd):
        return {
            "id": "fc-" + label,
            "type": "function_call",
            "call_id": label,
            "name": "run_command",
            "arguments": json.dumps({"argv": ["true"], "cwd": cwd, "timeout_seconds": 10}),
            "status": "completed",
        }

    requests = []
    client = client_for(
        [
            response([call("bad", "/work")], response_id="resp_bad"),
            response([call("good", ".")], response_id="resp_good"),
            response([message("Partial result")], response_id="resp_final"),
        ],
        requests,
    )
    store = SQLiteRuntimeStore(tmp_path / "runtime.db")
    runtime = ResponsesRuntime(store=store, client=client, dispatcher=dispatcher)
    result = await runtime.start("research", ModelConfig(model="exact-model"), RuntimeLimits())
    assert result.output_text == "Partial result"
    checkpoint = await runtime.checkpoint(result.session.id)
    state = checkpoint.native_state
    assert state["pending_operation"] is None
    assert (
        state["tool_results"][f"{result.session.id}:bad"]["result"]["error"]["code"]
        == "UNSAFE_PATH"
    )
    assert state["tool_results"][f"{result.session.id}:good"]["result"]["exit_code"] == 0
    generations = [payload for url, payload in requests if not url.endswith("/input_tokens")]
    assert len(generations) == 3
    assert "UNSAFE_PATH" in generations[1]["input"][-1]["output"]
    assert calls == ["create", "run"]
    await client.close()
    store.close()


@pytest.mark.parametrize("command", ["upload", "download", "read_range"])
async def test_invalid_file_path_is_rejected_before_workspace_operation(lab, command):
    broker, service, experiment, calls, made, args = setup(lab)
    original = broker.provider_factory

    class CheckedVM(FakeVM):
        async def download_file(self, path, *, expected_execution_id):
            self.calls.append("download")
            checked_path(path)
            return b"contents"

        async def read_range(self, path, *, offset, length, expected_execution_id):
            self.calls.append("read_range")
            checked_path(path)
            return {
                "sha256": "a" * 64,
                "size_bytes": 8,
                "data": base64.b64encode(b"contents"[offset : offset + length]).decode(),
            }

    def factory(**kwargs):
        base = original(**kwargs)
        return CheckedVM(base.journal, calls)

    broker.provider_factory = factory
    workspace = await broker.provision(cost_bound_usd="0.1", operation_id="provision")
    before = len(service.list_records("workspace_operation", broker.actor, experiment["id"]))
    operations = {
        "upload": lambda: broker.upload_file(
            workspace["id"],
            expected_execution_id="vm-123",
            path="/work/a.lean",
            data=b"contents",
            operation_id="invalid-upload",
        ),
        "download": lambda: broker.download_file(
            workspace["id"],
            expected_execution_id="vm-123",
            path="/work/a.lean",
            operation_id="invalid-download",
        ),
        "read_range": lambda: broker.read_workspace_range(
            workspace["id"],
            expected_execution_id="vm-123",
            path="/work/a.lean",
            offset=0,
            length=8,
            operation_id="invalid-read",
        ),
    }
    with pytest.raises(HarnessError) as error:
        await operations[command]()
    assert error.value.code == "UNSAFE_PATH"
    assert (
        len(service.list_records("workspace_operation", broker.actor, experiment["id"])) == before
    )
    current = service.get_record("workspace", workspace["id"], broker.actor)
    assert current["status"] == "ready" and current["active_operation_id"] is None
    assert service.ledger(experiment["id"], broker.actor)["uncertain_operations"] == 0
    assert calls == ["create"]
    result = await broker.run(
        workspace["id"],
        expected_execution_id="vm-123",
        request=CommandRequest(operation_id="valid-after-path", argv=["true"]),
    )
    assert result["exit_code"] == 0 and calls == ["create", "run"]


async def test_same_error_code_after_dispatch_is_not_a_safe_rejection(lab):
    broker, service, experiment, calls, made, args = setup(lab)
    original = broker.provider_factory

    class UnsafeAfterDispatch(FakeVM):
        def validate_command(self, request):
            return None

        async def run(self, request):
            self.calls.append("run")
            raise ExecutionError("UNSAFE_PATH", "provider returned ambiguous failure")

    def factory(**kwargs):
        base = original(**kwargs)
        return UnsafeAfterDispatch(base.journal, calls)

    broker.provider_factory = factory
    workspace = await broker.provision(cost_bound_usd="0.1", operation_id="provision")
    with pytest.raises(HarnessError) as error:
        await broker.run(
            workspace["id"],
            expected_execution_id="vm-123",
            request=CommandRequest(operation_id="ambiguous", argv=["true"]),
        )
    assert error.value.code == "WORKSPACE_RECONCILIATION_REQUIRED"
    assert calls == ["create", "run"]
    assert (
        service.get_record("workspace", workspace["id"], broker.actor)["status"]
        == "reconciliation_required"
    )
    assert service.ledger(experiment["id"], broker.actor)["uncertain_operations"] > 0


@pytest.mark.parametrize("invalid_authority", ["wrong_identity", "paused_experiment"])
async def test_authority_precedes_safe_request_validation(lab, invalid_authority):
    broker, service, experiment, calls, made, args = setup(lab)
    original = broker.provider_factory
    validations = []

    class CheckedVM(FakeVM):
        def validate_command(self, request):
            validations.append(request.operation_id)
            raise ExecutionError("UNSAFE_PATH", "bad cwd")

    def factory(**kwargs):
        base = original(**kwargs)
        return CheckedVM(base.journal, calls)

    broker.provider_factory = factory
    workspace = await broker.provision(cost_bound_usd="0.1", operation_id="provision")
    if invalid_authority == "paused_experiment":
        current = service.get_record("experiment", experiment["id"], broker.actor)
        service.transition_experiment(
            experiment["id"], "pause", current["revision"], broker.actor, "pause-before-command"
        )
    with pytest.raises(HarnessError) as error:
        await broker.run(
            workspace["id"],
            expected_execution_id="wrong-vm" if invalid_authority == "wrong_identity" else "vm-123",
            request=CommandRequest(operation_id="unauthorized", argv=["true"], cwd="/work"),
        )
    assert error.value.code == (
        "WORKSPACE_IDENTITY_MISMATCH"
        if invalid_authority == "wrong_identity"
        else "EXPERIMENT_NOT_ACTIVE"
    )
    assert validations == []
    assert calls == ["create"]


async def test_actual_local_provider_rejects_absolute_workspace_paths_without_docker():
    calls = []

    async def no_docker(argv, **kwargs):
        calls.append(argv)
        raise AssertionError("invalid local request reached Docker")

    provider = LocalDockerWorkspaceProvider(
        docker_host="unix:///tmp/physharness-pilot/docker.sock",
        image_digest="sha256:" + "a" * 64,
        timeout_seconds=60,
        runner=no_docker,
    )
    provider._container_id = "synthetic-container-id"
    assert (
        provider.validate_command(CommandRequest(operation_id="valid", argv=["true"], cwd="."))
        == "/work"
    )
    with pytest.raises(ExecutionError) as bad_cwd:
        provider.validate_command(CommandRequest(operation_id="bad", argv=["true"], cwd="/work"))
    assert bad_cwd.value.code == "UNSAFE_PATH"
    for action in (
        provider.upload_file("/work/a.lean", b"x", expected_execution_id=provider.execution_id),
        provider.download_file("/work/a.lean", expected_execution_id=provider.execution_id),
        provider.read_range(
            "/work/a.lean",
            offset=0,
            length=8,
            expected_execution_id=provider.execution_id,
        ),
    ):
        with pytest.raises(ExecutionError) as error:
            await action
        assert error.value.code == "UNSAFE_PATH"
    assert calls == []
