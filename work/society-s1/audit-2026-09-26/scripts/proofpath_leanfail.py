"""Proof-path audit: every Lean compile attempt (lean_check and shell `lean` runs) per arm,
with outcome and first-error category, from the full call outputs in cache/<arm>-calls.json."""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.dirname(HERE)
ARMS = ["calibration-doeblin-r2", "calibration-aperiodic", "pilot-doeblin", "S-r2", "I-01",
        "I-02", "I-03", "I-04", "I-05", "I-06", "I-07", "I-08", "single"]
CATS = [
    ("unknown_name", r"Unknown (constant|identifier)|unknown (constant|identifier)|unknown namespace|does not exist|not found|Invalid field|invalid field"),
    ("tactic_failed", r"failed|made no progress|could not prove|No goals|no goals|did not find|motive is not type correct|not definitionally"),
    ("unsolved_goals", r"unsolved goals"),
    ("type_mismatch", r"[Tt]ype mismatch|Application type mismatch|failed to synthesize|cannot synthesize|typeclass"),
    ("syntax", r"unexpected token|expected '|unexpected"),
]
COMPILE = re.compile(r"lake env lean|/opt/lean/bin/lean|\blean /work|LEAN_PATH=")


def errors_of(out):
    try:
        o = json.loads(out)
    except Exception:
        return None, out
    if isinstance(o, dict) and "messages" in o:
        errs = [m.get("data") or m.get("text") or "" for m in o.get("messages", []) if m.get("severity") == "error"]
        return o.get("ok"), "\n".join(errs)
    if isinstance(o, dict) and "exit_code" in o:
        return o.get("exit_code") == 0, (o.get("stdout") or "") + (o.get("stderr") or "")
    return None, out


def cat(text):
    for name, rx in CATS:
        if re.search(rx, text or ""):
            return name
    return "other"


def main(arms):
    res = {}
    for arm in arms:
        rows = {json.loads(l)["call_id"]: json.loads(l) for l in open(os.path.join(AUDIT, "data", arm, "tool_calls.jsonl"))}
        calls = json.load(open(os.path.join(HERE, "cache", f"{arm}-calls.json")))["calls"]
        seen = set()
        c = collections.Counter()
        names = collections.Counter()
        env = 0
        for x in calls:
            if x["call_id"] in seen or x["call_id"] not in rows:
                continue
            seen.add(x["call_id"])
            if x["name"] == "lean_check":
                kind = "lean_check"
            elif x["name"] == "shell" and COMPILE.search(" ".join(map(str, x["args"].get("argv") or []))):
                kind = "shell_lean"
            else:
                continue
            ok, err = errors_of(x["output"])
            c[kind] += 1
            if ok:
                c[kind + "_ok"] += 1
                continue
            if kind == "shell_lean" and re.search(r"lake: command not found|No such file|unknown package|not found: lake|could not find", err or ""):
                env += 1
                c["env_path_error"] += 1
                continue
            k = cat(err)
            c[kind + "_fail"] += 1
            c["cat_" + k] += 1
            if k == "unknown_name":
                for m in re.findall(r"Unknown (?:constant|identifier) `([^`]+)`", err or ""):
                    names[m] += 1
        res[arm] = dict(counts=dict(c), unknown_names=names.most_common(12))
    json.dump(res, open(os.path.join(HERE, "out", "proofpath", "leanfail.json"), "w"), indent=1)
    tot = collections.Counter()
    for arm, r in res.items():
        c = r["counts"]
        att = c.get("lean_check", 0) + c.get("shell_lean", 0)
        fail = c.get("lean_check_fail", 0) + c.get("shell_lean_fail", 0)
        tot.update({k: v for k, v in c.items()})
        print(f"{arm:24s} attempts={att:4d} fail={fail:3d} ({100 * fail / max(att, 1):.0f}%) env={c.get('env_path_error', 0)} "
              + " ".join(f"{k[4:]}={v}" for k, v in sorted(c.items()) if k.startswith("cat_")))
    att = tot["lean_check"] + tot["shell_lean"]
    fail = tot["lean_check_fail"] + tot["shell_lean_fail"]
    print("TOTAL attempts", att, "fail", fail, "env", tot["env_path_error"], {k[4:]: v for k, v in tot.items() if k.startswith("cat_")})
    allnames = collections.Counter()
    for r in res.values():
        for n, k in r["unknown_names"]:
            allnames[n] += k
    print("unknown names:", allnames.most_common(40))


if __name__ == "__main__":
    main(sys.argv[1:] or ARMS)
