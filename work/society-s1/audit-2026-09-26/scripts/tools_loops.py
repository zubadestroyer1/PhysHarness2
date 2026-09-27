"""Loops and repeated failures: identical calls, failure streaks, edit->check cycles per theorem."""
import json, re, collections, hashlib
from tools_lib import *

def full_args():
    out = {}
    for a in ARMS:
        for m in load(a, "messages"):
            if m["type"] == "function_call" and not m.get("inherited"):
                out[(a, m["call_id"])] = m["text"]
    return out

def is_check(c, shellcat):
    if c["tool"] == "lean_check":
        return True
    return c["tool"] == "shell" and shellcat.get((c["arm"], c["call_id"])) == "lean_compile"

def main():
    fa = full_args()
    shellcat = {(r["arm"], r["call_id"]): r["cat"] for r in json.load(open(os.path.join(os.path.dirname(__file__), "tools_out", "shell_rows.json")))}
    bys = calls_by_session()
    # 1. identical calls
    ident = collections.Counter(); ident_consec = 0; ident_calls = []
    for key, cs in bys.items():
        seen = collections.Counter(); prev = None
        for c in cs:
            h = (c["tool"], fa.get((c["arm"], c["call_id"]), c["arguments"]))
            if seen[h]:
                ident[c["tool"]] += 1; ident_calls.append(c)
                if prev == h:
                    ident_consec += 1
            seen[h] += 1; prev = h
    u, k, s = cost_of(ident_calls)
    print("identical repeated calls", sum(ident.values()), dict(ident.most_common()), "consecutive", ident_consec, "cost $%.2f %.1fmin" % (u, s / 60))
    # 2. failure streaks of Lean checks (lean_check or shell compile), ignoring interleaved non-check calls
    streaks = []
    for key, cs in bys.items():
        run = []
        for c in cs:
            if not is_check(c, shellcat):
                continue
            if c["outcome"] == "failed":
                run.append(c)
            else:
                if run: streaks.append((key, run, c))
                run = []
        if run: streaks.append((key, run, None))
    dist = collections.Counter(min(len(r), 10) for _, r, _ in streaks)
    print("lean failure streak lengths (checks until next ok check):", sorted(dist.items()))
    long = [(k, r, e) for k, r, e in streaks if len(r) >= 5]
    lu, lk, ls = cost_of([c for _, r, _ in long for c in r])
    print("streaks >=5:", len(long), "failed checks in them", sum(len(r) for _, r, _ in long), "cost $%.2f %.1fmin" % (lu, ls / 60), "ended unresolved", sum(1 for *_, e in long if e is None))
    for k, r, e in sorted(long, key=lambda x: -len(x[1]))[:8]:
        print("   ", k[0], k[1][:8], "turns", r[0]["turn"], "-", r[-1]["turn"], "len", len(r), "resolved" if e else "UNRESOLVED")
    # 3. checks per theorem until first ok (theorem name = first theorem/lemma in source)
    per = collections.defaultdict(list)
    for key, cs in bys.items():
        for c in cs:
            if c["tool"] != "lean_check":
                continue
            src = fa.get((c["arm"], c["call_id"]), "")
            m = re.search(r"(?:theorem|lemma)\s+([^\s({:\[]+)", src)
            if m:
                per[(key, m.group(1))].append(c)
    to_ok = []; never = 0
    for (key, name), cs in per.items():
        n = next((i + 1 for i, c in enumerate(cs) if c["outcome"] == "ok"), None)
        if n is None: never += 1
        else: to_ok.append(n)
    import statistics as st
    print("theorems checked", len(per), "reached ok", len(to_ok), "never ok", never, "checks-to-ok median", st.median(to_ok), "p90", sorted(to_ok)[int(.9 * len(to_ok))], "max", max(to_ok))
    print("checks per theorem incl. after ok: median", st.median(len(v) for v in per.values()), "total", sum(len(v) for v in per.values()))
    rechecks_after_ok = sum(max(0, len(cs) - (next((i + 1 for i, c in enumerate(cs) if c["outcome"] == "ok"), len(cs)))) for cs in per.values())
    print("lean_check calls on a theorem after it already compiled ok:", rechecks_after_ok)

main()
