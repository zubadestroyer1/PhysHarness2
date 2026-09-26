import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "work/parallel-pilot-2026-09-24/evaluate_pilot.py"
SPEC = importlib.util.spec_from_file_location("parallel_evaluate_pilot", SCRIPT)
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


def artifact(root, kind, content):
    raw = json.dumps(content).encode()
    digest = hashlib.sha256(raw).hexdigest()
    path = root / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"artifact_kind": kind, "sha256": digest, "created_at": "2026-09-24T00:00:00+00:00"}


def test_deduplicates_native_response_and_reads_cache_cost(tmp_path):
    response = {
        "id": "resp_one",
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
    }
    checkpoint = {
        "native_state": {
            "responses": [response],
            "tool_results": {"session:call": {"result": {"error": {"code": "UNSAFE_PATH"}}}},
        }
    }
    usage = {
        "input_tokens": 1000,
        "output_tokens": 100,
        "input_tokens_details": {"cached_tokens": 200, "cache_write_tokens": 300},
    }
    artifacts = [
        artifact(tmp_path, "native_checkpoint", checkpoint),
        artifact(tmp_path, "native_checkpoint", checkpoint),
        artifact(
            tmp_path,
            "runtime_event",
            {
                "kind": "usage",
                "operation_id": "op_one",
                "session_id": "session",
                "payload": {"response_id": "resp_one", "native_usage": usage},
            },
        ),
        artifact(
            tmp_path,
            "runtime_event",
            {
                "kind": "tool_completed",
                "operation_id": "session:call",
                "session_id": "session",
                "payload": {"name": "lookup_library_source"},
            },
        ),
    ]
    result = evaluation.runtime_metrics(artifacts, tmp_path)
    assert result["native_response_count"] == 1
    assert result["response_cap_hits"] == 1
    assert result["tool_calls_completed"] == 1
    assert result["retrieval_tool_calls_completed"] == 1
    assert result["tool_rejection_codes"] == {"UNSAFE_PATH": 1}
    assert evaluation.exact_input_bill(usage) == evaluation.Decimal("0.002790")


def test_receipt_cost_uses_latest_settlement_per_reservation():
    events = [
        {
            "sequence": 1,
            "kind": "resources.settled",
            "aggregate_id": "arm",
            "payload": {"id": "hold", "state": "settled", "actual_cost_usd": "0.10"},
        },
        {
            "sequence": 2,
            "kind": "resources.settled",
            "aggregate_id": "arm",
            "payload": {"id": "hold", "state": "settled", "actual_cost_usd": "0.10"},
        },
        {
            "sequence": 3,
            "kind": "resources.settled",
            "aggregate_id": "arm",
            "payload": {"id": "later", "state": "settled", "actual_cost_usd": "0.20"},
        },
    ]
    assert evaluation.settlement_cost_at(events, "arm", 2) == "0.10"


def test_child_task_and_event_time_are_canonical():
    tasks = [
        {"id": "root", "status": "completed"},
        {
            "id": "child",
            "status": "completed",
            "delegated_from_task_id": "root",
            "reply_to_parent_task_id": None,
            "detached": True,
        },
    ]
    roots, children = evaluation.classify_tasks(tasks)
    assert [t["id"] for t in roots] == ["root"]
    assert [t["id"] for t in children] == ["child"]
    assert (
        evaluation.event_elapsed_seconds("2026-09-24T00:00:00+00:00", "2026-09-24T00:00:42+00:00")
        == 42
    )
    with pytest.raises(evaluation.EvaluationError, match="predates"):
        evaluation.event_elapsed_seconds("2026-09-24T00:00:42+00:00", "2026-09-24T00:00:00+00:00")


def test_verified_receipt_rehashes_candidate_bytes(tmp_path):
    candidate = artifact(tmp_path, "lean_source", {"x": 1})
    candidate["id"] = "candidate"
    candidate["experiment_id"] = "experiment"
    problem = {
        "id": "problem",
        "formal_statement": "theorem target : True := by trivial",
        "target_digest": "target",
        "environment_digest": "environment",
        "review_id": "review",
        "target_theorem": "target",
    }
    experiment = {"id": "experiment", "target_digest": "target"}
    receipt = {
        "id": "receipt",
        "status": "verified",
        "experiment_id": "experiment",
        "problem_revision_id": "problem",
        "target_digest": "target",
        "challenge_sha256": hashlib.sha256(problem["formal_statement"].encode()).hexdigest(),
        "environment_digest": "environment",
        "review_id": "review",
        "target_theorem": "target",
        "artifact_id": "candidate",
        "candidate_sha256": candidate["sha256"],
        "axioms": [],
        "checker_versions": {},
    }
    result = evaluation.receipt_summary(
        receipt, problem, experiment, {"candidate": candidate}, tmp_path
    )
    assert result["binding_valid"]
    assert result["candidate_bytes_sha256"] == candidate["sha256"]
    path = tmp_path / candidate["sha256"][:2] / candidate["sha256"]
    path.write_bytes(b"tampered")
    with pytest.raises(evaluation.EvaluationError, match="artifact digest mismatch"):
        evaluation.receipt_summary(receipt, problem, experiment, {"candidate": candidate}, tmp_path)
