"""Local compiles rest on the harness statement check, never on the file's own output.

Lean-marked tests run real Lean (``PHYSHARNESS_LEAN_CMD``, else elan's v4.33.0 toolchain)
through the society ``lean_check`` tool and ``LeanSession.verify_statement``. They show that
plain Lean source cannot move a false or axiom-dirty statement to ``compiles_locally``: an
instance or macro that changes what the statement's text means, an elaborator that forges
the ``#print axioms`` report, and a declaration added with ``debug.skipKernelTC``.
The other tests drive the checker's plumbing and the statement-shape rules without Lean.
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path
from types import SimpleNamespace

import pytest
from commons_helpers import set_status, society_lab
from test_lean_session import FakeWorkspaceTools, RealLeanScratchTools, lean_env  # noqa: F401
from test_society_tools import FakeWorkspace, call, lemma_args, profile, running

from physharness.errors import HarnessError
from physharness.formal_tools import statement_check as driver
from physharness.orchestration.lean_session import (
    CHECK_BACKEND,
    CHECK_FILES,
    LeanSession,
    header_problem,
    signature_problem,
)

FALSE = {"lean_header": "import Lean", "lean_name": "bad", "lean_statement": ": (2 : Nat) + 2 = 5"}
TRUE = {"lean_header": "import Lean", "lean_name": "good", "lean_statement": ": (2 : Nat) + 2 = 4"}
# Each forgery is ordinary Lean source submitted through lean_check; before the statement
# check, each moved the false node to compiles_locally (Lean 4.33, one-shot backend).
FORGERIES = {
    "instance_shadowing": (
        "import Lean\n\n"
        "instance (priority := high) evilAdd : HAdd Nat Nat Nat := ⟨fun _ _ => 5⟩\n\n"
        "theorem bad : (2 : Nat) + 2 = 5 := rfl\n"
    ),
    "macro_rules": (
        "import Lean\n\n"
        "macro_rules | `($_a = $_b) => `(True)\n\n"
        "theorem bad : (2 : Nat) + 2 = 5 := trivial\n"
    ),
    "print_axioms_override": (
        "import Lean\n\n"
        "axiom cheat : False\n\n"
        "open Lean Elab Command in\n"
        "elab_rules : command\n"
        "  | `(#print axioms $id) => logInfo m!\"'{id.getId}' does not depend on any axioms\"\n\n"
        "theorem bad : (2 : Nat) + 2 = 5 := cheat.elim\n"
    ),
    "skip_kernel_tc": (
        "import Lean\n\n"
        "open Lean Elab Command in\n"
        "set_option debug.skipKernelTC true in\n"
        "run_cmd liftCoreM <| addDecl (.thmDecl { name := `lemmaFalse, levelParams := [], "
        "type := mkConst ``False, value := mkConst ``Nat.zero })\n\n"
        "theorem bad : (2 : Nat) + 2 = 5 := lemmaFalse.elim\n"
    ),
}
FORGERY_REASONS = {
    "instance_shadowing": "statement_mismatch",
    "macro_rules": "statement_mismatch",
    "print_axioms_override": "nonstandard_axioms",
    "skip_kernel_tc": "kernel_rejected",
}
HONEST = (
    "import Lean\n\n"
    "structure Pair where\n  a : Nat\n  b : Nat\n\n"
    "def Pair.sum (p : Pair) : Nat := p.a + p.b\n\n"
    "theorem helper : (Pair.mk 2 2).sum = 4 := rfl\n\n"
    "theorem good : (2 : Nat) + 2 = 4 := helper\n"
)
LAKE_SHIM = (
    "#!/bin/sh\n"
    "# `lake --offline env CMD...` in a Lake project; here CMD runs as is.\n"
    '[ "$1" = "--offline" ] && shift\n'
    '[ "$1" = "env" ] && shift\n'
    'exec "$@"\n'
)


def _toolchain_bin():
    command = os.environ.get("PHYSHARNESS_LEAN_CMD")
    if not command and shutil.which("lean"):
        command = "lean +leanprover/lean4:v4.33.0"
    if not command:
        return None
    try:
        prefix = subprocess.run(
            [*shlex.split(command), "--print-prefix"], capture_output=True, text=True, timeout=120
        )
    except (OSError, subprocess.SubprocessError):
        return None
    binary = Path(prefix.stdout.strip()) / "bin"
    return binary if prefix.returncode == 0 and (binary / "lean").exists() else None


@pytest.fixture
def real_lean(lean_env):  # noqa: F811
    """``lean_env`` with a ``lake`` shim and a real Lean toolchain on its PATH."""
    binary = _toolchain_bin()
    if binary is None:
        pytest.skip("set PHYSHARNESS_LEAN_CMD, or install elan's leanprover/lean4:v4.33.0")
    shim = lean_env.root / "bin" / "lake"
    shim.write_text(LAKE_SHIM)
    shim.chmod(0o755)
    lean_env.env["PATH"] = os.pathsep.join(
        [str(lean_env.root / "bin"), str(binary), lean_env.env["PATH"]]
    )
    lean_env.lean = str(binary / "lean")
    return lean_env


def _tools(state, backend):
    """Workspace tools whose argv runs locally; one-shot checks run real Lean, and the REPL
    backends' checks are answered by the fake REPL (which reports standard axioms).

    As in the VM, the Lake project (/opt/sources/physlib) is a directory apart from the
    workspace (/work), so Lean runs there on files outside it.
    """
    if backend == "one_shot":
        tools = RealLeanScratchTools(state, state.lean)
    else:
        tools = FakeWorkspaceTools(state, background=backend == "repl")
    project = state.root / "project"
    project.mkdir(exist_ok=True)
    tools.substitutions = [
        (old, str(project) if old == "/opt/sources/physlib" else new)
        for old, new in tools.substitutions
    ]
    return tools


async def _formal_node(tools, service, node):
    created = await call(tools, "commons_node", lemma_args(**node))
    stated = await call(
        tools, "commons_node", {"action": "set_lean_statement", "node_id": created["id"], **node}
    )
    assert stated["lean_elaborated"] is True, stated
    set_status(service, created["id"], "formally_stated")
    return created["id"]


# Real Lean -------------------------------------------------------------------------


@pytest.mark.lean
@pytest.mark.parametrize("backend", ["one_shot", "repl_inline", "repl"])
async def test_plain_lean_source_cannot_forge_a_local_compile(lab, real_lean, backend):
    service, author, exp, branches, _ = society_lab(lab)
    alpha, context = running(service, author, exp, branches[0]["id"])
    session = LeanSession(_tools(real_lean, backend))
    tools = profile(service, alpha, context, workspace=FakeWorkspace(lean=session))
    node = await _formal_node(tools, service, FALSE)
    for label, source in FORGERIES.items():
        checked = await call(tools, "lean_check", {"source": source, "node_id": node})
        # The session's own report may say complete with no axioms; it does not decide.
        assert checked["local_compile"]["recorded"] is False, (label, checked)
        assert checked["local_compile"]["reason"] == FORGERY_REASONS[label], (label, checked)
        assert service.get_record("commons_node", node, alpha)["status"] == "formally_stated"
    assert session._backend == backend
    # An honest proof of a true statement still compiles locally, on the check's axioms.
    honest = await _formal_node(tools, service, TRUE)
    checked = await call(tools, "lean_check", {"source": HONEST, "node_id": honest})
    assert checked["local_compile"]["recorded"] is True, checked
    assert checked["local_compile"]["status_evidence"] == {
        "source_sha256": checked["source_sha256"],
        "backend": CHECK_BACKEND,
        "axioms": {"good": []},
    }
    assert service.get_record("commons_node", honest, alpha)["status"] == "compiles_locally"


@pytest.mark.lean
async def test_statement_check_verdicts_on_real_lean(real_lean):
    session = LeanSession(_tools(real_lean, "one_shot"))

    async def verify(source, node=FALSE, key="v"):
        return await session.verify_statement(
            source, node["lean_header"], node["lean_name"], node["lean_statement"], operation_id=key
        )

    for label, source in FORGERIES.items():
        verdict = await verify(source, key=label)
        if label == "print_axioms_override":
            # The forged report is ignored: the checker collects the axioms itself.
            assert verdict["ok"] is True and verdict["axioms"] == ["cheat"], verdict
        else:
            assert verdict["ok"] is False, (label, verdict)
            assert verdict["reason"] == FORGERY_REASONS[label], (label, verdict)
    classical = (
        "import Lean\n\ntheorem good : (2 : Nat) + 2 = 4 ∧ (True ∨ ¬True) :=\n"
        "  ⟨rfl, Classical.em True⟩\n"
    )
    node = {**TRUE, "lean_statement": ": (2 : Nat) + 2 = 4 ∧ (True ∨ ¬True)"}
    verdict = await verify(classical, node, "classical")
    assert verdict == {
        "ok": True,
        "reason": None,
        "axioms": ["propext", "Classical.choice", "Quot.sound"],
        "detail": None,
        "backend": CHECK_BACKEND,
    }
    sorried = await verify("import Lean\n\ntheorem good : (2 : Nat) + 2 = 4 := sorry\n", TRUE, "s")
    assert sorried["ok"] is True and sorried["axioms"] == ["sorryAx"]
    # A hole node: its header ends with the universe line its statement needs.
    universe = {
        "lean_header": "import Lean\nuniverse u_1",
        "lean_name": "refl_hole_0",
        "lean_statement": "{α : Type u_1} (a : α) : a = a",
    }
    source = "import Lean\nuniverse u_1\n\ntheorem refl_hole_0 {α : Type u_1} (a : α) : a = a :=\n"
    verdict = await verify(source + "  rfl\n", universe, "universe")
    assert verdict["ok"] is True and verdict["axioms"] == []
    # Other universe parameters are another statement.
    other = source.replace("Type u_1", "Sort u_1")
    assert (await verify(other + "  rfl\n", universe, "sort"))["reason"] == "statement_mismatch"
    # A source that does not compile, or declares no such theorem, fails closed.
    broken = await verify("import Lean\n\ntheorem bad : (2 : Nat) + 2 = 5 := rfl\n", key="x")
    assert broken["ok"] is False and broken["reason"] == "source_compile_failed"
    missing = await verify("import Lean\n\ntheorem other : True := trivial\n", key="y")
    assert missing["reason"] == "theorem_missing"
    assert not any((real_lean.root / "work" / ".physharness").glob("check-*"))


@pytest.mark.lean
async def test_elaboration_rejects_a_signature_that_ends_the_declaration(real_lean):
    session = LeanSession(_tools(real_lean, "one_shot"))
    injected = ": True := trivial\n#exit\ntheorem junk : (1 : Nat) = 2"
    with pytest.raises(HarnessError) as raised:
        await session.elaborate_statement("", "n", injected, operation_id="injected")
    assert raised.value.code == "INVALID_ARGUMENTS"
    assert not [c for c in session._tools.calls if c[0] in ("lean_scratch", "run")]
    plain = await session.elaborate_statement("", "n", ": (1 : Nat) = 1", operation_id="plain")
    assert plain["ok"] is True


# Statement shape ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "signature",
    [
        ": (1 : Nat) + 1 = 2",
        "(x : ℝ) (h : 0 < x) : 0 < x ^ 2",
        "{α : Type u_1} [inst : Inhabited α] ⦃a : α⦄ : a = a",
        ": ∀ ε > 0, ∃ δ > 0, |δ| < ε",
        ": (fun x : Nat => x) 1 = 1",
        ": ({ fst := 1, snd := 2 } : Nat × Nat).1 = 1",
        ": (let x := 1; x) = 1",
        ": (match (0 : Nat) with | 0 => True | _ => False)",
        ': "a := b" = "a := b" -- a note := here',
        "(x : Nat := 5) : x = x",
        ": somewhere = somewhere",
    ],
)
def test_signature_shape_accepts_plain_signatures(signature):
    assert signature_problem(signature) is None


@pytest.mark.parametrize(
    ("signature", "problem"),
    [
        (": True := trivial\n#exit\ntheorem junk : (1 : Nat) = 2", "declaration_value"),
        (": True := trivial\ntheorem junk : (1 : Nat) = 2", "declaration_value"),
        (": Nat → True\n| _ => trivial\n#exit", "match_alternatives"),
        (": Nonempty Nat where\n#exit", "where_clause"),
        (": (True\n#exit", "unbalanced_brackets"),
        (": True)\n#exit", "unbalanced_brackets"),
        (": (True]", "unbalanced_brackets"),
        (": let x := 1; x = 1", "declaration_value"),
        ("   ", "empty"),
        ("-- only a comment", "unreadable"),
    ],
)
def test_signature_shape_rejects_text_that_ends_the_declaration(signature, problem):
    assert signature_problem(signature) == problem


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "import Mathlib",
        "import Mathlib\nopen Real\nopen scoped BigOperators Topology",
        "/- Copyright -/\nimport Mathlib.Data.Real.Basic\n-- physics\nopen Real\n  Topology",
        "import Lean\nset_option maxHeartbeats 400000\nset_option autoImplicit false",
        'import Lean\nset_option trace.profiler.output "x"',
        "import Mathlib\nopen Nat (succ_le_iff)\nuniverse u v u_1 u₁",
        "public import Mathlib",
    ],
)
def test_header_shape_accepts_import_open_set_option_and_universe_lines(header):
    assert header_problem(header) is None


@pytest.mark.parametrize(
    "header",
    [
        "import Mathlib\n#exit",
        "import Mathlib #exit",
        "import Mathlib\nopen Real #exit",
        "import Mathlib\nopen Real in",
        "import Mathlib\nopen Real hiding pi",
        "import Lean\ninstance (priority := high) evil : HAdd Nat Nat Nat := ⟨fun _ _ => 5⟩",
        "import Lean\nmacro_rules | `($_a = $_b) => `(True)",
        "import Lean\nset_option debug.skipKernelTC true in",
        "import Lean\nuniverse u end",
        "import Lean\nnamespace Foo",
        "import Lean\nopen Real\nTopology",
    ],
)
def test_header_shape_rejects_other_commands(header):
    assert header_problem(header) == "header_line"


async def test_elaboration_refuses_injected_statements_before_lean_runs(lean_env):  # noqa: F811
    tools = FakeWorkspaceTools(lean_env, repl_present=False)
    session = LeanSession(tools)
    for header, signature in (
        ("", ": True := trivial\n#exit"),
        ("import Mathlib\n#exit", ": 1 = 2"),
    ):
        with pytest.raises(HarnessError) as raised:
            await session.elaborate_statement(header, "n", signature, operation_id="e")
        assert raised.value.code == "INVALID_ARGUMENTS"
        with pytest.raises(HarnessError):
            await session.elaborate_statements(
                header, [("h", ": 1 = 1", ()), ("n", signature, ())], operation_id="b"
            )
    with pytest.raises(HarnessError):  # a universe name is a header line too
        await session.elaborate_statements(
            "import Mathlib", [("h", ": 1 = 1", ("u_1\n#exit",))], operation_id="u"
        )
    assert tools.calls == []


async def test_sketch_gives_no_node_statement_for_an_injected_goal(lean_env):  # noqa: F811
    """A goal pretty-printed through the file's own notation can carry commands."""
    tools = FakeWorkspaceTools(lean_env)
    forged = "theorem extracted_1 : True := trivial\n#exit\ntheorem y : False := sorry"
    tools.canned.append(
        json.dumps(
            {
                "op": "check",
                "counts": {"errors": 0, "messages": 0, "sorries": 2, "sorry_warnings": 0},
                "messages": [],
                "sorries": [
                    {"pos": {"line": 3, "column": 2}, "goal": "⊢ True", "extracted": forged},
                    {
                        "pos": {"line": 4, "column": 2},
                        "goal": "⊢ 1 = 1",
                        "extracted": "theorem extracted_1 : 1 = 1 := sorry",
                    },
                ],
                "axioms": None,
            }
        )
    )
    sketch = await LeanSession(tools).sketch_goals(
        "import Mathlib\n\ntheorem t : True := by\n  sorry\n  sorry\n", operation_id="s"
    )
    first, second = sketch["holes"]
    assert first["extract_failed"] is True and first["reason"] == "invalid_signature"
    assert second["lean_statement"] == ": 1 = 1" and "extract_failed" not in second


