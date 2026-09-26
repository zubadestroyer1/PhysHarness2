"""Context rent by category using measured per-turn input growth, split across what was
appended at each boundary (tool args+output, pushed peer updates, harness notes) by chars.
rent_k = growth_k * turns_remaining. Usage: context_rent2.py <arm> ..."""
import sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from society_common import *
from task_economy import task_table

COMMONS = {"commons_query", "commons_read", "commons_node", "commons_post", "commons_claim",
           "inbox", "message", "recruit", "wait", "submit_review", "read_artifact"}


def user_kind(item):
    c = item.get("content")
    s = c if isinstance(c, str) else json.dumps(c)
    if s.startswith("{"):
        try:
            return json.loads(s).get("type", "prompt"), len(s)
        except ValueError:
            pass
    return "prompt", len(s)


def session_rent(arm_name, sid, manifests, usage_in):
    lst = sorted(manifests, key=lambda p: p["created_at"])
    items = decode_checkpoint(arm_name, lst[-1]).model_dump()["native_state"]["input"]
    # boundaries: list of dict(category->chars) appended after each model output
    bounds, cur, started = [], None, False
    for it in items:
        t = it.get("type")
        if t in ("reasoning", "function_call") or (t == "message" and it.get("role") == "assistant"):
            if cur is not None and cur.get("_closed"):
                bounds.append(cur)
                cur = None
            if cur is None:
                cur = collections.Counter()
            if t == "function_call":
                cur["_name"] = 0
                cur[it["name"]] += len(it.get("arguments") or "")
                cur["__tool"] = it["name"]
            started = True
        elif t == "function_call_output":
            if cur is not None:
                cur[cur.get("__tool", "?")] += len(it.get("output") if isinstance(it.get("output"), str) else json.dumps(it.get("output")))
                cur["_closed"] = 1
        elif t is None or t == "message":
            k, n = user_kind(it)
            if not started:
                continue
            if cur is None:
                cur = collections.Counter()
            cur[{"research_network_updates": "peer_updates", "research_runtime_note": "harness_note"}.get(k, "other_user")] += n
            cur["_closed"] = 1
    if cur is not None:
        bounds.append(cur)
    n = len(usage_in)
    rent = collections.Counter()
    rent["base"] += usage_in[0] * n
    for k in range(n - 1):
        growth = usage_in[k + 1] - usage_in[k]
        b = bounds[k] if k < len(bounds) else collections.Counter({"unmatched": 1})
        parts = {key: v for key, v in b.items() if not key.startswith("_")}
        tot = sum(parts.values()) or 1
        for key, v in parts.items():
            rent[key] += growth * (n - k - 1) * v / tot
    return rent, sum(usage_in)


def arm_rent(arm_name, roles=("root", "recruit/delegate")):
    a, rows = task_table(arm_name)
    role = {r["task_id"]: r["role"] for r in rows}
    usage = collections.defaultdict(list)
    task_of = {}
    for e in a.runtime_events():
        if e["kind"] == "usage":
            usage[e["session_id"]].append(e["payload"]["input_tokens"])
            task_of[e["session_id"]] = e["task_id"]
    cps = collections.defaultdict(list)
    for p in a.artifacts("native_checkpoint"):
        cps[p["provenance"]["session_id"]].append(p)
    total, inp = collections.Counter(), 0
    for sid, ins in usage.items():
        if role.get(task_of[sid]) not in roles or sid not in cps:
            continue
        r, s = session_rent(arm_name, sid, cps[sid], ins)
        total.update(r)
        inp += s
    return total, inp


if __name__ == "__main__":
    for arm in sys.argv[1:]:
        t, inp = arm_rent(arm)
        commons = sum(v for k, v in t.items() if k in COMMONS)
        print(f"{arm}: input={inp/1e6:.1f}M base={t['base']/inp:.0%} commons_tools={commons/inp:.0%} "
              f"peer_updates={t['peer_updates']/inp:.1%} harness_note={t['harness_note']/inp:.1%} "
              f"society_total={(commons+t['peer_updates'])/inp:.0%} | "
              + " ".join(f"{k}={v/inp:.1%}" for k, v in t.most_common(9) if k not in ('base',)))
