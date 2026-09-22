"""Synthetic local planning/evidence tests, never live experiment qualification."""

import hashlib
from decimal import Decimal

import pytest


def api():
    from physharness import evaluation

    assert hasattr(evaluation, "PortfolioPlanner"), "evaluation primitives are absent"
    return evaluation


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def records(problem_id="p1", target="target", family="f1"):
    digest = sha(target)
    return [
        {
            "id": problem_id,
            "kind": "problem",
            "project_id": "project",
            "target_digest": digest,
            "environment_digest": sha("env"),
            "semantic_review": "approved",
            "review_id": f"review-{problem_id}",
            "formal_statement": target,
            "target_theorem": "target",
            "definition_holes": False,
        },
        {
            "id": f"review-{problem_id}",
            "kind": "review",
            "project_id": "project",
            "problem_id": problem_id,
            "target_digest": digest,
            "scope": "target",
            "decision": "approved",
            "reviewed_by": "expert",
        },
        {
            "id": f"artifact-{problem_id}",
            "kind": "artifact",
            "project_id": "project",
            "sha256": sha("proof"),
            "artifact_kind": "lean_source",
            "experiment_id": f"experiment-{problem_id}",
        },
        {
            "id": f"receipt-{problem_id}",
            "kind": "verification",
            "project_id": "project",
            "problem_revision_id": problem_id,
            "target_digest": digest,
            "candidate_sha256": sha("proof"),
            "challenge_sha256": sha(target),
            "review_id": f"review-{problem_id}",
            "target_theorem": "target",
            "environment_digest": sha("env"),
            "artifact_id": f"artifact-{problem_id}",
            "experiment_id": f"experiment-{problem_id}",
            "status": "verified",
            "assurance": "kernel",
            "code": "kernel_checked",
            "message": "Synthetic test record",
            "remediation": "",
            "checker_versions": {"lean": "test-pin", "comparator": "test-pin"},
            "axioms": [],
        },
    ]


def evidence(items=None):
    return api().CanonicalEvidence(items or records(), snapshot_id="synthetic-test-snapshot")


def manifest(**updates):
    v = api()
    values = dict(
        id="m1",
        mode="synthetic",
        seed=7,
        targets=[
            v.TargetSpec(
                problem_id="p1",
                target_digest=sha("target"),
                environment_digest=sha("env"),
                family_id="f1",
                split="development",
            )
        ],
        arms=[
            v.ArmSpec(id="a", runtime="runtime", model="exact-model-1", approach="direct"),
            v.ArmSpec(id="b", runtime="runtime", model="exact-model-2", approach="decompose"),
        ],
        envelope=v.Budget(
            max_cost_usd=Decimal("8"), max_wall_seconds=400, max_tokens=8000, max_concurrency=2
        ),
        attempt_cost_usd=Decimal("1"),
        attempt_tokens=1000,
        attempt_seconds=40,
        deep_attempt_seconds=80,
        repeats=2,
        protected_per_arm=1,
        policy="uniform",
        sharing="none",
        information=v.InformationAccess(mode="discovery"),
    )
    values.update(updates)
    return v.EvaluationManifest(**values)


def observation(plan, receipt_id=None, **updates):
    values = dict(
        attempt_id=plan.id,
        observed_model=plan.model,
        status="completed",
        cost_usd=Decimal("0.5"),
        wall_seconds=20,
        tokens=400,
        receipt_id=receipt_id,
        experiment_id="experiment-p1",
    )
    values.update(updates)
    return api().AttemptObservation(**values)


def test_uniform_attempts_are_reproducible_and_diverse():
    plan = api().PortfolioPlanner(manifest()).plan()
    assert plan == api().PortfolioPlanner(manifest()).plan()
    assert len(plan) == 4 and len({p.seed for p in plan}) == 4
    assert {p.model for p in plan} == {"exact-model-1", "exact-model-2"}
    assert sum(p.protected for p in plan) == 2
    assert all(p.max_wall_seconds == 80 for p in plan if p.protected)


