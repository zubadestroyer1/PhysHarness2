"""Estimate input-token savings of the proposed lean configuration by re-pricing the measured
per-turn composition (out/composition.json). Static estimate: it removes rent only and does
not model behavioural changes (fewer coordination turns etc.). Offline."""
import json, collections
from pathlib import Path
HERE = Path(__file__).resolve().parent
comp = json.loads((HERE / "out" / "composition.json").read_text())
PRICE = 2.5e-6
# provider tokens per turn removed from the tool catalog (scaled per-tool estimates, tool_rent.py):
# lean_sketch, load_skill, fetch_source, search_literature (0 calls) + notebook (16 calls, 38% rejected)
TOOL_CUT = {"root": 156 + 99 + 80 + 61 + 192, "recruit_detached": 156 + 99 + 80 + 61 + 192,
            "recruit_joined": 154 + 97 + 79 + 60 + 190, "referee": 90 + 77 + 59 + 184}
TARGET_KEEP = 1008 / 1283  # measured: problem record -> statement/definitions/assumptions only
PEER_KEEP = 0.16           # excerpt (9% of tokens) + ~20 tokens/item of compact attribution
changes = {
    "C1 prompt bookkeeping (review record, task record x2, indices, branch, capacity, contract, model list, retrieval notes)":
        lambda s, k, v: v if k in ("p_target_review", "p_brief_task_record", "p_brief_indices", "p_brief_misc", "p_misc", "p_target_dup", "p_workforce") else 0,
    "C2 readable_work in fresh sessions (duplicates current task)":
        lambda s, k, v: v if k == "p_brief_state" and not s["_pred"] else 0,
    "C3 referee commons frontier + empty views":
        lambda s, k, v: v if k == "p_commons_view" and s["profile"] == "referee" else 0,
    "C4 target record metadata":
        lambda s, k, v: v * (1 - TARGET_KEEP) if k == "p_target" else 0,
    "C5 unused tools (lean_sketch, load_skill, fetch_source, search_literature, notebook)":
        lambda s, k, v: TOOL_CUT[s["profile"]] if k == "tools_defs" else 0,
    "C6 peer-update format (compact lines, no per-batch notice)":
        lambda s, k, v: v * (1 - PEER_KEEP) if k == "inj_peer_updates" else 0,
    "C7 check-in notes":
        lambda s, k, v: v if k == "inj_checkin_note" else 0,
}
sess_pred = {}
data_dir = HERE.parents[1] / "data"
for arm in comp:
    for l in open(data_dir / arm / "sessions.jsonl"):
        r = json.loads(l); sess_pred[r["session_id"]] = bool(r["predecessor"])
out = collections.defaultdict(collections.Counter); inp = collections.Counter()
per_turn = collections.defaultdict(lambda: collections.Counter()); turns = collections.Counter()
for arm, sessions in comp.items():
    for s in sessions:
        s["_pred"] = sess_pred[s["session_id"]]
        for t in s["turns"]:
            inp[arm] += t["input"]; inp["ALL"] += t["input"]; turns[s["profile"]] += 1
            for name, fn in changes.items():
                saved = sum(fn(s, k, v) for k, v in t["parts"].items())
                out[arm][name] += saved; out["ALL"][name] += saved
                per_turn[s["profile"]][name] += saved
res = {}
for arm in ["ALL", "S-r2", "single", "I-01"]:
    tot = sum(out[arm].values())
    res[arm] = {"input_M": round(inp[arm] / 1e6, 2), "saved_M": round(tot / 1e6, 2),
                "saved_pct": round(100 * tot / inp[arm], 1), "saved_usd": round(tot * PRICE, 2),
                "by_change_pct": {k[:2]: round(100 * v / inp[arm], 2) for k, v in out[arm].items()}}
res["per_turn_by_profile"] = {p: {k[:2]: round(v / turns[p]) for k, v in c.items()} | {"total": round(sum(c.values()) / turns[p])}
                              for p, c in per_turn.items()}
res["changes"] = list(changes)
(HERE / "out" / "lean_estimate.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
