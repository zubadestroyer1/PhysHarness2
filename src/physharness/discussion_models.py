"""Bounded, attributed research-board inputs. No model-supplied proof status."""

from typing import Literal

from pydantic import Field, model_validator

from .domain import StrictModel


class DiscussionCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4000)
    branch_id: str | None = None


class DiscussionPostCreate(StrictModel):
    kind: Literal[
        "question", "finding", "objection", "help", "update", "synthesis", "attempt_failed"
    ]
    content: str = Field(min_length=1, max_length=12000)
    # Optional structured header; omitted from stored payloads and fingerprints when None.
    abstract: str | None = Field(default=None, max_length=600)
    reply_to_post_id: str | None = None
    artifact_ids: list[str] = Field(default_factory=list, max_length=12)
    reference_post_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_references(self):
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("Artifact references must be unique")
        if len(set(self.reference_post_ids)) != len(self.reference_post_ids):
            raise ValueError("Post references must be unique")
        if not self.content.strip():
            raise ValueError("A post needs substantive content")
        return self
