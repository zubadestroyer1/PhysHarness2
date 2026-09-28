"""Pinned Mathlib and Physlib declaration finder for the workspace VM (standard library only).

The host uploads this file into the workspace and runs one of:

  declaration_index.py query --index P --root D [--root D] --mode name|type -- QUERY
  declaration_index.py read --root D [--root D] PATH LINE

Each prints one JSON object to stdout. ``query`` builds the index at P when it is missing:
a header scan of every ``.lean`` file under each root that keeps the declarations starting
at column 0, one row per declaration (name, signature, path, line, module), written to
``P.tmp`` and then renamed. It then ranks the rows against QUERY. ``read`` returns a
bounded window of source lines around LINE, never a whole file.
"""

import argparse
import difflib
import heapq
import json
import os
import re
import sys

MAX_FILES = 20_000
MAX_ROWS = 400_000
MAX_INDEX_BYTES = 64 * 1024 * 1024  # /work/.cache is RAM-backed tmpfs
MAX_RESULTS = 20
MAX_SIGNATURE = 300
MAX_ROW = 400
CONTINUATION_LINES = 6
READ_CONTEXT = 40
MAX_READ_BYTES = 4000
SKIPPED = frozenset({".lake", ".git"})
DECLARATION = re.compile(
    r"^(?:@\[[^\]]*\]\s*)?(?:(?:private|protected|noncomputable|nonrec|partial|unsafe)\s+)*"
    r"(theorem|lemma|def|abbrev|instance|structure|class|inductive|axiom|opaque)\s+"
    r"([^\s:({\[⦃]+)(.*)$"
)
NAMESPACE = re.compile(r"^namespace\s+(\S+)\s*$")
# A section, a noncomputable section and a mutual block are all closed by ``end``.
SECTION = re.compile(r"^(?:(?:noncomputable\s+)?section(?:\s+(\S+))?|mutual)\s*$")
END = re.compile(r"^end(?:\s+(\S+))?\s*$")
BODY = re.compile(r":=|\swhere\b")
TOKEN = re.compile(r"[\w.']+")


def _signature(first, following):
    """The declaration's rest of line plus indented continuation lines, cut at the body."""
    parts = [first]
    for line in following:
        if BODY.search(parts[-1]) or not line.strip() or not line[0].isspace():
            break
        if line.lstrip().startswith("|"):
            break
        parts.append(line)
    text = BODY.split(" ".join(parts), maxsplit=1)[0]
    return " ".join(text.split())[:MAX_SIGNATURE]


def _declarations(lines):
    """(name, signature, line number) for each column-0 declaration of one file."""
    scopes = []  # (is_namespace, part) per Lean scope, innermost last
    for index, line in enumerate(lines):
        match = DECLARATION.match(line)
        if match is not None:
            name = match.group(2)
            if name.startswith("_root_."):
                name = name[len("_root_.") :]
            else:
                name = ".".join([part for is_namespace, part in scopes if is_namespace] + [name])
            following = lines[index + 1 : index + 1 + CONTINUATION_LINES]
            yield name, _signature(match.group(3), following), index + 1
            continue
        opened = NAMESPACE.match(line)
        if opened is not None:
            scopes += [(True, part) for part in opened.group(1).split(".")]
            continue
        section = SECTION.match(line)
        if section is not None:
            scopes += [(False, part) for part in (section.group(1) or "").split(".")]
            continue
        ended = END.match(line)
        if ended is not None:
            del scopes[-len((ended.group(1) or "").split(".")) :]


def _rows(roots):
    files = rows = 0
    for root in roots:
        base = os.path.basename(os.path.normpath(root))
        for folder, dirs, names in os.walk(root):
            dirs[:] = sorted(entry for entry in dirs if entry not in SKIPPED)
            for filename in sorted(names):
                if not filename.endswith(".lean"):
                    continue
                files += 1
                if files > MAX_FILES:
                    return
                relative = os.path.relpath(os.path.join(folder, filename), root)
                relative = relative.replace(os.sep, "/")
                module = relative[: -len(".lean")].replace("/", ".")
                with open(os.path.join(folder, filename), encoding="utf-8", errors="replace") as f:
                    lines = f.read().splitlines()
                for name, signature, number in _declarations(lines):
                    rows += 1
                    if rows > MAX_ROWS:
                        return
                    yield f"{name}\t{signature}\t{base}/{relative}\t{number}\t{module}\n"


