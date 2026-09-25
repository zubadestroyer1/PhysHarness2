"""Read-only validation of canonical, settled continuation chains."""

from __future__ import annotations

import hashlib
from datetime import datetime

from .execution.checkpoint_chunks import decode
from .execution.types import ExecutionError


class LineageError(ValueError):
    pass


def validate_terminal_lineage(
    tasks, sessions, links, artifacts, artifact_content, experiment_id, scope
):
    """Validate every per-task source-to-successor edge; never grant runtime authority."""
    if any(task.get("experiment_id") != experiment_id for task in tasks):
        raise LineageError("TASK_SCOPE_MISMATCH")
    if any(s.get("status") not in {"completed", "failed", "handed_off"} for s in sessions):
        raise LineageError("NONTERMINAL_SESSION")
    try:
        task_by_id = {task["id"]: task for task in tasks}
        session_by_id = {s["id"]: s for s in sessions}
        if len(task_by_id) != len(tasks) or len(session_by_id) != len(sessions):
            raise LineageError("DUPLICATE_LINEAGE_RECORD")
        if len({s.get("native_record_id") for s in sessions}) != len(sessions):
            raise LineageError("DUPLICATE_NATIVE_SESSION")
        if any(
            s.get("experiment_id") != experiment_id or s.get("task_id") not in task_by_id
            for s in sessions
        ):
            raise LineageError("SESSION_SCOPE_MISMATCH")
        if any(
            link.get("experiment_id") != experiment_id or link.get("task_id") not in task_by_id
            for link in links
        ):
            raise LineageError("LINK_SCOPE_MISMATCH")
        for task in tasks:
            task_links = sorted(
                (link for link in links if link["task_id"] == task["id"]),
                key=lambda link: link["ordinal"],
            )
            task_sessions = [s for s in sessions if s["task_id"] == task["id"]]
            if not task_links:
                if task.get("continuation_link_protocol") or task.get("continuation_count", 0):
                    raise LineageError("MISSING_CONTINUATION_LINKS")
                if any(s["status"] == "handed_off" for s in task_sessions):
                    raise LineageError("ORPHAN_HANDOFF")
                for standalone in task_sessions:
                    _checkpoint(standalone, task, artifacts, artifact_content, experiment_id)
                continue
            if (
                task.get("status") not in {"completed", "failed"}
                or task.get("ready_continuation") is not None
                or task.get("continuation_count") != len(task_links)
                or [link.get("ordinal") for link in task_links]
                != list(range(1, len(task_links) + 1))
                or len(task_sessions) != len(task_links) + 1
            ):
                raise LineageError("INCOMPLETE_CONTINUATION_CHAIN")
            for ordinal, link in enumerate(task_links, start=1):
                source = session_by_id.get(link.get("source_session_record_id"))
                successor = session_by_id.get(link.get("successor_record_id"))
                if (
                    link.get("status") != "started"
                    or link.get("branch_id") != task.get("branch_id")
                    or any(
                        link.get(field) != scope.get(field)
                        for field in ("target_digest", "review_id", "environment_digest")
                    )
                    or source is None
                    or successor is None
                    or source.get("task_id") != task["id"]
                    or successor.get("task_id") != task["id"]
                    or source.get("status") != "handed_off"
                    or source.get("native_record_id") != link.get("source_session_id")
                    or successor.get("native_record_id") != link.get("successor_session_id")
                    or source.get("checkpoint_artifact_id")
                    != link.get("source_checkpoint_artifact_id")
                    or source["id"] == successor["id"]
                    or not isinstance(link.get("holder"), str)
                    or not link["holder"]
                    or type(link.get("fence")) is not int
                    or link["fence"] <= 0
                ):
                    raise LineageError("CONTINUATION_LINK_MISMATCH")
                if (
                    ordinal > 1
                    and task_links[ordinal - 2].get("successor_record_id") != source["id"]
                ):
                    raise LineageError("DISCONNECTED_CONTINUATION_CHAIN")
                if ordinal < len(task_links) and successor["status"] != "handed_off":
                    raise LineageError("DISCONNECTED_CONTINUATION_CHAIN")
                if ordinal == len(task_links) and successor["status"] not in {
                    "completed",
                    "failed",
                }:
                    raise LineageError("UNFINISHED_SUCCESSOR")
                if not (
                    datetime.fromisoformat(source["created_at"])
                    < datetime.fromisoformat(link["issued_at"])
                    <= datetime.fromisoformat(link["consumed_at"])
                    < datetime.fromisoformat(successor["created_at"])
                ):
                    raise LineageError("CONTINUATION_ORDER_MISMATCH")
                source_cp = _checkpoint(source, task, artifacts, artifact_content, experiment_id)
                successor_cp = _checkpoint(
                    successor, task, artifacts, artifact_content, experiment_id
                )
                if (
                    source_cp.state_digest != link.get("source_checkpoint_digest")
                    or source_cp.session.model.model_dump(mode="json") != link.get("source_model")
                    or source_cp.session.runtime != link.get("source_runtime")
                    or source_cp.session.limits.model_dump(mode="json")
                    != link.get("source_runtime_limits")
                    or successor_cp.session.model.model_dump(mode="json")
                    != link.get("successor_model")
                    or successor_cp.session.runtime != link.get("successor_runtime")
                    or successor_cp.session.limits.model_dump(mode="json")
                    != link.get("successor_runtime_limits")
                ):
                    raise LineageError("CONTINUATION_CHECKPOINT_MISMATCH")
                ticket = link.get("workspace_ticket")
                if ticket:
                    archive = artifacts.get(ticket.get("artifact_id"))
                    if (
                        archive is None
                        or archive.get("artifact_kind") != "checkpoint"
                        or archive.get("experiment_id") != experiment_id
                        or archive.get("task_id") != task["id"]
                        or archive.get("sha256") != ticket.get("archive_sha256")
                        or archive.get("branch_id") != task.get("branch_id")
                        or hashlib.sha256(artifact_content(archive["id"])).hexdigest()
                        != ticket.get("archive_sha256")
                    ):
                        raise LineageError("WORKSPACE_ARCHIVE_MISMATCH")
            chain_ids = {link["source_session_record_id"] for link in task_links}
            chain_ids.add(task_links[-1]["successor_record_id"])
            if chain_ids != {session["id"] for session in task_sessions}:
                raise LineageError("EXTRA_OR_CYCLIC_SESSION")
            final = task.get("consumed_continuation") or {}
            last = task_links[-1]
            if (
                final.get("ordinal") != last["ordinal"]
                or final.get("source_session_id") != last.get("source_session_id")
                or final.get("source_checkpoint_digest") != last.get("source_checkpoint_digest")
                or final.get("successor_model") != last.get("successor_model")
                or final.get("successor_runtime") != last.get("successor_runtime")
                or final.get("successor_runtime_limits") != last.get("successor_runtime_limits")
                or final.get("holder") != last.get("holder")
                or final.get("fence") != last.get("fence")
                or final.get("consumed_at") != last.get("consumed_at")
            ):
                raise LineageError("LATEST_CONTINUATION_MISMATCH")
    except LineageError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, ExecutionError) as exc:
        raise LineageError("INVALID_LINEAGE_EVIDENCE") from exc
    return True


