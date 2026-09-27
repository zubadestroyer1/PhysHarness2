"""Proof-path audit: provenance of the accepted proof and on-path/dead-end split (read-only).

Inputs: out/proofpath/<arm>_calls.json (from proofpath_timeline.py) and the accepted proof
source out/proofs/<arm>.lean (the submitted candidate, by sha256, from the arm export).
Writes out/proofpath/analysis.json and prints a per-arm digest.

Call labels (one tool call per turn, so a turn's tokens follow its call):
  path      authored Lean (lean_check / write_file / shell heredoc / message) that declares at
            least one declaration whose name is in the final proof
  deadend   authored Lean declaring only names absent from the final proof
  probe     authored Lean with no declarations (API probes, #check, example, small tests)
  compile   shell compile / file edit runs without new declarations
  search    search_library, read_source, shell inspection (rg/sed/ls/find)
  commons   commons_*, message, inbox, notebook, wait, read_artifact, read_file, recruit
  review    submit_review (referees)
  submit    submit_for_verification, verification_status, return_result
"""
import collections
import difflib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out", "proofpath")
ARMS = ["calibration-doeblin-r2", "calibration-aperiodic", "pilot-doeblin", "S-r2", "I-01",
        "I-02", "I-03", "I-04", "I-05", "I-06", "I-07", "I-08", "single"]
DECL = re.compile(r"^[ \t]*(?:private\s+|protected\s+|noncomputable\s+)*(?:theorem|lemma|def|abbrev|instance)\s+([^\s:({\[]+)", re.M)
FAIL_KINDS = [
    ("unknown_name", re.compile(r"Unknown (constant|identifier)|unknown (constant|identifier)|unknown namespace", re.I)),
    ("no_goals", re.compile(r"No goals to be solved|no goals")),
    ("unsolved_goals", re.compile(r"unsolved goals")),
    ("type_mismatch", re.compile(r"type mismatch|Application type mismatch|failed to synthesize|cannot synthesize", re.I)),
    ("rewrite_simp", re.compile(r"rewrite. failed|motive is not type correct|simp made no progress|linarith failed|nlinarith failed|positivity failed|omega could not|failed to prove|gcongr", re.I)),
    ("parse", re.compile(r"unexpected token|expected", re.I)),
]


def jl(path):
    with open(path) as f:
        return [json.loads(line) for line in f]


def blocks(src):
    """name -> declaration text (up to the next top-level declaration)."""
    out = {}
    ms = list(DECL.finditer(src))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(src)
        # include the docstring immediately before? keep body only
        out[m.group(1)] = src[m.start():end].strip()
    return out


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


FILE = re.compile(r"(?:/work/)?scratch/([\w\-.]+\.lean)")
WRITES = re.compile(r"cat\s*>|open\([^)]*,\s*['\"]w|\+=\s*['\"]|\btee\b|printf .*>")


def track_files(rows):
    """Attach `file_decls` to shell rows: the declarations of the scratch files they touch.

    Workspaces are per branch, so files are keyed by session. write_file sets a file's
    declarations; shell heredocs / python appends add the declarations they carry."""
    files = collections.defaultdict(dict)
    for r in rows:
        fs = files[r["session"]]
        if r["tool"] == "write_file":
            path = FILE.search(r["summary"] or "")
            if path:
                fs[path.group(1)] = set(r["decls"])
        elif r["tool"] == "shell":
            text = r["text"] or ""
            touched = FILE.findall(text)
            names = re.search(r"(?:names|pieces|parts|files)\s*=\s*\[([^\]]*)\]", text)
            if names:
                parts = [re.sub(r"\.lean$", "", w) + ".lean" for w in re.findall(r"['\"]([\w\-.]+)['\"]", names.group(1))]
                srcs = [p for p in parts if p in fs]
                if touched and srcs:
                    out = touched[-1] if touched[-1] not in srcs else touched[0]
                    fs[out] = set().union(*[fs[p] for p in srcs])
                    touched = touched + srcs
            r["files"] = touched
            for src, dst in re.findall(r"\bcp\s+(?:/work/)?scratch/([\w\-.]+\.lean)\s+(?:/work/)?scratch/([\w\-.]+\.lean)", text):
                fs[dst] = set(fs.get(src, set()))
            if r["decls"] and touched and WRITES.search(text):
                heredoc = re.search(r"cat\s*(>>?)\s*(?:/work/)?scratch/([\w\-.]+\.lean)", text)
                if heredoc:
                    target = heredoc.group(2)
                    if heredoc.group(1) == ">":
                        fs[target] = set(r["decls"])
                    else:
                        fs.setdefault(target, set()).update(r["decls"])
                else:
                    target = touched[0]
                    if re.search(r"open\([^)]*,\s*['\"]w", text) and "+=" not in text:
                        fs[target] = set(r["decls"])
                    else:
                        fs.setdefault(target, set()).update(r["decls"])
            r["file_decls"] = sorted(set().union(*[fs.get(f, set()) for f in touched])) if touched else []