# Statement check plumbing ------------------------------------------------------------


def test_statement_check_files_are_packaged_and_fit_one_upload():
    for file in CHECK_FILES:
        data = resources.files("physharness.formal_tools").joinpath(file).read_bytes()
        assert 0 < len(data) < 32_768  # E2B's per-file workspace upload limit


class CheckTools:
    """Records uploads and answers each statement-check run with a scripted result."""

    def __init__(self, *answers):
        self.policy = SimpleNamespace(timeout_seconds=600)
        self.answers, self.calls = list(answers), []

    async def write(self, arguments, operation_id):
        self.calls.append(("write", arguments["path"]))
        return {"path": arguments["path"]}

    async def run(self, arguments, operation_id):
        self.calls.append(("run", arguments["argv"][2]))
        stdout, exit_code = self.answers.pop(0)
        return {"exit_code": exit_code, "stdout": stdout, "stderr": "Traceback: boom"}


async def _verify(tools, source="import Lean\n\ntheorem bad : 1 = 1 := rfl\n", **node):
    node = {**FALSE, **node}
    return await LeanSession(tools).verify_statement(
        source,
        node["lean_header"],
        node["lean_name"],
        node["lean_statement"],
        operation_id="op",
    )


@pytest.mark.parametrize(
    ("stdout", "reason"),
    [
        ("", "statement_check_failed"),
        ("not json", "statement_check_failed"),
        ("[1, 2]", "statement_check_failed"),
        ('{"ok": "true", "axioms": []}', "statement_check_failed"),
        ('{"ok": 1, "axioms": []}', "statement_check_failed"),
        ('{"ok": true}', "statement_check_malformed"),
        ('{"ok": true, "axioms": "propext"}', "statement_check_malformed"),
        ('{"ok": true, "axioms": [1]}', "statement_check_malformed"),
        ('{"ok": true, "axioms": [""]}', "statement_check_malformed"),
        (json.dumps({"ok": True, "axioms": ["a"] * 33}), "statement_check_malformed"),
        ('{"ok": false, "reason": "Statement Mismatch!"}', "statement_check_failed"),
        ('{"ok": false, "reason": "statement_mismatch"}', "statement_mismatch"),
        ("[" * 100000, "statement_check_failed"),
    ],
)
async def test_statement_check_answers_are_retyped_and_fail_closed(stdout, reason):
    verdict = await _verify(CheckTools((stdout, 0)))
    assert verdict["ok"] is False and verdict["axioms"] is None
    assert verdict["reason"] == reason


