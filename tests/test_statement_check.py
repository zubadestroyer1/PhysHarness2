"""Verified source ranks rest on the harness statement check, never on the file's output.

Lean-marked tests run real Lean (``PHYSHARNESS_LEAN_CMD``, else elan's v4.33.0 toolchain)
through the society ``lean_check`` tool and ``LeanSession.verify_statement``. They show that
elaboration-level tricks in plain Lean source cannot publish a false or axiom-dirty statement
as a ``verified`` source: an instance or macro that changes what the statement's text means,
an elaborator that forges the ``#print axioms`` report, and a declaration added with
``debug.skipKernelTC``. (Compile-time code that writes VM files, like a shell command, can
tamper with the check itself: the result is VM-attested.) They also show that honest
headers and ``match`` statements pass. The other tests drive the checker's plumbing and the
statement-shape rules without Lean.
"""

import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path
from types import SimpleNamespace

import pytest
from commons_helpers import society_lab
from test_lean_session import FakeWorkspaceTools, RealLeanScratchTools, lean_env  # noqa: F401
from test_society_tools import FakeWorkspace, call, lemma_args, profile, running

from physharness.errors import HarnessError
from physharness.formal_tools import statement_check as driver
from physharness.orchestration import workspace_tools as workspace_tools_module
from physharness.orchestration.lean_session import (
    CHECK_BACKEND,
    CHECK_FILES,
    LeanSession,
    header_problem,
    signature_problem,
)
from physharness.orchestration.workspace_tools import WorkspaceTools

