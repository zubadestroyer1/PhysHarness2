"""Per-turn input composition: attribute every measured input token of every completed turn to
fixed scaffolding (tool definitions, initial prompt by section), injected harness context
(peer-update batches, check-in notes, continuation/compaction anchors), agent-produced content
(call arguments, assistant text), tool outputs (work vs coordination tools) and a residual
(encrypted reasoning carried in context + framing + proxy-tokenizer error).
Token counts: o200k_base (offline proxy); tool-definition tokens are the measured constant
turn-1 residual per profile (calibrate.py). Writes out/composition.json.
Run from <repo>: PYTHONPATH=src:tests:<scaffold dir> .venv/bin/python <this> [ARM ...]"""
import json, sys, collections
from pathlib import Path
HERE = Path(__file__).resolve().parent
AUDIT = HERE.parents[1]
sys.path.insert(0, str(AUDIT))
import tiktoken
import extract as X
from prompts import newest_checkpoints

enc = tiktoken.get_encoding("o200k_base")
def tok(s):
    return len(enc.encode(s, disallowed_special=()))

# provider-side tool-definition tokens (incl. framing), measured in calibrate.py
TOOLS_TOK = {"root": 3522, "recruit_detached": 3522, "recruit_joined": 3686, "referee": 1949}
WORK = {"shell", "read_file", "write_file", "run_computation", "lean_check", "lean_sketch",
        "search_library", "read_source", "search_literature", "fetch_source",
        "submit_for_verification", "verification_status"}
COORD = {"commons_query", "commons_read", "read_artifact", "commons_node", "commons_post",
         "commons_claim", "inbox", "recruit", "message", "wait", "notebook", "return_result",
         "submit_review"}
PROMPT_SECTION = {
    "instructions": "p_constitution",
    "objective": "p_objective",
    "continuation": "p_continuation", "handoff_notes": "p_continuation",
    "commons_frontier": "p_commons_view", "focus_nodes": "p_commons_view", "lab": "p_commons_view",
    "mailbox": "p_commons_view", "joined_results": "p_commons_view",
    "research_capacity": "p_workforce", "capacity_guidance": "p_workforce", "task_contract": "p_workforce",
    "allowed_model_configurations": "p_workforce", "review_assignment": "p_workforce",
    "peer_source_retrieval": "p_workforce", "peer_update_delivery": "p_workforce",
    "assigned_source_post_ids": "p_workforce", "synthesis_scope": "p_workforce",
}
BRIEF_SECTION = {"target": "p_target", "assumptions": "p_target_dup", "review": "p_target_review",
                 "readable_work": "p_brief_state", "current_task": "p_brief_task_record",
                 "indices": "p_brief_indices"}


def item_cat(m):
    t, sub = m["type"], m.get("subtype")
    if m["direction"] == "model_output":
        if t == "function_call":
            return "agent_args_work" if m.get("tool") in WORK else "agent_args_coord" if m.get("tool") in COORD else "agent_args_other"
        if t == "message":
            return "agent_text"
        return None  # reasoning / compaction: residual
    if t == "function_call_output":
        tool = m.get("tool")
        return "out_work" if tool in WORK else "out_coord" if tool in COORD else "out_other"
    if sub == "research_network_updates":
        return "inj_peer_updates"
    if sub == "research_runtime_note":
        return "inj_checkin_note"
    if sub in ("compaction_anchor", "continuation_prompt"):
        return "inj_anchor"
    if sub == "initial_prompt":
        return "initial_prompt"
    return "inj_other"


