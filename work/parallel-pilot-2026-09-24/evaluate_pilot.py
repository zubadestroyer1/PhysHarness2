"""Read-only, source-free metrics from canonical pilot SQLite and artifact records."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
USD = Decimal(1_000_000)
RETRIEVAL_TOOLS = {
    "search_knowledge",
    "read_dependency_bundle",
    "read_artifact",
    "read_artifact_chunk",
    "read_discussion_post",
    "read_research_message",
    "search_library_source",
    "lookup_library_source",
    "lookup_library_declaration",
    "working_context",
    "restart_brief",
    "history_page",
    "index_page",
    "research_graph_page",
    "mailbox_page",
}


class EvaluationError(Exception):
    pass


def required(value, field):
    if value is None:
        raise EvaluationError(f"required metric field unavailable: {field}")
    return value


def money(amount) -> str:
    return format(Decimal(amount) / USD, "f")


def read_artifact_bytes(root: Path, record: dict) -> bytes:
    digest = required(record.get("sha256"), "artifact.sha256")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise EvaluationError("invalid artifact digest")
    path = root / digest[:2] / digest
    if path.is_symlink() or path.parent.is_symlink():
        raise EvaluationError("artifact symlink refused")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise EvaluationError("artifact digest mismatch")
    return raw


def read_artifact(root: Path, record: dict) -> dict:
    return json.loads(read_artifact_bytes(root, record))


def load_canonical(config: dict):
    url = required(config.get("database_url"), "config.database_url")
    if not url.startswith("sqlite:///"):
        raise EvaluationError("this extractor requires a local SQLite URL")
    db_path = Path(url.removeprefix("sqlite:///"))
    if not db_path.is_file():
        raise EvaluationError("canonical database unavailable")
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    try:
        records = defaultdict(list)
        for kind, payload in connection.execute("SELECT kind,payload FROM records"):
            records[kind].append(json.loads(payload))
        events = [
            {
                "sequence": row[0],
                "kind": row[1],
                "aggregate_id": row[2],
                "payload": json.loads(row[3]),
                "created_at": row[4],
                "operation_id": row[5],
            }
            for row in connection.execute(
                "SELECT sequence,kind,aggregate_id,payload,created_at,operation_id "
                "FROM events ORDER BY sequence"
            )
        ]
        budgets = {
            row[0]: {
                "max_cost_usd": money(row[1]),
                "reserved_cost_usd": money(row[2]),
                "spent_ceiling_usd": money(row[3]),
                "active_workers": row[4],
                "tokens_reserved": row[5],
                "tokens_spent": row[6],
            }
            for row in connection.execute(
                "SELECT experiment_id,max_cost,reserved,spent,active_workers,"
                "tokens_reserved,tokens_spent FROM budgets"
            )
        }
        commands = {
            row[0]: {"operation_id": row[1], "result": json.loads(row[2])}
            for row in connection.execute("SELECT id,operation_id,result FROM commands")
        }
    finally:
        connection.rollback()
        connection.close()
    return records, events, budgets, commands


def exact_input_bill(usage: dict) -> Decimal | None:
    total = usage.get("input_tokens")
    output = usage.get("output_tokens")
    details = usage.get("input_tokens_details")
    if (
        not isinstance(details, dict)
        or "cache_write_tokens" not in details
        or "cached_tokens" not in details
    ):
        return None
    write, cached = details["cache_write_tokens"], details["cached_tokens"]
    if any(type(x) is not int or x < 0 for x in (total, output, write, cached)):
        raise EvaluationError("invalid native usage count")
    ordinary = total - write - cached
    if ordinary < 0:
        raise EvaluationError("native cache counts exceed input usage")
    value = (
        Decimal(ordinary) * 2
        + Decimal(cached) * Decimal("0.20")
        + Decimal(write) * Decimal("2.50")
        + Decimal(output) * 10
    ) / USD
    return value.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


def runtime_metrics(artifacts: list[dict], artifact_root: Path):
    usages, native_responses = {}, {}
    counts = Counter()
    tool_names = Counter()
    tool_results = {}
    errors = Counter()
    for artifact in artifacts:
        kind = artifact.get("artifact_kind")
        if kind not in {
            "runtime_event",
            "native_checkpoint",
            "native_archive",
            "execution_failure",
        }:
            continue
        content = read_artifact(artifact_root, artifact)
        if kind == "runtime_event":
            event_kind = required(content.get("kind"), "runtime_event.kind")
            operation_id = content.get("operation_id")
            payload = content.get("payload") or {}
            if event_kind == "usage":
                response_id = required(payload.get("response_id"), "usage.response_id")
                old = usages.get(response_id)
                if old and old["native_usage"] != payload.get("native_usage"):
                    raise EvaluationError("conflicting duplicate response usage")
                usages[response_id] = {
                    "operation_id": operation_id,
                    "native_usage": required(payload.get("native_usage"), "usage.native_usage"),
                    "artifact_created_at": artifact.get("created_at"),
                }
            elif event_kind == "tool_completed":
                if operation_id is None:
                    raise EvaluationError("tool event lacks operation ID")
                key = (operation_id, payload.get("name"))
                # Canonical runtime event artifacts are immutable/idempotent, but count once.
                if key not in tool_names:
                    tool_names[key] = 1
            elif event_kind == "provider_compaction_items":
                counts["provider_compaction_items"] += int(
                    required(payload.get("count"), "compaction.count")
                )
            elif event_kind == "compaction":
                counts["active_context_compactions"] += 1
        elif kind in {"native_checkpoint", "native_archive"}:
            state = content.get("native_state", {}) if kind == "native_checkpoint" else content
            for response in state.get("responses", []):
                response_id = response.get("id")
                if not response_id:
                    raise EvaluationError("native response lacks ID")
                old = native_responses.get(response_id)
                fields = {
                    "status": response.get("status"),
                    "incomplete_reason": (response.get("incomplete_details") or {}).get("reason"),
                }
                if old and old != fields:
                    raise EvaluationError("conflicting duplicate native response")
                native_responses[response_id] = fields
            for operation_id, entry in state.get("tool_results", {}).items():
                result = entry.get("result") if isinstance(entry, dict) else None
                error = result.get("error") if isinstance(result, dict) else None
                code = error.get("code") if isinstance(error, dict) else None
                if not isinstance(code, str):
                    continue
                if not re.fullmatch(r"[A-Z0-9_]{1,80}", code):
                    raise EvaluationError("unsafe tool rejection code")
                if operation_id in tool_results and tool_results[operation_id] != code:
                    raise EvaluationError("conflicting duplicate tool rejection")
                tool_results[operation_id] = code
        else:
            code = content.get("code")
            if not isinstance(code, str):
                raise EvaluationError("execution failure lacks safe code")
            errors[code] += 1
    completed_tools = Counter(name for _, name in tool_names)
    completed_names = {operation: name for operation, name in tool_names}
    safe_rejections = [
        {"operation_id": operation, "tool_name": completed_names.get(operation), "code": code}
        for operation, code in sorted(tool_results.items())
    ]
    return {
        "usages": usages,
        "native_response_count": len(native_responses),
        "unsettled_native_response_count": len(set(native_responses) - set(usages)),
        "response_cap_hits": sum(
            item["status"] == "incomplete" and item["incomplete_reason"] == "max_output_tokens"
            for item in native_responses.values()
        ),
        "other_incomplete_responses": sum(
            item["status"] == "incomplete" and item["incomplete_reason"] != "max_output_tokens"
            for item in native_responses.values()
        ),
        "tool_calls_completed": sum(completed_tools.values()),
        "tool_calls_by_name": dict(sorted(completed_tools.items())),
        "retrieval_tool_calls_completed": sum(completed_tools[name] for name in RETRIEVAL_TOOLS),
        "provider_compaction_items": counts["provider_compaction_items"],
        "active_context_compactions": counts["active_context_compactions"],
        "model_execution_error_codes": dict(sorted(errors.items())),
        "tool_rejections": safe_rejections,
        "tool_rejection_codes": dict(sorted(Counter(tool_results.values()).items())),
    }


def settlement_cost_at(events: list[dict], experiment_id: str, sequence: int) -> str:
    by_reservation = {}
    for event in events:
        if event["sequence"] > sequence:
            break
        if event["kind"] != "resources.settled" or event["aggregate_id"] != experiment_id:
            continue
        payload = event["payload"]
        if payload.get("state") == "settled":
            by_reservation[required(payload.get("id"), "settlement.id")] = Decimal(
                required(payload.get("actual_cost_usd"), "settlement.actual_cost_usd")
            )
    return format(sum(by_reservation.values(), Decimal(0)), "f")


def receipt_summary(
    receipt: dict, problem: dict, experiment: dict, artifacts_by_id: dict, artifact_root: Path
):
    artifact = artifacts_by_id.get(receipt.get("artifact_id"))
    if artifact is None:
        raise EvaluationError("receipt candidate artifact missing")
    expected_challenge = hashlib.sha256(problem["formal_statement"].encode()).hexdigest()
    candidate_digest = hashlib.sha256(read_artifact_bytes(artifact_root, artifact)).hexdigest()
    binding = {
        "same_experiment": receipt.get("experiment_id")
        == experiment["id"]
        == artifact.get("experiment_id"),
        "same_problem_revision": receipt.get("problem_revision_id") == problem["id"],
        "same_target_digest": receipt.get("target_digest")
        == problem.get("target_digest")
        == experiment.get("target_digest"),
        "same_challenge_sha256": receipt.get("challenge_sha256") == expected_challenge,
        "same_environment_digest": receipt.get("environment_digest")
        == problem.get("environment_digest"),
        "same_review_id": receipt.get("review_id") == problem.get("review_id"),
        "same_target_theorem": receipt.get("target_theorem") == problem.get("target_theorem"),
        "same_candidate_sha256": receipt.get("candidate_sha256")
        == artifact.get("sha256")
        == candidate_digest,
    }
    if receipt.get("status") == "verified" and not all(binding.values()):
        raise EvaluationError("verified receipt has invalid source or target binding")
    return {
        "id": receipt["id"],
        "status": receipt.get("status"),
        "assurance": receipt.get("assurance"),
        "code": receipt.get("code"),
        "candidate_artifact_id": artifact["id"],
        "candidate_sha256": artifact["sha256"],
        "candidate_bytes_sha256": candidate_digest,
        "axioms": required(receipt.get("axioms"), "receipt.axioms"),
        "checker_versions": required(receipt.get("checker_versions"), "receipt.checker_versions"),
        "claim_id": receipt.get("claim_id"),
        "publication": receipt.get("publication"),
        "target_digest": receipt.get("target_digest"),
        "problem_revision_id": receipt.get("problem_revision_id"),
        "environment_digest": receipt.get("environment_digest"),
        "bindings": binding,
        "binding_valid": all(binding.values()),
    }


def classify_tasks(tasks: list[dict]) -> tuple[list[dict], list[dict]]:
    children = [
        task
        for task in tasks
        if task.get("delegated_from_task_id") or task.get("reply_to_parent_task_id")
    ]
    child_ids = {task["id"] for task in children}
    return [task for task in tasks if task["id"] not in child_ids], children


def event_elapsed_seconds(started_at: str, event_at: str) -> float:
    elapsed = (
        datetime.fromisoformat(event_at) - datetime.fromisoformat(started_at)
    ).total_seconds()
    if elapsed < 0:
        raise EvaluationError("event predates experiment start")
    return elapsed


def command_key(project_id: str, key: str) -> str:
    raw = json.dumps(
        [project_id, "research-controller", key],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def evaluate(config: dict) -> dict:
    records, events, budgets, commands = load_canonical(config)
    artifact_root = Path(required(config.get("artifact_root"), "config.artifact_root"))
    experiments = {r["id"]: r for r in records["experiment"]}
    problems = {r["id"]: r for r in records["problem"]}
    artifact_index = {r["id"]: r for r in records["artifact"]}
    arms = config.get("arms")
    if not isinstance(arms, list) or len(arms) != 4:
        raise EvaluationError("exactly four configured arms required")
    output = {
        "protocol": "parallel-pilot-evaluation-v1",
        "observed_at": datetime.now(UTC).isoformat(),
        "interpretation": "descriptive observations; one run per cell cannot establish causality",
        "arms": [],
    }
    for arm in arms:
        identifier = required(arm.get("experiment_id"), "arm.experiment_id")
        experiment = required(experiments.get(identifier), "arm.experiment")
        problem = required(problems.get(experiment["problem_id"]), "arm.problem")
        budget = required(budgets.get(identifier), "arm.budget")
        tasks = [r for r in records["task"] if r.get("experiment_id") == identifier]
        sessions = [r for r in records["session"] if r.get("experiment_id") == identifier]
        artifacts = [r for r in records["artifact"] if r.get("experiment_id") == identifier]
        receipts = [r for r in records["verification"] if r.get("experiment_id") == identifier]
        own_events = [
            e
            for e in events
            if e["aggregate_id"] == identifier or e["payload"].get("experiment_id") == identifier
        ]
        runtime = runtime_metrics(artifacts, artifact_root)
        usage = runtime.pop("usages")
        if sessions and not usage and budget["tokens_spent"]:
            raise EvaluationError("spent model tokens lack native usage events")
        input_tokens = sum(
            required(u["native_usage"].get("input_tokens"), "usage.input_tokens")
            for u in usage.values()
        )
        output_tokens = sum(
            required(u["native_usage"].get("output_tokens"), "usage.output_tokens")
            for u in usage.values()
        )
        exact_components = [exact_input_bill(u["native_usage"]) for u in usage.values()]
        exact_available = all(value is not None for value in exact_components)
        exact_total = sum(exact_components, Decimal(0)) if exact_available else None
        verified_events = [e for e in own_events if e["kind"] == "verification.verified"]
        verified_events.sort(key=lambda e: e["sequence"])
        first = verified_events[0] if verified_events else None
        started = experiment.get("started_at")
        if first and not started:
            raise EvaluationError("verified receipt has no experiment start time")
        elapsed = event_elapsed_seconds(started, first["created_at"]) if first else None
        first_bill = None
        first_bill_reason = "no_verified_receipt" if first is None else None
        if first is not None:
            model_reservation_ids = {
                r["reservation_id"]
                for r in records["model_reservation"]
                if r.get("experiment_id") == identifier
            }
            settled_ids = {
                e["payload"]["id"]
                for e in own_events
                if e["kind"] == "resources.settled"
                and e["sequence"] <= first["sequence"]
                and e["payload"].get("id") in model_reservation_ids
                and e["payload"].get("state") == "settled"
            }
            matched_ids = set()
            before = []
            for u in usage.values():
                key = command_key(experiment["project_id"], f"model-settle:{u['operation_id']}")
                command = commands.get(key)
                if command is None:
                    continue
                reservation_id = command["result"].get("id")
                if reservation_id in settled_ids:
                    matched_ids.add(reservation_id)
                    before.append(u)
            billed = [exact_input_bill(u["native_usage"]) for u in before]
            if matched_ids != settled_ids or len(before) != len(matched_ids):
                first_bill_reason = "missing_usage_for_settlement"
            elif any(x is None for x in billed):
                first_bill_reason = "cache_write_details_unavailable"
            else:
                first_bill = format(sum(billed, Decimal(0)), "f")
        receipt_rows = [
            receipt_summary(r, problem, experiment, artifact_index, artifact_root) for r in receipts
        ]
        roots, children = classify_tasks(tasks)
        model_reservations = [
            r for r in records["model_reservation"] if r.get("experiment_id") == identifier
        ]
        task_ids = {task["id"] for task in tasks}
        completed_task_events = [
            event
            for event in events
            if event["kind"] == "task.completed" and event["aggregate_id"] in task_ids
        ]
        final_task_at = max((event["created_at"] for event in completed_task_events), default=None)
        if final_task_at and not started:
            raise EvaluationError("completed task has no experiment start time")
        # A generated usage artifact is the authoritative settled model-call count;
        # native response IDs from immutable checkpoints are deduplicated separately.
        output["arms"].append(
            {
                "label": arm["label"],
                "experiment_id": identifier,
                "experiment_status": experiment["status"],
                "time_to_last_completed_task_seconds": (
                    event_elapsed_seconds(started, final_task_at) if final_task_at else None
                ),
                "duration_basis": "experiment.started_at to final canonical task.completed event",
                "program": problem["program"],
                "sharing": experiment["sharing"],
                "target_digest": experiment["target_digest"],
                "ledger": budget,
                "finalization": {
                    "active_workers": budget["active_workers"],
                    "reserved_cost_usd": budget["reserved_cost_usd"],
                    "reserved_tokens": budget["tokens_reserved"],
                    "open_model_reservations": sum(
                        r.get("status") not in {"settled", "released"}
                        for r in model_reservations
                    ),
                    "nonterminal_tasks": sum(
                        t.get("status") not in {"completed", "failed", "cancelled"}
                        for t in tasks
                    ),
                    "pending_verifications": sum(r.get("status") == "queued" for r in receipts),
                },
                "model_usage": {
                    "settled_responses": len(usage),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "calculated_bill_estimate_usd": format(exact_total, "f")
                    if exact_total is not None
                    else None,
                    "calculated_bill_unavailable_reason": None
                    if exact_available
                    else "cache_write_details_unavailable",
                    "basis": (
                        "calculated estimate, not actual bill; standard rates per million: "
                        "$2 ordinary, $0.20 cached, $2.50 cache write, $10 output"
                    ),
                },
                "runtime": runtime,
                "coordination": {
                    "delegated_tasks": len(children),
                    "recruits_inferred_from_delegated_tasks": len(children),
                    "messages": sum(
                        r.get("experiment_id") == identifier for r in records["message"]
                    ),
                    "discussion_posts": sum(
                        e["kind"] == "discussion.post_created" for e in own_events
                    ),
                    "discussion_deliveries": len(
                        [
                            r
                            for r in records["discussion_delivery"]
                            if r.get("experiment_id") == identifier
                        ]
                    ),
                    "handoffs_issued": sum(
                        e["kind"] == "task.handoff-issue"
                        and e["aggregate_id"] in task_ids
                        for e in events
                    ),
                },
                "root_tasks": [{"id": t["id"], "status": t["status"]} for t in roots],
                "child_tasks": [
                    {
                        "id": t["id"],
                        "status": t["status"],
                        "parent_task_id": t.get("delegated_from_task_id")
                        or t.get("reply_to_parent_task_id"),
                        "detached": bool(t.get("detached")),
                    }
                    for t in children
                ],
                "receipts": receipt_rows,
                "first_verified": {
                    "receipt_id": first["aggregate_id"] if first else None,
                    "verified_at": first["created_at"] if first else None,
                    "seconds_since_experiment_start": elapsed,
                    "settled_ceiling_cost_at_receipt_usd": settlement_cost_at(
                        events, identifier, first["sequence"]
                    )
                    if first
                    else None,
                    "calculated_bill_estimate_at_receipt_usd": first_bill,
                    "calculated_bill_unavailable_reason": first_bill_reason,
                },
            }
        )
    probe_state = Path(config["private_directory"]) / "probe-state.json"
    if not probe_state.is_file():
        raise EvaluationError("probe state unavailable")
    probe = json.loads(probe_state.read_text())
    if probe.get("stage") != "schema_access_accepted":
        raise EvaluationError("probe has no reconciled accepted result")
    probe_ceiling = Decimal(required(probe.get("upper_cost_usd"), "probe.upper_cost_usd"))
    arm_spend = sum(Decimal(a["ledger"]["spent_ceiling_usd"]) for a in output["arms"])
    arm_reserved = sum(Decimal(a["ledger"]["reserved_cost_usd"]) for a in output["arms"])
    output["aggregate"] = {
        "probe_ceiling_usd": format(probe_ceiling, "f"),
        "arms_spent_ceiling_usd": format(arm_spend, "f"),
        "arms_reserved_usd": format(arm_reserved, "f"),
        "spent_plus_reserved_plus_probe_usd": format(arm_spend + arm_reserved + probe_ceiling, "f"),
        "authorized_ceiling_usd": "100.00",
    }
    if arm_spend + arm_reserved + probe_ceiling > Decimal("100.00"):
        raise EvaluationError("aggregate pilot envelope exceeded")
    return output


def write_output(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".evaluation-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--mode", choices=("snapshot", "final"), required=True)
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text())
        result = evaluate(config)
        if args.mode == "final":
            directory = Path(config["results_directory"])
            if any(not (directory / f"{arm['label']}.json").is_file() for arm in config["arms"]):
                raise EvaluationError("all four arm results required for final evaluation")
            for arm in result["arms"]:
                state = arm["finalization"]
                if (
                    arm["runtime"]["unsettled_native_response_count"]
                    or state["active_workers"]
                    or Decimal(state["reserved_cost_usd"])
                    or state["reserved_tokens"]
                    or state["open_model_reservations"]
                    or state["nonterminal_tasks"]
                    or state["pending_verifications"]
                ):
                    raise EvaluationError(f"arm {arm['label']} has unsettled canonical state")
                path = directory / f"{arm['label']}.json"
                supervisor = json.loads(path.read_text())
                if (
                    supervisor.get("experiment_id") != arm["experiment_id"]
                    or supervisor.get("status") != "completed"
                    or supervisor.get("remaining_task_ids")
                    or supervisor.get("pending_verification_ids")
                    or supervisor.get("verification_errors")
                    or supervisor.get("verification_worker_continues")
                ):
                    raise EvaluationError(f"arm {arm['label']} supervisor result is not final")
            destination = ROOT / "output.json"
        else:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            destination = ROOT / "snapshots" / f"{stamp}.json"
        write_output(destination, result)
        print(json.dumps({"status": "written", "path": str(destination)}))
        return 0
    except (EvaluationError, OSError, ValueError, KeyError, sqlite3.Error) as error:
        print(
            json.dumps({"status": "blocked", "code": type(error).__name__, "reason": str(error)}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