def _checkpoint(session, task, artifacts, artifact_content, experiment_id):
    artifact = artifacts[session["checkpoint_artifact_id"]]
    raw = artifact_content(artifact["id"])
    if (
        artifact.get("artifact_kind") != "native_checkpoint"
        or artifact.get("experiment_id") != experiment_id
        or artifact.get("branch_id") not in {None, task.get("branch_id")}
        or (artifact.get("provenance") or {}).get("task_id") != task["id"]
        or (artifact.get("provenance") or {}).get("session_id") != session.get("native_record_id")
        or hashlib.sha256(raw).hexdigest() != artifact.get("sha256")
        or session.get("branch_id") not in {None, task.get("branch_id")}
    ):
        raise LineageError("CHECKPOINT_SCOPE_MISMATCH")

    def read(ref):
        chunk = artifacts.get(ref["artifact_id"])
        if (
            chunk is None
            or chunk.get("artifact_kind") != "native_checkpoint_chunk"
            or chunk.get("experiment_id") != experiment_id
            or (chunk.get("provenance") or {}).get("task_id") != task["id"]
            or (chunk.get("provenance") or {}).get("session_id") != session.get("native_record_id")
            or chunk.get("sha256") != ref["sha256"]
        ):
            raise LineageError("CHECKPOINT_CHUNK_SCOPE_MISMATCH")
        return artifact_content(chunk["id"])

    checkpoint = decode(raw, read)
    if (
        checkpoint.session.id != session.get("native_record_id")
        or checkpoint.session.status != session.get("status")
        or checkpoint.native_state.get("settled_boundary") is not True
        or checkpoint.native_state.get("pending_operation")
        or checkpoint.native_state.get("pending_tool_call")
    ):
        raise LineageError("CHECKPOINT_STATE_MISMATCH")
    return checkpoint
