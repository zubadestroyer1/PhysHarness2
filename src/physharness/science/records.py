"""Evidence contracts deliberately separate computation from formal acceptance."""

from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import Field, model_validator

from physharness.knowledge.sources import Digest, Record, sha


class LeanObligation(Record):
    source: str
    source_sha256: Digest
    required_imports: list[str] = Field(default_factory=lambda: ["Mathlib"])
    status: Literal["uncompiled"] = "uncompiled"
    variable_mapping: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bind_source(self):
        if sha(self.source) != self.source_sha256:
            raise ValueError("Lean obligation source digest mismatch")
        return self


class ComputationResult(Record):
    status: Literal["checked_computation", "refuted", "blocked"]
    code: str
    message: str
    remediation: str
    input_sha256: Digest | None
    proof_status: Literal["not_lean_proof"] = "not_lean_proof"
    obligation: LeanObligation | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class NumericalRecord(Record):
    quantity: str = Field(min_length=1, max_length=1000)
    value: str = Field(min_length=1, max_length=1024)
    absolute_error: str | None = Field(default=None, min_length=1, max_length=1024)
    precision_bits: int = Field(ge=1, le=1_000_000)
    method: str = Field(min_length=1, max_length=10000)
    seed: int | None
    input_sha256: Digest
    environment_digest: Digest
    tool_versions: dict[str, str]
    assumptions: list[str]
    units: str = "dimensionless"
    error_interpretation: Literal["reported_bound", "estimate", "unknown"] = "estimate"
    evidence_kind: Literal["numerical_observation"] = "numerical_observation"

    @model_validator(mode="after")
    def finite_values(self):
        try:
            value = Decimal(self.value)
            error = Decimal(self.absolute_error) if self.absolute_error is not None else None
        except InvalidOperation as exc:
            raise ValueError("numerical values must be decimal strings") from exc
        if not value.is_finite() or (error is not None and (not error.is_finite() or error < 0)):
            raise ValueError("numerical value must be finite and its error nonnegative")
        if (error is None) != (self.error_interpretation == "unknown"):
            raise ValueError("unknown error must be explicit; bounds and estimates need a value")
        if not self.tool_versions or any(not k or not v for k, v in self.tool_versions.items()):
            raise ValueError("reproduction requires nonempty tool version provenance")
        return self
