"""Worker cleanup never strands a local VM or its worker slot.

Executor-level: a scripted runtime writes a file into a local workbench whose Docker
transport runs the real guest helper, then the experiment is paused, cancelled or runs
out of time, or the task lease is lost. Cleanup must end with a saved final checkpoint,
a destroyed VM and a released slot, or with a workspace the operator recovery path
accepts; a teardown without a saved checkpoint is recorded in the failure evidence.
"""

import asyncio
import json
import time

import pytest
from test_core import setup_experiment
from test_workbench_failure_classification import (
    HOST,
    IMAGE,
    GuestDocker,
    local_broker,
    workspace_tools,
)

from physharness.domain import ArtifactCreate, BranchCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import RuntimeResult, RuntimeSession
from physharness.execution.local_docker import LocalDockerWorkspaceProvider
from physharness.execution.workspace_archive import StreamedWorkspaceArchive
from physharness.orchestration import workspaces
from physharness.orchestration.research_worker import (
    ResearchTaskExecutor,
    ResearchTeamRunner,
    TeamRunManifest,
)
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


def slow_guest_reads(runner, seconds, on_chunk=None):
    """Each guest chunk read takes `seconds`, standing in for a slow `docker exec`."""
    base = type(runner)

    class Slow(base):
        async def __call__(self, argv, **kwargs):
            if "chunk" in argv:
                self.chunk_reads += 1
                if on_chunk is not None:
                    on_chunk(self.chunk_reads)
                await asyncio.sleep(seconds)
            return await base.__call__(self, argv, **kwargs)

    runner.__class__ = Slow
    runner.chunk_reads = 0


def expire_lease(service, task, seconds=0.0):
    with service.db.transaction() as session:
        session.get(LeaseRow, task["id"]).expires_at = time.time() + seconds if seconds else 0


def guest_actions(runner, action):
    return [call for call in runner.calls if action in call]


def scripted_runtime(monkeypatch, executor, service, operator, experiment, task, **options):
    """Write Proof.lean, then optionally stop the experiment and cut the lease short."""
    runtime = executor.runtime_factory

    async def start(self, prompt, model, limits):
        written = await self.dispatcher.dispatch(
            "write_workspace_file", {"path": "Proof.lean", "content": SOURCE}, "write"
        )
        assert "error" not in written, written
        if options.get("stop"):
            stop_experiment(service, operator, experiment, task, options["stop"])
        if options.get("residual_lease"):
            # The active-experiment renewal is refused now; only the residual lease
            # (at most 60 s in production) remains when worker cleanup starts.
            expire_lease(service, task, options["residual_lease"])
        return RuntimeResult(
            session=RuntimeSession(runtime="responses", model=model, limits=limits),
            output_text="partial result",
            completion_reason=options.get("completion_reason"),
        )

    monkeypatch.setattr(runtime, "start", start)


def recovery_evidence(service, operator, experiment, workspace, key="recovery-evidence"):
    return service.create_artifact(
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
        key,
    )


@pytest.mark.parametrize(
    "stop,code",
    [
        ("pause", "EXPERIMENT_NOT_ACTIVE"),
        ("cancel", "EXPERIMENT_NOT_ACTIVE"),
        ("deadline", "EXPERIMENT_DEADLINE"),
    ],
)
async def test_slow_final_checkpoint_after_stop_outlives_residual_lease(
    lab, tmp_path, monkeypatch, stop, code
):
    service, operator, experiment, task, executor, runner, root = workbench(lab, tmp_path, [])
    for index in range(4):
        (root / f"Lemma{index}.lean").write_text(f"theorem t{index} : True := trivial\n")
    scripted_runtime(
        monkeypatch, executor, service, operator, experiment, task, stop=stop, residual_lease=1
    )
    slow_guest_reads(runner, 0.35)  # Five reads outlast the residual lease.
    with pytest.raises(HarnessError) as error:
        await executor.execute(task["id"], operator.project_id)
    assert error.value.code == code
    [workspace] = service.list_records("workspace", operator, experiment["id"])
    assert workspace["status"] == "destroyed" and runner.removed()
    assert sorted(checkpoint_paths(service, operator, workspace)) == [
        "Lemma0.lean",
        "Lemma1.lean",
        "Lemma2.lean",
        "Lemma3.lean",
        "Proof.lean",
    ]
    [export] = operations(service, operator, experiment, "export")
    assert export["status"] == "completed" and export["inputs"]["final_checkpoint"] is True
    ledger = service.ledger(experiment["id"], operator)
    assert ledger["active_workers"] == 0 and ledger["uncertain_operations"] == 0


