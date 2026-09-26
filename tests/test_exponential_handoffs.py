"""A handed-off source drains only through its exact settled successor."""

import hashlib
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from physharness.execution.types import (
    ModelConfig,
    RuntimeCheckpoint,
    RuntimeLimits,
    RuntimeSession,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "work/exponential-pilot-2026-09-24"))
from operator_handoffs import HandoffAuditError, terminal_sessions  # noqa: E402


def lineage(prefix=""):
    model = ModelConfig(model="gpt-6-sol", parameters={"reasoning": {"effort": "high"}})
    limits = RuntimeLimits(max_total_tokens=None)
    source = RuntimeCheckpoint.build(
        RuntimeSession(
            id=prefix + "native-source",
            runtime="openai_responses",
            model=model,
            limits=limits,
            status="handed_off",
        ),
        {"settled_boundary": True, "pending_operation": None, "pending_tool_call": None},
    )
    successor = RuntimeCheckpoint.build(
        RuntimeSession(
            id=prefix + "native-successor",
            runtime="openai_responses",
            model=model,
            limits=limits,
            status="completed",
        ),
        {"settled_boundary": True, "pending_operation": None, "pending_tool_call": None},
    )
    task = {
        "id": prefix + "task",
        "experiment_id": "experiment",
        "branch_id": prefix + "branch",
        "status": "completed",
        "holder": "holder",
        "fence": 2,
        "continuation_count": 1,
        "ready_continuation": None,
        "consumed_continuation": {
            "ordinal": 1,
            "experiment_id": "experiment",
            "branch_id": prefix + "branch",
            "source_session_id": prefix + "native-source",
            "source_checkpoint_digest": source.state_digest,
            "holder": "holder",
            "fence": 2,
            "consumed_at": "2026-09-24T10:01:00+00:00",
            "successor_runtime": "openai_responses",
            "successor_model": model.model_dump(mode="json"),
            "successor_runtime_limits": limits.model_dump(mode="json"),
        },
    }
    sessions = [
        {
            "id": prefix + "source",
            "experiment_id": "experiment",
            "task_id": prefix + "task",
            "status": "handed_off",
            "native_record_id": prefix + "native-source",
            "checkpoint_artifact_id": prefix + "source-artifact",
            "created_at": "2026-09-24T10:00:00+00:00",
        },
        {
            "id": prefix + "successor",
            "experiment_id": "experiment",
            "task_id": prefix + "task",
            "status": "completed",
            "native_record_id": prefix + "native-successor",
            "checkpoint_artifact_id": prefix + "successor-artifact",
            "created_at": "2026-09-24T10:02:00+00:00",
        },
    ]
    bytes_by_id = {
        prefix + "source-artifact": source.model_dump_json().encode(),
        prefix + "successor-artifact": successor.model_dump_json().encode(),
    }
    artifacts = {
        artifact_id: {
            "id": artifact_id,
            "artifact_kind": "native_checkpoint",
            "experiment_id": "experiment",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "provenance": {"task_id": prefix + "task", "session_id": session["native_record_id"]},
        }
        for (artifact_id, raw), session in zip(bytes_by_id.items(), sessions, strict=True)
    }
    return [task], sessions, artifacts, bytes_by_id


def check(case):
    tasks, sessions, artifacts, contents = case
    return terminal_sessions(tasks, sessions, artifacts, contents.__getitem__, "experiment")


def test_exact_consumed_handoff_and_terminal_successor_drain():
    assert check(lineage())


def test_separate_tasks_may_each_have_one_resolved_handoff():
    first = lineage("first-")
    second = lineage("second-")
    assert check(
        (first[0] + second[0], first[1] + second[1], first[2] | second[2], first[3] | second[3])
    )


@pytest.mark.parametrize(
    "change",
    [
        "orphan",
        "multiple",
        "digest",
        "provenance",
        "pending",
        "unfinished",
        "wrong_task",
        "wrong_order",
    ],
)
def test_orphan_or_unresolved_handoff_stays_blocked(change):
    tasks, sessions, artifacts, contents = deepcopy(lineage())
    if change == "orphan":
        tasks[0]["consumed_continuation"] = None
    elif change == "multiple":
        sessions.append({**sessions[0], "id": "another-source"})
    elif change == "digest":
        tasks[0]["consumed_continuation"]["source_checkpoint_digest"] = "0" * 64
    elif change == "provenance":
        artifacts["source-artifact"]["provenance"]["task_id"] = "other-task"
    elif change == "pending":
        checkpoint = RuntimeCheckpoint.model_validate_json(contents["source-artifact"])
        changed = RuntimeCheckpoint.build(
            checkpoint.session, {**checkpoint.native_state, "pending_operation": "unknown"}
        )
        contents["source-artifact"] = changed.model_dump_json().encode()
        artifacts["source-artifact"]["sha256"] = hashlib.sha256(
            contents["source-artifact"]
        ).hexdigest()
        tasks[0]["consumed_continuation"]["source_checkpoint_digest"] = changed.state_digest
    elif change == "unfinished":
        sessions[1]["status"] = "running"
    elif change == "wrong_task":
        sessions[1]["task_id"] = "another-task"
    elif change == "wrong_order":
        sessions[1]["created_at"] = sessions[0]["created_at"]
    with pytest.raises(HandoffAuditError) as error:
        check((tasks, sessions, artifacts, contents))
    if change == "multiple":
        assert str(error.value) == "MULTIPLE_HANDOFFS_REVIEW_REQUIRED"
