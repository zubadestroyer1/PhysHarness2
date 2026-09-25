"""Fast Lean feedback for agents: a REPL session with automation on holes and goal extraction.

Backends, chosen once per workspace:
- ``repl``: a detached daemon keeps one REPL alive with imports cached per header;
- ``repl_inline``: providers that require a quiescent guest after every command (the local
  Docker workbench) run the same request against a private REPL that dies with the command;
- ``one_shot``: without a REPL binary, ``lake env lean`` on a scratch file, parsed from text.

Every result is evidence only: ``proof_status`` stays ``not_accepted``.
"""

import hashlib
import json
import re
import shlex
from importlib import resources

from ..errors import HarnessError
from ..formal_tools.lean_session_daemon import (
    SORRY_WARNING,
    parse_axioms,
    select_messages,
    split_header,
)

AUTOMATION = (
    "rfl",
    "norm_num",
    "simp",
    "simp_all",
    "linarith",
    "nlinarith",
    "positivity",
    "omega",
    "aesop",
    "exact?",
)
DAEMON_PATH = ".physharness/lean_session.py"  # workspace-relative upload target
# With background processes (E2B), the daemon runs from /tmp so it stays out of the small
# workspace checkpoint archive; a VM restore drops /tmp, which triggers a re-upload.
DAEMON_RUNTIME_DIR = "/tmp/physharness"
DAEMON_RUNTIME_PATH = DAEMON_RUNTIME_DIR + "/lean_session.py"
REPL_CANDIDATES = ("/opt/lean-repl/.lake/build/bin/repl",)
SOCKET_PATH = "/tmp/physharness-lean.sock"
LAKE_PROJECT = "/opt/sources/physlib"
# E2B accepts at most 32,768 bytes per uploaded file (the request file, or lean_scratch's
# scratch file); this leaves room for the request envelope around the source.
MAX_UPLOAD_BYTES = 32_768
MAX_SOURCE_BYTES = 30_000
MAX_MESSAGES = 50
MAX_MESSAGE_TEXT = 2000
MAX_HOLES = 32
MAX_GOAL = 4000
MAX_HEADER = 2000  # NodeCreate.lean_header
MAX_STATEMENT = 20000  # NodeCreate.lean_statement
MAX_AXIOM_NAMES = 32
MAX_NAME = 200
# The daemon answers this long before the provider's own timeout, which quarantines the VM.
RUN_MARGIN_SECONDS = 30
_DAEMON_MISSING = 97
_START_FAILURES = ("server_start_failed", "repl_start_failed")
_SEVERITIES = ("error", "warning", "info")
_ERRORS = {
    "timeout": ("lean_timeout", "Lean did not finish before the time limit; the REPL restarted."),
    "budget_exhausted": ("lean_timeout", "Lean ran out of time before the check could start."),
    "repl_crashed": ("lean_repl_crashed", "The Lean REPL crashed; it restarts on the next call."),
    "repl_error": ("lean_repl_error", "The Lean REPL rejected the request."),
}
_PHASES = {
    "timeout": "lean_timeout",
    "budget_exhausted": "lean_timeout",
    "repl_crashed": "lean_repl_crashed",
}
_HEADER = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?P<col>\d+): "
    r"(?P<severity>error|warning|info|information)(?:\([^)]*\))?: ?(?P<text>.*)$"
)
_EXTRACTED = re.compile(
    r"(?:\A|\n)\s*(?:Try this:\s*)?(?:\[apply\]\s*)?(?:theorem|lemma)\s+"
    r"(?P<name>[^\s(\[{:]+?)(?:\.\{(?P<universes>[^{}]*)\})?"
    r"(?P<signature>[\s(\[{:].*?):=\s*(?:by\s+)?sorry\s*\Z",
    re.S,
)
_DECLARATION = re.compile(
    r"^(?:@\[[^\]]*\]\s*)*(?:(?:private|protected|noncomputable|nonrec)\s+)*"
    r"(?:theorem|lemma)\s+(?P<name>[^\s(\[{:]+)"
)
_BLOCK = re.compile(r"^(?:(?:noncomputable\s+)?section|namespace|mutual)\b")


