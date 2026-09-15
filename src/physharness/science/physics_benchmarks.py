"""Versioned physics tasks; author estimates and references never constitute approval."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from physharness.domain import digest_json
from physharness.errors import HarnessError
from physharness.knowledge.sources import Record
from physharness.verification.boundary import safe_read

Text = Annotated[str, Field(min_length=1, max_length=30000, pattern=r"\S")]
Identifier = Annotated[
    str, Field(min_length=3, max_length=200, pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
]
Source = Annotated[str, Field(min_length=1, max_length=200000, pattern=r"\S")]
Split = Literal["development", "holdout"]
Program = Literal["quantum", "classical"]


class Provenance(Record):
    uri: Text
    locator: Text
    note: Text


class Shortcut(Record):
    declaration: Text
    note: Text


class PhysicsTask(Record):
    id: Identifier
    family: Text
    split: Split
    title: Text
    difficulty_band: Literal["foundation", "intermediate", "stretch"]
    difficulty_rationale: Text
    capabilities: list[Text] = Field(min_length=1, max_length=30)
    statement: Text
    assumptions: list[Text] = Field(max_length=100)
    physical_scope: Text
    provenance: list[Provenance] = Field(min_length=1, max_length=30)
    target_theorem: Annotated[str, Field(min_length=1, max_length=500)]
    target_source: Source
    reference_source: Source
    reference_outline: Text
    known_shortcuts: list[Shortcut] = Field(max_length=100)
    limitations: list[Text] = Field(min_length=1, max_length=30)


class NegativePhysicsCase(Record):
    id: Identifier
    parent_id: Identifier
    category: Text
    expected_outcome: Literal["kernel_nonacceptance", "semantic_hold"]
    target_source: Source
    candidate_source: Source
    rationale: Text
    required_diagnostics: list[Text] = Field(max_length=16)
    semantic_change: Text

    @model_validator(mode="after")
    def disposition(self):
        if self.expected_outcome == "kernel_nonacceptance" and not self.required_diagnostics:
            raise ValueError("Kernel nonacceptance requires causal diagnostic evidence")
        if self.expected_outcome == "semantic_hold" and self.required_diagnostics:
            raise ValueError("A semantic hold must not require a kernel failure diagnostic")
        return self


class PhysicsCollection(Record):
    version: Literal[1] = 1
    program: Program
    tasks: list[PhysicsTask] = Field(min_length=1, max_length=100)
    negative_cases: list[NegativePhysicsCase] = Field(max_length=100)


class PhysicsBenchmark(Record):
    collections: list[PhysicsCollection] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def identities(self):
        programs = set()
        ids = set()
        targets = set()
        families = {}
        for collection in self.collections:
            if collection.program in programs:
                raise ValueError("Duplicate program collection")
            programs.add(collection.program)
            parents = {task.id: task for task in collection.tasks}
            for task in collection.tasks:
                if task.id in ids or not task.id.startswith(collection.program + "."):
                    raise ValueError("Task identity is duplicated or has the wrong program")
                ids.add(task.id)
                if task.id.split(".")[1:-1] != [task.family]:
                    raise ValueError("Task identity must match program.family.slug")
                if task.target_source in targets:
                    raise ValueError("Benchmark contains duplicate target source")
                targets.add(task.target_source)
                key = (collection.program, task.family)
                if key in families and families[key] != task.split:
                    raise ValueError("A mathematical family crosses the holdout split")
                families[key] = task.split
            for case in collection.negative_cases:
                if case.id in ids or not case.id.startswith(collection.program + "."):
                    raise ValueError("Negative identity is duplicated or has the wrong program")
                ids.add(case.id)
                if case.parent_id not in parents:
                    raise ValueError("Negative case requires a parent in its program collection")
        return self

    def snapshot(self) -> PhysicsBenchmark:
        """Revalidate nested containers which Python callers can mutate despite frozen records."""
        return type(self).model_validate_json(self.model_dump_json())

    def revision_digest(self) -> str:
        return digest_json(self.snapshot().model_dump(mode="json"))

    def discovery_tasks(self, split: Split) -> list[dict]:
        if split not in {"development", "holdout"}:
            raise ValueError("Unknown discovery split")
        fields = {
            "id",
            "title",
            "statement",
            "assumptions",
            "physical_scope",
            "target_theorem",
            "target_source",
        }
        return [
            dict(task.model_dump(include=fields, mode="json"), program=collection.program)
            for collection in self.snapshot().collections
            for task in collection.tasks
            if task.split == split
        ]

    def inventory(self) -> dict:
        counts = {program: {"positive": 0, "negative": 0} for program in ["quantum", "classical"]}
        families = set()
        bands = Counter()
        splits = Counter()
        negative_types = Counter()
        flags = []
        for collection in self.snapshot().collections:
            counts[collection.program] = {
                "positive": len(collection.tasks),
                "negative": len(collection.negative_cases),
            }
            program_families = {task.family for task in collection.tasks}
            if len(program_families) < 4:
                flags.append(f"{collection.program}: fewer than four mathematical families")
            for task in collection.tasks:
                families.add((collection.program, task.family))
                bands[task.difficulty_band] += 1
                splits[task.split] += 1
            negative_types.update(case.expected_outcome for case in collection.negative_cases)
        return {
            "benchmark_sha256": self.revision_digest(),
            "counts": counts,
            "family_count": len(families),
            "difficulty_bands": dict(bands),
            "splits": dict(splits),
            "negative_outcomes": dict(negative_types),
            "quality_flags": flags,
            "required_inventory_complete": all(
                c == {"positive": 20, "negative": 10} for c in counts.values()
            ),
            "difficulty_status": "author_estimates_not_calibrated",
            "scientific_review": "pending",
            "production_qualified": False,
            "contamination_status": "not_ruled_out",
        }


def load_physics_benchmarks(paths: list[Path]) -> PhysicsBenchmark:
    try:
        if not 1 <= len(paths) <= 2:
            raise ValueError("Supply one or two program collections")
        collections = []
        for path in paths:
            path = Path(path)
            raw = safe_read(path.parent, path.name)
            if len(raw) > 16_000_000:
                raise ValueError("Physics collection exceeds16MB")
            collections.append(PhysicsCollection.model_validate_json(raw))
        return PhysicsBenchmark(collections=collections)
    except (ValueError, OSError) as error:
        raise HarnessError(
            "physics_benchmark_invalid",
            "Physics benchmark input is invalid.",
            details={"reason": str(error)[:2000]},
        ) from error
