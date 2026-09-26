from types import SimpleNamespace

import pytest
from test_core import setup_experiment

from physharness.domain import ArtifactCreate, BranchCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.storage import LeaseRow, ReservationRow
from physharness.verification import VerificationOutcome
from physharness.worker_authority import worker_effects


def recovery_case(lab, *, command="run", native_status="handed_off"):
    service, researcher, _ = lab
    experiment, _ = setup_experiment(lab)
    experiment = service.transition_experiment(
        experiment["id"], "start", experiment["revision"], researcher, "start-recovery"
    )
    operator = Principal(id="recovery-operator", project_id=researcher.project_id, role="operator")
    branch = service.create_branch(
        experiment["id"],
        BranchCreate(title="Recovery", objective="Recover files"),
        researcher,
        "recovery-branch",
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Attempt"), researcher, "recovery-task"
    )
    lease = service.acquire_task(task["id"], "recovery-holder", 300, operator, "recovery-lease")
    slot = service.reserve_resources(experiment["id"], "0", 1, operator, "recovery-slot")
    workspace_reservation = service.reserve_resources(
        experiment["id"], "0", 0, operator, "recovery-workspace-reservation"
    )
    execution_id = "a" * 64
    with service.db.transaction() as session:
        task_row = service._get(session, "task", task["id"], operator)
        service._replace(
            session,
            task_row,
            {"status": "blocked", "execution_status": "blocked", "worker_slot_id": slot["id"]},
        )
        session.get(LeaseRow, task["id"]).expires_at = 0
        workspace = service._insert(
            session,
            "workspace",
            operator,
            {
                "task_id": task["id"],
                "experiment_id": experiment["id"],
                "branch_id": branch["id"],
                "holder": "recovery-holder",
                "fence": lease["fence"],
                "provider_spec": {
                    "provider": "local_docker",
                    "template_id": "sha256:" + "b" * 64,
                    "timeout_seconds": 60,
                },
                "reservation_id": workspace_reservation["id"],
                "shared_worker_slot_id": slot["id"],
                "cost_bound_usd": "0.000000",
                "status": "reconciliation_required",
                "execution_id": execution_id,
                "active_operation_id": None,
                "destruction_confirmed": False,
            },
        )
        operation = service._insert(
            session,
            "workspace_operation",
            operator,
            {
                "experiment_id": experiment["id"],
                "branch_id": branch["id"],
                "task_id": task["id"],
                "workspace_id": workspace["id"],
                "command": command,
                "status": "reconciliation_required",
                "result": None,
            },
        )
        row = service._get(session, "workspace", workspace["id"], operator)
        workspace = service._replace(session, row, {"active_operation_id": operation["id"]})
        session_record = service._insert(
            session,
            "session",
            operator,
            {
                "experiment_id": experiment["id"],
                "branch_id": branch["id"],
                "task_id": task["id"],
                "status": native_status,
            },
        )
    service.settle_resources(slot["id"], None, True, operator, "slot-uncertain")
    service.settle_resources(
        workspace_reservation["id"], None, True, operator, "workspace-uncertain"
    )
    experiment = service.get_record("experiment", experiment["id"], operator)
    service.transition_experiment(
        experiment["id"], "pause", experiment["revision"], operator, "pause-recovery"
    )
    artifact = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            kind="workspace_recovery_observation",
            content="Operator attests absence after archive.",
            provenance={
                "workspace_id": workspace["id"],
                "execution_id": execution_id,
                "archive_sha256": "c" * 64,
                "destruction_confirmed": True,
                "absence_confirmed": True,
            },
        ),
        operator,
        "recovery-evidence",
    )
    return (
        service,
        operator,
        experiment,
        task,
        workspace,
        operation,
        session_record,
        slot,
        workspace_reservation,
        artifact,
    )


def test_retire_failed_local_workspace_settles_only_zero_cost_resources(lab):
    service, actor, experiment, task, workspace, operation, native, slot, reservation, artifact = (
        recovery_case(lab)
    )
    result = service.retire_failed_local_workspace(
        workspace["id"],
        workspace["revision"],
        workspace["execution_id"],
        artifact["id"],
        actor,
        "retire-recovery",
    )
    assert result["workspace_id"] == workspace["id"]
    assert service.get_record("workspace", workspace["id"], actor)["status"] == "destroyed"
    assert service.get_record("workspace_operation", operation["id"], actor)["status"] == "failed"
    assert service.get_record("session", native["id"], actor)["status"] == "failed"
    assert service.get_record("task", task["id"], actor)["status"] == "failed"
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    assert (
        service.retire_failed_local_workspace(
            workspace["id"],
            workspace["revision"],
            workspace["execution_id"],
            artifact["id"],
            actor,
            "retire-recovery",
        )
        == result
    )


