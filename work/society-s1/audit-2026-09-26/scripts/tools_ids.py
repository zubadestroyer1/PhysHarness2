"""Identifier hygiene: UUID arguments never seen earlier in the session transcript (guessed or
completed from an 8-hex prefix), and 8-hex short ids written into posts/messages."""
import json, re, collections
from tools_lib import *

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SHORT = re.compile(r"(?<![0-9a-f-])[0-9a-f]{8}(?![0-9a-f-])")
ID_TOOLS = {"commons_read", "commons_node", "commons_post", "commons_claim", "message", "wait", "verification_status", "read_artifact", "recruit", "inbox"}


def main():
    calls = {(c["arm"], c["call_id"]): c for c in load_all("tool_calls")}
    unseen = []; seen_ok = 0; short_posts = 0; posts = 0; short_ids = 0
    for a in ARMS:
        by = collections.defaultdict(list)
        for m in load(a, "messages"):
            by[m["session_id"]].append(m)
        for s, ms in by.items():
            known = set(); prefixes = set()
            for m in ms:
                t = m.get("text") or ""
                if m["type"] == "function_call" and m.get("tool") in ID_TOOLS and not m.get("inherited"):
                    try:
                        args = json.loads(t)
                    except Exception:
                        args = {}
                    for k, v in args.items():
                        vals = v if isinstance(v, list) else [v]
                        for x in vals:
                            if isinstance(x, str) and UUID.fullmatch(x):
                                c = calls.get((a, m["call_id"]))
                                if x in known:
                                    seen_ok += 1
                                else:
                                    unseen.append((a, s[:8], m.get("turn"), m["tool"], k, x, x[:8] in prefixes, c["outcome"] if c else None, c["error_code"] if c else None))
                            elif isinstance(x, str) and re.fullmatch(r"[0-9a-f]{8}", x):
                                c = calls.get((a, m["call_id"]))
                                unseen.append((a, s[:8], m.get("turn"), m["tool"], k, x, True, c["outcome"] if c else None, c["error_code"] if c else None))
                if m["type"] == "function_call" and m.get("tool") in ("commons_post", "message") and not m.get("inherited"):
                    posts += 1
                    body = UUID.sub("", t)
                    n = len(SHORT.findall(body))
                    if n:
                        short_posts += 1; short_ids += n
                known.update(UUID.findall(t))
                prefixes.update(x[:8] for x in UUID.findall(t))
                prefixes.update(SHORT.findall(t))
    print("id args seen earlier:", seen_ok, "| never seen earlier:", len(unseen))
    print(collections.Counter((u[7], u[8]) for u in unseen))
    for u in unseen:
        print("  ", u)
    print("posts/messages:", posts, "containing bare 8-hex short ids:", short_posts, "short ids:", short_ids)

main()
