"""Per-tool definition rent (provider tokens re-sent every turn) vs calls. Offline."""
import json, collections, glob
from pathlib import Path
HERE = Path(__file__).resolve().parent
AUDIT = HERE.parents[1]
cal = json.loads((HERE / "out" / "calibration.json").read_text())
turns = json.loads((HERE / "out" / "numbers.json").read_text())["turns_by_profile"]
MEAS = {"root": 3522, "recruit": 3686, "referee": 1949}
PROF = {"root": ("root", ["root", "recruit_detached"]), "recruit": ("recruit", ["recruit_joined"]), "referee": ("referee", ["referee"])}
calls = collections.Counter()
for f in glob.glob(str(AUDIT / "data" / "*" / "tool_calls.jsonl")):
    for l in open(f):
        calls[json.loads(l)["tool"]] += 1
rent = collections.Counter(); per_turn = collections.defaultdict(dict)
for key, (cat, profs) in PROF.items():
    pt = cal["per_tool_tok"][cat]
    scale = MEAS[cat] / cal["tools_tok"][cat]
    n = sum(turns.get(p, 0) for p in profs)
    for tool, t in pt.items():
        rent[tool] += t * scale * n
        per_turn[tool][key] = round(t * scale)
tot = sum(rent.values())
print(f"total definition rent {tot/1e6:.2f}M tokens = ${tot*2.5e-6:.2f}")
rows = []
for tool, r in rent.most_common():
    rows.append({"tool": tool, "tok_per_turn": per_turn[tool], "rent_M": round(r / 1e6, 3), "usd": round(r * 2.5e-6, 2),
                 "calls": calls[tool], "usd_per_call": round(r * 2.5e-6 / calls[tool], 3) if calls[tool] else None})
    print(rows[-1])
json.dump(rows, open(HERE / "out" / "tool_rent.json", "w"), indent=1)
