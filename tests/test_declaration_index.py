"""find_declaration: the guest header index and the host tool around it (S1 audit #19)."""

import ast
import importlib.util
import json
import subprocess
import sys
from importlib import resources

import pytest

from physharness.errors import HarnessError
from physharness.execution.types import GUEST_PYTHON
from physharness.orchestration import workspace_tools
from physharness.orchestration.workspace_tools import WorkspacePolicy, WorkspaceTools

SCRIPT = resources.files("physharness.formal_tools") / "declaration_index.py"
DOT = (
    "namespace Matrix\n\ntheorem dotProduct_comm (v w : Fin 2 → ℕ) :\n"
    "    dotProduct v w = dotProduct w v := by\n  simp\n\nend Matrix\n\n"
    "def dotProduct (v w : Fin 2 → ℕ) : ℕ := 0\n"
)
SCOPES = """\
namespace A.B

@[simp] protected theorem one : 1 = 1 := rfl

section Inner
private lemma two {α : Type} (a : α) :
    a = a := rfl
end Inner

theorem _root_.three : True := trivial

noncomputable section
structure Pair (α : Type) where
  fst : α
inductive Tree
  | leaf
axiom four : False

theorem five : True :=
  trivial
end
end A.B

instance six : Inhabited Nat := ⟨0⟩
instance : Inhabited Bool := ⟨true⟩
"""


def run(*args):
    done = subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60, check=True
    )
    return json.loads(done.stdout)


def refused(*args):
    done = subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60
    )
    return done.returncode, json.loads(done.stdout)


def library(tmp_path, files):
    root = tmp_path / "mathlib"
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    return root


def test_index_ranks_names_suggests_and_reads_bounded(tmp_path):
    root = tmp_path / "mathlib"
    (root / "Mathlib" / "Data").mkdir(parents=True)
    (root / "Mathlib" / "Data" / "Dot.lean").write_text(DOT)
    index = tmp_path / "work" / ".cache" / "decls.tsv"
    query = ("query", "--index", str(index), "--root", str(root), "--mode", "name", "--")
    found = run(*query, "dotProduct")
    assert found["rows"][0] == "dotProduct (v w : Fin 2 → ℕ) : ℕ — mathlib/Mathlib/Data/Dot.lean:9"
    assert found["exact"] is True and found["top"] == {
        "name": "dotProduct",
        "module": "Mathlib.Data.Dot",
    }
    assert index.exists() and found["indexed"] == 2
    renamed = run(*query, "Matrix.dotProduct")
    assert renamed["exact"] is False and "dotProduct" in renamed["did_you_mean"]
    assert run(*query, "dotProduct_comm")["rows"][0].startswith("Matrix.dotProduct_comm (v w")
    read = run("read", "--root", str(root), "mathlib/Mathlib/Data/Dot.lean", "3")
    assert read["start_line"] == 1 and "dotProduct_comm" in read["text"]
    assert len(read["text"].encode()) <= 4000


def test_type_mode_ranks_signatures_by_shared_tokens(tmp_path):
    root = library(tmp_path, {"Mathlib/Data/Dot.lean": DOT})
    index = tmp_path / "decls.tsv"
    found = run(
        "query",
        "--index",
        str(index),
        "--root",
        str(root),
        "--mode",
        "type",
        "--",
        "dotProduct w v",
    )
    assert [row.split(" (")[0] for row in found["rows"]] == [
        "Matrix.dotProduct_comm",
        "dotProduct",
    ]
    assert found["exact"] is False and found["top"]["name"] == "Matrix.dotProduct_comm"
    unmatched = run(
        "query", "--index", str(index), "--root", str(root), "--mode", "type", "--", "Real"
    )
    assert unmatched["rows"] == [] and unmatched["top"] is None


