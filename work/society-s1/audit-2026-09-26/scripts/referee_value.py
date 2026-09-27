"""For each referee review: was the node's Lean proof already complete (author lean_check ok &
complete containing `theorem <lean_name>`) before the request / verdict? Did anything change after?
Usage: referee_value.py <arm>"""
import sys, re
sys.path.insert(0, __import__("os").path.dirname(__file__))
from commons_nodes import *
from task_economy import task_table


def main(arm):
    a, calls, roots, label = load(arm)
    _, rows = task_table(arm)
    nodes = a.records["commons_node"]
    proved = collections.defaultdict(lambda: 1e18)  # (branch, lean_name) -> first complete check time
    for c in calls:
        if c["name"] != "lean_check" or c["t"] is None or label(c["branch_id"]) == "ref":
            continue
        try:
            o = json.loads(c["output"])
        except ValueError:
            continue
        if not (o.get("ok") and o.get("complete")):
            continue
        src = c["args"].get("source") or ""
        for m in re.finditer(r"theorem\s+([A-Za-z_][\w\.']*)", src):
            key = m.group(1)
            proved[key] = min(proved[key], c["t"])
    refs = [r for r in rows if r["role"] == "referee"]
    before_req = before_verdict = 0
    lines = []
    for r in refs:
        n = nodes[r["node_id"]]
        ln = n.get("lean_name")
        pt = proved.get(ln, 1e18) if ln else 1e18
        req = a.t0 + r["created"]
        ver = a.t0 + (r["review_at"] or 1e9)
        before_req += pt <= req
        before_verdict += pt <= ver
        lines.append((r["created"], r["scope"], r["verdict"], ln, round(a.rel(pt)) if pt < 1e17 else None,
                       round(r["review_at"] - r["created"]) if r["review_at"] else None,
                       round(r["first_lease"] - r["created"]) if r["first_lease"] else None, round(r["cost"], 2)))
    for l in lines:
        print("  req=%6.0f %-8s %-10s %-40s proved_at=%s  req->verdict=%ss queue=%ss $%s" % l)
    n = len(refs)
    lat = sorted(l[5] for l in lines if l[5] is not None)
    q = sorted(l[6] for l in lines if l[6] is not None)
    print(f"{arm}: referees={n} node already Lean-proved (complete lean_check by a non-referee) before request={before_req} "
          f"({before_req/max(1,n):.0%}), before verdict={before_verdict} ({before_verdict/max(1,n):.0%}); "
          f"req->verdict median={lat[len(lat)//2] if lat else None}s max={max(lat) if lat else None}s; "
          f"queue median={q[len(q)//2] if q else None}s max={max(q) if q else None}s sum={sum(q)}s")


if __name__ == "__main__":
    for arm in sys.argv[1:]:
        main(arm)
