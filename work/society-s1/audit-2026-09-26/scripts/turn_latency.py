"""Per-turn model latency (generation_started->usage) and between-turn gap (usage->next
generation_started, i.e. tool + harness time), for root sessions. Usage: turn_latency.py <arm>..."""
import sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from society_common import *
from task_economy import task_table


def med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else float("nan")


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else float("nan")


if __name__ == "__main__":
    for arm in sys.argv[1:]:
        a, rows = task_table(arm)
        role = {r["task_id"]: r["role"] for r in rows}
        by = collections.defaultdict(list)
        for e in a.runtime_events():
            by[e["session_id"]].append(e)
        model, gap, tool_gap = collections.defaultdict(list), [], collections.defaultdict(list)
        for sid, evs in by.items():
            r = role.get(evs[0]["task_id"])
            start = None
            last_usage = None
            last_tool = None
            for e in evs:
                if e["kind"] == "generation_started":
                    if last_usage is not None and r == "root":
                        gap.append(e["t"] - last_usage)
                        if last_tool:
                            tool_gap[last_tool].append(e["t"] - last_usage)
                    start = e["t"]
                elif e["kind"] == "usage" and start is not None:
                    model[r].append(e["t"] - start)
                    last_usage = e["t"]
                    last_tool = None
                elif e["kind"] == "tool_completed":
                    last_tool = e["payload"]["name"]
        print(f"{arm:22s} root model s/turn: med={med(model['root']):.1f} p90={pct(model['root'],.9):.1f} "
              f"n={len(model['root'])} | gap med={med(gap):.1f} p90={pct(gap,.9):.1f} | referee model med={med(model['referee']):.1f}"
              f" | sum model={sum(model['root'])/60:.0f}min sum gap={sum(gap)/60:.0f}min")
        if "-v" in sys.argv:
            for k, v in sorted(tool_gap.items(), key=lambda kv: -sum(kv[1])):
                print(f"     {k:24s} n={len(v):4d} med={med(v):5.1f}s total={sum(v)/60:5.1f}min")
