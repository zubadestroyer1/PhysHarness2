"""Proof-path audit: worker wall-time split (model latency + tool time per call) into Lean
compiles (ok/failed), library/API search, and everything else, per arm (read-only)."""
import collections
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.dirname(HERE)
ARMS = ["calibration-aperiodic", "S-r2", "I-01", "I-02", "I-03", "I-04", "I-05", "I-06", "I-07", "I-08", "single"]
COMP = re.compile(r"lake env lean|/opt/lean/bin/lean|\blean /work|LEAN_PATH=")
SEARCH = re.compile(r"^(bash -lc )?(rg|grep|sed|find|ls|cat|nl|head|tail)\b")


def argv_text(c):
    try:
        a = json.loads(c["arguments"])
        return " ".join(map(str, a.get("argv") or []))
    except Exception:
        return c["arguments"] or ""


tot = collections.Counter()
for arm in ARMS:
    turns = {(t["session_id"], t["turn"]): t for t in map(json.loads, open(os.path.join(AUDIT, "data", arm, "turns.jsonl")))}
    agg = collections.Counter()
    for line in open(os.path.join(AUDIT, "data", arm, "tool_calls.jsonl")):
        c = json.loads(line)
        if c["hat"] not in ("root", "recruit"):
            continue
        t = turns.get((c["session_id"], c["turn"]))
        dur = ((t["latency_s"] or 0) if t else 0) + (c["duration_s"] or 0)
        agg["all"] += dur
        text = argv_text(c) if c["tool"] == "shell" else ""
        iscomp = c["tool"] == "lean_check" or (c["tool"] == "shell" and COMP.search(text))
        if iscomp:
            agg["compile"] += dur
            if c["outcome"] != "ok":
                agg["compile_fail"] += dur
        elif c["tool"] in ("search_library", "read_source") or (c["tool"] == "shell" and SEARCH.search(text)):
            agg["search"] += dur
    tot.update(agg)
    print(f"{arm:22s} worker-min={agg['all'] / 60:5.1f} compile={100 * agg['compile'] / agg['all']:.0f}% "
          f"(failed {100 * agg['compile_fail'] / agg['all']:.0f}%) search/read={100 * agg['search'] / agg['all']:.0f}%")
print("TOTAL", f"compile={100 * tot['compile'] / tot['all']:.0f}% failed={100 * tot['compile_fail'] / tot['all']:.0f}% search={100 * tot['search'] / tot['all']:.0f}%")
