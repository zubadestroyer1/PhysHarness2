"""Lean error taxonomy across lean_check (structured messages) and shell lake/lean compiles
(stdout 'file:line:col: error: ...' lines; transcript text is cut at 4000 chars, so shell
counts are lower bounds)."""
import json, re, collections
from tools_lib import *

ESC = re.compile(r"\\u([0-9a-fA-F]{4})")


def kind(e):
    if re.search(r"[Uu]nknown (constant|identifier)|unknown namespace", e): return "unknown identifier/constant"
    if "unknown module prefix" in e or "unknown package" in e: return "import/module path"
    if "Application type mismatch" in e or "Type mismatch" in e or "type mismatch" in e: return "type mismatch"
    if "unsolved goals" in e: return "unsolved goals"
    if "failed to synthesize" in e: return "instance synthesis"
    if "rewrite" in e.lower() or "motive is not type correct" in e: return "rewrite failed"
    if re.search(r"(linarith|nlinarith|positivity|omega|simp|norm_num|ring|gcongr|aesop|decide|exact\?)[^\n]{0,40}(failed|could not|made no progress)", e) or "made no progress" in e: return "tactic failed"
    if "unexpected token" in e or "expected" in e[:60]: return "parse error"
    if "heartbeats" in e or "timeout" in e.lower(): return "timeout/heartbeats"
    if "Function expected" in e: return "function expected"
    return "other"


def main():
    shcat = {(r["arm"], r["call_id"]): r["cat"] for r in json.load(open(os.path.join(os.path.dirname(__file__), "tools_out", "shell_rows.json")))}
    cnt = {"lean_check": collections.Counter(), "shell": collections.Counter()}
    for a in ARMS:
        for m in load(a, "messages"):
            if m["type"] != "function_call_output" or m.get("inherited"):
                continue
            t = ESC.sub(lambda x: chr(int(x.group(1), 16)), m["text"])
            if m["tool"] == "lean_check":
                for e in re.findall(r'"severity": "error", "line": \d+, "col": \d+, "text": "((?:[^"\\]|\\.){0,200})', t):
                    cnt["lean_check"][kind(e)] += 1
            elif m["tool"] == "shell" and shcat.get((a, m["call_id"])) == "lean_compile":
                for e in re.findall(r"\.lean:\d+:\d+: error: ([^\n\\]*(?:\\n[^\n\\]*){0,2})", t):
                    cnt["shell"][kind(e)] += 1
    for k, c in cnt.items():
        tot = sum(c.values())
        print(k, tot, [(x, v, f"{v/tot:.0%}") for x, v in c.most_common()])

main()
