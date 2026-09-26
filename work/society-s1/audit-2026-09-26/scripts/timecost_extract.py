"""Extract per-arm timing / token / persistence tables for the time-and-cost audit.

Read-only on run data. Writes JSON tables to .superpowers/live-run/audit/scripts/out/.
Usage: PYTHONPATH=src .venv/bin/python .superpowers/live-run/audit/scripts/timecost_extract.py [arm ...]
"""

import collections
import json
import os
import sqlite3
import sys
from datetime import datetime

ROOT = ".state/s1/arms"
OUT = ".superpowers/live-run/audit/scripts/out"
ARMS = [
    "calibration-doeblin", "calibration-doeblin-r2", "calibration-aperiodic", "pilot-doeblin",
    "S", "S-r2", "I-01", "I-02", "I-03", "I-04", "I-05", "I-06", "I-07", "I-08", "single",
]


def ts(s):
    return datetime.fromisoformat(s).timestamp()


class Content:
    """Artifact content by sha256: newest export dir first, then the live store."""

    def __init__(self, arm):
        base = f"{ROOT}/{arm}"
        exports = sorted(os.listdir(f"{base}/exports")) if os.path.isdir(f"{base}/exports") else []
        self.dirs = [f"{base}/exports/{e}" for e in reversed(exports)]
        self.store = f"{base}/artifacts"

    def path(self, sha):
        for d in self.dirs:
            p = f"{d}/{sha}"
            if os.path.exists(p):
                return p
        p = f"{self.store}/{sha[:2]}/{sha}"
        if os.path.exists(p):
            return p
        return None

    def read(self, sha):
        p = self.path(sha)
        if p is None:
            return None
        with open(p, "rb") as f:
            return f.read()


def classify_run(argv, op_suffix):
    text = " ".join(argv) if isinstance(argv, list) else str(argv)
    if "query = sys.argv[1].casefold()" in text:
        return "search_library_scan"
    if "--checker" in text:
        return "lean_verify_statement"
    if "lean_session.py" in text and "inline" in text:
        return "lean_repl_inline"
    if "lean_session.py" in text:
        return "lean_repl_daemon"
    if "test -x" in text and "repl" in text:
        return "lean_backend_probe"
    if "lake" in text and "env" in text and "lean" in text:
        return "lean_one_shot"
    if op_suffix.endswith(":lean") or ":lean" in op_suffix:
        return "lean_one_shot"
    return "shell_other"