def test_retire_failed_export_preserves_completed_session_and_accepted_receipt(lab):
    service, actor, experiment, task, workspace, operation, native, slot, reservation, artifact = (
        recovery_case(lab, command="export", native_status="completed")
    )
    candidate = service.create_artifact(
        ArtifactCreate(experiment_id=experiment["id"], kind="lean_source", content="proof"),
        actor,
        "export-case-candidate",
    )
    receipt = service.verify_candidate(
        experiment["id"], candidate["id"], True, actor, "export-case-submit"
    )

    def accepted(request):
        return VerificationOutcome(
            status="verified",
            assurance="independent_kernel",
            code="kernel_checked",
            message="Controlled accepted receipt",
            remediation="",
            challenge_sha256=request.challenge_sha256,
            target_digest=request.target_digest,
            environment_digest=request.environment_digest,
            candidate_sha256=request.candidate_sha256,
            axioms=[],
            checker_versions={"lean": "test-pin", "comparator": "test-pin", "nanoda": "test-pin"},
        )

    service.verifier = SimpleNamespace(verify=accepted)
    verified = service.process_verification(receipt["id"], actor)
    assert verified["status"] == "verified"
    claim = service.get_record("claim", verified["claim_id"], actor)
    session_before = service.get_record("session", native["id"], actor)
    receipt_before = service.get_record("verification", receipt["id"], actor)
    spent_before = service.ledger(experiment["id"], actor)["spent_cost_usd"]
    service.retire_failed_local_workspace(
        workspace["id"],
        workspace["revision"],
        workspace["execution_id"],
        artifact["id"],
        actor,
        "retire-export",
    )
    assert service.get_record("workspace_operation", operation["id"], actor)["status"] == "failed"
    assert service.get_record("session", native["id"], actor) == session_before
    assert service.get_record("verification", receipt["id"], actor) == receipt_before
    assert service.get_record("claim", claim["id"], actor) == claim
    assert service.ledger(experiment["id"], actor)["spent_cost_usd"] == spent_before


@pytest.mark.parametrize("command", ["upload", "restore", "destroy", "read_range"])
def test_retirement_denies_other_uncertain_commands(lab, command):
    service, actor, experiment, task, workspace, operation, native, slot, reservation, artifact = (
        recovery_case(lab, command=command)
    )
    before = service.ledger(experiment["id"], actor)
    with pytest.raises(HarnessError, match="Uncertain operation binding"):
        service.retire_failed_local_workspace(
            workspace["id"],
            workspace["revision"],
            workspace["execution_id"],
            artifact["id"],
            actor,
            f"reject-{command}",
        )
    assert service.ledger(experiment["id"], actor) == before


@pytest.mark.parametrize(
    "change", ["bad_identity", "bad_revision", "live_lease", "bad_evidence", "active_experiment"]
)
def test_retire_failed_local_workspace_rejects_unsafe_state(lab, change):
    service, actor, experiment, task, workspace, operation, native, slot, reservation, artifact = (
        recovery_case(lab)
    )
    execution_id = workspace["execution_id"]
    revision = workspace["revision"]
    evidence_id = artifact["id"]
    if change == "bad_identity":
        execution_id = "d" * 64
    elif change == "bad_revision":
        revision += 1
    elif change == "live_lease":
        with service.db.transaction() as session:
            session.get(LeaseRow, task["id"]).expires_at = 9999999999
    elif change == "bad_evidence":
        evidence_id = task["id"]
    elif change == "active_experiment":
        exp = service.get_record("experiment", experiment["id"], actor)
        service.transition_experiment(
            exp["id"], "resume", exp["revision"], actor, "resume-recovery"
        )
    with pytest.raises(HarnessError):
        service.retire_failed_local_workspace(
            workspace["id"], revision, execution_id, evidence_id, actor, "retire-recovery"
        )
    assert (
        service.get_record("workspace", workspace["id"], actor)["status"]
        == "reconciliation_required"
    )


def test_recovery_observation_cannot_be_issued_by_worker_or_bound_operator(lab):
    service, actor, experiment, task, workspace, operation, native, slot, reservation, artifact = (
        recovery_case(lab)
    )
    worker = Principal(
        id="worker",
        project_id=actor.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=task["branch_id"],
    )
    request = ArtifactCreate(
        experiment_id=experiment["id"],
        kind="workspace_recovery_observation",
        content="Forged",
        provenance={"workspace_id": workspace["id"]},
    )
    with pytest.raises(HarnessError, match="unbound operator"):
        service.create_artifact(request, worker, "worker-forgery")
    with worker_effects(actor, task["id"], "recovery-holder", 1, require_active=False):
        with pytest.raises(HarnessError, match="unbound operator"):
            service.create_artifact(request, actor, "bound-forgery")
        with pytest.raises(HarnessError, match="Unbound controller"):
            service.retire_failed_local_workspace(
                workspace["id"],
                workspace["revision"],
                workspace["execution_id"],
                artifact["id"],
                actor,
                "bound-retirement",
            )


