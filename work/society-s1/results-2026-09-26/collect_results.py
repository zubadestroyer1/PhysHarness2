"""Collect the S1 live-run results into one path-free JSON summary.

Run from the repository root that holds the private run state (.state/s1, git-ignored):

    python3 <this file> > results.json

Reads each arm's run-team.json, newest metrics file, newest export log, arm.json and the
arm database (read-only) for the budget ledger. Writes no absolute path, token or credential.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from pathlib import Path

STATE = Path(".state/s1")
# (arm, role). Attempts that were stopped and replaced keep their own entries.
ARMS = [
    ("calibration-doeblin", "calibration attempt 1 (paused by the operator; replaced)"),
    ("calibration-doeblin-r2", "calibration"),
    ("calibration-aperiodic", "calibration"),
    ("pilot-doeblin", "pilot"),
    ("S", "society attempt 1 (paused after provider rate-limit failures; replaced)"),
    ("S-r2", "society (S)"),
    *[(f"I-0{i}", "independent (I)") for i in range(1, 9)],
    ("single", "single agent"),
]
METRIC_KEYS = (
    "accepted_root",
    "time_to_root_seconds",
    "spent_cost_usd",
    "tokens_spent",
    "branches",
    "nodes_by_status",
    "reviews_by_verdict",
    "referee_negative_share",
    "citations",
    "cross_branch_citations",
    "cross_branch_dependencies",
    "duplicate_claim_fraction",
    "lean_checks_per_accepted_result",
    "contamination_flags",
    "literature_fetches",
)
MIX_KEYS = (
    "runtime_events",
    "lean_formalization_share",
    "lean_formalization_share_of_math",
    "commons_society_share",
    "stagnation_warnings",
    "by_tool",
)


def newest(directory: Path, pattern: str) -> Path | None:
    files = sorted(directory.glob(pattern))
    return files[-1] if files else None


def ledger(arm_dir: Path) -> dict:
    db = sqlite3.connect(f"file:{arm_dir / 'harness.db'}?mode=ro", uri=True)
    try:
        max_cost, spent, reserved, workers, tokens = db.execute(
            "select max_cost, spent, reserved, active_workers, tokens_spent from budgets"
        ).fetchone()
        unsettled = db.execute(
            "select count(*) from reservations where state != 'settled'"
        ).fetchone()[0]
        amendments = [
            json.loads(payload)
            for (payload,) in db.execute(
                "select payload from events where kind = 'experiment.budget.amended'"
            )
        ]
    finally:
        db.close()
    return {
        "max_cost_usd": max_cost / 1e6,
        "spent_usd": spent / 1e6,
        "reserved_usd": reserved / 1e6,
        "active_workers": workers,
        "tokens_spent": tokens,
        "unsettled_reservations": unsettled,
        "budget_amendments": [
            {k: a[k] for k in ("old_max_cost_usd", "new_max_cost_usd", "authorization_ref")}
            for a in amendments
        ],
    }


def arm_result(arm: str, role: str) -> dict:
    arm_dir = STATE / "arms" / arm
    config = json.loads((STATE / "plans" / arm / "arm.json").read_text())
    run = json.loads((arm_dir / "run-team.json").read_text())
    prepared = json.loads((arm_dir / "prepared.json").read_text())
    metrics_file = newest(arm_dir / "metrics", "metrics-*.json")
    metrics = json.loads(metrics_file.read_text()) if metrics_file else {}
    export_file = newest(arm_dir / "logs", "export-*.json")
    export = {}
    if export_file and export_file.stat().st_size:
        data = json.loads(export_file.read_text())
        if data.get("status") == "exported":
            export = {
                "artifacts": data.get("artifacts"),
                "manifest_sha256": data["validation"].get("manifest_sha256"),
                "validation": data["validation"].get("status"),
            }
    outcomes: dict[str, int] = {}
    for outcome in run.get("outcomes", []):
        key = outcome["status"] + (f":{outcome['code']}" if outcome.get("code") else "")
        outcomes[key] = outcomes.get(key, 0) + 1
    mix = metrics.get("tool_call_mix", {})
    return {
        "arm": arm,
        "role": role,
        "target": config["target"],
        "experiment_id": prepared["experiment_id"],
        "target_digest": prepared["target_digest"],
        "challenge_sha256": config["challenge_sha256"],
        "config": {
            k: config[k]
            for k in ("roots", "policy", "concurrency", "ceiling", "wall", "max_total_tasks")
        },
        "run": {
            "status": run.get("status"),
            "stop_reason": run.get("stop_reason"),
            "root_goal_status": run.get("root_goal_status"),
            "verified_target_receipt_id": run.get("verified_target_receipt_id"),
            "attempted_tasks": run.get("attempted_tasks"),
            "outcomes": outcomes,
        },
        "ledger": ledger(arm_dir),
        "metrics": {k: metrics.get(k) for k in METRIC_KEYS},
        "tool_call_mix": {k: mix.get(k) for k in MIX_KEYS},
        "export": export,
    }


def spread(values: list[float]) -> dict:
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": round(statistics.mean(values), 3),
        "max": max(values),
    }


def main() -> None:
    arms = [arm_result(arm, role) for arm, role in ARMS]
    independent = [a for a in arms if a["role"] == "independent (I)"]
    verified = [a for a in independent if a["run"]["stop_reason"] == "TARGET_VERIFIED"]
    times = [a["metrics"]["time_to_root_seconds"] for a in verified]
    summary = {
        "independent": {
            "verified": f"{len(verified)}/{len(independent)}",
            "time_to_root_seconds": spread(times),
            "spent_usd": spread([a["ledger"]["spent_usd"] for a in independent]),
            "total_spent_usd": round(sum(a["ledger"]["spent_usd"] for a in independent), 6),
        },
        "total_spent_usd_all_arms": round(sum(a["ledger"]["spent_usd"] for a in arms), 6),
    }
    print(json.dumps({"format": "s1-live-results-v1", "summary": summary, "arms": arms}, indent=1))


if __name__ == "__main__":
    main()