def extract(arm):
    base = f"{ROOT}/{arm}"
    db = sqlite3.connect(f"file:{base}/harness.db?mode=ro", uri=True)
    content = Content(arm)
    out = {"arm": arm}

    events = [
        (seq, kind, agg, op, json.loads(p), ts(c))
        for seq, kind, agg, op, p, c in db.execute(
            "select sequence,kind,aggregate_id,operation_id,payload,created_at from events order by sequence"
        )
    ]
    out["event_counts"] = dict(collections.Counter(e[1] for e in events))
    out["event_times"] = {
        "first": events[0][5] if events else None,
        "last": events[-1][5] if events else None,
    }
    firsts = {}
    lasts = {}
    for e in events:
        firsts.setdefault(e[1], e[5])
        lasts[e[1]] = e[5]
    out["first_event"] = firsts
    out["last_event"] = lasts
    # all event timestamps (for event-loop busy analysis)
    out["event_ts"] = [e[5] for e in events]
    out["event_kind_seq"] = [e[1] for e in events]

    recs = collections.defaultdict(list)
    for kind, payload in db.execute("select kind,payload from records"):
        if kind in {"artifact"}:
            p = json.loads(payload)
            recs[kind].append(p)
        elif kind in {"session", "task", "workspace_operation", "verification", "workspace",
                      "model_reservation", "experiment", "continuation_link"}:
            recs[kind].append(json.loads(payload))

    sessions = []
    for s in recs["session"]:
        sessions.append({
            "id": s["id"], "native": s.get("native_record_id"), "task_id": s.get("task_id"),
            "status": s.get("status"), "input_tokens": s.get("input_tokens"),
            "output_tokens": s.get("output_tokens"), "created_at": ts(s["created_at"]),
            "revision": s.get("revision"), "checkpoint_artifact_id": s.get("checkpoint_artifact_id"),
        })
    out["sessions"] = sessions
    tasks = []
    for t in recs["task"]:
        tasks.append({
            "id": t["id"], "hat": t.get("hat"), "status": t.get("status"),
            "created_at": ts(t["created_at"]), "branch_id": t.get("branch_id"),
            "created_by": t.get("created_by"), "objective": (t.get("objective") or "")[:120],
        })
    out["tasks"] = tasks

    # task lifecycle events
    tev = collections.defaultdict(list)
    for seq, kind, agg, op, p, t in events:
        if kind.startswith("task."):
            tev[agg].append((kind, t, p))
    out["task_events"] = {k: v for k, v in tev.items()}

    # session.saved per session record
    saves = collections.defaultdict(list)
    for seq, kind, agg, op, p, t in events:
        if kind == "session.saved":
            saves[agg].append(t)
    out["session_saves"] = saves

    # artifacts
    art_kind_counts = collections.Counter()
    art_kind_bytes = collections.Counter()
    runtime = []
    chunks = collections.defaultdict(list)
    manifests = collections.defaultdict(list)
    ws_checkpoint = []
    for a in recs["artifact"]:
        k = a.get("artifact_kind")
        art_kind_counts[k] += 1
        art_kind_bytes[k] += a.get("size_bytes") or 0
        prov = a.get("provenance") or {}
        t = ts(a["created_at"])
        if k == "runtime_event":
            raw = content.read(a["sha256"])
            if raw is None:
                continue
            j = json.loads(raw)
            runtime.append({
                "t": t, "kind": j.get("kind"), "op": j.get("operation_id"),
                "session": j.get("session_id"), "payload": j.get("payload"),
                "task_id": prov.get("task_id"),
            })
        elif k == "native_checkpoint_chunk":
            chunks[prov.get("session_id")].append((t, a.get("size_bytes") or 0))
        elif k == "native_checkpoint":
            manifests[prov.get("session_id")].append((t, a.get("size_bytes") or 0, a["id"], a["sha256"]))
        elif k in {"checkpoint", "checkpoint_chunk"}:
            ws_checkpoint.append((k, t, a.get("size_bytes") or 0))
    out["artifact_counts"] = dict(art_kind_counts)
    out["artifact_bytes"] = dict(art_kind_bytes)
    runtime.sort(key=lambda r: r["t"])
    # strip completed artifact content
    for r in runtime:
        if r["kind"] == "completed" and isinstance(r["payload"], dict):
            r["payload"] = {"len": len(json.dumps(r["payload"]))}
    out["runtime"] = runtime
    out["chunks"] = {k: sorted(v) for k, v in chunks.items()}
    out["manifests"] = {k: sorted(v) for k, v in manifests.items()}
    out["ws_checkpoint_artifacts"] = ws_checkpoint

    # workspace operations
    pend = {}
    comp = {}
    ready = {}
    for seq, kind, agg, op, p, t in events:
        if kind == "workspace.operation.pending":
            pend[op] = t
        elif kind == "workspace.operation.completed":
            comp[op] = t
        elif kind == "workspace.ready":
            ready[op] = t
    tool_names = {}
    for r in runtime:
        if r["kind"] == "tool_completed":
            tool_names[r["op"]] = r["payload"].get("name")
    ops = []
    for o in recs["workspace_operation"]:
        inp = o.get("inputs") or {}
        res = o.get("result") or {}
        opid = inp.get("operation_id") or ""
        parts = opid.split(":")
        tool_op = ":".join(parts[:2]) if len(parts) >= 2 else opid
        suffix = ":".join(parts[2:])
        cls = o["command"]
        if o["command"] == "run":
            cls = classify_run(inp.get("argv"), suffix)
        diag = res.get("diagnostics") if isinstance(res, dict) else None
        peak = None
        if isinstance(diag, dict):
            peak = (diag.get("memory_after") or {}).get("peak_bytes")
        start = pend.get(o["id"], ts(o["created_at"]))
        end = comp.get(o["id"]) or ready.get(o["id"])
        ops.append({
            "id": o["id"], "workspace_id": o.get("workspace_id"), "task_id": o.get("task_id"),
            "command": o["command"], "class": cls, "status": o.get("status"),
            "start": start, "end": end, "tool_op": tool_op, "suffix": suffix,
            "tool": tool_names.get(tool_op),
            "exit_code": res.get("exit_code") if isinstance(res, dict) else None,
            "stdout_len": len(res.get("stdout") or "") if isinstance(res, dict) else None,
            "stderr_len": len(res.get("stderr") or "") if isinstance(res, dict) else None,
            "peak_bytes": peak,
            "path": inp.get("path"),
            "timeout": inp.get("timeout_seconds"),
            "final_checkpoint": inp.get("final_checkpoint"),
            "argv_head": (inp.get("argv") or [])[:3] if o["command"] == "run" else None,
            "argv_text": " ".join(inp.get("argv"))[:300] if o["command"] == "run" and isinstance(inp.get("argv"), list) else None,
        })
    ops.sort(key=lambda x: x["start"])
    out["workspace_ops"] = ops

    ver = []
    for v in recs["verification"]:
        vq = [e[5] for e in events if e[1] == "verification.queued" and e[2] == v["id"]]
        vv = [e[5] for e in events if e[1] in ("verification.verified", "verification.rejected", "verification.failed") and e[2] == v["id"]]
        ver.append({"id": v["id"], "status": v.get("status"), "created_at": ts(v["created_at"]),
                    "queued": vq[0] if vq else None, "done": vv[-1] if vv else None,
                    "artifact_id": v.get("artifact_id"), "submitted_by": v.get("submitted_by")})
    out["verifications"] = ver
    out["verification_event_kinds"] = sorted({e[1] for e in events if e[1].startswith("verification")})

    # promote_file timing (proof submission)
    out["continuation_links"] = len(recs["continuation_link"])

    rt = {}
    try:
        rt = json.load(open(f"{base}/run-team.json"))
    except Exception:
        pass
    out["run_team"] = {
        "status": rt.get("status"), "root_goal_status": rt.get("root_goal_status"),
        "stop_reason": rt.get("stop_reason"), "attempted_tasks": rt.get("attempted_tasks"),
        "ledger": rt.get("ledger"),
    }
    for f in os.listdir(base):
        if f.startswith("launch-record") and f.endswith(".json"):
            try:
                out["launch_record"] = json.load(open(f"{base}/{f}"))
            except Exception:
                pass
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    arms = sys.argv[1:] or ARMS
    for arm in arms:
        data = extract(arm)
        with open(f"{OUT}/extract_{arm}.json", "w") as f:
            json.dump(data, f)
        print(arm, "runtime events", len(data["runtime"]), "ops", len(data["workspace_ops"]))


if __name__ == "__main__":
    main()
