#!/usr/bin/env python3
"""Normalize the S1 live-run arms into per-arm JSONL files for the audit.

Read-only on all run data: SQLite is opened with ``mode=ro`` and artifact contents are
read from the newest non-empty ``exports/<stamp>/`` directory (falling back to the live
``artifacts/`` store). Output goes to ``.superpowers/live-run/audit/data/<arm>/``.

Run from the repository root:
    PYTHONPATH=src .venv/bin/python .superpowers/live-run/audit/extract.py [ARM ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from physharness.execution.checkpoint_chunks import decode  # noqa: E402

ARMS = [
    "calibration-doeblin",
    "calibration-doeblin-r2",
    "calibration-aperiodic",
    "pilot-doeblin",
    "S",
    "S-r2",
    "I-01",
    "I-02",
    "I-03",
    "I-04",
    "I-05",
    "I-06",
    "I-07",
    "I-08",
    "single",
]
ARMS_DIR = REPO / ".state" / "s1" / "arms"
OUT_DIR = REPO / ".superpowers" / "live-run" / "audit" / "data"

PRICE_IN = Decimal("2.50")
PRICE_OUT = Decimal("10.00")
MICRO = Decimal("0.000001")

TEXT_LIMIT = 4000
EXCERPT = 400

# Never write secrets or local absolute paths.
_REDACTIONS = [
    (re.compile(re.escape(str(REPO))), "<repo>"),
    (re.compile(r"/Users/[^/\s\"'\\]+"), "/Users/<user>"),
    (re.compile(r"/home/[^/\s\"'\\]+"), "/home/<user>"),
    (re.compile(r"\borg-[A-Za-z0-9]{8,}"), "org-<redacted>"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "sk-<redacted>"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}"), "Bearer <redacted>"),
]


def redact(text):
    if not isinstance(text, str):
        return text
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def clip(text, limit):
    if text is None:
        return None
    text = redact(text)
    return text if len(text) <= limit else text[:limit]


def cost(inp, out):
    return (PRICE_IN * inp + PRICE_OUT * out) / 1_000_000


def ledger_cost(inp, out):
    # Same arithmetic as orchestration/pricing.py: ceil to micro-USD per settlement.
    return cost(inp, out).quantize(MICRO, rounding=ROUND_CEILING)


def ts(value):
    return datetime.fromisoformat(value) if value else None


def seconds(start, end):
    if not start or not end:
        return None
    return round((ts(end) - ts(start)).total_seconds(), 6)


def epoch_iso(value):
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def dumps(row):
    return json.dumps(row, ensure_ascii=False, allow_nan=False, default=str)


class Arm:
    def __init__(self, name):
        self.name = name
        self.base = ARMS_DIR / name
        exports = sorted(
            d for d in (self.base / "exports").iterdir() if d.is_dir() and any(d.iterdir())
        )
        self.export_dir = exports[-1] if exports else None
        self.db = sqlite3.connect(f"file:{self.base / 'harness.db'}?mode=ro", uri=True)
        self.read_misses = 0
        self.store_fallbacks = 0

    def content(self, sha):
        for path in (
            self.export_dir / sha if self.export_dir else None,
            self.base / "artifacts" / sha[:2] / sha,
        ):
            if path is not None and path.is_file():
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != sha:
                    continue
                if path.parent.name == sha[:2]:
                    self.store_fallbacks += 1
                return data
        self.read_misses += 1
        raise FileNotFoundError(sha)

    def records(self, kind, where="", params=()):
        sql = f"select id, payload from records where kind=? {where}"
        return [(rid, json.loads(p)) for rid, p in self.db.execute(sql, (kind, *params))]

    def artifacts(self, *kinds):
        marks = ",".join("?" for _ in kinds)
        return self.records(
            "artifact", f"and json_extract(payload,'$.artifact_kind') in ({marks})", kinds
        )


_LEAN_COMPILE = re.compile(r"(lake\s+env\s+lean|/bin/lean\s|\blean\s+\S+\.lean|lake\s+build)")
_INSPECT = re.compile(r"^\s*(cat|sed|head|tail|ls|find|grep|rg|wc|nl|awk)\b")


def shell_intent(command):
    """Coarse heuristic label for a free-form shell command."""
    if _LEAN_COMPILE.search(command):
        return "lean_compile"
    if _INSPECT.search(command):
        return "inspect"
    if re.match(r"^\s*python3?\b", command):
        return "python"
    return "other"


def argv_summary(op):
    inputs = op.get("inputs") or {}
    argv = inputs.get("argv") or []
    command = op.get("command")
    if command != "run" or not argv:
        detail = inputs.get("path") or inputs.get("source_path") or ""
        return {"kind": command, "intent": None, "excerpt": clip(str(detail), 200)}
    script = argv[2] if len(argv) > 2 else ""
    if argv[0].endswith("python3") and "-c" in argv:
        body = argv[argv.index("-c") + 1] if argv.index("-c") + 1 < len(argv) else ""
        if "'hits'" in body:
            return {"kind": "search_script", "intent": None, "excerpt": clip(argv[-1], 200)}
        if "hashlib" in body and "pathlib" in body:
            return {"kind": "read_source_script", "intent": None,
                    "excerpt": clip(" ".join(argv[argv.index("-c") + 2:]), 200)}
    if argv[:2] == ["sh", "-c"] and "lean_session.py" in script:
        return {"kind": "lean_session", "intent": None, "excerpt": clip(" ".join(argv[3:]), 200)}
    if argv[:2] == ["sh", "-c"] and "statement_check.py" in script:
        return {"kind": "statement_check", "intent": None, "excerpt": clip(" ".join(argv[3:]), 200)}
    if argv[:2] == ["sh", "-c"] and "lean-repl" in script:
        return {"kind": "repl_probe", "intent": None, "excerpt": clip(script, 200)}
    if argv[:2] in (["bash", "-lc"], ["sh", "-c"], ["bash", "-c"]):
        return {"kind": "shell", "intent": shell_intent(script), "excerpt": clip(script, 200)}
    joined = " ".join(argv)
    return {"kind": "shell_argv", "intent": shell_intent(joined), "excerpt": clip(joined, 200)}


def classify_hat(task):
    if task.get("hat") == "referee" or task.get("review_assignment"):
        return "referee"
    if task.get("synthesis"):
        return "synthesis"
    if task.get("delegated_from_task_id"):
        return "recruit"
    if task.get("created_by") == "research-controller" and not task.get("reply_to_parent_task_id"):
        return "root"
    return "other"


_SUGGESTED = re.compile(r"Suggested hat \(optional[^)]*\):\s*([A-Za-z_\-]+)")


def item_text(item):
    """Model-visible text of one native input item, and its kind label."""
    kind = item.get("type") or ("message" if "role" in item else "unknown")
    if kind == "message":
        content = item.get("content")
        if isinstance(content, str):
            return content
        parts = []
        for part in content or []:
            if isinstance(part, dict):
                parts.append(part.get("text") or part.get("refusal") or "")
        return "".join(parts)
    if kind == "function_call":
        return item.get("arguments") or ""
    if kind == "function_call_output":
        output = item.get("output")
        return output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    if kind == "reasoning":
        return "".join(
            part.get("text", "") for part in item.get("summary") or [] if isinstance(part, dict)
        )
    return ""


def output_status(text):
    """Classify a tool output string: harness rejection envelope vs. in-band failure."""
    info = {
        "outcome": None,
        "is_error": None,
        "error_code": None,
        "ok": None,
        "exit_code": None,
        "lean_error_messages": None,
        "signal": None,
    }
    if text is None:
        return info
    info["is_error"] = False
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        value = None
    if not isinstance(value, dict):
        info["outcome"] = "ok"
        return info
    error = value.get("error")
    if isinstance(error, dict):
        info["is_error"] = True
        info["error_code"] = error.get("code")
    if isinstance(value.get("ok"), bool):
        info["ok"] = value["ok"]
    if isinstance(value.get("exit_code"), int):
        info["exit_code"] = value["exit_code"]
    messages = value.get("messages")
    if isinstance(messages, list):
        info["lean_error_messages"] = sum(
            1 for m in messages if isinstance(m, dict) and m.get("severity") == "error"
        )
    signal = value.get("_research_runtime_signal")
    if isinstance(signal, dict):
        info["signal"] = signal.get("kind")
    if info["is_error"]:
        info["outcome"] = "rejected"
    elif info["ok"] is False or (info["exit_code"] not in (None, 0)):
        info["outcome"] = "failed"
    else:
        info["outcome"] = "ok"
    return info


def extract(arm_name):
    arm = Arm(arm_name)
    out = OUT_DIR / arm_name
    out.mkdir(parents=True, exist_ok=True)
    concerns = []

    # --- canonical records -------------------------------------------------------------
    tasks = dict(arm.records("task"))
    branches = dict(arm.records("branch"))
    sessions = dict(arm.records("session"))
    links = [p for _, p in arm.records("continuation_link")]
    reviews = defaultdict(list)
    for _, review in arm.records("commons_review"):
        reviews[review.get("task_id")].append(review)
    workspace_ops = dict(arm.records("workspace_operation"))

    artifact_seq = {
        aid: seq
        for aid, seq in arm.db.execute(
            "select aggregate_id, sequence from events where kind='artifact.created'"
        )
    }

    # Events: tasks, session saves, workspace operation timing.
    task_events = defaultdict(list)
    save_times = defaultdict(list)
    ws_events = defaultdict(dict)
    for kind, aggregate, operation, payload, created in arm.db.execute(
        "select kind, aggregate_id, operation_id, payload, created_at from events "
        "where kind like 'task.%' or kind='session.saved' or kind like 'workspace.operation.%' "
        "order by sequence"
    ):
        if kind == "session.saved":
            save_times[aggregate].append(created)
        elif kind.startswith("task."):
            task_events[aggregate].append({"kind": kind, "at": created, "payload": json.loads(payload)})
        else:
            ws_events[operation].setdefault(kind.rsplit(".", 1)[-1], created)

    # Newest native checkpoint per native session id.
    newest_checkpoint = {}
    for aid, meta in arm.artifacts("native_checkpoint"):
        sid = (meta.get("provenance") or {}).get("session_id")
        key = (meta.get("created_at"), artifact_seq.get(aid, 0))
        if sid and (sid not in newest_checkpoint or key > newest_checkpoint[sid][0]):
            newest_checkpoint[sid] = (key, aid, meta)
    checkpoint_meta = {aid: meta for aid, meta in arm.artifacts("native_checkpoint")}
    archives = {}
    for aid, meta in arm.artifacts("native_archive"):
        prov = meta.get("provenance") or {}
        archives[(prov.get("session_id"), prov.get("archive_digest"))] = meta
    failures = {}
    failures_by_task = defaultdict(list)
    for aid, meta in arm.artifacts("execution_failure"):
        try:
            body = json.loads(arm.content(meta["sha256"]))
        except (FileNotFoundError, ValueError):
            continue
        failure = {
            "code": body.get("code"),
            "error_type": body.get("error_type"),
            "at": meta.get("created_at"),
            "operation_id": body.get("operation_id"),
        }
        if body.get("operation_id"):
            failures[body["operation_id"]] = {**failure, "match": "operation_id"}
        elif body.get("task_id"):
            failures_by_task[body["task_id"]].append({**failure, "match": "task_id"})

    # Runtime events grouped by native session, in canonical write order.
    runtime = defaultdict(list)
    for aid, meta in arm.artifacts("runtime_event"):
        event = json.loads(arm.content(meta["sha256"]))
        event["at"] = meta.get("created_at")
        event["seq"] = artifact_seq.get(aid, 0)
        event["task_id"] = (meta.get("provenance") or {}).get("task_id")
        runtime[event.get("session_id")].append(event)
    for events in runtime.values():
        events.sort(key=lambda e: (e["seq"] or 0, e["at"] or ""))

    by_native = {p["native_record_id"]: rid for rid, p in sessions.items()}
    unknown_sessions = sorted(sid for sid in runtime if sid not in by_native)
    if unknown_sessions:
        concerns.append(f"runtime events for {len(unknown_sessions)} session(s) without a session record")

    predecessor = {}
    successor = {}
    for link in links:
        src, dst = link.get("source_session_record_id"), link.get("successor_record_id")
        if src and dst:
            successor[src] = {"record_id": dst, "session_id": link.get("successor_session_id"),
                              "link_id": link.get("id"), "mode": link.get("continuation_mode"),
                              "status": link.get("status")}
            predecessor[dst] = {"record_id": src, "session_id": link.get("source_session_id"),
                                "link_id": link.get("id"), "mode": link.get("continuation_mode"),
                                "status": link.get("status")}
        elif src:
            successor.setdefault(src, {"record_id": None, "session_id": None,
                                       "link_id": link.get("id"), "mode": link.get("continuation_mode"),
                                       "status": link.get("status")})

    ws_by_call = defaultdict(list)
    ws_unlinked_by_task = defaultdict(list)
    for oid, op in workspace_ops.items():
        call_op = (op.get("inputs") or {}).get("operation_id")
        if isinstance(call_op, str) and ":call_" in call_op:
            parts = call_op.split(":", 2)
            ws_by_call[f"{parts[0]}:{parts[1]}"].append(oid)
        else:
            ws_unlinked_by_task[op.get("task_id")].append(oid)

    def ws_row(oid, method):
        op = workspace_ops[oid]
        timing = ws_events.get(oid, {})
        start = timing.get("pending") or op.get("created_at")
        end = timing.get("completed") or timing.get("rejected")
        result = op.get("result") or {}
        diagnostics = result.get("diagnostics") if isinstance(result, dict) else None
        return {
            "workspace_operation_id": oid,
            "link": method,
            "command": op.get("command"),
            "sub_operation": ((op.get("inputs") or {}).get("operation_id") or "").split(":", 2)[2]
            if ((op.get("inputs") or {}).get("operation_id") or "").count(":") >= 2
            else None,
            "argv": argv_summary(op),
            "status": op.get("status"),
            "pending_at": start,
            "completed_at": end,
            "duration_s": seconds(start, end),
            "exit_code": result.get("exit_code") if isinstance(result, dict) else None,
            "stdout_chars": len(result.get("stdout") or "") if isinstance(result, dict) else None,
            "stderr_chars": len(result.get("stderr") or "") if isinstance(result, dict) else None,
            "limit_reason": (diagnostics or {}).get("limit_reason") if isinstance(diagnostics, dict) else None,
        }

    # --- sessions, turns, tool calls, messages ----------------------------------------
    session_rows, turn_rows, call_rows, message_rows = [], [], [], []
    ws_linked = {}
    final_inputs = {}  # record id -> list of canonical item digests (for inheritance)
    decode_errors = []

    ordered_sessions = sorted(sessions.items(), key=lambda kv: (kv[1].get("created_at"), kv[0]))
    for record_id, record in ordered_sessions:
        sid = record["native_record_id"]
        task = tasks.get(record.get("task_id"), {})
        branch = branches.get(record.get("branch_id"), {})
        hat = classify_hat(task) if task else "other"

        # Latest checkpoint (newest artifact; the record pointer is cross-checked).
        pointer = record.get("checkpoint_artifact_id")
        chosen = newest_checkpoint.get(sid)
        checkpoint_id = chosen[1] if chosen else pointer
        meta = checkpoint_meta.get(checkpoint_id)
        state, csession = {}, {}
        try:
            raw = arm.content(meta["sha256"])
            checkpoint = decode(raw, lambda ref: arm.content(ref["sha256"]))
            state = checkpoint.native_state
            csession = checkpoint.session.model_dump(mode="json")
        except Exception as error:  # keep going; report the gap
            decode_errors.append({"session_id": sid, "error": f"{type(error).__name__}: {error}"})

        own_archives = []
        for digest in state.get("archives", []):
            archive_meta = archives.get((sid, digest))
            if archive_meta is None:
                concerns.append(f"{sid}: archive {digest} missing")
                continue
            own_archives.append(json.loads(arm.content(archive_meta["sha256"])))
        full_input = [item for a in own_archives for item in a.get("input_prefix", [])]
        archived_count = len(full_input)
        full_input += state.get("input", [])
        responses = {}
        for bundle in own_archives + [state]:
            for response in bundle.get("responses", []):
                responses[response.get("id")] = response
        outputs_by_call = {}
        for item in full_input:
            if item.get("type") == "function_call_output":
                outputs_by_call[item.get("call_id")] = item.get("output")

        # Inherited prefix for native continuations (portable ones start fresh).
        digests = [hashlib.sha256(json.dumps(i, sort_keys=True).encode()).hexdigest() for i in full_input]
        final_inputs[record_id] = digests
        inherited = 0
        pred = predecessor.get(record_id)
        if pred and pred["record_id"] in final_inputs:
            prior = final_inputs[pred["record_id"]]
            while inherited < min(len(prior), len(digests)) and prior[inherited] == digests[inherited]:
                inherited += 1

        # Turns from runtime events.
        turns = []
        current = None
        for event in runtime.get(sid, []):
            kind = event.get("kind")
            payload = event.get("payload") or {}
            if kind == "generation_started":
                current = {
                    "operation_id": event.get("operation_id"),
                    "started_at": event["at"],
                    "input_reserved": payload.get("input_tokens_reserved"),
                    "output_reserved": payload.get("output_tokens_reserved"),
                    "usage": None,
                    "ended_at": None,
                    "tools_completed": [],
                    "compaction_events": [],
                }
                turns.append(current)
            elif kind == "usage":
                match = next((t for t in reversed(turns) if t["operation_id"] == event.get("operation_id")), None)
                if match is None:
                    concerns.append(f"{sid}: usage without generation_started {event.get('operation_id')}")
                    match = {"operation_id": event.get("operation_id"), "started_at": None,
                             "input_reserved": None, "output_reserved": None,
                             "tools_completed": [], "compaction_events": []}
                    turns.append(match)
                match["usage"] = payload
                match["ended_at"] = event["at"]
            elif kind == "tool_completed":
                target = current or (turns[-1] if turns else None)
                if target is not None:
                    target["tools_completed"].append(
                        {"operation_id": event.get("operation_id"), "name": payload.get("name"), "at": event["at"]}
                    )
            elif kind in {"compaction", "provider_compaction_items"} and turns:
                turns[-1]["compaction_events"].append({"kind": kind, "at": event["at"], **payload})

        turn_of_response = {}
        session_tokens = defaultdict(int)
        session_cost = Decimal(0)
        session_ledger_cost = Decimal(0)
        session_calls = 0
        session_errors = 0
        session_failures = 0
        for index, turn in enumerate(turns, 1):
            usage = turn["usage"] or {}
            native = usage.get("native_usage") or {}
            in_details = native.get("input_tokens_details") or {}
            out_details = native.get("output_tokens_details") or {}
            inp = usage.get("input_tokens") or 0
            outp = usage.get("output_tokens") or 0
            cached = in_details.get("cached_tokens") or 0
            response = responses.get(usage.get("response_id")) if usage else None
            if usage:
                turn_of_response[usage.get("response_id")] = index
            output_items = (response or {}).get("output") or []
            calls = [item for item in output_items if item.get("type") == "function_call"]
            failure = failures.get(turn["operation_id"])
            if failure is None and not usage and failures_by_task.get(record.get("task_id")):
                failure = failures_by_task[record.get("task_id")][-1]
            turn_cost = cost(inp, outp) if usage else Decimal(0)
            turn_ledger = ledger_cost(inp, outp) if usage else Decimal(0)
            session_cost += turn_cost
            session_ledger_cost += turn_ledger
            for key, value in (
                ("input_tokens", inp),
                ("cached_tokens", cached),
                ("cache_write_tokens", in_details.get("cache_write_tokens") or 0),
                ("output_tokens", outp),
                ("reasoning_tokens", out_details.get("reasoning_tokens") or 0),
            ):
                session_tokens[key] += value
            provider_created = (response or {}).get("created_at")
            provider_completed = (response or {}).get("completed_at")
            started_at = turn["started_at"]
            turn_rows.append(
                {
                    "arm": arm_name,
                    "session_id": sid,
                    "session_record_id": record_id,
                    "task_id": record.get("task_id"),
                    "hat": hat,
                    "operation_id": turn["operation_id"],
                    "turn": index,
                    "response_id": usage.get("response_id"),
                    "completed": bool(usage),
                    "failure": failure,
                    "started_at": started_at,
                    "ended_at": turn["ended_at"],
                    "latency_s": seconds(started_at, turn["ended_at"]),
                    "provider_created_at": epoch_iso(provider_created),
                    "provider_completed_at": epoch_iso(provider_completed),
                    "provider_latency_s": (provider_completed - provider_created)
                    if provider_created is not None and provider_completed is not None
                    else None,
                    "pre_provider_s": round(provider_created - ts(started_at).timestamp(), 3)
                    if provider_created is not None and started_at
                    else None,
                    "input_tokens": inp,
                    "cached_tokens": cached,
                    "cache_write_tokens": in_details.get("cache_write_tokens") or 0,
                    "uncached_input_tokens": inp - cached,
                    "output_tokens": outp,
                    "reasoning_tokens": out_details.get("reasoning_tokens") or 0,
                    "input_reserved": turn["input_reserved"],
                    "output_reserved": turn["output_reserved"],
                    "cost_usd": str(turn_cost.quantize(Decimal("0.000000001"))),
                    "cost_usd_ledger": str(turn_ledger),
                    "response_status": (response or {}).get("status"),
                    "response_found": response is not None,
                    "output_item_types": [item.get("type") for item in output_items],
                    "assistant_text_chars": sum(
                        len(item_text(item)) for item in output_items if item.get("type") == "message"
                    ),
                    "tool_calls": [call.get("name") for call in calls]
                    or ([t["name"] for t in turn["tools_completed"]] if response is None else []),
                    "compaction_events": turn["compaction_events"],
                }
            )

            # Tool calls of this turn.
            completed_by_op = {t["operation_id"]: t for t in turn["tools_completed"]}
            previous_end = turn["ended_at"]
            call_items = calls or [
                {"call_id": t["operation_id"].split(":", 1)[1], "name": t["name"], "arguments": None}
                for t in turn["tools_completed"]
            ]
            for call in call_items:
                call_id = call.get("call_id")
                tool_op = f"{sid}:{call_id}"
                done = completed_by_op.get(tool_op)
                output = outputs_by_call.get(call_id)
                status = output_status(output)
                start = previous_end
                end = done["at"] if done else None
                linked = [ws_row(oid, "operation_id") for oid in sorted(
                    ws_by_call.get(tool_op, []),
                    key=lambda o: ws_events.get(o, {}).get("pending") or workspace_ops[o].get("created_at") or "",
                )]
                if start and end:
                    for oid in ws_unlinked_by_task.get(record.get("task_id"), []):
                        pending = ws_events.get(oid, {}).get("pending") or workspace_ops[oid].get("created_at")
                        if pending and start <= pending <= end:
                            linked.append(ws_row(oid, "time_window"))
                    linked.sort(key=lambda r: r["pending_at"] or "")
                for row in linked:
                    ws_linked[row["workspace_operation_id"]] = (sid, call_id)
                session_calls += 1
                session_errors += bool(status["is_error"])
                session_failures += status["outcome"] == "failed"
                call_rows.append(
                    {
                        "arm": arm_name,
                        "session_id": sid,
                        "task_id": record.get("task_id"),
                        "hat": hat,
                        "turn": index,
                        "call_id": call_id,
                        "tool": call.get("name"),
                        "arguments": clip(call.get("arguments"), EXCERPT),
                        "arguments_chars": len(call.get("arguments") or ""),
                        "output_chars": len(output) if output is not None else None,
                        "output_excerpt": clip(output, EXCERPT),
                        "output_found": output is not None,
                        **status,
                        "started_at": start,
                        "ended_at": end,
                        "duration_s": seconds(start, end),
                        "workspace_ops": linked,
                        "workspace_ops_duration_s": round(
                            sum(r["duration_s"] or 0 for r in linked), 6
                        ) if linked else None,
                        "argv_summary": [r["argv"] for r in linked if r["command"] == "run"],
                    }
                )
                if end:
                    previous_end = end

        # Messages: full reassembled transcript.
        item_turn = {}
        for response_id, index in turn_of_response.items():
            for item in (responses.get(response_id) or {}).get("output") or []:
                if item.get("id"):
                    item_turn[item["id"]] = index
        call_names = {
            item.get("call_id"): item.get("name")
            for item in full_input
            if item.get("type") == "function_call"
        }
        last_produced = 0
        initial_anchor = state.get("initial_anchor")
        first_user_seen = False
        compaction_pending = False
        for position, item in enumerate(full_input):
            kind = item.get("type") or ("message" if "role" in item else "unknown")
            role = item.get("role")
            produced = item_turn.get(item.get("id")) if item.get("id") else None
            is_inherited = position < inherited
            if produced:
                last_produced = produced
                turn = produced
                direction = "model_output"
            else:
                turn = None if is_inherited else last_produced + 1
                direction = "model_output" if role == "assistant" or kind in {
                    "reasoning", "function_call", "compaction"
                } else "model_input"
            if kind == "compaction":
                compaction_pending = True
            text = item_text(item)
            subtype = None
            if kind == "message" and role == "user":
                content = item.get("content")
                parsed = None
                if isinstance(content, str):
                    try:
                        parsed = json.loads(content)
                    except ValueError:
                        parsed = None
                if not first_user_seen and content == initial_anchor:
                    subtype = "initial_prompt"
                elif isinstance(parsed, dict) and parsed.get("type") in {
                    "research_network_updates", "research_runtime_note"
                }:
                    subtype = parsed["type"]
                elif isinstance(parsed, dict) and "objective" in parsed:
                    subtype = "compaction_anchor" if compaction_pending else "continuation_prompt"
                    compaction_pending = False
                else:
                    subtype = "user_text"
                first_user_seen = True
            encrypted = item.get("encrypted_content")
            message_rows.append(
                {
                    "arm": arm_name,
                    "session_id": sid,
                    "seq": position,
                    "segment": "archive" if position < archived_count else "active",
                    "inherited": is_inherited,
                    "turn": turn,
                    "direction": direction,
                    "type": kind,
                    "role": role,
                    "subtype": subtype,
                    "item_id": item.get("id"),
                    "call_id": item.get("call_id"),
                    "tool": item.get("name") or call_names.get(item.get("call_id"))
                    if kind in {"function_call", "function_call_output"}
                    else None,
                    "chars": len(text),
                    "truncated": len(text) > TEXT_LIMIT,
                    "text": clip(text, TEXT_LIMIT),
                    "encrypted_chars": len(encrypted) if isinstance(encrypted, str) else None,
                }
            )

        saves = save_times.get(record_id, [])
        timed = [t for t in turns if t["started_at"]]
        ended = [t for t in turns if t["ended_at"]]
        compaction_count = max(
            state.get("provider_compaction_count", 0),
            sum(1 for t in turns for c in t["compaction_events"] if c["kind"] == "provider_compaction_items"),
        )
        model = record.get("model") or {}
        session_rows.append(
            {
                "arm": arm_name,
                "session_id": sid,
                "session_record_id": record_id,
                "task_id": record.get("task_id"),
                "hat": hat,
                "task_hat_field": task.get("hat"),
                "branch_id": record.get("branch_id"),
                "lab": branch.get("lab"),
                "status": record.get("status"),
                "checkpoint_status": csession.get("status"),
                "model": model.get("model"),
                "reasoning_effort": ((model.get("parameters") or {}).get("reasoning") or {}).get("effort"),
                "created_at": record.get("created_at"),
                "first_turn_started_at": timed[0]["started_at"] if timed else None,
                "last_turn_ended_at": ended[-1]["ended_at"] if ended else None,
                "last_save_at": saves[-1] if saves else None,
                "save_count": len(saves),
                "wall_s": seconds(record.get("created_at"), saves[-1] if saves else None),
                "turns": csession.get("turns"),
                "generation_attempts": len(turns),
                "completed_turns": sum(1 for t in turns if t["usage"]),
                "failed_generations": sum(1 for t in turns if not t["usage"]),
                "input_tokens": session_tokens["input_tokens"],
                "cached_input_tokens": session_tokens["cached_tokens"],
                "cache_write_tokens": session_tokens["cache_write_tokens"],
                "uncached_input_tokens": session_tokens["input_tokens"] - session_tokens["cached_tokens"],
                "output_tokens": session_tokens["output_tokens"],
                "reasoning_tokens": session_tokens["reasoning_tokens"],
                "record_input_tokens": record.get("input_tokens"),
                "record_output_tokens": record.get("output_tokens"),
                "cost_usd": str(session_cost.quantize(Decimal("0.000001"))),
                "cost_usd_ledger": str(session_ledger_cost),
                "harness_price_discounts_cached": False,
                "compaction_count": compaction_count,
                "active_input_epoch": state.get("active_input_epoch", 0),
                "archives": len(state.get("archives", [])),
                "inherited_archive_refs": len(state.get("archive_refs", [])),
                "lineage_input_offset": state.get("cumulative_input_offset", 0),
                "lineage_output_offset": state.get("cumulative_output_offset", 0),
                "predecessor": predecessor.get(record_id),
                "successor": successor.get(record_id),
                "transcript_items": len(full_input),
                "inherited_items": inherited,
                "tool_calls": session_calls,
                "tool_rejections": session_errors,
                "tool_failures": session_failures,
                "network_deliveries": len(state.get("network_delivery_ids", [])),
                "turn_note_last_turn": state.get("turn_note_turns"),
                "checkpoint_artifact_id": checkpoint_id,
                "checkpoint_matches_record": checkpoint_id == pointer,
            }
        )

    # --- workspace operations (all, with link to tool calls) --------------------------
    ws_rows = []
    for oid, op in sorted(
        workspace_ops.items(),
        key=lambda kv: (ws_events.get(kv[0], {}).get("pending") or kv[1].get("created_at") or "", kv[0]),
    ):
        row = ws_row(oid, None)
        link = ws_linked.get(oid)
        row.update(
            {
                "arm": arm_name,
                "task_id": op.get("task_id"),
                "workspace_id": op.get("workspace_id"),
                "session_id": link[0] if link else None,
                "call_id": link[1] if link else None,
            }
        )
        row.pop("link")
        ws_rows.append(row)

    # --- tasks ----------------------------------------------------------------------------
    task_rows = []
    sessions_by_task = defaultdict(list)
    for row in session_rows:
        sessions_by_task[row["task_id"]].append(row)
    for tid, task in sorted(tasks.items(), key=lambda kv: (kv[1].get("created_at"), kv[0])):
        events = task_events.get(tid, [])

        def first(kind):
            return next((e["at"] for e in events if e["kind"] == kind), None)

        def last(kind):
            return next((e["at"] for e in reversed(events) if e["kind"] == kind), None)

        branch = branches.get(task.get("branch_id"), {})
        suggested = _SUGGESTED.search(task.get("objective") or "")
        own = sessions_by_task.get(tid, [])
        task_reviews = reviews.get(tid, [])
        superseded = [e for e in events if e["kind"] == "task.superseded_by_verification"]
        task_rows.append(
            {
                "arm": arm_name,
                "task_id": tid,
                "hat": classify_hat(task),
                "task_hat_field": task.get("hat"),
                "suggested_hat": suggested.group(1) if suggested else None,
                "branch_id": task.get("branch_id"),
                "branch_title": clip(branch.get("title"), 200),
                "branch_relation": branch.get("relation"),
                "branch_hat": branch.get("hat"),
                "lab": branch.get("lab"),
                "status": task.get("status"),
                "execution_status": task.get("execution_status"),
                "error_code": task.get("error_code"),
                "created_at": task.get("created_at"),
                "queued_at": first("task.queued"),
                "leased_at": first("task.leased"),
                "completed_at": last("task.completed"),
                "queue_wait_s": seconds(first("task.queued"), first("task.leased")),
                "lease_to_complete_s": seconds(first("task.leased"), last("task.completed")),
                "events": [{"kind": e["kind"], "at": e["at"]} for e in events],
                "objective_excerpt": clip(task.get("objective"), 300),
                "objective_chars": len(task.get("objective") or ""),
                "created_by": task.get("created_by"),
                "delegated_from_task_id": task.get("delegated_from_task_id"),
                "requested_by": (task.get("review_assignment") or {}).get("requested_by"),
                "review_assignment": {
                    k: (task.get("review_assignment") or {}).get(k)
                    for k in ("node_id", "scope", "cross_model")
                } if task.get("review_assignment") else None,
                "synthesis": task.get("synthesis"),
                "detached": task.get("detached"),
                "continuation_count": task.get("continuation_count"),
                "sessions": [s["session_id"] for s in own],
                "input_tokens": sum(s["input_tokens"] for s in own),
                "output_tokens": sum(s["output_tokens"] for s in own),
                "cost_usd": str(sum(Decimal(s["cost_usd_ledger"]) for s in own)),
                "tool_calls": sum(s["tool_calls"] for s in own),
                "outcome": {
                    "status": task.get("status"),
                    "execution_status": task.get("execution_status"),
                    "error_code": task.get("error_code"),
                    "terminal_recovery": task.get("terminal_recovery"),
                    "evidence_count": len(task.get("evidence_ids") or []),
                    "review_verdicts": [
                        {"scope": r.get("scope"), "verdict": r.get("verdict"), "stale": r.get("stale")}
                        for r in task_reviews
                    ],
                    "superseded_by_verification": [e["payload"].get("receipt_id") for e in superseded],
                    "return_result": clip(json.dumps(task.get("return_result"), ensure_ascii=False), 300)
                    if task.get("return_result") is not None
                    else None,
                },
            }
        )

    # --- write -----------------------------------------------------------------------------
    for filename, rows in (
        ("sessions.jsonl", session_rows),
        ("turns.jsonl", turn_rows),
        ("tool_calls.jsonl", call_rows),
        ("tasks.jsonl", task_rows),
        ("messages.jsonl", message_rows),
        ("workspace_ops.jsonl", ws_rows),
    ):
        with open(out / filename, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(dumps(row) + "\n")

    # --- sanity -----------------------------------------------------------------------------
    budget = arm.db.execute(
        "select max_cost, spent, tokens_spent, reserved, tokens_reserved from budgets"
    ).fetchall()
    reservations = arm.db.execute(
        "select state, count(*), coalesce(sum(actual),0), coalesce(sum(tokens_actual),0) "
        "from reservations group by state"
    ).fetchall()
    metrics_files = sorted((arm.base / "metrics").glob("*.json"))
    metrics = json.loads(metrics_files[-1].read_text()) if metrics_files else {}
    inp = sum(r["input_tokens"] for r in turn_rows)
    outp = sum(r["output_tokens"] for r in turn_rows)
    exact = sum((Decimal(r["cost_usd"]) for r in turn_rows), Decimal(0))
    ledger = sum((Decimal(r["cost_usd_ledger"]) for r in turn_rows), Decimal(0))
    ledger_spent = Decimal(sum(b[1] for b in budget)) / 1_000_000 if budget else None
    ledger_tokens = sum(b[2] for b in budget) if budget else None
    metric_tools = (metrics.get("tool_call_mix") or {}).get("by_tool") or {}
    our_tools = defaultdict(int)
    for row in call_rows:
        our_tools[row["tool"]] += 1
    tool_diff = {
        name: {"ours": our_tools.get(name, 0), "metrics": metric_tools.get(name, 0)}
        for name in sorted(set(our_tools) | set(metric_tools))
        if our_tools.get(name, 0) != metric_tools.get(name, 0)
    }
    record_in = sum(s.get("input_tokens") or 0 for s in sessions.values())
    record_out = sum(s.get("output_tokens") or 0 for s in sessions.values())
    sanity = {
        "export_dir": str(arm.export_dir.relative_to(REPO)) if arm.export_dir else None,
        "artifact_store_fallbacks": arm.store_fallbacks,
        "artifact_read_misses": arm.read_misses,
        "counts": {
            "sessions": len(session_rows),
            "turns": len(turn_rows),
            "completed_turns": sum(1 for r in turn_rows if r["completed"]),
            "tool_calls": len(call_rows),
            "tasks": len(task_rows),
            "messages": len(message_rows),
            "workspace_ops": len(ws_rows),
            "workspace_ops_linked_to_calls": sum(1 for r in ws_rows if r["call_id"]),
        },
        "ours": {
            "input_tokens": inp,
            "cached_input_tokens": sum(r["cached_tokens"] for r in turn_rows),
            "output_tokens": outp,
            "reasoning_tokens": sum(r["reasoning_tokens"] for r in turn_rows),
            "total_tokens": inp + outp,
            "cost_usd_exact": str(exact.quantize(MICRO)),
            "cost_usd_per_turn_ceil": str(ledger),
        },
        "session_records": {"input_tokens": record_in, "output_tokens": record_out},
        "ledger_budgets": {
            "spent_usd": str(ledger_spent) if ledger_spent is not None else None,
            "tokens_spent": ledger_tokens,
            "reserved_usd_outstanding": str(Decimal(sum(b[3] for b in budget)) / 1_000_000) if budget else None,
            "reservations_by_state": {
                state: {"count": n, "actual_usd": str(Decimal(a) / 1_000_000), "tokens_actual": t}
                for state, n, a, t in reservations
            },
        },
        "metrics": {
            "file": metrics_files[-1].name if metrics_files else None,
            "spent_cost_usd": metrics.get("spent_cost_usd"),
            "tokens_spent": metrics.get("tokens_spent"),
            "model_sessions": (metrics.get("evidence") or {}).get("model_sessions"),
            "tool_calls_total": (metrics.get("tool_call_mix") or {}).get("total"),
        },
        "match": {
            "tokens_vs_ledger": (inp + outp) == ledger_tokens,
            "cost_ceil_vs_ledger": ledger_spent is not None and ledger == ledger_spent,
            "tokens_vs_metrics": metrics.get("tokens_spent") == inp + outp,
            "cost_vs_metrics": metrics.get("spent_cost_usd") is not None
            and Decimal(metrics["spent_cost_usd"]) == ledger,
            "tokens_vs_session_records": record_in == inp and record_out == outp,
            "tool_calls_vs_metrics": (metrics.get("tool_call_mix") or {}).get("total") == len(call_rows),
        },
        "tool_count_differences_vs_metrics": tool_diff,
        "decode_errors": decode_errors,
        "unknown_runtime_sessions": unknown_sessions,
        "calls_without_output": sum(1 for r in call_rows if not r["output_found"]),
        "calls_without_completion_event": sum(1 for r in call_rows if not r["ended_at"]),
        "turns_without_response_in_checkpoint": sum(
            1 for r in turn_rows if r["completed"] and not r["response_found"]
        ),
        "concerns": concerns,
    }
    notes = [
        f"Ledger cost = per-turn cost ceil-rounded to 1e-6 USD (pricing.py); the exact sum is "
        f"{(ledger - exact).quantize(MICRO)} USD lower over {len(turn_rows)} turns."
    ]
    in_flight = sanity["calls_without_completion_event"]
    metric_total = sanity["metrics"]["tool_calls_total"]
    if metric_total is not None and metric_total != len(call_rows):
        if len(call_rows) - in_flight == metric_total:
            notes.append(
                f"Tool calls: {in_flight} function call(s) were in flight when the run stopped "
                "(no output, no tool_completed event); metrics count only completed calls."
            )
        else:
            notes.append("Tool call count differs from metrics for an unexplained reason.")
    failed = sanity["counts"]["turns"] - sanity["counts"]["completed_turns"]
    if failed:
        notes.append(
            f"{failed} generation(s) have no usage (failed/cancelled); they settle at zero and "
            "carry no tokens."
        )
    sanity["explanations"] = notes
    return sanity


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("arms", nargs="*", default=ARMS)
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sanity_path = OUT_DIR / "sanity.json"
    sanity = json.loads(sanity_path.read_text()) if sanity_path.exists() else {}
    sanity["price"] = {
        "input_usd_per_million": str(PRICE_IN),
        "output_usd_per_million": str(PRICE_OUT),
        "harness_discounts_cached_tokens": False,
        "evidence": "src/physharness/orchestration/pricing.py docstring and .state/s1/prices.json "
        "source note: cached-token discounts are conservatively omitted; each settlement is "
        "ceil-rounded to 1e-6 USD.",
    }
    arms = sanity.setdefault("arms", {})
    for name in args.arms:
        print(f"extracting {name}", flush=True)
        arms[name] = extract(name)
        s = arms[name]
        print(
            f"  tokens {s['ours']['total_tokens']} (ledger {s['ledger_budgets']['tokens_spent']}) "
            f"cost {s['ours']['cost_usd_per_turn_ceil']} (ledger {s['ledger_budgets']['spent_usd']}) "
            f"match {s['match']}",
            flush=True,
        )
    sanity["arms"] = {name: arms[name] for name in ARMS if name in arms}
    sanity_path.write_text(json.dumps(sanity, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
