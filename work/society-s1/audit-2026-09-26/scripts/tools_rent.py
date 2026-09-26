"""Context rent by tool: each output's tokens are re-sent on every later turn of its session.

tokens(output) = output_chars / 2.55 (median chars/token measured from input-token deltas of
974 turns whose tool output exceeded 2k chars). Rent (token-turns) = tokens x later turns in
the session (successor sessions start fresh; one compaction in the study, ignored).
Ledger $ uses $2.50/M on every input token (the harness prices cached tokens at full rate).
Also counts \\uXXXX escapes: json.dumps(ensure_ascii=True) in responses.py turns every
non-ASCII character of a tool output into a 6-char escape.
"""
import json, re, collections
from tools_lib import *

CPT = 2.55
ESC = re.compile(r"\\u[0-9a-fA-F]{4}")


def main():
    sessions = {(s["arm"], s["session_id"]): s for s in load_all("sessions")}
    T = turns_index()
    rent = collections.Counter(); first = collections.Counter(); esc_rent = collections.Counter()
    esc_n = collections.Counter(); chars = collections.Counter(); n = collections.Counter()
    for a in ARMS:
        for m in load(a, "messages"):
            if m["type"] != "function_call_output" or m.get("inherited"):
                continue
            s = sessions.get((a, m["session_id"]))
            if not s or m.get("turn") is None:
                continue
            later = max(0, (s["turns"] or 0) - m["turn"])
            tok = m["chars"] / CPT
            e = len(ESC.findall(m["text"]))
            if m.get("truncated") and len(m["text"]) > 0:
                e = e * m["chars"] / len(m["text"])  # extrapolate escapes past the 4000-char cut
            tool = m["tool"]
            rent[tool] += tok * later; first[tool] += tok; chars[tool] += m["chars"]; n[tool] += 1
            esc_n[tool] += e
            # an escape is 6 chars instead of 1: ~5 extra chars -> ~5/CPT tokens (upper) per escape
            esc_rent[tool] += e * (5 / CPT) * (later + 1)
    tot_rent = sum(rent.values()); tot_in = sum(float(s["input_tokens"]) for s in sessions.values())
    print(f"total input tokens {tot_in/1e6:.1f}M; tool-output rent {tot_rent/1e6:.1f}M token-turns ({tot_rent/tot_in:.0%} of all input)")
    print(f"{'tool':22} {'n':>5} {'charsK':>7} {'firstM':>7} {'rentM':>7} {'rent$':>7} {'%in':>5} {'escK':>6} {'escRentM':>8}")
    for t, r in rent.most_common():
        print(f"{t:22} {n[t]:5} {chars[t]/1e3:7.0f} {first[t]/1e6:7.2f} {(r+first[t])/1e6:7.1f} {(r+first[t])*2.5e-6:7.2f} {(r+first[t])/tot_in:5.1%} {esc_n[t]/1e3:6.1f} {esc_rent[t]/1e6:8.1f}")
    print("escape overhead total (upper est, token-turns) %.1fM = $%.2f ledger" % (sum(esc_rent.values())/1e6, sum(esc_rent.values())*2.5e-6))

main()
