"""File promotion tests use a fake VM for transport, never synthetic proof acceptance."""

import hashlib
import os
import subprocess
import sys

import pytest
from test_workspace_service import setup

from physharness.domain import Principal
from physharness.errors import HarnessError
from physharness.execution.local_docker import _GUEST, LocalDockerWorkspaceProvider
from physharness.execution.types import CommandRequest
from physharness.execution.workspace_archive import checked_path
from physharness.orchestration.workspace_tools import WorkspaceTools
from physharness.orchestration.workspaces import WorkspaceBroker


async def test_promote_file_captures_exact_source_and_replays_without_second_read(lab):
    broker, service, experiment, calls, made, _ = setup(lab)
    workspace = await broker.provision(cost_bound_usd="0.2", operation_id="p")
    source = b"theorem example : True := by trivial\n"
    made[0].files["proof.lean"] = source
    made[0].capture_file = lambda path, **kw: _capture(made[0], calls, path, **kw)
    digest = hashlib.sha256(source).hexdigest()
    target = service.get_record("experiment", experiment["id"], broker.actor)["target_digest"]
    kwargs = dict(
        expected_execution_id=workspace["execution_id"],
        path="proof.lean",
        expected_sha256=digest,
        expected_target_digest=target,
        operation_id="capture",
    )
    result = await broker.promote_file(workspace["id"], **kwargs)
    assert result["sha256"] == digest
    assert result["proof_status"] == "not_accepted"
    assert service.artifact_content(result["artifact_id"], broker.actor) == source
    assert (await broker.promote_file(workspace["id"], **kwargs)) == result
    assert calls.count("capture") == 1


async def test_promote_file_rejects_wrong_hash_and_target_without_artifact(lab):
    broker, service, experiment, calls, made, _ = setup(lab)
    workspace = await broker.provision(cost_bound_usd="0.2", operation_id="p")
    made[0].files["proof.lean"] = b"theorem example : True := by trivial\n"
    made[0].capture_file = lambda path, **kw: _capture(made[0], calls, path, **kw)
    target = service.get_record("experiment", experiment["id"], broker.actor)["target_digest"]
    with pytest.raises(HarnessError):
        await broker.promote_file(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            path="proof.lean",
            expected_sha256="0" * 64,
            expected_target_digest=target,
            operation_id="wrong-hash",
        )
    with pytest.raises(HarnessError):
        await broker.promote_file(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            path="proof.lean",
            expected_sha256=hashlib.sha256(made[0].files["proof.lean"]).hexdigest(),
            expected_target_digest="f" * 64,
            operation_id="wrong-target",
        )
    assert calls.count("capture") == 1
    with pytest.raises(HarnessError):
        await broker.promote_file(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            path="proof.lean",
            expected_sha256="0" * 64,
            expected_target_digest=target,
            operation_id="wrong-hash",
        )
    assert calls.count("capture") == 1
    good = await broker.promote_file(
        workspace["id"],
        expected_execution_id=workspace["execution_id"],
        path="proof.lean",
        expected_sha256=hashlib.sha256(made[0].files["proof.lean"]).hexdigest(),
        expected_target_digest=target,
        operation_id="corrected",
    )
    assert good["proof_status"] == "not_accepted"


async def _capture(vm, calls, path, *, expected_execution_id, max_bytes):
    checked_path(path)
    assert expected_execution_id == vm.execution_id
    calls.append("capture")
    data = vm.files[path]
    if len(data) > max_bytes:
        raise HarnessError("WORKSPACE_TRANSFER_REJECTED", "Source exceeds bounded capture")
    return data


