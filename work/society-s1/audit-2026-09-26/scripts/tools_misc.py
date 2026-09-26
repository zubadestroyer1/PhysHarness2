"""Remaining tool-friction numbers for tools.md (run after tools_shell.py and the search dump).

Sections: tool profile; rejection costs; statement check; lake PATH detour; lean_check
automation vs OOM; search_library hit rates; inbox usage; verification; totals.
"""
import json, re, collections, statistics as st
from tools_lib import *

OUT = os.path.join(os.path.dirname(__file__), "tools_out")


def pct(x, p):
    x = sorted(x)
    return x[min(len(x) - 1, int(p * len(x)))] if x else 0


def outputs(tool):
    out = {}
    for a in ARMS:
        for m in load(a, "messages"):
            if m["type"] == "function_call_output" and m.get("tool") == tool and not m.get("inherited"):
                out[(a, m["call_id"])] = m
    return out


def profile(calls):
    print("## tool profile")
    by = collections.defaultdict(list)
    for c in calls:
        by[c["tool"]].append(c)
    for t, cs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        oc = [c["output_chars"] or 0 for c in cs]
        d = [c["duration_s"] for c in cs if c["duration_s"] is not None]
        roles = collections.Counter(c["hat"] for c in cs)
        print(f"{t:24} n={len(cs):4} root/recruit/referee={roles['root']}/{roles['recruit']}/{roles['referee']} "
              f"rej={sum(c['outcome']=='rejected' for c in cs)} fail={sum(c['outcome']=='failed' for c in cs)} "
              f"outK med/p90={st.median(oc)/1e3:.1f}/{pct(oc,.9)/1e3:.1f} dur med={st.median(d) if d else 0:.1f}s")


def rejections(calls):
    print("## rejection direct cost")
    by = collections.defaultdict(list)
    for c in calls:
        if c["outcome"] == "rejected":
            by[c["error_code"]].append(c)
    for k, cs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        u, t, s = cost_of(cs)
        print(f"{k:28} n={len(cs)} ${u:.2f} {t/1e6:.2f}M tok {s/60:.1f} min")
    u, t, s = cost_of([c for c in calls if c["outcome"] == "rejected"])
    print(f"all rejections ${u:.2f} {s/60:.1f} min")


def statement_check():
    print("## statement check (lean_check with node_id)")
    reasons = collections.Counter(); renew = collections.Counter()
    for (a, cid), m in outputs("lean_check").items():
        t = m["text"]
        mm = re.search(r'"local_compile": (\{.*?\})', t)
        if mm:
            r = re.search(r'"reason": "([^"]{0,60})', mm.group(1))
            reasons[r.group(1) if r else "?"] += 1
        r2 = re.search(r'"claim_renewed": (true|false)', t)
        if r2:
            renew[r2.group(1)] += 1
    print(dict(reasons), "claim_renewed", dict(renew))
    ex = collections.Counter()
    for w in load_all("workspace_ops"):
        if "check-run" in (w.get("sub_operation") or ""):
            ex[w["exit_code"]] += 1
    print("check-run exit codes", dict(ex))


def lake_detour():
    print("## lake PATH")
    rs = json.load(open(os.path.join(OUT, "shell_rows.json")))
    sh = {(r["arm"], r["call_id"]): r for r in rs}
    bys = calls_by_session()
    tight = []; loose = []
    for r in rs:
        if r["exit_code"] != 127:
            continue
        cs = bys[(r["arm"], r["session_id"])]
        i = [c["call_id"] for c in cs].index(r["call_id"])
        t_, l_ = [cs[i]], [cs[i]]
        for c in cs[i + 1:i + 8]:
            s = sh.get((c["arm"], c["call_id"]))
            if (s and s["cat"] == "lean_compile" and s["outcome"] == "ok") or c["tool"] == "lean_check":
                break
            l_.append(c)
            if s and (s["cat"] == "env_probe" or (s["cat"] == "lean_compile" and s["exit_code"] == 127)):
                t_.append(c)
        tight += t_; loose += l_
    for name, x in (("tight", tight), ("loose", loose)):
        u, t, s = cost_of(x)
        print(f"{name}: {len(x)} calls ${u:.2f} {s/60:.1f} min, sessions {len({(c['arm'], c['session_id']) for c in x})}")


def automation():
    print("## automation on holes vs REPL OOM")
    args = {}
    for a in ARMS:
        for m in load(a, "messages"):
            if m["type"] == "function_call" and m.get("tool") == "lean_check" and not m.get("inherited"):
                try:
                    args[(a, m["call_id"])] = json.loads(m["text"]).get("automate", True)
                except Exception:
                    pass
    c = collections.Counter()
    for k, m in outputs("lean_check").items():
        holes = '"holes": [{' in m["text"]
        c[(args.get(k, "?"), holes, "lean_repl_crashed" in m["text"])] += 1
    print({str(k): v for k, v in c.items()})
    print("cgroup_oom_observed ops", sum(1 for w in load_all("workspace_ops") if w["limit_reason"] == "cgroup_oom_observed"))


def search(calls):
    print("## search_library / read_source")
    rows = json.load(open(os.path.join(OUT, "search_rows.json")))
    zero = {(r[0], r[1], r[2]) for r in rows if r[4] == 0}
    zc = [c for c in calls if c["tool"] == "search_library" and (c["arm"], c["session_id"], c["turn"]) in zero]
    u, t, s = cost_of(zc)
    print(f"zero-hit {len(zero)}/{len(rows)} ${u:.2f} {s/60:.1f} min")
    rs = json.load(open(os.path.join(OUT, "shell_rows.json")))
    lib = [r for r in rs if r["cat"] == "lib_search"]
    print("shell rg lib searches", len(lib), "using | head", sum("head" in r["cmd"] for r in lib))


def inbox(calls):
    print("## inbox")
    out = outputs("inbox")
    ib = [c for c in calls if c["tool"] == "inbox"]
    empty = sum('"items": []' in m["text"] for m in out.values())
    u, t, s = cost_of(ib)
    print(f"inbox calls {len(ib)} empty {empty} ${u:.2f} {s/60:.1f} min")


def main():
    calls = load_all("tool_calls")
    sessions = load_all("sessions")
    print(f"calls {len(calls)} sessions {len(sessions)} ledger ${sum(float(s['cost_usd_ledger']) for s in sessions):.2f} "
          f"input {sum(s['input_tokens'] for s in sessions)/1e6:.1f}M cached {sum(s['cached_input_tokens'] for s in sessions)/1e6:.1f}M "
          f"output {sum(s['output_tokens'] for s in sessions)/1e6:.2f}M turns {sum(s['turns'] for s in sessions)}")
    profile(calls); rejections(calls); statement_check(); lake_detour(); automation(); search(calls); inbox(calls)
    for tool in ("submit_for_verification", "verification_status"):
        print(tool, collections.Counter((re.search(r'"status": "(\w+)"', m["text"]) or [None, None])[1] for m in outputs(tool).values()))


main()
