"""Proof-path audit: spend of each non-submitting task after its last contribution to the
accepted proof. Originator of a final declaration = first non-referee session that authored
it; contribution time = first successful compile of that declaration (by anyone)."""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import proofpath_analyze as pa  # noqa: E402

AUDIT = os.path.dirname(HERE)
ARMS = pa.ARMS


def main(arms):
    out = {}
    for arm in arms:
        fo = pa.first_ok(arm)
        d = json.load(open(os.path.join(pa.OUT, f"{arm}_calls.json")))
        rows = d["rows"]
        for r in rows:
            if r["tool"] == "shell" and not r["decls"]:
                r["decls"] = pa.DECL.findall((r["text"] or "").replace("\\n", "\n"))
        ses = {json.loads(l)["session_id"]: json.loads(l) for l in open(os.path.join(AUDIT, "data", arm, "sessions.jsonl"))}
        fb = pa.blocks(open(os.path.join(HERE, "out", "proofs", f"{arm}.lean")).read())
        origin = {}
        for r in rows:
            if r["hat"] == "referee":
                continue
            for n in r["decls"]:
                if n in fb and n not in origin:
                    origin[n] = (r["session"], r["t"] / 60)
        sub = next(r for r in rows if r["tool"] == "submit_for_verification")
        subtask = ses[sub["session"]]["task_id"]
        contrib = collections.defaultdict(list)
        chars = collections.Counter()
        for n, (sid, t0) in origin.items():
            task = ses[sid]["task_id"]
            contrib[task].append(fo[n][0] if fo.get(n) else t0)
            chars[task] += len(fb[n])
        total_chars = sum(len(v) for v in fb.values())
        res = []
        for task in sorted({v["task_id"] for v in ses.values() if v["hat"] != "referee"}):
            sids = [k for k, v in ses.items() if v["task_id"] == task]
            hat = ses[sids[0]]["hat"]
            cost = sum(float(t["cost"]) for t in d["turns"] if t["session"] in sids)
            last = max(contrib[task]) if contrib.get(task) else 0.0
            after = sum(float(t["cost"]) for t in d["turns"] if t["session"] in sids and t["started"] / 60 > last)
            res.append(dict(task=task[:8], hat=hat, assembler=task == subtask, cost=round(cost, 2),
                            originated_pct=round(100 * chars[task] / total_chars), last_contrib_min=round(last, 1),
                            cost_after_last=round(after, 2) if task != subtask else None))
        out[arm] = res
        nonasm = [x for x in res if not x["assembler"]]
        waste = sum(x["cost_after_last"] for x in nonasm)
        tot = sum(x["cost"] for x in res)
        print(f"{arm:22s} non-assembler spend after last contribution ${waste:6.2f} of ${tot:6.2f} ({100 * waste / tot:.0f}%) :: "
              + "; ".join(f"{x['hat'][:3]}{'*' if x['assembler'] else ''} ${x['cost']} orig {x['originated_pct']}% last {x['last_contrib_min']}m after ${x['cost_after_last']}" for x in res))
    json.dump(out, open(os.path.join(pa.OUT, "idle.json"), "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1:] or ARMS)