FALSE = {"lean_header": "import Lean", "lean_name": "bad", "lean_statement": ": (2 : Nat) + 2 = 5"}
TRUE = {"lean_header": "import Lean", "lean_name": "good", "lean_statement": ": (2 : Nat) + 2 = 4"}
# Each forgery is ordinary Lean source submitted through lean_check; before the statement
# check, each moved the false node to the S1 status compiles_locally (Lean 4.33, one-shot).
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
# What lean_check does with each forgery: the refusal reason, or the rank it publishes (never
# verified: the check finds the added axiom).
FORGERY_OUTCOMES = {
    "instance_shadowing": "statement_mismatch",
    "macro_rules": "statement_mismatch",
    "print_axioms_override": "partial",
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
    return created["id"]


# Real Lean -------------------------------------------------------------------------


@pytest.mark.lean
@pytest.mark.parametrize("backend", ["one_shot", "repl_inline", "repl"])
async def test_elaboration_tricks_cannot_forge_a_verified_source(lab, real_lean, backend):
    service, author, exp, branches, _ = society_lab(lab)
    alpha, context = running(service, author, exp, branches[0]["id"])
    session = LeanSession(_tools(real_lean, backend))
    tools = profile(service, alpha, context, workspace=FakeWorkspace(lean=session))
    node = await _formal_node(tools, service, FALSE)
    for label, source in FORGERIES.items():
        checked = await call(tools, "lean_check", {"source": source, "node_id": node})
        # The session's own report may say complete with no axioms; it does not decide.
        published = checked["published"]
        outcome = published.get("rank") if published["recorded"] else published["reason"]
        assert outcome == FORGERY_OUTCOMES[label], (label, checked)
        stored = service.read_node(node, alpha)["node"]
        assert (stored["lean_source"] or {}).get("rank") != "verified", (label, stored)
    assert session._backend == backend
    # An honest proof of a true statement is published verified, on the check's axioms.
    honest = await _formal_node(tools, service, TRUE)
    checked = await call(tools, "lean_check", {"source": HONEST, "node_id": honest})
    assert checked["published"]["rank"] == "verified", checked
    stored = service.read_node(honest, alpha)["node"]
    assert stored["lean_source"]["statement_check"] == {"ok": True, "reason": None, "axioms": []}
    assert stored["status"] == "open"  # only the independent verifier accepts


@pytest.mark.lean
async def test_a_skeleton_ranks_partial_until_its_stubs_are_filled(lab, real_lean):
    service, author, exp, branches, _ = society_lab(lab)
    alpha, context = running(service, author, exp, branches[0]["id"])
    session = LeanSession(_tools(real_lean, "one_shot"))
    tools = profile(service, alpha, context, workspace=FakeWorkspace(lean=session))
    node = await _formal_node(tools, service, TRUE)
    skeleton = (
        "import Lean\n\n"
        "theorem step : (2 : Nat) + 2 = 4 := sorry\n\n"
        "theorem good : (2 : Nat) + 2 = 4 := step\n"
    )
    checked = await call(tools, "lean_check", {"source": skeleton, "node_id": node, "stubs": True})
    (stub,) = checked["stubs"]
    assert stub["created"] is True, checked
    # The published text has no sorry of its own; the stub it imports inlines as sorry.
    assert "sorry" not in checked["skeleton_source"]
    assert checked["complete"] is False and checked["published"]["rank"] == "partial", checked
    # Filled under the skeleton's plain header, the stub passes the statement check, and the
    # republished skeleton is verified.
    filled = "import Lean\n\ntheorem step : (2 : Nat) + 2 = 4 := rfl\n"
    proved = await call(tools, "lean_check", {"source": filled, "node_id": stub["node_id"]})
    assert proved["published"]["rank"] == "verified", proved
    source = checked["skeleton_source"]
    again = await call(tools, "lean_check", {"source": source, "node_id": node})
    assert again["published"]["rank"] == "verified", again


@pytest.mark.lean
async def test_stub_headers_refuse_auto_bound_definition_names(lab, real_lean):
    service, author, exp, branches, _ = society_lab(lab)
    alpha, context = running(service, author, exp, branches[0]["id"])
    session = LeanSession(_tools(real_lean, "one_shot"))
    tools = profile(service, alpha, context, workspace=FakeWorkspace(lean=session))
    node = await _formal_node(tools, service, TRUE)
    # Lean's default binds an unknown non-function name as a variable: false, yet it elaborates.
    # (An unknown applied name, f 0, is refused either way.)
    auto = await session.elaborate_statements(
        "import Lean", [("two_eq", ": two = 2", ()), ("f0", ": f 0 = 1", ())], operation_id="a"
    )
    assert [result["ok"] for result in auto] == [True, False], auto
    skeleton = (
        "import Lean\n\n"
        "def two : Nat := 2\n\n"
        "def f (n : Nat) : Nat := n\n\n"
        "theorem two_eq : two = 2 := sorry\n\n"
        "theorem f0 : f 0 = 1 := sorry\n\n"
        "theorem good : (2 : Nat) + 2 = 4 := rfl\n"
    )
    checked = await call(tools, "lean_check", {"source": skeleton, "node_id": node, "stubs": True})
    assert [(s["lean_name"], s["created"], s["reason"]) for s in checked["stubs"]] == [
        ("two_eq", False, "stub_needs_definition_node"),
        ("f0", False, "stub_needs_definition_node"),
    ], checked
    assert checked["skeleton_source"] == skeleton and checked["published"]["rank"] == "partial"
    # The skeleton's own autoImplicit true does not reach the stub elaboration.
    permissive = skeleton.replace("\n\ndef two", "\nset_option autoImplicit true\n\ndef two", 1)
    checked = await call(
        tools, "lean_check", {"source": permissive, "node_id": node, "stubs": True}
    )
    assert [s["reason"] for s in checked["stubs"]] == ["stub_needs_definition_node"] * 2, checked


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
            assert verdict["reason"] == FORGERY_OUTCOMES[label], (label, verdict)
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


# Honest statements the elaborator gives auxiliary constants (a matcher per ``match`` or
# ``fun`` with alternatives), each with a proof.
AUXILIARY = {
    "match": (": (match (0 : Nat) with | 0 => True | _ => False)", "trivial"),
    "fun_alternatives": (": (fun | 0 => True | _ => False : Nat → Prop) 0", "trivial"),
    "two_matches": (
        "(n : Nat) : (match n with | 0 => True | _ + 1 => True) ∧ "
        "(match n, n with | 0, _ => True | _, _ => True)",
        "by cases n <;> exact ⟨trivial, trivial⟩",
    ),
}


@pytest.mark.lean
async def test_honest_headers_and_match_statements_pass_the_check(real_lean):
    session = LeanSession(_tools(real_lean, "one_shot"))
    # Lower-case namespaces (Mathlib's unitInterval, symmDiff...), primed and Greek universe
    # names and safe options are honest header lines.
    header = (
        "import Lean\nopen scoped Classical\nopen npowRec\n  Nat.le\nuniverse u v u' uι\n"
        "set_option maxHeartbeats 400000\nset_option linter.unusedVariables false"
    )
    statement = "{α : Sort u} {β : Sort v} (a : α) (b : β) : a = a ∧ b = b"
    elaborated = await session.elaborate_statement(header, "h", statement, operation_id="h")
    assert elaborated["ok"] is True, elaborated
    source = f"{header}\n\ntheorem h {statement} := ⟨rfl, rfl⟩\n"
    verdict = await session.verify_statement(source, header, "h", statement, operation_id="h")
    assert verdict["ok"] is True and verdict["axioms"] == [], verdict
    for label, (statement, proof) in AUXILIARY.items():
        assert signature_problem(statement) is None, label
        source = f"import Lean\n\ntheorem t {statement} := {proof}\n"
        verdict = await session.verify_statement(
            source, "import Lean", "t", statement, operation_id=label
        )
        assert verdict["ok"] is True and verdict["axioms"] == [], (label, verdict)
    statement = AUXILIARY["match"][0]
    # The elaborator reuses an earlier helper's identical matcher: another name, same meaning.
    reused = (
        "import Lean\n\ndef helper (n : Nat) : Prop := match n with | 0 => True | _ => False\n\n"
        f"theorem t {statement} := trivial\n"
    )
    verdict = await session.verify_statement(
        reused, "import Lean", "t", statement, operation_id="reused"
    )
    assert verdict["ok"] is True and verdict["axioms"] == [], verdict
    # A matcher that means something else is another statement.
    other = "import Lean\n\ntheorem t : (match (0 : Nat) with | 0 => True | _ => True) := trivial\n"
    verdict = await session.verify_statement(
        other, "import Lean", "t", statement, operation_id="other"
    )
    assert verdict["reason"] == "statement_mismatch", verdict


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
    # A header that ends inside a block comment would carry the comment into the signature,
    # whose string literal then hides a declaration and #exit from the shape check.
    header, signature = "import Lean\nopen Nat /-", '" -/ theorem n : True := trivial\n#exit\n"'
    with pytest.raises(HarnessError) as raised:
        await session.elaborate_statement(header, "n", signature, operation_id="comment")
    assert raised.value.code == "INVALID_ARGUMENTS"


@pytest.mark.lean
async def test_elaboration_refuses_an_interpolation_shaped_injection(real_lean, tmp_path):
    """Regression for the signature shape-check bypass: an identifier ending in ``!``
    followed by a plain string whose ``{`` was mistaken for a ``s!`` interpolation. Lean
    4.33 runs whatever command follows the resulting parse error, so the shape check must
    refuse the signature before Lean sees it."""
    marker = "PWNED_FROM_INJECTION"
    header = "set_option autoImplicit true\nset_option relaxedAutoImplicit true"
    signature = f': x!"{{" := sorry\n#eval IO.println "{marker}"\n#exit\n"}}"'

    # The shape check refuses it, so the injected command never reaches Lean.
    assert signature_problem(signature) is not None
    session = LeanSession(_tools(real_lean, "one_shot"))
    with pytest.raises(HarnessError) as raised:
        await session.elaborate_statement(header, "n", signature, operation_id="inject")
    assert raised.value.code == "INVALID_ARGUMENTS"
    assert not [c for c in session._tools.calls if c[0] in ("lean_scratch", "run")]

    # Positive control: the exact source elaborate_statement would build does run the
    # injected command under real Lean 4.33, proving the refusal above is load-bearing.
    source = f"{header}\n\ntheorem n {signature} := by\n  sorry\n"
    path = tmp_path / "inject.lean"
    path.write_text(source, encoding="utf-8")
    completed = subprocess.run(
        [real_lean.lean, str(path)], capture_output=True, text=True, timeout=120, cwd=tmp_path
    )
    assert marker in completed.stdout


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
        # A signature may span lines; a continuation at column 0 whose first token is not a
        # command (a type name, a binder, a proposition) is fine.
        "(x : Nat)\n  (y : Nat) : x = y",
        "(x : Nat) :\nNat.succ x = x",
        "(p : Prop) :\np ∨ ¬ p",
        # `s!`/`m!`/`f!` interpolations are still read as interpolations, braces and all.
        ': s!"a{1}b" = s!"a{1}b"',
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
        # Lean would read the harness's own ``:= sorry`` into the comment or literal.
        (": True /- := sorry", "unterminated"),
        (': "a" = "b', "unterminated"),
        (": «x", "unterminated"),
        # ``x!"..."`` is an identifier ending in ``!`` then a *plain* string (only ``s!``/
        # ``m!``/``f!`` interpolate): Lean 4.33 reads ``{`` as a literal, so the ``:= sorry``
        # after it becomes visible and ends the declaration -- it must not be swallowed.
        (': x!"{" := sorry\n#eval IO.println "x"\n#exit\n"}"', "declaration_value"),
        ('(f : String) : f = f!"{f}" := rfl\n#eval IO.println "x"', "declaration_value"),
        # Belt-and-braces: a command at column 0 on a continuation line, whatever the lexer
        # made the preceding text look like. Lean recovers from a parse error there and runs
        # the command.
        (": foo\n#eval bar", "command_line"),
        (": foo\n#exit", "command_line"),
        (": foo\nset_option maxHeartbeats 0 in", "command_line"),
        (": foo\ntheorem evil : True", "command_line"),
        (": foo\n@[simp] theorem evil : True", "command_line"),
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
        "import Mathlib\nopen Nat (succ_le_iff)\nuniverse u v u_1 u₁",
        "public import Mathlib",
        # Namespaces named after definitions start lower-case; universe names are any
        # identifiers.
        "import Mathlib\nopen scoped unitInterval",
        "import Mathlib\nopen scoped symmDiff",
        "import Mathlib\nopen scoped nonZeroDivisors",
        "import Mathlib\nopen unitInterval intervalIntegral\n  symmDiff Real",
        "import Mathlib\nopen ArithmeticFunction.sigma Nat.le in.x",
        "import Mathlib\nuniverse u v u'",
        "import Mathlib\nuniverse uι U u₀ uᵢ",
        "import Mathlib\nopen Real\nopen Filter Topology",
        "import Mathlib\nset_option linter.unusedVariables false",
        "import Mathlib\nset_option linter.style.longLine false\nset_option pp.proofs true",
        "import Mathlib\nset_option synthInstance.maxHeartbeats 40000\nset_option maxRecDepth 2000",
        "import Mathlib\nset_option relaxedAutoImplicit false\n"
        "set_option exponentiation.threshold 300",
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
        # A command keyword ends the open or universe command and starts its own.
        "import Mathlib\nopen Real namespace Foo",
        "import Mathlib\nopen Real end",
        "import Mathlib\nopen Real set_option autoImplicit true",
        "import Mathlib\nopen Real seal Real.pi",
        "import Mathlib\nopen Real export Nat (succ)",
        "import Mathlib\nopen Real suppress_compilation",
        "import Mathlib\nopen scoped Real lemma",
        "import Mathlib\nuniverse u suppress_compilation",
        "import Mathlib\nuniverse u in",
        "import Mathlib\nopen Real hiding",
        "import Mathlib\nopen Real in\nopen Nat",
        "import Mathlib\nset_option maxHeartbeats 400000 in",
        "import Mathlib\nopen Real.",
        "import Mathlib\nuniverse u.v",
    ],
)
def test_header_shape_rejects_other_commands(header):
    assert header_problem(header) == "header_line"


