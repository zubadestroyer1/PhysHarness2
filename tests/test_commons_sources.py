"""The lemma store: node modules and ranked lean_source publication (S1 audit #12)."""

import pytest
from commons_helpers import society_lab
from test_commons_review import referee

from physharness import commons
from physharness.commons import _lean_digest
from physharness.commons_models import NodeCreate
from physharness.commons_sources import (
    MAX_COMMONS_MODULES,
    Expansion,
    Module,
    inline_commons,
    module_prefix,
    node_module,
    remap,
    scope_closers,
    source_state,
    split_imports,
)
from physharness.domain import ArtifactCreate, BranchCreate, Principal
from physharness.errors import HarnessError

LEAN = {
    "lean_header": "import Mathlib",
    "lean_name": "trace_add",
    "lean_statement": ": (1 : Nat) + 1 = 2",
}
ELABORATED = {"ok": True, "backend": "lean-repl", "diagnostics_sha256": "e" * 64}


def publish(service, node_id, agent, rank, key, content="theorem x : True := trivial", **record):
    artifact = service.create_artifact(
        ArtifactCreate(
            experiment_id=agent.experiment_id,
            branch_id=agent.branch_id,
            kind="lean_source",
            content=content,
        ),
        agent,
        key + ":a",
    )
    return service.record_lean_source(
        node_id,
        artifact["id"],
        {
            "rank": rank,
            "bytes": len(content),
            "statement_check": None,
            "lean_statement_sha256": None,
            "imports": [],
            **record,
        },
        agent,
        key,
    )


def lemma(service, exp, agent, title, key, **fields):
    return service.create_node(
        exp["id"],
        NodeCreate(node_type="lemma", title=title, statement=f"{title}.", **fields),
        agent,
        key,
    )


def third_branch(service, author, exp):
    branch = service.create_branch(
        exp["id"], BranchCreate(title="gamma", objective="gamma"), author, "gamma"
    )
    return Principal(
        id="society-worker-c",
        role="agent",
        project_id=author.project_id,
        experiment_id=exp["id"],
        branch_id=branch["id"],
    )


