"""Operator drain rule for durable lineage and legacy single handoffs."""

from __future__ import annotations

import hashlib
from datetime import datetime

from physharness.continuation_lineage import LineageError, validate_terminal_lineage
from physharness.execution.types import ExecutionError, RuntimeCheckpoint


class HandoffAuditError(ValueError):
    pass


def terminal_sessions(
    tasks, sessions, artifact_by_id, artifact_content, experiment_id, *, links=None, scope=None
):
    """Return true only for terminal sessions with fully bound continuations."""
    if any(task.get("continuation_link_protocol") for task in tasks) and not links:
        raise HandoffAuditError("MISSING_CONTINUATION_LINKS")
    if links:
        try:
            return validate_terminal_lineage(
                tasks, sessions, links, artifact_by_id, artifact_content, experiment_id, scope or {}
            )
        except LineageError as exc:
            raise HandoffAuditError(str(exc)) from exc
    handed = [s for s in sessions if s.get("status") == "handed_off"]
    if len({source.get("task_id") for source in handed}) != len(handed):
        raise HandoffAuditError("MULTIPLE_HANDOFFS_REVIEW_REQUIRED")
    if any(s.get("status") not in {"completed", "failed", "handed_off"} for s in sessions):
        raise HandoffAuditError("NONTERMINAL_SESSION")
    if not handed:
        return True

    try:
        task_by_id = {task["id"]: task for task in tasks}
        if (
            len(task_by_id) != len(tasks)
            or len({s["id"] for s in sessions}) != len(sessions)
            or len({s.get("native_record_id") for s in sessions}) != len(sessions)
        ):
            raise HandoffAuditError("DUPLICATE_LINEAGE_RECORD")
        if any(
            s.get("experiment_id") != experiment_id or s.get("task_id") not in task_by_id
            for s in sessions
        ):
            raise HandoffAuditError("SESSION_SCOPE_MISMATCH")
    except HandoffAuditError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise HandoffAuditError("INVALID_HANDOFF_EVIDENCE") from exc

    if len(handed) > 1:
        task_ids = [source["task_id"] for source in handed]
        for task_id in task_ids:
            terminal_sessions(
                [task_by_id[task_id]],
                [session for session in sessions if session["task_id"] == task_id],
                artifact_by_id,
                artifact_content,
                experiment_id,
            )
        return True

    source = handed[0]
    task = task_by_id[source["task_id"]]
    consumed = task.get("consumed_continuation") or {}
    same_task = [s for s in sessions if s["task_id"] == task["id"]]
    if (
        task.get("experiment_id") != experiment_id
        or task.get("status") not in {"completed", "failed"}
        or task.get("ready_continuation") is not None
        or task.get("continuation_count") != 1
        or consumed.get("ordinal") != 1
        or consumed.get("experiment_id") != experiment_id
        or consumed.get("branch_id") != task.get("branch_id")
        or consumed.get("source_session_id") != source.get("native_record_id")
        or consumed.get("holder") != task.get("holder")
        or consumed.get("fence") != task.get("fence")
        or len(same_task) != 2
        or any(s.get("branch_id") not in {None, task.get("branch_id")} for s in same_task)
    ):
        raise HandoffAuditError("UNRESOLVED_HANDOFF")
    successor = next(s for s in same_task if s["id"] != source["id"])
    if successor.get("status") not in {"completed", "failed"}:
        raise HandoffAuditError("UNRESOLVED_HANDOFF")
    try:
        source_time = datetime.fromisoformat(source["created_at"])
        consume_time = datetime.fromisoformat(consumed["consumed_at"])
        successor_time = datetime.fromisoformat(successor["created_at"])
        if not source_time < consume_time < successor_time:
            raise HandoffAuditError("HANDOFF_ORDER_MISMATCH")
        checkpoints = []
        for session in (source, successor):
            artifact = artifact_by_id[session["checkpoint_artifact_id"]]
            raw = artifact_content(artifact["id"])
            if (
                artifact.get("artifact_kind") != "native_checkpoint"
                or artifact.get("experiment_id") != experiment_id
                or artifact.get("branch_id") not in {None, task.get("branch_id")}
                or (artifact.get("provenance") or {}).get("task_id") != task["id"]
                or (artifact.get("provenance") or {}).get("session_id")
                != session.get("native_record_id")
                or hashlib.sha256(raw).hexdigest() != artifact.get("sha256")
            ):
                raise HandoffAuditError("CHECKPOINT_SCOPE_MISMATCH")
            checkpoint = RuntimeCheckpoint.model_validate_json(raw)
            checkpoint.verify()
            if (
                checkpoint.session.id != session.get("native_record_id")
                or checkpoint.session.status != session["status"]
                or checkpoint.native_state.get("settled_boundary") is not True
                or checkpoint.native_state.get("pending_operation")
                or checkpoint.native_state.get("pending_tool_call")
            ):
                raise HandoffAuditError("CHECKPOINT_STATE_MISMATCH")
            checkpoints.append(checkpoint)
        if checkpoints[0].state_digest != consumed.get("source_checkpoint_digest"):
            raise HandoffAuditError("HANDOFF_DIGEST_MISMATCH")
        if (
            checkpoints[1].session.runtime != consumed.get("successor_runtime")
            or checkpoints[1].session.model.model_dump(mode="json")
            != consumed.get("successor_model")
            or checkpoints[1].session.limits.model_dump(mode="json")
            != consumed.get("successor_runtime_limits")
        ):
            raise HandoffAuditError("SUCCESSOR_SCOPE_MISMATCH")
    except HandoffAuditError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, ExecutionError) as exc:
        raise HandoffAuditError("INVALID_HANDOFF_EVIDENCE") from exc
    return True