async def test_statement_check_uploads_its_files_once_and_after_a_restore():
    ok = json.dumps({"ok": True, "axioms": ["propext"], "reason": None})
    tools = CheckTools((ok, 0), ("", 97), (ok, 0))
    session = LeanSession(tools)

    async def verify(key):
        return await session.verify_statement(
            "import Lean\n\ntheorem bad : 1 = 1 := rfl\n",
            "import Lean",
            "bad",
            ": 1 = 1",
            operation_id=key,
        )

    first = await verify("first")
    assert first == {
        "ok": True,
        "reason": None,
        "axioms": ["propext"],
        "detail": None,
        "backend": CHECK_BACKEND,
    }
    uploads = [path for kind, path in tools.calls if kind == "write"]
    assert uploads[:2] == [".physharness/statement_check.py", ".physharness/statement_check.lean"]
    assert [Path(path).name for path in uploads[2:]] == ["Source.lean", "Reference.lean"]
    tools.calls.clear()
    # The VM dropped /tmp: the run reports the files missing, they are uploaded, and the
    # check runs again.
    assert (await verify("second"))["ok"] is True
    kinds = [(kind, Path(path).name if kind == "write" else "") for kind, path in tools.calls]
    assert kinds == [
        ("write", "Source.lean"),
        ("write", "Reference.lean"),
        ("run", ""),
        ("write", "statement_check.py"),
        ("write", "statement_check.lean"),
        ("run", ""),
    ]
    missing = CheckTools(("", 97), ("", 97))
    assert (await _verify(missing))["reason"] == "statement_check_unavailable"
    assert "rm -rf .physharness/check-" in missing.calls[-1][1]


