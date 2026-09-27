"""Per arm-group friction rates (per 100 calls) and lookup share of context rent."""
import json, collections
from tools_lib import *

LOOKUP = {"search_library", "read_source"}


def main():
    sh = {(r["arm"], r["call_id"]): r["cat"] for r in json.load(open(os.path.join(os.path.dirname(__file__), "tools_out", "shell_rows.json")))}
    sessions = {(s["arm"], s["session_id"]): s for s in load_all("sessions")}
    G = ["cal/pilot", "S", "S-r2", "I", "single"]
    st = {g: collections.Counter() for g in G}
    for c in load_all("tool_calls"):
        g = group(c["arm"]); s = st[g]
        s["calls"] += 1
        s["rej"] += c["outcome"] == "rejected"
        s["fail"] += c["outcome"] == "failed"
        cat = sh.get((c["arm"], c["call_id"]))
        s["lookup_calls"] += c["tool"] in LOOKUP or cat in ("lib_search", "lib_search_cwd", "lib_view")
        s["lake127"] += c.get("exit_code") == 127
    for a in ARMS:
        g = group(a)
        for m in load(a, "messages"):
            if m["type"] != "function_call_output" or m.get("inherited"):
                continue
            ss = sessions[(a, m["session_id"])]
            rent = m["chars"] / 2.55 * (max(0, ss["turns"] - (m.get("turn") or 0)) + 1)
            st[g]["rent"] += rent
            if m["tool"] in LOOKUP or sh.get((a, m["call_id"])) in ("lib_search", "lib_search_cwd", "lib_view"):
                st[g]["lookup_rent"] += rent
    for s in sessions.values():
        st[group(s["arm"])]["input"] += s["input_tokens"]
        st[group(s["arm"])]["usd"] += float(s["cost_usd_ledger"])
    print(f"{'group':10} {'calls':>6} {'rej/100':>7} {'fail/100':>8} {'lookup%calls':>12} {'toolrent%in':>11} {'lookup%in':>9} {'lookup$':>8}")
    for g in G:
        s = st[g]
        print(f"{g:10} {s['calls']:6} {100*s['rej']/s['calls']:7.2f} {100*s['fail']/s['calls']:8.1f} {100*s['lookup_calls']/s['calls']:12.1f} {100*s['rent']/s['input']:11.1f} {100*s['lookup_rent']/s['input']:9.1f} {s['lookup_rent']*2.5e-6:8.2f}")

main()