def parse_lean_output(text: str, path_hint: str | None) -> list[dict]:
    """Parse ``<file>:<line>:<col>: <severity>: <text>`` diagnostics from Lean's CLI.

    A message continues until the next header. Text before the first header (such as a Lake
    error) becomes one message without a position.
    """
    messages, preamble, current = [], [], None
    for raw in text.splitlines():
        match = _HEADER.match(raw)
        if match and (path_hint is None or match["path"] == path_hint):
            severity = match["severity"].replace("information", "info")
            current = {
                "severity": severity,
                "line": int(match["line"]),
                "col": int(match["col"]),
                "text": [match["text"]],
            }
            messages.append(current)
        elif current is not None:
            current["text"].append(raw)
        else:
            preamble.append(raw)
    for message in messages:
        message["text"] = "\n".join(message["text"]).strip()
    leading = "\n".join(preamble).strip()
    if leading:
        severity = "error" if leading.startswith("error") else "info"
        messages.insert(0, {"severity": severity, "line": None, "col": None, "text": leading})
    return messages


def parse_extracted(text: str) -> tuple[str, str, list[str]] | None:
    """Name, signature and universe parameters of an ``extract_goal`` statement.

    ``theorem extracted_1.{u_1} {α : Type u_1} : P := sorry`` ->
    ``("extracted_1", "{α : Type u_1} : P", ["u_1"])``; a caller elaborating the signature
    on its own needs ``universe u_1`` in scope.
    """
    match = _EXTRACTED.search(text or "")
    if match is None:
        return None
    signature = " ".join(match["signature"].split())
    if ":" not in signature:
        return None
    universes = [u.strip() for u in (match["universes"] or "").split(",") if u.strip()]
    return match["name"], signature, universes


def signature_from_extracted(text: str) -> tuple[str, str] | None:
    """``theorem extracted_1 (x : ℝ) : P := sorry`` -> ``("extracted_1", "(x : ℝ) : P")``."""
    parsed = parse_extracted(text)
    return None if parsed is None else parsed[:2]


def top_level_names(source: str) -> list[str]:
    """Names of ``theorem``/``lemma`` declarations outside every ``namespace`` block."""
    names, blocks, in_comment = [], [], False
    for line in source.split("\n"):
        stripped = line.strip()
        if in_comment:
            in_comment = "-/" not in stripped
            continue
        if stripped.startswith("/-"):
            in_comment = "-/" not in stripped[2:]
            continue
        block = _BLOCK.match(stripped)
        if block:
            blocks.append(block.group(0).split()[-1])
        elif re.match(r"^end\b", stripped):
            if blocks:
                blocks.pop()
        else:
            declaration = _DECLARATION.match(stripped)
            if declaration and "namespace" not in blocks:
                name = declaration["name"]
                if name not in names and len(names) < MAX_HOLES:
                    names.append(name)
    return names


_RAW_STRING = re.compile(r'r(#*)"')
_CHAR = re.compile(r"'(?:\\(?:x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|u\{[0-9a-fA-F]+\}|.)|[^\\'\n])'")
_OPENERS = {")": "(", "}": "{"}
_COMMAND = re.compile(
    r"(?<![\w.'!?])(namespace|section|mutual|end|theorem|lemma|def|abbrev|axiom|opaque|"
    r"instance|structure|class|inductive|variable)(?![\w'!?])"
)
_BLOCKS = ("namespace", "section", "mutual")
_NAME = re.compile(r"\s*([\w.'!?]+)")


def _ident_before(source: str, index: int) -> bool:
    previous = source[index - 1] if index else ""
    return bool(previous) and (previous.isalnum() or previous in "_'!?.")


def _block_comment_end(source: str, index: int) -> int:
    """The index after the ``-/`` that closes the (nested) block comment opened at index."""
    depth, index = 1, index + 2
    while index < len(source):
        if source.startswith("/-", index):
            depth, index = depth + 1, index + 2
        elif source.startswith("-/", index):
            depth, index = depth - 1, index + 2
            if depth == 0:
                return index
        else:
            index += 1
    return len(source)


