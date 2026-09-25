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

from physharness.formal_tools import lean_session_daemon as daemon
from physharness.orchestration.lean_session import (
    AUTOMATION,
    DAEMON_PATH,
    REPL_CANDIDATES,
    LeanSession,
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
        stdout, exit_code = self.scratch.pop(0)
        return {
            "source_path": path,
            "source_sha256": digest,
            "diagnostics": {
                "operation_id": operation_id + ":lean",
                "execution_id": "local",
                "exit_code": exit_code,
                "stdout": stdout.format(path="/work/" + path),
                "stderr": "",
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
    assert first["automation"]["closed_by"] == "linarith" and first["extracted"] is None
    assert second["automation"]["suggestion"] == "exact fake_lemma"
    assert third["automation"]["closed_by"] is None
    assert third["automation"]["tried"] == list(AUTOMATION)
    assert third["extracted"] is None
    assert result["axioms"] is None  # holes remain, so no axiom report
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
    assert sketch["holes"] == [{"index": 0, "goal": None, "extract_failed": True}]
    assert sketch["reason_code"] == "lean_repl_unavailable"


async def test_sketch_goals_extracts_signatures(lean_env):
    source = (
        "import Mathlib\n\ntheorem main (x : Nat) : x = x := by\n"
        "  have h0 : x = x := by\n    sorry\n"
        "  have h1 : x = x := by\n    sorry\n"
        "  have h2 : x = x := by\n    sorry\n"
        "  sorry -- goal: NOEXTRACT\n"
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
            },
            {"index": 3, "goal": "⊢ NOEXTRACT", "extract_failed": True},
        ],
        "closed": [
            {"index": 0, "closed_by": "linarith", "suggestion": None},
            {"index": 1, "closed_by": "exact?", "suggestion": "exact fake_lemma"},
        ],
    }
    extracted = [c["proofState"] for c in _commands(lean_env) if c.get("tactic") == "extract_goal"]
    assert extracted == [2, 3]
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
    scratch = [
        ("", 0),
        ("'top' depends on axioms: [propext]\n'also_top' does not depend on any axioms\n", 0),
    ]
    tools = FakeWorkspaceTools(lean_env, repl_present=False, scratch=scratch)
    result = await LeanSession(tools).check(AXIOM_SOURCE, automate=True, operation_id="op")
    assert result["backend"] == "one_shot" and result["complete"] is True
    assert result["axioms"] == {"top": ["propext"], "also_top": []}
    second = [call[1] for call in tools.calls if call[0] == "lean_scratch"][1]
    assert second == AXIOM_SOURCE + "\n#print axioms top\n#print axioms also_top"
    sorry_axiom = [("", 0), ("'top' depends on axioms: [sorryAx]\n", 0)]
    tools = FakeWorkspaceTools(lean_env, repl_present=False, scratch=sorry_axiom)
    result = await LeanSession(tools).check(AXIOM_SOURCE, automate=True, operation_id="op")
    assert result["ok"] is True and result["complete"] is False


async def test_outputs_bounded(lean_env):
    lines = ["import Mathlib", ""]
    for index in range(40):
        lines += [f"theorem t{index} (x : Nat) : x = x := by", "  sorry -- goal: " + "g" * 5000]
    lines += ["-- WARN " + "w" * 3000 for _ in range(60)]
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
        ("'t' does not depend on any axioms\n", 0),
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
    scratch = [("", 0), ("'t' does not depend on any axioms\n", 0)]
    tools = FakeWorkspaceTools(lean_env, scratch=scratch)
    result = await LeanSession(tools).check(SOURCE, automate=True, operation_id="op")
    assert result["backend"] == "one_shot" and result["reason_code"] == "lean_repl_unavailable"
    assert result["messages"][0]["text"].startswith("Lean REPL could not start")
    assert "the daemon could not be placed" in result["messages"][0]["text"]