def build_index(path, roots):
    """Write the index to ``path``; exit 3 past MAX_INDEX_BYTES without writing it."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temporary = path + ".tmp"
    written = 0
    with open(temporary, "w", encoding="utf-8") as stream:
        for row in _rows(roots):
            size = len(row.encode("utf-8"))
            if written + size > MAX_INDEX_BYTES:
                stream.close()
                os.remove(temporary)
                print(json.dumps({"error": "index_too_large", "bytes": written}))
                sys.exit(3)
            stream.write(row)
            written += size
    os.replace(temporary, path)


def _name_score(name, query):
    if name == query:
        return 100
    if name.endswith("." + query):
        return 90
    folded, wanted = name.casefold(), query.casefold()
    if folded == wanted:
        return 85
    if folded.endswith(wanted):
        return 80
    if wanted in folded:
        return 60 - min(20, len(name) - len(query))
    parts = [part.casefold() for part in re.split(r"[._]", query) if part]
    share = sum(part in folded for part in parts) / len(parts) if parts else 0
    return 40 * share if share >= 0.5 else 0


def _type_score(signature, tokens):
    found = set(TOKEN.findall(signature))
    return 50 * sum(token in found for token in tokens) / len(tokens) if tokens else 0


def _render(row):
    name, signature, path, line, _module = row
    tail = f" — {path}:{line}"
    head = f"{name} {signature}" if signature else name
    return head[: MAX_ROW - len(tail)] + tail


def _scan(index):
    with open(index, encoding="utf-8") as stream:
        for line in stream:
            yield line.rstrip("\n").split("\t")


def query(index, mode, text):
    """The index streams by: a full Mathlib index is too large to hold as rows in memory."""
    tokens = TOKEN.findall(text)
    indexed = 0

    def scored():
        nonlocal indexed
        for row in _scan(index):
            indexed += 1
            score = _name_score(row[0], text) if mode == "name" else _type_score(row[1], tokens)
            if score > 0:
                yield -score, len(row[0]), row[0], row

    best = heapq.nsmallest(MAX_RESULTS, scored())
    exact = bool(best) and -best[0][0] >= 85
    suggestions = []
    if not exact:
        last = {}  # a name's last dotted part -> the first full name ending in it
        for row in _scan(index):
            last.setdefault(row[0].rsplit(".", 1)[-1], row[0])
        close = difflib.get_close_matches(text.rsplit(".", 1)[-1], list(last), n=5, cutoff=0.75)
        suggestions = [last[part] for part in close]
    top = best[0][3] if best else None
    return {
        "rows": [_render(entry[3]) for entry in best],
        "exact": exact,
        "top": {"name": top[0], "module": top[4]} if top else None,
        "did_you_mean": suggestions,
        "indexed": indexed,
    }


def read(roots, path, line):
    parts = path.split("/")
    bases = {os.path.basename(os.path.normpath(root)): root for root in roots}
    if (
        len(parts) < 2
        or parts[0] not in bases
        or not path.endswith(".lean")
        or any(part in {"", ".", ".."} for part in parts)
        or "\x00" in path
    ):
        return {"error": "unsafe_path"}
    try:
        with open(
            os.path.join(bases[parts[0]], *parts[1:]), encoding="utf-8", errors="replace"
        ) as f:
            lines = f.read().splitlines(keepends=True)
    except OSError:
        return {"error": "source_unavailable"}
    start = max(1, line - READ_CONTEXT)
    if start > len(lines):
        return {"error": "line_out_of_range", "lines": len(lines)}
    text = "".join(lines[start - 1 : line + READ_CONTEXT])
    data = text.encode("utf-8")
    truncated = len(data) > MAX_READ_BYTES
    if truncated:
        text = data[:MAX_READ_BYTES].decode("utf-8", "ignore")
    return {
        "path": path,
        "start_line": start,
        "end_line": start + text.count("\n") - text.endswith("\n"),
        "text": text,
        "truncated": truncated,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="declaration_index")
    commands = parser.add_subparsers(dest="command", required=True)
    find = commands.add_parser("query")
    find.add_argument("--index", required=True)
    find.add_argument("--root", action="append", required=True)
    find.add_argument("--mode", choices=("name", "type"), required=True)
    find.add_argument("text")
    window = commands.add_parser("read")
    window.add_argument("--root", action="append", required=True)
    window.add_argument("path")
    window.add_argument("line", type=int)
    args = parser.parse_args(argv)
    if args.command == "query":
        if not os.path.exists(args.index):
            build_index(args.index, args.root)
        result = query(args.index, args.mode, args.text)
    else:
        result = read(args.root, args.path, args.line)
    print(json.dumps(result, ensure_ascii=False))
    if "error" in result:
        sys.exit(2)


if __name__ == "__main__":
    main()