def test_index_qualifies_names_by_namespace_and_cuts_signatures(tmp_path):
    long = "theorem long " + " ".join(f"(h{i} : {i} = {i})" for i in range(60)) + " : True"
    root = library(tmp_path, {"Mathlib/Scopes.lean": SCOPES, "Mathlib/Long.lean": long + "\n"})
    (root / ".lake" / "Hidden.lean").parent.mkdir()
    (root / ".lake" / "Hidden.lean").write_text("theorem hidden : True := trivial\n")
    index = tmp_path / "decls.tsv"
    run("query", "--index", str(index), "--root", str(root), "--mode", "name", "--", "x")
    rows = {
        name: (signature, path, int(line), module)
        for name, signature, path, line, module in (
            row.split("\t") for row in index.read_text().splitlines()
        )
    }
    assert rows["A.B.one"] == (": 1 = 1", "mathlib/Mathlib/Scopes.lean", 3, "Mathlib.Scopes")
    assert rows["A.B.two"][0] == "{α : Type} (a : α) : a = a"
    assert rows["three"][0] == ": True"
    assert rows["A.B.Pair"][0] == "(α : Type)"
    assert rows["A.B.Tree"][0] == ""
    assert rows["A.B.four"][0] == ": False"
    assert rows["A.B.five"][0] == ": True"
    assert rows["six"][0] == ": Inhabited Nat"
    assert "hidden" not in rows and len(rows["long"][0]) == 300
    assert set(rows) == {"A.B.one", "A.B.two", "three", "A.B.Pair", "A.B.Tree"} | {
        "A.B.four",
        "A.B.five",
        "six",
        "long",
    }


def test_index_past_the_byte_cap_is_refused_and_never_written(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("declaration_index", str(SCRIPT))
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.MAX_INDEX_BYTES == 64 * 1024 * 1024
    root = library(tmp_path, {"Mathlib/Data/Dot.lean": DOT})
    index = tmp_path / "cache" / "decls.tsv"
    first = len(next(script._rows([str(root)])).encode())  # the second row does not fit
    monkeypatch.setattr(script, "MAX_INDEX_BYTES", first + 1)
    argv = ["query", "--index", str(index), "--root", str(root), "--mode", "name", "--", "dot"]
    with pytest.raises(SystemExit) as exit_:
        script.main(argv)
    assert exit_.value.code == 3
    assert json.loads(capsys.readouterr().out) == {"error": "index_too_large", "bytes": first}
    assert list(index.parent.iterdir()) == []


@pytest.mark.parametrize(
    "path",
    [
        "mathlib/../mathlib/Mathlib/Data/Dot.lean",
        "physlib/Mathlib/Data/Dot.lean",
        "mathlib/Mathlib/Data/Dot.txt",
        "/etc/Dot.lean",
    ],
)
def test_read_refuses_paths_outside_the_roots(tmp_path, path):
    root = library(tmp_path, {"Mathlib/Data/Dot.lean": DOT})
    assert refused("read", "--root", str(root), path, "1") == (2, {"error": "unsafe_path"})


def test_read_cuts_the_window_on_a_character_boundary(tmp_path):
    wide = "".join(f"{'ℕ' * 99}\n" for _ in range(200))
    root = library(tmp_path, {"Mathlib/Wide.lean": wide, "Mathlib/Data/Dot.lean": DOT})
    read = run("read", "--root", str(root), "mathlib/Mathlib/Wide.lean", "100")
    assert (read["start_line"], read["truncated"]) == (60, True)
    data = read["text"].encode()
    assert 3990 < len(data) <= 4000 and "�" not in read["text"]
    assert read["end_line"] == 60 + read["text"].count("\n")
    short = run("read", "--root", str(root), "mathlib/Mathlib/Data/Dot.lean", "9")
    assert (short["start_line"], short["end_line"], short["truncated"]) == (1, 9, False)
    assert short["text"] == DOT
    beyond = refused("read", "--root", str(root), "mathlib/Mathlib/Data/Dot.lean", "60")
    assert beyond == (2, {"error": "line_out_of_range", "lines": 9})


def test_script_is_standard_library_and_fits_one_upload():
    source = SCRIPT.read_bytes()
    assert len(source) < 32 * 1024
    modules = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module.split(".")[0])
    assert modules and modules <= sys.stdlib_module_names


# Host side --------------------------------------------------------------------------------


