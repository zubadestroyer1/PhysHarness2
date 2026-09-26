"""#check probes in lean_check: which Mathlib names agents guessed, which did not exist, and repeats."""
import json, re, collections
from tools_lib import *

def main():
    probes = []  # (arm, session, turn, name, found)
    for a in ARMS:
        src, out = {}, {}
        for m in load(a, "messages"):
            if m.get("inherited") or m.get("tool") != "lean_check":
                continue
            if m["type"] == "function_call":
                try:
                    src[m["call_id"]] = (json.loads(m["text"])["source"], m)
                except Exception:
                    pass
            elif m["type"] == "function_call_output":
                out[m["call_id"]] = m["text"]
        for cid, (s, m) in src.items():
            o = out.get(cid)
            if o is None:
                continue
            try:
                res = json.loads(o)
            except Exception:
                continue
            errlines = {msg.get("line") for msg in res.get("messages", []) if msg.get("severity") == "error"}
            for i, line in enumerate(s.split("\n"), 1):
                mm = re.match(r"\s*#check\s+@?([A-Za-z_][\w.'₀-₉]*)", line)
                if mm:
                    probes.append((a, m["session_id"], m.get("turn"), mm.group(1), i not in errlines))
    n = len(probes); miss = sum(1 for p in probes if not p[4])
    print("#check lines", n, "not found/err", miss, "sessions", len({(p[0], p[1]) for p in probes}))
    names = collections.defaultdict(list)
    for p in probes:
        names[p[3]].append(p)
    rep = [(k, v) for k, v in names.items() if len({(x[0], x[1]) for x in v}) > 1]
    print("distinct names", len(names), "checked in >1 session", len(rep),
          "checks of those", sum(len(v) for _, v in rep))
    same_sess = sum(len(v) - len({(x[0], x[1]) for x in v}) for v in names.values())
    print("re-checks of same name within a session", same_sess)
    top = sorted(names.items(), key=lambda kv: -len({(x[0], x[1]) for x in kv[1]}))[:25]
    for k, v in top:
        print(f"{k:50} sessions={len({(x[0], x[1]) for x in v}):3} arms={len({x[0] for x in v}):2} found={sum(x[4] for x in v)}/{len(v)}")
    json.dump(probes, open(os.path.join(os.path.dirname(__file__), "tools_out", "check_probes.json"), "w"))

main()
