"""Only a proven, operator-attested pre-dispatch local read can retire."""

import pytest
from test_failed_local_workspace_retirement import recovery_case

from physharness.domain import ArtifactCreate
from physharness.errors import HarnessError


def read_case(lab, *, path="/work/lyap_comparison.lean", mismatch=None):
    service, actor, experiment, task, workspace, operation, native, slot, reservation, old = (
        recovery_case(lab, command="read_range", native_status="completed")
    )
    inputs = {
        "execution_id": workspace["execution_id"],
        "command": "read_range",
        "path": path,
        "offset": 0,
        "length": 25000,
    }
    if mismatch == "wrong_execution":
        inputs["execution_id"] = "b" * 64
    elif mismatch == "bad_length":
        inputs["length"] = 0
    with service.db.transaction() as session:
        row = service._get(session, "workspace_operation", operation["id"], actor)
        service._replace(session, row, {"inputs": inputs})
    prior_provenance = service.get_record("artifact", old["id"], actor)["provenance"]
    if mismatch == "wrong_attested_path":
        attested_path = "/work/other.lean"
    else:
        attested_path = path
    evidence = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            kind="workspace_recovery_observation",
            content="Operator observation, not a scientific claim.",
            provenance={
                **prior_provenance,
                "predispatch_rejected_path": attested_path,
            },
        ),
        actor,
        "read-recovery-evidence",
    )
    return service, actor, experiment, task, workspace, operation, native, evidence


def test_exact_invalid_read_can_retire_after_operator_teardown(lab):
    service, actor, experiment, task, workspace, operation, native, evidence = read_case(lab)
    native_before = service.get_record("session", native["id"], actor)
    result = service.retire_failed_local_workspace(
        workspace["id"],
        workspace["revision"],
        workspace["execution_id"],
        evidence["id"],
        actor,
        "retire-invalid-read",
    )
    assert result["failed_session_ids"] == []
    assert service.get_record("session", native["id"], actor) == native_before
    assert service.get_record("workspace", workspace["id"], actor)["status"] == "destroyed"
    assert service.get_record("workspace_operation", operation["id"], actor)["status"] == "failed"
    assert service.get_record("task", task["id"], actor)["status"] == "failed"
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0


@pytest.mark.parametrize(
    "path,mismatch",
    [
        ("scratch/valid.lean", None),
        ("/work/lyap_comparison.lean", "wrong_execution"),
        ("/work/lyap_comparison.lean", "bad_length"),
        ("/work/lyap_comparison.lean", "wrong_attested_path"),
    ],
)
def test_read_retirement_denies_nonmatching_or_possibly_dispatched_request(lab, path, mismatch):
    service, actor, experiment, task, workspace, operation, native, evidence = read_case(
        lab, path=path, mismatch=mismatch
    )
    before = service.ledger(experiment["id"], actor)
    with pytest.raises(HarnessError) as error:
        service.retire_failed_local_workspace(
            workspace["id"],
            workspace["revision"],
            workspace["execution_id"],
            evidence["id"],
            actor,
            "reject-invalid-read",
        )
    assert error.value.code == "RECOVERY_SCOPE"
    assert service.ledger(experiment["id"], actor) == before
    assert (
        service.get_record("workspace", workspace["id"], actor)["status"]
        == "reconciliation_required"
    )