class LocalBroker:
    """Runs the uploaded guest script over temporary stand-ins for /opt/sources and /work."""

    def __init__(self, root):
        self.root, self.work = root, root / "work"
        self.work.mkdir()
        self.uploads, self.runs = [], []
        self.canned = None

    async def upload_file(self, workspace_id, *, expected_execution_id, path, data, operation_id):
        self.uploads.append(path)
        (self.work / path).parent.mkdir(parents=True, exist_ok=True)
        (self.work / path).write_bytes(data)
        return {"path": path}

    async def run(self, workspace_id, *, expected_execution_id, request):
        assert request.argv[: len(GUEST_PYTHON)] == list(GUEST_PYTHON) and request.cwd == "."
        self.runs.append((list(request.argv), request.timeout_seconds))
        if self.canned is not None:
            return self.canned
        args = [arg.replace("/opt/sources", str(self.root)) for arg in request.argv[2:]]
        done = subprocess.run(
            [sys.executable, "-I", *args],
            cwd=self.work,
            capture_output=True,
            text=True,
            timeout=request.timeout_seconds,
            check=False,
        )
        return {"exit_code": done.returncode, "stdout": done.stdout, "stderr": done.stderr}


@pytest.fixture
def declarations(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_tools, "_DECLARATION_QUERIES", {})
    library(tmp_path, {"Mathlib/Data/Dot.lean": DOT})
    (tmp_path / "physlib").mkdir()
    broker = LocalBroker(tmp_path)
    tools = WorkspaceTools.__new__(WorkspaceTools)
    tools.broker = broker
    tools.workspace = {"id": "test-workspace", "execution_id": "test-execution"}
    tools.policy = WorkspacePolicy(
        template_id="test-template",
        environment_digest="b" * 64,
        qualification_report_sha256="c" * 64,
        timeout_seconds=600,
        cost_bound_usd="0",
        cost_source="local_no_external_invoice",
    )
    return tools, broker


def find(tools, **arguments):
    return tools.find_declaration(
        {"query": None, "mode": "name", "path": None, "line": None, "verify": False, **arguments},
        "find",
    )


async def test_find_declaration_uploads_once_caches_queries_and_reads(declarations):
    tools, broker = declarations
    found = await find(tools, query="dotProduct")
    assert found["rows"][0] == "dotProduct (v w : Fin 2 → ℕ) : ℕ — mathlib/Mathlib/Data/Dot.lean:9"
    assert found["exact"] is True and found["indexed"] == 2
    assert found["environment_digest"] == "b" * 64
    assert found["mechanism"] == "declaration_header_index"
    assert broker.uploads == [".physharness/declaration_index.py"]
    [(argv, timeout)] = broker.runs
    assert timeout == 120
    assert argv[2:] == [
        ".physharness/declaration_index.py",
        "query",
        "--index",
        ".cache/physharness/decls-bbbbbbbbbbbbbbbb.tsv",
        "--root",
        "/opt/sources/physlib",
        "--root",
        "/opt/sources/mathlib",
        "--mode",
        "name",
        "--",
        "dotProduct",
    ]
    assert (broker.work / ".cache/physharness/decls-bbbbbbbbbbbbbbbb.tsv").exists()
    # A repeated query is answered from the host cache; another mode runs the script.
    assert await find(tools, query="dotProduct") == found and len(broker.runs) == 1
    typed = await find(tools, query="dotProduct w v", mode="type")
    assert typed["top"]["name"] == "Matrix.dotProduct_comm" and len(broker.runs) == 2
    read = await find(tools, path="mathlib/Mathlib/Data/Dot.lean", line=9)
    assert (read["path"], read["start_line"], read["end_line"]) == (
        "mathlib/Mathlib/Data/Dot.lean",
        1,
        9,
    )
    assert "def dotProduct" in read["text"] and read["truncated"] is False
    assert read["mechanism"] == "declaration_header_index"
    assert broker.uploads == [".physharness/declaration_index.py"]  # uploaded once


