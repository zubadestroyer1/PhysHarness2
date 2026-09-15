"""Submission and promotion authority. Public clients never provide verification outcomes."""

import logging

from .errors import HarnessError
from .verification import UnavailableVerifier, VerificationOutcome, VerificationRequest

log = logging.getLogger(__name__)


class AcceptanceMixin:
    def verify_candidate(self, experiment_id, artifact_id, publication, actor, key):
        self._research_role(actor)

        def action(session, op):
            experiment = self._get(session, "experiment", experiment_id, actor)
            problem = self._get(session, "problem", experiment.payload["problem_id"], actor)
            artifact = self._get(session, "artifact", artifact_id, actor)
            if artifact.payload.get("experiment_id") != experiment_id:
                raise HarnessError(
                    "ARTIFACT_EXPERIMENT_MISMATCH", "Candidate belongs to another experiment."
                )
            if artifact.payload["artifact_kind"] != "lean_source":
                raise HarnessError(
                    "CANDIDATE_FORMAT",
                    "Submit a Lean source artifact for proof verification.",
                    status=422,
                )
            self.artifacts.get(artifact.payload["sha256"])
            record = self._insert(
                session,
                "verification",
                actor,
                {
                    "experiment_id": experiment_id,
                    "problem_revision_id": problem.id,
                    "target_digest": experiment.payload["target_digest"],
                    "artifact_id": artifact_id,
                    "candidate_sha256": artifact.payload["sha256"],
                    "environment_digest": problem.payload["environment_digest"],
                    "publication": publication,
                    "status": "queued",
                    "assurance": "none",
                    "submitted_by": actor.id,
                    "checker_versions": {},
                    "axioms": [],
                },
            )
            self._event(
                session,
                actor,
                op,
                "verification.queued",
                record["id"],
                {"experiment_id": experiment_id},
                dispatch=True,
            )
            return record

        return self._execute(
            actor,
            key,
            "verification.submit",
            {
                "experiment_id": experiment_id,
                "artifact_id": artifact_id,
                "publication": publication,
            },
            action,
        )

    def process_verification(self, identifier, actor):
        if actor.role not in {"operator", "verifier", "admin"}:
            raise HarnessError(
                "FORBIDDEN", "Only the acceptance worker can process verification.", status=403
            )
        receipt = self.get_record("verification", identifier, actor)
        if receipt["status"] in {"verified", "blocked", "rejected"}:
            return receipt
        problem = self.get_record("problem", receipt["problem_revision_id"], actor)
        request = VerificationRequest(
            problem_revision_id=problem["id"],
            target_digest=problem["target_digest"],
            environment_digest=problem["environment_digest"],
            candidate_sha256=receipt["candidate_sha256"],
            candidate_source=self.artifact_content(receipt["artifact_id"], actor).decode("utf-8"),
            publication=receipt["publication"],
            semantic_reviewed=problem["semantic_review"] == "approved",
            definition_holes=problem["definition_holes"],
        )
        try:
            raw_outcome = (self.verifier or UnavailableVerifier()).verify(request)
            outcome = VerificationOutcome.model_validate(raw_outcome.model_dump())
            for field in ["target_digest", "environment_digest", "candidate_sha256"]:
                if getattr(outcome, field) != receipt[field]:
                    raise HarnessError(
                        "CHECKER_IDENTITY_MISMATCH",
                        "Checker outcome does not match submitted evidence.",
                    )
            if (
                receipt["publication"]
                and outcome.status == "verified"
                and outcome.assurance != "independent_kernel"
            ):
                raise HarnessError(
                    "ASSURANCE_DOWNGRADE",
                    "Publication requires successful independent kernel replay.",
                )
        except Exception as error:
            log.exception("Independent checker failed", extra={"operation_id": identifier})
            outcome = VerificationOutcome(
                status="blocked",
                assurance="none",
                code="checker_failed",
                message="The independent checker failed; no proof was accepted.",
                remediation="Inspect acceptance worker logs using the receipt ID.",
                target_digest=receipt["target_digest"],
                environment_digest=receipt["environment_digest"],
                candidate_sha256=receipt["candidate_sha256"],
                diagnostics={"exception_type": type(error).__name__},
            )
        if outcome.status != "verified":
            log.warning(
                "Proof not accepted: %s: %s",
                outcome.code,
                outcome.message,
                extra={"operation_id": identifier, "error_code": outcome.code},
            )

        def commit(session, op):
            row = self._get(session, "verification", identifier, actor)
            current = self._get(session, "problem", receipt["problem_revision_id"], actor)
            result = outcome.model_dump(mode="json")
            if (
                current.payload.get("review_id") != problem.get("review_id")
                or current.payload["target_digest"] != receipt["target_digest"]
            ):
                result.update(
                    status="blocked",
                    assurance="none",
                    code="review_changed",
                    message="Target review changed during verification; submit a fresh check.",
                )
            if row.payload["status"] != "queued":
                return row.payload
            record = self._replace(session, row, result)
            if result["status"] == "verified":
                claim = self._insert(
                    session,
                    "claim",
                    actor,
                    {
                        "experiment_id": receipt["experiment_id"],
                        "problem_revision_id": problem["id"],
                        "target_digest": receipt["target_digest"],
                        "statement": problem["formal_statement"],
                        "assumptions": problem["assumptions"],
                        "evidence": "formal_proof",
                        "proof_status": "verified",
                        "semantic_review": "approved",
                        "novelty_status": "unreviewed",
                        "verification_id": identifier,
                        "artifact_id": receipt["artifact_id"],
                        "assurance": result["assurance"],
                    },
                )
                record = self._replace(
                    session,
                    self._get(session, "verification", identifier, actor),
                    {"claim_id": claim["id"]},
                )
            self._event(
                session,
                actor,
                op,
                f"verification.{result['status']}",
                identifier,
                {"experiment_id": receipt["experiment_id"], "code": result["code"]},
            )
            return record

        return self._execute(
            actor,
            f"acceptance-result:{identifier}",
            "verification.process",
            {"receipt_id": identifier},
            commit,
        )
