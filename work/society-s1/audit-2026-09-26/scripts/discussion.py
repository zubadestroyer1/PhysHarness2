"""Discussion traffic: posts, deliveries, reads, signal vs noise. Usage: discussion.py <arm>"""
import sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from commons_nodes import *


def report(arm_name):
    a, calls, roots, label = load(arm_name)
    posts = a.records["discussion_post"]
    topics = a.records["discussion_topic"]
    print(f"== {arm_name}: topics={len(topics)} posts={len(posts)} deliveries={len(a.records['discussion_delivery'])} "
          f"subscriptions={len(a.records['discussion_subscription'])} readers={len(a.records['discussion_reader'])} "
          f"messages={len(a.records.get('message', {}))}")
    kinds = collections.Counter((label(p.get("branch_id")) if label(p.get("branch_id")) in ("ref", "platform") else "agent", p["post_kind"]) for p in posts.values())
    print("  posts by (author class, kind):", dict(kinds))
    by_author = collections.Counter(label(p.get("branch_id")) for p in posts.values())
    print("  posts by author:", dict(by_author))
    goal = [n for n in a.records["commons_node"].values() if n["node_type"] == "goal"]
    goal_topic = goal[0]["topic_id"] if goal else None
    on_goal = sum(1 for p in posts.values() if p["topic_id"] == goal_topic)
    print(f"  posts on goal thread: {on_goal} ({on_goal/max(1,len(posts)):.0%})")
    sizes = [len(p.get("content") or "") for p in posts.values()]
    print(f"  post body chars: total={sum(sizes)} median={sorted(sizes)[len(sizes)//2] if sizes else 0} "
          f"with_lean_proof={sum(1 for p in posts.values() if ':=' in (p.get('content') or '') and ('theorem' in (p.get('content') or '') or 'lemma' in (p.get('content') or '')))}")
    # deliveries
    deliv = a.records["discussion_delivery"].values()
    items = collections.Counter()
    delivered = collections.defaultdict(set)  # reader -> post ids
    per_reader = collections.Counter()
    first_delivery = {}
    for d in deliv:
        rk = d["reader_key"]
        br = rk.split(":", 1)[1] if rk.startswith("branch:") else None
        for it in d["items"]:
            items[it.get("source_kind")] += 1
            pid = it.get("retrieval_post_id") or it.get("id")
            delivered[br].add(pid)
            per_reader[label(br)] += 1
            key = (br, pid)
            t = ts(d["created_at"])
            if key not in first_delivery or t < first_delivery[key]:
                first_delivery[key] = t
    n_items = sum(items.values())
    print(f"  delivered items={n_items} by source={dict(items)} per reader={dict(per_reader)}")
    own = sum(1 for (br, pid) in first_delivery if pid in posts and posts[pid].get("branch_id") == br)
    print(f"  delivered items that were the reader's own post: {own} ({own/max(1,len(first_delivery)):.0%})")
    # full reads
    reads = collections.defaultdict(list)
    for c in calls:
        if c["name"] == "commons_read" and c["args"].get("post_id"):
            reads[(c["branch_id"], c["args"]["post_id"])].append(c["t"])
    read_after = sum(1 for key in first_delivery if key in reads)
    lat = sorted(min(reads[key]) - first_delivery[key] for key in first_delivery if key in reads and min(reads[key]) >= first_delivery[key])
    print(f"  delivered (reader,post) pairs={len(first_delivery)}; later read in full by reader={read_after} "
          f"({read_after/max(1,len(first_delivery)):.1%}); delivery->read latency median={lat[len(lat)//2] if lat else None:.0f}s" if lat else
          f"  delivered pairs={len(first_delivery)} read_after={read_after}")
    post_reads = collections.Counter()
    for (br, pid), tt in reads.items():
        if pid in posts and posts[pid].get("branch_id") != br:
            post_reads[pid] += 1
    print(f"  commons_read(post) calls={sum(len(v) for v in reads.values())}; posts read by a non-author: {len(post_reads)} "
          f"({len(post_reads)/max(1,len(posts)):.0%} of posts)")
    # cited posts
    cited = collections.Counter()
    for p in posts.values():
        for r in p.get("reference_post_ids") or []:
            cited[r] += 1
        if p.get("reply_to_post_id"):
            cited[p["reply_to_post_id"]] += 1
    print(f"  posts referenced/replied-to: {len(cited)} ({len(cited)/max(1,len(posts)):.0%})")
    # read-only by kind
    rk = collections.Counter(posts[pid]["post_kind"] for pid in post_reads)
    print("  posts read by non-author, by kind:", dict(rk))
    return a, posts, first_delivery, reads


if __name__ == "__main__":
    for arm in sys.argv[1:]:
        report(arm)
