"""Read-only, source-free per-attempt evaluation using frozen pilot extractors."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

OLD_EXTRACTOR = Path(__file__).resolve().parents[1] / "parallel-pilot-2026-09-24/evaluate_pilot.py"
SPEC = importlib.util.spec_from_file_location("frozen_parallel_evaluator", OLD_EXTRACTOR)
frozen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(frozen)


def evaluate_attempt(attempt: dict) -> dict:
    records, events, budgets, _ = frozen.load_canonical(attempt)
    identifier = attempt["experiment_id"]
    experiment = next(r for r in records["experiment"] if r["id"] == identifier)
    problem = next(r for r in records["problem"] if r["id"] == experiment["problem_id"])
    budget = budgets[identifier]
    root = Path(attempt["artifact_root"])
    artifacts = [r for r in records["artifact"] if r.get("experiment_id") == identifier]
    artifact_index = {r["id"]: r for r in artifacts}
    receipts = [r for r in records["verification"] if r.get("experiment_id") == identifier]
    tasks = [r for r in records["task"] if r.get("experiment_id") == identifier]
    runtime = frozen.runtime_metrics(artifacts, root)
    usage = runtime.pop("usages")
    summary = [
        frozen.receipt_summary(r, problem, experiment, artifact_index, root) for r in receipts
    ]
    verified = [
        e
        for e in events
        if e["kind"] == "verification.verified" and e["aggregate_id"] in {r["id"] for r in receipts}
    ]
    verified.sort(key=lambda e: e["sequence"])
    first = verified[0] if verified else None
    completed = [
        e
        for e in events
        if e["kind"] == "task.completed" and e["aggregate_id"] in {t["id"] for t in tasks}
    ]
    last = max((e["created_at"] for e in completed), default=None)
    roots, children = frozen.classify_tasks(tasks)
    exact_bills = [frozen.exact_input_bill(u["native_usage"]) for u in usage.values()]
    model_reservations = [
        r for r in records["model_reservation"] if r.get("experiment_id") == identifier
    ]
    return {
        "protocol": "exponential-pilot-attempt-evaluation-v1",
        "label": attempt["label"],
        "experiment_id": identifier,
        "experiment_status": experiment["status"],
        "sharing": experiment["sharing"],
        "challenge_sha256": hashlib.sha256(problem["formal_statement"].encode()).hexdigest(),
        "target_digest": problem["target_digest"],
        "environment_digest": problem["environment_digest"],
        "ledger": budget,
        "first_verified": {
            "receipt_id": first["aggregate_id"] if first else None,
            "seconds_since_experiment_start": frozen.event_elapsed_seconds(
                experiment["started_at"], first["created_at"]
            )
            if first
            else None,
            "settled_ceiling_cost_at_receipt_usd": frozen.settlement_cost_at(
                events, identifier, first["sequence"]
            )
            if first
            else None,
        },
        "whole_attempt": {
            "seconds_to_last_completed_task": frozen.event_elapsed_seconds(
                experiment["started_at"], last
            )
            if last
            else None,
            "spent_ceiling_usd": budget["spent_ceiling_usd"],
            "calculated_bill_estimate_usd": format(sum(exact_bills, Decimal(0)), "f")
            if all(value is not None for value in exact_bills)
            else None,
            "settled_native_responses": len(usage),
        },
        "finalization": {
            "active_workers": budget["active_workers"],
            "reserved_cost_usd": budget["reserved_cost_usd"],
            "reserved_tokens": budget["tokens_reserved"],
            "open_model_reservations": sum(
                r.get("status") not in {"settled", "released"} for r in model_reservations
            ),
            "nonterminal_tasks": sum(
                t.get("status") not in {"completed", "failed", "cancelled"} for t in tasks
            ),
            "unsettled_native_responses": runtime["unsettled_native_response_count"],
        },
        "root_task_count": len(roots),
        "delegated_task_count": len(children),
        "message_count": sum(r.get("experiment_id") == identifier for r in records["message"]),
        "runtime": runtime,
        "receipts": summary,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text())
    attempts = [a for a in manifest["attempts"] if a["label"] == args.label]
    if len(attempts) != 1:
        parser.error("exactly one known attempt label required")
    result = evaluate_attempt(attempts[0])
    frozen.write_output(args.output, result)
    print(json.dumps({"status": "written", "path": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