async def test_statement_check_refuses_invalid_statements_without_the_vm():
    for node in (
        {"lean_statement": ": True := trivial\n#exit"},
        {"lean_header": "import Lean\n#exit"},
        {"lean_name": "bad name"},
    ):
        tools = CheckTools()
        verdict = await _verify(tools, **node)
        assert verdict["reason"] == "invalid_lean_statement" and tools.calls == []
    tools = CheckTools()
    too_large = await _verify(tools, source="-" * 30_001)
    assert too_large["reason"] == "statement_check_too_large" and tools.calls == []


FAKE_LEAN = """\
import os, sys, time
args = sys.argv[1:]
mode = os.environ.get("FAKE_CHECK_MODE", "ok")
if args[0] == "-R":
    assert args[2] == "-o" and args[4].startswith(args[1] + "/")
    source = open(args[4]).read()
    if "FAIL" in source:
        print("error: FAIL"); sys.exit(1)
    if "SLOW" in source:
        time.sleep(30)
    open(args[3], "w").write("olean")
    sys.exit(0)
assert args[0] == "--run"
if mode == "twice":
    print('PHYSHARNESS_STATEMENT_CHECK {"ok": true, "axioms": []}')
if mode == "exit":
    sys.exit(1)
print('PHYSHARNESS_STATEMENT_CHECK {"ok": true, "axioms": ["propext"]}')
"""


