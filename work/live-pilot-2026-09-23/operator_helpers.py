"""Bounded operator commands for the two reviewed first-pilot targets.

No command prints configuration, credentials, artifact contents or model context.
Only ``prepare`` changes canonical records, through HarnessService.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from physharness.domain import ExperimentCreate

TARGETS = {
    "projection": ("b3817784-8d0e-4961-9903-c3c0feef1b58", "f2214f34-d2b0-4035-9be8-75857cd8cb2f"),
    "purity": ("215b5024-4285-4aa4-baed-05cf37363291", "346e6d5e-4d40-4a30-a28d-c93236f45714"),
}
SAFE_CODE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,79}$")
SAFE_ATTEMPT = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+:/(),-]{0,119}$")


class OperatorHelperError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def error_code(error: Exception) -> str:
    """Return a fixed diagnostic code without forwarding arbitrary exception text."""
    allowed = {
        "INVALID_ATTEMPT",
        "TARGET_MISMATCH",
        "CONTRACT_MISMATCH",
        "CAMPAIGN_MISMATCH",
        "REVIEW_MISMATCH",
        "TARGET_REVISION_MISMATCH",
    }
    return (
        error.code
        if isinstance(error, OperatorHelperError) and error.code in allowed
        else "UNEXPECTED_ERROR"
    )


def build_request(previous: dict, expected_problem_id: str) -> ExperimentCreate:
    """Preserve the v2 attempt contract and change only the cost ceiling."""
    if previous.get("problem_id") != expected_problem_id:
        raise OperatorHelperError("TARGET_MISMATCH")
    models = previous.get("models")
    budget = previous.get("budget")
    limits = previous.get("runtime_limits")
    if (
        models
        != [
            {
                "runtime": "responses",
                "model": "gpt-6-sol",
                "parameters": {"reasoning": {"effort": "high"}},
            }
        ]
        or not isinstance(budget, dict)
        or budget.get("max_concurrency") != 1
        or budget.get("max_runtime_seconds") != 1800
        or budget.get("max_tokens") != 96000
        or limits
        != {
            "max_turns": 24,
            "max_output_tokens": 16384,
            "max_total_tokens": 96000,
            "timeout_seconds": 1800,
        }
        or previous.get("policy") != "direct"
        or previous.get("sharing") != "verified"
        or previous.get("mode") != "research"
    ):
        raise OperatorHelperError("CONTRACT_MISMATCH")
    return ExperimentCreate.model_validate(
        {
            "campaign_id": previous["campaign_id"],
            "problem_id": expected_problem_id,
            "models": models,
            "budget": {**budget, "max_cost_usd": "25"},
            "policy": previous["policy"],
            "mode": previous["mode"],
            "sharing": previous["sharing"],
            "runtime_limits": limits,
        }
    )


def prepare(attempt: str, target: str) -> dict:
    if not SAFE_ATTEMPT.fullmatch(attempt):
        raise OperatorHelperError("INVALID_ATTEMPT")
    from physharness.cli import local_authority

    _, service, actor = local_authority("operator")
    expected_problem_id, previous_experiment_id = TARGETS[target]
    previous = service.get_record("experiment", previous_experiment_id, actor)
    problem = service.get_record("problem", expected_problem_id, actor)
    request = build_request(previous, expected_problem_id)
    if request.campaign_id != problem.get("campaign_id"):
        raise OperatorHelperError("CAMPAIGN_MISMATCH")
    if problem.get("target_digest") != previous.get("target_digest"):
        raise OperatorHelperError("TARGET_REVISION_MISMATCH")
    if problem.get("semantic_review") != "approved" or not problem.get("review_id"):
        raise OperatorHelperError("REVIEW_MISMATCH")
    key = f"live-pilot-2026-09-23:{target}:{attempt}:experiment"
    created = service.create_experiment(request, actor, key)
    return {
        "attempt": attempt,
        "target": target,
        "problem_id": expected_problem_id,
        "campaign_id": request.campaign_id,
        "experiment_id": created["id"],
        "status": created["status"],
        "max_cost_usd": "25",
        "idempotency_key": key,
    }


def _code(value):
    return value if isinstance(value, str) and SAFE_CODE.fullmatch(value) else None


def _dollars(units):
    return format(Decimal(int(units)) / Decimal(1_000_000), ".6f")


def _checker_versions(value):
    if not isinstance(value, dict):
        return {}
    return {
        name: version
        for name in ("lean", "comparator", "nanoda")
        if isinstance(version := value.get(name), str) and SAFE_VERSION.fullmatch(version)
    }


def _session_tokens(value):
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else 0


def snapshot(database: Path, expected: dict[str, str]) -> dict:
    """Read only the explicitly named local pilot DB and emit allowlisted metadata."""
    if not database.is_file() or database.is_symlink():
        raise ValueError("Expected regular pilot database is unavailable")
    result = {"experiments": {}}
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        for target, exp_id in expected.items():
            row = conn.execute(
                "SELECT payload FROM records WHERE id=? AND kind='experiment'", (exp_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Expected {target} experiment is absent")
            experiment = json.loads(row[0])
            expected_problem_id = TARGETS[target][0]
            if experiment.get("problem_id") != expected_problem_id:
                raise ValueError(f"Expected {target} target does not match")
            b = conn.execute(
                "SELECT max_cost,reserved,spent,active_workers,max_concurrency,max_tokens,"
                "tokens_reserved,tokens_spent FROM budgets WHERE experiment_id=?",
                (exp_id,),
            ).fetchone()
            if b is None:
                raise ValueError(f"Expected {target} ledger is absent")
            rows = conn.execute(
                "SELECT kind,payload FROM records WHERE json_extract(payload,'$.experiment_id')=? "
                "AND kind IN ('task','session','claim','artifact','verification','branch')",
                (exp_id,),
            ).fetchall()
            counts = Counter()
            statuses = {}
            receipts = []
            artifact_refs = []
            session_tokens = {"input": 0, "output": 0}
            for kind, raw in rows:
                data = json.loads(raw)
                counts[kind] += 1
                state = data.get("status") or data.get("proof_status")
                if kind in {"task", "verification", "claim", "session"} and isinstance(state, str):
                    statuses.setdefault(kind, Counter())[state if _code(state) else "unknown"] += 1
                if kind == "session":
                    session_tokens["input"] += _session_tokens(data.get("input_tokens"))
                    session_tokens["output"] += _session_tokens(data.get("output_tokens"))
                if kind == "verification":
                    receipts.append(
                        {
                            "id": data.get("id"),
                            "status": state if _code(state) else "unknown",
                            "code": _code(data.get("code")),
                            "assurance": data.get("assurance")
                            if data.get("assurance") in {"none", "kernel", "independent_kernel"}
                            else None,
                            "checker_versions": _checker_versions(data.get("checker_versions")),
                            "artifact_id": data.get("artifact_id"),
                            "claim_id": data.get("claim_id"),
                        }
                    )
                if kind == "artifact" and data.get("artifact_kind") in {
                    "team_run_report",
                    "research_output",
                }:
                    artifact_refs.append({"id": data.get("id"), "kind": data.get("artifact_kind")})
            uncertain = conn.execute(
                "SELECT count(*) FROM reservations WHERE experiment_id=? AND state='uncertain'",
                (exp_id,),
            ).fetchone()[0]
            result["experiments"][target] = {
                "experiment_id": exp_id,
                "problem_id": expected_problem_id,
                "status": experiment.get("status")
                if _code(experiment.get("status"))
                else "unknown",
                "counts": dict(counts),
                "statuses": {kind: dict(counter) for kind, counter in statuses.items()},
                "receipts": receipts,
                "artifact_refs": artifact_refs,
                "session_tokens": session_tokens,
                "ledger": {
                    "max_cost_usd": _dollars(b[0]),
                    "reserved_cost_usd": _dollars(b[1]),
                    "spent_cost_usd": _dollars(b[2]),
                    "active_workers": b[3],
                    "max_concurrency": b[4],
                    "max_tokens": b[5],
                    "tokens_reserved": b[6],
                    "tokens_spent": b[7],
                    "uncertain_operations": uncertain,
                },
            }
    result["captured_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return result


def summarize_report(report: dict) -> dict:
    """Strip run-team output to finite accounting and durable references."""
    ledger = report.get("ledger") or {}
    return {
        "experiment_id": report.get("experiment_id"),
        "status": _code(report.get("status")),
        "stop_reason": _code(report.get("stop_reason")),
        "report_artifact_id": report.get("artifact_id"),
        "attempted_tasks": report.get("attempted_tasks"),
        "remaining_task_ids": report.get("remaining_task_ids", []),
        "outcomes": [
            {
                "task_id": o.get("task_id"),
                "status": _code(o.get("status")),
                "code": _code(o.get("code")),
            }
            for o in report.get("outcomes", [])
        ],
        "output_artifact_ids": [
            o["artifact_id"] for o in report.get("outcomes", []) if o.get("artifact_id")
        ],
        "receipts": [
            {
                "id": r.get("id"),
                "status": _code(r.get("status")),
                "code": _code(r.get("code")),
                "assurance": r.get("assurance")
                if r.get("assurance") in {"none", "kernel", "independent_kernel"}
                else None,
                "checker_versions": _checker_versions(r.get("checker_versions")),
                "artifact_id": r.get("artifact_id"),
                "claim_id": r.get("claim_id"),
            }
            for r in report.get("verification_receipts", [])
        ],
        "pending_verification_ids": report.get("pending_verification_ids", []),
        "verification_worker_continues": bool(report.get("verification_worker_continues")),
        "ledger": {
            key: ledger.get(key)
            for key in (
                "max_cost_usd",
                "reserved_cost_usd",
                "spent_cost_usd",
                "uncertain_operations",
                "max_tokens",
                "tokens_reserved",
                "tokens_spent",
            )
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser(
        "prepare", help="Create one new canonical experiment from an existing v2 target"
    )
    p.add_argument("target", choices=TARGETS)
    p.add_argument("--attempt", required=True)
    s = sub.add_parser("snapshot", help="Read-only metadata snapshot of an explicit pilot DB")
    s.add_argument("--database", type=Path, required=True)
    for target in TARGETS:
        s.add_argument(f"--{target}-experiment", required=True)
    s.add_argument("--output", type=Path, required=True)
    r = sub.add_parser("report", help="Extract safe references and ledger from run-team JSON")
    r.add_argument("--input", type=Path, required=True)
    r.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stage = args.command.upper()
    try:
        if args.command == "prepare":
            result = prepare(args.attempt, args.target)
        elif args.command == "snapshot":
            result = snapshot(
                args.database, {target: getattr(args, f"{target}_experiment") for target in TARGETS}
            )
        else:
            if args.input.stat().st_size > 1_000_000 or args.input.is_symlink():
                raise ValueError("Run report must be a bounded regular JSON file")
            result = summarize_report(json.loads(args.input.read_text()))
        if args.command == "prepare":
            print(json.dumps(result, sort_keys=True))
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_suffix(args.output.suffix + ".tmp")
            temporary.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
            os.replace(temporary, args.output)
            print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "stage": stage,
                    "code": error_code(error),
                    "message": "Operator helper failed; inspect canonical state privately.",
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