async def test_find_declaration_reports_index_failure_uncached_with_rg_remediation(declarations):
    tools, broker = declarations
    failure = {"exit_code": 3, "stdout": '{"error": "index_too_large", "bytes": 67108000}'}
    broker.canned = {**failure, "stderr": ""}
    for _ in range(2):
        result = await find(tools, query="dotProduct")
        assert result["rows"] == [] and result["reason_code"] == "declaration_index_failed"
        assert result["diagnostics"] == broker.canned
        assert "rg <query> /opt/sources/mathlib /opt/sources/physlib" in result["remediation"]
        assert result["remediation"].startswith("Past the header-index cap")
    assert len(broker.runs) == 2  # a failure is never cached
    assert broker.uploads == [".physharness/declaration_index.py"] * 2  # nor trusts the upload
    broker.canned = {"exit_code": 1, "stdout": "", "stderr": "Traceback"}
    other = await find(tools, query="dotProduct")
    assert other["reason_code"] == "declaration_index_failed"
    assert "rg <query>" in other["remediation"]
    broker.canned = {"exit_code": 1, "stdout": "", "stderr": "missing"}
    unreadable = await find(tools, path="mathlib/Mathlib/Data/Dot.lean", line=1)
    assert unreadable["reason_code"] == "declaration_read_failed"
    assert unreadable["diagnostics"] == broker.canned


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"query": "dotProduct", "path": "mathlib/Mathlib/Data/Dot.lean", "line": 1},
        {"query": "dotProduct", "line": 1},
        {"path": "mathlib/Mathlib/Data/Dot.lean"},
        {"line": 3},
        {"query": ""},
        {"query": "x" * 201},
        {"query": "dotProduct", "mode": "semantic"},
        {"path": "mathlib/Mathlib/Data/Dot.lean", "line": 0},
        {"path": "mathlib/Mathlib/Data/Dot.lean", "line": True},
    ],
)
async def test_find_declaration_takes_a_query_or_a_path_with_a_line(declarations, arguments):
    tools, broker = declarations
    with pytest.raises(HarnessError) as error:
        await find(tools, **arguments)
    assert (error.value.code, error.value.status) == ("INVALID_QUERY", 422)
    assert broker.runs == [] and broker.uploads == []


@pytest.mark.parametrize("path", ["/opt/sources/mathlib/A.lean", "mathlib/../physlib/A.lean"])
async def test_find_declaration_refuses_unsafe_read_paths(declarations, path):
    tools, broker = declarations
    with pytest.raises(HarnessError) as error:
        await find(tools, path=path, line=1)
    assert error.value.code == "UNSAFE_PATH" and broker.runs == []


async def test_find_declaration_verifies_only_an_exact_top_row(declarations, monkeypatch):
    tools, broker = declarations
    checked = []

    async def lookup(arguments, operation_id):
        checked.append((arguments, operation_id))
        return {"reason_code": None, "diagnostics": {"stdout": "dotProduct : ℕ" + "x" * 3000}}

    monkeypatch.setattr(tools, "lookup_library_declaration", lookup)
    verified = await find(tools, query="dotProduct", verify=True)
    assert checked == [({"name": "dotProduct", "imports": ["Mathlib.Data.Dot"]}, "find:verify")]
    assert verified["verified"]["name"] == "dotProduct" and verified["verified"]["ok"] is True
    assert verified["verified"]["output"].startswith("dotProduct : ℕ")
    assert len(verified["verified"]["output"]) == 2000
    # The cached rows carry no verification; an inexact best row is never checked.
    assert "verified" not in await find(tools, query="dotProduct")
    assert "verified" not in await find(tools, query="Matrix.dotProduct", verify=True)
    assert len(checked) == 1


async def test_find_declaration_reports_an_unverifiable_name(declarations, monkeypatch):
    tools, broker = declarations
    (broker.root / "mathlib/Mathlib/Prime.lean").write_text("theorem add' : True := trivial\n")
    result = await find(tools, query="add'", verify=True)
    assert result["exact"] is True
    assert result["verified"]["ok"] is False and result["verified"]["name"] == "add'"
    assert "qualified Lean declaration name" in result["verified"]["output"]