def _string_end(source: str, index: int, interpolated: bool) -> int:
    index += 1
    while index < len(source):
        character = source[index]
        if character == "\\":
            index += 2
        elif character == '"':
            return index + 1
        elif interpolated and character == "{":
            index = _scan(source, index + 1, [], "}")
        else:
            index += 1
    return len(source)


def _opaque(text: str) -> str:
    """A literal as one token: equal literals stay equal, and no keyword can occur inside."""
    return (
        "\x00" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16].upper() + "\x00"
    )


def _scan(source: str, index: int, out: list, close: str | None) -> int:
    """Copy code into ``out`` from ``index`` until an unmatched ``close`` (or the end).

    Comments become whitespace; string, character and raw-string literals, escaped
    identifiers and syntax quotations become opaque tokens.
    """
    depth = 0
    while index < len(source):
        character = source[index]
        if source.startswith("--", index):
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
            out.append(" ")
        elif source.startswith("/-", index):
            end = _block_comment_end(source, index)
            out.append(" " + "\n" * source.count("\n", index, end))
        elif character == '"':
            interpolated = (
                index >= 2 and source[index - 1] == "!" and _ident_before(source, index - 1)
            )
            end = _string_end(source, index, interpolated)
            out.append(_opaque(source[index:end]))
        elif (
            character == "r"
            and not _ident_before(source, index)
            and _RAW_STRING.match(source, index)
        ):
            hashes = _RAW_STRING.match(source, index).group(1)
            end = source.find('"' + hashes, _RAW_STRING.match(source, index).end())
            end = len(source) if end < 0 else end + 1 + len(hashes)
            out.append(_opaque(source[index:end]))
        elif character == "'" and not _ident_before(source, index) and _CHAR.match(source, index):
            end = _CHAR.match(source, index).end()
            out.append(_opaque(source[index:end]))
        elif character == "«":
            end = source.find("»", index + 1)
            end = len(source) if end < 0 else end + 1
            out.append(_opaque(source[index:end]))
        elif character == "`" and source.startswith(("`(", "``("), index):
            start = source.index("(", index) + 1
            end = _scan(source, start, [], ")")
            out.append(_opaque(source[index:end]))
        else:
            if close is not None:
                if character == _OPENERS[close]:
                    depth += 1
                elif character == close:
                    if depth == 0:
                        return index + 1
                    depth -= 1
            out.append(character)
            end = index + 1
        index = end
    return len(source)


def lean_code(source: str) -> str:
    """Lean source with comments blanked and literals and quotations made opaque tokens."""
    out: list[str] = []
    _scan(source, 0, out, None)
    return "".join(out)


def top_level_declarations(code: str) -> list[tuple[str, str, str]]:
    """``(keyword, name, rest)`` for each declaration outside every namespace, section and
    mutual block of ``lean_code`` output, plus ``("variable", "", rest)`` for each variable
    command anywhere, since variables change a declaration's signature."""
    found, blocks = [], 0
    for match in _COMMAND.finditer(code):
        keyword = match.group(1)
        if keyword in _BLOCKS:
            blocks += 1
        elif keyword == "end":
            blocks = max(0, blocks - 1)
        elif keyword == "variable":
            found.append((keyword, "", code[match.end() :]))
        elif blocks == 0:
            name = _NAME.match(code, match.end())
            if name is not None:
                found.append((keyword, name.group(1), code[name.end() :]))
    return found


def _clean(value: str) -> str:
    """Replace lone surrogates (JSON ``\\ud800`` escapes) so the text is encodable UTF-8."""
    return value.encode("utf-8", "replace").decode("utf-8")


def _clip(value, limit):
    if not isinstance(value, str):
        return None
    value = _clean(value)
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _message(severity, line, col, text):
    return {"severity": severity, "line": line, "col": col, "text": _clip(text, MAX_MESSAGE_TEXT)}


def _no_automation():
    return {"closed_by": None, "suggestion": None, "tried": []}


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _position(item):
    """Line and column from a REPL ``pos``: non-negative ints or None."""
    position = item.get("pos")
    if not isinstance(position, dict):
        return None, None
    line, col = position.get("line"), position.get("column")
    valid = [
        v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None
        for v in (line, col)
    ]
    return valid[0], valid[1]


