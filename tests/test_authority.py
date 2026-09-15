from datetime import timedelta

import pytest
from sqlalchemy import update
from test_core import setup_experiment

from physharness.domain import ArtifactCreate, BranchCreate, Principal, TaskCreate, utcnow
from physharness.errors import HarnessError
from physharness.storage import LeaseRow


def operator(actor):
    return Principal(id="controller", project_id=actor.project_id, role="operator")


def test_worker_cannot_mint_experiments_review_or_reconcile_own_usage(lab):
    service, researcher, _ = lab
    experiment, problem = setup_experiment(lab)
    worker = Principal(id="worker", project_id="lab", role="agent", experiment_id=experiment["id"])
    service.transition_experiment(experiment["id"], "start", 1, researcher, "start")
    reservation = service.reserve_resources(
        experiment["id"], "0.5", 1, operator(researcher), "allocation"
    )
    with pytest.raises(HarnessError, match="capability"):
        service.settle_resources(reservation["id"], "0", False, worker, "forged-usage")
    with pytest.raises(HarnessError):
        service.review_problem(problem["id"], "approved", "self-review", worker, "forged-review")
    with pytest.raises(HarnessError):
        service.reserve_resources(experiment["id"], "0", 1, worker, "free-worker")
    branch = service.create_branch(
        experiment["id"],
        BranchCreate(title="Alternative", objective="Try a representation"),
        worker,
        "branch",
    )
    assert branch["experiment_id"] == experiment["id"]


def test_worker_scope_does_not_expose_other_experiment_history(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    worker = Principal(id="worker", project_id="lab", role="agent", experiment_id="unrelated")
    with pytest.raises(HarnessError):
        service.get_record("experiment", experiment["id"], worker)
    assert service.list_records("experiment", worker) == []
    assert service.events(worker) == []


def test_agent_identity_requires_an_explicit_experiment():
    with pytest.raises(ValueError):
        Principal(id="worker", project_id="lab", role="agent")


def test_task_lease_is_fenced_and_completion_needs_evidence(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    controller = operator(actor)
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Branch", objective="Proof attempt"), actor, "branch"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Prove a lemma"), actor, "task"
    )
    lease = service.acquire_task(task["id"], "worker-a", 60, controller, "lease-a")
    with service.db.transaction() as session:
        session.execute(
            update(LeaseRow)
            .where(LeaseRow.task_id == task["id"])
            .values(expires_at=(utcnow() - timedelta(seconds=1)).timestamp())
        )
    new_lease = service.acquire_task(task["id"], "worker-b", 60, controller, "lease-b")
    assert new_lease["fence"] > lease["fence"]
    evidence = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            kind="finding",
            content="Incomplete: unresolved regularity",
        ),
        actor,
        "finding",
    )
    with pytest.raises(HarnessError) as failure:
        service.finish_task(
            task["id"],
            "worker-a",
            lease["fence"],
            [evidence["id"]],
            "completed",
            controller,
            "stale-finish",
        )
    assert failure.value.code == "STALE_LEASE"
    completed = service.finish_task(
        task["id"],
        "worker-b",
        new_lease["fence"],
        [evidence["id"]],
        "completed",
        controller,
        "finish",
    )
    assert completed["status"] == "completed"
    assert completed["evidence_ids"] == [evidence["id"]]
    assert "verified" not in completed


def test_verification_submission_cannot_self_accept_and_unavailable_checker_is_loud(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    candidate = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            kind="lean_source",
            content="theorem target : (1 : Nat) = 1 := by rfl",
        ),
        actor,
        "candidate",
    )
    queued = service.verify_candidate(experiment["id"], candidate["id"], False, actor, "verify")
    assert queued["status"] == "queued"
    assert queued["assurance"] == "none"
    result = service.process_verification(queued["id"], operator(actor))
    assert result["status"] == "blocked"
    assert result["code"] == "verifier_unavailable"
    assert result["assurance"] == "none"
    assert service.list_records("claim", actor) == []
    assert service.process_verification(queued["id"], operator(actor)) == result


def test_global_token_budget_is_enforced_across_model_calls(lab):
    service, actor, _ = lab
    from physharness.domain import ExperimentCreate

    original, _ = setup_experiment(lab)
    request = ExperimentCreate.model_validate(
        {k: original[k] for k in ["campaign_id", "problem_id", "models", "budget"]}
    )
    request = request.model_copy(
        update={"budget": request.budget.model_copy(update={"max_tokens": 100})}
    )
    experiment = service.create_experiment(request, actor, "token-exp")
    service.transition_experiment(experiment["id"], "start", 1, actor, "token-start")
    service.reserve_resources(experiment["id"], "0.1", 0, operator(actor), "tokens-one", tokens=70)
    with pytest.raises(HarnessError) as failure:
        service.reserve_resources(
            experiment["id"], "0.1", 0, operator(actor), "tokens-two", tokens=40
        )
    assert failure.value.code == "TOKEN_BUDGET_EXCEEDED"


def test_idempotency_cache_does_not_return_data_after_identity_scope_changes(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    request = BranchCreate(title="Private", objective="Original identity")
    branch = service.create_branch(experiment["id"], request, actor, "original-branch")
    reassigned = Principal(
        id=actor.id, project_id=actor.project_id, role="agent", experiment_id="elsewhere"
    )
    with pytest.raises(HarnessError):
        service.get_record("branch", branch["id"], reassigned)
    with pytest.raises(HarnessError):
        service.create_branch(experiment["id"], request, reassigned, "original-branch")


def test_checkpoint_replay_uses_caller_intent_not_changed_live_context(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="B", objective="Explore"), actor, "branch"
    )
    args = (branch["id"], 1, "Try an invariant", "b" * 64, "a" * 64, None, actor, "checkpoint")
    saved = service.checkpoint_branch(*args)
    assert service.checkpoint_branch(*args) == saved
