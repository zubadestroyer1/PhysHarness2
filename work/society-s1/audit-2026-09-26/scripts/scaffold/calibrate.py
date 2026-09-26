"""Calibrate fixed scaffolding tokens: o200k_base token counts (offline proxy tokenizer) of the
initial prompt (by key) and of the offline-built tool catalogs, compared with each fresh
session's measured turn-1 input tokens. Writes out/calibration.json.
Run from <repo>: PYTHONPATH=src:tests .venv/bin/python <this>"""
import json, sys, collections, statistics as st
from pathlib import Path
HERE = Path(__file__).resolve().parent
AUDIT = HERE.parents[1]
sys.path.insert(0, str(AUDIT))
import tiktoken
import extract as X
import test_society_tools as T
from prompts import newest_checkpoints

enc = tiktoken.get_encoding("o200k_base")
tok = lambda s: len(enc.encode(s))
cats = {"root": T.catalog({"reply_to_parent_task_id": None}),
        "recruit": T.catalog({"reply_to_parent_task_id": "parent"}),
        "referee": T.referee_catalog("informal")}
tools_tok = {k: tok(json.dumps(d.definitions, ensure_ascii=False)) for k, d in cats.items()}
per_tool_tok = {k: {d["name"]: tok(json.dumps(d, ensure_ascii=False)) for d in c.definitions}
                for k, c in cats.items()}
print("tool tokens", tools_tok)

rows = []
for name in X.ARMS:
    arm = X.Arm(name)
    sess = {json.loads(l)["session_id"]: json.loads(l) for l in open(AUDIT / "data" / name / "sessions.jsonl")}
    turn1 = {}
    for l in open(AUDIT / "data" / name / "turns.jsonl"):
        t = json.loads(l)
        if t["turn"] == 1 and t["completed"]:
            turn1[t["session_id"]] = t["input_tokens"]
    for sid, man in newest_checkpoints(arm).items():
        s = sess.get(sid)
        if not s or s["inherited_items"] or sid not in turn1:
            continue
        cp = X.decode(arm.content(man["sha256"]), lambda ref: arm.content(ref["sha256"]))
        anchor = cp.native_state["initial_anchor"]
        obj = json.loads(anchor)
        keytok = {k: tok(json.dumps(v, ensure_ascii=False, separators=(",", ":"), sort_keys=True)) for k, v in obj.items()}
        brief = obj.get("research_brief") or {}
        brieftok = {k: tok(json.dumps(v, ensure_ascii=False, separators=(",", ":"), sort_keys=True)) for k, v in brief.items()}
        # the first user item may be preceded by nothing else; count all input items before first output
        prof = "referee" if s["hat"] == "referee" else ("recruit" if s["hat"] == "recruit" else "root")
        rows.append({"arm": name, "session_id": sid, "hat": s["hat"], "profile": prof,
                     "has_predecessor": bool(s["predecessor"]),
                     "anchor_chars": len(anchor), "anchor_tok": tok(anchor), "turn1_input": turn1[sid],
                     "tools_tok": tools_tok[prof], "key_tok": keytok, "brief_tok": brieftok,
                     "turns": s["turns"], "input_tokens": s["input_tokens"]})
for r in rows:
    r["residual"] = r["turn1_input"] - r["anchor_tok"] - r["tools_tok"]
by = collections.defaultdict(list)
for r in rows:
    by[r["profile"]].append(r["residual"])
for k, v in by.items():
    print(k, "n", len(v), "residual median", st.median(v), "min", min(v), "max", max(v))
(HERE / "out" / "calibration.json").write_text(json.dumps({"tools_tok": tools_tok, "per_tool_tok": per_tool_tok, "rows": rows}, indent=1))