def _normalise_check(response):
    """Re-type a daemon ``check`` answer. The VM, so the agent, controls these bytes."""
    counts, messages = response.get("counts"), response.get("messages", [])
    sorries, axioms = response.get("sorries", []), response.get("axioms")
    if (
        response.get("op") != "check"
        or not isinstance(counts, dict)
        or not isinstance(messages, list)
        or not isinstance(sorries, list)
        or not (axioms is None or isinstance(axioms, dict))
    ):
        raise ValueError("malformed Lean session answer")
    clean_counts = {
        key: _count(counts.get(key)) for key in ("errors", "messages", "sorries", "sorry_warnings")
    }
    clean_messages = []
    for item in messages:
        if isinstance(item, dict):
            severity = item.get("severity")
            data = item.get("data")
            clean_messages.append(
                _message(
                    severity if severity in _SEVERITIES else "info",
                    *_position(item),
                    data if isinstance(data, str) else "",
                )
            )
    holes, extracted = [], []
    for item in sorries:
        if not isinstance(item, dict) or len(holes) >= MAX_HOLES:
            continue
        automation = item.get("automation") if isinstance(item.get("automation"), dict) else {}
        tried = automation.get("tried") if isinstance(automation.get("tried"), list) else []
        closed = automation.get("closed_by")
        line, col = _position(item)
        holes.append(
            {
                "index": len(holes),
                "line": line,
                "col": col,
                "goal": _clip(item.get("goal"), MAX_GOAL),
                "automation": {
                    "closed_by": closed if closed in AUTOMATION else None,
                    "suggestion": _clip(automation.get("suggestion"), MAX_MESSAGE_TEXT),
                    "tried": [t for t in tried if t in AUTOMATION][: len(AUTOMATION)],
                },
            }
        )
        extracted.append(_clip(item.get("extracted"), MAX_STATEMENT + MAX_NAME))
    clean_axioms = {}
    for name, values in (axioms or {}).items():
        if len(clean_axioms) < MAX_AXIOM_NAMES and 0 < len(name) <= MAX_NAME:
            if isinstance(values, list):
                clean_axioms[_clean(name)] = [
                    _clean(v) for v in values if isinstance(v, str) and 0 < len(v) <= MAX_NAME
                ][:MAX_AXIOM_NAMES]
    return clean_counts, clean_messages, holes, extracted, clean_axioms


def _appended_axioms(report, source, names):
    """``#print axioms`` results read only from the lines appended after ``source``.

    Each report must be Lean's message at its own appended line of the scratch file, and
    must open with the name printed there; output that agent code printed (``#eval``,
    either stream) carries other positions or paths and is ignored, and so is any text
    after the report in the same message.
    """
    output, path = report["diagnostics"], "/work/" + report["source_path"]
    first = source.count("\n") + 2  # printed = source + "\n" + one line per name
    axioms = {}
    for stream in ("stdout", "stderr"):
        for message in parse_lean_output(output.get(stream) or "", path):
            index = (message["line"] or 0) - first
            if message["severity"] != "info" or not 0 <= index < len(names):
                continue
            name, text = names[index], message["text"]
            if text.startswith(f"'{name}' does not depend on any axioms"):
                entry = []
            elif text.startswith(f"'{name}' depends on axioms: [") and "]" in text:
                entry = parse_axioms(text[: text.index("]") + 1]).get(name)
            else:
                entry = None
            if entry is not None and name not in axioms:
                axioms[name] = entry
    return axioms


