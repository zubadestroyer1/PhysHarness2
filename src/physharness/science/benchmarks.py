"""Local benchmark registries; reference expectations never constitute qualification."""

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from physharness.errors import HarnessError
from physharness.knowledge.sources import Digest, Record


class BenchmarkTask(Record):
    id: str = Field(min_length=1)
    program: Literal["quantum", "classical"]
    family: str = Field(min_length=1)
    kind: Literal["candidate", "altered"]
    split: Literal["development", "holdout"]
    statement: str = Field(min_length=1)
    assumptions: list[str]
    provenance_uri: str = Field(min_length=1)
    provenance_sha256: Digest
    provenance_start_line: int = Field(ge=1)
    provenance_end_line: int = Field(ge=1)
    target_source: str = Field(min_length=1)
    candidate_source: str = Field(min_length=1)
    reference_expectation: Literal["should_verify", "must_not_verify"]
    reference_rationale: str = Field(min_length=1)
    altered_from: str | None = None
    attack: str | None = None
    review_status: Literal["pending", "approved", "rejected"] = "pending"
    review_decision_id: str | None = None
    compiler_status: Literal["not_run", "passed", "failed"] = "not_run"
    qualification_receipt_sha256: Digest | None = None
    environment_digest: Digest | None = None
    checker_versions: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent(self):
        if self.provenance_end_line < self.provenance_start_line:
            raise ValueError("invalid provenance line range")
        if self.kind == "altered" and (
            not self.altered_from
            or not self.attack
            or self.reference_expectation != "must_not_verify"
        ):
            raise ValueError("altered case requires parent, attack and negative expectation")
        if self.kind == "candidate" and (
            self.altered_from or self.attack or self.reference_expectation != "should_verify"
        ):
            raise ValueError("candidate metadata conflicts with reference expectation")
        return self


class BenchmarkRegistry(Record):
    version: Literal[1] = 1
    description: str
    tasks: list[BenchmarkTask] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def check_families(self):
        by_id = {t.id: t for t in self.tasks}
        if len(by_id) != len(self.tasks):
            raise ValueError("benchmark IDs must be unique")
        families = {}
        for task in self.tasks:
            if task.family in families and families[task.family] != task.split:
                raise ValueError("a benchmark family cannot cross development/holdout splits")
            families[task.family] = task.split
            if task.kind == "altered":
                original = by_id.get(task.altered_from)
                if (
                    original is None
                    or original.kind != "candidate"
                    or original.family != task.family
                    or original.program != task.program
                ):
                    raise ValueError("altered benchmark must reference its original family")
        return self

    def require_qualified(self) -> None:
        """Validate service-supplied qualification records; does not authenticate them."""
        pending = [
            t.id
            for t in self.tasks
            if (
                t.review_status != "approved"
                or not t.review_decision_id
                or t.compiler_status != "passed"
                or not t.qualification_receipt_sha256
                or not t.environment_digest
                or not all(t.checker_versions.get(name) for name in ("lean", "comparator"))
            )
        ]
        if pending:
            raise HarnessError(
                "benchmark_qualification_pending",
                "Benchmark qualification lacks expert review or independent checker evidence.",
                remediation="Have trusted review and verifier services record per-case evidence.",
                details={"pending_count": len(pending), "pending_ids": pending},
            )

    def discovery_tasks(self, split: Literal["development", "holdout"]) -> list[dict]:
        """Target-only export; do not expose this registry or sources file to benchmark workers."""
        if split not in {"development", "holdout"}:
            raise ValueError("unknown benchmark split")
        fields = {"id", "program", "family", "split", "statement", "assumptions", "target_source"}
        return [
            t.model_dump(include=fields)
            for t in self.tasks
            if t.split == split and t.kind == "candidate"
        ]


def load_benchmarks(path: Path) -> BenchmarkRegistry:
    if path.stat().st_size > 20_000_000:
        raise HarnessError("benchmark_registry_limit", "Benchmark registry exceeds 20 MB.")
    return BenchmarkRegistry.model_validate_json(path.read_bytes())
