"""Commons node lifecycle, claims, edges, citations, reads, reviews per node. Usage: commons_nodes.py <arm>"""
import sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from society_common import *

CACHE = os.path.join(os.path.dirname(__file__), "cache")


def load(arm_name):
    a = Arm(arm_name)
    calls = json.load(open(os.path.join(CACHE, f"{arm_name}-calls.json")))["calls"]
    roots = {}
    for t in sorted(a.records["task"].values(), key=lambda t: (t["created_at"], t["id"])):
        br = a.records["branch"][t["branch_id"]]
        if not t.get("hat") and not br.get("parent_id") and t["created_by"] == "research-controller":
            roots.setdefault(t["branch_id"], f"R{len(roots)+1}")
    def label(branch_id):
        if branch_id is None:
            return "platform"
        if branch_id in roots:
            return roots[branch_id]
        br = a.records["branch"].get(branch_id, {})
        if br.get("hat") == "referee":
            return "ref"
        p = br.get("parent_id")
        while p and p not in roots:
            p = a.records["branch"].get(p, {}).get("parent_id")
        return f"{roots.get(p, '?')}.child" if p else "?"
    return a, calls, roots, label


def node_report(arm_name):
    a, calls, roots, label = load(arm_name)
    nodes = a.records["commons_node"]
    created = {e["aggregate_id"]: e["t"] for e in a.by_kind["commons.node_created"]}
    status_ev = collections.defaultdict(list)
    for e in a.by_kind["commons.node_status"]:
        status_ev[e["payload"]["node_id"]].append((a.rel(e["t"]), e["payload"]["from"], e["payload"]["to"]))
    lean_ev = collections.defaultdict(list)
    for e in a.by_kind["commons.lean_statement_set"]:
        lean_ev[e["aggregate_id"]].append(a.rel(e["t"]))
    claims = collections.defaultdict(list)
    for e in a.by_kind["commons.node_claim"]:
        p = e["payload"]
        claims[p["node_id"]].append((a.rel(e["t"]), label(p["branch_id"]), p["action"]))
    edges = [(e["payload"]["source_id"], e["payload"]["relation"], e["payload"]["target_id"], a.rel(e["t"]))
             for e in a.by_kind["commons.edge_added"]]
    posts = a.records["discussion_post"]
    cites = collections.defaultdict(list)
    for p in posts.values():
        for n in p.get("cites") or []:
            cites[n].append((a.rel(ts(p["created_at"])), label(p.get("branch_id")), p["id"]))
    reads = collections.defaultdict(list)
    for c in calls:
        if c["name"] == "commons_read" and c["args"].get("node_id"):
            reads[c["args"]["node_id"]].append((a.rel(c["t"]), label(c["branch_id"])))
    thread = collections.Counter()
    for p in posts.values():
        if p.get("node_id"):
            thread[p["node_id"]] += 1
    reviews = collections.defaultdict(list)
    for r in a.records["commons_review"].values():
        reviews[r["node_id"]].append((a.rel(ts(r["created_at"])), r["scope"], r["verdict"]))
    out = []
    for nid, n in sorted(nodes.items(), key=lambda kv: created.get(kv[0], 0)):
        out.append(dict(
            node_id=nid, author=label(n.get("branch_id")), type=n["node_type"], title=n["title"],
            status=n["status"], created=a.rel(created.get(nid, a.t0)), lean_name=n.get("lean_name"),
            statuses=status_ev[nid], lean_set=lean_ev[nid], claims=claims[nid],
            out_edges=[(r, t[:8], round(tt)) for s, r, t, tt in edges if s == nid],
            in_edges=[(s[:8], r, round(tt)) for s, r, t, tt in edges if t == nid],
            cites=cites[nid], reads=reads[nid], thread_posts=thread[nid], reviews=sorted(reviews[nid]),
            citation_count=n.get("citation_count"),
        ))
    return a, out, label


if __name__ == "__main__":
    a, out, label = node_report(sys.argv[1])
    for n in out:
        own = n["author"]
        xreads = [r for r in n["reads"] if r[1] != own and r[1] != "ref"]
        xcites = [c for c in n["cites"] if c[1] != own and c[1] != "ref"]
        print(f"{n['node_id'][:8]} {own:9s} {n['type']:6s} {n['status']:15s} c={n['created']:6.0f} "
              f"lean={[round(x) for x in n['lean_set']]} st={[(round(t),to) for t,f,to in n['statuses']]} "
              f"rev={[(round(t),s[0],v) for t,s,v in n['reviews']]}")
        print(f"      title={n['title'][:90]!r} lean_name={n['lean_name']}")
        print(f"      claims={[(round(t),b,x) for t,b,x in n['claims'] if x=='claim']} "
              f"reads(total/xbranch)={len(n['reads'])}/{len(xreads)} {sorted(set(r[1] for r in xreads))} "
              f"cites(total/xbranch)={len(n['cites'])}/{len(xcites)} {sorted(set(c[1] for c in xcites))} "
              f"posts={n['thread_posts']} out={n['out_edges']} in={n['in_edges']}")