def test_rank_rule_replaces_upward_only(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(
        exp["id"], NodeCreate(node_type="lemma", title="L", statement="L."), alpha, "n"
    )
    assert publish(service, node["id"], beta, "partial", "p1")["recorded"] is True
    assert publish(service, node["id"], beta, "complete", "c1")["replaced"] is True
    lower = publish(service, node["id"], alpha, "partial", "p2")
    assert lower == {
        "recorded": False,
        "module": node["lean_module"],
        "reason": "lower_rank",
        "rank": "complete",
    }
    goal = service.query_nodes(exp["id"], alpha, node_type="goal")["items"][0]
    assert publish(service, goal["id"], alpha, "complete", "g")["reason"] == "goal_node"


def test_modules_are_unique_even_when_ids_share_eight_hex(lab, monkeypatch):
    service, _, exp, _, (alpha, _) = society_lab(lab)
    ids = iter(["abcdef12-1111-4000-8000-000000000001", "abcdef12-2222-4000-8000-000000000002"])
    monkeypatch.setattr(commons, "new_id", lambda: next(ids))
    first = service.create_node(
        exp["id"], NodeCreate(node_type="lemma", title="A", statement="A."), alpha, "a"
    )
    second = service.create_node(
        exp["id"], NodeCreate(node_type="lemma", title="B", statement="B."), alpha, "b"
    )
    assert first["lean_module"] == "Commons.Nabcdef12"
    assert second["lean_module"] == "Commons.Nabcdef122222"
    # Each module resolves to its own node, through the id-prefix candidates.
    with service.db.sessions() as session:
        for node in (first, second):
            found = service._module_node(session, node["lean_module"], alpha, exp["id"])
            assert found.id == node["id"]
        with pytest.raises(HarnessError) as error:
            service._module_node(session, "Commons.Nabcdef129999", alpha, exp["id"])
    assert (error.value.code, error.value.status) == ("COMMONS_MODULE_NOT_FOUND", 404)
    assert error.value.details == {"module": "Commons.Nabcdef129999"}


def test_module_names_and_their_id_prefixes():
    assert node_module({"id": "abcdef12-3456-4000-8000-000000000001"}) == "Commons.Nabcdef12"
    assert node_module({"id": "x", "lean_module": "Commons.Nabcdef123456"}) == (
        "Commons.Nabcdef123456"
    )
    assert module_prefix("Commons.Nabcdef12") == "abcdef12"
    assert module_prefix("Commons.Nabcdef123456") == "abcdef12-3456"
    assert module_prefix("Commons.Nabcdef1234564000") == "abcdef12-3456-4000"
    for name in ("Commons.Nabcdef1", "Commons.Nabcdef12345", "Commons.NABCDEF12", "Mathlib"):
        assert module_prefix(name) is None


def test_verified_source_is_replaced_only_by_its_publisher_or_the_author(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = lemma(service, exp, alpha, "Trace", "n", **LEAN)
    digest = _lean_digest(*LEAN.values())
    gamma = third_branch(service, author, exp)
    assert publish(service, node["id"], beta, "verified", "b1", lean_statement_sha256=digest)[
        "recorded"
    ]
    refused = publish(service, node["id"], gamma, "verified", "g1", lean_statement_sha256=digest)
    assert refused == {
        "recorded": False,
        "module": node["lean_module"],
        "reason": "lower_rank",
        "rank": "verified",
    }
    for agent, key in ((beta, "b2"), (alpha, "a1")):
        replaced = publish(
            service, node["id"], agent, "verified", key, lean_statement_sha256=digest
        )
        assert replaced["recorded"] is True and replaced["replaced"] is True
    stored = service.read_node(node["id"], alpha)["node"]["lean_source"]
    assert stored["branch_id"] == alpha.branch_id and stored["rank"] == "verified"


def test_publication_refused_when_the_statement_changed(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = lemma(service, exp, alpha, "Trace", "n", **LEAN)
    old = _lean_digest(*LEAN.values())
    assert publish(service, node["id"], beta, "verified", "v", lean_statement_sha256=old)[
        "recorded"
    ]
    changed = {**LEAN, "lean_statement": ": (2 : Nat) + 2 = 4"}
    service.set_lean_statement(node["id"], *changed.values(), ELABORATED, alpha, "restate")
    stale = publish(service, node["id"], beta, "verified", "stale", lean_statement_sha256=old)
    assert stale == {
        "recorded": False,
        "module": node["lean_module"],
        "reason": "statement_changed",
    }
    # A verified source of the older statement now counts as complete: another branch's
    # complete source of the current statement replaces it.
    assert source_state(service.read_node(node["id"], alpha)["node"]) == "complete"
    gamma = third_branch(service, author, exp)
    current = _lean_digest(*changed.values())
    fresh = publish(service, node["id"], gamma, "complete", "c", lean_statement_sha256=current)
    assert fresh["recorded"] is True and fresh["replaced"] is True


def test_import_edges_are_depends_on_and_skip_cycles(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    first = lemma(service, exp, alpha, "First", "first")
    second = lemma(service, exp, alpha, "Second", "second")

    def imports(*nodes):
        return [{"module": n["lean_module"], "node_id": n["id"], "sha256": "0" * 64} for n in nodes]

    assert publish(service, first["id"], beta, "complete", "p1", imports=imports(second))[
        "recorded"
    ]
    edges = service.read_node(first["id"], alpha)["edges_out"]
    assert [(e["relation"], e["node_id"]) for e in edges] == [("depends_on", second["id"])]
    # An import edge that would close a cycle with a linked depends_on edge is skipped.
    third = lemma(service, exp, alpha, "Third", "third")
    service.link_nodes(exp["id"], third["id"], "depends_on", first["id"], alpha, "link")
    closing = publish(service, second["id"], beta, "complete", "p2", imports=imports(third))
    assert closing["recorded"] is True
    assert service.read_node(second["id"], alpha)["edges_out"] == []
    stored = service.read_node(second["id"], alpha)["node"]["lean_source"]
    assert [entry["node_id"] for entry in stored["imports"]] == [third["id"]]


def test_a_source_whose_stored_imports_reach_its_node_is_refused(lab):
    """The stored import graph is re-walked under the experiment lock, so two publications
    racing past lean_check's own-module check cannot store an import cycle."""
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    a, b, c = (lemma(service, exp, alpha, title, title) for title in ("A", "B", "C"))

    def imports(*nodes):
        return [{"module": n["lean_module"], "node_id": n["id"], "sha256": "0" * 64} for n in nodes]

    assert publish(service, b["id"], beta, "complete", "b", imports=imports(a))["recorded"]
    assert publish(service, c["id"], beta, "complete", "c", imports=imports(b))["recorded"]
    refused = {"recorded": False, "module": a["lean_module"], "reason": "imports_own_module"}
    # A -> B -> A, A -> C -> B -> A, and A -> A.
    for key, targets in (("ab", (b,)), ("ac", (c,)), ("aa", (a,))):
        assert publish(service, a["id"], beta, "complete", key, imports=imports(*targets)) == (
            refused
        )
    assert service.read_node(a["id"], alpha)["node"]["lean_source"] is None
    # An acyclic source still publishes.
    assert publish(service, a["id"], beta, "complete", "free")["recorded"] is True


def test_the_goal_lists_no_module(lab):
    """Nothing imports the goal, so neither a page nor the frontier names a module for it."""
    service, _, exp, _, (alpha, _) = society_lab(lab)
    node = lemma(service, exp, alpha, "L", "l")
    pages = (
        service.query_nodes(exp["id"], alpha)["items"],
        service.query_nodes(exp["id"], alpha, frontier=True)["items"],
    )
    for items in pages:
        modules = {item["node_type"]: item["module"] for item in items}
        assert modules == {"goal": None, "lemma": node["lean_module"]}
    goal = next(item for item in pages[0] if item["node_type"] == "goal")
    with pytest.raises(HarnessError) as error:
        service.commons_module(goal["id"], alpha)
    assert (error.value.code, error.value.status) == ("COMMONS_MODULE_NOT_FOUND", 404)


def test_query_matches_lean_name_and_filters_by_source(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    compiled = lemma(service, exp, alpha, "Compiled", "compiled", **LEAN)
    stub = lemma(service, exp, alpha, "Stub", "stub", **{**LEAN, "lean_name": "stub_lemma"})
    service.set_lean_statement(
        stub["id"],
        LEAN["lean_header"],
        "stub_lemma",
        LEAN["lean_statement"],
        ELABORATED,
        alpha,
        "e",
    )
    plain = lemma(service, exp, alpha, "Plain", "plain")
    digest = _lean_digest(*LEAN.values())
    publish(service, compiled["id"], beta, "complete", "p", lean_statement_sha256=digest)

    def found(**query):
        return [item["id"] for item in service.query_nodes(exp["id"], beta, **query)["items"]]

    assert found(text="trace_add") == [compiled["id"]]
    assert found(text=compiled["lean_module"]) == [compiled["id"]]
    assert found(source="complete") == [compiled["id"]]
    assert found(source="stub") == [stub["id"]]
    assert plain["id"] in found(source="none") and compiled["id"] not in found(source="none")
    assert found(source="verified") == [] and found(source="partial") == []
    item = service.query_nodes(exp["id"], beta, text="trace_add")["items"][0]
    assert (item["module"], item["source"]) == (compiled["lean_module"], "complete")
    with pytest.raises(HarnessError) as error:
        service.query_nodes(exp["id"], beta, source="sorry")
    assert error.value.code == "INVALID_QUERY"


def test_publication_is_scoped_and_announced_on_the_node(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = lemma(service, exp, alpha, "Trace", "n")
    theirs = service.create_artifact(
        ArtifactCreate(experiment_id=exp["id"], kind="lean_source", content="x"), alpha, "theirs"
    )
    notes = service.create_artifact(
        ArtifactCreate(experiment_id=exp["id"], kind="notes", content="x"), beta, "notes"
    )
    record = {
        "rank": "complete",
        "bytes": 1,
        "statement_check": None,
        "lean_statement_sha256": None,
        "imports": [],
    }
    for artifact, key in ((theirs, "theirs"), (notes, "notes")):
        with pytest.raises(HarnessError) as error:
            service.record_lean_source(node["id"], artifact["id"], record, beta, key + ":p")
        assert (error.value.code, error.value.status) == ("SOURCE_ARTIFACT_SCOPE", 403)
    published = publish(service, node["id"], beta, "complete", "ok")
    stored = service.read_node(node["id"], alpha)["node"]["lean_source"]
    assert published == {
        "recorded": True,
        "module": node["lean_module"],
        "rank": "complete",
        "replaced": False,
    }
    assert stored["branch_id"] == beta.branch_id and stored["task_id"] is None
    assert set(stored) == {
        "artifact_id",
        "sha256",
        "bytes",
        "branch_id",
        "task_id",
        "rank",
        "statement_check",
        "lean_statement_sha256",
        "imports",
        "recorded_at",
    }
    (event,) = [
        e for e in service.events(author, limit=1000) if e["kind"] == "commons.source_published"
    ]
    assert event["aggregate_id"] == node["id"]
    assert event["payload"] == {
        "experiment_id": exp["id"],
        "node_id": node["id"],
        "branch_id": beta.branch_id,
        "artifact_id": stored["artifact_id"],
        "sha256": stored["sha256"],
        "rank": "complete",
        "replaced": False,
    }
    service.abandon_node(node["id"], "Moot.", alpha, "abandon")
    closed = publish(service, node["id"], beta, "verified", "late")
    assert closed == {"recorded": False, "module": node["lean_module"], "reason": "node_closed"}


def test_a_referee_may_read_the_nodes_published_source(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = lemma(service, exp, alpha, "Trace", "n")
    publish(service, node["id"], beta, "complete", "p")
    source = service.read_node(node["id"], alpha)["node"]["lean_source"]
    scratch = service.create_artifact(
        ArtifactCreate(experiment_id=exp["id"], kind="lean_source", content="y"), beta, "scratch"
    )
    ref = referee(service.request_review(node["id"], "informal", alpha, "review"), exp)
    assert service.referee_may_read_artifact(node["id"], source["artifact_id"], ref) is True
    assert service.referee_may_read_artifact(node["id"], scratch["id"], ref) is False


# Commons imports: the inliner (S1 audit #12) ---------------------------------------------

A, B = "Commons.Naaaaaaaa", "Commons.Nbbbbbbbb"
PROOF = "import Mathlib\n\ntheorem trace_add : (1 : Nat) + 1 = 2 := rfl\n"


def module(name, source, rank="verified"):
    stub = rank == "stub"
    return Module(
        name,
        name[-8:] + "-node",
        source,
        rank,
        None if stub else "s" * 64,
        None if stub else "art",
        "b",
    )


def resolver(*modules):
    table = {m.name: m for m in modules}

    def resolve(name):
        if name not in table:
            raise HarnessError("COMMONS_MODULE_NOT_FOUND", name, status=404)
        return table[name]

    return resolve


def test_source_without_commons_imports_is_returned_unchanged():
    text = "import Mathlib\n\ntheorem t : True := trivial\n"
    assert inline_commons(text, resolver(), max_bytes=30_000) == Expansion(text)
    # A module name outside an import line is not an import.
    mentioned = f"import Mathlib\n-- see {A}\ntheorem t : True := trivial\n"
    assert inline_commons(mentioned, resolver(), max_bytes=30_000) == Expansion(mentioned)


def test_imports_are_hoisted_and_modules_ordered_by_dependency():
    a = module(A, "import Mathlib.Data.Nat.Basic\n\ntheorem a : 1 = 1 := rfl\n")
    b = module(B, f"import Mathlib\nimport {A}\n\ntheorem b : 1 = 1 := a\n")
    flat = inline_commons(
        f"import {B}\nimport Mathlib\nopen Nat\n\ntheorem c : 1 = 1 := b\n",
        resolver(a, b),
        max_bytes=30_000,
    )
    lines = flat.source.split("\n")
    assert lines[:2] == ["import Mathlib", "import Mathlib.Data.Nat.Basic"]
    assert [m.name for m in flat.modules] == [A, B] and "import Commons" not in flat.source
    assert (
        flat.source.index("theorem a")
        < flat.source.index("theorem b")
        < flat.source.index("theorem c")
    )
    caller = remap(
        {"messages": [{"line": lines.index("theorem c : 1 = 1 := b") + 1}], "holes": []}, flat
    )
    assert caller["messages"][0]["line"] == 5


def test_remap_names_the_module_or_the_hoisted_imports():
    a = module(A, "import Mathlib\n\ntheorem a : 1 = 1 := sorry\n")
    flat = inline_commons(f"import {A}\n\ntheorem c : 1 = 1 := a\n", resolver(a), max_bytes=30_000)
    lines = flat.source.split("\n")
    inside = lines.index("theorem a : 1 = 1 := sorry") + 1
    result = {
        "ok": True,
        "messages": [{"line": 1, "col": 0, "text": "import"}, {"line": None, "text": "note"}],
        "holes": [{"index": 0, "line": inside, "col": 21}],
    }
    mapped = remap(result, flat)
    assert mapped["holes"] == [
        {"index": 0, "line": None, "col": 21, "module": A, "expanded_line": inside}
    ]
    assert mapped["messages"] == [
        {"line": None, "col": 0, "text": "import", "expanded_line": 1},
        {"line": None, "text": "note"},
    ]
    assert mapped["ok"] is True and remap(result, Expansion("x")) is result


def test_each_module_is_sectioned_and_its_open_namespace_closed():
    a = module(A, "import Mathlib\nopen Nat\nnamespace Foo\n\ntheorem a : 1 = 1 := rfl\n")
    lines = inline_commons(
        f"import {A}\n\ntheorem c : 1 = 1 := Foo.a\n", resolver(a), max_bytes=30_000
    ).source.split("\n")
    start = lines.index("section")
    assert lines[start + 2] == "open Nat" and lines[lines.index("end Foo") + 1] == "end"


def test_cycles_exit_unbalanced_scopes_stubs_and_size_are_handled():
    loop = resolver(module(A, f"import {B}\n"), module(B, f"import {A}\n"))
    with pytest.raises(HarnessError, match="imports itself"):
        inline_commons(f"import {A}\n", loop, max_bytes=30_000)
    for text in ("theorem a : True := trivial\n#exit\n", "theorem a : True := trivial\nend Foo\n"):
        with pytest.raises(HarnessError) as refused:
            inline_commons(f"import {A}\n", resolver(module(A, text)), max_bytes=30_000)
        assert refused.value.code == "COMMONS_MODULE_REFUSED"
    stub = module(A, "import Mathlib\n\ntheorem a : 1 = 1 := sorry\n", rank="stub")
    flat = inline_commons(f"import {A}\n", resolver(stub), max_bytes=30_000)
    assert flat.closure_complete is False and flat.stubs == (stub.node_id,)
    with pytest.raises(HarnessError) as big:
        inline_commons(f"import {A}\n", resolver(stub), max_bytes=10)
    assert big.value.code == "COMMONS_EXPANSION_TOO_LARGE"


def test_shared_and_repeated_imports_are_inlined_once():
    c = "Commons.Ncccccccc"
    shared = module(c, "import Mathlib\n\ntheorem shared : 1 = 1 := rfl\n")
    a = module(A, f"import {c}\n\ntheorem a : 1 = 1 := shared\n")
    b = module(B, f"import {c} {c}\n\ntheorem b : 1 = 1 := shared\n")
    flat = inline_commons(f"import {A} {B}\nimport {A}\n", resolver(shared, a, b), max_bytes=30_000)
    assert [m.name for m in flat.modules] == [c, A, B]
    assert flat.source.count("theorem shared") == 1


def test_expansion_is_bounded_in_modules_and_unresolved_names_fail():
    def chain(name):
        index = int(name[-8:], 16)
        return module(name, f"import Commons.N{index + 1:08x}\n")

    with pytest.raises(HarnessError) as limit:
        inline_commons("import Commons.N00000000\n", chain, max_bytes=10**7)
    assert limit.value.code == "COMMONS_EXPANSION_LIMIT"
    assert str(MAX_COMMONS_MODULES) in limit.value.message
    with pytest.raises(HarnessError) as missing:
        inline_commons(f"import {A}\n", resolver(), max_bytes=30_000)
    assert missing.value.code == "COMMONS_MODULE_NOT_FOUND"


def test_split_imports_reads_past_comments_and_scope_closers_track_nesting():
    text = f"/- Copyright\n   header -/\n-- note\nimport Mathlib {A} -- trailing\n\nopen Nat\n"
    assert split_imports(text) == ([A], ["import Mathlib"], ["open Nat", ""], 5)
    nested = (
        "namespace Foo\nsection Bar\nmutual\ntheorem a : True := trivial\nend\n"
        'noncomputable section\n-- end\ndef s := "end"\n'
    )
    assert scope_closers(A, nested) == ["end", "end Bar", "end Foo"]


def test_only_plain_module_names_make_an_import_line():
    # A line with anything but module names stays in place, where Lean judges it.
    for line in ("import Mathlib set_option pp.all true", "import «Mathlib»", "import"):
        text = f"import {A}\n{line}\ntheorem t : True := trivial\n"
        assert split_imports(text) == ([A], [], [line, "theorem t : True := trivial", ""], 1)
    # An unterminated comment after the imports keeps the caller's own lines.
    text = f"import {A}\n/- open\ntheorem t : False := sorry\n"
    assert split_imports(text)[2:] == (["/- open", "theorem t : False := sorry", ""], 1)


def test_scope_keywords_are_found_after_lean_notation():
    # `ᵀ` is a word character to Python but notation to Lean, which runs the `end`.
    assert scope_closers(A, "section\ndef y := Aᵀend\n") == []
    with pytest.raises(HarnessError) as refused:
        scope_closers(A, "def y := Aᵀend\n")
    assert refused.value.code == "COMMONS_MODULE_REFUSED"


def test_the_exact_size_is_checked_after_the_wrappers_are_added():
    a = module(A, "theorem a : True := trivial\n")
    with pytest.raises(HarnessError) as big:
        inline_commons(f"import {A}\n", resolver(a), max_bytes=40)
    flat = inline_commons(f"import {A}\n", resolver(a), max_bytes=30_000)
    assert big.value.code == "COMMONS_EXPANSION_TOO_LARGE"
    assert big.value.details == {"bytes": len(flat.source.encode()), "limit": 40}


def test_refusals_say_what_to_do():
    loop = resolver(module(A, f"import {B}\n"), module(B, f"import {A}\n"))
    chain = [
        (loop, "republish"),
        (resolver(module(A, "#exit\n")), "republish"),
    ]
    for resolve, fragment in chain:
        with pytest.raises(HarnessError) as refused:
            inline_commons(f"import {A}\n", resolve, max_bytes=30_000)
        assert fragment in refused.value.remediation.lower()


def test_expand_commons_reads_live_sources_stubs_and_flags_stale_ones(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    used = lemma(service, exp, alpha, "Trace", "used", **LEAN)
    digest = _lean_digest(*LEAN.values())
    publish(service, used["id"], beta, "verified", "src", PROOF, lean_statement_sha256=digest)
    source = service.read_node(used["id"], alpha)["node"]["lean_source"]
    stub = lemma(service, exp, alpha, "Stub", "stub")
    service.set_lean_statement(
        stub["id"], "import Mathlib", "stub_lemma", ": 2 = 2", ELABORATED, alpha, "stated"
    )
    caller = f"import {used['lean_module']}\nimport {stub['lean_module']}\n"
    flat = service.expand_commons(exp["id"], caller, alpha, max_bytes=30_000)
    assert flat.modules == (
        Module(
            used["lean_module"],
            used["id"],
            PROOF,
            "verified",
            source["sha256"],
            source["artifact_id"],
            beta.branch_id,
        ),
        Module(
            stub["lean_module"],
            stub["id"],
            "import Mathlib\n\ntheorem stub_lemma : 2 = 2 := sorry\n",
            "stub",
        ),
    )
    assert flat.closure_complete is False and flat.stubs == (stub["id"],)
    # A restated node's source proves an older statement: it imports flagged stale.
    changed = {**LEAN, "lean_statement": ": (2 : Nat) + 2 = 4"}
    service.set_lean_statement(used["id"], *changed.values(), ELABORATED, alpha, "restate")
    (stale,) = service.expand_commons(
        exp["id"], f"import {used['lean_module']}\n", alpha, max_bytes=30_000
    ).modules
    assert (stale.rank, stale.stale, stale.source) == ("complete", True, PROOF)
    # No published source and no elaborated statement: nothing to import.
    bare = lemma(service, exp, alpha, "Bare", "bare")
    with pytest.raises(HarnessError) as missing:
        service.expand_commons(exp["id"], f"import {bare['lean_module']}\n", alpha, max_bytes=99)
    assert (missing.value.code, missing.value.status) == ("COMMONS_MODULE_NOT_FOUND", 404)
    assert "no published source" in missing.value.message
    # Another experiment's agent cannot import this experiment's module.
    _, _, other, _, (outsider, _) = society_lab(lab, prefix="other")
    with pytest.raises(HarnessError) as foreign:
        service.expand_commons(other["id"], caller, outsider, max_bytes=30_000)
    assert foreign.value.code == "COMMONS_MODULE_NOT_FOUND"
