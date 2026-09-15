"""Reproducible descriptive metrics; uncertainty is not a qualification claim."""

import math
import random
from decimal import Decimal
from statistics import NormalDist

from pydantic import Field

from .evidence import canonical_digest
from .portfolio import Contract, PortfolioPlanner


def wilson_interval(successes: int, total: int, confidence: float = 0.95):
    if total <= 0 or successes < 0 or successes > total or not 0 < confidence < 1:
        raise ValueError("invalid binomial interval input")
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def paired_bootstrap(differences: list[float], *, seed=0, samples=2000, confidence=0.95):
    if not differences or samples < 100 or not 0 < confidence < 1:
        raise ValueError("bootstrap requires cases, >=100 samples and a valid confidence")
    if not all(math.isfinite(x) for x in differences):
        raise ValueError("nonfinite observations")
    rng = random.Random(seed)
    values = sorted(
        sum(rng.choice(differences) for _ in differences) / len(differences) for _ in range(samples)
    )
    alpha = (1 - confidence) / 2
    return values[int(alpha * (samples - 1))], values[int((1 - alpha) * (samples - 1))]


class EvaluationSummary(Contract):
    manifest_id: str
    manifest_digest: str
    matched_signature: str
    mode: str
    snapshot_digest: str
    solved: int
    total_targets: int
    solved_by_target: dict[str, bool]
    target_families: dict[str, str]
    total_cost_usd: Decimal
    elapsed_seconds: float
    total_tokens: int
    interval_low: float
    interval_high: float
    interval_method: str = "Wilson 95%; descriptive target independence assumption"
    invalid_evidence: dict[str, str] = Field(default_factory=dict)
    completed_attempts: int
    planned_capacity: int


def summarize(manifest, plans, observations, evidence, *, elapsed_seconds):
    planner = PortfolioPlanner(manifest)
    expected = planner.validate_history(plans, observations)
    if (
        not math.isfinite(elapsed_seconds)
        or not 0 <= elapsed_seconds <= manifest.envelope.max_wall_seconds
    ):
        raise ValueError("wall-clock envelope exceeded or invalid")
    durations = [o.wall_seconds for o in observations]
    minimum_elapsed = max(
        max(durations, default=0),
        math.fsum(durations) / manifest.envelope.max_concurrency,
    )
    if elapsed_seconds < minimum_elapsed:
        raise ValueError("elapsed time contradicts attempt durations or concurrency capacity")
    total_cost = sum((o.cost_usd for o in observations), Decimal(0))
    total_tokens = sum(o.tokens for o in observations)
    if total_cost > manifest.envelope.max_cost_usd or total_tokens > manifest.envelope.max_tokens:
        raise ValueError("aggregate experiment envelope exceeded")
    if any(o.status == "running" for o in observations):
        raise ValueError("cannot finalize evaluation while attempts are running")
    solved = {target.problem_id: False for target in manifest.targets}
    invalid = {}
    credited_receipts = set()
    for obs in observations:
        if obs.status != "completed" or not obs.receipt_id:
            continue
        p = expected[obs.attempt_id]
        checked = evidence.validate(
            p.problem_id,
            obs.receipt_id,
            target_digest=p.target_digest,
            environment_digest=p.environment_digest,
            experiment_id=obs.experiment_id,
        )
        if checked.valid and obs.receipt_id in credited_receipts:
            invalid[obs.attempt_id] = "receipt reused across attempts"
        elif checked.valid:
            credited_receipts.add(obs.receipt_id)
            solved[p.problem_id] = True
        else:
            invalid[obs.attempt_id] = checked.reason
    low, high = wilson_interval(sum(solved.values()), len(solved))
    matched = canonical_digest(
        {
            "targets": sorted(
                [t.model_dump() for t in manifest.targets], key=lambda t: t["problem_id"]
            ),
            "envelope": manifest.envelope.model_dump(mode="json"),
            "information": manifest.information.model_dump(),
            "mode": manifest.mode,
        }
    )
    return EvaluationSummary(
        manifest_id=manifest.id,
        manifest_digest=canonical_digest(manifest.model_dump(mode="json")),
        matched_signature=matched,
        mode=manifest.mode,
        snapshot_digest=evidence.snapshot_digest,
        solved=sum(solved.values()),
        total_targets=len(solved),
        solved_by_target=solved,
        target_families={t.problem_id: t.family_id for t in manifest.targets},
        total_cost_usd=total_cost,
        elapsed_seconds=elapsed_seconds,
        total_tokens=total_tokens,
        interval_low=low,
        interval_high=high,
        invalid_evidence=invalid,
        completed_attempts=len(observations),
        planned_capacity=planner.capacity,
    )


class Comparison(Contract):
    left_manifest: str
    right_manifest: str
    mode: str
    difference: float
    interval_low: float
    interval_high: float
    method: str = "paired family-cluster bootstrap of solved fractions; left minus right"
    seed: int
    samples: int
    matched_envelopes: bool = True
    matching: str
    actual_cost_difference_usd: Decimal
    actual_wall_difference_seconds: float


def compare(left, right, *, seed=0, samples=2000, matching="actual"):
    if left.matched_signature != right.matched_signature:
        raise ValueError(
            "comparison requires matched targets, envelopes, information access and mode"
        )
    if matching not in {"actual", "envelope"}:
        raise ValueError("matching must be actual or envelope")
    if matching == "actual" and (
        left.total_cost_usd != right.total_cost_usd or left.elapsed_seconds != right.elapsed_seconds
    ):
        raise ValueError("actual-cost comparison requires matched spending and wall-clock exposure")
    families = {}
    for key in left.solved_by_target:
        families.setdefault(left.target_families[key], []).append(
            int(left.solved_by_target[key]) - int(right.solved_by_target[key])
        )
    # Equal family weights avoid pseudo-replication by many near-duplicate targets.
    differences = [sum(values) / len(values) for values in families.values()]
    low, high = paired_bootstrap(differences, seed=seed, samples=samples)
    return Comparison(
        left_manifest=left.manifest_digest,
        right_manifest=right.manifest_digest,
        mode=left.mode,
        matching=matching,
        difference=sum(differences) / len(differences),
        interval_low=low,
        interval_high=high,
        seed=seed,
        samples=samples,
        actual_cost_difference_usd=left.total_cost_usd - right.total_cost_usd,
        actual_wall_difference_seconds=left.elapsed_seconds - right.elapsed_seconds,
    )
