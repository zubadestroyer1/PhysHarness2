"""Deterministic planning; the execution layer must enforce reservations and isolation."""

import hashlib
import math
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .evidence import CanonicalEvidence, canonical_digest

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Money = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Budget(Contract):
    max_cost_usd: Money
    max_wall_seconds: int = Field(gt=0)
    max_tokens: int = Field(gt=0)
    max_concurrency: int = Field(gt=0)


class TargetSpec(Contract):
    problem_id: str = Field(min_length=1)
    target_digest: Digest
    environment_digest: Digest
    family_id: str = Field(min_length=1)
    split: Literal["development", "holdout"]


class ArmSpec(Contract):
    id: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    model: str = Field(min_length=1)
    approach: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("model")
    @classmethod
    def exact_model(cls, value):
        if value.strip() != value or any(char.isspace() for char in value):
            raise ValueError("exact model identifier required")
        return value

    @model_validator(mode="after")
    def serializable(self):
        canonical_digest(self.parameters)
        return self


class InformationAccess(Contract):
    mode: Literal["discovery", "literature_assisted"] = "discovery"
    allowed_source_ids: list[str] = Field(default_factory=list)
    hidden_problem_ids: list[str] = Field(default_factory=list)
    leakage_manifest_digest: Digest | None = None


class EvaluationManifest(Contract):
    id: str = Field(min_length=1)
    mode: Literal["live", "replay", "synthetic"]
    seed: int = Field(ge=0)
    targets: list[TargetSpec] = Field(min_length=1, max_length=1000)
    arms: list[ArmSpec] = Field(min_length=1, max_length=100)
    envelope: Budget
    attempt_cost_usd: Money
    attempt_tokens: int = Field(gt=0)
    attempt_seconds: int = Field(gt=0)
    deep_attempt_seconds: int = Field(gt=0)
    repeats: int = Field(ge=1, le=1000)
    protected_per_arm: int = Field(default=1, ge=0)
    policy: Literal["uniform", "adaptive"] = "uniform"
    sharing: Literal["none", "verified", "attributed_ideas"] = "none"
    information: InformationAccess = Field(default_factory=InformationAccess)

    @model_validator(mode="after")
    def consistency(self):
        if (
            self.protected_per_arm > self.repeats
            or self.deep_attempt_seconds < self.attempt_seconds
        ):
            raise ValueError("protected attempts need valid repetition and depth reservations")
        if len({a.id for a in self.arms}) != len(self.arms):
            raise ValueError("duplicate arm ids")
        if len({t.problem_id for t in self.targets}) != len(self.targets):
            raise ValueError("duplicate target revisions")
        families = {}
        for target in self.targets:
            if target.family_id in families and families[target.family_id] != target.split:
                raise ValueError("family crosses development and holdout partitions")
            families[target.family_id] = target.split
        return self


class AttemptPlan(Contract):
    id: str
    manifest_id: str
    problem_id: str
    target_digest: Digest
    environment_digest: Digest
    arm_id: str
    runtime: str
    model: str
    approach: str
    parameters: dict[str, Any]
    repetition: int
    seed: int
    protected: bool
    max_cost_usd: Money
    max_tokens: int
    max_wall_seconds: int
    context_policy: Literal["fresh_independent", "explicit_shared"]


class AttemptObservation(Contract):
    attempt_id: str
    observed_model: str
    status: Literal["completed", "failed", "running"]
    cost_usd: Money
    wall_seconds: float = Field(ge=0)
    tokens: int = Field(ge=0)
    experiment_id: str
    receipt_id: str | None = None
    runtime_trace_digest: Digest | None = None


class AllocationDecision(Contract):
    attempt: AttemptPlan | None
    reason: str
    observations: int = 0
    empirical_success_rate: float | None = None
    uncertainty_radius: float | None = None


