"""Lean session: REPL daemon protocol, host backends, parsers and output bounds.

Daemon tests run the real daemon as a local subprocess against tests/fixtures/fake_lean_repl.py.
Host tests drive LeanSession through a FakeWorkspaceTools that executes argv locally.
"""

import hashlib
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from importlib import resources
from pathlib import Path
from types import SimpleNamespace

import pytest

from physharness.errors import HarnessError
from physharness.formal_tools import lean_session_daemon as daemon
from physharness.orchestration.lean_session import (
    AUTOMATION,
    DAEMON_PATH,
    MAX_SOURCE_BYTES,
    REPL_CANDIDATES,
    LeanSession,
    parse_extracted,
    parse_lean_output,
    signature_from_extracted,
    split_header,
    top_level_names,
)
from physharness.orchestration.workspace_tools import WorkspaceTools

FAKE_REPL = Path(__file__).parent / "fixtures" / "fake_lean_repl.py"
DAEMON_FILE = Path(daemon.__file__)
SOURCE = "import Mathlib\n\ntheorem t (x : Nat) : x = x := by\n  sorry\n"
THREE_HOLES = (
    "import Mathlib\n\n"
    "theorem a (x : Nat) : x = x := by\n  sorry\n\n"
    "theorem b (x : Nat) : x = x := by\n  sorry\n\n"
    "theorem c (x : Nat) : x = x := by\n  sorry\n"
)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _eventually(predicate, seconds=5.0):
    limit = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > limit:
            return False
        time.sleep(0.02)
    return True


def _fake_pids(state):
    path = state.logs / "pids.txt"
    return [int(line) for line in path.read_text().split()] if path.exists() else []


def _commands(state):
    path = state.logs / "commands.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _raw_request(path, request):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(20)
        conn.connect(path)
        conn.sendall(json.dumps(request).encode())
        conn.shutdown(socket.SHUT_WR)
        data = b""
        while chunk := conn.recv(65536):
            data += chunk
    return json.loads(data)


def _shutdown(path):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(5)
            conn.connect(path)
            conn.sendall(json.dumps({"op": "shutdown"}).encode())
            conn.shutdown(socket.SHUT_WR)
            conn.recv(4096)
    except OSError:
        pass


@pytest.fixture
def lean_env():
    """Short socket directory (macOS UNIX socket paths are ~104 bytes) and fake REPL wiring."""
    root = Path(tempfile.mkdtemp(prefix="ls", dir="/tmp"))
    shim, logs = root / "bin", root / "logs"
    shim.mkdir()
    logs.mkdir()
    python3 = shim / "python3"
    python3.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    python3.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{shim}{os.pathsep}{os.environ.get('PATH', '')}",
        "FAKE_LEAN_REPL_DIR": str(logs),
    }
    state = SimpleNamespace(
        root=root, socket=str(root / "s.sock"), logs=logs, env=env, runtime=root / "rt"
    )
    yield state
    _shutdown(state.socket)
    for pid in _fake_pids(state):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    shutil.rmtree(root, ignore_errors=True)


