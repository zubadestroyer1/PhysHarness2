"""Attribute each session's input tokens to the step that added them (context rent).
Per turn k: growth_k = in[k+1]-in[k]; rent_k = growth_k * (turns after k). Base = in[0]*turns.
Usage: context_rent.py <arm> [<arm> ...]"""
import sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from society_common import *

BUCKET = {
    "commons_query": "commons", "commons_read": "commons", "commons_node": "commons",
    "commons_post": "commons", "commons_claim": "commons", "inbox": "commons", "message": "commons",
    "recruit": "commons", "wait": "commons", "submit_review": "commons", "read_artifact": "commons",
}


def rent(arm_name, roles=("root", "recruit/delegate")):
    from task_economy import task_table
    a, rows = task_table(arm_name)
    role = {r["task_id"]: r["role"] for r in rows}
    rt = a.runtime_events()
    by_session = collections.defaultdict(list)
    for e in rt:
        by_session[e["session_id"]].append(e)
    total = collections.Counter()
    for sid, evs in by_session.items():
        tid = evs[0]["task_id"]
        if role.get(tid) not in roles:
            continue
        # sequence of (usage, tool) pairs in time order
        seq = []
        for e in evs:
            if e["kind"] == "usage":
                seq.append(["usage", e["payload"]["input_tokens"], None])
            elif e["kind"] == "tool_completed" and seq:
                seq[-1][2] = e["payload"]["name"]
        ins = [s[1] for s in seq]
        n = len(ins)
        if not n:
            continue
        total["base"] += ins[0] * n
        for k in range(n - 1):
            growth = ins[k + 1] - ins[k]
            name = seq[k][2] or "(no tool)"
            total[name] += growth * (n - k - 1)
        total["_input_total"] += sum(ins)
    return total


if __name__ == "__main__":
    for arm in sys.argv[1:]:
        t = rent(arm)
        tot = t.pop("_input_total")
        commons = sum(v for k, v in t.items() if BUCKET.get(k) == "commons")
        print(f"{arm}: input={tot/1e6:.1f}M base={t['base']/tot:.0%} commons-tools={commons/tot:.0%} "
              + " ".join(f"{k}={v/tot:.1%}" for k, v in t.most_common(12) if k != "base"))
