"""Submission and promotion authority. Public clients never provide verification outcomes."""

import logging

from .errors import HarnessError
from .verification import UnavailableVerifier, VerificationOutcome, VerificationRequest
from .verification.boundary import MAX_CANDIDATE_CHARACTERS, digest, preflight

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
            if experiment.payload["target_digest"] != problem.payload["target_digest"]:
                raise HarnessError(
                    "TARGET_CHANGED", "Experiment target no longer matches its revision."
                )
            try:
                source = self.artifacts.get(artifact.payload["sha256"]).decode("utf-8")
            except UnicodeError as error:
                raise HarnessError(
                    "CANDIDATE_FORMAT", "Candidate must be valid UTF-8 Lean source.", status=422
                ) from error
            self._check_candidate_size(source)
            record = self._insert(
                session,
                "verification",
                actor,
                {
                    "experiment_id": experiment_id,
                    "problem_revision_id": problem.id,
                    "target_digest": experiment.payload["target_digest"],
                    "challenge_sha256": digest(problem.payload["formal_statement"].encode("utf-8")),
                    "review_id": problem.payload.get("review_id"),
                    "target_theorem": problem.payload.get("target_theorem", "target"),
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
        incompatible_receipt = any(
            field not in receipt for field in ("challenge_sha256", "review_id", "target_theorem")
        )
        try:
            if incompatible_receipt:
                raise HarnessError(
                    "VERIFICATION_RECEIPT_INCOMPATIBLE",
                    "This receipt predates source and review binding; submit a fresh verification.",
                )
            if self._verification_revision_changed(problem, receipt):
                raise HarnessError("REVIEW_CHANGED", "Target review changed; submit a fresh check.")
            try:
                source = self.artifact_content(receipt["artifact_id"], actor).decode("utf-8")
            except (OSError, UnicodeError, HarnessError) as error:
                raise HarnessError(
                    "CANDIDATE_UNAVAILABLE",
                    "Exact candidate bytes could not be read as UTF-8.",
                    remediation="Restore the pinned artifact and submit a fresh verification.",
                ) from error
            self._check_candidate_size(source)
            request = VerificationRequest(
                problem_revision_id=problem["id"],
                target_theorem=problem.get("target_theorem", "target"),
                target_digest=receipt["target_digest"],
                challenge_sha256=receipt["challenge_sha256"],
                environment_digest=receipt["environment_digest"],
                candidate_sha256=receipt["candidate_sha256"],
                candidate_source=source,
                publication=receipt["publication"],
                semantic_reviewed=problem["semantic_review"] == "approved",
                definition_holes=problem["definition_holes"],
            )
            outcome = preflight(request)
            if outcome is None:
                review = self.get_record("review", receipt["review_id"], actor)
                if any(
                    (
                        review.get("problem_id") != problem["id"],
                        review.get("target_digest") != receipt["target_digest"],
                        review.get("decision") != "approved",
                        review.get("scope") != "target",
                    )
                ):
                    raise HarnessError(
                        "REVIEW_INVALID", "Review does not approve this target revision."
                    )
                raw_outcome = (self.verifier or UnavailableVerifier()).verify(request)
                outcome = VerificationOutcome.model_validate(raw_outcome.model_dump())
            for field in [
                "target_digest",
                "challenge_sha256",
                "environment_digest",
                "candidate_sha256",
            ]:
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
            known = isinstance(error, HarnessError)
            outcome = VerificationOutcome(
                status="blocked",
                assurance="none",
                code=error.code.lower() if known else "checker_failed",
                message=error.message
                if known
                else "The independent checker failed; no proof was accepted.",
                remediation=error.remediation
                if known
                else "Inspect acceptance worker logs using the receipt ID.",
                target_digest=receipt["target_digest"],
                challenge_sha256=receipt.get("challenge_sha256")
                or digest(problem["formal_statement"].encode("utf-8")),
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
            # A reviewer updates this same row. PostgreSQL must serialize that update
            # with the final identity check and receipt/claim commit, then refresh any
            # snapshot read before the lock was acquired. SQLite already serializes writes.
            session.refresh(current, with_for_update=True)
            result = outcome.model_dump(mode="json")
            # Only locally detected legacy receipts skip comparisons of missing pins.
            # Checker diagnostic text never controls this authoritative identity guard.
            if not incompatible_receipt and self._verification_revision_changed(
                current.payload, receipt
            ):
                result.update(
                    status="blocked",
                    assurance="none",
                    code="review_changed",
                    message="Target review changed during verification; submit a fresh check.",
                    remediation="Review the current revision and submit a fresh verification.",
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
                        "challenge_sha256": receipt["challenge_sha256"],
                        "review_id": receipt["review_id"],
                        "target_theorem": receipt["target_theorem"],
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

    @staticmethod
    def _verification_revision_changed(problem, receipt):
        return any(
            (
                problem.get("review_id") != receipt.get("review_id"),
                problem.get("target_theorem", "target") != receipt.get("target_theorem"),
                problem["target_digest"] != receipt["target_digest"],
                problem["environment_digest"] != receipt["environment_digest"],
                digest(problem["formal_statement"].encode("utf-8"))
                != receipt.get("challenge_sha256"),
            )
        )

    @staticmethod
    def _check_candidate_size(source):
        if len(source) > MAX_CANDIDATE_CHARACTERS:
            raise HarnessError(
                "CANDIDATE_TOO_LARGE",
                f"Candidate exceeds {MAX_CANDIDATE_CHARACTERS:,} characters.",
                status=422,
                remediation="Reduce the candidate source and submit a fresh verification.",
            )
