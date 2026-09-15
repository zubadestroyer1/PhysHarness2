from datetime import timedelta

import pytest
from sqlalchemy import update
from test_core import setup_experiment

from physharness.domain import ArtifactCreate, BranchCreate, Principal, TaskCreate, utcnow
from physharness.errors import HarnessError
from physharness.storage import LeaseRow


def running_task(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Attempt", objective="Explore"), actor, "branch"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Explore"), actor, "task"
    )
    operator = Principal(id="controller", project_id="lab", role="operator")
    lease = service.acquire_task(task["id"], "holder", 60, operator, "lease")
    worker = Principal(
        id="worker",
        project_id="lab",
        role="agent",
        experiment_id=experiment["id"],
        branch_id=branch["id"],
    )
    return service, experiment, task, worker, operator, lease


def test_expired_worker_cannot_publish_or_receive_cached_mutation(lab):
    from physharness.worker_authority import worker_effects

    service, experiment, task, worker, operator, lease = running_task(lab)
    request = ArtifactCreate(experiment_id=experiment["id"], kind="finding", content="Unproved")
    with worker_effects(worker, task["id"], "holder", lease["fence"]):
        artifact = service.create_artifact(request, worker, "finding")
    with service.db.transaction() as session:
        session.execute(
            update(LeaseRow)
            .where(LeaseRow.task_id == task["id"])
            .values(expires_at=(utcnow() - timedelta(seconds=1)).timestamp())
        )
    for key in ("finding", "new-finding"):
        with worker_effects(worker, task["id"], "holder", lease["fence"]):
            with pytest.raises(HarnessError) as error:
                service.create_artifact(request, worker, key)
        assert error.value.code == "STALE_LEASE"
        assert error.value.operation_id
    assert [r["id"] for r in service.list_records("artifact", operator)] == [artifact["id"]]


def test_cancelled_experiment_stops_operator_checkpoint_effects(lab):
    from physharness.worker_authority import worker_effects

    service, experiment, task, worker, operator, lease = running_task(lab)
    current = service.get_record("experiment", experiment["id"], operator)
    service.transition_experiment(
        experiment["id"], "cancel", current["revision"], operator, "cancel"
    )
    with worker_effects(operator, task["id"], "holder", lease["fence"]):
        with pytest.raises(HarnessError) as error:
            service.create_artifact(
                ArtifactCreate(
                    experiment_id=experiment["id"], kind="native_checkpoint", content="stale"
                ),
                operator,
                "checkpoint",
            )
    assert error.value.code == "EXPERIMENT_NOT_ACTIVE"
    assert service.list_records("artifact", operator) == []


def test_fence_rechecked_after_action_and_partial_effect_rolled_back(lab):
    from physharness.worker_authority import worker_effects

    service, experiment, task, worker, operator, lease = running_task(lab)

    def action(session, op):
        row = service._insert(session, "finding", worker, {"experiment_id": experiment["id"]})
        # Represents expiry while an action performs external I/O under the transaction.
        session.execute(
            update(LeaseRow)
            .where(LeaseRow.task_id == task["id"])
            .values(expires_at=(utcnow() - timedelta(seconds=1)).timestamp())
        )
        return row

    with worker_effects(worker, task["id"], "holder", lease["fence"]):
        with pytest.raises(HarnessError) as error:
            service._execute(worker, "slow-operation", "test.slow", {}, action)
    assert error.value.code == "STALE_LEASE"
    assert service.list_records("finding", operator) == []


def test_binding_cannot_change_actor_and_resets_after_exception(lab):
    from physharness.worker_authority import worker_effects

    service, experiment, task, worker, operator, lease = running_task(lab)
    request = ArtifactCreate(experiment_id=experiment["id"], kind="finding", content="Unproved")
    with worker_effects(worker, task["id"], "holder", lease["fence"]):
        with pytest.raises(HarnessError) as error:
            service.create_artifact(request, operator, "wrong-actor")
    assert error.value.code == "WORKER_EFFECT_SCOPE"
    assert service.create_artifact(request, operator, "outside-context")["id"]


def test_only_controller_can_retain_final_checkpoint_after_cancellation(lab):
    from physharness.worker_authority import worker_effects

    service, experiment, task, worker, operator, lease = running_task(lab)
    current = service.get_record("experiment", experiment["id"], operator)
    service.transition_experiment(
        experiment["id"], "cancel", current["revision"], operator, "cancel"
    )
    with (
        pytest.raises(HarnessError) as error,
        worker_effects(worker, task["id"], "holder", lease["fence"], require_active=False),
    ):
        pytest.fail("An agent acquired the operator exception")
    assert error.value.code == "WORKER_EFFECT_SCOPE"
    with worker_effects(operator, task["id"], "holder", lease["fence"], require_active=False):
        record = service.create_artifact(
            ArtifactCreate(
                experiment_id=experiment["id"], kind="native_checkpoint", content="uncertain"
            ),
            operator,
            "final-checkpoint",
        )
    assert record["kind"] == "artifact"
    assert service.get_record("experiment", experiment["id"], operator)["status"] == "cancelled"
