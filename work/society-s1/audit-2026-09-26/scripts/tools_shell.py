"""Classify every shell call by what the agent used it for (finer than extract.py's intent)."""
import json, re, collections, statistics as st
from tools_lib import *

LIB = r"(/opt/sources|Mathlib/|mathlib/|physlib|\.lake/packages)"
RULES = [
    ("lean_compile", re.compile(r"(lake\s+env\s+lean|/bin/lean\s|\blean\s+[^|;&]*\.lean|lake\s+build)")),
    ("file_edit_python", re.compile(r"python3?[^\n]*(<<|-c)[\s\S]*(\.replace\(|write_text|open\([^)]*['\"]w['\"])")),
    ("file_write_shell", re.compile(r"(cat\s*>\s*\S+\s*<<|tee\s+\S+\s*<<|printf[^|]*>\s*\S+|perl\s+-[pi]|sed\s+-i)")),
    ("env_probe", re.compile(r"(command -v|which\s|--version|/opt/lean/bin|elan|lake\s+--help|lean\s+--help|find /opt -maxdepth|ls /opt)")),
    ("lib_search", re.compile(r"\b(rg|grep)\b[^\n]*" + LIB)),
    ("lib_search_cwd", re.compile(r"^\s*(rg|grep)\b")),
    ("lib_view", re.compile(r"\b(sed|cat|head|tail|nl|awk)\b[^\n]*" + LIB)),
    ("ws_view", re.compile(r"\b(sed|cat|head|tail|nl)\b[^\n]*(/work|scratch/|\.lean|\.py)")),
    ("ws_inspect", re.compile(r"\b(ls|find|wc|sha256sum|pwd|stat|du)\b")),
    ("clock", re.compile(r"^\s*date\b")),
    ("python_compute", re.compile(r"python3?")),
]


def command_of(args):
    try:
        a = json.loads(args)
    except Exception:
        return None, None
    argv = a.get("argv") or []
    if len(argv) >= 3 and argv[0] in ("bash", "sh") and argv[1] in ("-lc", "-c"):
        return argv[2], a.get("cwd")
    return " ".join(argv), a.get("cwd")


def classify(cmd):
    for name, rx in RULES:
        if rx.search(cmd):
            return name
    return "other"


def rows():
    out = []
    for a in ARMS:
        full = {}
        for m in load(a, "messages"):
            if m["type"] == "function_call" and m.get("tool") == "shell" and not m.get("inherited"):
                full[m["call_id"]] = m["text"]
        for c in load(a, "tool_calls"):
            if c["tool"] != "shell":
                continue
            cmd, cwd = command_of(full.get(c["call_id"], c["arguments"]))
            if cmd is None:
                cmd, cwd = "<unparsed>", None
            out.append({**c, "cmd": cmd, "cwd": cwd, "cat": classify(cmd)})
    return out


if __name__ == "__main__":
    rs = rows()
    by = collections.defaultdict(list)
    for r in rs:
        by[r["cat"]].append(r)
    print(f"{'category':18} {'n':>4} {'fail':>4} {'dur_med':>7} {'dur_sum_m':>9} {'outK_med':>8} {'outK_sum':>8}")
    for cat, cs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        d = [c["duration_s"] for c in cs if c["duration_s"]]
        oc = [c["output_chars"] or 0 for c in cs]
        print(f"{cat:18} {len(cs):4} {sum(c['outcome']=='failed' for c in cs):4} {st.median(d):7.1f} {sum(d)/60:9.1f} {st.median(oc)/1000:8.1f} {sum(oc)/1000:8.0f}")
    grp = collections.defaultdict(collections.Counter)
    for r in rs:
        grp[group(r["arm"])][r["cat"]] += 1
    for g, c in grp.items():
        print(g, dict(c.most_common()))
    json.dump([{k: r[k] for k in ("arm", "session_id", "turn", "call_id", "cat", "cmd", "cwd", "outcome", "exit_code", "duration_s", "output_chars", "hat")} for r in rs],
              open(os.path.join(os.path.dirname(__file__), "tools_out", "shell_rows.json"), "w"))