async def test_cleanup_keeps_renewing_lease_through_deduplicated_checkpoint(
    lab, tmp_path, monkeypatch
):
    # Identical files dedupe to one stored chunk, so most reads persist nothing.
    monkeypatch.setattr(workspaces, "_CLEANUP_LEASE_SECONDS", 2)
    service, operator, experiment, task, executor, runner, root = workbench(lab, tmp_path, [])
    for index in range(15):
        (root / f"copy{index}.txt").write_text("same bytes\n")
    scripted_runtime(
        monkeypatch,
        executor,
        service,
        operator,
        experiment,
        task,
        stop="pause",
        residual_lease=0.5,
    )
    slow_guest_reads(runner, 0.2)  # Over 3 s of reads under a 2 s cleanup lease.
    with pytest.raises(HarnessError) as error:
        await executor.execute(task["id"], operator.project_id)
    assert error.value.code == "EXPERIMENT_NOT_ACTIVE"
    [workspace] = service.list_records("workspace", operator, experiment["id"])
    assert workspace["status"] == "destroyed" and runner.removed()
    assert len(checkpoint_paths(service, operator, workspace)) == 16
    ledger = service.ledger(experiment["id"], operator)
    assert ledger["active_workers"] == 0 and ledger["uncertain_operations"] == 0


async def test_cleanup_renewal_never_revives_an_expired_or_replaced_lease(lab, tmp_path):
    broker, service, experiment, runner, root, _ = local_broker(lab, tmp_path)
    tools = workspace_tools(broker, service, experiment)
    await tools.write({"path": "Proof.lean", "content": SOURCE}, "w1")
    current = service.get_record("experiment", experiment["id"], broker.actor)
    service.transition_experiment(
        experiment["id"], "pause", current["revision"], broker.actor, "pause"
    )
    renew = service.renew_task_for_cleanup
    args = (broker.task_id, broker.holder, broker.fence, broker.worker_slot_id, 60, broker.actor)
    with pytest.raises(HarnessError) as refused:  # Another holder's fence.
        renew(broker.task_id, broker.holder, broker.fence + 1, None, 60, broker.actor, "r0")
    assert refused.value.code == "STALE_LEASE"
    expire_lease(service, {"id": broker.task_id}, 5)
    assert renew(*args, "r1")["expires_at"] > time.time() + 55  # Inactive, still live.
    expire_lease(service, {"id": broker.task_id})
    with pytest.raises(HarnessError) as refused:
        renew(*args, "r2")
    assert refused.value.code == "STALE_LEASE"
    with service.db.transaction() as session:
        assert session.get(LeaseRow, broker.task_id).expires_at == 0


async def test_cleanup_renewal_requires_an_open_workspace_of_that_holder(lab, tmp_path):
    broker, service, experiment, runner, root, _ = local_broker(lab, tmp_path)
    args = (broker.task_id, broker.holder, broker.fence, broker.worker_slot_id, 60, broker.actor)
    with pytest.raises(HarnessError) as refused:  # Nothing to close yet.
        service.renew_task_for_cleanup(*args, "r1")
    assert refused.value.code == "CLEANUP_SCOPE"
    tools = workspace_tools(broker, service, experiment)
    await tools.write({"path": "Proof.lean", "content": SOURCE}, "w1")
    service.renew_task_for_cleanup(*args, "r2")
    await tools.close()
    with pytest.raises(HarnessError) as refused:  # The VM is gone; cleanup is over.
        service.renew_task_for_cleanup(*args, "r3")
    assert refused.value.code == "CLEANUP_SCOPE"


async def test_final_checkpoint_deadline_stops_guest_reads_and_reports(lab, tmp_path, monkeypatch):
    monkeypatch.setattr(workspaces, "_FINAL_CHECKPOINT_SECONDS", 0.5)
    service, operator, experiment, task, executor, runner, root = workbench(lab, tmp_path, [])
    for index in range(6):
        (root / f"Lemma{index}.lean").write_text(f"theorem t{index} : True := trivial\n")
    scripted_runtime(monkeypatch, executor, service, operator, experiment, task)
    slow_guest_reads(runner, 0.3)
    with pytest.raises(HarnessError) as error:
        await executor.execute(task["id"], operator.project_id)
    assert error.value.code == "WORKSPACE_CHECKPOINT_UNSAVED"
    # No guest read is issued past the deadline, including the closing listing.
    assert runner.chunk_reads <= 3 and len(guest_actions(runner, "list3")) == 1
    [export] = operations(service, operator, experiment, "export")
    assert export["status"] == "rejected"
    assert export["result"]["code"] == "WORKSPACE_CHECKPOINT_DEADLINE"
    [workspace] = service.list_records("workspace", operator, experiment["id"])
    assert workspace["status"] == "destroyed" and runner.removed()
    ledger = service.ledger(experiment["id"], operator)
    assert ledger["active_workers"] == 0 and ledger["uncertain_operations"] == 0
    [failure] = failure_evidence(service, operator, experiment)
    assert failure["code"] == "WORKSPACE_CHECKPOINT_UNSAVED"
    assert failure["workspace_cleanup"]["final_checkpoint"] == {
        "status": "rejected",
        "operation_id": export["id"],
        "code": "WORKSPACE_CHECKPOINT_DEADLINE",
    }
    assert service.get_record("task", task["id"], operator)["status"] == "blocked"


