"""Read-only snapshot of records already authenticated by the canonical application.

This class validates relationships, not the authenticity of caller-created dictionaries.
Only trusted snapshot loaders may construct it; it must never accept public worker payloads.
"""

import hashlib
import json
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict

from physharness.verification import VerificationOutcome


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


class EvidenceValidation(BaseModel):
    model_config = ConfigDict(frozen=True)
    valid: bool
    reason: str
    problem_id: str
    receipt_id: str
    artifact_id: str | None = None
    candidate_sha256: str | None = None
    review_id: str | None = None


class CanonicalEvidence:
    def __init__(self, records: list[dict], *, snapshot_id: str):
        if not snapshot_id.strip():
            raise ValueError("canonical snapshot provenance is required")
        records = deepcopy(records)
        self._records = {}
        for record in records:
            key = record.get("id")
            if not key or key in self._records:
                raise ValueError("duplicate or missing canonical record id")
            self._records[key] = record
        self.snapshot_id = snapshot_id
        self.snapshot_digest = canonical_digest(sorted(records, key=lambda row: row["id"]))

    def record(self, identifier: str) -> dict:
        if identifier not in self._records:
            raise ValueError(f"canonical record missing: {identifier}")
        return deepcopy(self._records[identifier])

    def validate(
        self,
        problem_id: str,
        receipt_id: str,
        *,
        target_digest: str | None = None,
        environment_digest: str | None = None,
        experiment_id: str | None = None,
    ) -> EvidenceValidation:
        try:
            problem = self.record(problem_id)
            receipt = self.record(receipt_id)
            if problem["kind"] != "problem" or receipt["kind"] != "verification":
                raise ValueError("wrong canonical record kind")
            if receipt["problem_revision_id"] != problem_id:
                raise ValueError("receipt belongs to another target revision")
            if problem.get("semantic_review") != "approved" or problem.get(
                "definition_holes", True
            ):
                raise ValueError("target meaning/definitions are not approved")
            review = self.record(problem["review_id"])
            if (
                review["kind"] != "review"
                or review["decision"] != "approved"
                or review["scope"] != "target"
                or review["problem_id"] != problem_id
                or review["target_digest"] != problem["target_digest"]
                or receipt.get("review_id") != review["id"]
                or not review.get("reviewed_by")
            ):
                raise ValueError("semantic review does not approve the exact target")
            if (
                receipt.get("challenge_sha256")
                != hashlib.sha256(problem["formal_statement"].encode("utf-8")).hexdigest()
            ):
                raise ValueError("receipt challenge source mismatch")
            if receipt.get("target_theorem") != problem["target_theorem"]:
                raise ValueError("receipt selected theorem mismatch")
            for field, expected in (
                ("target_digest", target_digest),
                ("environment_digest", environment_digest),
            ):
                if receipt[field] != problem[field] or (expected and receipt[field] != expected):
                    raise ValueError(f"receipt {field} mismatch")
            artifact = self.record(receipt["artifact_id"])
            if (
                artifact["kind"] != "artifact"
                or artifact.get("artifact_kind") != "lean_source"
                or artifact["sha256"] != receipt["candidate_sha256"]
                or artifact["experiment_id"] != receipt["experiment_id"]
            ):
                raise ValueError("receipt artifact identity mismatch")
            if experiment_id and receipt["experiment_id"] != experiment_id:
                raise ValueError("receipt belongs to another experiment")
            project = problem["project_id"]
            if any(row["project_id"] != project for row in (receipt, artifact, review)):
                raise ValueError("cross-project evidence is forbidden")
            outcome = VerificationOutcome.model_validate(
                {key: receipt[key] for key in VerificationOutcome.model_fields if key in receipt}
            )
            if outcome.status != "verified":
                raise ValueError("receipt is not verified")
            if receipt.get("publication") and outcome.assurance != "independent_kernel":
                raise ValueError("publication receipt lacks independent kernel")
            return EvidenceValidation(
                valid=True,
                reason="exact reviewed target and receipt",
                problem_id=problem_id,
                receipt_id=receipt_id,
                artifact_id=artifact["id"],
                candidate_sha256=artifact["sha256"],
                review_id=review["id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            return EvidenceValidation(
                valid=False, reason=str(exc), problem_id=problem_id, receipt_id=receipt_id
            )