def test_planner_rejects_unfunded_protected_attempts():
    with pytest.raises(ValueError, match="envelope"):
        api().PortfolioPlanner(
            manifest(
                envelope=api().Budget(
                    max_cost_usd=Decimal("1"),
                    max_wall_seconds=100,
                    max_tokens=1000,
                    max_concurrency=1,
                )
            )
        ).plan()


def test_receipt_binding_and_review_are_required():
    assert evidence().validate("p1", "receipt-p1").valid
    for field, value in [
        ("target_digest", sha("other")),
        ("environment_digest", sha("other")),
        ("status", "blocked"),
        ("candidate_sha256", sha("other")),
    ]:
        rows = records()
        rows[-1][field] = value
        assert not evidence(rows).validate("p1", "receipt-p1").valid
    rows = records()
    rows[1]["decision"] = "rejected"
    assert not evidence(rows).validate("p1", "receipt-p1").valid


def test_solved_counts_targets_not_repeated_attempts():
    m = manifest()
    plans = api().PortfolioPlanner(m).plan()
    observations = [observation(p, "receipt-p1") for p in plans]
    summary = api().summarize(m, plans, observations, evidence(), elapsed_seconds=80)
    assert summary.solved == 1 and summary.total_targets == 1
    assert summary.total_cost_usd == Decimal("2") and summary.mode == "synthetic"
    assert 0 <= summary.interval_low <= summary.interval_high <= 1


def test_model_substitution_and_foreign_receipts_do_not_count():
    m = manifest()
    plans = api().PortfolioPlanner(m).plan()
    with pytest.raises(ValueError, match="model"):
        api().summarize(
            m,
            plans,
            [observation(plans[0], "receipt-p1", observed_model="other")],
            evidence(),
            elapsed_seconds=80,
        )
    result = api().summarize(
        m,
        plans,
        [observation(plans[0], "receipt-p1", experiment_id="foreign")],
        evidence(),
        elapsed_seconds=80,
    )
    assert result.solved == 0 and result.invalid_evidence


def test_comparisons_require_matched_budget_and_mode():
    v = api()
    m = manifest()
    plans = v.PortfolioPlanner(m).plan()
    summary = v.summarize(
        m, plans, [observation(plans[0], "receipt-p1")], evidence(), elapsed_seconds=80
    )
    replay = m.model_copy(update={"mode": "replay"})
    other = v.summarize(replay, plans, [], evidence(), elapsed_seconds=80)
    with pytest.raises(ValueError, match="matched"):
        v.compare(summary, other, seed=11)
    same = v.compare(summary, summary, seed=11)
    assert same == v.compare(summary, summary, seed=11)
    assert same.difference == 0 and same.interval_low == same.interval_high == 0


def test_adaptive_selection_uses_observations_and_preserves_deep_attempts():
    v = api()
    m = manifest(policy="adaptive")
    planner = v.PortfolioPlanner(m)
    plans = planner.plan()
    selected = planner.select_next(plans, [], evidence())
    assert selected.attempt.protected and selected.empirical_success_rate is None
    history = [observation(selected.attempt)]
    next_choice = planner.select_next(plans, history, evidence())
    assert next_choice.attempt.protected
    assert planner.cancellable([p.id for p in plans], plans) == [
        p.id for p in plans if not p.protected
    ]


def test_sharing_hides_discovery_targets_and_requires_attribution():
    v = api()
    m = manifest(
        sharing="attributed_ideas",
        information=v.InformationAccess(mode="discovery", allowed_source_ids=["source"]),
    )
    items = [
        v.SharedItem(
            id="i1",
            source_id="source",
            kind="idea",
            text="idea",
            author="agent",
            problem_ids=["p1"],
        ),
        v.SharedItem(
            id="i2",
            source_id="source",
            kind="idea",
            text="idea",
            author="agent",
            problem_ids=["unrelated"],
        ),
    ]
    shared = v.shared_context(m, items, evidence())
    assert [item.id for item in shared] == ["i2"] and shared[0].evidence_label == "unverified_idea"
    assert not v.shared_context(m.model_copy(update={"sharing": "none"}), items, evidence())