class PortfolioPlanner:
    def __init__(self, manifest: EvaluationManifest):
        self.manifest = EvaluationManifest.model_validate(manifest.model_dump())

    @property
    def capacity(self):
        m = self.manifest
        return len(m.targets) * len(m.arms) * m.repeats

    def plan(self) -> list[AttemptPlan]:
        m = self.manifest
        protected = len(m.targets) * len(m.arms) * m.protected_per_arm
        seconds = (
            protected * m.deep_attempt_seconds + (self.capacity - protected) * m.attempt_seconds
        )
        # Conservative serial wall budget: no promise of unrealized parallel speedup.
        if (
            self.capacity * m.attempt_cost_usd > m.envelope.max_cost_usd
            or self.capacity * m.attempt_tokens > m.envelope.max_tokens
            or seconds > m.envelope.max_wall_seconds
        ):
            raise ValueError("attempt reservations exceed the explicit experiment envelope")
        repeats = m.repeats if m.policy == "uniform" else m.repeats * len(m.arms)
        if repeats * len(m.arms) * len(m.targets) > 100_000:
            raise ValueError("candidate portfolio exceeds offline planning limit")
        result = []
        for target in m.targets:
            for repetition in range(repeats):
                for arm in m.arms:
                    identity = canonical_digest(
                        [m.id, m.seed, target.model_dump(), arm.model_dump(), repetition]
                    )
                    result.append(
                        AttemptPlan(
                            id=identity,
                            manifest_id=m.id,
                            problem_id=target.problem_id,
                            target_digest=target.target_digest,
                            environment_digest=target.environment_digest,
                            arm_id=arm.id,
                            runtime=arm.runtime,
                            model=arm.model,
                            approach=arm.approach,
                            parameters=arm.parameters,
                            repetition=repetition,
                            seed=int(identity[:16], 16),
                            protected=repetition < m.protected_per_arm,
                            max_cost_usd=m.attempt_cost_usd,
                            max_tokens=m.attempt_tokens,
                            max_wall_seconds=m.deep_attempt_seconds
                            if repetition < m.protected_per_arm
                            else m.attempt_seconds,
                            context_policy="fresh_independent"
                            if m.sharing == "none"
                            else "explicit_shared",
                        )
                    )
        return result

    def validate_history(self, plans, history):
        expected = {p.id: p for p in self.plan()}
        if {p.id: p for p in plans} != expected or len(plans) != len(expected):
            raise ValueError("attempt plan differs from the manifest")
        seen = set()
        traces = set()
        for observation in history:
            if observation.attempt_id not in expected or observation.attempt_id in seen:
                raise ValueError("unknown or duplicate attempt observation")
            seen.add(observation.attempt_id)
            if self.manifest.mode == "live" and not observation.runtime_trace_digest:
                raise ValueError("live evaluation requires canonical runtime trace provenance")
            if observation.runtime_trace_digest:
                if observation.runtime_trace_digest in traces:
                    raise ValueError("runtime trace reused across attempts")
                traces.add(observation.runtime_trace_digest)
            plan = expected[observation.attempt_id]
            if observation.observed_model != plan.model:
                raise ValueError("observed model differs from exact requested model")
            if (
                observation.cost_usd > plan.max_cost_usd
                or observation.tokens > plan.max_tokens
                or observation.wall_seconds > plan.max_wall_seconds
            ):
                raise ValueError("attempt exceeded reserved envelope; comparison is invalid")
        if len(history) > self.capacity:
            raise ValueError("observations exceed funded attempt capacity")
        return expected

    def select_next(self, plans, history, evidence: CanonicalEvidence) -> AllocationDecision:
        expected = self.validate_history(plans, history)
        if len(history) >= self.capacity:
            return AllocationDecision(attempt=None, reason="funded attempt capacity exhausted")
        if sum(o.status == "running" for o in history) >= self.manifest.envelope.max_concurrency:
            return AllocationDecision(attempt=None, reason="concurrency reservation exhausted")
        used = {o.attempt_id for o in history}
        available = [p for p in plans if p.id not in used]
        protected = [p for p in available if p.protected]
        if protected:
            return AllocationDecision(
                attempt=protected[0], reason="reserved protected deep attempt"
            )
        if self.manifest.policy == "uniform":
            return AllocationDecision(
                attempt=available[0], reason="uniform repeated independent baseline"
            )
        counts = {arm.id: [0, 0] for arm in self.manifest.arms}
        credited_receipts = set()
        for obs in history:
            if obs.status == "running":
                continue
            p = expected[obs.attempt_id]
            counts[p.arm_id][0] += 1
            if (
                obs.status == "completed"
                and obs.receipt_id
                and obs.receipt_id not in credited_receipts
                and evidence.validate(
                    p.problem_id,
                    obs.receipt_id,
                    target_digest=p.target_digest,
                    environment_digest=p.environment_digest,
                    experiment_id=obs.experiment_id,
                ).valid
            ):
                counts[p.arm_id][1] += 1
                credited_receipts.add(obs.receipt_id)
        total = sum(n for n, _ in counts.values())

        def priority(p):
            n, wins = counts[p.arm_id]
            return float("inf") if n == 0 else wins / n + math.sqrt(2 * math.log(max(2, total)) / n)

        selected = max(available, key=priority)
        n, wins = counts[selected.arm_id]
        return AllocationDecision(
            attempt=selected,
            reason="UCB exploration from observed receipt outcomes",
            observations=n,
            empirical_success_rate=wins / n if n else None,
            uncertainty_radius=math.sqrt(2 * math.log(max(2, total)) / n) if n else None,
        )

    @staticmethod
    def cancellable(attempt_ids, plans):
        by_id = {p.id: p for p in plans}
        if set(attempt_ids) - by_id.keys():
            raise ValueError("unknown attempt id")
        return [identifier for identifier in attempt_ids if not by_id[identifier].protected]


class SharedItem(Contract):
    id: str
    source_id: str
    kind: Literal["verified_proof", "idea"]
    text: str
    problem_ids: list[str]
    author: str = ""
    receipt_id: str | None = None
    evidence_label: Literal["unverified_idea", "verified_dependency"] = "unverified_idea"


def shared_context(manifest, items, evidence):
    if manifest.sharing == "none":
        return []
    hidden = set(manifest.information.hidden_problem_ids)
    if manifest.information.mode == "discovery":
        hidden.update(t.problem_id for t in manifest.targets)
    allowed = set(manifest.information.allowed_source_ids)
    result = []
    for item in items:
        if item.source_id not in allowed or hidden.intersection(item.problem_ids):
            continue
        if item.kind == "verified_proof":
            if len(item.problem_ids) != 1 or not item.receipt_id:
                continue
            checked = evidence.validate(item.problem_ids[0], item.receipt_id)
            if (
                checked.valid
                and hashlib.sha256(item.text.encode()).hexdigest() == checked.candidate_sha256
            ):
                result.append(item.model_copy(update={"evidence_label": "verified_dependency"}))
        elif manifest.sharing == "attributed_ideas" and item.author.strip():
            result.append(item.model_copy(update={"evidence_label": "unverified_idea"}))
    return result