async def test_lease_lost_mid_checkpoint_stops_deduplicated_guest_reads(lab, tmp_path, monkeypatch):
    monkeypatch.setattr(workspaces, "_CLEANUP_LEASE_SECONDS", 1)
    service, operator, experiment, task, executor, runner, root = workbench(lab, tmp_path, [])
    for index in range(20):
        (root / f"copy{index:02}.txt").write_text("same bytes\n")
    scripted_runtime(monkeypatch, executor, service, operator, experiment, task)

    def lose_lease(reads):
        if reads == 3:
            expire_lease(service, task)

    slow_guest_reads(runner, 0.1, lose_lease)
    with pytest.raises(HarnessError) as error:
        await executor.execute(task["id"], operator.project_id)
    assert error.value.code == "WORKSPACE_RECONCILIATION_REQUIRED"
    # Reads stop at the next renewal instead of continuing through all 21 files.
    assert runner.chunk_reads < 12 and len(guest_actions(runner, "list3")) == 1
    assert not runner.removed()
    [workspace] = service.list_records("workspace", operator, experiment["id"])
    [export] = operations(service, operator, experiment, "export")
    assert workspace["status"] == "reconciliation_required"
    assert workspace["active_operation_id"] == export["id"]
    assert export["status"] == "reconciliation_required"
    assert service.ledger(experiment["id"], operator)["active_workers"] == 1


@pytest.mark.parametrize("stop", [None, "pause"])
async def test_lease_lost_after_final_checkpoint_is_recoverable(lab, tmp_path, monkeypatch, stop):
    service, operator, experiment, task, executor, runner, root = workbench(lab, tmp_path, [])
    scripted_runtime(monkeypatch, executor, service, operator, experiment, task, stop=stop)
    original = WorkspaceBroker.destroy

    async def destroy(self, *args, **kwargs):
        expire_lease(service, task)  # The lease runs out right after the export commits.
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(WorkspaceBroker, "destroy", destroy)
    with pytest.raises(HarnessError) as error:
        await executor.execute(task["id"], operator.project_id)
    assert error.value.code == "WORKSPACE_RECONCILIATION_REQUIRED"
    # Nothing was destroyed without authority; the undispatched teardown is recorded.
    assert not runner.removed() and (root / "Proof.lean").read_text() == SOURCE
    [workspace] = service.list_records("workspace", operator, experiment["id"])
    [export] = operations(service, operator, experiment, "export")
    [teardown] = operations(service, operator, experiment, "destroy")
    assert export["status"] == "completed"
    assert workspace["status"] == "reconciliation_required"
    assert workspace["destruction_confirmed"] is False
    assert workspace["active_operation_id"] == teardown["id"]
    assert teardown["status"] == "reconciliation_required"
    assert teardown["result"]["code"] == "STALE_LEASE"
    saved = teardown["inputs"]["final_checkpoint"]
    assert saved["status"] == "completed"
    assert saved["artifact_id"] == workspace["checkpoint_artifact_id"]
    [failure] = failure_evidence(service, operator, experiment)
    assert failure["workspace_cleanup"]["status"] == "reconciliation_required"
    assert failure["workspace_cleanup"]["operation_id"] == teardown["id"]
    assert service.ledger(experiment["id"], operator)["active_workers"] == 1
    # The documented operator procedure applies and releases the slot.
    if stop is None:
        current = service.get_record("experiment", experiment["id"], operator)
        service.transition_experiment(
            experiment["id"], "pause", current["revision"], operator, "pause-for-recovery"
        )
    evidence = recovery_evidence(service, operator, experiment, workspace)
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


async def test_repeated_close_after_final_checkpoint_records_undispatched_teardown(lab, tmp_path):
    broker, service, experiment, runner, root, _ = local_broker(lab, tmp_path)
    tools = workspace_tools(broker, service, experiment)
    await tools.write({"path": "Proof.lean", "content": SOURCE}, "w1")
    # An earlier close saved the final checkpoint, then stopped before teardown.
    saved = await broker.export_workspace(
        tools.workspace["id"],
        expected_execution_id=tools.workspace["execution_id"],
        operation_id=f"final-checkpoint:{broker.holder}",
        final=True,
    )
    expire_lease(service, {"id": broker.task_id})
    for _ in range(2):
        with pytest.raises(HarnessError) as error:
            await tools.close()
        assert error.value.code == "WORKSPACE_RECONCILIATION_REQUIRED"
    assert not runner.removed()
    workspace = broker.inspect(tools.workspace["id"])
    [teardown] = operations(service, broker.actor, experiment, "destroy")
    assert workspace["status"] == "reconciliation_required"
    assert workspace["active_operation_id"] == teardown["id"]
    assert teardown["result"]["code"] == "STALE_LEASE"
    assert teardown["inputs"]["final_checkpoint"]["artifact_id"] == saved["artifact"]["id"]
    assert tools.cleanup_report["status"] == "reconciliation_required"
    assert tools.cleanup_report["operation_id"] == teardown["id"]


