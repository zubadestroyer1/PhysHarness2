"""Source and knowledge services connected to the canonical scientific authority."""

from .domain import ArtifactCreate, Principal, canonical_json, digest_json
from .errors import HarnessError
from .evaluation.evidence import CanonicalEvidence
from .knowledge import LemmaIndex, LemmaRecord, ingest_text


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

    def _applicable_knowledge(self, experiment_id, actor, claim_id=None):
        experiment = self.get_record("experiment", experiment_id, actor)
        target = self.get_record("problem", experiment["problem_id"], actor)
        scope = (
            experiment_id
            if experiment["mode"] == "discovery" or experiment["sharing"] == "none"
            else None
        )
        broker = Principal(id="knowledge-broker", project_id=actor.project_id, role="operator")
        # This broker may inspect provenance, but only this policy can release a dependency.
        claims = self.list_records("claim", broker, scope)
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
            origin = self.get_record("experiment", claim["experiment_id"], broker)
            if origin["id"] != experiment_id and origin.get("sharing", "none") == "none":
                continue
            receipt = self.get_record("verification", claim["verification_id"], broker)
            problem = self.get_record("problem", claim["problem_revision_id"], broker)
            if (
                problem["semantic_review"] != "approved"
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
            candidate = self.get_record("artifact", receipt["artifact_id"], broker)
            review = self.get_record("review", problem["review_id"], broker)
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
            self.artifacts.get(candidate["sha256"])
            yield claim, problem, receipt, candidate, review

    def search_knowledge(self, experiment_id, query, actor, type_query="", limit=20):
        experiment = self.get_record("experiment", experiment_id, actor)
        target = self.get_record("problem", experiment["problem_id"], actor)
        records = [
            LemmaRecord(
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
            for claim, _, receipt, candidate, _ in self._applicable_knowledge(experiment_id, actor)
        ]
        hits = LemmaIndex(records).search(
            query,
            environment_digest=target["environment_digest"],
            type_query=type_query,
            limit=limit,
        )
        return {
            "items": [hit.model_dump(mode="json") for hit in hits],
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
        claim, problem, receipt, candidate, review = matches[0]
        result = {
            "format": "physharness-dependency-source-v1",
            "status": "accepted_dependency_source",
            "consuming_experiment_id": experiment_id,
            "claim": claim,
            "problem": problem,
            "receipt": receipt,
            "review": review,
            "artifact": candidate,
            "candidate_source": self.artifacts.get(candidate["sha256"]).decode("utf-8"),
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
