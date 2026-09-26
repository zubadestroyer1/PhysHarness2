"""Cross-arm coordination table (markdown). Usage: arm_table.py <arm>..."""
import sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from commons_nodes import *
from task_economy import task_table
from context_rent2 import arm_rent, COMMONS
from turn_time_split import split


def row(arm):
    a, rows = task_table(arm)
    _, calls, roots, label = load(arm)
    ver = [e for e in a.by_kind["verification.verified"]]
    ttp = a.rel(ver[0]["t"]) / 60 if ver else None
    roles = collections.Counter(r["role"] for r in rows)
    cost = sum(r["cost"] for r in rows)
    refc = sum(r["cost"] for r in rows if r["role"] == "referee")
    t, inp = arm_rent(arm)
    commons = sum(v for k, v in t.items() if k in COMMONS)
    d = split(arm)
    tt = sum(d.values()) or 1
    posts = a.records["discussion_post"]
    deliv = sum(len(x["items"]) for x in a.records["discussion_delivery"].values())
    return dict(
        arm=arm, ttp=ttp, cost=cost, roots=roles["root"], recruits=roles["recruit/delegate"],
        referees=roles["referee"], ref_cost=refc, ref_share=refc / cost if cost else 0,
        soc_time=d["society"] / tt, soc_tokens=(commons + t["peer_updates"]) / inp if inp else 0,
        peer_upd=t["peer_updates"] / inp if inp else 0,
        posts=len(posts), deliv=deliv, msgs=len(a.records.get("message", {})),
        nodes=len(a.records["commons_node"]), waits=len(a.by_kind["task.peer_wait_requested"]),
    )


if __name__ == "__main__":
    print("| arm | time to proof (min) | cost $ | roots | recruits | referee tasks | referee $ (share) | society share of agent time | society share of root/recruit input tokens (of which pushed updates) | posts | pushed items | messages | nodes | peer waits |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for arm in sys.argv[1:]:
        r = row(arm)
        ttp = f"{r['ttp']:.1f}" if r["ttp"] else "-"
        print(f"| {arm} | {ttp} | {r['cost']:.2f} | {r['roots']} | {r['recruits']} | {r['referees']} | {r['ref_cost']:.2f} ({r['ref_share']:.0%}) | "
              f"{r['soc_time']:.0%} | {r['soc_tokens']:.0%} ({r['peer_upd']:.0%}) | {r['posts']} | {r['deliv']} | {r['msgs']} | {r['nodes']} | {r['waits']} |")
