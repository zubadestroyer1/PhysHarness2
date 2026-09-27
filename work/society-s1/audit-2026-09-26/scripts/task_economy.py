"""Per-task economy: role, timing, tokens, cost, tool calls. Usage: task_economy.py <arm> [--json out]"""
import sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from society_common import *


def task_table(arm_name):
    a = Arm(arm_name)
    costs = a.reservation_costs()
    rt = a.runtime_events()
    sess_by_native = {s["native_record_id"]: s for s in a.records["session"].values()}
    per_task = collections.defaultdict(lambda: dict(
        turns=0, tools=collections.Counter(), first=None, last=None, in_tok=0, out_tok=0,
        cached=0, reasoning=0, sessions=set()))
    for e in rt:
        tid = e["task_id"]
        d = per_task[tid]
        d["first"] = e["t"] if d["first"] is None else min(d["first"], e["t"])
        d["last"] = e["t"] if d["last"] is None else max(d["last"], e["t"])
        d["sessions"].add(e["session_id"])
        if e["kind"] == "usage":
            d["turns"] += 1
            u = e["payload"]
            d["in_tok"] += u.get("input_tokens", 0)
            d["out_tok"] += u.get("output_tokens", 0)
            nu = u.get("native_usage") or {}
            d["cached"] += (nu.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0
            d["reasoning"] += (nu.get("output_tokens_details") or {}).get("reasoning_tokens", 0) or 0
        elif e["kind"] == "tool_completed":
            d["tools"][e["payload"]["name"]] += 1
    ev_task = collections.defaultdict(list)
    for e in a.events:
        if e["kind"].startswith("task."):
            ev_task[e["aggregate_id"]].append(e)
    reviews = {r["task_id"]: r for r in a.records["commons_review"].values()}
    rows = []
    for tid, t in a.records["task"].items():
        br = a.records["branch"].get(t["branch_id"], {})
        hat = t.get("hat")
        if hat == "referee":
            role = "referee"
        elif t.get("synthesis"):
            role = "synthesis"
        elif t["created_by"] == "research-controller" and not br.get("parent_id"):
            role = "root"
        else:
            role = "recruit/delegate"
        d = per_task[tid]
        evs = ev_task[tid]
        leased = [e["t"] for e in evs if e["kind"] == "task.leased"]
        completed = [e["t"] for e in evs if e["kind"] == "task.completed"]
        ra = t.get("review_assignment") or {}
        rv = reviews.get(tid)
        rows.append(dict(
            task_id=tid, role=role, branch_id=t["branch_id"], lab=br.get("lab"), status=t["status"],
            created=a.rel(ts(t["created_at"])),
            first_lease=a.rel(min(leased)) if leased else None,
            completed=a.rel(max(completed)) if completed else None,
            first_event=a.rel(d["first"]) if d["first"] else None,
            last_event=a.rel(d["last"]) if d["last"] else None,
            active_s=(d["last"] - d["first"]) if d["first"] else 0,
            turns=d["turns"], in_tok=d["in_tok"], out_tok=d["out_tok"], cached=d["cached"],
            reasoning=d["reasoning"], cost=costs.get(tid, 0.0), n_sessions=len(d["sessions"]),
            tools=dict(d["tools"]), n_tools=sum(d["tools"].values()),
            node_id=ra.get("node_id"), scope=ra.get("scope"), requested_by=ra.get("requested_by"),
            verdict=rv["verdict"] if rv else None,
            review_at=a.rel(ts(rv["created_at"])) if rv else None,
        ))
    rows.sort(key=lambda r: r["created"])
    return a, rows


def summarize(rows):
    by = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        s = by[r["role"]]
        s["tasks"] += 1
        for k in ("turns", "in_tok", "out_tok", "cached", "cost", "active_s", "n_tools"):
            s[k] += r[k]
    return by


if __name__ == "__main__":
    arm = sys.argv[1]
    a, rows = task_table(arm)
    by = summarize(rows)
    tot = collections.Counter()
    for s in by.values():
        tot.update(s)
    print(f"arm {arm}: t0={a.experiment['created_at']}")
    for role, s in by.items():
        print(f"  {role:18s} tasks={s['tasks']:3d} cost=${s['cost']:.2f} ({s['cost']/tot['cost']:.0%}) "
              f"in={s['in_tok']/1e6:.1f}M out={s['out_tok']/1e3:.0f}k cached={s['cached']/max(1,s['in_tok']):.0%} "
              f"turns={s['turns']} agent-min={s['active_s']/60:.1f} tools={s['n_tools']}")
    print(f"  TOTAL cost=${tot['cost']:.2f} in={tot['in_tok']/1e6:.1f}M out={tot['out_tok']/1e3:.0f}k agent-min={tot['active_s']/60:.1f}")
    if "--rows" in sys.argv:
        for r in rows:
            print(json.dumps({k: (round(v, 1) if isinstance(v, float) else v) for k, v in r.items()}))