def test_family_holdout_cannot_overlap_development():
    v = api()
    with pytest.raises(ValueError, match="family"):
        manifest(
            targets=[
                v.TargetSpec(
                    problem_id="p1",
                    target_digest=sha("target"),
                    environment_digest=sha("env"),
                    family_id="same",
                    split="development",
                ),
                v.TargetSpec(
                    problem_id="p2",
                    target_digest=sha("target2"),
                    environment_digest=sha("env"),
                    family_id="same",
                    split="holdout",
                ),
            ]
        )


def test_verified_sharing_binds_actual_proof_text():
    v = api()
    m = manifest(
        sharing="verified",
        information=v.InformationAccess(mode="literature_assisted", allowed_source_ids=["source"]),
    )
    forged = v.SharedItem(
        id="i",
        source_id="source",
        kind="verified_proof",
        text="forged",
        problem_ids=["p1"],
        receipt_id="receipt-p1",
    )
    assert v.shared_context(m, [forged], evidence()) == []


def test_actual_cost_comparison_rejects_unmatched_spending():
    v = api()
    m = manifest()
    plans = v.PortfolioPlanner(m).plan()
    first = v.summarize(m, plans, [observation(plans[0])], evidence(), elapsed_seconds=80)
    second = v.summarize(
        m, plans, [observation(plans[0], cost_usd=Decimal("0.7"))], evidence(), elapsed_seconds=80
    )
    with pytest.raises(ValueError, match="matched"):
        v.compare(first, second)


def test_live_evaluation_requires_trace_provenance():
    v = api()
    m = manifest(mode="live")
    plans = v.PortfolioPlanner(m).plan()
    with pytest.raises(ValueError, match="trace"):
        v.summarize(m, plans, [observation(plans[0])], evidence(), elapsed_seconds=80)


def test_same_receipt_cannot_reward_multiple_independent_attempts():
    v = api()
    m = manifest()
    plans = v.PortfolioPlanner(m).plan()
    result = v.summarize(
        m,
        plans,
        [observation(plans[0], "receipt-p1"), observation(plans[1], "receipt-p1")],
        evidence(),
        elapsed_seconds=80,
    )
    assert result.solved == 1
    assert result.invalid_evidence[plans[1].id] == "receipt reused across attempts"


@pytest.mark.parametrize("durations,elapsed", [([20], 0), ([20], 19), ([20, 20, 20, 20], 30)])
def test_elapsed_cannot_contradict_attempt_durations_or_concurrency(durations, elapsed):
    v = api()
    m = manifest()
    plans = v.PortfolioPlanner(m).plan()
    observations = [
        observation(p, wall_seconds=duration) for p, duration in zip(plans, durations, strict=False)
    ]
    with pytest.raises(ValueError, match="elapsed.*duration"):
        v.summarize(m, plans, observations, evidence(), elapsed_seconds=elapsed)


def test_elapsed_accepts_parallel_attempts_within_capacity():
    v = api()
    m = manifest()
    plans = v.PortfolioPlanner(m).plan()
    observations = [observation(p, wall_seconds=20) for p in plans]
    assert v.summarize(m, plans, observations, evidence(), elapsed_seconds=40).elapsed_seconds == 40


@pytest.mark.parametrize(
    "field,value",
    [("challenge_sha256", "f" * 64), ("review_id", "stale"), ("target_theorem", "other")],
)
def test_canonical_evidence_requires_source_review_and_theorem(field, value):
    rows = records()
    rows[-1][field] = value
    assert not evidence(rows).validate("p1", "receipt-p1").valid
