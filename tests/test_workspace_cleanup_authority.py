"""Worker cleanup never strands a local VM or its worker slot.

Executor-level: a scripted runtime writes a file into a local workbench whose Docker
transport runs the real guest helper, then the experiment is paused, cancelled or runs
out of time, or the task lease is lost. Cleanup must end with a saved final checkpoint,
a destroyed VM and a released slot, or with a workspace the operator recovery path
accepts; a teardown without a saved checkpoint is recorded in the failure evidence.
"""

import json

import pytest
from test_core import setup_experiment
from test_workbench_failure_classification import HOST, IMAGE, GuestDocker

from physharness.domain import ArtifactCreate, BranchCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import RuntimeResult, RuntimeSession
from physharness.execution.local_docker import LocalDockerWorkspaceProvider
from physharness.execution.workspace_archive import StreamedWorkspaceArchive
from physharness.orchestration.research_worker import ResearchTaskExecutor
from physharness.orchestration.workspace_tools import WorkspacePolicy, WorkspaceTools
from physharness.orchestration.workspaces import WorkspaceBroker
from physharness.storage import LeaseRow

SOURCE = "theorem x : True := trivial\n"
PRICES = {"explicit-test-model": {"input_usd_per_million": "1", "output_usd_per_million": "1"}}


def stop_experiment(service, operator, experiment, task, stop):
    if stop == "lease":
        with service.db.transaction() as session:
            session.get(LeaseRow, task["id"]).expires_at = 0
        return
    if stop == "deadline":
        with service.db.transaction() as session:
            row = service._get(session, "experiment", experiment["id"], operator)
            service._replace(session, row, {"started_at": "2000-01-01T00:00:00+00:00"})
        return
    current = service.get_record("experiment", experiment["id"], operator)
    service.transition_experiment(
        experiment["id"], stop, current["revision"], operator, f"operator-{stop}"
    )


def workbench(lab, tmp_path, stops, **transport):
    """One-slot experiment whose runtime writes Proof.lean, then applies the next stop."""
    service, researcher, _ = lab
    experiment, problem = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, researcher, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="R", objective="E"), researcher, "branch"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="work"), researcher, "task"
    )
    root = tmp_path / "work"
    root.mkdir()
    runner = GuestDocker(root, **transport)
    operator = Principal(id="operator", project_id=researcher.project_id, role="operator")
    policy = WorkspacePolicy(
        template_id=IMAGE,
        environment_digest=problem["environment_digest"],
        qualification_report_sha256="a" * 64,
        timeout_seconds=60,
        cost_bound_usd="0",
        cost_source="local_no_external_invoice",
    )

    def vm_factory(service, actor, task_id, holder, fence, worker_slot_id):
        def provider_factory(*, journal, timeout_seconds):
            return LocalDockerWorkspaceProvider(
                docker_host=HOST,
                image_digest=IMAGE,
                timeout_seconds=timeout_seconds,
                runner=runner,
                journal=journal,
            )

        broker = WorkspaceBroker(
            service,
            actor=actor,
            task_id=task_id,
            holder=holder,
            fence=fence,
            worker_slot_id=worker_slot_id,
            provider_factory=provider_factory,
            provider_spec={"provider": "local_docker", "template_id": IMAGE, "timeout_seconds": 60},
        )
        return WorkspaceTools(broker, policy)

    class Runtime:
        def __init__(self, store, dispatcher, event_sink):
            self.dispatcher = dispatcher

        async def start(self, prompt, model, limits):
            written = await self.dispatcher.dispatch(
                "write_workspace_file", {"path": "Proof.lean", "content": SOURCE}, "write"
            )
            assert "error" not in written, written
            stop = stops.pop(0) if stops else None
            if stop:
                stop_experiment(service, operator, experiment, task, stop)
            return RuntimeResult(
                session=RuntimeSession(runtime="responses", model=model, limits=limits),
                output_text="partial result",
            )

    executor = ResearchTaskExecutor(
        service, prices=PRICES, runtime_factory=Runtime, workspace_factory=vm_factory
    )
    return service, operator, experiment, task, executor, runner, root


def operations(service, operator, experiment, command):
    return [
        row
        for row in service.list_records("workspace_operation", operator, experiment["id"])
        if row["command"] == command
    ]


def failure_evidence(service, operator, experiment):
    rows = [
        row
        for row in service.list_records("artifact", operator, experiment["id"])
        if row.get("artifact_kind") == "execution_failure"
    ]
    return [json.loads(service.artifact_content(row["id"], operator)) for row in rows]


def checkpoint_paths(service, operator, workspace):
    artifact = service.get_record("artifact", workspace["checkpoint_artifact_id"], operator)
    archive = StreamedWorkspaceArchive.from_bytes(
        service.artifact_content(artifact["id"], operator), sha256=artifact["sha256"]
    )
    return [entry["path"] for entry in archive.manifest["files"]]