def test_retirement_rolls_back_if_shared_slot_charge_is_ambiguous(lab):
    service, actor, experiment, task, workspace, operation, native, slot, reservation, artifact = (
        recovery_case(lab)
    )
    with service.db.transaction() as session:
        session.get(ReservationRow, slot["id"]).reserved = 1
    with pytest.raises(HarnessError, match="Zero-cost"):
        service.retire_failed_local_workspace(
            workspace["id"],
            workspace["revision"],
            workspace["execution_id"],
            artifact["id"],
            actor,
            "ambiguous-retirement",
        )
    assert (
        service.get_record("workspace", workspace["id"], actor)["status"]
        == "reconciliation_required"
    )
    assert (
        service.get_record("workspace_operation", operation["id"], actor)["status"]
        == "reconciliation_required"
    )
    assert service.get_record("session", native["id"], actor)["status"] == "handed_off"
    assert service.get_record("task", task["id"], actor)["status"] == "blocked"


def test_retirement_rejects_unsettled_model_charge_even_if_binding_is_stale(lab):
    service, actor, experiment, task, workspace, operation, native, slot, reservation, artifact = (
        recovery_case(lab)
    )
    current = service.get_record("experiment", experiment["id"], actor)
    service.transition_experiment(
        current["id"], "resume", current["revision"], actor, "resume-for-model-charge"
    )
    model_charge = service.reserve_resources(experiment["id"], "0.1", 0, actor, "unsettled-model")
    current = service.get_record("experiment", experiment["id"], actor)
    service.transition_experiment(
        current["id"], "pause", current["revision"], actor, "repause-for-model-charge"
    )
    with service.db.transaction() as session:
        service._insert(
            session,
            "model_reservation",
            actor,
            {
                "experiment_id": experiment["id"],
                "task_id": task["id"],
                "reservation_id": model_charge["id"],
                "status": "settled",
            },
        )
    with pytest.raises(HarnessError, match="Model charge remains open"):
        service.retire_failed_local_workspace(
            workspace["id"],
            workspace["revision"],
            workspace["execution_id"],
            artifact["id"],
            actor,
            "model-charge-open",
        )
    assert (
        service.get_record("workspace", workspace["id"], actor)["status"]
        == "reconciliation_required"
    )


def test_retirement_rolls_back_resources_for_unexpected_native_session(lab):
    service, actor, experiment, task, workspace, operation, native, slot, reservation, artifact = (
        recovery_case(lab)
    )
    with service.db.transaction() as session:
        row = service._get(session, "session", native["id"], actor)
        service._replace(session, row, {"status": "interrupted"})
    before = service.ledger(experiment["id"], actor)
    with pytest.raises(HarnessError, match="unexpected status"):
        service.retire_failed_local_workspace(
            workspace["id"],
            workspace["revision"],
            workspace["execution_id"],
            artifact["id"],
            actor,
            "unexpected-session-retirement",
        )
    assert service.ledger(experiment["id"], actor) == before
    with service.db.sessions() as session:
        assert session.get(ReservationRow, slot["id"]).state == "uncertain"
        assert session.get(ReservationRow, reservation["id"]).state == "uncertain"
    assert service.get_record("task", task["id"], actor)["status"] == "blocked"


def test_running_task_retires_only_as_an_abandoned_attempt(lab):
    # A worker that lost its lease cannot mark its task terminal; the task stays running.
    service, actor, experiment, task, workspace, operation, native, slot, reservation, artifact = (
        recovery_case(lab, command="export")
    )

    def retire(key):
        return service.retire_failed_local_workspace(
            workspace["id"],
            workspace["revision"],
            workspace["execution_id"],
            artifact["id"],
            actor,
            key,
        )

    for status, expires_at, code in [
        ("queued", 0, "RECOVERY_SCOPE"),
        ("running", 9999999999, "LEASE_HELD"),
    ]:
        with service.db.transaction() as session:
            row = service._get(session, "task", task["id"], actor)
            service._replace(session, row, {"status": status})
            session.get(LeaseRow, task["id"]).expires_at = expires_at
        with pytest.raises(HarnessError) as error:
            retire(f"reject-{status}")
        assert error.value.code == code
    with service.db.transaction() as session:
        session.get(LeaseRow, task["id"]).expires_at = 0
    retire("retire-abandoned")
    assert service.get_record("task", task["id"], actor)["status"] == "failed"
    assert service.get_record("workspace", workspace["id"], actor)["status"] == "destroyed"
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