@pytest.mark.parametrize(
    "header",
    [
        'import Lean\nset_option trace.profiler.output "x"',  # writes a file
        "import Lean\nset_option trace.profiler true",
        "import Lean\nset_option debug.skipKernelTC true",
        "import Lean\nset_option warningAsError true",
        "import Lean\nset_option compiler.extract_closed false",
        "import Lean\nset_option backward.synthInstance.canonInstances false",
        "import Lean\nset_option pp false",
    ],
)
def test_header_shape_allows_only_elaboration_limit_and_display_options(header):
    assert header_problem(header) == "set_option_not_allowed"


@pytest.mark.parametrize(
    "header",
    ["import Lean\nopen Nat /-", "import Lean\nopen Nat /- a -/ /-", 'import Lean\n"'],
)
def test_header_shape_rejects_a_header_ending_in_a_comment_or_literal(header):
    assert header_problem(header) == "unterminated"


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
    with pytest.raises(HarnessError) as raised:  # the refusal names the options allowed
        await session.elaborate_statement(
            'import Lean\nset_option trace.profiler.output "p"', "n", ": 1 = 1", operation_id="o"
        )
    assert "set_option_not_allowed" in raised.value.message
    assert "maxHeartbeats" in raised.value.remediation and "pp." in raised.value.remediation
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


