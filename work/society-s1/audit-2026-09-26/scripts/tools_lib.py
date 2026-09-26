"""Shared loaders for the tool-friction audit (read-only over data/<arm>/*.jsonl)."""
import json
import os
from collections import defaultdict

AUDIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(AUDIT)))
DATA = os.path.join(AUDIT, "data")
ARMS = ["calibration-doeblin", "calibration-doeblin-r2", "calibration-aperiodic", "pilot-doeblin",
        "S", "S-r2"] + [f"I-0{i}" for i in range(1, 9)] + ["single"]


def group(arm):
    if arm.startswith("I-"):
        return "I"
    if arm.startswith("calibration") or arm.startswith("pilot"):
        return "cal/pilot"
    return arm


def load(arm, name):
    path = os.path.join(DATA, arm, f"{name}.jsonl")
    with open(path) as f:
        return [json.loads(l) for l in f]


def load_all(name, arms=ARMS):
    out = []
    for a in arms:
        out.extend(load(a, name))
    return out


PRICE_IN = 2.5e-6
PRICE_OUT = 10e-6


_TURNS = None
_CALLS_BY_SESSION = None


def turns_index():
    global _TURNS
    if _TURNS is None:
        _TURNS = {(t["arm"], t["session_id"], t["turn"]): t for t in load_all("turns")}
    return _TURNS


def calls_by_session():
    global _CALLS_BY_SESSION
    if _CALLS_BY_SESSION is None:
        _CALLS_BY_SESSION = defaultdict(list)
        for c in load_all("tool_calls"):
            _CALLS_BY_SESSION[(c["arm"], c["session_id"])].append(c)
        for v in _CALLS_BY_SESSION.values():
            v.sort(key=lambda c: c["turn"])
    return _CALLS_BY_SESSION


def call_cost(c):
    """Ledger $ of the turn that emitted the call, plus its tokens and wall seconds (turn latency + tool)."""
    t = turns_index().get((c["arm"], c["session_id"], c["turn"]), {})
    usd = float(t.get("cost_usd") or 0)
    secs = (t.get("latency_s") or 0) + (c.get("duration_s") or 0)
    return usd, (t.get("input_tokens") or 0) + (t.get("output_tokens") or 0), secs


def cost_of(calls):
    usd = tok = secs = 0.0
    for c in calls:
        u, k, s = call_cost(c)
        usd += u; tok += k; secs += s
    return usd, tok, secs
