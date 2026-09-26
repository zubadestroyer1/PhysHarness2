"""Headline numbers for the scaffolding report (reads out/*.json and data/*). Offline.
Run from <repo>: PYTHONPATH=src:tests:<scaffold dir> .venv/bin/python <this>"""
import json, collections, glob, statistics as st
from pathlib import Path
HERE = Path(__file__).resolve().parent
AUDIT = HERE.parents[1]
from summarize import GROUP  # noqa
PRICE = 2.5e-6
comp = json.loads((HERE / "out" / "composition.json").read_text())
cal = json.loads((HERE / "out" / "calibration.json").read_text())
res = {}

# a) turn-1 fixed context per profile (fresh sessions)
t1 = collections.defaultdict(list)
for r in cal["rows"]:
    if not r["has_predecessor"]:
        prof = r["profile"]
        t1[prof].append(r)
a = {}
for prof, rows in t1.items():
    a[prof] = {"n": len(rows), "turn1_input_median": st.median(r["turn1_input"] for r in rows),
               "turn1_min": min(r["turn1_input"] for r in rows), "turn1_max": max(r["turn1_input"] for r in rows),
               "prompt_tok_median": st.median(r["anchor_tok"] for r in rows),
               "prompt_chars_median": st.median(r["anchor_chars"] for r in rows)}
res["turn1"] = a

# b) totals by group (all arms), by hat, and for society vs non-society
tot = collections.Counter(); byhat = collections.defaultdict(collections.Counter); turns = collections.Counter()
per_arm = {}
for arm, sessions in comp.items():
    ac = collections.Counter()
    for s in sessions:
        for t in s["turns"]:
            turns[s["profile"]] += 1
            for k, v in t["parts"].items():
                g = GROUP.get(k, k)
                tot[g] += v; byhat[s["hat"]][g] += v; ac[g] += v
            tot["_input"] += t["input"]; byhat[s["hat"]]["_input"] += t["input"]; ac["_input"] += t["input"]
            tot["_output"] += t["output"]; ac["_output"] += t["output"]; ac["_turns"] += 1
    per_arm[arm] = ac
res["totals"] = {k: round(v) for k, v in tot.items()}
res["turns_by_profile"] = dict(turns)
def shares(c):
    inp = c["_input"]
    fixed = sum(v for k, v in c.items() if k.startswith("F_"))
    return {"input_M": round(inp / 1e6, 2), "turns": c.get("_turns"),
            "fixed_pct": round(100 * fixed / inp, 1),
            "fixed_nonproblem_pct": round(100 * (fixed - c["F_problem"]) / inp, 1),
            "tools_pct": round(100 * c["F_tools"] / inp, 1),
            "bookkeeping_brief_pct": round(100 * (c["F_bookkeeping"] + c["F_brief_state"]) / inp, 1),
            "commons_view_workforce_pct": round(100 * (c["F_commons_view"] + c["F_workforce"]) / inp, 1),
            "problem_pct": round(100 * c["F_problem"] / inp, 1),
            "peer_updates_pct": round(100 * c["I_peer_updates"] / inp, 1),
            "checkin_pct": round(100 * c["I_checkin"] / inp, 1),
            "coord_io_pct": round(100 * (c["A_args_coord"] + c["O_coord"]) / inp, 1),
            "work_io_pct": round(100 * (c["A_args_work"] + c["O_work"]) / inp, 1),
            "residual_pct": round(100 * c["R_reasoning_residual"] / inp, 1),
            "fixed_usd": round(fixed * PRICE, 2), "peer_usd": round(c["I_peer_updates"] * PRICE, 2),
            "coord_usd": round((c["A_args_coord"] + c["O_coord"]) * PRICE, 2),
            "total_usd": round(inp * PRICE + c["_output"] * 1e-5, 2)}
res["per_arm"] = {arm: shares(c) for arm, c in per_arm.items()}
res["all"] = shares(tot)
res["by_hat"] = {h: shares(c) for h, c in byhat.items()}
json.dump(res, open(HERE / "out" / "numbers.json", "w"), indent=1)
print(json.dumps(res["turn1"], indent=1))
print("ALL", res["all"])
for h, v in res["by_hat"].items(): print(h, v)
for a_, v in res["per_arm"].items(): print(a_, v)
print(res["turns_by_profile"])
