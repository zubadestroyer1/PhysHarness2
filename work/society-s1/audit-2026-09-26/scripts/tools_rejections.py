"""Dump every harness rejection with its context: call, output, and the agent's next calls."""
import json, sys
from collections import defaultdict
from tools_lib import *

def main():
    calls = load_all("tool_calls")
    turns = {(t["arm"], t["session_id"], t["turn"]): t for t in load_all("turns")}
    by_sess = defaultdict(list)
    for c in calls:
        by_sess[(c["arm"], c["session_id"])].append(c)
    for k in by_sess:
        by_sess[k].sort(key=lambda c: c["turn"])
    msgs = {}
    for a in ARMS:
        for m in load(a, "messages"):
            if m["type"] == "function_call_output" and not m.get("inherited"):
                msgs[(a, m["call_id"])] = m["text"]
    code_filter = sys.argv[1] if len(sys.argv) > 1 else None
    for key, cs in by_sess.items():
        for i, c in enumerate(cs):
            if c["outcome"] != "rejected":
                continue
            if code_filter and c["error_code"] != code_filter:
                continue
            t = turns.get((c["arm"], c["session_id"], c["turn"]), {})
            print("=" * 100)
            print(f"{c['arm']} sess={c['session_id'][:8]} task={c['task_id'][:8]} hat={c['hat']} turn={c['turn']}/{len(cs)} {c['tool']} -> {c['error_code']} dur={c['duration_s']:.2f}s turn_in={t.get('input_tokens')} t_lat={t.get('latency_s')}")
            print("ARGS:", c["arguments"][:600])
            print("OUT :", (msgs.get((c["arm"], c["call_id"])) or c["output_excerpt"])[:900])
            for n in cs[i + 1:i + 6]:
                print(f"   next t{n['turn']} {n['tool']} [{n['outcome']}{'/'+n['error_code'] if n['error_code'] else ''}] {n['arguments'][:260]}")

if __name__ == "__main__":
    main()