def run_daemon(state, mode, request, *, timeout=20.0):
    argv = [sys.executable, str(DAEMON_FILE), mode]
    if mode == "request":
        argv += ["--socket", state.socket]
    argv += ["--timeout", str(timeout), "--cwd", str(state.root)]
    argv += ["--repl", sys.executable, str(FAKE_REPL)]
    completed = subprocess.run(
        argv,
        input=json.dumps(request).encode(),
        capture_output=True,
        env=state.env,
        timeout=timeout + 30,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    return json.loads(completed.stdout)


class FakeWorkspaceTools:
    """Executes workspace argv locally under a temporary /work stand-in."""

    def __init__(self, state, *, repl_present=True, background=True, scratch=(), timeout=600):
        self.root = state.root / "work"
        self.root.mkdir(exist_ok=True)
        self.env, self.background = state.env, background
        self.policy = SimpleNamespace(timeout_seconds=timeout)
        self.scratch, self.calls = list(scratch), []
        self.canned = []  # stdout answers that replace real daemon runs (hostile VM tests)
        self.marker = state.root / "repl-binary"
        self.marker.write_text("")
        self.marker.chmod(0o755)
        fake = f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKE_REPL))}"
        self.substitutions = [
            (f"lake env {REPL_CANDIDATES[0]}", fake),
            (REPL_CANDIDATES[0], str(self.marker if repl_present else state.root / "missing")),
            ("/opt/sources/physlib", str(self.root)),
            ("/tmp/physharness-lean.sock", state.socket),
            ("/tmp/physharness", str(state.runtime)),
        ]

    def allows_background_processes(self):
        return self.background

    async def write(self, arguments, operation_id):
        self.calls.append(("write", arguments["path"], operation_id))
        target = self.root / arguments["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(arguments["content"], encoding="utf-8")
        return {"path": arguments["path"]}

    async def run(self, arguments, operation_id):
        argv = []
        for item in arguments["argv"]:
            for old, new in self.substitutions:
                item = item.replace(old, new)
            argv.append(item)
        assert arguments["cwd"] == "."
        assert 0 < arguments["timeout_seconds"] <= self.policy.timeout_seconds
        if self.canned and "lean_session.py" in argv[-1]:
            result = {
                "operation_id": operation_id,
                "execution_id": "local",
                "exit_code": 0,
                "stdout": self.canned.pop(0),
                "stderr": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
            }
            self.calls.append(("run", argv, operation_id, arguments["timeout_seconds"], result))
            return result
        completed = subprocess.run(
            argv,
            cwd=self.root,
            capture_output=True,
            env=self.env,
            timeout=arguments["timeout_seconds"],
        )
        result = {
            "operation_id": operation_id,
            "execution_id": "local",
            "exit_code": completed.returncode,
            "stdout": completed.stdout.decode(),
            "stderr": completed.stderr.decode(),
            "stdout_truncated": False,
            "stderr_truncated": False,
        }
        self.calls.append(("run", argv, operation_id, arguments["timeout_seconds"], result))
        return result

    async def lean_scratch(self, arguments, operation_id):
        source = arguments["source"]
        self.calls.append(("lean_scratch", source, operation_id))
        digest = hashlib.sha256(source.encode()).hexdigest()
        path = "scratch/" + digest + ".lean"
        stdout, exit_code, *stderr = self.scratch.pop(0)
        return {
            "source_path": path,
            "source_sha256": digest,
            "diagnostics": {
                "operation_id": operation_id + ":lean",
                "execution_id": "local",
                "exit_code": exit_code,
                "stdout": stdout.format(path="/work/" + path),
                "stderr": stderr[0].format(path="/work/" + path) if stderr else "",
                "stdout_truncated": False,
                "stderr_truncated": False,
            },
            "proof_status": "not_accepted",
        }

    def runs(self):
        return [call for call in self.calls if call[0] == "run"]


# Pure helpers


def test_parse_lean_output_multiline_and_severity():
    path = "/work/scratch/a.lean"
    text = (
        "error: unknown package 'Foo'\n"
        f"{path}:1:8: warning: declaration uses `sorry`\n"
        "'bar' does not depend on any axioms\n"
        f"{path}:10:23: error: unsolved goals\n"
        "⊢ False\n"
        "\n"
        "case right\n"
        "⊢ True\n"
        f"{path}:12:30: error(lean.unknownIdentifier): Unknown identifier `nope`\n"
        f"{path}:14:0: information: note\n"
    )
    assert parse_lean_output(text, path) == [
        {"severity": "error", "line": None, "col": None, "text": "error: unknown package 'Foo'"},
        {
            "severity": "warning",
            "line": 1,
            "col": 8,
            "text": "declaration uses `sorry`\n'bar' does not depend on any axioms",
        },
        {
            "severity": "error",
            "line": 10,
            "col": 23,
            "text": "unsolved goals\n⊢ False\n\ncase right\n⊢ True",
        },
        {"severity": "error", "line": 12, "col": 30, "text": "Unknown identifier `nope`"},
        {"severity": "info", "line": 14, "col": 0, "text": "note"},
    ]
    other = "other.lean:2:0: warning: unused\n"
    assert parse_lean_output(other, None)[0]["line"] == 2
    assert parse_lean_output(other, path) == [
        {"severity": "info", "line": None, "col": None, "text": "other.lean:2:0: warning: unused"}
    ]
    assert parse_lean_output("", path) == []


def test_split_header():
    source = (
        "/- Copyright\n  notice -/\n"
        "import Mathlib\n"
        "-- physics\n"
        "import Physlib\n\n"
        "open Real\n"
        "  Topology\n"
        "set_option maxHeartbeats 400000\n\n"
        "open Nat in\n"
        "theorem t : True := trivial\n"
    )
    header, body = split_header(source)
    assert header == (
        "/- Copyright\n  notice -/\nimport Mathlib\n-- physics\nimport Physlib\n\n"
        "open Real\n  Topology\nset_option maxHeartbeats 400000"
    )
    assert body == "\nopen Nat in\ntheorem t : True := trivial\n"
    assert header + "\n" + body == source
    assert split_header("theorem t : True := trivial") == ("", "theorem t : True := trivial")
    assert split_header("import Mathlib\n/-- doc -/\ntheorem t : True := trivial") == (
        "import Mathlib",
        "/-- doc -/\ntheorem t : True := trivial",
    )
    assert split_header("import Mathlib") == ("import Mathlib", "")
    # Headers that differ only by trailing blank lines share one cached import.
    assert split_header("import Mathlib\ntheorem x : True := trivial")[0] == "import Mathlib"


def test_signature_from_extracted():
    assert signature_from_extracted("theorem extracted_1 (x : ℝ) : P := sorry") == (
        "extracted_1",
        "(x : ℝ) : P",
    )
    assert signature_from_extracted(
        "theorem extracted_1 (x : ℕ)\n    (h : 0 < x) : x ≠ 0 :=\n  sorry"
    ) == ("extracted_1", "(x : ℕ) (h : 0 < x) : x ≠ 0")
    assert signature_from_extracted("theorem extracted_1 : 1 = 1 := sorry") == (
        "extracted_1",
        ": 1 = 1",
    )
    assert signature_from_extracted("theorem extracted_1 (x : ℕ) : x = x…") is None
    assert signature_from_extracted("no goals") is None
    assert signature_from_extracted("") is None


def test_daemon_is_packaged_bounded_and_matches_candidates():
    text = resources.files("physharness.formal_tools").joinpath("lean_session_daemon.py")
    data = text.read_bytes()
    assert data == DAEMON_FILE.read_bytes()
    assert len(data) < 32_768  # E2B's per-file workspace upload limit
    assert daemon.DEFAULT_REPL == ("lake", "env", REPL_CANDIDATES[0])
    assert DAEMON_PATH == ".physharness/lean_session.py"


def test_daemon_response_fits_stdout_cap():
    decoded = json.loads(daemon.fit({"op": "check", "messages": [{"data": "m" * 30000}]}))
    assert len(decoded["messages"][0]["data"]) == 20000
    assert decoded["truncated"] is True
    huge = {"op": "check", "messages": [{"data": "é" * 19000} for _ in range(50)]}
    assert len(daemon.fit(huge)) <= daemon.MAX_RESPONSE_BYTES
    small = {"op": "status", "generation": 1}
    assert json.loads(daemon.fit(small)) == small


# Daemon against the fake REPL


def test_daemon_caches_header_env(lean_env):
    first = run_daemon(lean_env, "request", {"op": "check", "source": SOURCE})
    second = run_daemon(
        lean_env, "request", {"op": "check", "source": SOURCE.replace("x = x", "x + 0 = x")}
    )
    assert first["header_cached"] is False and second["header_cached"] is True
    headers = [command for command in _commands(lean_env) if "env" not in command]
    assert headers == [{"cmd": "import Mathlib"}]
    assert first["sorries"][0]["pos"] == {"line": 4, "column": 2}
    assert first["counts"] == {"errors": 0, "messages": 1, "sorries": 1, "sorry_warnings": 1}
    status = run_daemon(lean_env, "request", {"op": "status"})
    assert status["headers_cached"] == 1 and status["running"] is True
    assert len(_fake_pids(lean_env)) == 1


def test_daemon_restarts_after_crash_and_expires_proof_states(lean_env):
    first = run_daemon(lean_env, "request", {"op": "check", "source": SOURCE})
    state, generation = first["sorries"][0]["proofState"], first["generation"]
    crashed = run_daemon(lean_env, "request", {"op": "check", "source": "import Mathlib\nCRASH"})
    assert crashed["error"] == "repl_crashed"
    tactic = {"op": "tactics", "proof_state": state, "generation": generation}
    tactic["tactics"] = ["linarith"]
    assert run_daemon(lean_env, "request", tactic) == {"error": "proof_state_expired"}
    again = run_daemon(lean_env, "request", {"op": "check", "source": SOURCE})
    assert again["generation"] > generation and again["header_cached"] is False
    # The new REPL reuses proofState numbers, but an old handle stays expired.
    assert again["sorries"][0]["proofState"] == state
    assert run_daemon(lean_env, "request", tactic) == {"error": "proof_state_expired"}
    fresh = run_daemon(lean_env, "request", {**tactic, "generation": again["generation"]})
    assert fresh["closed_by"] == "linarith" and fresh["tried"] == ["linarith"]
    old, new = _fake_pids(lean_env)
    assert not _alive(old) and _alive(new)


def test_daemon_timeout_kills_and_restarts(lean_env):
    run_daemon(lean_env, "request", {"op": "check", "source": SOURCE})
    started = time.monotonic()
    slow = run_daemon(
        lean_env, "request", {"op": "check", "source": "import Mathlib\nSLEEP"}, timeout=2
    )
    assert slow["error"] == "timeout"
    assert time.monotonic() - started < 15
    assert _eventually(lambda: not _alive(_fake_pids(lean_env)[0]))
    recovered = run_daemon(lean_env, "request", {"op": "check", "source": SOURCE})
    assert "error" not in recovered and recovered["header_cached"] is False
    assert recovered["generation"] == slow["generation"] + 1


def test_daemon_restarts_after_max_commands(lean_env, monkeypatch):
    monkeypatch.setenv("FAKE_LEAN_REPL_DIR", str(lean_env.logs))
    session = daemon.Session([sys.executable, str(FAKE_REPL)], str(lean_env.root), 3)
    try:
        deadline = time.monotonic() + 20
        first = session.handle({"op": "check", "source": SOURCE}, deadline)
        second = session.handle({"op": "check", "source": SOURCE}, deadline)
        third = session.handle({"op": "check", "source": SOURCE}, deadline)
    finally:
        session.reset()
    assert first["generation"] == second["generation"] == 1
    assert third["generation"] == 2 and third["header_cached"] is False
    assert not any(_alive(pid) for pid in _fake_pids(lean_env))


def test_daemon_compound_check_automates_and_extracts_inline(lean_env):
    source = THREE_HOLES.replace(
        "theorem c (x : Nat) : x = x := by\n  sorry",
        "theorem c : 1 = 1 := by\n  sorry -- goal: NOEXTRACT",
    )
    request = {
        "op": "check",
        "source": source,
        "automation": list(AUTOMATION),
        "extract_goals": True,
        "axiom_names": ["a", "b", "c"],
    }
    result = run_daemon(lean_env, "inline", request)
    first, second, third = result["sorries"]
    statement = "theorem extracted_1 (x : Nat) : x = x := sorry"
    # Extraction runs for every hole before automation, so it survives slow automation.
    assert first["extracted"] == second["extracted"] == statement
    assert first["automation"]["closed_by"] == "linarith"
    assert second["automation"]["suggestion"] == "exact fake_lemma"
    assert third["automation"]["closed_by"] is None
    assert third["automation"]["tried"] == list(AUTOMATION)
    assert third["extracted"] is None
    assert result["axioms"] is None  # holes remain, so no axiom report
    sent = [c["tactic"] for c in _commands(lean_env) if c.get("proofState") == 0]
    assert sent[0] == "extract_goal"
    assert sent[1] == f"set_option maxHeartbeats {daemon.TACTIC_HEARTBEATS} in rfl"
    assert "exact?" in [c["tactic"] for c in _commands(lean_env) if c.get("proofState") == 1]
    (pid,) = _fake_pids(lean_env)
    assert not _alive(pid)
    assert not Path(lean_env.socket).exists()


# Host LeanSession


async def test_check_repl_backend_holes_and_automation(lean_env):
    tools = FakeWorkspaceTools(lean_env)
    session = LeanSession(tools)
    result = await session.check(THREE_HOLES, automate=True, operation_id="op")
    assert result["backend"] == "repl"
    assert result["ok"] is True and result["complete"] is False
    assert result["automation_available"] is True and result["reason_code"] is None
    assert result["proof_status"] == "not_accepted" and result["axioms"] == {}
    assert result["source_sha256"] == hashlib.sha256(THREE_HOLES.encode()).hexdigest()
    first, second, third = result["holes"]
    assert first == {
        "index": 0,
        "line": 4,
        "col": 2,
        "goal": "x : Nat\n⊢ x = x",
        "automation": {
            "closed_by": "linarith",
            "suggestion": None,
            "tried": ["rfl", "norm_num", "simp", "simp_all", "linarith"],
        },
    }
    assert second["automation"] == {
        "closed_by": "exact?",
        "suggestion": "exact fake_lemma",
        "tried": list(AUTOMATION),
    }
    assert third["automation"] == {"closed_by": None, "suggestion": None, "tried": list(AUTOMATION)}
    assert result["messages"] == [
        # The fake reports it at body line 1, which is source line 2 after the header.
        {"severity": "warning", "line": 2, "col": 0, "text": "declaration uses `sorry`"}
    ]
    writes = [call for call in tools.calls if call[0] == "write"]
    assert writes[0][1] == DAEMON_PATH
    # The daemon runs from /tmp, outside the checkpointed workspace.
    assert (lean_env.runtime / "lean_session.py").read_bytes() == DAEMON_FILE.read_bytes()
    probe, request = tools.runs()
    assert probe[1] == ["sh", "-c", f"test -x {tools.marker} && echo yes || echo no"]
    runtime = lean_env.runtime / "lean_session.py"
    expected = f"python3 {runtime} request --socket {lean_env.socket} --timeout 120 "
    assert expected in request[1][2]
    assert request[3] <= tools.policy.timeout_seconds
    assert not (tools.root / ".physharness").exists()  # neither daemon nor request file
    await session.check(SOURCE, automate=False, operation_id="op2")
    assert [call[1] for call in tools.calls if call[0] == "write"].count(DAEMON_PATH) == 1
    assert len(tools.runs()) == 3  # the probe is cached; one round trip per check
    identifiers = [call[2] for call in tools.calls]
    assert len(set(identifiers)) == len(identifiers)


async def test_check_repl_inline_when_background_disallowed(lean_env):
    tools = FakeWorkspaceTools(lean_env, background=False)
    result = await LeanSession(tools).check(THREE_HOLES, automate=True, operation_id="op")
    assert result["backend"] == "repl_inline" and result["automation_available"] is True
    assert result["holes"][0]["automation"]["closed_by"] == "linarith"
    assert f"python3 {DAEMON_PATH} inline --timeout " in tools.runs()[-1][1][2]
    # Without background processes the daemon stays in /work (local_docker has no writable /tmp).
    assert (tools.root / DAEMON_PATH).read_bytes() == DAEMON_FILE.read_bytes()
    assert not lean_env.runtime.exists()
    assert [path.name for path in (tools.root / ".physharness").iterdir()] == ["lean_session.py"]
    pids = _fake_pids(lean_env)
    assert pids and not any(_alive(pid) for pid in pids)
    assert not Path(lean_env.socket).exists()


async def test_check_respects_policy_timeout(lean_env):
    tools = FakeWorkspaceTools(lean_env, timeout=40)
    result = await LeanSession(tools).check(SOURCE, automate=False, operation_id="op")
    assert result["backend"] == "repl"
    request = tools.runs()[-1]
    assert request[3] == 40 and "--timeout 20 " in request[1][2]


async def test_check_one_shot_fallback_when_repl_missing(lean_env):
    scratch = [
        (
            "{path}:3:8: warning: declaration uses 'sorry'\n"
            "{path}:6:2: error: unsolved goals\nx : Nat\n⊢ x = x\n",
            1,
        )
    ]
    tools = FakeWorkspaceTools(lean_env, repl_present=False, scratch=scratch)
    result = await LeanSession(tools).check(SOURCE, automate=True, operation_id="op")
    assert result["backend"] == "one_shot"
    assert result["ok"] is False and result["complete"] is False
    assert result["automation_available"] is False
    assert result["reason_code"] == "lean_repl_unavailable"
    assert result["holes"] == [
        {
            "index": 0,
            "line": 3,
            "col": 8,
            "goal": None,
            "automation": {"closed_by": None, "suggestion": None, "tried": []},
        }
    ]
    assert result["messages"][1] == {
        "severity": "error",
        "line": 6,
        "col": 2,
        "text": "unsolved goals\nx : Nat\n⊢ x = x",
    }
    assert result["axioms"] == {} and result["proof_status"] == "not_accepted"
    assert not [call for call in tools.calls if call[0] == "write"]
    tools.scratch.append(("{path}:3:8: warning: declaration uses 'sorry'\n", 0))
    sketch = await LeanSession(tools).sketch_goals(SOURCE, operation_id="op2")
    assert sketch["backend"] == "one_shot" and sketch["header"] == "import Mathlib"
    assert sketch["holes"] == [
        {"index": 0, "goal": None, "extract_failed": True, "reason": "goal_unavailable"}
    ]
    assert sketch["reason_code"] == "lean_repl_unavailable"


async def test_sketch_goals_extracts_signatures(lean_env):
    source = (
        "import Mathlib\n\ntheorem main (x : Nat) : x = x := by\n"
        "  have h0 : x = x := by\n    sorry\n"
        "  have h1 : x = x := by\n    sorry\n"
        "  have h2 : x = x := by\n    sorry\n"
        "  have h3 : x = x := by\n    sorry -- goal: NOEXTRACT\n"
        "  sorry -- goal: UNIVERSE\n"
    )
    tools = FakeWorkspaceTools(lean_env)
    result = await LeanSession(tools).sketch_goals(source, operation_id="op")
    assert result == {
        "backend": "repl",
        "ok": True,
        "header": "import Mathlib",
        "reason_code": None,
        "holes": [
            {
                "index": 2,
                "goal": "x : Nat\n⊢ x = x",
                "lean_name": "hole_2",
                "lean_statement": "(x : Nat) : x = x",
                "universes": [],
            },
            {
                "index": 3,
                "goal": "⊢ NOEXTRACT",
                "extract_failed": True,
                "reason": "extract_goal_failed",
            },
            {
                "index": 4,
                "goal": "⊢ UNIVERSE",
                "lean_name": "hole_4",
                "lean_statement": "{α : Type u_1} (a : α) : a = a",
                "universes": ["u_1"],
            },
        ],
        "closed": [
            {"index": 0, "closed_by": "linarith", "suggestion": None},
            {"index": 1, "closed_by": "exact?", "suggestion": "exact fake_lemma"},
        ],
    }
    extracted = [c["proofState"] for c in _commands(lean_env) if c.get("tactic") == "extract_goal"]
    assert extracted == [0, 1, 2, 3, 4]
    assert len(tools.runs()) == 2  # probe + one compound request


async def test_elaborate_statement_ok_and_error(lean_env):
    session = LeanSession(FakeWorkspaceTools(lean_env))
    good = await session.elaborate_statement(
        "import Mathlib", "foo", "(x : Nat) : x = x", operation_id="good"
    )
    bad = await session.elaborate_statement(
        "import Mathlib", "foo", "(x : Nat) : ERROR", operation_id="bad"
    )
    assert good["ok"] is True and good["backend"] == "repl" and good["reason_code"] is None
    assert len(good["diagnostics_sha256"]) == 64
    assert bad["ok"] is False and bad["diagnostics_sha256"] != good["diagnostics_sha256"]
    assert any(message["severity"] == "error" for message in bad["messages"])
    bodies = [c["cmd"] for c in _commands(lean_env) if "env" in c and "cmd" in c]
    assert bodies[0] == "\ntheorem foo (x : Nat) : x = x := by\n  sorry\n"


AXIOM_SOURCE = """import Mathlib

theorem top : 1 = 1 := by
  rfl

namespace Inner
theorem hidden : 2 = 2 := rfl
end Inner

/-- A docstring mentioning theorem ghost. -/
@[simp] lemma also_top : True := trivial
"""


async def test_axioms_printed_for_top_level_names_only(lean_env):
    assert top_level_names(AXIOM_SOURCE) == ["top", "also_top"]
    tools = FakeWorkspaceTools(lean_env)
    result = await LeanSession(tools).check(AXIOM_SOURCE, automate=True, operation_id="op")
    standard = ["propext", "Classical.choice", "Quot.sound"]
    assert result["ok"] is True and result["complete"] is True
    assert result["axioms"] == {"top": standard, "also_top": standard}
    printed = _commands(lean_env)[-1]
    assert printed["cmd"] == "#print axioms top\n#print axioms also_top"
    # Lean reports each #print axioms at its own line: the appended lines 13 and 14.
    scratch = [
        ("", 0),
        (
            "{path}:13:0: info: 'top' depends on axioms: [propext]\n"
            "{path}:14:0: info: 'also_top' does not depend on any axioms\n",
            0,
        ),
    ]
    tools = FakeWorkspaceTools(lean_env, repl_present=False, scratch=scratch)
    result = await LeanSession(tools).check(AXIOM_SOURCE, automate=True, operation_id="op")
    assert result["backend"] == "one_shot" and result["complete"] is True
    assert result["axioms"] == {"top": ["propext"], "also_top": []}
    second = [call[1] for call in tools.calls if call[0] == "lean_scratch"][1]
    assert second == AXIOM_SOURCE + "\n#print axioms top\n#print axioms also_top"
    sorry_axiom = [("", 0), ("{path}:13:0: info: 'top' depends on axioms: [sorryAx]\n", 0)]
    tools = FakeWorkspaceTools(lean_env, repl_present=False, scratch=sorry_axiom)
    result = await LeanSession(tools).check(AXIOM_SOURCE, automate=True, operation_id="op")
    assert result["ok"] is True and result["complete"] is False


async def test_one_shot_axioms_come_only_from_the_appended_lines(lean_env):
    """An agent's #eval output cannot stand in for the platform's #print axioms report."""
    forged = "'top' does not depend on any axioms\n'also_top' does not depend on any axioms"
    cases = {
        # #exit (or anything else) suppressed the real report; #eval printed a forgery.
        "eval_only": ("{path}:3:0: info: " + forged + "\n", "", {}),
        # A forgery at an appended position, but in another file's diagnostics.
        "other_path": ("/work/scratch/other.lean:13:0: info: " + forged + "\n", "", {}),
        # The real report is present, and a forgery follows it on stderr (IO.eprintln).
        "stderr": (
            "{path}:13:0: info: 'top' depends on axioms: [cheat]\n",
            forged,
            {"top": ["cheat"]},
        ),
        # Each appended line reports only the name printed there, and only in its opening.
        "wrong_line": ("{path}:14:0: info: " + forged + "\n", "", {}),
        "trailing_text": (
            "{path}:13:0: info: 'top' depends on axioms: [cheat]\n"
            "'top' does not depend on any axioms\n",
            "",
            {"top": ["cheat"]},
        ),
    }
    for label, (stdout, stderr, expected) in cases.items():
        tools = FakeWorkspaceTools(
            lean_env, repl_present=False, scratch=[("", 0), (stdout, 0, stderr)]
        )
        result = await LeanSession(tools).check(AXIOM_SOURCE, automate=True, operation_id="op")
        assert result["ok"] is True, label
        assert result["axioms"] == expected, label
        # No axiom message from the appended lines is no report: never complete.
        assert result["complete"] is bool(expected), label


async def test_outputs_bounded(lean_env):
    lines = ["import Mathlib", ""]
    for index in range(40):
        lines += [f"theorem t{index} (x : Nat) : x = x := by", "  sorry -- goal: LONG"]
    lines += ["-- WARN LONG" for _ in range(60)]  # the fake expands LONG to 3000-5000 chars
    source = "\n".join(lines)
    tools = FakeWorkspaceTools(lean_env)
    result = await LeanSession(tools).check(source, automate=True, operation_id="op")
    assert result["ok"] is True and result["complete"] is False
    assert 0 < len(result["messages"]) <= 50
    assert all(len(message["text"]) <= 2000 for message in result["messages"])
    assert len(result["holes"]) == 32
    assert all(len(hole["goal"]) <= 4000 for hole in result["holes"])
    assert len(tools.runs()[-1][4]["stdout"].encode()) <= daemon.MAX_RESPONSE_BYTES


async def test_workspace_tools_delegate_to_lean_session():
    tools = WorkspaceTools.__new__(WorkspaceTools)
    tools.broker = SimpleNamespace(provider_spec={"provider": "local_docker"})
    tools._lean_session = None
    assert tools.allows_background_processes() is False
    tools.broker = SimpleNamespace(provider_spec={"provider": "e2b"})
    assert tools.allows_background_processes() is True
    calls = []

    class StubSession:
        async def check(self, source, *, automate, operation_id):
            calls.append(("check", source, automate, operation_id))
            return {"backend": "repl"}

        async def sketch_goals(self, source, *, operation_id):
            calls.append(("sketch", source, operation_id))
            return {"holes": []}

    tools._lean_session = StubSession()
    assert await tools.lean_check({"source": "s"}, "op1") == {"backend": "repl"}
    await tools.lean_check({"source": "s", "automate": False}, "op2")
    assert await tools.lean_sketch_goals({"source": "t"}, "op3") == {"holes": []}
    assert calls == [
        ("check", "s", True, "op1"),
        ("check", "s", False, "op2"),
        ("sketch", "t", "op3"),
    ]


@pytest.mark.lean
def test_real_repl_inline_check_and_automation(tmp_path):
    """Run with PHYSHARNESS_LEAN_REPL_CMD (e.g. 'lake env /opt/lean-repl/.lake/build/bin/repl')
    and PHYSHARNESS_LEAN_REPL_CWD (a Lake project such as /opt/sources/physlib)."""
    command = os.environ.get("PHYSHARNESS_LEAN_REPL_CMD")
    cwd = os.environ.get("PHYSHARNESS_LEAN_REPL_CWD")
    if not command or not cwd:
        pytest.skip("set PHYSHARNESS_LEAN_REPL_CMD and PHYSHARNESS_LEAN_REPL_CWD")

    def inline(request):
        argv = [sys.executable, str(DAEMON_FILE), "inline", "--timeout", "300", "--cwd", cwd]
        completed = subprocess.run(
            [*argv, "--repl", *shlex.split(command)],
            input=json.dumps(request).encode(),
            capture_output=True,
            timeout=400,
        )
        assert completed.returncode == 0, completed.stderr.decode()
        return json.loads(completed.stdout)

    holes = inline(
        {
            "op": "check",
            "source": "theorem t (x : Nat) : x + 0 = x := by\n  sorry\n",
            "automation": list(AUTOMATION),
            "extract_goals": False,
        }
    )
    assert holes["counts"]["errors"] == 0
    assert holes["sorries"][0]["goal"].endswith("⊢ x + 0 = x")
    assert holes["sorries"][0]["automation"]["closed_by"] is not None
    complete = inline(
        {"op": "check", "source": "theorem u : 2 + 2 = 4 := by\n  decide\n", "axiom_names": ["u"]}
    )
    assert complete["counts"] == {"errors": 0, "messages": 0, "sorries": 0, "sorry_warnings": 0}
    assert isinstance(complete["axioms"]["u"], list)


def test_daemon_check_without_header_uses_fresh_environment(lean_env):
    source = "theorem u : 1 = 1 := by\n  sorry\n"
    result = run_daemon(lean_env, "inline", {"op": "check", "source": source})
    assert result["header_cached"] is False
    assert result["sorries"][0]["pos"] == {"line": 2, "column": 2}
    assert _commands(lean_env) == [{"cmd": source}]


async def test_request_reuploads_a_removed_daemon(lean_env):
    tools = FakeWorkspaceTools(lean_env, background=False)
    session = LeanSession(tools)
    await session.check(SOURCE, automate=False, operation_id="first")
    (tools.root / DAEMON_PATH).unlink()
    result = await session.check(SOURCE, automate=False, operation_id="second")
    assert result["backend"] == "repl_inline" and result["ok"] is True
    uploads = [call[2] for call in tools.calls if call[0] == "write" and call[1] == DAEMON_PATH]
    assert uploads == ["first:lean-daemon", "second:lean-check:daemon"]


async def test_repl_start_failure_falls_back_to_one_shot(lean_env):
    scratch = [
        ("{path}:3:8: warning: declaration uses 'sorry'\n", 0),
        ("", 0),
        ("{path}:3:0: info: 't' does not depend on any axioms\n", 0),
    ]
    tools = FakeWorkspaceTools(lean_env, background=False, scratch=scratch)
    tools.substitutions[0] = (f"lake env {REPL_CANDIDATES[0]}", str(lean_env.root / "no-repl"))
    session = LeanSession(tools)
    result = await session.check(SOURCE, automate=True, operation_id="op")
    assert result["backend"] == "one_shot" and result["reason_code"] == "lean_repl_unavailable"
    assert result["messages"][0]["severity"] == "info"
    assert result["messages"][0]["text"].startswith("Lean REPL could not start")
    assert len(result["holes"]) == 1
    again = await session.check("theorem t : True := trivial\n", automate=True, operation_id="b")
    assert again["backend"] == "one_shot" and again["messages"] == []
    assert again["complete"] is True and again["axioms"] == {"t": []}


async def test_repl_daemon_reuploaded_when_tmp_copy_missing(lean_env):
    tools = FakeWorkspaceTools(lean_env)
    session = LeanSession(tools)
    await session.check(SOURCE, automate=False, operation_id="first")
    runtime = lean_env.runtime / "lean_session.py"
    assert runtime.exists() and not (tools.root / ".physharness").exists()
    _shutdown(lean_env.socket)  # A VM restore drops /tmp: both the daemon file and the server.
    runtime.unlink()
    result = await session.check(SOURCE, automate=False, operation_id="second")
    assert result["backend"] == "repl" and result["ok"] is True
    uploads = [call[2] for call in tools.calls if call[0] == "write" and call[1] == DAEMON_PATH]
    assert uploads == ["first:lean-daemon", "second:lean-check:daemon"]
    assert runtime.read_bytes() == DAEMON_FILE.read_bytes()
    assert not (tools.root / ".physharness").exists()


async def test_daemon_placement_failure_falls_back_to_one_shot(lean_env):
    blocker = lean_env.root / "not-a-directory"
    blocker.write_text("")
    lean_env.runtime = blocker / "rt"  # mkdir -p under a regular file fails
    scratch = [("", 0), ("{path}:6:0: info: 't' does not depend on any axioms\n", 0)]
    tools = FakeWorkspaceTools(lean_env, scratch=scratch)
    result = await LeanSession(tools).check(SOURCE, automate=True, operation_id="op")
    assert result["backend"] == "one_shot" and result["reason_code"] == "lean_repl_unavailable"
    assert result["messages"][0]["text"].startswith("Lean REPL could not start")
    assert "the daemon could not be placed" in result["messages"][0]["text"]


# Fix round 1: hostile answers, automation budget, upload limit, completeness, universes, caps

GOOD = {
    "op": "check",
    "counts": {"errors": 0, "messages": 0, "sorries": 0, "sorry_warnings": 0},
    "messages": [],
    "sorries": [],
    "axioms": None,
}


def _assert_bounded_check(result):
    assert result["backend"] in ("repl", "repl_inline", "one_shot")
    assert type(result["ok"]) is bool and type(result["complete"]) is bool
    assert result["proof_status"] == "not_accepted"
    assert result["reason_code"] is None or isinstance(result["reason_code"], str)
    assert isinstance(result["messages"], list) and len(result["messages"]) <= 50
    for message in result["messages"]:
        assert set(message) == {"severity", "line", "col", "text"}
        assert message["severity"] in ("error", "warning", "info")
        for value in (message["line"], message["col"]):
            assert value is None or (type(value) is int and value >= 0)
        assert isinstance(message["text"], str) and len(message["text"]) <= 2000
    assert len(result["holes"]) <= 32
    for hole in result["holes"]:
        assert type(hole["index"]) is int
        assert hole["goal"] is None or (isinstance(hole["goal"], str) and len(hole["goal"]) <= 4000)
        automation = hole["automation"]
        assert automation["closed_by"] is None or automation["closed_by"] in AUTOMATION
        assert automation["suggestion"] is None or isinstance(automation["suggestion"], str)
        assert len(automation["tried"]) <= 10
        assert all(tactic in AUTOMATION for tactic in automation["tried"])
    assert isinstance(result["axioms"], dict) and len(result["axioms"]) <= 32
    for name, values in result["axioms"].items():
        assert isinstance(name, str) and len(name) <= 200 and len(values) <= 32
        assert all(isinstance(value, str) and len(value) <= 200 for value in values)


MALFORMED = [
    "not json at all",
    "[" * 10000,  # RecursionError inside json.loads
    "[1, 2]",
    json.dumps({"error": ["x"]}),
    json.dumps({"error": {"nested": 1}, "detail": 5}),
    json.dumps({"phase_error": {}}),
    json.dumps({**GOOD, "op": "tactics"}),
    json.dumps({**GOOD, "counts": 5}),
    json.dumps({**GOOD, "messages": "abc"}),
    json.dumps({**GOOD, "sorries": {"a": 1}}),
    json.dumps({**GOOD, "axioms": [1]}),
]


@pytest.mark.parametrize("stdout", MALFORMED, ids=lambda stdout: stdout[:40])
async def test_hostile_daemon_answers_become_bounded_failures(lean_env, stdout):
    tools = FakeWorkspaceTools(lean_env)
    tools.canned = [stdout] * 3
    session = LeanSession(tools)
    result = await session.check(SOURCE, automate=True, operation_id="a")
    _assert_bounded_check(result)
    assert result["ok"] is False and result["complete"] is False
    assert result["reason_code"] == "lean_session_failed"
    sketch = await session.sketch_goals(SOURCE, operation_id="b")
    assert sketch["holes"] == [] and sketch["reason_code"] == "lean_session_failed"
    elaboration = await session.elaborate_statement(
        "import Mathlib", "t", ": True", operation_id="c"
    )
    assert elaboration["ok"] is False and elaboration["reason_code"] == "lean_session_failed"


async def test_hostile_daemon_fields_are_retyped(lean_env):
    payload = {
        **GOOD,
        "counts": {"errors": -3, "messages": "x", "sorries": 2, "sorry_warnings": None},
        "messages": [
            {"data": "no severity"},
            {"severity": ["x"], "pos": {"line": "1", "column": -2}, "data": 7},
            7,
            {"severity": "error", "pos": {"line": 3, "column": 1}, "data": "e" * 5000},
        ],
        "sorries": [
            {
                "automation": {"tried": 5, "closed_by": "rm -rf", "suggestion": 3},
                "extracted": 7,
                "goal": 3,
                "pos": "x",
            },
            {
                "automation": {"tried": ["simp", "evil", "linarith"], "closed_by": "simp"},
                "goal": "⊢ True",
                "extracted": "theorem x : True := sorry",
            },
        ],
        "axioms": {"a": [1, "propext", "x" * 300], "b" * 300: ["c"], "c": "not a list"},
        "phase_error": {},
    }
    tools = FakeWorkspaceTools(lean_env)
    tools.canned = [json.dumps(payload)] * 2
    session = LeanSession(tools)
    result = await session.check(SOURCE, automate=True, operation_id="a")
    _assert_bounded_check(result)
    assert [m["severity"] for m in result["messages"]] == ["info", "info", "error"]
    assert result["messages"][1] == {"severity": "info", "line": None, "col": None, "text": ""}
    assert result["messages"][2]["line"] == 3 and len(result["messages"][2]["text"]) == 2000
    assert result["ok"] is False and result["complete"] is False
    assert result["reason_code"] == "lean_session_failed"
    assert result["holes"][0] == {
        "index": 0,
        "line": None,
        "col": None,
        "goal": None,
        "automation": {"closed_by": None, "suggestion": None, "tried": []},
    }
    assert result["holes"][1]["automation"] == {
        "closed_by": "simp",
        "suggestion": None,
        "tried": ["simp", "linarith"],
    }
    assert result["axioms"] == {"a": ["propext"]}
    sketch = await session.sketch_goals(SOURCE, operation_id="b")
    assert sketch["holes"] == [
        {"index": 0, "goal": None, "extract_failed": True, "reason": "extract_goal_failed"}
    ]
    assert sketch["closed"] == [{"index": 1, "closed_by": "simp", "suggestion": None}]


def test_daemon_automation_budget_keeps_repl_and_extraction(lean_env):
    warm = run_daemon(lean_env, "request", {"op": "check", "source": SOURCE})
    request = {"op": "check", "source": SOURCE, "automation": ["slow"] * 16}
    request["extract_goals"] = True
    result = run_daemon(lean_env, "request", request, timeout=5)
    assert "error" not in result and "phase_error" not in result
    assert result["automation_stopped"] == "budget_exhausted"
    hole = result["sorries"][0]
    assert hole["extracted"] == "theorem extracted_1 (x : Nat) : x = x := sorry"
    tried = hole["automation"]["tried"]
    assert 0 < len(tried) < 16
    sent = [c for c in _commands(lean_env) if c.get("tactic", "").endswith(" in slow")]
    assert len(sent) == len(tried)  # only tactics actually sent are recorded
    assert result["generation"] == warm["generation"]
    (pid,) = _fake_pids(lean_env)
    assert _alive(pid)  # the idle, in-sync REPL was not reset
    again = run_daemon(lean_env, "request", {"op": "check", "source": SOURCE})
    assert again["header_cached"] is True and again["generation"] == warm["generation"]


def test_daemon_expired_request_fails_fast_without_reset(lean_env):
    warm = run_daemon(lean_env, "request", {"op": "check", "source": SOURCE})
    stale = {"op": "check", "source": SOURCE, "deadline": time.time() - 5}
    assert _raw_request(lean_env.socket, stale)["error"] == "budget_exhausted"
    status = run_daemon(lean_env, "request", {"op": "status"})
    assert status["running"] is True and status["generation"] == warm["generation"]
    assert status["headers_cached"] == 1 and len(_fake_pids(lean_env)) == 1


async def test_budget_stop_is_reported_on_the_host(lean_env):
    payload = {
        **GOOD,
        "counts": {"errors": 0, "messages": 0, "sorries": 1, "sorry_warnings": 0},
        "sorries": [{"goal": "⊢ True", "automation": {"tried": ["rfl"]}}],
        "automation_stopped": "budget_exhausted",
    }
    tools = FakeWorkspaceTools(lean_env)
    tools.canned = [json.dumps(payload)]
    result = await LeanSession(tools).check(SOURCE, automate=True, operation_id="a")
    assert result["ok"] is True and result["reason_code"] == "lean_automation_budget_exhausted"
    assert result["holes"][0]["automation"]["tried"] == ["rfl"]


async def test_source_limit_matches_upload_limit(lean_env):
    tools = FakeWorkspaceTools(lean_env)
    session = LeanSession(tools)
    with pytest.raises(HarnessError) as error:
        await session.check("-- " + "x" * MAX_SOURCE_BYTES, automate=True, operation_id="big")
    assert error.value.code == "SOURCE_LIMIT" and tools.calls == []
    # JSON escaping can push an in-limit source past the 32,768-byte upload limit.
    with pytest.raises(HarnessError) as error:
        await session.check("-- " + '"' * 20000, automate=True, operation_id="quoted")
    assert error.value.code == "SOURCE_LIMIT"
    assert [call[1] for call in tools.calls if call[0] == "write"] == [DAEMON_PATH]
    one_shot = FakeWorkspaceTools(lean_env, repl_present=False)
    with pytest.raises(HarnessError) as error:
        await LeanSession(one_shot).check(
            "x" * (MAX_SOURCE_BYTES + 1), automate=False, operation_id="one"
        )
    assert error.value.code == "SOURCE_LIMIT" and one_shot.calls == []


async def test_axiom_phase_error_is_never_complete(lean_env):
    tools = FakeWorkspaceTools(lean_env)
    tools.canned = [json.dumps({**GOOD, "phase_error": "timeout"})]
    result = await LeanSession(tools).check(AXIOM_SOURCE, automate=True, operation_id="a")
    assert result["ok"] is True and result["complete"] is False
    assert result["reason_code"] == "lean_timeout" and result["axioms"] == {}
    scratch = [("", 0), ("'top' depends on axioms: [propext]\n", 1)]
    tools = FakeWorkspaceTools(lean_env, repl_present=False, scratch=scratch)
    result = await LeanSession(tools).check(AXIOM_SOURCE, automate=True, operation_id="b")
    assert result["ok"] is True and result["complete"] is False


def test_parse_extracted_universe_parameters():
    text = (
        "theorem extracted_1.{u_1, u_2} {α : Type u_1} {β : Type u_2} (f : α → β) :\n"
        "    f = f := sorry"
    )
    signature = "{α : Type u_1} {β : Type u_2} (f : α → β) : f = f"
    assert parse_extracted(text) == ("extracted_1", signature, ["u_1", "u_2"])
    assert signature_from_extracted(text) == ("extracted_1", signature)
    assert parse_extracted("theorem Foo.bar (x : Nat) : x = x := sorry") == (
        "Foo.bar",
        "(x : Nat) : x = x",
        [],
    )


async def test_sketch_caps_header_and_statement(lean_env):
    source = (
        "import Mathlib\n-- " + "c" * 2100 + "\nimport Physlib\n" + THREE_HOLES.split("\n", 1)[1]
    )
    sketch = await LeanSession(FakeWorkspaceTools(lean_env)).sketch_goals(source, operation_id="a")
    assert sketch["header"] is None
    assert sketch["holes"] == [
        {
            "index": 2,
            "goal": "x : Nat\n⊢ x = x",
            "extract_failed": True,
            "reason": "header_too_long",
        }
    ]
    long_statement = "theorem extracted_1 (x : Nat) : " + "x = x ∧ " * 3000 + "True := sorry"
    payload = {
        **GOOD,
        "counts": {"errors": 0, "messages": 0, "sorries": 2, "sorry_warnings": 0},
        "sorries": [
            {"goal": "⊢ a", "extracted": long_statement},
            {"goal": "⊢ b", "extracted": "theorem extracted_1 (x : Nat) : x = x…"},
        ],
    }
    tools = FakeWorkspaceTools(lean_env)
    tools.canned = [json.dumps(payload)]
    sketch = await LeanSession(tools).sketch_goals(SOURCE, operation_id="b")
    assert sketch["header"] == "import Mathlib"
    assert sketch["holes"] == [
        {"index": 0, "goal": "⊢ a", "extract_failed": True, "reason": "statement_too_long"},
        {"index": 1, "goal": "⊢ b", "extract_failed": True, "reason": "statement_too_long"},
    ]


# Fix round 2: residual hostile paths, invalid sources, extraction reserve

SURROGATE = "\ud800"


@pytest.mark.parametrize(
    "payload",
    [
        {
            **GOOD,
            "counts": {"errors": 1, "messages": 1, "sorries": 1, "sorry_warnings": 0},
            "messages": [{"severity": "error", "data": "bad " + SURROGATE}],
            "sorries": [
                {
                    "goal": "⊢ " + SURROGATE,
                    "extracted": "theorem extracted_1 (x : Nat) : x = " + SURROGATE + " := sorry",
                    "automation": {"suggestion": SURROGATE, "tried": []},
                }
            ],
            "axioms": {SURROGATE: [SURROGATE]},
        },
        {**GOOD, "axioms": {"t" + SURROGATE: ["propext" + SURROGATE]}},
        {"error": "repl_error", "detail": "detail " + SURROGATE},
        {"error": SURROGATE, "detail": SURROGATE},
    ],
    ids=["check", "axioms", "repl_error", "unknown_error"],
)
async def test_lone_surrogates_from_the_vm_are_replaced(lean_env, payload):
    from physharness.domain import digest_json

    stdout = json.dumps(payload)  # json escapes lone surrogates as \\ud800
    assert "\\ud800" in stdout
    tools = FakeWorkspaceTools(lean_env)
    tools.canned = [stdout] * 3
    session = LeanSession(tools)
    results = [
        await session.check(SOURCE, automate=True, operation_id="a"),
        await session.sketch_goals(SOURCE, operation_id="b"),
        await session.elaborate_statement("import Mathlib", "t", ": True", operation_id="c"),
    ]
    _assert_bounded_check(results[0])
    for result in results:
        json.dumps(result, ensure_ascii=False).encode("utf-8")  # no UnicodeEncodeError
        digest_json(result)
    assert SURROGATE not in json.dumps(results, ensure_ascii=False)


async def test_invalid_unicode_source_is_rejected_before_any_call(lean_env):
    tools = FakeWorkspaceTools(lean_env)
    session = LeanSession(tools)
    with pytest.raises(HarnessError) as error:
        await session.check("theorem t : True := " + SURROGATE, automate=True, operation_id="a")
    assert error.value.code == "INVALID_SOURCE" and error.value.status == 422
    with pytest.raises(HarnessError) as error:
        await session.sketch_goals(SURROGATE, operation_id="b")
    assert error.value.code == "INVALID_SOURCE"
    with pytest.raises(HarnessError) as error:
        await session.elaborate_statement("import Mathlib", "t", ": " + SURROGATE, operation_id="c")
    assert error.value.code == "INVALID_SOURCE"
    with pytest.raises(HarnessError) as error:
        await session.check(b"theorem", automate=True, operation_id="d")
    assert error.value.code == "INVALID_SOURCE"
    assert tools.calls == []


def test_daemon_extraction_keeps_a_send_reserve(lean_env, monkeypatch):
    monkeypatch.setenv("FAKE_LEAN_REPL_DIR", str(lean_env.logs))
    session = daemon.Session([sys.executable, str(FAKE_REPL)], str(lean_env.root))
    try:
        session.handle({"op": "check", "source": SOURCE}, time.monotonic() + 20)
        tight = time.monotonic() + daemon.EXTRACT_RESERVE_SECONDS * 0.8
        result = session.handle({"op": "check", "source": SOURCE, "extract_goals": True}, tight)
        assert result["header_cached"] is True
        assert result["phase_error"] == "budget_exhausted"
        assert result["sorries"][0]["extracted"] is None
        # Nothing was written with too little time left, so the REPL was not reset.
        assert session.repl is not None and session.repl.process.poll() is None
        assert session.generation == 1
        assert not [c for c in _commands(lean_env) if c.get("tactic") == "extract_goal"]
    finally:
        session.reset()
