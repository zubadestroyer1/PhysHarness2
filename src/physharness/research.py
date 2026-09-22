"""Source and knowledge services connected to the canonical scientific authority."""

from sqlalchemy import select

from .domain import ArtifactCreate, Principal, canonical_json, digest_json
from .errors import HarnessError
from .evaluation.evidence import CanonicalEvidence
from .knowledge import LemmaIndex, LemmaRecord, ingest_text
from .knowledge.index import tokens
from .storage import RecordRow, record_json_text


class ResearchMixin:
    def ingest_source(self, experiment_id, text, format, uri, source_revision, license, actor, key):
        self._research_role(actor)
        if not license.strip():
            raise HarnessError(
                "SOURCE_LICENSE_REQUIRED", "Record the source's license or permitted-use basis."
            )
        self.get_record("experiment", experiment_id, actor)
        source = ingest_text(text, format=format, uri=uri, revision=source_revision)
        data = source.model_dump(mode="json")
        artifact = self.create_artifact(
            ArtifactCreate(
                experiment_id=experiment_id,
                kind="ingested_source",
                content=canonical_json(data),
                media_type="application/json",
                provenance={"uri": uri, "source_revision": source_revision, "license": license},
            ),
            actor,
            f"source-artifact:{key}",
        )

        def action(session, op):
            self._get(session, "experiment", experiment_id, actor)
            record = self._insert(
                session,
                "source",
                actor,
                {
                    "experiment_id": experiment_id,
                    "uri": uri,
                    "source_revision": source_revision,
                    "source_format": format,
                    "license": license,
                    "artifact_id": artifact["id"],
                    "content_sha256": source.document.content_sha256,
                    "span_count": len(source.spans),
                    "semantic_review": "pending",
                },
            )
            self._event(
                session,
                actor,
                op,
                "source.ingested",
                record["id"],
                {"experiment_id": experiment_id},
            )
            return record

        return self._execute(
            actor,
            key,
            "source.ingest",
            {
                "experiment_id": experiment_id,
                "content_sha256": source.document.content_sha256,
                "format": format,
                "uri": uri,
                "source_revision": source_revision,
                "license": license,
            },
            action,
        )

    def _knowledge_claims(self, experiment, actor, claim_id=None):
        """Load metadata in indexed keyset batches; no artifact content is fetched here."""
        scope = (
            experiment["id"]
            if experiment["mode"] == "discovery" or experiment["sharing"] == "none"
            else None
        )
        query = select(RecordRow).where(
            RecordRow.project_id == actor.project_id,
            RecordRow.kind == "claim",
            record_json_text("proof_status") == "verified",
        )
        if scope:
            query = query.where(record_json_text("experiment_id") == scope)
        if claim_id:
            query = query.where(RecordRow.id == claim_id)
        cursor = None
        with self.db.sessions() as session:
            while True:
                page = query if cursor is None else query.where(RecordRow.id > cursor)
                rows = list(session.scalars(page.order_by(RecordRow.id).limit(256)))
                for row in rows:
                    yield row.payload
                if len(rows) < 256:
                    return
                cursor = rows[-1].id

    def _applicable_knowledge(
        self, experiment_id, actor, claim_id=None, *, claims=None, rejected_candidates=None
    ):
        experiment = self.get_record("experiment", experiment_id, actor)
        target = self.get_record("problem", experiment["problem_id"], actor)
        broker = Principal(id="knowledge-broker", project_id=actor.project_id, role="operator")
        # This broker may inspect provenance, but only this policy can release a dependency.
        if claims is None:
            claims = self._knowledge_claims(experiment, broker, claim_id)
        for claim in claims:
            if claim_id and claim["id"] != claim_id:
                continue
            if claim["experiment_id"] == experiment_id:
                try:
                    self.get_record("claim", claim["id"], actor)
                except HarnessError as error:
                    if error.code == "NOT_FOUND":
                        continue
                    raise
            if claim["proof_status"] != "verified":
                continue
            try:
                origin = self.get_record("experiment", claim["experiment_id"], broker)
                if origin["id"] != experiment_id and origin.get("sharing", "none") == "none":
                    continue
                receipt = self.get_record("verification", claim["verification_id"], broker)
                if (
                    origin["id"] != experiment_id
                    and receipt.get("assurance") != "independent_kernel"
                ):
                    continue
                problem = self.get_record("problem", claim["problem_revision_id"], broker)
                candidate = self.get_record("artifact", receipt["artifact_id"], broker)
                review = self.get_record("review", problem["review_id"], broker)
            except HarnessError as error:
                if error.code == "NOT_FOUND":
                    continue  # Broken or inaccessible metadata cannot become a dependency.
                raise
            if (
                problem["semantic_review"] != "approved"
                or receipt.get("claim_id") != claim["id"]
                or claim["statement"] != problem["formal_statement"]
                or claim["assumptions"] != problem["assumptions"]
                or claim["target_digest"] != problem["target_digest"]
            ):
                continue
            if (
                experiment["mode"] == "discovery"
                and claim["target_digest"] == target["target_digest"]
            ):
                continue
            evidence = CanonicalEvidence(
                [problem, receipt, candidate, review], snapshot_id=f"knowledge:{claim['id']}"
            )
            if not evidence.validate(
                problem["id"],
                receipt["id"],
                target_digest=claim["target_digest"],
                environment_digest=target["environment_digest"],
                experiment_id=origin["id"],
            ).valid:
                continue
            try:
                source = self.artifacts.get(candidate["sha256"])
            except HarnessError as error:
                if rejected_candidates is None or error.code not in {
                    "ARTIFACT_INTEGRITY_ERROR",
                    "ARTIFACT_NOT_FOUND",
                    "ARTIFACT_PATH_UNSAFE",
                }:
                    raise
                # Report only candidates that passed visibility and all acceptance bindings.
                rejected_candidates.append({"claim_id": claim["id"], "code": error.code})
                continue
            yield claim, problem, receipt, candidate, review, source

    def search_knowledge(self, experiment_id, query, actor, type_query="", limit=20):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be from 1 to 1000")
        experiment = self.get_record("experiment", experiment_id, actor)
        target = self.get_record("problem", experiment["problem_id"], actor)
        terms, type_terms = tokens(query), tokens(type_query)
        ranked = []
        for claim in self._knowledge_claims(experiment, actor):
            statement_terms = tokens(claim["statement"])
            matches = terms & statement_terms
            if type_terms <= statement_terms and (not terms or matches):
                # Service lemmas use the statement as their type signature, so this is
                # the same ordering as LemmaIndex's lexical-plus-type score.
                ranked.append((-3 * len(matches), claim["id"], str(claim["revision"]), claim))
        ranked.sort(key=lambda item: item[:3])
        hits, rejected_candidates = [], []
        eligible = self._applicable_knowledge(
            experiment_id,
            actor,
            claims=(item[3] for item in ranked),
            rejected_candidates=rejected_candidates,
        )
        for claim, _, receipt, candidate, _, _ in eligible:
            record = LemmaRecord(
                id=claim["id"],
                revision=str(claim["revision"]),
                environment_digest=receipt["environment_digest"],
                target_digest=claim["target_digest"],
                statement=claim["statement"],
                type_signature=claim["statement"],
                status="verified",
                receipt_id=receipt["id"],
                provenance_uri=f"physharness:artifact:{candidate['id']}",
                assumptions=claim["assumptions"],
                limitations=["Recomposition in the consuming proof is still required."],
            )
            hits.extend(
                LemmaIndex([record]).search(
                    query,
                    environment_digest=target["environment_digest"],
                    type_query=type_query,
                    limit=1,
                )
            )
            if len(hits) == limit:
                break
        return {
            "items": [hit.model_dump(mode="json") for hit in hits],
            "rejected_candidates": rejected_candidates,
            "retrieval": "lexical_and_type_tokens",
            "environment_digest": target["environment_digest"],
            "information_policy": experiment["mode"],
            "source": "canonical_verified_claims",
        }

    def knowledge_bundle(self, experiment_id, claim_id, actor):
        matches = list(self._applicable_knowledge(experiment_id, actor, claim_id))
        if len(matches) != 1:
            raise HarnessError(
                "KNOWLEDGE_NOT_APPLICABLE",
                "No accessible accepted dependency matches this claim and environment.",
                status=404,
                remediation=(
                    "Check sharing policy, target review and the exact environment revision."
                ),
            )
        claim, problem, receipt, candidate, review, source = matches[0]
        result = {
            "format": "physharness-dependency-source-v1",
            "status": "accepted_dependency_source",
            "consuming_experiment_id": experiment_id,
            "claim": claim,
            "problem": problem,
            "receipt": receipt,
            "review": review,
            "artifact": candidate,
            "candidate_source": source.decode("utf-8"),
            "recomposition_required": True,
            "limitations": [
                "This exports source and acceptance evidence, not an importable trusted binary.",
                "Rebuild under the pinned environment and verify the complete consuming proof.",
            ],
        }
        return {**result, "manifest_sha256": digest_json(result)}

    def register_program(self, experiment_id, source_artifact_id, inputs, parent_id, actor, key):
        self._research_role(actor)

        def action(session, op):
            self._get(session, "experiment", experiment_id, actor)
            source = self._get(session, "artifact", source_artifact_id, actor)
            if source.payload.get("experiment_id") != experiment_id:
                raise HarnessError("PROGRAM_SCOPE", "Program source belongs to another experiment.")
            self.artifacts.get(source.payload["sha256"])
            if parent_id:
                parent = self._get(session, "program", parent_id, actor)
                if parent.payload["experiment_id"] != experiment_id:
                    raise HarnessError(
                        "PROGRAM_SCOPE", "Program parent belongs to another experiment."
                    )
            record = self._insert(
                session,
                "program",
                actor,
                {
                    "experiment_id": experiment_id,
                    "source_artifact_id": source_artifact_id,
                    "source_sha256": source.payload["sha256"],
                    "inputs": inputs,
                    "inputs_sha256": digest_json(inputs),
                    "parent_id": parent_id,
                    "status": "registered",
                    "execution": "requires_qualified_vm_broker",
                },
            )
            self._event(
                session,
                actor,
                op,
                "program.registered",
                record["id"],
                {"experiment_id": experiment_id},
            )
            return record

        return self._execute(
            actor,
            key,
            "program.register",
            {
                "experiment_id": experiment_id,
                "source_artifact_id": source_artifact_id,
                "inputs": inputs,
                "parent_id": parent_id,
            },
            action,
        )