class LeanSession:
    """One Lean session per workspace, reached through the existing broker tools."""

    def __init__(self, workspace_tools):
        self._tools = workspace_tools
        self._backend = None
        self._repl = None
        self._note = None

    async def check(
        self, source: str, *, automate: bool, operation_id: str, timeout: float = 120
    ) -> dict:
        result, _ = await self._check(source, automate, False, operation_id, timeout)
        return result

    async def sketch_goals(self, source: str, *, operation_id: str) -> dict:
        result, extracted = await self._check(source, True, True, operation_id, 120)
        header = split_header(source)[0]
        holes, closed = [], []
        for hole, text in zip(result["holes"], extracted, strict=True):
            automation = hole["automation"]
            if automation["closed_by"]:
                closed.append(
                    {
                        "index": hole["index"],
                        "closed_by": automation["closed_by"],
                        "suggestion": automation["suggestion"],
                    }
                )
                continue
            entry = {"index": hole["index"], "goal": hole["goal"]}
            parsed = parse_extracted(text) if text else None
            if len(header) > MAX_HEADER:
                failure = "header_too_long"
            elif text is None and result["backend"] == "one_shot":
                failure = "goal_unavailable"
            elif (text and text.endswith("…")) or (parsed and len(parsed[1]) > MAX_STATEMENT):
                failure = "statement_too_long"  # never a silently truncated statement
            elif parsed is None:
                failure = "extract_goal_failed"
            else:
                failure = None
                entry.update(
                    lean_name=f"hole_{hole['index']}",
                    lean_statement=parsed[1],
                    universes=parsed[2],
                )
            if failure:
                entry.update(extract_failed=True, reason=failure)
            holes.append(entry)
        return {
            "backend": result["backend"],
            "ok": result["ok"],
            "header": header if len(header) <= MAX_HEADER else None,
            "holes": holes,
            "closed": closed,
            "reason_code": result["reason_code"],
        }

    async def elaborate_statement(
        self, header: str, name: str, signature: str, *, operation_id: str
    ) -> dict:
        if (
            not all(isinstance(value, str) for value in (header, name, signature))
            or not name.strip()
            or any(character.isspace() for character in name)
            or not signature.strip()
        ):
            raise HarnessError("INVALID_ARGUMENTS", "Supply a Lean header, name and signature.")
        source = f"{header}\n\ntheorem {name} {signature} := by\n  sorry\n"
        result = await self.check(source, automate=False, operation_id=operation_id)
        ok = result["ok"] and not any(m["severity"] == "error" for m in result["messages"])
        evidence = {
            "source_sha256": result["source_sha256"],
            "backend": result["backend"],
            "ok": ok,
            "messages": result["messages"],
        }
        canonical = json.dumps(evidence, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return {
            "ok": ok,
            "backend": result["backend"],
            "diagnostics_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "messages": result["messages"],
            "source_sha256": result["source_sha256"],
            "reason_code": result["reason_code"],
        }

    async def _check(self, source, automate, extract, operation_id, timeout):
        try:
            size = len(source.encode("utf-8"))
        except (AttributeError, UnicodeEncodeError) as exc:
            raise HarnessError(
                "INVALID_SOURCE",
                "Lean source must be valid Unicode text (no lone surrogate code points).",
                status=422,
            ) from exc
        if size > MAX_SOURCE_BYTES:
            raise HarnessError(
                "SOURCE_LIMIT",
                f"Lean source must be text of at most {MAX_SOURCE_BYTES} bytes (the workspace "
                "upload limit); split it, or run lake env lean on a workspace file.",
            )
        digest = hashlib.sha256(source.encode()).hexdigest()
        if await self._select_backend(operation_id) != "one_shot":
            payload = {
                "op": "check",
                "source": source,
                "automation": list(AUTOMATION) if automate else None,
                "extract_goals": extract,
                "axiom_names": top_level_names(source),
            }
            response = await self._request(payload, operation_id + ":lean-check", timeout)
            error = response.get("error")
            if not (isinstance(error, str) and error in _START_FAILURES):
                return self._repl_result(response, digest)
            # The binary exists but cannot run: behave as if it were absent from now on.
            self._backend = "one_shot"
            detail = response.get("detail")
            self._note = "Lean REPL could not start; using one-shot Lean. " + (
                _clip(detail, 500) if isinstance(detail, str) else ""
            )
        result = await self._one_shot(source, digest, operation_id)
        return result, [None] * len(result["holes"])

    async def _select_backend(self, operation_id):
        if self._backend is not None:
            return self._backend
        timeout = min(10, self._tools.policy.timeout_seconds)
        for index, candidate in enumerate(REPL_CANDIDATES):
            probe = await self._tools.run(
                {
                    "argv": ["sh", "-c", f"test -x {candidate} && echo yes || echo no"],
                    "cwd": ".",
                    "timeout_seconds": timeout,
                },
                f"{operation_id}:lean-probe-{index}",
            )
            if probe["exit_code"] == 0 and probe["stdout"].strip() == "yes":
                self._repl = candidate
                break
        if self._repl is None:
            self._backend = "one_shot"
        else:
            await self._upload_daemon(operation_id + ":lean-daemon")
            background = self._tools.allows_background_processes()
            self._backend = "repl" if background else "repl_inline"
        return self._backend

    async def _upload_daemon(self, operation_id):
        daemon = resources.files("physharness.formal_tools") / "lean_session_daemon.py"
        await self._tools.write(
            {"path": DAEMON_PATH, "content": daemon.read_text(encoding="utf-8")}, operation_id
        )

    def _timeouts(self, timeout):
        limit = float(self._tools.policy.timeout_seconds)
        margin = min(RUN_MARGIN_SECONDS, limit / 2)
        daemon_timeout = max(0.5, min(float(timeout), limit - margin))
        return daemon_timeout, min(limit, daemon_timeout + margin)

    async def _request(self, payload, operation_id, timeout):
        """Write the request file and pipe it to the daemon; argv cannot carry stdin."""
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(body.encode("utf-8")) > MAX_UPLOAD_BYTES:
            raise HarnessError(
                "SOURCE_LIMIT",
                f"The escaped Lean request exceeds the {MAX_UPLOAD_BYTES}-byte upload limit; "
                "split the source.",
            )
        # Unique per operation, so concurrent identical requests never share (and delete) a file.
        digest = hashlib.sha256(f"{operation_id}\n{body}".encode()).hexdigest()
        path = f".physharness/req-{digest}.json"
        daemon_timeout, run_timeout = self._timeouts(timeout)
        if self._backend == "repl":
            daemon, mode = DAEMON_RUNTIME_PATH, ["request", "--socket", SOCKET_PATH]
            place = (
                f"if test -f {DAEMON_PATH}; then mkdir -p {DAEMON_RUNTIME_DIR} && "
                f"mv -f {DAEMON_PATH} {DAEMON_RUNTIME_PATH}; fi; "
            )
        else:
            daemon, mode, place = DAEMON_PATH, ["inline"], ""
        argv = ["python3", daemon, *mode, "--timeout", f"{daemon_timeout:g}"]
        argv += ["--cwd", LAKE_PROJECT, "--repl", "lake", "env", self._repl]
        tidy = f"rm -f {path}; rmdir .physharness 2>/dev/null"
        script = (
            f"{place}if ! test -f {daemon}; then {tidy}; exit {_DAEMON_MISSING}; fi; "
            f"{shlex.join(argv)} < {path}; status=$?; {tidy}; exit $status"
        )
        for attempt in range(2):
            await self._tools.write({"path": path, "content": body}, f"{operation_id}:{attempt}")
            result = await self._tools.run(
                {"argv": ["sh", "-c", script], "cwd": ".", "timeout_seconds": run_timeout},
                f"{operation_id}:run-{attempt}",
            )
            if result["exit_code"] != _DAEMON_MISSING or attempt:
                break
            await self._upload_daemon(f"{operation_id}:daemon")  # removed or VM restored
        if result["exit_code"] == _DAEMON_MISSING:
            return {"error": "server_start_failed", "detail": "the daemon could not be placed"}
        try:
            response = json.loads(result["stdout"])
        except Exception:  # Includes RecursionError from deeply nested agent-controlled JSON.
            response = None
        if not isinstance(response, dict):
            detail = result.get("stderr") or result.get("stdout") or ""
            return {
                "error": "session_failed",
                "detail": f"exit status {result['exit_code']}: {detail[-1500:]}",
            }
        return response

    def _repl_result(self, response, digest):
        try:
            return self._interpret(response, digest)
        except Exception:  # A hostile or broken answer yields a bounded result, never a crash.
            text = "The Lean session returned a malformed answer."
            return self._failure(digest, "lean_session_failed", text), []

    def _failure(self, digest, reason_code, text):
        return {
            "backend": self._backend,
            "ok": False,
            "complete": False,
            "messages": [_message("error", None, None, text)],
            "holes": [],
            "axioms": {},
            "source_sha256": digest,
            "proof_status": "not_accepted",
            "automation_available": True,
            "reason_code": reason_code,
        }

    def _interpret(self, response, digest):
        error = response.get("error")
        if error is not None:
            code = error if isinstance(error, str) else ""
            reason_code, text = _ERRORS.get(code, ("lean_session_failed", None))
            detail = response.get("detail")
            if text is None or code == "repl_error":
                label = _clip(code, 40) or "malformed error"
                text = f"Lean session failure ({label})" + (
                    f": {detail}" if isinstance(detail, str) and detail else "."
                )
            return self._failure(digest, reason_code, text), []
        counts, messages, holes, extracted, axioms = _normalise_check(response)
        phase, stopped = response.get("phase_error"), response.get("automation_stopped")
        ok = not counts["errors"] and not any(m["severity"] == "error" for m in messages)
        reason_code = None
        if phase is not None:
            code = phase if isinstance(phase, str) else ""
            reason_code = _PHASES.get(code, "lean_session_failed")
        elif stopped is not None:
            reason_code = "lean_automation_budget_exhausted"
        result = {
            "backend": self._backend,
            "ok": ok,
            # A phase error (for example in the axiom report) never yields a complete result.
            "complete": ok
            and not holes
            and not counts["sorries"]
            and not counts["sorry_warnings"]
            and phase is None
            and not any("sorryAx" in values for values in axioms.values()),
            "messages": select_messages(messages, MAX_MESSAGES),
            "holes": holes,
            "axioms": axioms,
            "source_sha256": digest,
            "proof_status": "not_accepted",
            "automation_available": True,
            "reason_code": reason_code,
        }
        return result, extracted

    async def _one_shot(self, source, digest, operation_id):
        scratch = await self._tools.lean_scratch({"source": source}, operation_id + ":lean-one")
        diagnostics, path = scratch["diagnostics"], "/work/" + scratch["source_path"]
        messages = []
        for stream in ("stdout", "stderr"):
            messages += parse_lean_output(diagnostics.get(stream) or "", path)
        if diagnostics["exit_code"] != 0 and not any(m["severity"] == "error" for m in messages):
            text = f"Lean exited with status {diagnostics['exit_code']}."
            messages.append(_message("error", None, None, text))
        if self._note:
            messages.insert(0, _message("info", None, None, self._note))
            self._note = None
        holes = [
            {
                "index": index,
                "line": message["line"],
                "col": message["col"],
                "goal": None,
                "automation": _no_automation(),
            }
            for index, message in enumerate(
                m for m in messages if m["severity"] == "warning" and SORRY_WARNING.match(m["text"])
            )
        ][:MAX_HOLES]
        ok = not any(message["severity"] == "error" for message in messages)
        axioms, axioms_ok = {}, True
        names = top_level_names(source)
        printed = source + "\n" + "\n".join(f"#print axioms {name}" for name in names)
        if ok and not holes and names:
            # The axiom report is part of completeness: failing or skipping it is incomplete.
            axioms_ok = len(printed.encode("utf-8")) <= MAX_UPLOAD_BYTES
            if axioms_ok:
                report = await self._tools.lean_scratch(
                    {"source": printed}, operation_id + ":lean-one-axioms"
                )
                axioms = _appended_axioms(report, source, names)
                # No report from the appended lines (an #exit, say) is no axiom report.
                axioms_ok = report["diagnostics"].get("exit_code") == 0 and bool(axioms)
        return {
            "backend": "one_shot",
            "ok": ok,
            "complete": ok
            and not holes
            and axioms_ok
            and not any("sorryAx" in axiom_list for axiom_list in axioms.values()),
            "messages": [
                dict(m, text=_clip(m["text"], MAX_MESSAGE_TEXT))
                for m in select_messages(messages, MAX_MESSAGES)
            ],
            "holes": holes,
            "axioms": axioms,
            "source_sha256": digest,
            "proof_status": "not_accepted",
            "automation_available": False,
            "reason_code": "lean_repl_unavailable",
        }
