"""Scaffolding audit: decode each session's newest native checkpoint and measure the initial
prompt by top-level key (and nested collaboration keys). Read-only.
Writes out/prompts_<arm>.json and samples/<arm>_<hat>_<n>.json (redacted full prompts).
Usage: prompts.py [ARM ...]"""
import json, os, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
AUDIT = HERE.parents[1]
sys.path.insert(0, str(AUDIT))
import extract as X  # noqa: E402

OUT = HERE / "out"; OUT.mkdir(exist_ok=True)
SAMPLES = HERE / "samples"; SAMPLES.mkdir(exist_ok=True)


def size(v):
    return len(json.dumps(v, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


def newest_checkpoints(arm):
    seq = {}
    for (aid, s) in arm.db.execute(
        "select aggregate_id, sequence from events where kind='artifact.created'"):
        seq[aid] = s
    best = {}
    for rid, p in arm.artifacts("native_checkpoint"):
        sid = (p.get("provenance") or {}).get("session_id")
        key = (p["created_at"], seq.get(rid, 0))
        if sid and (sid not in best or key > best[sid][0]):
            best[sid] = (key, p)
    return {sid: v[1] for sid, v in best.items()}


def run(name):
    arm = X.Arm(name)
    sessions = {json.loads(l)["session_id"]: json.loads(l)
                for l in open(AUDIT / "data" / name / "sessions.jsonl")}
    rows, counts = [], {}
    for sid, man in newest_checkpoints(arm).items():
        cp = X.decode(arm.content(man["sha256"]), lambda ref: arm.content(ref["sha256"]))
        st = cp.native_state
        anchor = st.get("initial_anchor")
        s = sessions.get(sid, {})
        row = {"session_id": sid, "hat": s.get("hat"), "task_id": s.get("task_id"),
               "anchor_chars": len(anchor) if anchor else None, "keys": {}, "collab": {}}
        try:
            obj = json.loads(anchor)
        except Exception:
            obj = None
        if isinstance(obj, dict):
            for k, v in obj.items():
                row["keys"][k] = size(v)
            for k in ("research_brief", "commons_frontier", "focus_nodes", "lab", "research_capacity",
                      "capacity_guidance", "task_contract", "continuation", "handoff_notes", "mailbox",
                      "joined_results", "review_assignment"):
                v = obj.get(k)
                if isinstance(v, dict):
                    row["collab"][k] = {kk: size(vv) for kk, vv in v.items()}
        # other user items (non-initial): count and sizes by type
        extra = {}
        for it in st.get("input", []):
            if it.get("role") == "user" and it.get("content") != anchor:
                c = it.get("content")
                t = "text"
                if isinstance(c, str) and c.startswith("{"):
                    try:
                        t = json.loads(c).get("type") or "json"
                    except ValueError:
                        pass
                e = extra.setdefault(t, [0, 0]); e[0] += 1; e[1] += len(c) if isinstance(c, str) else size(c)
        row["other_user_items"] = extra
        row["model_params"] = sorted((cp.session.model.parameters or {}).keys())
        rows.append(row)
        key = s.get("hat") or "unknown"
        n = counts.get(key, 0)
        if n < 2 and isinstance(obj, dict):
            (SAMPLES / f"{name}_{key}_{n}.json").write_text(X.redact(json.dumps(obj, indent=1, ensure_ascii=False)))
            counts[key] = n + 1
    (OUT / f"prompts_{name}.json").write_text(json.dumps(rows, indent=1))
    print(name, len(rows))


if __name__ == "__main__":
    for a in (sys.argv[1:] or X.ARMS):
        run(a)
