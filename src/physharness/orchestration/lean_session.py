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
MAX_SOURCE_BYTES = 1_000_000
MAX_MESSAGES = 50
MAX_MESSAGE_TEXT = 2000
MAX_HOLES = 32
MAX_GOAL = 4000
# The daemon answers this long before the provider's own timeout, which quarantines the VM.
RUN_MARGIN_SECONDS = 30
_DAEMON_MISSING = 97
_START_FAILURES = {"server_start_failed", "repl_start_failed"}
_REASONS = {"timeout": "lean_timeout", "repl_crashed": "lean_repl_crashed"}
_REASONS["repl_error"] = "lean_repl_error"
_HEADER = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?P<col>\d+): "
    r"(?P<severity>error|warning|info|information)(?:\([^)]*\))?: ?(?P<text>.*)$"
)
_EXTRACTED = re.compile(
    r"(?:\A|\n)\s*(?:Try this:\s*)?(?:\[apply\]\s*)?(?:theorem|lemma)\s+"
    r"(?P<name>[^\s(\[{:]+)(?P<signature>.*?):=\s*(?:by\s+)?sorry\s*\Z",
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


def signature_from_extracted(text: str) -> tuple[str, str] | None:
    """``theorem extracted_1 (x : ℝ) : P := sorry`` -> ``("extracted_1", "(x : ℝ) : P")``."""
    match = _EXTRACTED.search(text or "")
    if match is None:
        return None
    signature = " ".join(match["signature"].split())
    if ":" not in signature:
        return None
    return match["name"], signature


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


def _clip(value, limit):
    if not isinstance(value, str):
        return None
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _message(severity, line, col, text):
    return {"severity": severity, "line": line, "col": col, "text": _clip(text, MAX_MESSAGE_TEXT)}


def _no_automation():
    return {"closed_by": None, "suggestion": None, "tried": []}


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
            signature = signature_from_extracted(text) if text else None
            entry = {"index": hole["index"], "goal": hole["goal"]}
            if signature is None:
                entry["extract_failed"] = True
            else:
                entry.update(lean_name=f"hole_{hole['index']}", lean_statement=signature[1])
            holes.append(entry)
        return {
            "backend": result["backend"],
            "ok": result["ok"],
            "header": split_header(source)[0],
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
        if not isinstance(source, str) or len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise HarnessError("SOURCE_LIMIT", "Lean source must be text of at most one MiB.")
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
            if response.get("error") not in _START_FAILURES:
                return self._repl_result(response, digest)
            # The binary exists but cannot run: behave as if it were absent from now on.
            self._backend = "one_shot"
            self._note = "Lean REPL could not start; using one-shot Lean. " + str(
                response.get("detail", "")
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
        except (TypeError, ValueError):
            response = None
        if not isinstance(response, dict):
            detail = result.get("stderr") or result.get("stdout") or ""
            return {
                "error": "session_failed",
                "detail": f"exit status {result['exit_code']}: {detail[-1500:]}",
            }
        return response

    def _repl_result(self, response, digest):
        result = {
            "backend": self._backend,
            "ok": False,
            "complete": False,
            "messages": [],
            "holes": [],
            "axioms": {},
            "source_sha256": digest,
            "proof_status": "not_accepted",
            "automation_available": True,
            "reason_code": None,
        }
        error = response.get("error")
        if error:
            text = f"Lean session {error}: {response.get('detail', '')}".strip()
            if error == "timeout":
                text = "Lean did not finish before the time limit; the REPL was restarted."
            result["messages"] = [_message("error", None, None, text)]
            result["reason_code"] = _REASONS.get(error, "lean_session_failed")
            return result, []
        counts = response.get("counts") or {}
        raw = response.get("messages") or []
        result["messages"] = [
            _message(
                m.get("severity", "info"),
                (m.get("pos") or {}).get("line"),
                (m.get("pos") or {}).get("column"),
                str(m.get("data", "")),
            )
            for m in select_messages(raw, MAX_MESSAGES)
        ]
        sorries = (response.get("sorries") or [])[:MAX_HOLES]
        for index, sorry in enumerate(sorries):
            automation = sorry.get("automation") or {}
            result["holes"].append(
                {
                    "index": index,
                    "line": (sorry.get("pos") or {}).get("line"),
                    "col": (sorry.get("pos") or {}).get("column"),
                    "goal": _clip(sorry.get("goal"), MAX_GOAL),
                    "automation": {
                        "closed_by": automation.get("closed_by"),
                        "suggestion": _clip(automation.get("suggestion"), MAX_MESSAGE_TEXT),
                        "tried": list(automation.get("tried") or []),
                    },
                }
            )
        errors = counts.get("errors", 0) or any(m["severity"] == "error" for m in raw)
        result["ok"] = not errors
        result["axioms"] = response.get("axioms") or {}
        result["complete"] = (
            result["ok"]
            and not sorries
            and not counts.get("sorries")
            and not counts.get("sorry_warnings")
            and not any("sorryAx" in axioms for axioms in result["axioms"].values())
        )
        result["reason_code"] = _REASONS.get(response.get("phase_error"))
        if response.get("phase_error") and result["reason_code"] is None:
            result["reason_code"] = "lean_session_failed"
        return result, [sorry.get("extracted") for sorry in sorries]

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
        axioms = {}
        names = top_level_names(source)
        printed = source + "\n" + "\n".join(f"#print axioms {name}" for name in names)
        if ok and not holes and names and len(printed.encode("utf-8")) <= MAX_SOURCE_BYTES:
            report = await self._tools.lean_scratch(
                {"source": printed}, operation_id + ":lean-one-axioms"
            )
            output = report["diagnostics"]
            axioms = parse_axioms(
                (output.get("stdout") or "") + "\n" + (output.get("stderr") or "")
            )
        return {
            "backend": "one_shot",
            "ok": ok,
            "complete": ok
            and not holes
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