@pytest.fixture
def fake_check(tmp_path, monkeypatch):
    """The driver against a fake ``lake env lean`` that honours ``-o`` and ``--run``."""
    tools = tmp_path / "bin"
    tools.mkdir()
    (tools / "lake").write_text(
        f'#!/bin/sh\nshift 2\nshift\nexec {shlex.quote(sys.executable)} {tools / "lean.py"} "$@"\n'
    )
    (tools / "lake").chmod(0o755)
    (tools / "lean.py").write_text(FAKE_LEAN)
    monkeypatch.setenv("PATH", f"{tools}{os.pathsep}{os.environ['PATH']}")

    def run(source="theorem bad : 1 = 1 := rfl", *, mode="ok", timeout=20.0):
        monkeypatch.setenv("FAKE_CHECK_MODE", mode)
        workdir = tmp_path / "check"
        workdir.mkdir()
        (workdir / "Source.lean").write_text(source)
        (workdir / "Reference.lean").write_text("theorem bad : 1 = 1 := sorry")
        completed = subprocess.run(
            [sys.executable, driver.__file__, "--timeout", str(timeout), "--cwd", str(tmp_path)]
            + ["--checker", "check.lean", str(workdir), "bad"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stderr
        assert not workdir.exists()
        return json.loads(completed.stdout)

    return run


def test_statement_check_driver_compiles_then_runs_the_checker(fake_check):
    assert fake_check() == {"ok": True, "axioms": ["propext"]}
    failed = fake_check("FAIL")
    assert failed["reason"] == "source_compile_failed" and "error: FAIL" in failed["detail"]
    # Only one report counts, from a checker that exits normally.
    assert fake_check(mode="twice")["reason"] == "checker_failed"
    assert fake_check(mode="exit")["reason"] == "checker_failed"
    assert fake_check("SLOW", timeout=1)["reason"] == "check_timeout"
