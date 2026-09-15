"""Portable scientific context, issued from canonical branch-visible evidence.

Summaries are unverified annotations. They cannot replace the immutable target,
open obligations, or failed-attempt references, and never mutate source records.
"""

from __future__ import annotations

import copy
import json
import math

from sqlalchemy import select

from .domain import Principal, canonical_json, digest_json
from .errors import HarnessError
from .storage import RecordRow

FORMAT = "physharness.portable-context.v1"
HISTORY_KINDS = frozenset({"artifact", "claim", "task", "verification", "source", "program"})
STATUS_FIELDS = (
    "status",
    "proof_status",
    "semantic_review",
    "novelty_status",
    "assurance",
    "evidence",
    "code",
    "message",
    "remediation",
)
MAX_BYTES = 8 * 1024 * 1024
MAX_LINEAGE = 256


def _error(code, message, **details):
    return HarnessError(code, message, details=details)


def _encoded(value):
    return canonical_json(value).encode("utf-8")


def _estimate(content):
    """A declared estimate, never a provider tokenizer or hard token guarantee."""
    return math.ceil(len(content) / 4)


class PortableMemory:
    def __init__(self, service):
        self.service = service

    def _reader(self, session, branch_id, actor, *, write=False):
        branch = (
            self.service._writable_branch(session, branch_id, actor)
            if write
            else self.service._get(session, "branch", branch_id, actor)
        )
        if actor.role == "agent" and actor.branch_id != branch_id:
            raise _error("CONTEXT_SCOPE", "Portable context requires the assigned branch identity.")
        reader = Principal(
            id=actor.id,
            project_id=actor.project_id,
            role="agent",
            experiment_id=branch.payload["experiment_id"],
            branch_id=branch_id,
        )
        return branch, reader

    def _records(self, session, kind, reader):
        rows = session.scalars(
            select(RecordRow)
            .where(
                RecordRow.project_id == reader.project_id,
                RecordRow.kind == kind,
                RecordRow.payload["experiment_id"].as_string() == reader.experiment_id,
            )
            .order_by(RecordRow.id)
        )
        return [row for row in rows if self.service._in_scope(session, row, reader)]

    def _reference(self, session, row, reader):
        if row.kind not in HISTORY_KINDS or (
            row.kind == "artifact"
            and row.payload.get("artifact_kind") in self.service._private_artifact_kinds
        ):
            raise _error(
                "CONTEXT_EVIDENCE_KIND", "Native/private checkpoints are not portable evidence."
            )
        row = self.service._get(session, row.kind, row.id, reader)
        data = row.payload
        if data.get("proof_status") == "verified" or (
            row.kind == "verification" and data.get("status") == "verified"
        ):
            experiment = self.service._get(session, "experiment", reader.experiment_id, reader)
            if not self.service._accepted_for_sharing(session, row, experiment):
                raise _error(
                    "CONTEXT_EVIDENCE_INVALID", "A verified label lacks bound canonical acceptance."
                )
        reference = {
            "id": row.id,
            "kind": row.kind,
            "revision": row.revision,
            "record_sha256": digest_json(data),
            "branch_id": data.get("branch_id"),
            "evidence_status": {key: data[key] for key in STATUS_FIELDS if key in data},
        }
        if row.kind == "artifact":
            self.service.artifacts.get(data["sha256"])
            reference["artifact_sha256"] = data["sha256"]
            reference["artifact_kind"] = data["artifact_kind"]
        return reference

    def _core(self, session, branch, reader):
        experiment = self.service._get(session, "experiment", reader.experiment_id, reader)
        target = self.service._get(session, "problem", experiment.payload["problem_id"], reader)
        review = None
        if target.payload.get("review_id"):
            # This exception reads only the assigned target's canonical review. General
            # review browsing remains subject to the service's branch visibility policy.
            row = session.get(RecordRow, target.payload["review_id"])
            if (
                not row
                or row.kind != "review"
                or row.project_id != reader.project_id
                or row.payload.get("problem_id") != target.id
                or row.payload.get("target_digest") != target.payload["target_digest"]
                or row.payload.get("decision") != target.payload.get("semantic_review")
            ):
                raise _error("CONTEXT_REVIEW_INVALID", "Target review identity is inconsistent.")
            review = copy.deepcopy(row.payload)
        elif target.payload.get("semantic_review") != "pending":
            raise _error(
                "CONTEXT_REVIEW_INVALID", "A reviewed target requires its canonical review."
            )
        if target.payload["target_digest"] != experiment.payload["target_digest"]:
            raise _error("CONTEXT_TARGET_INVALID", "Experiment and target identities differ.")
        tasks = [
            row
            for row in self._records(session, "task", reader)
            if row.payload.get("branch_id") == reader.branch_id
            and row.payload.get("status") != "completed"
        ]
        claims = [
            row
            for row in self._records(session, "claim", reader)
            if row.payload.get("branch_id") == reader.branch_id
            and row.payload.get("proof_status") != "verified"
        ]
        failures = [
            row
            for row in self._records(session, "verification", reader)
            if row.payload.get("branch_id") == reader.branch_id
            and row.payload.get("status") in {"blocked", "rejected"}
        ]
        return {
            "target": copy.deepcopy(target.payload),
            "review": review,
            "branch": {
                "id": branch.id,
                "experiment_id": reader.experiment_id,
                "target_digest": branch.payload["target_digest"],
            },
            "sharing": experiment.payload.get("sharing", "none"),
            "information_policy": experiment.payload.get("mode", "research"),
            "open_tasks": [
                {
                    "reference": self._reference(session, row, reader),
                    "objective": row.payload["objective"],
                    "dependency_ids": row.payload["dependency_ids"],
                }
                for row in tasks
            ],
            "open_claims": [
                {
                    "reference": self._reference(session, row, reader),
                    "statement": row.payload["statement"],
                    "assumptions": row.payload["assumptions"],
                }
                for row in claims
            ],
            "failed_attempts": [self._reference(session, row, reader) for row in failures],
        }

    def history_page(self, branch_id, actor, *, kind, limit=50, after=None):
        if kind not in HISTORY_KINDS:
            raise _error("CONTEXT_EVIDENCE_KIND", "Select a portable scientific record kind.")
        with self.service.db.sessions() as session:
            _, reader = self._reader(session, branch_id, actor)
            page = self.service.page_records(kind, reader, reader.experiment_id, limit, after)
            references = []
            for record in page["items"]:
                if (
                    kind == "artifact"
                    and record.get("artifact_kind") in self.service._private_artifact_kinds
                ):
                    continue
                row = self.service._get(session, kind, record["id"], reader)
                references.append(self._reference(session, row, reader))
            return {
                "items": references,
                "next_cursor": page["next_cursor"],
                "history_retained": True,
                "native_continuation": "not_included",
            }

    def _read_one(self, session, checkpoint_id, reader):
        record = self.service._get(session, "artifact", checkpoint_id, reader)
        metadata = record.payload
        if (
            metadata.get("artifact_kind") != "checkpoint"
            or metadata.get("context_format") != FORMAT
        ):
            raise _error(
                "CONTEXT_NOT_ISSUED", "Artifact was not issued as a portable context checkpoint."
            )
        content = self.service.artifacts.get(metadata["sha256"])
        if len(content) > MAX_BYTES:
            raise _error(
                "CONTEXT_ENVELOPE_EXCEEDED", "Stored context exceeds the supported byte bound."
            )
        try:
            payload = json.loads(content)
        except (ValueError, UnicodeError) as exc:
            raise _error("CONTEXT_INTEGRITY", "Checkpoint JSON is invalid.") from exc
        expected_keys = {
            "format",
            "version",
            "branch_id",
            "experiment_id",
            "scientific_core",
            "approach",
            "unresolved_obligations",
            "summary",
            "history",
            "lineage",
            "envelope",
            "portable",
            "native_continuation",
        }
        if (
            not isinstance(payload, dict)
            or set(payload) != expected_keys
            or payload.get("format") != FORMAT
            or type(payload.get("version")) is not int
            or payload.get("version") != 1
            or digest_json(payload) != metadata.get("context_sha256")
            or payload.get("branch_id") != reader.branch_id
            or metadata.get("branch_id") != reader.branch_id
            or payload.get("experiment_id") != reader.experiment_id
            or payload.get("portable") is not True
            or payload.get("native_continuation") != "not_included"
        ):
            raise _error(
                "CONTEXT_INTEGRITY", "Checkpoint structure, digest, or authority binding differs."
            )
        try:
            for annotation in (payload["approach"], payload["summary"]):
                if annotation is None:
                    if payload["approach"] is None:
                        raise ValueError("approach is required")
                    continue
                if (
                    set(annotation) != {"text", "attributed_to", "evidence_status"}
                    or not isinstance(annotation["text"], str)
                    or annotation["attributed_to"] != metadata["origin_actor_id"]
                    or annotation["evidence_status"] != "unverified"
                ):
                    raise ValueError("annotation cannot confer evidence authority")
            obligations = payload["unresolved_obligations"]
            if (
                set(obligations) != {"items", "attributed_to", "evidence_status"}
                or not isinstance(obligations["items"], list)
                or not all(isinstance(item, str) for item in obligations["items"])
                or obligations["attributed_to"] != metadata["origin_actor_id"]
                or obligations["evidence_status"] != "unverified"
            ):
                raise ValueError("invalid obligation annotation")
            history = payload["history"]
            if (
                set(history) != {"references", "selection", "complete", "retained", "retrieval"}
                or not isinstance(history["references"], list)
                or history["selection"] != "explicit"
                or history["complete"] is not False
                or history["retained"] is not True
                or history["retrieval"] != "PortableMemory.history_page"
            ):
                raise ValueError("invalid history manifest")
            if len(content) != metadata.get("size_bytes") or _estimate(content) != metadata.get(
                "estimated_tokens"
            ):
                raise ValueError("size metadata differs")
            envelope = payload["envelope"]
            self._validate_envelope(envelope["max_bytes"], envelope["max_estimated_tokens"])
            if (
                envelope["estimator"] != "ceil_utf8_bytes_div_4"
                or len(content) > envelope["max_bytes"]
                or _estimate(content) > envelope["max_estimated_tokens"]
                or payload["lineage"] != metadata.get("context_lineage")
            ):
                raise ValueError("envelope or lineage differs")
        except (KeyError, TypeError, ValueError) as exc:
            raise _error(
                "CONTEXT_INTEGRITY", "Checkpoint envelope or lineage is inconsistent."
            ) from exc
        return record, payload

    def _lineage(self, session, checkpoint_id, reader):
        seen, head, prior_generation, expected_digest = set(), None, None, None
        while checkpoint_id:
            if checkpoint_id in seen or len(seen) >= MAX_LINEAGE:
                raise _error(
                    "CONTEXT_LINEAGE",
                    "Checkpoint lineage is cyclic or exceeds its supported depth.",
                )
            seen.add(checkpoint_id)
            record, payload = self._read_one(session, checkpoint_id, reader)
            if expected_digest and record.payload["sha256"] != expected_digest:
                raise _error("CONTEXT_LINEAGE", "An ancestor checkpoint hash differs.")
            if head is None:
                head = (record, payload)
            try:
                lineage = payload["lineage"]
                generation = lineage["generation"]
                previous = lineage["previous_checkpoint_id"]
                previous_digest = lineage["previous_sha256"]
                if (
                    type(generation) is not int
                    or generation < 1
                    or (prior_generation is not None and generation != prior_generation - 1)
                    or (generation == 1 and (previous is not None or previous_digest is not None))
                    or (
                        generation > 1
                        and (not isinstance(previous, str) or not isinstance(previous_digest, str))
                    )
                ):
                    raise ValueError("invalid generation")
            except (KeyError, TypeError, ValueError) as exc:
                raise _error(
                    "CONTEXT_LINEAGE", "Checkpoint generation does not match its predecessor."
                ) from exc
            checkpoint_id, expected_digest, prior_generation = previous, previous_digest, generation
        return head

    @staticmethod
    def _validate_envelope(max_bytes, max_estimated_tokens):
        if (
            type(max_bytes) is not int
            or not 1 <= max_bytes <= MAX_BYTES
            or type(max_estimated_tokens) is not int
            or max_estimated_tokens < 1
        ):
            raise _error(
                "CONTEXT_ENVELOPE_INVALID",
                "Specify positive byte and estimated-token bounds; maximum 8 MiB.",
            )

    def checkpoint(
        self,
        branch_id,
        actor,
        key,
        *,
        approach,
        unresolved_obligations,
        summary=None,
        previous_checkpoint_id=None,
        evidence_ids=None,
        max_bytes=65536,
        max_estimated_tokens=16384,
        task_id=None,
        holder=None,
        fence=None,
    ):
        self.service._research_role(actor)
        self._validate_envelope(max_bytes, max_estimated_tokens)
        if (
            not isinstance(approach, str)
            or not approach.strip()
            or not isinstance(unresolved_obligations, list)
            or not all(isinstance(item, str) and item.strip() for item in unresolved_obligations)
            or (summary is not None and not isinstance(summary, str))
        ):
            raise _error(
                "CONTEXT_INPUT_INVALID", "Approach, obligations, and summary must be explicit text."
            )
        if any(value is not None for value in (task_id, holder, fence)) and not all(
            value is not None for value in (task_id, holder, fence)
        ):
            raise _error(
                "CONTEXT_FENCE_REQUIRED",
                "A task checkpoint requires task, holder, and fence together.",
            )
        evidence_ids = [] if evidence_ids is None else evidence_ids
        if (
            not isinstance(evidence_ids, list)
            or not all(isinstance(item, str) for item in evidence_ids)
            or len(set(evidence_ids)) != len(evidence_ids)
        ):
            raise _error(
                "CONTEXT_INPUT_INVALID",
                "Evidence IDs must be a unique list of canonical identifiers.",
            )
        inputs = {
            "branch_id": branch_id,
            "approach": approach,
            "unresolved_obligations": unresolved_obligations,
            "summary": summary,
            "previous_checkpoint_id": previous_checkpoint_id,
            "evidence_ids": evidence_ids,
            "max_bytes": max_bytes,
            "max_estimated_tokens": max_estimated_tokens,
            "task_id": task_id,
            "holder": holder,
            "fence": fence,
        }

        def action(session, operation_id):
            branch, reader = self._reader(session, branch_id, actor, write=True)
            if task_id:
                task = self.service._get(session, "task", task_id, reader)
                if task.payload.get("branch_id") != branch_id:
                    raise _error("CONTEXT_SCOPE", "Task checkpoint belongs to another branch.")
                if actor.role == "agent" and holder != actor.id:
                    raise _error(
                        "CONTEXT_SCOPE", "Worker cannot checkpoint using another holder identity."
                    )
                self.service._fenced(session, task_id, holder, fence)
            core = self._core(session, branch, reader)
            core_bytes = _encoded(core)
            if len(core_bytes) > max_bytes or _estimate(core_bytes) > max_estimated_tokens:
                raise _error(
                    "SCIENTIFIC_CORE_TOO_LARGE",
                    "The full scientific core cannot fit; increase the envelope.",
                    core_bytes=len(core_bytes),
                    core_estimated_tokens=_estimate(core_bytes),
                )
            lineage = {"generation": 1, "previous_checkpoint_id": None, "previous_sha256": None}
            if previous_checkpoint_id:
                previous, previous_payload = self._lineage(session, previous_checkpoint_id, reader)
                if previous_payload["lineage"]["generation"] >= MAX_LINEAGE:
                    raise _error(
                        "CONTEXT_LINEAGE", "Start an explicitly new lineage after the depth bound."
                    )
                lineage = {
                    "generation": previous_payload["lineage"]["generation"] + 1,
                    "previous_checkpoint_id": previous.id,
                    "previous_sha256": previous.payload["sha256"],
                }
            references = []
            for identifier in evidence_ids:
                row = session.get(RecordRow, identifier)
                if not row or row.project_id != reader.project_id:
                    raise _error("NOT_FOUND", "Evidence was not found in the assigned scope.")
                references.append(self._reference(session, row, reader))

            def annotate(text):
                return {
                    "text": text,
                    "attributed_to": actor.id,
                    "evidence_status": "unverified",
                }

            payload = {
                "format": FORMAT,
                "version": 1,
                "branch_id": branch_id,
                "experiment_id": reader.experiment_id,
                "scientific_core": core,
                "approach": annotate(approach),
                "unresolved_obligations": {
                    "items": unresolved_obligations,
                    "attributed_to": actor.id,
                    "evidence_status": "unverified",
                },
                "summary": annotate(summary) if summary is not None else None,
                "history": {
                    "references": references,
                    "selection": "explicit",
                    "complete": False,
                    "retained": True,
                    "retrieval": "PortableMemory.history_page",
                },
                "lineage": lineage,
                "envelope": {
                    "max_bytes": max_bytes,
                    "max_estimated_tokens": max_estimated_tokens,
                    "estimator": "ceil_utf8_bytes_div_4",
                },
                "portable": True,
                "native_continuation": "not_included",
            }
            content = _encoded(payload)
            if len(content) > max_bytes or _estimate(content) > max_estimated_tokens:
                raise _error(
                    "CONTEXT_ENVELOPE_EXCEEDED",
                    "Selected history or annotations exceed the envelope; "
                    "select less history or increase it.",
                    bytes=len(content),
                    estimated_tokens=_estimate(content),
                )
            sha256 = self.service.artifacts.put(content)
            if task_id:
                self.service._fenced(session, task_id, holder, fence)
            record = self.service._insert(
                session,
                "artifact",
                actor,
                {
                    "experiment_id": reader.experiment_id,
                    "branch_id": branch_id,
                    "artifact_kind": "checkpoint",
                    "media_type": "application/json",
                    "sha256": sha256,
                    "size_bytes": len(content),
                    "submitted_by": actor.id,
                    "context_format": FORMAT,
                    "context_sha256": digest_json(payload),
                    "context_lineage": lineage,
                    "estimated_tokens": _estimate(content),
                    "task_id": task_id,
                    "provenance": {"branch_id": branch_id},
                },
            )
            self.service._event(
                session,
                actor,
                operation_id,
                "context.checkpointed",
                record["id"],
                {"branch_id": branch_id, "generation": lineage["generation"]},
            )
            return record

        return self.service._execute(actor, key, "context.checkpoint", inputs, action)

    def restore(self, checkpoint_id, actor, *, expected_branch_id=None):
        with self.service.db.sessions() as session:
            artifact = self.service._get(session, "artifact", checkpoint_id, actor)
            branch_id = artifact.payload.get("branch_id")
            if not branch_id or (
                expected_branch_id is not None and branch_id != expected_branch_id
            ):
                raise _error("CONTEXT_SCOPE", "Checkpoint does not belong to the requested branch.")
            branch, reader = self._reader(session, branch_id, actor)
            _, payload = self._lineage(session, checkpoint_id, reader)
            if payload["scientific_core"] != self._core(session, branch, reader):
                raise _error(
                    "CONTEXT_STALE",
                    "Target, review, information policy, or mandatory obligations changed; "
                    "issue a fresh checkpoint.",
                )
            try:
                for reference in payload["history"]["references"]:
                    row = self.service._get(session, reference["kind"], reference["id"], reader)
                    if self._reference(session, row, reader) != reference:
                        raise _error(
                            "CONTEXT_STALE", "Selected evidence changed since the checkpoint."
                        )
            except (KeyError, TypeError) as exc:
                raise _error("CONTEXT_INTEGRITY", "Evidence references are malformed.") from exc
            except HarnessError as exc:
                if exc.code == "CONTEXT_EVIDENCE_INVALID":
                    raise _error(
                        "CONTEXT_STALE", "Selected evidence no longer has valid acceptance."
                    ) from exc
                raise
            return copy.deepcopy(payload)
