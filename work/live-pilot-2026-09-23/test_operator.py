import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from operator_helpers import (
    OperatorHelperError,
    build_request,
    error_code,
    snapshot,
    summarize_report,
)


def baseline(problem_id, campaign_id="campaign-1"):
    return {
        "id": "old-exp",
        "campaign_id": campaign_id,
        "problem_id": problem_id,
        "models": [
            {
                "runtime": "responses",
                "model": "gpt-6-sol",
                "parameters": {"reasoning": {"effort": "high"}},
            }
        ],
        "budget": {
            "max_cost_usd": "5",
            "max_concurrency": 1,
            "max_runtime_seconds": 1800,
            "max_tokens": 96000,
        },
        "policy": "direct",
        "mode": "research",
        "sharing": "verified",
        "runtime_limits": {
            "max_turns": 24,
            "max_output_tokens": 16384,
            "max_total_tokens": 96000,
            "timeout_seconds": 1800,
        },
    }


def test_fresh_request_preserves_all_limits_and_changes_only_cost():
    old = baseline("b3817784-8d0e-4961-9903-c3c0feef1b58")
    request = build_request(old, old["problem_id"])
    assert request.budget.max_cost_usd == 25
    assert request.budget.max_tokens == 96000
    assert request.runtime_limits == old["runtime_limits"]
    assert request.problem_id == old["problem_id"]
    assert request.campaign_id == old["campaign_id"]


def test_mismatched_baseline_rejected():
    with pytest.raises(OperatorHelperError) as raised:
        build_request(baseline("wrong"), "b3817784-8d0e-4961-9903-c3c0feef1b58")
    assert raised.value.code == "TARGET_MISMATCH"


def test_contract_mismatch_has_allowlisted_code():
    old = baseline("b3817784-8d0e-4961-9903-c3c0feef1b58")
    old["runtime_limits"]["timeout_seconds"] = 900
    with pytest.raises(OperatorHelperError) as raised:
        build_request(old, old["problem_id"])
    assert error_code(raised.value) == "CONTRACT_MISMATCH"
    assert error_code(ValueError("secret")) == "UNEXPECTED_ERROR"


def test_snapshot_excludes_artifact_bodies_and_diagnostics(tmp_path: Path):
    db = tmp_path / "pilot.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE records (id TEXT, project_id TEXT, kind TEXT, "
            "revision INTEGER, payload TEXT)"
        )
        conn.execute(
            "CREATE TABLE budgets (experiment_id TEXT, max_cost INTEGER, reserved INTEGER, "
            "spent INTEGER, active_workers INTEGER, max_concurrency INTEGER, "
            "max_tokens INTEGER, tokens_reserved INTEGER, tokens_spent INTEGER)"
        )
        conn.execute(
            "CREATE TABLE reservations (id TEXT, experiment_id TEXT, reserved INTEGER, "
            "workers INTEGER, state TEXT, actual INTEGER, tokens_reserved INTEGER, "
            "tokens_actual INTEGER)"
        )
        exp = "11111111-1111-4111-8111-111111111111"
        for kind, payload in [
            (
                "experiment",
                {
                    "id": exp,
                    "status": "queued",
                    "problem_id": "b3817784-8d0e-4961-9903-c3c0feef1b58",
                    "secret": "NEVER_SHOW",
                },
            ),
            (
                "verification",
                {
                    "id": "receipt",
                    "experiment_id": exp,
                    "status": "blocked",
                    "code": "timeout",
                    "assurance": "none",
                    "checker_versions": {"lean": "Lean 4.20.0", "secret": "NEVER_SHOW"},
                    "diagnostics": {"secret": "NEVER_SHOW"},
                    "artifact_id": "candidate",
                },
            ),
            (
                "artifact",
                {
                    "id": "artifact",
                    "experiment_id": exp,
                    "kind": "artifact",
                    "artifact_kind": "research_output",
                    "content": "NEVER_SHOW",
                },
            ),
            (
                "session",
                {
                    "id": "session",
                    "experiment_id": exp,
                    "status": "running",
                    "input_tokens": 23,
                    "output_tokens": 7,
                    "native_context": "NEVER_SHOW",
                },
            ),
        ]:
            conn.execute(
                "INSERT INTO records VALUES (?,?,?,?,?)",
                (payload["id"], "project", kind, 1, json.dumps(payload)),
            )
        conn.execute(
            "INSERT INTO budgets VALUES (?,?,?,?,?,?,?,?,?)",
            (exp, 25000000, 1000000, 2000000, 0, 1, 96000, 0, 1000),
        )
    result = snapshot(db, {"projection": exp})
    assert result["experiments"]["projection"]["receipts"][0]["code"] == "timeout"
    assert result["experiments"]["projection"]["receipts"][0]["assurance"] == "none"
    assert result["experiments"]["projection"]["receipts"][0]["checker_versions"] == {
        "lean": "Lean 4.20.0"
    }
    assert result["experiments"]["projection"]["artifact_refs"] == [
        {"id": "artifact", "kind": "research_output"}
    ]
    assert result["experiments"]["projection"]["statuses"]["session"] == {"running": 1}
    assert result["experiments"]["projection"]["session_tokens"] == {"input": 23, "output": 7}
    assert result["captured_at"].endswith("Z")
    datetime.fromisoformat(result["captured_at"].replace("Z", "+00:00"))
    assert "NEVER_SHOW" not in json.dumps(result)
    assert result["experiments"]["projection"]["ledger"]["spent_cost_usd"] == "2.000000"


def test_report_extractor_returns_only_references_and_accounting():
    report = {
        "experiment_id": "exp",
        "status": "blocked",
        "stop_reason": "TIMEOUT",
        "artifact_id": "report",
        "ledger": {"spent_cost_usd": "1.2", "reserved_cost_usd": "0"},
        "outcomes": [
            {
                "task_id": "task",
                "status": "blocked",
                "code": "BUDGET_EXHAUSTED",
                "artifact_id": "output",
                "output_text": "NEVER_SHOW",
            }
        ],
        "verification_receipts": [
            {
                "id": "receipt",
                "status": "blocked",
                "code": "timeout",
                "assurance": "independent_kernel",
                "checker_versions": {"lean": "Lean 4.20.0", "secret": "NEVER_SHOW"},
                "diagnostics": "NEVER_SHOW",
                "artifact_id": "candidate",
            }
        ],
    }
    summary = summarize_report(report)
    assert summary["report_artifact_id"] == "report"
    assert summary["output_artifact_ids"] == ["output"]
    assert summary["outcomes"] == [
        {"task_id": "task", "status": "blocked", "code": "BUDGET_EXHAUSTED"}
    ]
    assert summary["receipts"][0]["assurance"] == "independent_kernel"
    assert summary["receipts"][0]["checker_versions"] == {"lean": "Lean 4.20.0"}
    assert "NEVER_SHOW" not in json.dumps(summary)