@pytest.mark.parametrize(
    "stop,code",
    [
        ("pause", "EXPERIMENT_NOT_ACTIVE"),
        ("cancel", "EXPERIMENT_NOT_ACTIVE"),
        ("deadline", "EXPERIMENT_DEADLINE"),
    ],
)
async def test_stopped_experiment_cleanup_checkpoints_destroys_and_releases_slot(
    lab, tmp_path, stop, code
):
    service, operator, experiment, task, executor, runner, root = workbench(lab, tmp_path, [stop])
    with pytest.raises(HarnessError) as error:
        await executor.execute(task["id"], operator.project_id)
    assert error.value.code == code
    [workspace] = service.list_records("workspace", operator, experiment["id"])
    assert workspace["status"] == "destroyed" and runner.removed()
    ledger = service.ledger(experiment["id"], operator)
    assert ledger["active_workers"] == 0 and ledger["uncertain_operations"] == 0
    # The agent's work survives in a final checkpoint taken under cleanup authority.
    assert checkpoint_paths(service, operator, workspace) == ["Proof.lean"]
    [export] = operations(service, operator, experiment, "export")
    assert export["status"] == "completed" and export["inputs"]["final_checkpoint"] is True
    [teardown] = operations(service, operator, experiment, "destroy")
    assert teardown["inputs"]["final_checkpoint"]["status"] == "completed"
    [failure] = failure_evidence(service, operator, experiment)
    assert failure["code"] == code
    assert failure["workspace_cleanup"]["status"] == "destroyed"
    saved = failure["workspace_cleanup"]["final_checkpoint"]
    assert saved["artifact_id"] == workspace["checkpoint_artifact_id"]
    if stop == "pause":
        # Once resumed and the stale lease lapses, the freed slot runs the task again.
        current = service.get_record("experiment", experiment["id"], operator)
        service.transition_experiment(
            experiment["id"], "resume", current["revision"], operator, "resume"
        )
        with service.db.transaction() as session:
            session.get(LeaseRow, task["id"]).expires_at = 0
        result = await executor.execute(task["id"], operator.project_id)
        assert result["status"] == "completed"
        assert service.ledger(experiment["id"], operator)["active_workers"] == 0


async def test_lost_lease_cleanup_leaves_vm_for_operator_retirement(lab, tmp_path):
    service, operator, experiment, task, executor, runner, root = workbench(
        lab, tmp_path, ["lease"]
    )
    with pytest.raises(HarnessError) as error:
        await executor.execute(task["id"], operator.project_id)
    assert error.value.code == "WORKSPACE_RECONCILIATION_REQUIRED"
    # Without the lease nothing is read or destroyed: the VM and its files stay put.
    assert not runner.removed() and (root / "Proof.lean").read_text() == SOURCE
    [workspace] = service.list_records("workspace", operator, experiment["id"])
    assert workspace["status"] == "reconciliation_required"
    [export] = operations(service, operator, experiment, "export")
    assert workspace["active_operation_id"] == export["id"]
    assert export["status"] == "reconciliation_required"
    assert export["inputs"]["final_checkpoint"] is True
    assert export["result"]["code"] == "STALE_LEASE"
    assert not any("list3" in call for call in runner.calls)
    [failure] = failure_evidence(service, operator, experiment)
    assert failure["workspace_cleanup"]["status"] == "reconciliation_required"
    assert failure["workspace_cleanup"]["operation_id"] == export["id"]
    assert service.ledger(experiment["id"], operator)["active_workers"] == 1
    # The documented operator procedure now applies and releases the slot.
    current = service.get_record("experiment", experiment["id"], operator)
    service.transition_experiment(
        experiment["id"], "pause", current["revision"], operator, "pause-for-recovery"
    )
    evidence = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            kind="workspace_recovery_observation",
            content="Operator archived /work, removed the container and confirmed absence.",
            provenance={
                "workspace_id": workspace["id"],
                "execution_id": workspace["execution_id"],
                "archive_sha256": "c" * 64,
                "destruction_confirmed": True,
                "absence_confirmed": True,
            },
        ),
        operator,
        "recovery-evidence",
    )
    service.retire_failed_local_workspace(
        workspace["id"],
        workspace["revision"],
        workspace["execution_id"],
        evidence["id"],
        operator,
        "retire",
    )
    ledger = service.ledger(experiment["id"], operator)
    assert ledger["active_workers"] == 0 and ledger["uncertain_operations"] == 0
    assert service.get_record("workspace", workspace["id"], operator)["status"] == "destroyed"
    assert service.get_record("task", task["id"], operator)["status"] == "failed"


@pytest.mark.parametrize("stop", [None, "pause"])
async def test_teardown_without_saved_checkpoint_is_recorded_as_failure(lab, tmp_path, stop):
    # A complete but over-limit listing definitely refuses the final checkpoint.
    service, operator, experiment, task, executor, runner, root = workbench(
        lab, tmp_path, [stop], oversized={"list3"}
    )
    with pytest.raises(HarnessError) as error:
        await executor.execute(task["id"], operator.project_id)
    expected = "WORKSPACE_CHECKPOINT_UNSAVED"
    assert error.value.code == expected
    [workspace] = service.list_records("workspace", operator, experiment["id"])
    assert workspace["status"] == "destroyed" and runner.removed()
    ledger = service.ledger(experiment["id"], operator)
    assert ledger["active_workers"] == 0 and ledger["uncertain_operations"] == 0
    [export] = operations(service, operator, experiment, "export")
    assert export["status"] == "rejected"
    [failure] = failure_evidence(service, operator, experiment)
    assert failure["code"] == expected
    assert failure["workspace_cleanup"]["status"] == "destroyed"
    assert failure["workspace_cleanup"]["final_checkpoint"] == {
        "status": "rejected",
        "operation_id": export["id"],
        "code": "WORKSPACE_TRANSFER_REJECTED",
    }
    current = service.get_record("task", task["id"], operator)
    if stop is None:
        # The loss is reported through the task outcome, not only on the destroy record.
        # (A paused experiment keeps the task unchanged; its failure evidence remains.)
        assert current["status"] == "blocked"
        [evidence_id] = current["evidence_ids"]
        assert service.get_record("artifact", evidence_id, operator)["artifact_kind"] == (
            "execution_failure"
        )
