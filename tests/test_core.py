from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from physharness.artifacts import LocalArtifactStore
from physharness.domain import CampaignCreate, ExperimentCreate, Principal, ProblemCreate
from physharness.errors import HarnessError
from physharness.service import HarnessService
from physharness.storage import Database


def setup_experiment(lab, *, approved=True, cost="1.00", concurrency=2):
    service, actor, reviewer = lab
    campaign = service.create_campaign(
        CampaignCreate(
            title="Quantum lab", objective="Check trace invariance", programs=["quantum"]
        ),
        actor,
        "campaign",
    )
    problem = service.create_problem(
        ProblemCreate(
            campaign_id=campaign["id"],
            title="Trace",
            program="quantum",
            informal_statement="The trace of the identity is its dimension.",
            formal_statement="theorem target : (1 : Nat) = 1 := by rfl",
            assumptions=["Finite-dimensional setting"],
            environment_digest="a" * 64,
        ),
        actor,
        "problem",
    )
    if approved:
        service.review_problem(problem["id"], "approved", "Reviewed fixture", reviewer, "review")
    experiment = service.create_experiment(
        ExperimentCreate(
            campaign_id=campaign["id"],
            problem_id=problem["id"],
            models=[{"runtime": "responses", "model": "explicit-test-model"}],
            budget={
                "max_cost_usd": cost,
                "max_concurrency": concurrency,
                "max_runtime_seconds": 600,
            },
        ),
        actor,
        "experiment",
    )
    return experiment, problem


def test_idempotent_command_is_reused_but_changed_intent_is_rejected(lab):
    service, actor, _ = lab
    request = CampaignCreate(title="A", objective="B", programs=["classical"])
    first = service.create_campaign(request, actor, "same")
    assert service.create_campaign(request, actor, "same") == first
    assert len(service.list_records("campaign", actor)) == 1
    with pytest.raises(HarnessError) as err:
        service.create_campaign(request.model_copy(update={"title": "Changed"}), actor, "same")
    assert err.value.code == "IDEMPOTENCY_CONFLICT"


def test_review_cannot_be_fabricated_by_researcher(lab):
    service, actor, _ = lab
    _, problem = setup_experiment(lab, approved=False)
    with pytest.raises(HarnessError) as err:
        service.review_problem(problem["id"], "approved", "I say so", actor, "forged")
    assert err.value.code == "FORBIDDEN"
    assert service.get_record("problem", problem["id"], actor)["semantic_review"] == "pending"


def test_unreviewed_target_cannot_start_an_accepted_target_experiment(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, approved=False)
    with pytest.raises(HarnessError) as err:
        service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    assert err.value.code == "TARGET_REVIEW_REQUIRED"


def test_stale_transition_cannot_overwrite_new_state(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    queued = service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    assert queued["status"] == "queued"
    with pytest.raises(HarnessError) as err:
        service.transition_experiment(experiment["id"], "cancel", 1, actor, "cancel-old")
    assert err.value.code == "REVISION_CONFLICT"
    cancelled = service.transition_experiment(experiment["id"], "cancel", 2, actor, "cancel")
    assert cancelled["status"] == "cancelled"
    with pytest.raises(HarnessError) as err:
        service.reserve_resources(experiment["id"], "0.10", 1, actor, "late-child")
    assert err.value.code == "EXPERIMENT_NOT_ACTIVE"


def test_different_project_cannot_read_or_mutate_known_identifiers(lab):
    service, actor, _ = lab
    experiment, problem = setup_experiment(lab)
    outsider = Principal(id=actor.id, project_id="other", role="reviewer")
    with pytest.raises(HarnessError) as err:
        service.get_record("problem", problem["id"], outsider)
    assert err.value.code == "NOT_FOUND"
    assert service.list_records("experiment", outsider) == []
    with pytest.raises(HarnessError):
        service.review_problem(problem["id"], "approved", "Forged", outsider, "other-review")


def test_concurrent_reservations_cannot_overspend_budget(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, cost="1.00", concurrency=100)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")

    def reserve(i):
        try:
            return service.reserve_resources(experiment["id"], "0.40", 1, actor, f"reserve-{i}")
        except HarnessError as error:
            assert error.code == "BUDGET_EXCEEDED"
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = [x for x in pool.map(reserve, range(8)) if x]
    assert len(accepted) == 2
    ledger = service.ledger(experiment["id"], actor)
    assert Decimal(ledger["reserved_cost_usd"]) == Decimal("0.80")
    assert ledger["active_workers"] == 2


def test_concurrency_limit_applies_across_descendants(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    reservation = service.reserve_resources(experiment["id"], "0.10", 1, actor, "r1")
    with pytest.raises(HarnessError) as err:
        service.reserve_resources(experiment["id"], "0.10", 1, actor, "r2")
    assert err.value.code == "CONCURRENCY_EXCEEDED"
    service.settle_resources(
        reservation["id"],
        "0.08",
        False,
        Principal(id="controller", project_id="lab", role="operator"),
        "settle",
    )
    service.settle_resources(
        reservation["id"],
        "0.08",
        False,
        Principal(id="controller", project_id="lab", role="operator"),
        "settle-again",
    )
    ledger = service.ledger(experiment["id"], actor)
    assert ledger["active_workers"] == 0
    assert Decimal(ledger["spent_cost_usd"]) == Decimal("0.08")


def test_uncertain_external_cost_is_not_refunded(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    reservation = service.reserve_resources(experiment["id"], "0.40", 1, actor, "r1")
    service.settle_resources(
        reservation["id"],
        None,
        True,
        Principal(id="controller", project_id="lab", role="operator"),
        "uncertain",
    )
    ledger = service.ledger(experiment["id"], actor)
    assert Decimal(ledger["reserved_cost_usd"]) == Decimal("0.40")
    assert ledger["uncertain_operations"] == 1


def test_events_and_outbox_survive_database_reopen(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    reopened = HarnessService(Database(service.db.url), service.artifacts)
    assert reopened.get_record("experiment", experiment["id"], actor)["status"] == "queued"
    events = reopened.events(actor)
    assert any(e["kind"] == "experiment.queued" for e in events)
    assert any(o["kind"] == "experiment.queued" for o in reopened.pending_outbox())


def test_candidate_and_numerical_evidence_cannot_self_promote(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    with pytest.raises(HarnessError) as err:
        service.create_claim(experiment["id"], "Proved it", [], "verified", None, actor, "claim")
    assert err.value.code == "INVALID_EVIDENCE"
    claim = service.create_claim(
        experiment["id"], "Numerical agreement", [], "numerical", None, actor, "n"
    )
    assert claim["proof_status"] == "unproved"
    assert claim["novelty_status"] == "unreviewed"


def test_artifact_tampering_is_detected_before_returning_bytes(tmp_path):
    store = LocalArtifactStore(tmp_path)
    digest = store.put(b"honest proof")
    assert store.get(digest) == b"honest proof"
    store.path_for(digest).write_bytes(b"different proof")
    with pytest.raises(HarnessError) as err:
        store.get(digest)
    assert err.value.code == "ARTIFACT_INTEGRITY_ERROR"


def test_artifact_digest_cannot_traverse_paths(tmp_path):
    store = LocalArtifactStore(tmp_path)
    with pytest.raises(HarnessError) as err:
        store.get("../../secret")
    assert err.value.code == "INVALID_DIGEST"
