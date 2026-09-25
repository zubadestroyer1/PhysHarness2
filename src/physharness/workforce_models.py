"""Bounded requests for research portfolio, recruitment and public discovery."""

from typing import Literal

from pydantic import Field, model_validator

from .domain import StrictModel

# Society lab names: generated as "lab-" + branch id prefix, or chosen from existing labs.
LAB_PATTERN = r"^[a-z0-9-]{1,40}$"


class ConfigureWorkforceRequest(StrictModel):
    max_total_tasks: int = Field(ge=1, le=100_000)
    max_pending_tasks: int = Field(ge=1, le=100_000)
    expected_revision: int | None = Field(default=None, ge=1)
    synthesis_interval_posts: int = Field(default=0, ge=0, le=100)

    @model_validator(mode="after")
    def valid_caps(self):
        if self.max_pending_tasks > self.max_total_tasks:
            raise ValueError("max_pending_tasks cannot exceed max_total_tasks")
        if 0 < self.synthesis_interval_posts < 4:
            raise ValueError("synthesis_interval_posts must be zero or at least four")
        return self


class PortfolioRoot(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=20_000)
    model_index: int | None = Field(default=None, ge=0, le=99)
    public_summary: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def nonblank(self):
        if not self.title.strip() or not self.objective.strip():
            raise ValueError("title and objective must contain text")
        if self.public_summary is not None and not self.public_summary.strip():
            raise ValueError("public_summary must contain text")
        return self


class SeedPortfolioRequest(StrictModel):
    roots: list[PortfolioRoot] = Field(min_length=1, max_length=32)


class RecruitResearcherRequest(StrictModel):
    parent_branch_id: str
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=20_000)
    relation: Literal["helper", "collaborator", "competing"] = "collaborator"
    model_index: int | None = Field(default=None, ge=0, le=99)
    discussion_refs: list[str] = Field(default_factory=list, max_length=20)
    synthesis: bool = False
    detached: bool = False
    public_summary: str | None = Field(default=None, max_length=1000)
    # Society experiments only: None joins the parent's lab, "new" founds a lab,
    # any other value names an existing lab. Omitted from fingerprints when None.
    lab: str | None = Field(default=None, pattern=LAB_PATTERN)

    @model_validator(mode="after")
    def nonblank(self):
        if not self.title.strip() or not self.objective.strip():
            raise ValueError("title and objective must contain text")
        if self.public_summary is not None and not self.public_summary.strip():
            raise ValueError("public_summary must contain text")
        return self


class PublishResearchProfileRequest(StrictModel):
    branch_id: str
    published: bool
    summary: str = Field(default="", max_length=1000)
    interests: list[str] = Field(default_factory=list, max_length=12)
    assignment: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def valid_text(self):
        if self.published and not self.summary.strip():
            raise ValueError("published profile requires summary")
        if any(not item.strip() or len(item) > 100 for item in self.interests):
            raise ValueError("interests must be nonblank and at most 100 characters each")
        return self


class JoinResearchTeamRequest(StrictModel):
    branch_id: str
    team: str = Field(min_length=1, max_length=100)
    joined: bool = True


class RequestResearchCapacityRequest(StrictModel):
    branch_id: str
    requested_workers: int = Field(ge=1, le=1000)
    rationale: str = Field(min_length=1, max_length=1000)
