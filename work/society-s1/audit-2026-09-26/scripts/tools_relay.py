"""Cross-workspace code relay: Lean lines an agent emits (write_file / lean_check / shell args)
that it first received from a peer (commons_read / inbox outputs, pushed network updates).
Workspaces are per-agent VMs, so peer code can only arrive as text in context and must be
re-emitted by the model as output tokens to reach its own workspace.
"""
import json, re, collections
from tools_lib import *

ESC = re.compile(r"\\u([0-9a-fA-F]{4})")


def decode(t):
    t = ESC.sub(lambda m: chr(int(m.group(1), 16)), t)
    return t.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")


def lines(t):
    return {l.strip() for l in decode(t).split("\n") if len(l.strip()) >= 30 and not l.strip().startswith(("import", "open", "--"))}


def main():
    T = turns_index()
    agg = collections.Counter(); per_arm = collections.Counter(); sessions_with = set()
    for a in ARMS:
        by_sess = collections.defaultdict(list)
        for m in load(a, "messages"):
            by_sess[m["session_id"]].append(m)
        for s, ms in by_sess.items():
            received = set(); own = set()
            for m in ms:
                if m.get("inherited"):
                    continue
                if (m["type"] == "function_call_output" and m.get("tool") in ("commons_read", "inbox", "read_artifact")) or m.get("subtype") == "research_network_updates":
                    received |= lines(m["text"]) - own
                elif m["type"] == "function_call" and m.get("tool") in ("write_file", "lean_check", "shell"):
                    ls = lines(m["text"])
                    hit = ls & received
                    if hit:
                        chars = sum(len(l) for l in hit)
                        agg[m["tool"]] += chars; per_arm[group(a)] += chars; sessions_with.add((a, s))
                        agg["calls_" + m["tool"]] += 1
                    own |= ls
                elif m["type"] == "function_call" and m.get("tool") in ("commons_post", "message"):
                    own |= lines(m["text"])
    print("re-emitted peer Lean chars by tool:", {k: v for k, v in agg.items()})
    print("by group:", dict(per_arm), "sessions:", len(sessions_with))
    tot = sum(v for k, v in agg.items() if not k.startswith("calls_"))
    print("total %.0fk chars ~ %.0fk output tokens (2.55 c/t) ~ $%.2f output + ~%.0f s generation at 7.8 ms/token" % (tot / 1e3, tot / 2.55 / 1e3, tot / 2.55 * 1e-5, tot / 2.55 * 0.0078))

main()
