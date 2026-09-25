"""Portable scientific context, issued from canonical branch-visible evidence.

Summaries are unverified annotations. They cannot replace the immutable target,
open obligations, or failed-attempt references, and never mutate source records.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import math

from sqlalchemy import func, select

from .domain import Principal, canonical_json, digest_json
from .errors import HarnessError
from .storage import RecordRow, record_json_text

FORMAT = "physharness.portable-context.v1"
WORKING_FORMAT = "physharness.working-context.v1"
NOTES_FORMAT = "physharness.research-notes.v1"
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


def _prompt_view(payload):
    """Amended-away assignments stay in the canonical record (and its digest), not prompts."""
    view = copy.deepcopy(payload)
    superseded = view.pop("superseded_objectives", None)
    dropped = view.pop("superseded_objectives_dropped", None) or {}
    if superseded:
        view["superseded_objective_count"] = len(superseded) + dropped.get("count", 0)
    return view


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
            own_branch = data.get("branch_id") == reader.branch_id
            accepted = (
                self.service._accepted_evidence(
                    session, row, experiment, {"kernel", "independent_kernel"}
                )
                if own_branch
                else self.service._accepted_for_sharing(session, row, experiment)
            )
            if not accepted:
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

    def history_page(self, branch_id, actor, *, kind, limit=50, after=None, max_bytes=65536):
        if kind not in HISTORY_KINDS:
            raise _error("CONTEXT_EVIDENCE_KIND", "Select a portable scientific record kind.")
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= MAX_BYTES
        ):
            raise _error("CONTEXT_INPUT_INVALID", "Invalid history page envelope.")
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
            result = {
                "items": references,
                "next_cursor": page["next_cursor"],
                "history_retained": True,
                "native_continuation": "not_included",
            }
            if len(_encoded(result)) > max_bytes:
                raise _error(
                    "CONTEXT_ENVELOPE_EXCEEDED",
                    "History page exceeds byte envelope; use a smaller limit.",
                )
            return result

    def read_record(self, branch_id, actor, *, kind, identifier, max_bytes=65536):
        """Read one authorized portable record with its exact, checked reference."""
        if kind not in HISTORY_KINDS:
            raise _error("CONTEXT_EVIDENCE_KIND", "Select a portable scientific record kind.")
        if not isinstance(identifier, str) or not identifier:
            raise _error("CONTEXT_INPUT_INVALID", "A canonical record identifier is required.")
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
            raise _error("CONTEXT_INPUT_INVALID", "Invalid read envelope.")
        with self.service.db.sessions() as session:
            _, reader = self._reader(session, branch_id, actor)
            row = self.service._get(session, kind, identifier, reader)
            result = {
                "reference": self._reference(session, row, reader),
                "record": copy.deepcopy(row.payload),
                "content": "metadata_only",
            }
            if len(_encoded(result)) > max_bytes:
                raise _error(
                    "CONTEXT_ENVELOPE_EXCEEDED", "Record metadata exceeds the read envelope."
                )
            return result

    def read_artifact_chunk(self, branch_id, actor, *, artifact_id, offset=0, max_bytes=16384):
        """Read hash-checked artifact bytes in a bounded, byte-exact encoding."""
        if (
            type(offset) is not int
            or offset < 0
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= 16384
        ):
            raise _error("CONTEXT_INPUT_INVALID", "Invalid artifact chunk offset or size.")
        with self.service.db.sessions() as session:
            _, reader = self._reader(session, branch_id, actor)
            row = self.service._get(session, "artifact", artifact_id, reader)
            reference = self._reference(session, row, reader)
            content = self.service.artifacts.get(row.payload["sha256"])
            if offset > len(content):
                raise _error("CONTEXT_INPUT_INVALID", "Artifact offset is past the end.")
            chunk = content[offset : offset + max_bytes]
            next_offset = offset + len(chunk)
            result = {
                "reference": reference,
                "offset": offset,
                "next_offset": next_offset,
                "total_bytes": len(content),
                "content_base64": base64.b64encode(chunk).decode("ascii"),
                "encoding": "base64",
                "complete": next_offset == len(content),
            }
            # UTF-8 text is readable to a model without an external decoder;
            # the byte-exact base64 and offsets remain authoritative. A chunk
            # splitting a multibyte character simply omits this convenience.
            try:
                result["content_utf8"] = chunk.decode("utf-8")
            except UnicodeDecodeError:
                pass
            return result

    def _index_specs(self):
        return {
            "open_tasks": ("task", record_json_text("status") != "completed", "status!=completed"),
            "open_claims": (
                "claim",
                record_json_text("proof_status") != "verified",
                "proof_status!=verified",
            ),
            "accepted_claims": (
                "claim",
                record_json_text("proof_status") == "verified",
                "proof_status=verified",
            ),
            "failed_attempts": (
                "verification",
                record_json_text("status").in_(["blocked", "rejected"]),
                "status in [blocked,rejected]",
            ),
            "artifacts": (
                "artifact",
                ~record_json_text("artifact_kind").in_(self.service._private_artifact_kinds),
                "artifact_kind not private",
            ),
        }

    def _index_page(self, session, reader, index, limit, after=None):
        kind, predicate, filter_text = self._index_specs()[index]
        query = select(RecordRow).where(
            RecordRow.project_id == reader.project_id,
            RecordRow.kind == kind,
            record_json_text("experiment_id") == reader.experiment_id,
            record_json_text("branch_id") == reader.branch_id,
            predicate,
        )
        if after:
            query = query.where(RecordRow.id > after)
        rows = list(session.scalars(query.order_by(RecordRow.id).limit(limit + 1)))
        items = [self._reference(session, row, reader) for row in rows[:limit]]
        complete = len(rows) <= limit
        return {
            "items": items,
            "next_cursor": items[-1]["id"] if not complete and items else after,
            "complete": complete,
            "retrieval": {
                "method": "PortableMemory.index_page",
                "index": index,
                "kind": kind,
                "branch_id": reader.branch_id,
                "filter": filter_text,
                "limit": max(1, limit),
                "after": after,
            },
        }

    def index_page(self, branch_id, actor, *, index, limit=50, after=None, max_bytes=65536):
        """Fetch the next exact page for a working-context index."""
        if index not in self._index_specs() or type(limit) is not int or not 1 <= limit <= 100:
            raise _error("CONTEXT_INPUT_INVALID", "Invalid working-context index or page size.")
        if after is not None and (not isinstance(after, str) or not after):
            raise _error("CONTEXT_INPUT_INVALID", "Invalid index cursor.")
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
            raise _error("CONTEXT_INPUT_INVALID", "Invalid index page envelope.")
        with self.service.db.sessions() as session:
            _, reader = self._reader(session, branch_id, actor)
            result = self._index_page(session, reader, index, limit, after)
            if len(_encoded(result)) > max_bytes:
                raise _error(
                    "CONTEXT_ENVELOPE_EXCEEDED",
                    "Index page exceeds byte envelope; use a smaller limit.",
                )
            return result

    def working_context(
        self,
        branch_id,
        actor,
        *,
        task_id=None,
        max_bytes=65536,
        page_size=10,
        selected_ids=None,
    ):
        """Bounded, exact scientific entry point; history remains in canonical records."""
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
            raise _error("CONTEXT_INPUT_INVALID", "Invalid working-context envelope.")
        if type(page_size) is not int or not 0 <= page_size <= 50:
            raise _error("CONTEXT_INPUT_INVALID", "Working-context page size must be 0–50.")
        selected_ids = [] if selected_ids is None else selected_ids
        if (
            not isinstance(selected_ids, list)
            or len(selected_ids) > 50
            or any(not isinstance(value, str) for value in selected_ids)
            or len(set(selected_ids)) != len(selected_ids)
        ):
            raise _error("CONTEXT_INPUT_INVALID", "Select at most 50 unique evidence IDs.")

        with self.service.db.sessions() as session:
            branch, reader = self._reader(session, branch_id, actor)
            experiment = self.service._get(session, "experiment", reader.experiment_id, reader)
            target = self.service._get(session, "problem", experiment.payload["problem_id"], reader)
            if target.payload["target_digest"] != experiment.payload["target_digest"]:
                raise _error("CONTEXT_TARGET_INVALID", "Experiment and target identities differ.")
            review = None
            if target.payload.get("review_id"):
                row = session.get(RecordRow, target.payload["review_id"])
                if (
                    not row
                    or row.kind != "review"
                    or row.project_id != reader.project_id
                    or row.payload.get("problem_id") != target.id
                    or row.payload.get("target_digest") != target.payload["target_digest"]
                    or row.payload.get("decision") != target.payload.get("semantic_review")
                ):
                    raise _error(
                        "CONTEXT_REVIEW_INVALID", "Target review identity is inconsistent."
                    )
                review = copy.deepcopy(row.payload)
            elif target.payload.get("semantic_review") != "pending":
                raise _error(
                    "CONTEXT_REVIEW_INVALID", "A reviewed target requires its canonical review."
                )
            current_task = None
            if task_id is not None:
                row = self.service._get(session, "task", task_id, reader)
                if row.payload.get("branch_id") != branch_id:
                    raise _error("CONTEXT_SCOPE", "Current task belongs to another branch.")
                current_task = _prompt_view(row.payload)
            context = {
                "format": WORKING_FORMAT,
                "branch": {
                    "id": branch_id,
                    "experiment_id": reader.experiment_id,
                    "target_digest": branch.payload["target_digest"],
                },
                "target": copy.deepcopy(target.payload),
                "review": review,
                "current_task": current_task,
                "information_policy": experiment.payload.get("mode", "research"),
                "sharing": experiment.payload.get("sharing", "none"),
                "selected_references": [],
                "readable_work": {
                    "active_source": None,
                    "last_diagnostics": None,
                    "open_obligations": [],
                    "child_findings": [],
                    "completeness": "bounded_current_selection",
                },
                "indices": {
                    name: self._index_page(session, reader, name, 0) for name in self._index_specs()
                },
                "history_retained": True,
                "native_continuation": "not_included",
                "completeness": "selected_and_paged",
            }
            mandatory_bytes = len(_encoded(context))
            if mandatory_bytes > max_bytes:
                raise _error(
                    "SCIENTIFIC_CORE_TOO_LARGE",
                    "Target, review, and current task exceed the working envelope.",
                    core_bytes=mandatory_bytes,
                )

            for identifier in selected_ids:
                row = session.get(RecordRow, identifier)
                if not row or row.project_id != reader.project_id:
                    raise _error("NOT_FOUND", "Evidence was not found in the assigned scope.")
                candidate = self._reference(session, row, reader)
                trial = {
                    **context,
                    "selected_references": [*context["selected_references"], candidate],
                }
                if len(_encoded(trial)) > max_bytes:
                    raise _error(
                        "CONTEXT_ENVELOPE_EXCEEDED",
                        "Selected references exceed the working envelope.",
                    )
                context = trial

            # Keep a small exact working set readable after compaction. Omitted
            # records remain reachable through the indices and chunk readers.
            source_rows = list(
                session.scalars(
                    select(RecordRow)
                    .where(
                        RecordRow.project_id == reader.project_id,
                        RecordRow.kind == "artifact",
                        record_json_text("experiment_id") == reader.experiment_id,
                        record_json_text("branch_id") == branch_id,
                        record_json_text("artifact_kind") == "lean_source",
                    )
                    .order_by(record_json_text("created_at").desc(), RecordRow.id.desc())
                    .limit(1)
                )
            )
            if source_rows:
                row = self.service._get(session, "artifact", source_rows[0].id, reader)
                content = self.service.artifacts.get(row.payload["sha256"])
                try:
                    source = content.decode("utf-8")
                except UnicodeDecodeError:
                    source = None
                if source is not None and len(content) <= 16384:
                    candidate = {
                        "reference": self._reference(session, row, reader),
                        "content": source,
                    }
                    trial = copy.deepcopy(context)
                    trial["readable_work"]["active_source"] = candidate
                    if len(_encoded(trial)) <= max_bytes:
                        context = trial
            receipts = list(
                session.scalars(
                    select(RecordRow)
                    .where(
                        RecordRow.project_id == reader.project_id,
                        RecordRow.kind == "verification",
                        record_json_text("experiment_id") == reader.experiment_id,
                        record_json_text("branch_id") == branch_id,
                    )
                    .order_by(record_json_text("created_at").desc(), RecordRow.id.desc())
                    .limit(1)
                )
            )
            if receipts:
                row = self.service._get(session, "verification", receipts[0].id, reader)
                candidate = {
                    "reference": self._reference(session, row, reader),
                    "record": copy.deepcopy(row.payload),
                }
                trial = copy.deepcopy(context)
                trial["readable_work"]["last_diagnostics"] = candidate
                if len(_encoded(trial)) <= max_bytes:
                    context = trial
            for kind, predicate in (
                ("task", record_json_text("status") != "completed"),
                ("claim", record_json_text("proof_status") != "verified"),
            ):
                rows = list(
                    session.scalars(
                        select(RecordRow)
                        .where(
                            RecordRow.project_id == reader.project_id,
                            RecordRow.kind == kind,
                            record_json_text("experiment_id") == reader.experiment_id,
                            record_json_text("branch_id") == branch_id,
                            predicate,
                        )
                        .order_by(record_json_text("created_at").desc(), RecordRow.id.desc())
                        .limit(3)
                    )
                )
                for selected in rows:
                    row = self.service._get(session, kind, selected.id, reader)
                    candidate = {
                        "reference": self._reference(session, row, reader),
                        "record": _prompt_view(row.payload),
                    }
                    trial = copy.deepcopy(context)
                    trial["readable_work"]["open_obligations"].append(candidate)
                    if len(_encoded(trial)) <= max_bytes:
                        context = trial
                    else:
                        break
            messages = list(
                session.scalars(
                    select(RecordRow)
                    .where(
                        RecordRow.project_id == reader.project_id,
                        RecordRow.kind == "message",
                        record_json_text("experiment_id") == reader.experiment_id,
                        record_json_text("recipient_branch_id") == branch_id,
                    )
                    .order_by(record_json_text("created_at").desc(), RecordRow.id.desc())
                    .limit(3)
                )
            )
            for selected in messages:
                row = self.service._get(session, "message", selected.id, reader)
                candidate = {
                    key: copy.deepcopy(row.payload.get(key))
                    for key in (
                        "id",
                        "sender_branch_id",
                        "attributed_to",
                        "content",
                        "artifact_ids",
                        "evidence_status",
                        "created_at",
                    )
                }
                trial = copy.deepcopy(context)
                trial["readable_work"]["child_findings"].append(candidate)
                if len(_encoded(trial)) <= max_bytes:
                    context = trial

            for name in self._index_specs():
                page = self._index_page(session, reader, name, page_size)
                section = context["indices"][name]
                for reference in page["items"]:
                    trial = {
                        **section,
                        "items": [*section["items"], reference],
                        "next_cursor": reference["id"],
                        "complete": False,
                    }
                    candidate = {**context, "indices": {**context["indices"], name: trial}}
                    if len(_encoded(candidate)) > max_bytes:
                        break
                    section = trial
                    context = candidate
                if len(section["items"]) == len(page["items"]) and page["complete"]:
                    section = {**section, "complete": True, "next_cursor": None}
                    context = {**context, "indices": {**context["indices"], name: section}}
            if len(_encoded(context)) > max_bytes:
                raise _error(
                    "CONTEXT_ENVELOPE_EXCEEDED", "Working context exceeds its byte envelope."
                )
            return context

    def research_graph_page(
        self, branch_id, actor, *, limit=50, after=None, max_bytes=65536, max_edges=100
    ):
        """Page explicit canonical research links visible to one branch."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise _error("CONTEXT_INPUT_INVALID", "Graph page size must be 1–100.")
        if after is not None and (not isinstance(after, str) or not after):
            raise _error("CONTEXT_INPUT_INVALID", "Graph cursor must be a record ID.")
        if (
            type(max_bytes) is not int
            or not 1 <= max_bytes <= MAX_BYTES
            or type(max_edges) is not int
            or not 1 <= max_edges <= 500
        ):
            raise _error("CONTEXT_INPUT_INVALID", "Invalid graph byte or edge envelope.")
        links = {
            "task": (
                ("delegated_from_task_id", "task", "delegated_from"),
                ("branch_id", "branch", "assigned_to"),
            ),
            "claim": (
                ("artifact_id", "artifact", "evidenced_by"),
                ("verification_id", "verification", "checked_by"),
            ),
            "verification": (
                ("artifact_id", "artifact", "checks_artifact"),
                ("claim_id", "claim", "checks_claim"),
            ),
            "artifact": (("task_id", "task", "produced_by"),),
            "source": (("artifact_id", "artifact", "stored_as"),),
            "program": (
                ("parent_id", "program", "extends"),
                ("source_artifact_id", "artifact", "uses_source"),
            ),
        }
        kinds = tuple(HISTORY_KINDS) + ("branch",)
        with self.service.db.sessions() as session:
            _, reader = self._reader(session, branch_id, actor)
            query = select(RecordRow).where(
                RecordRow.project_id == reader.project_id,
                RecordRow.kind.in_(kinds),
                record_json_text("experiment_id") == reader.experiment_id,
            )
            if after:
                query = query.where(RecordRow.id > after)
            scan_limit = max(100, limit * 4)
            rows = list(session.scalars(query.order_by(RecordRow.id).limit(scan_limit + 1)))
            nodes, edges, scanned, cursor, stopped = [], [], 0, after, False
            for row in rows[:scan_limit]:
                scanned += 1
                if not self.service._in_scope(session, row, reader):
                    cursor = row.id
                    continue
                if (
                    row.kind == "artifact"
                    and row.payload.get("artifact_kind") in self.service._private_artifact_kinds
                ):
                    cursor = row.id
                    continue
                if row.kind == "branch":
                    reference = {
                        "id": row.id,
                        "kind": "branch",
                        "revision": row.revision,
                        "record_sha256": digest_json(row.payload),
                    }
                else:
                    reference = self._reference(session, row, reader)
                row_edges = []
                candidate_links = list(links.get(row.kind, ()))
                if row.kind == "task":
                    candidate_links.append(("dependency_ids", "task", "requires"))
                if row.kind == "branch":
                    candidate_links.append(("parent_id", "branch", "forked_from"))
                for field, target_kind, relation in candidate_links:
                    values = row.payload.get(field)
                    for identifier in values if isinstance(values, list) else [values]:
                        if not identifier:
                            continue
                        target = session.get(RecordRow, identifier)
                        if (
                            target
                            and target.kind == target_kind
                            and target.project_id == reader.project_id
                            and self.service._in_scope(session, target, reader)
                            and not (
                                target.kind == "artifact"
                                and target.payload.get("artifact_kind")
                                in self.service._private_artifact_kinds
                            )
                        ):
                            row_edges.append(
                                {
                                    "source_id": row.id,
                                    "target_id": identifier,
                                    "relation": relation,
                                    "source_revision": row.revision,
                                }
                            )
                trial = {
                    "items": [*nodes, reference],
                    "edges": [*edges, *row_edges],
                    "next_cursor": row.id,
                    "complete": False,
                    "scan_limited": False,
                    "authority": "canonical_records",
                    "proof_inference": "none",
                }
                if len(edges) + len(row_edges) > max_edges or len(_encoded(trial)) > max_bytes:
                    if not nodes:
                        raise _error(
                            "GRAPH_NODE_TOO_LARGE",
                            "A graph node exceeds the page envelope; "
                            "read its exact record instead.",
                            record_id=row.id,
                        )
                    stopped = True
                    break
                nodes.append(reference)
                edges.extend(row_edges)
                cursor = row.id
                if len(nodes) >= limit:
                    break
            has_more = stopped or scanned < len(rows)
            result = {
                "items": nodes,
                "edges": edges,
                "next_cursor": cursor if has_more else None,
                "complete": not has_more,
                "scan_limited": scanned >= scan_limit,
                "authority": "canonical_records",
                "proof_inference": "none",
            }
            if len(_encoded(result)) > max_bytes:
                raise _error(
                    "CONTEXT_ENVELOPE_EXCEEDED", "Graph manifest exceeds its byte envelope."
                )
            return result

    def _notes_binding(self, session, branch, reader):
        experiment = self.service._get(session, "experiment", reader.experiment_id, reader)
        target = self.service._get(session, "problem", experiment.payload["problem_id"], reader)
        if target.payload.get("target_digest") != experiment.payload.get("target_digest"):
            raise _error("CONTEXT_STALE_TARGET", "Experiment target binding differs.")
        review = None
        if target.payload.get("review_id"):
            review = session.get(RecordRow, target.payload["review_id"])
            if (
                not review
                or review.kind != "review"
                or review.project_id != reader.project_id
                or review.payload.get("problem_id") != target.id
                or review.payload.get("target_digest") != target.payload["target_digest"]
                or review.payload.get("decision") != target.payload.get("semantic_review")
            ):
                raise _error("CONTEXT_REVIEW_INVALID", "Reviewed target identity differs.")
        elif target.payload.get("semantic_review") != "pending":
            raise _error("CONTEXT_REVIEW_INVALID", "Reviewed target lacks canonical review.")
        return {
            "target_id": target.id,
            "target_sha256": digest_json(target.payload),
            "target_digest": target.payload["target_digest"],
            "review_id": review.id if review else None,
            "review_sha256": digest_json(review.payload) if review else None,
            "environment_digest": target.payload["environment_digest"],
            "branch_id": branch.id,
            "experiment_id": reader.experiment_id,
        }

    def _obligation_counts(self, session, reader):
        counts = {}
        for name in ("open_tasks", "open_claims", "failed_attempts"):
            kind, predicate, _ = self._index_specs()[name]
            counts[name] = session.scalar(
                select(func.count())
                .select_from(RecordRow)
                .where(
                    RecordRow.project_id == reader.project_id,
                    RecordRow.kind == kind,
                    record_json_text("experiment_id") == reader.experiment_id,
                    record_json_text("branch_id") == reader.branch_id,
                    predicate,
                )
            )
        return counts

    def _obligation_fingerprints(self, session, reader):
        """Bounded-memory digest of each current obligation set and its revisions."""
        fingerprints = {}
        for name in ("open_tasks", "open_claims", "failed_attempts"):
            kind, predicate, _ = self._index_specs()[name]
            digest = hashlib.sha256()
            rows = session.execute(
                select(RecordRow.id, RecordRow.revision)
                .where(
                    RecordRow.project_id == reader.project_id,
                    RecordRow.kind == kind,
                    record_json_text("experiment_id") == reader.experiment_id,
                    record_json_text("branch_id") == reader.branch_id,
                    predicate,
                )
                .order_by(RecordRow.id)
            ).yield_per(256)
            for identifier, revision in rows:
                digest.update(_encoded([identifier, revision]))
                digest.update(b"\n")
            fingerprints[name] = digest.hexdigest()
        return fingerprints

    def checkpoint_research_notes(
        self,
        branch_id,
        actor,
        key,
        *,
        approach,
        unresolved_obligations,
        summary=None,
        evidence_ids=None,
        task_id=None,
        holder=None,
        fence=None,
        max_bytes=8192,
    ):
        """Issue small attributed notes without embedding all branch obligations."""
        self.service._research_role(actor)
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
            raise _error("CONTEXT_INPUT_INVALID", "Invalid notes envelope.")
        if (
            not isinstance(approach, str)
            or not approach.strip()
            or not isinstance(unresolved_obligations, list)
            or not all(isinstance(item, str) and item.strip() for item in unresolved_obligations)
            or (summary is not None and not isinstance(summary, str))
        ):
            raise _error("CONTEXT_INPUT_INVALID", "Notes require explicit unverified text.")
        evidence_ids = [] if evidence_ids is None else evidence_ids
        if (
            not isinstance(evidence_ids, list)
            or len(evidence_ids) > 50
            or any(not isinstance(item, str) for item in evidence_ids)
            or len(set(evidence_ids)) != len(evidence_ids)
        ):
            raise _error("CONTEXT_INPUT_INVALID", "Select at most 50 unique evidence IDs.")
        if any(value is not None for value in (task_id, holder, fence)) and not all(
            value is not None for value in (task_id, holder, fence)
        ):
            raise _error("CONTEXT_FENCE_REQUIRED", "Task notes require a complete current fence.")
        inputs = {
            "branch_id": branch_id,
            "task_id": task_id,
            "approach": approach,
            "summary": summary,
            "unresolved_obligations": unresolved_obligations,
            "evidence_ids": evidence_ids,
            "max_bytes": max_bytes,
            "holder": holder,
            "fence": fence,
        }

        def action(session, operation_id):
            branch, reader = self._reader(session, branch_id, actor, write=True)
            task_reference = None
            if task_id:
                task = self.service._get(session, "task", task_id, reader)
                if task.payload.get("branch_id") != branch_id or (
                    actor.role == "agent" and holder != actor.id
                ):
                    raise _error("CONTEXT_SCOPE", "Task notes require assigned branch and holder.")
                self.service._fenced(session, task_id, holder, fence)
                task_reference = self._reference(session, task, reader)
            binding = self._notes_binding(session, branch, reader)
            references = []
            for identifier in evidence_ids:
                row = session.get(RecordRow, identifier)
                if not row or row.project_id != reader.project_id:
                    raise _error("NOT_FOUND", "Evidence was not found in the assigned scope.")
                references.append(self._reference(session, row, reader))

            def annotation(value):
                return {
                    "text": value,
                    "attributed_to": actor.id,
                    "evidence_status": "unverified",
                }

            payload = {
                "format": NOTES_FORMAT,
                "version": 1,
                "binding": binding,
                "task_reference": task_reference,
                "approach": annotation(approach),
                "summary": annotation(summary) if summary is not None else None,
                "unresolved_obligations": {
                    "items": unresolved_obligations,
                    "attributed_to": actor.id,
                    "evidence_status": "unverified",
                },
                "history": {
                    "references": references,
                    "complete": False,
                    "retrieval": "PortableMemory.index_page",
                },
                "obligation_counts": self._obligation_counts(session, reader),
                "obligation_fingerprints": self._obligation_fingerprints(session, reader),
                "native_continuation": "not_included",
            }
            content = _encoded(payload)
            if len(content) > max_bytes:
                raise _error("CONTEXT_ENVELOPE_EXCEEDED", "Research notes exceed byte envelope.")
            handoff_shape = {
                "checkpoint_id": "0" * 36,
                "checkpoint_sha256": "0" * 64,
                "source_stale": True,
                "source_status": "stale_obligations_or_evidence",
                "approach": payload["approach"],
                "summary": payload["summary"],
                "unresolved_obligations": payload["unresolved_obligations"],
                "evidence_references": references,
                "stale_reference_ids": [],
                "evidence_complete": False,
                "native_continuation": "not_included",
            }
            if len(_encoded(handoff_shape)) > min(max_bytes, 8192):
                raise _error("CONTEXT_ENVELOPE_EXCEEDED", "Research notes exceed handoff envelope.")
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
                    "context_format": NOTES_FORMAT,
                    "context_sha256": digest_json(payload),
                    "task_id": task_id,
                    "provenance": {"branch_id": branch_id},
                },
            )
            self.service._event(
                session,
                actor,
                operation_id,
                "context.notes-checkpointed",
                record["id"],
                {"branch_id": branch_id, "task_id": task_id},
            )
            return record

        return self.service._execute(actor, key, "context.notes-checkpoint", inputs, action)

    def _read_notes_one(self, session, record, reader):
        if record.payload.get("context_format") != NOTES_FORMAT:
            raise _error(
                "CONTEXT_NOT_ISSUED", "Artifact is not an issued research-notes checkpoint."
            )
        content = self.service.artifacts.get(record.payload["sha256"])
        if len(content) > MAX_BYTES or len(content) != record.payload.get("size_bytes"):
            raise _error("CONTEXT_INTEGRITY", "Research-notes size differs.")
        try:
            payload = json.loads(content)
            if (
                set(payload)
                != {
                    "format",
                    "version",
                    "binding",
                    "task_reference",
                    "approach",
                    "summary",
                    "unresolved_obligations",
                    "history",
                    "obligation_counts",
                    "obligation_fingerprints",
                    "native_continuation",
                }
                or payload["format"] != NOTES_FORMAT
                or payload["version"] != 1
                or digest_json(payload) != record.payload.get("context_sha256")
                or payload["binding"]["branch_id"] != reader.branch_id
                or payload["binding"]["experiment_id"] != reader.experiment_id
                or record.payload.get("branch_id") != reader.branch_id
                or payload["native_continuation"] != "not_included"
                or not isinstance(payload["obligation_fingerprints"], dict)
                or set(payload["obligation_fingerprints"])
                != {"open_tasks", "open_claims", "failed_attempts"}
                or any(
                    not isinstance(value, str) or len(value) != 64
                    for value in payload["obligation_fingerprints"].values()
                )
            ):
                raise ValueError("structure differs")
            for value in (payload["approach"], payload["summary"]):
                if value is None:
                    continue
                if (
                    set(value) != {"text", "attributed_to", "evidence_status"}
                    or not isinstance(value["text"], str)
                    or value["attributed_to"] != record.payload["origin_actor_id"]
                    or value["evidence_status"] != "unverified"
                ):
                    raise ValueError("annotation differs")
            obligations = payload["unresolved_obligations"]
            if (
                set(obligations) != {"items", "attributed_to", "evidence_status"}
                or not isinstance(obligations["items"], list)
                or not all(isinstance(item, str) for item in obligations["items"])
                or obligations["attributed_to"] != record.payload["origin_actor_id"]
                or obligations["evidence_status"] != "unverified"
                or payload["history"]["complete"] is not False
                or payload["history"]["retrieval"] != "PortableMemory.index_page"
                or not isinstance(payload["history"].get("references"), list)
                or any(
                    not isinstance(ref, dict)
                    or not isinstance(ref.get("kind"), str)
                    or not isinstance(ref.get("id"), str)
                    for ref in payload["history"]["references"]
                )
            ):
                raise ValueError("obligations differ")
        except (ValueError, TypeError, KeyError) as exc:
            raise _error("CONTEXT_INTEGRITY", "Research-notes structure differs.") from exc
        return payload

    def handoff_notes(self, branch_id, actor, *, task_id=None, max_bytes=8192):
        """Recover attributed notes from the latest issued checkpoint, even if obligations moved."""
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
            raise _error("CONTEXT_INPUT_INVALID", "Invalid handoff-note envelope.")
        with self.service.db.sessions() as session:
            branch, reader = self._reader(session, branch_id, actor)
            if task_id is not None:
                task = self.service._get(session, "task", task_id, reader)
                if task.payload.get("branch_id") != branch_id:
                    raise _error("CONTEXT_SCOPE", "Handoff task belongs to another branch.")
            query = select(RecordRow).where(
                RecordRow.project_id == reader.project_id,
                RecordRow.kind == "artifact",
                record_json_text("experiment_id") == reader.experiment_id,
                record_json_text("branch_id") == branch_id,
                record_json_text("artifact_kind") == "checkpoint",
                record_json_text("context_format").in_([FORMAT, NOTES_FORMAT]),
            )
            if task_id is not None:
                query = query.where(record_json_text("task_id") == task_id)
            row = session.scalar(
                query.order_by(record_json_text("created_at").desc(), RecordRow.id.desc()).limit(1)
            )
            if row is None:
                return None
            if row.payload.get("context_format") == NOTES_FORMAT:
                payload = self._read_notes_one(session, row, reader)
                if payload["binding"] != self._notes_binding(session, branch, reader):
                    raise _error("CONTEXT_STALE_TARGET", "Research-notes target changed.")
                stale = payload["obligation_counts"] != self._obligation_counts(
                    session, reader
                ) or payload["obligation_fingerprints"] != self._obligation_fingerprints(
                    session, reader
                )
                source_task = payload["task_reference"]
                if source_task is not None:
                    try:
                        current_task = self.service._get(session, "task", source_task["id"], reader)
                        if self._reference(session, current_task, reader) != source_task:
                            stale = True
                    except HarnessError:
                        stale = True
                references, stale_reference_ids = [], []
                for source_ref in payload["history"]["references"]:
                    try:
                        current = self.service._get(
                            session, source_ref["kind"], source_ref["id"], reader
                        )
                        reference = self._reference(session, current, reader)
                        if reference != source_ref:
                            raise _error("CONTEXT_STALE", "Selected evidence changed.")
                        references.append(reference)
                    except HarnessError:
                        stale = True
                        stale_reference_ids.append(source_ref["id"])
                notes = {
                    "checkpoint_id": row.id,
                    "checkpoint_sha256": row.payload["sha256"],
                    "source_stale": bool(stale),
                    "source_status": "stale_obligations_or_evidence" if stale else "current",
                    "approach": copy.deepcopy(payload["approach"]),
                    "summary": copy.deepcopy(payload["summary"]),
                    "unresolved_obligations": copy.deepcopy(payload["unresolved_obligations"]),
                    "evidence_references": references,
                    "stale_reference_ids": stale_reference_ids,
                    "evidence_complete": False,
                    "native_continuation": "not_included",
                }
                if len(_encoded(notes)) > max_bytes:
                    raise _error("CONTEXT_ENVELOPE_EXCEEDED", "Notes exceed handoff envelope.")
                return notes
            checkpoint, payload = self._lineage(session, row.id, reader)
            experiment = self.service._get(session, "experiment", reader.experiment_id, reader)
            target = self.service._get(session, "problem", experiment.payload["problem_id"], reader)
            source_core = payload["scientific_core"]
            if (
                source_core["target"] != target.payload
                or target.payload.get("target_digest") != experiment.payload.get("target_digest")
                or source_core["branch"]["target_digest"] != branch.payload["target_digest"]
            ):
                raise _error("CONTEXT_STALE_TARGET", "Checkpoint target changed before handoff.")
            review = source_core["review"]
            if review is None:
                if target.payload.get("review_id") is not None:
                    raise _error(
                        "CONTEXT_STALE_TARGET", "Checkpoint review changed before handoff."
                    )
            else:
                current_review = session.get(RecordRow, review["id"])
                if (
                    not current_review
                    or current_review.kind != "review"
                    or current_review.project_id != reader.project_id
                    or current_review.payload != review
                    or target.payload.get("review_id") != review["id"]
                    or review.get("target_digest") != target.payload["target_digest"]
                ):
                    raise _error(
                        "CONTEXT_STALE_TARGET", "Checkpoint review changed before handoff."
                    )
            stale = source_core.get("sharing") != experiment.payload.get(
                "sharing", "none"
            ) or source_core.get("information_policy") != experiment.payload.get("mode", "research")
            specs = (
                ("open_tasks", "task", record_json_text("status") != "completed"),
                ("open_claims", "claim", record_json_text("proof_status") != "verified"),
                (
                    "failed_attempts",
                    "verification",
                    record_json_text("status").in_(["blocked", "rejected"]),
                ),
            )
            for name, kind, predicate in specs:
                count = session.scalar(
                    select(func.count())
                    .select_from(RecordRow)
                    .where(
                        RecordRow.project_id == reader.project_id,
                        RecordRow.kind == kind,
                        record_json_text("experiment_id") == reader.experiment_id,
                        record_json_text("branch_id") == branch_id,
                        predicate,
                    )
                )
                if count != len(source_core[name]):
                    stale = True
                for entry in source_core[name]:
                    source_ref = entry["reference"] if "reference" in entry else entry
                    try:
                        current = self.service._get(session, kind, source_ref["id"], reader)
                        if self._reference(session, current, reader) != source_ref:
                            stale = True
                    except HarnessError:
                        stale = True
            references, stale_reference_ids = [], []
            for source_ref in payload["history"]["references"]:
                try:
                    current = self.service._get(
                        session, source_ref["kind"], source_ref["id"], reader
                    )
                    reference = self._reference(session, current, reader)
                    if reference != source_ref:
                        raise _error("CONTEXT_STALE", "Selected evidence changed.")
                    references.append(reference)
                except HarnessError:
                    stale = True
                    stale_reference_ids.append(source_ref["id"])
            notes = {
                "checkpoint_id": checkpoint.id,
                "checkpoint_sha256": checkpoint.payload["sha256"],
                "source_stale": bool(stale),
                "source_status": "stale_obligations_or_evidence" if stale else "current",
                "approach": copy.deepcopy(payload["approach"]),
                "summary": copy.deepcopy(payload["summary"]),
                "unresolved_obligations": copy.deepcopy(payload["unresolved_obligations"]),
                "evidence_references": references,
                "stale_reference_ids": stale_reference_ids,
                "evidence_complete": False,
                "native_continuation": "not_included",
            }
            if len(_encoded(notes)) > max_bytes:
                raise _error(
                    "CONTEXT_ENVELOPE_EXCEEDED",
                    "Checkpoint notes exceed the handoff envelope.",
                    checkpoint_id=checkpoint.id,
                )
            return notes

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
