"""What-if: replace a tool output larger than THRESH chars with a 300-char stub (plus a re-fetch
handle) once it is K turns old. Counterfactual savings in re-sent input tokens, before any
re-fetches (assume a 10% re-fetch rate of the full output, charged once at its original size
for the rest of the session: pessimistic)."""
from tools_lib import *

def main():
    sessions = {(s["arm"], s["session_id"]): s for s in load_all("sessions")}
    total_in = sum(s["input_tokens"] for s in sessions.values())
    outs = []
    for a in ARMS:
        for m in load(a, "messages"):
            if m["type"] == "function_call_output" and not m.get("inherited"):
                s = sessions[(a, m["session_id"])]
                outs.append((m["chars"], max(0, s["turns"] - (m.get("turn") or 0))))
    for thresh in (2000, 4000, 8000):
        for K in (3, 5, 10):
            saved = 0
            for ch, later in outs:
                if ch > thresh and later + 1 > K:
                    saved += (ch - 300) / 2.55 * (later + 1 - K)
            refetch = 0.10 * saved  # pessimistic
            net = saved - refetch
            print(f"thresh {thresh:5} K {K:2}: net saved {net/1e6:5.1f}M tokens = {net/total_in:5.1%} of all input = ${net*2.5e-6:6.2f} ledger")

main()
