"""Extract every function call (name, args, output, time, task, branch) per arm from the
latest native checkpoint of each session. Writes cache/<arm>-calls.json (private)."""
import sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from society_common import *

CACHE = os.path.join(os.path.dirname(__file__), "cache")


def extract(arm_name):
    a = Arm(arm_name)
    rt = a.runtime_events()
    tool_t = {}
    for e in rt:
        if e["kind"] == "tool_completed":
            tool_t[e["operation_id"]] = e["t"]
    sess = {s["native_record_id"]: s for s in a.records["session"].values()}
    cps = collections.defaultdict(list)
    for p in a.artifacts("native_checkpoint"):
        cps[p["provenance"]["session_id"]].append(p)
    calls = []
    rt_tools = collections.Counter(e["session_id"] for e in rt if e["kind"] == "tool_completed")
    for sid, lst in cps.items():
        lst.sort(key=lambda p: p["created_at"])
        items, outputs = {}, {}
        # Latest checkpoint first; walk back only when compaction dropped earlier calls.
        for manifest in reversed(lst):
            ns = decode_checkpoint(arm_name, manifest).model_dump()["native_state"]
            for i in ns["input"]:
                if i.get("type") == "function_call":
                    items.setdefault(i["call_id"], i)
                elif i.get("type") == "function_call_output":
                    outputs.setdefault(i["call_id"], i.get("output"))
            if len(items) >= rt_tools[sid]:
                break
        s = sess.get(sid, {})
        for i in items.values():
            try:
                args = json.loads(i.get("arguments") or "{}")
            except ValueError:
                args = {"_raw": i.get("arguments")}
            out = outputs.get(i["call_id"])
            if not isinstance(out, str):
                out = json.dumps(out)
            calls.append(dict(
                session_id=sid, task_id=s.get("task_id") or lst[-1]["provenance"].get("task_id"),
                branch_id=s.get("branch_id"), call_id=i["call_id"], name=i["name"], args=args,
                output=out[:20000], output_len=len(out or ""),
                t=tool_t.get(f"{sid}:{i['call_id']}"),
            ))
    calls.sort(key=lambda c: (c["t"] or 0))
    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, f"{arm_name}-calls.json"), "w") as f:
        json.dump(dict(t0=a.t0, calls=calls), f)
    return calls


if __name__ == "__main__":
    for arm in sys.argv[1:]:
        c = extract(arm)
        print(arm, len(c), sum(1 for x in c if x["t"] is None), "untimed")