def test_guest_capture_is_bounded_and_refuses_symlink(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    (root / "proof.lean").write_bytes(b"exact proof")
    (root / "outside.lean").symlink_to(tmp_path / "secret")
    (tmp_path / "secret").write_bytes(b"secret")
    guest = _GUEST.replace("root='/work'", f"root={str(root)!r}")

    def capture(path, cap):
        return subprocess.run(
            [sys.executable, "-c", guest, "capture", path, str(cap)],
            capture_output=True,
        )

    assert capture("proof.lean", 11).stdout == b"Oexact proof"
    assert capture("proof.lean", 4).stdout == b"R"
    linked = capture("outside.lean", 100)
    assert linked.stdout == b"R"


async def test_submit_workspace_candidate_queues_existing_verifier_as_agent(lab):
    broker, service, experiment, calls, made, _ = setup(lab)
    workspace = await broker.provision(cost_bound_usd="0.2", operation_id="p")
    source = b"theorem example : True := by trivial\n"
    made[0].files["proof.lean"] = source
    made[0].capture_file = lambda path, **kw: _capture(made[0], calls, path, **kw)
    task = service.get_record("task", broker.task_id, broker.actor)
    agent = Principal(
        id="proof-agent",
        project_id=broker.actor.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=task["branch_id"],
    )
    tools = WorkspaceTools.__new__(WorkspaceTools)
    tools.broker, tools.workspace = broker, workspace
    result = await tools.submit_workspace_candidate(
        {
            "path": "proof.lean",
            "sha256": hashlib.sha256(source).hexdigest(),
            "target_digest": experiment["target_digest"],
        },
        "submit",
        agent,
    )
    receipt = service.get_record("verification", result["receipt_id"], broker.actor)
    artifact = service.get_record("artifact", result["artifact_id"], broker.actor)
    assert receipt["status"] == "queued"
    assert receipt["submitted_by"] == agent.id
    assert artifact["branch_id"] == agent.branch_id
    assert result["status"] == "queued"


@pytest.mark.integration
async def test_real_pinned_workspace_capture_boundary_and_candidate_queue(lab):
    """Opt-in dedicated Docker check; it never calls a model or acceptance worker."""
    host = os.environ.get("PHYSHARNESS_WORKBENCH_DOCKER_HOST")
    image = os.environ.get("PHYSHARNESS_WORKBENCH_IMAGE_DIGEST")
    if not host or not image:
        pytest.skip("Dedicated workbench endpoint and pinned image digest are required")
    fixture, service, experiment, _, _, _ = setup(lab, concurrency=1)
    broker = WorkspaceBroker(
        service,
        actor=fixture.actor,
        task_id=fixture.task_id,
        holder=fixture.holder,
        fence=fixture.fence,
        provider_factory=lambda *, journal, timeout_seconds: LocalDockerWorkspaceProvider(
            docker_host=host,
            image_digest=image,
            timeout_seconds=timeout_seconds,
            journal=journal,
        ),
        provider_spec={"provider": "local_docker", "template_id": image, "timeout_seconds": 180},
    )
    workspace = None
    try:
        workspace = await broker.provision(cost_bound_usd="0", operation_id="capture-provision")
        source = b"import Mathlib\ntheorem copied : True := by trivial\n"
        await broker.upload_file(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            path="proof.lean",
            data=source,
            operation_id="capture-upload",
        )
        target = service.get_record("experiment", experiment["id"], broker.actor)["target_digest"]
        args = dict(
            expected_execution_id=workspace["execution_id"],
            path="proof.lean",
            expected_sha256=hashlib.sha256(source).hexdigest(),
            expected_target_digest=target,
        )
        result = await broker.promote_file(workspace["id"], operation_id="capture-good", **args)
        assert service.artifact_content(result["artifact_id"], broker.actor) == source
        assert result["proof_status"] == "not_accepted"
        await broker.upload_file(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            path="consumer.lean",
            data=source + b"theorem use_copied : True := by exact copied\n",
            operation_id="reuse-upload",
        )
        local_check = await broker.run(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            request=CommandRequest(
                operation_id="reuse-compile",
                argv=["lake", "--offline", "env", "lean", "/work/consumer.lean"],
                cwd="/opt/sources/physlib",
                timeout_seconds=120,
            ),
        )
        assert local_check["exit_code"] == 0, local_check["stderr"]
        task = service.get_record("task", broker.task_id, broker.actor)
        agent = Principal(
            id="capture-agent",
            project_id=broker.actor.project_id,
            role="agent",
            experiment_id=experiment["id"],
            branch_id=task["branch_id"],
        )
        tools = WorkspaceTools.__new__(WorkspaceTools)
        tools.broker, tools.workspace = broker, workspace
        submitted = await tools.submit_workspace_candidate(
            {"path": "proof.lean", "sha256": args["expected_sha256"], "target_digest": target},
            "real-candidate",
            agent,
        )
        assert (
            service.get_record("verification", submitted["receipt_id"], broker.actor)["status"]
            == "queued"
        )
        with pytest.raises(HarnessError):
            await broker.promote_file(
                workspace["id"],
                operation_id="capture-bad-hash",
                **{**args, "expected_sha256": "0" * 64},
            )
        with pytest.raises(HarnessError):
            await broker.promote_file(
                workspace["id"],
                operation_id="capture-bad-target",
                **{**args, "expected_target_digest": "f" * 64},
            )
        command = await broker.run(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            request=CommandRequest(
                operation_id="capture-symlink",
                argv=[
                    "python3",
                    "-c",
                    "import os; os.symlink('/work/proof.lean', '/work/link.lean')",
                ],
                cwd=".",
                timeout_seconds=10,
            ),
        )
        assert command["exit_code"] == 0
        with pytest.raises(HarnessError):
            await broker.promote_file(
                workspace["id"],
                operation_id="capture-link",
                **{**args, "path": "link.lean"},
            )
        assert broker.inspect(workspace["id"])["status"] == "ready"
    finally:
        if workspace and broker.inspect(workspace["id"])["status"] == "ready":
            await broker.destroy(
                workspace["id"],
                expected_execution_id=workspace["execution_id"],
                operation_id="capture-destroy",
                actual_cost_usd="0",
            )


async def test_capture_transport_failure_is_uncertain_not_refusal(lab):
    from physharness.execution import ExecutionError

    broker, service, experiment, _, made, _ = setup(lab)
    workspace = await broker.provision(cost_bound_usd="0.2", operation_id="p")
    source = b"theorem example : True := by trivial\n"

    async def lost(path, **kwargs):
        raise ExecutionError("WORKSPACE_TRANSFER_FAILED", "transport lost after dispatch")

    made[0].capture_file = lost
    target = service.get_record("experiment", experiment["id"], broker.actor)["target_digest"]
    with pytest.raises(HarnessError) as error:
        await broker.promote_file(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            path="proof.lean",
            expected_sha256=hashlib.sha256(source).hexdigest(),
            expected_target_digest=target,
            operation_id="lost",
        )
    assert error.value.code != "WORKSPACE_TRANSFER_REJECTED"
    assert broker.inspect(workspace["id"])["status"] == "reconciliation_required"
    assert service.ledger(experiment["id"], broker.actor)["uncertain_operations"] == 1


async def test_e2b_upload_helper_refusal_is_not_treated_as_definite(lab):
    from physharness.execution import ExecutionError

    broker, service, experiment, _, made, _ = setup(lab)
    workspace = await broker.provision(cost_bound_usd="0.2", operation_id="p")

    async def refuse(path, data, **kwargs):
        # The E2B helper can exit nonzero after a partial write.
        raise ExecutionError("WORKSPACE_TRANSFER_REJECTED", "helper completed unsuccessfully")

    made[0].upload_file = refuse
    with pytest.raises(HarnessError) as error:
        await broker.upload_file(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            path="a.lean",
            data=b"x",
            operation_id="upload",
        )
    assert error.value.code != "WORKSPACE_TRANSFER_REJECTED"
    assert broker.inspect(workspace["id"])["status"] == "reconciliation_required"
    assert service.ledger(experiment["id"], broker.actor)["uncertain_operations"] == 1