def test_statement_check_imports_only_the_modules_it_uses():
    """Lean maps an .olean from its file only on its first load in a process, so every module
    both the checker and the source import is read again onto the checker's heap. With
    ``import Lean`` that was all of Lean (1.6 GB) for an ``import Lean`` source, which the
    2 GiB workbench OOM-killed; these modules' closure is a quarter of it."""
    checker = resources.files("physharness.formal_tools").joinpath("statement_check.lean")
    lines = checker.read_text("utf-8").splitlines()
    assert [line.split()[1] for line in lines if line.startswith("import ")] == [
        "Lean.CoreM",
        "Lean.Data.Json",
        "Lean.Replay",
        "Lean.Util.CollectAxioms",
        "Lean.Util.FoldConsts",
        "Lean.Util.Path",
    ]


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
    # A VM restore dropped the uploaded checker: the run reports the files missing, they are
    # uploaded, and the check runs again.
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


async def test_statement_check_runs_from_workspace_paths_without_staging():
    ok = json.dumps({"ok": True, "axioms": [], "reason": None})
    tools = CheckTools((ok, 0))
    assert (await _verify(tools))["ok"] is True
    [script] = [text for kind, text in tools.calls if kind == "run"]
    assert "/tmp" not in script and "mkdir" not in script and "mv -f" not in script
    assert ".physharness/statement_check.py --timeout" in script
    assert "--checker .physharness/statement_check.lean" in script


