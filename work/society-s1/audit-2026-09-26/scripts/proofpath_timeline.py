"""Proof-path audit: per-arm chronological research timeline (read-only).

Joins data/<arm>/tool_calls.jsonl (turn, outcome, times) with the full call arguments in
cache/<arm>-calls.json and writes out/proofpath/<arm>_timeline.txt plus
out/proofpath/<arm>_calls.json (compact rows used by proofpath_analyze.py).
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(AUDIT, "..", "..", ".."))
OUT = os.path.join(HERE, "out", "proofpath")
ARMS = ["calibration-doeblin-r2", "calibration-aperiodic", "pilot-doeblin", "S-r2", "I-01",
        "I-02", "I-03", "I-04", "I-05", "I-06", "I-07", "I-08", "single"]
DECL = re.compile(r"^\s*(?:private\s+|protected\s+|noncomputable\s+)*(?:theorem|lemma|def|abbrev)\s+([^\s:({\[]+)", re.M)


def ts(v):
    return datetime.fromisoformat(v).timestamp()


def jl(path):
    with open(path) as f:
        return [json.loads(line) for line in f]


def decls(src):
    return DECL.findall(src or "")


def sorries(src):
    return len(re.findall(r"\bsorry\b", src or ""))


def clip(s, n=160):
    s = (s or "").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def events(arm):
    c = sqlite3.connect(f"file:{REPO}/.state/s1/arms/{arm}/harness.db?mode=ro", uri=True)
    rows = c.execute("select kind, payload, created_at from events where kind like 'verification.%' "
                     "or kind='experiment.started' or kind='experiment.created' order by sequence").fetchall()
    exp = [json.loads(p) for (p,) in c.execute("select payload from records where kind='experiment'")]
    return rows, exp


def summarize(call, args, out):
    tool = call["tool"]
    if tool in ("lean_check",):
        src = args.get("source") or ""
        path = args.get("path")
        ds = decls(src)
        errs = call.get("lean_error_messages")
        first = ""
        try:
            o = json.loads(out)
            msgs = [m for m in o.get("messages", []) if m.get("severity") == "error"]
            if msgs:
                first = clip(msgs[0].get("data") or msgs[0].get("text") or "", 90)
            if not src and path:
                src = ""
        except Exception:
            o = {}
        return (f"{'path=' + path + ' ' if path else ''}src={len(src)}c sorry={sorries(src)} decls={ds[:6]}{'+' if len(ds) > 6 else ''}"
                f" errs={errs} {('ERR: ' + first) if first else ''} status={o.get('proof_status') if isinstance(o, dict) else ''}"), ds, src
    if tool == "write_file":
        src = args.get("content") or ""
        ds = decls(src)
        return f"{args.get('path')} {len(src)}c sorry={sorries(src)} decls={ds[:8]}{'+' if len(ds) > 8 else ''}", ds, src
    if tool == "commons_node":
        return (f"{args.get('action')} {args.get('node_type') or ''} '{clip(args.get('title'), 90)}' "
                f"lean_name={args.get('lean_name')} status={args.get('status')}"), [], args.get("lean_statement") or ""
    if tool == "commons_post":
        return f"{args.get('kind')} '{clip(args.get('abstract'), 150)}'", [], args.get("body") or ""
    if tool == "recruit":
        return f"'{clip(args.get('title'), 70)}' brief='{clip(args.get('brief'), 170)}'", [], ""
    if tool == "message":
        return f"to={str(args.get('to'))[:8]} '{clip(args.get('content'), 170)}'", decls(args.get("content")), args.get("content") or ""
    if tool == "search_library":
        return f"q='{clip(args.get('query'), 80)}'", [], ""
    if tool == "read_source":
        return f"{args.get('path')}", [], ""
    if tool == "shell":
        text = " ".join(map(str, args.get("argv") or []))
        return f"{clip(text, 150)}", decls(text), text
    if tool == "submit_review":
        return f"{args.get('verdict')} '{clip(args.get('summary'), 120)}'", [], ""
    if tool == "return_result":
        return f"'{clip(args.get('summary'), 200)}'", [], args.get("summary") or ""
    if tool == "run_computation":
        return clip(json.dumps(args), 150), [], ""
    if tool in ("commons_claim", "commons_read", "commons_query", "read_artifact", "read_file",
                "inbox", "wait", "notebook", "verification_status", "submit_for_verification"):
        return clip(json.dumps(args, ensure_ascii=False), 150), [], ""
    return clip(json.dumps(args, ensure_ascii=False), 150), [], ""


def main(arms):
    os.makedirs(OUT, exist_ok=True)
    for arm in arms:
        cache = json.load(open(os.path.join(HERE, "cache", f"{arm}-calls.json")))
        full = {}
        for c in cache["calls"]:
            full.setdefault(c["call_id"], c)
        t0 = cache["t0"]
        calls = jl(os.path.join(AUDIT, "data", arm, "tool_calls.jsonl"))
        sessions = {s["session_id"]: s for s in jl(os.path.join(AUDIT, "data", arm, "sessions.jsonl"))}
        turns = jl(os.path.join(AUDIT, "data", arm, "turns.jsonl"))
        calls.sort(key=lambda c: (c["ended_at"] or c["started_at"] or ""))
        rows = []
        lines = [f"# {arm} t0={datetime.utcfromtimestamp(t0).isoformat()}Z"]
        vrows, _ = events(arm)
        for k, p, at in vrows:
            lines.append(f"# event {k} at +{(ts(at) - t0) / 60:.2f}m")
        for sid, s in sessions.items():
            lines.append(f"# session {sid[:8]} hat={s['hat']} task={s['task_id'][:8]} turns={s['turns']} "
                         f"in={s['input_tokens']} out={s['output_tokens']} cost={s['cost_usd']} "
                         f"created=+{(ts(s['created_at']) - t0) / 60:.2f}m last=+{(ts(s['last_save_at']) - t0) / 60:.2f}m")
        for c in calls:
            f = full.get(c["call_id"], {})
            args = f.get("args") or {}
            out = f.get("output") or ""
            summ, ds, text = summarize(c, args, out)
            t = ts(c["ended_at"] or c["started_at"]) - t0
            row = dict(t=round(t, 1), session=c["session_id"], hat=c["hat"], task=c["task_id"],
                       turn=c["turn"], tool=c["tool"], outcome=c["outcome"], error_code=c["error_code"],
                       decls=ds, text=text, summary=summ, call_id=c["call_id"],
                       duration_s=c["duration_s"])
            rows.append(row)
            lines.append(f"{t / 60:6.2f}m {c['session_id'][:6]} {c['hat'][:4]:4s} t{c['turn']:<3} "
                         f"{c['tool'][:14]:14s} {str(c['outcome'])[:4]:4s} {summ}")
        with open(os.path.join(OUT, f"{arm}_timeline.txt"), "w") as fh:
            fh.write("\n".join(lines) + "\n")
        with open(os.path.join(OUT, f"{arm}_calls.json"), "w") as fh:
            json.dump(dict(t0=t0, rows=rows, turns=[dict(session=t["session_id"], turn=t["turn"],
                      started=ts(t["started_at"]) - t0, input=t["input_tokens"], output=t["output_tokens"],
                      cost=t["cost_usd"], tools=t["tool_calls"]) for t in turns]), fh)
        print(arm, len(rows))


if __name__ == "__main__":
    main(sys.argv[1:] or ARMS)
