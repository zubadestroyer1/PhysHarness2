"""Share of agent wall time spent in turns whose action was a society/commons tool.
Usage: turn_time_split.py <arm>..."""
import sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from commons_nodes import *

COMM = {"commons_query", "commons_read", "commons_node", "commons_post", "commons_claim", "inbox",
        "message", "recruit", "wait", "read_artifact"}


def split(arm):
    a, calls, roots, label = load(arm)
    by = collections.defaultdict(list)
    for e in a.runtime_events():
        by[e["session_id"]].append(e)
    sess = {s["native_record_id"]: s for s in a.records["session"].values()}
    d = collections.Counter()
    for sid, evs in by.items():
        lab = label(sess[sid]["branch_id"])
        if lab == "ref":
            continue
        cur = None
        for e in evs:
            if e["kind"] == "generation_started":
                if cur:
                    d[cur[1]] += e["t"] - cur[0]
                cur = [e["t"], "no_tool"]
            elif e["kind"] == "tool_completed" and cur:
                cur[1] = "society" if e["payload"]["name"] in COMM else "math"
                cur.append(e["t"])
        if cur and len(cur) > 2:
            d[cur[1]] += cur[2] - cur[0]
    return d


if __name__ == "__main__":
    for arm in sys.argv[1:]:
        d = split(arm)
        tot = sum(d.values())
        print(f"{arm:22s} agent-min={tot/60:6.1f} society={d['society']/tot:.0%} math={d['math']/tot:.0%} no_tool={d['no_tool']/tot:.0%}")