async def test_statement_check_succeeds_when_tmp_is_read_only(lean_env):  # noqa: F811
    """The S1 bug: /tmp is part of the workbench's read-only root, so staging there failed."""
    shim = lean_env.root / "bin"
    (shim / "lean.py").write_text(FAKE_LEAN)
    (shim / "lake").write_text(
        f"#!/bin/sh\nshift 3\nexec {shlex.quote(sys.executable)} "
        f'{shlex.quote(str(shim / "lean.py"))} "$@"\n'
    )
    (shim / "lake").chmod(0o755)
    blocker = lean_env.root / "not-a-directory"
    blocker.write_text("")
    lean_env.runtime = blocker / "rt"  # mkdir -p under a regular file fails, like /tmp there
    verdict = await _verify(FakeWorkspaceTools(lean_env, background=False))
    assert verdict["ok"] is True and verdict["axioms"] == ["propext"]


async def test_statement_check_unavailable_is_logged_at_error(caplog):
    with caplog.at_level(logging.ERROR, logger="physharness.orchestration.lean_session"):
        verdict = await _verify(CheckTools(("", 97), ("", 97)))
    assert verdict["reason"] == "statement_check_unavailable"
    [record] = [r for r in caplog.records if r.getMessage() == "statement_check_unavailable"]
    assert record.levelname == "ERROR" and record.error_code == "statement_check_unavailable"


