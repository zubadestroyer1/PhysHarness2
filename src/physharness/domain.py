"""Typed scientific inputs; callers cannot supply acceptance or review status."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6, allow_inf_nan=False)]
Program = Literal["quantum", "classical"]


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class Principal(StrictModel):
    id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    role: Literal["researcher", "reviewer", "operator", "publisher", "verifier", "admin", "agent"]
    experiment_id: str | None = None
    branch_id: str | None = None
    agent_orchestrator: bool = False

    @model_validator(mode="after")
    def worker_scope(self):
        if self.role == "agent" and not self.experiment_id:
            raise ValueError("An agent identity requires an experiment scope")
        if self.agent_orchestrator and (self.role != "agent" or self.branch_id):
            raise ValueError("An orchestrator is an explicitly unscoped agent")
        if self.branch_id and not self.experiment_id:
            raise ValueError("A branch identity requires an experiment scope")
        return self


class CampaignCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=20000)
    programs: list[Program] = Field(min_length=1, max_length=2)


class ProblemCreate(StrictModel):
    campaign_id: str
    title: str = Field(min_length=1, max_length=200)
    program: Program
    informal_statement: str = Field(min_length=1, max_length=100000)
    formal_statement: str = Field(min_length=1, max_length=100000)
    assumptions: list[str] = Field(default_factory=list, max_length=1000)
    definitions: dict[str, str] = Field(default_factory=dict)
    source: str = Field(default="", max_length=20000)
    environment_digest: Digest
    target_theorem: str = Field(default="target", min_length=1, max_length=500)
    parent_revision_id: str | None = None
    definition_holes: bool = False


class ResourceEnvelope(StrictModel):
    max_cost_usd: Money
    max_concurrency: int = Field(ge=1, le=1_000_000)
    max_runtime_seconds: int = Field(ge=1, le=31_536_000)
    max_tokens: int | None = Field(default=None, ge=1)


class ModelConfiguration(StrictModel):
    runtime: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    parameters: dict[str, Any] = Field(default_factory=dict)


class LiteraturePolicy(StrictModel):
    mode: Literal["off", "open", "benchmark"] = "off"
    # arXiv ids, DOIs, domains or title fragments withheld from benchmark runs.
    blocked_sources: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=200
    )
    masked_reference_artifact_id: str | None = Field(default=None, min_length=1, max_length=36)
    overlap_threshold: float = Field(default=0.02, ge=0, le=1)


class ScaffoldingPolicy(StrictModel):
    playbook: bool = True
    skills: bool = True
    checkin_every_turns: int | None = Field(default=12, ge=2, le=200)
    stagnation_nudges: bool = True


class SocietyPolicy(StrictModel):
    """Immutable opt-in for the shared commons; absent means today's behaviour."""

    tool_profile: Literal["society"] = "society"
    claim_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    lab_size_max: int = Field(default=8, ge=1, le=32)
    cross_lab_direct_messages: bool = False
    referee_quorum: int = Field(default=1, ge=1, le=5)
    literature: LiteraturePolicy = Field(default_factory=LiteraturePolicy)
    scaffolding: ScaffoldingPolicy = Field(default_factory=ScaffoldingPolicy)


class ExperimentCreate(StrictModel):
    campaign_id: str
    problem_id: str
    models: list[ModelConfiguration] = Field(min_length=1, max_length=100)
    budget: ResourceEnvelope
    policy: str = Field(default="independent", min_length=1, max_length=100)
    mode: Literal["research", "discovery", "literature_assisted", "replay"] = "research"
    sharing: Literal["none", "verified", "ideas"] = "verified"
    runtime_limits: dict[str, Any] = Field(default_factory=dict)
    execution_profile: Literal["general", "formal-research"] = "general"
    context_profile: Literal["research", "stress8192"] = "research"
    society: SocietyPolicy | None = None

    @model_validator(mode="after")
    def society_scope(self):
        if self.society is None:
            return self
        if self.sharing != "ideas":
            raise ValueError("SOCIETY_REQUIRES_IDEAS: a society commons requires ideas sharing")
        literature = self.society.literature
        if literature.mode == "benchmark" and not literature.masked_reference_artifact_id:
            raise ValueError("Benchmark literature mode requires masked_reference_artifact_id")
        return self


class BranchCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=20000)
    relation: Literal["helper", "collaborator", "competing"] = "competing"
    parent_id: str | None = None
    checkpoint_id: str | None = None
    model_index: int | None = Field(default=None, ge=0, le=99)


class ArtifactCreate(StrictModel):
    experiment_id: str | None = None
    branch_id: str | None = None
    trusted_input: bool = False
    kind: str = Field(min_length=1, max_length=100)
    content: str = Field(max_length=5_000_000)
    media_type: str = Field(default="text/plain", max_length=200)
    provenance: dict[str, Any] = Field(default_factory=dict)


class TaskCreate(StrictModel):
    branch_id: str
    objective: str = Field(min_length=1, max_length=20000)
    dependency_ids: list[str] = Field(default_factory=list, max_length=1000)
    detached: bool = False
    # Optional free-form approach note for the assignee; never validated as mathematics.
    strategy: str | None = Field(default=None, max_length=500)


def make_record(kind: str, actor: Principal, data: dict[str, Any]) -> dict[str, Any]:
    return {
        **data,
        "id": new_id(),
        "kind": kind,
        "project_id": actor.project_id,
        "revision": 1,
        "created_at": utcnow().isoformat(),
    }