def label(row, final_names):
    tool = row["tool"]
    if tool == "shell" and not row["decls"] and row.get("files"):
        fd = row.get("file_decls") or []
        if fd:
            return "path" if any(d in final_names for d in fd) else "deadend"
        return "probe"
    if tool == "submit_review":
        return "review"
    if tool in ("submit_for_verification", "verification_status", "return_result"):
        return "submit"
    if tool in ("search_library", "read_source"):
        return "search"
    if tool in ("commons_post", "commons_read", "commons_node", "commons_claim", "commons_query",
                "message", "inbox", "notebook", "wait", "read_artifact", "read_file", "recruit"):
        if tool == "message" and row["decls"]:
            pass
        else:
            return "commons"
    ds = row["decls"]
    if tool in ("lean_check", "write_file", "shell", "message", "run_computation"):
        if ds:
            return "path" if any(d in final_names for d in ds) else "deadend"
        if tool == "lean_check":
            return "probe"
        if tool == "shell":
            t = row["text"]
            if re.search(r"lake env lean|lean /work|lake build|python3|sed -i|cat >|cat >>|perl -", t):
                return "compile"
            return "search"
        return "commons"
    return "other"


def main(arms):
    result = {}
    for arm in arms:
        d = json.load(open(os.path.join(OUT, f"{arm}_calls.json")))
        rows, turns = d["rows"], d["turns"]
        final_src = open(os.path.join(HERE, "out", "proofs", f"{arm}.lean")).read()
        fb = blocks(final_src)
        final_names = set(fb)
        # shell rows: recover declarations from heredoc text
        for r in rows:
            if r["tool"] == "shell" and not r["decls"]:
                r["decls"] = DECL.findall((r["text"] or "").replace("\\n", "\n"))
        track_files(rows)
        # provenance per final declaration
        prov = {}
        for name, body in fb.items():
            first = None
            best = None
            authors = collections.Counter()
            for r in rows:
                if name in r["decls"]:
                    authors[(r["session"][:8], r["hat"])] += 1
                    if first is None:
                        first = r
                    txt = blocks(r["text"] or "").get(name)
                    if txt:
                        ratio = difflib.SequenceMatcher(None, norm(txt), norm(body), autojunk=False).ratio() if len(txt) < 8000 else None
                        if ratio is not None and ratio > 0.95 and best is None:
                            best = (r, ratio)
            prov[name] = dict(
                first_t=first and first["t"], first_session=first and first["session"][:8],
                first_hat=first and first["hat"],
                near_final_t=best and best[0]["t"], near_final_session=best and best[0]["session"][:8],
                near_final_hat=best and best[0]["hat"],
                authors=[f"{s}/{h}:{n}" for (s, h), n in authors.most_common()],
                chars=len(body))
        # label calls and roll up turn tokens/cost
        tmap = {(t["session"], t["turn"]): t for t in turns}
        lab = collections.defaultdict(lambda: dict(calls=0, turns=0, input=0, output=0, cost=0.0))
        per_session = collections.defaultdict(lambda: collections.defaultdict(lambda: dict(calls=0, cost=0.0)))
        claimed = set()
        for r in rows:
            L = label(r, final_names)
            r["label"] = L
            t = tmap.get((r["session"], r["turn"]))
            x = lab[L]
            x["calls"] += 1
            if t and (r["session"], r["turn"]) not in claimed:
                claimed.add((r["session"], r["turn"]))
                x["turns"] += 1
                x["input"] += t["input"]
                x["output"] += t["output"]
                x["cost"] += float(t["cost"])
            per_session[r["session"][:8] + "/" + r["hat"]][L]["calls"] += 1
            if t:
                per_session[r["session"][:8] + "/" + r["hat"]][L]["cost"] += float(t["cost"])
        # turns with no tool call (final message turns)
        notool = [t for t in turns if (t["session"], t["turn"]) not in claimed]
        lab["no_tool"] = dict(calls=0, turns=len(notool), input=sum(t["input"] for t in notool),
                              output=sum(t["output"] for t in notool),
                              cost=sum(float(t["cost"]) for t in notool))
        # dead-end declarations: authored names never in final
        dead = collections.defaultdict(lambda: dict(first_t=None, sessions=set(), checks=0))
        for r in rows:
            for n in r["decls"]:
                if n not in final_names and r["tool"] in ("lean_check", "write_file", "shell"):
                    e = dead[n]
                    e["first_t"] = e["first_t"] if e["first_t"] is not None else r["t"]
                    e["sessions"].add(r["session"][:8] + "/" + r["hat"])
                    e["checks"] += 1
        # Lean failure taxonomy
        fails = collections.Counter()
        lean_checks = [r for r in rows if r["tool"] == "lean_check"]
        for r in lean_checks:
            if r["outcome"] == "failed":
                s = r["summary"]
                k = next((k for k, rx in FAIL_KINDS if rx.search(s)), "other")
                fails[k] += 1
        # milestones
        def first(pred):
            for r in rows:
                if pred(r):
                    return r
            return None
        sub = first(lambda r: r["tool"] == "submit_for_verification")
        m = dict(
            first_lean_ok=first(lambda r: r["tool"] == "lean_check" and r["outcome"] == "ok" and r["decls"]),
            first_target_mention=first(lambda r: "physics_target" in r["decls"]),
            first_target_ok=first(lambda r: "physics_target" in r["decls"] and r["tool"] == "lean_check" and r["outcome"] == "ok" and "sorry=0" in r["summary"]),
            first_recruit=first(lambda r: r["tool"] == "recruit"),
            submit=sub,
        )
        ms = {k: (v and dict(t=v["t"], session=v["session"][:8], hat=v["hat"], turn=v["turn"])) for k, v in m.items()}
        result[arm] = dict(
            final_decls=len(fb), final_chars=len(final_src), provenance=prov,
            labels={k: dict(v) for k, v in lab.items()},
            per_session={k: {kk: dict(vv) for kk, vv in v.items()} for k, v in per_session.items()},
            dead={k: dict(first_t=v["first_t"], sessions=sorted(v["sessions"]), checks=v["checks"]) for k, v in dead.items()},
            lean_checks=len(lean_checks),
            lean_fail=sum(1 for r in lean_checks if r["outcome"] == "failed"),
            lean_fail_kinds=dict(fails),
            milestones=ms,
        )
    with open(os.path.join(OUT, "analysis.json"), "w") as fh:
        json.dump(result, fh, indent=1, default=str)
    for arm, a in result.items():
        tot = sum(v["cost"] for v in a["labels"].values())
        print(f"== {arm} decls={a['final_decls']} checks={a['lean_checks']} fail={a['lean_fail']} {a['lean_fail_kinds']}")
        print("   labels:", {k: f"{v['turns']}t ${v['cost']:.2f} ({100 * v['cost'] / tot:.0f}%)" for k, v in sorted(a["labels"].items())})
        print("   milestones:", {k: v and f"{v['t'] / 60:.1f}m {v['session']}/{v['hat']}" for k, v in a["milestones"].items()})


if __name__ == "__main__":
    main(sys.argv[1:] or ARMS)


def first_ok(arm):
    """First successful compile time (min) per final declaration: lean_check ok with the
    declaration in its source, or an exit-0 `lean` shell run on a file holding it."""
    d = json.load(open(os.path.join(OUT, f"{arm}_calls.json")))
    rows = d["rows"]
    for r in rows:
        if r["tool"] == "shell" and not r["decls"]:
            r["decls"] = DECL.findall((r["text"] or "").replace("\\n", "\n"))
    track_files(rows)
    fb = blocks(open(os.path.join(HERE, "out", "proofs", f"{arm}.lean")).read())
    out = {}
    for r in rows:
        ok = r["outcome"] == "ok"
        if r["tool"] == "lean_check" and ok and "sorry=0" in r["summary"]:
            names = r["decls"]
        elif r["tool"] == "shell" and ok and re.search(r"\blean\b\s+/work|lake env lean|/opt/lean/bin/lean", r["text"] or ""):
            names = (r.get("file_decls") or []) + r["decls"]
        else:
            continue
        for n in names:
            if n in fb and n not in out:
                out[n] = (round(r["t"] / 60, 2), r["session"][:8], r["hat"])
    return {n: out.get(n) for n in fb}