OK_VERDICT = {"ok": True, "reason": None, "axioms": [], "detail": None, "backend": CHECK_BACKEND}
BROKEN = {**OK_VERDICT, "ok": False, "reason": "statement_check_unavailable", "axioms": None}


@pytest.fixture
def self_tests(monkeypatch):
    cache = {}
    monkeypatch.setattr(workspace_tools_module, "_CHECKER_SELF_TESTS", cache)
    return cache


def provisioning_tools(verdict, template_id="image-a"):
    """A WorkspaceTools whose broker provisions instantly and whose checker answers `verdict`."""
    tools = WorkspaceTools.__new__(WorkspaceTools)
    tools.policy = SimpleNamespace(template_id=template_id, timeout_seconds=600, cost_bound_usd=0)
    tools.workspace, tools.cleanup_report, tools.checker_self_test = None, None, True
    provisions, checks = [], []

    async def provision(**kwargs):
        provisions.append(kwargs)
        return {"id": "ws", "execution_id": "vm"}

    async def verify_statement(source, header, name, signature, *, operation_id):
        checks.append((header, name, signature))
        return verdict

    tools.broker = SimpleNamespace(task_id="task", holder="holder", provision=provision)
    tools._lean_session = SimpleNamespace(verify_statement=verify_statement)
    return tools, provisions, checks


async def test_checker_self_test_runs_once_per_image(self_tests):
    first, _, checks = provisioning_tools(OK_VERDICT)
    second, _, later = provisioning_tools(OK_VERDICT)
    await first._ensure()
    await first._ensure()
    await second._ensure()
    assert checks == [("import Lean", "physharness_checker_self_test", ": True")]
    assert later == [] and self_tests == {"image-a": True}


async def test_unavailable_checker_fails_fast_and_logs(self_tests, caplog):
    tools, _, _ = provisioning_tools(BROKEN)
    with caplog.at_level(logging.ERROR), pytest.raises(HarnessError) as error:
        await tools._ensure()
    assert error.value.code == "STATEMENT_CHECK_UNAVAILABLE" and error.value.status == 503
    with pytest.raises(HarnessError):
        await tools._ensure()  # every later use of this workspace fails the same way
    [record] = [r for r in caplog.records if r.getMessage() == "statement_check_self_test_failed"]
    assert record.error_code == "STATEMENT_CHECK_UNAVAILABLE"
    other, _, checks = provisioning_tools(BROKEN)
    with pytest.raises(HarnessError):
        await other._ensure()
    assert checks == []  # the per-image verdict is cached for the process


async def test_failed_self_test_provisions_no_later_workspace(self_tests):
    first, provisions, _ = provisioning_tools(BROKEN)
    with pytest.raises(HarnessError):
        await first._ensure()
    assert len(provisions) == 1
    later, provisions, checks = provisioning_tools(BROKEN)
    with pytest.raises(HarnessError) as error:
        await later._ensure()
    assert error.value.code == "STATEMENT_CHECK_UNAVAILABLE"
    assert provisions == [] and checks == [] and later.workspace is None
    later.checker_self_test = False  # a referee's workspace needs no checker
    await later._ensure()
    other, provisions, _ = provisioning_tools(OK_VERDICT, template_id="image-b")
    await other._ensure()  # each image is judged on its own
    assert len(provisions) == 1 and self_tests == {"image-a": False, "image-b": True}


async def test_checker_self_test_timeout_is_retried_and_off_by_default(self_tests):
    timed_out = {**OK_VERDICT, "ok": False, "reason": "check_timeout", "axioms": None}
    tools, _, checks = provisioning_tools(timed_out)
    await tools._ensure()  # provisions without raising; judged nothing
    assert checks == [("import Lean", "physharness_checker_self_test", ": True")]
    assert self_tests == {}
    tools.checker_self_test = False
    checks.clear()
    tools.workspace = None
    await tools._ensure()
    assert checks == []


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