def prompt_split(anchor):
    try:
        obj = json.loads(anchor)
    except ValueError:
        return {"p_unparsed": tok(anchor)}
    parts = collections.Counter()
    for k, v in obj.items():
        if k == "research_brief" and isinstance(v, dict):
            for bk, bv in v.items():
                parts[BRIEF_SECTION.get(bk, "p_brief_misc")] += tok(json.dumps(bv, ensure_ascii=False, separators=(",", ":")))
        else:
            parts[PROMPT_SECTION.get(k, "p_misc")] += tok(json.dumps(v, ensure_ascii=False, separators=(",", ":")))
    total = tok(anchor)
    s = sum(parts.values()) or 1
    return {k: v * total / s for k, v in parts.items()}


def run(name):
    arm = X.Arm(name)
    tasks = {}
    for (p,) in arm.db.execute("select payload from records where kind='task'"):
        t = json.loads(p); tasks[t["id"]] = t
    sessions = [json.loads(l) for l in open(AUDIT / "data" / name / "sessions.jsonl")]
    turns = collections.defaultdict(list)
    for l in open(AUDIT / "data" / name / "turns.jsonl"):
        t = json.loads(l)
        if t["completed"]:
            turns[t["session_id"]].append(t)
    msgs = collections.defaultdict(list)
    for l in open(AUDIT / "data" / name / "messages.jsonl"):
        m = json.loads(l); msgs[m["session_id"]].append(m)
    cps = newest_checkpoints(arm)
    out = []
    for s in sessions:
        sid = s["session_id"]
        task = tasks.get(s["task_id"], {})
        if s["hat"] == "referee":
            prof = "referee"
        elif s["hat"] == "recruit":
            prof = "recruit_joined" if task.get("reply_to_parent_task_id") else "recruit_detached"
        else:
            prof = "root"
        cp = X.decode(arm.content(cps[sid]["sha256"]), lambda ref: arm.content(ref["sha256"]))
        anchor = cp.native_state.get("initial_anchor") or ""
        psplit = prompt_split(anchor)
        comp_turns = [m["turn"] for m in msgs[sid] if m["type"] == "compaction" and m["turn"]]
        comp_turn = min(comp_turns) if comp_turns else None
        items = []
        for m in sorted(msgs[sid], key=lambda m: m["seq"]):
            cat = item_cat(m)
            if cat is None:
                continue
            if cat == "initial_prompt" and m["chars"] == len(anchor):
                n = None  # split below
            else:
                text = m.get("text") or ""
                n = tok(text) * (m["chars"] / len(text)) if text else 0
            if m.get("inherited"):
                enter = 1
            elif m["direction"] == "model_output":
                enter = (m["turn"] or 0) + 1
            else:
                enter = m["turn"] or 1
            leave = comp_turn if (m.get("segment") == "archive" and comp_turn) else 10 ** 9
            items.append((enter, leave, cat, n, m.get("tool")))
        rows = []
        for t in sorted(turns[sid], key=lambda t: t["turn"]):
            k = t["turn"]
            c = collections.Counter()
            c["tools_defs"] = TOOLS_TOK[prof]
            by_tool = collections.Counter()
            for enter, leave, cat, n, tool in items:
                if enter <= k <= leave:
                    if n is None:
                        for pk, pv in psplit.items():
                            c[pk] += pv
                    else:
                        c[cat] += n
                        if tool and cat.startswith("out_"):
                            by_tool[tool] += n
            known = sum(c.values())
            c["residual"] = t["input_tokens"] - known
            rows.append({"turn": k, "input": t["input_tokens"], "cached": t["cached_tokens"],
                         "output": t["output_tokens"], "parts": dict(c), "by_tool_out": dict(by_tool)})
        out.append({"arm": name, "session_id": sid, "hat": s["hat"], "profile": prof,
                    "task_id": s["task_id"], "anchor_split": psplit, "turns": rows})
    return out


if __name__ == "__main__":
    arms = sys.argv[1:] or X.ARMS
    allrows = {}
    p = HERE / "out" / "composition.json"
    if p.exists():
        allrows = json.loads(p.read_text())
    for a in arms:
        allrows[a] = run(a)
        print(a, len(allrows[a]))
    p.write_text(json.dumps(allrows))