async def test_dispatched_uncertain_teardown_stays_outside_operator_retirement(
    lab, tmp_path, monkeypatch
):
    service, operator, experiment, task, executor, runner, root = workbench(lab, tmp_path, [])
    scripted_runtime(monkeypatch, executor, service, operator, experiment, task, stop="pause")
    base = type(runner)

    class FailingRemoval(base):
        async def __call__(self, argv, **kwargs):
            if argv[3] == "rm":
                self.calls.append(argv[3:])
                return 1, b"", b"daemon unavailable"
            return await base.__call__(self, argv, **kwargs)

    runner.__class__ = FailingRemoval
    with pytest.raises(HarnessError):
        await executor.execute(task["id"], operator.project_id)
    [workspace] = service.list_records("workspace", operator, experiment["id"])
    [teardown] = operations(service, operator, experiment, "destroy")
    assert workspace["status"] == "reconciliation_required"
    assert teardown["status"] == "reconciliation_required" and teardown["result"] is None
    expire_lease(service, task)
    evidence = recovery_evidence(service, operator, experiment, workspace)
    with pytest.raises(HarnessError) as refused:
        service.retire_failed_local_workspace(
            workspace["id"],
            workspace["revision"],
            workspace["execution_id"],
            evidence["id"],
            operator,
            "retire",
        )
    assert refused.value.code == "RECOVERY_SCOPE"


async def test_verified_target_keeps_outcome_when_final_checkpoint_is_refused(
    lab, tmp_path, monkeypatch
):
    service, operator, experiment, task, executor, runner, root = workbench(
        lab, tmp_path, [], oversized={"list3"}
    )
    scripted_runtime(
        monkeypatch,
        executor,
        service,
        operator,
        experiment,
        task,
        completion_reason="target_verified",
    )
    result = await executor.execute(task["id"], operator.project_id)
    assert result["status"] == "completed"
    [warning] = result["warnings"]
    assert warning["code"] == "WORKSPACE_CHECKPOINT_UNSAVED"
    current = service.get_record("task", task["id"], operator)
    assert current["status"] == "completed"
    output_id, warning_id = current["evidence_ids"]
    assert warning_id == warning["artifact_id"]
    kinds = [
        service.get_record("artifact", identifier, operator)["artifact_kind"]
        for identifier in current["evidence_ids"]
    ]
    assert kinds == ["research_output", "execution_failure"]
    [export] = operations(service, operator, experiment, "export")
    [evidence] = failure_evidence(service, operator, experiment)
    assert evidence["code"] == "WORKSPACE_CHECKPOINT_UNSAVED"
    assert evidence["severity"] == "warning"
    assert evidence["workspace_cleanup"]["final_checkpoint"] == {
        "status": "rejected",
        "operation_id": export["id"],
        "code": "WORKSPACE_TRANSFER_REJECTED",
    }
    [workspace] = service.list_records("workspace", operator, experiment["id"])
    assert workspace["status"] == "destroyed"
    ledger = service.ledger(experiment["id"], operator)
    assert ledger["active_workers"] == 0 and ledger["uncertain_operations"] == 0


async def test_team_run_stays_clean_when_verified_task_checkpoint_is_refused(
    lab, tmp_path, monkeypatch
):
    service, operator, experiment, task, executor, runner, root = workbench(
        lab, tmp_path, [], oversized={"list3"}
    )
    dependent = service.create_task(
        TaskCreate(branch_id=task["branch_id"], objective="follow up", dependency_ids=[task["id"]]),
        lab[1],
        "dependent",
    )
    scripted_runtime(
        monkeypatch,
        executor,
        service,
        operator,
        experiment,
        task,
        completion_reason="target_verified",
    )
    report = await ResearchTeamRunner(service, executor=executor).run(
        TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=operator.project_id,
            mode="replay",
            task_ids=[task["id"], dependent["id"]],
            timeout_seconds=60,
            process_verifications=False,
        )
    )
    outcomes = {outcome["task_id"]: outcome for outcome in report["outcomes"]}
    assert outcomes[task["id"]]["status"] == "completed"
    assert outcomes[task["id"]]["warnings"][0]["code"] == "WORKSPACE_CHECKPOINT_UNSAVED"
    assert outcomes[dependent["id"]]["status"] == "completed"  # Dependents still run.
    assert report["status"] == "completed", report
