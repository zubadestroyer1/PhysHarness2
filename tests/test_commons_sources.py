"""The lemma store: node modules and ranked lean_source publication (S1 audit #12)."""

import os
import shlex
import subprocess

import pytest
from commons_helpers import publish, society_lab, state_lean
from test_commons_review import referee

from physharness import commons
from physharness.commons import _lean_digest
from physharness.commons_models import NodeCreate
from physharness.commons_sources import (
    MAX_COMMONS_MODULES,
    Closures,
    Expansion,
    Module,
    gate_remedy,
    inline_commons,
    module_prefix,
    node_module,
    refused_command,
    remap,
    scope_closers,
    split_imports,
)
from physharness.domain import ArtifactCreate, BranchCreate, Principal
from physharness.errors import HarnessError
from physharness.orchestration.lean_session import parse_lean_output
from physharness.storage import RecordRow

LEAN = {
    "lean_header": "import Mathlib",
    "lean_name": "trace_add",
    "lean_statement": ": (1 : Nat) + 1 = 2",
}
ELABORATED = {"ok": True, "backend": "lean-repl", "diagnostics_sha256": "e" * 64}


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
    # The verified source of the older statement proves nothing of the current one: it reads
    # stale and counts as no source, so another branch's source of the current statement
    # replaces it.
    assert service.read_node(node["id"], alpha)["node"]["source"] == "stale"
    listed = service.query_nodes(exp["id"], alpha, source="stale")["items"]
    assert [item["id"] for item in listed] == [node["id"]]
    gamma = third_branch(service, author, exp)
    current = _lean_digest(*changed.values())
    fresh = publish(service, node["id"], gamma, "complete", "c", lean_statement_sha256=current)
    assert fresh["recorded"] is True and fresh["replaced"] is True


def test_any_source_of_the_current_statement_replaces_a_stale_one(lab):
    """After a statement change the old source proves nothing: a partial of the new
    statement replaces it, and a stale verified source keeps no publisher lock."""
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = lemma(service, exp, alpha, "Trace", "n", **LEAN)
    old = _lean_digest(*LEAN.values())
    assert publish(service, node["id"], beta, "complete", "c", lean_statement_sha256=old)[
        "recorded"
    ]
    changed = {**LEAN, "lean_statement": ": (2 : Nat) + 2 = 4"}
    service.set_lean_statement(node["id"], *changed.values(), ELABORATED, alpha, "restate")
    current = _lean_digest(*changed.values())
    partial = publish(service, node["id"], beta, "partial", "p", lean_statement_sha256=current)
    assert partial["recorded"] is True and partial["replaced"] is True
    assert service.read_node(node["id"], alpha)["node"]["source"] == "partial"
    # A verified source answers only to its publisher and the author while it is current.
    gamma = third_branch(service, author, exp)
    publish(service, node["id"], beta, "verified", "v", lean_statement_sha256=current)
    locked = publish(service, node["id"], gamma, "partial", "g1", lean_statement_sha256=current)
    assert (locked["recorded"], locked["reason"], locked["rank"]) == (
        False,
        "lower_rank",
        "verified",
    )
    service.set_lean_statement(node["id"], *LEAN.values(), ELABORATED, alpha, "restate-back")
    fresh = publish(service, node["id"], gamma, "partial", "g2", lean_statement_sha256=old)
    assert fresh["recorded"] is True and fresh["replaced"] is True
    # Imports of a stale source keep inlining it, flagged stale (Task 10).
    service.set_lean_statement(node["id"], *changed.values(), ELABORATED, alpha, "restate-2")
    (module,) = service.expand_commons(
        exp["id"], f"import {node['lean_module']}\n", alpha, max_bytes=100_000
    ).modules
    assert (module.rank, module.stale) == ("partial", True)


def test_a_verified_rank_needs_a_passing_statement_check_on_standard_axioms(lab):
    """Whoever calls it, record_lean_source refuses a verified rank the evidence does not
    support: the rank lets a node skip review and locks its statement."""
    service, _, exp, _, (alpha, _) = society_lab(lab)
    node = lemma(service, exp, alpha, "Trace", "n", **LEAN)
    digest = _lean_digest(*LEAN.values())
    for key, check in (
        ("none", None),
        ("failed", {"ok": False, "reason": "statement_mismatch", "axioms": None}),
        ("sorry", {"ok": True, "reason": None, "axioms": ["propext", "sorryAx"]}),
        ("unreported", {"ok": True, "reason": None, "axioms": None}),
    ):
        with pytest.raises(HarnessError) as refused:
            publish(
                service,
                node["id"],
                alpha,
                "verified",
                key,
                lean_statement_sha256=digest,
                statement_check=check,
            )
        assert (refused.value.code, refused.value.status) == ("INVALID_SOURCE_RECORD", 422), key
    assert service.read_node(node["id"], alpha)["node"]["lean_source"] is None
    check = {"ok": True, "reason": None, "axioms": ["propext", "Classical.choice"]}
    published = publish(
        service,
        node["id"],
        alpha,
        "verified",
        "ok",
        lean_statement_sha256=digest,
        statement_check=check,
    )
    assert published["recorded"] is True and published["rank"] == "verified"


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
    # Nor does an import of its module inline anything, even with an elaborated statement
    # that would otherwise make a sorry stub of the target (PR 37 review).
    plant(service, goal["id"], **{**LEAN, "lean_elaborated": True})
    name = node_module(service.get_record("commons_node", goal["id"], alpha))
    with pytest.raises(HarnessError) as imported:
        service.expand_commons(exp["id"], f"import {name}\n", alpha, max_bytes=30_000)
    assert imported.value.code == "COMMONS_MODULE_NOT_FOUND"
    assert imported.value.details == {"module": name, "node_id": goal["id"]}


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
        "closure",
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
        "previous_rank": None,
    }
    service.abandon_node(node["id"], "Moot.", alpha, "abandon")
    closed = publish(service, node["id"], beta, "verified", "late")
    assert closed == {"recorded": False, "module": node["lean_module"], "reason": "node_closed"}


def test_a_referee_may_read_the_nodes_published_source(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = lemma(service, exp, alpha, "Trace", "n")
    publish(service, node["id"], beta, "partial", "p")  # a skeleton, which a referee checks
    source = service.read_node(node["id"], alpha)["node"]["lean_source"]
    scratch = service.create_artifact(
        ArtifactCreate(experiment_id=exp["id"], kind="lean_source", content="y"), beta, "scratch"
    )
    ref = referee(service.request_review(node["id"], alpha, "review"), exp)
    assert service.referee_may_read_artifact(node["id"], source["artifact_id"], ref) is True
    assert service.referee_may_read_artifact(node["id"], scratch["id"], ref) is False


def imported(service, node, agent):
    """An import entry of the node's current source (or stub), as lean_check records it."""
    current = service.get_record("commons_node", node["id"], agent)
    sha256 = (current["lean_source"] or {}).get("sha256")
    return {"module": current["lean_module"], "node_id": current["id"], "sha256": sha256}


def test_an_importer_goes_stale_once_its_import_is_replaced(lab):
    """PR 37 review: a verified importer stayed verified, off the frontier and immune to
    review after the source it imported was replaced."""
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    gamma = third_branch(service, author, exp)
    a, b = lemma(service, exp, alpha, "A", "a"), lemma(service, exp, alpha, "B", "b")
    da, db = state_lean(service, a["id"], alpha, "la"), state_lean(service, b["id"], alpha, "lb")
    helper = "theorem helper_b : True := trivial\ntheorem trace_add : (1 : Nat) + 1 = 2 := rfl\n"
    publish(service, b["id"], beta, "complete", "b1", content=helper, lean_statement_sha256=db)
    source = (
        f"import {b['lean_module']}\ntheorem trace_add : (1 : Nat) + 1 = 2 := by\n"
        "  have := helper_b\n  rfl\n"
    )
    imports = [imported(service, b, alpha)]
    publish(
        service, a["id"], alpha, "verified", "a1", source, lean_statement_sha256=da, imports=imports
    )

    def state(node):
        return service.read_node(node["id"], alpha)["node"]["source"]

    def frontier():
        return {
            item["id"] for item in service.query_nodes(exp["id"], alpha, frontier=True)["items"]
        }

    assert state(a) == "verified" and a["id"] not in frontier()
    # Another branch cannot replace an equal-rank complete source: others may import it.
    refused = publish(service, b["id"], gamma, "complete", "g1", PROOF, lean_statement_sha256=db)
    assert (refused["reason"], refused["rank"]) == ("lower_rank", "complete")
    # Its publisher (or the node's author) can, and A's check inlined the old one.
    assert publish(service, b["id"], beta, "complete", "b2", PROOF, lean_statement_sha256=db)[
        "replaced"
    ]
    assert (state(a), state(b)) == ("stale", "complete")
    assert a["id"] in frontier() and service.node_source_state(a["id"], alpha)[1] == "stale"
    assert service.request_review(a["id"], beta, "review")  # no REVIEW_UNNEEDED
    # A stale source is none: another branch's source of A's statement replaces it.
    assert publish(service, a["id"], gamma, "partial", "g2", lean_statement_sha256=da)["replaced"]
    assert publish(service, b["id"], alpha, "complete", "a-b", lean_statement_sha256=db)["replaced"]


def test_any_branch_replaces_a_complete_source_of_a_node_without_a_statement(lab):
    """PR 37 re-audit: nothing outranks a complete source on a node with no elaborated Lean
    statement (a definition), so the equal-rank lock let an unrelated first file hold the
    node for good. Only a node another branch can outrank keeps the lock."""
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    gamma = third_branch(service, author, exp)
    node = service.create_node(
        exp["id"], NodeCreate(node_type="definition", title="D", statement="D."), alpha, "d"
    )
    junk = "theorem unrelated : True := trivial\n"
    assert publish(service, node["id"], beta, "complete", "junk", junk)["recorded"] is True
    real = "import Mathlib\nnoncomputable def D : ℝ := 1\n"
    replaced = publish(service, node["id"], gamma, "complete", "real", real)
    assert (replaced["recorded"], replaced["replaced"]) == (True, True)
    assert publish(service, node["id"], beta, "partial", "lower")["reason"] == "lower_rank"


def test_a_source_stands_only_on_the_lean_its_check_inlined(lab):
    """A change two imports down stales the importer too. A source recording its check's
    closure stands on exactly that Lean, and an import's restatement changes none of it."""
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    a, b, c, x = (lemma(service, exp, alpha, title, title) for title in "ABCX")
    digests = {n["id"]: state_lean(service, n["id"], alpha, "l" + n["title"]) for n in (a, b, c, x)}

    def put(node, key, *children, closure=None):
        lines = [f"import {child['lean_module']}" for child in children]
        record = {"imports": [imported(service, child, alpha) for child in children]}
        if closure is not None:
            record["closure"] = [imported(service, member, alpha) for member in closure]
        record["lean_statement_sha256"] = digests[node["id"]]
        content = "\n".join([*lines, f"theorem {key} : True := trivial"])
        published = publish(service, node["id"], beta, "complete", key, content, **record)
        assert published["recorded"] is True, published

    def state(node):
        return service.read_node(node["id"], alpha)["node"]["source"]

    put(c, "c1")
    put(b, "b1", c)
    put(a, "a1", b)
    assert [state(n) for n in (a, b, c)] == ["complete"] * 3
    restated = {**LEAN, "lean_statement": ": (2 : Nat) = 2"}
    service.set_lean_statement(b["id"], *restated.values(), ELABORATED, alpha, "restate")
    assert (state(a), state(b)) == ("complete", "stale")
    service.set_lean_statement(b["id"], *LEAN.values(), ELABORATED, alpha, "restate-back")
    put(c, "c2")
    assert [state(n) for n in (a, b, c)] == ["stale", "stale", "complete"]
    # X's check inlined A, B and C as they are now, so X stands though A's own check did not.
    put(x, "x1", a, closure=(b, c, a))
    assert state(x) == "complete"
    put(c, "c3")
    assert state(x) == "stale"


def test_a_legacy_import_chain_is_judged_the_same_in_any_order():
    """PR 37 re-audit: a depth bound was memoized with each verdict, so on a chain of 201
    records without a closure, judging from the head staled every node and from the leaf
    none. A long chain now stands either way, with no deep recursion; a replaced source
    below stales everything above it, and a cycle stands on nothing."""

    def chain(size, first="s0"):
        return [
            {
                "id": f"n{i}",
                "lean_source": {
                    "sha256": f"s{i}" if i else first,
                    "imports": [{"node_id": f"n{i - 1}", "sha256": f"s{i - 1}"}] if i else [],
                },
            }
            for i in range(size)
        ]

    nodes = chain(10 * MAX_COMMONS_MODULES)
    head_first, leaf_first = Closures.over(nodes), Closures.over(nodes)
    assert all(head_first.stands(node) for node in reversed(nodes))
    assert all(leaf_first.stands(node) for node in nodes)
    replaced = chain(MAX_COMMONS_MODULES + 1, first="s0-new")
    closures = Closures.over(replaced)
    assert [closures.stands(node) for node in reversed(replaced)] == [False] * (
        MAX_COMMONS_MODULES
    ) + [True]
    loop = [
        {"id": a, "lean_source": {"sha256": a, "imports": [{"node_id": b, "sha256": b}]}}
        for a, b in (("x", "y"), ("y", "x"))
    ]
    assert not any(Closures.over(loop).stands(node) for node in loop)


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


# The publication gate (PR 37 review) -----------------------------------------------------

# Every body a published module may not hold, with the command the gate names. A module's
# compile-time code would run in each importer's VM, and a referee's.
REFUSED = {
    'run_cmd do\n  IO.FS.writeFile "/work/Checker.lean" ""\n': "run_cmd",
    'theorem a : True := trivial #eval IO.getEnv "HOME"\n': "#eval",
    "#guard 1 = 1\n": "#guard",
    "#guard_msgs in\n#check 1\n": "#guard_msgs",
    "#reduce (2 : Nat) ^ 64\n": "#reduce",
    # Lean reads the longest token, so this is `#eval IO.getEnv "HOME"`.
    '#evalIO.getEnv "HOME"\n': "#evalIO",
    "theorem a : True := by\n  run_tac pure ()\n": "run_tac",
    "example : True := by_elab do return default\n": "by_elab",
    'elab "x" : term => return default\n': "elab",
    "axiom cheat {p : Prop} : p\nmacro_rules | `(tactic| sorry) => `(tactic| exact cheat)\n": (
        "macro_rules"
    ),
    'syntax "cheat" : tactic\n': "syntax",
    "initialize counter : Nat ← pure 0\n": "initialize",
    "unsafe def f : Nat := 1\n": "unsafe",
    "simproc s (_) := fun _ => pure .continue\n": "simproc",
    "register_simp_attr my_simp\n": "register_simp_attr",
    "@[command_elab printAxioms] def fake : Nat := 1\n": "@[command_elab]",
    "@[simp, to_additive (attr := norm_num)] theorem a : True := trivial\n": "@[norm_num]",
    '@[extern "c_fn"] opaque g : Nat\n': "@[extern]",
    "attribute [tactic foo] bar\n": "attribute [tactic]",
    'notation "⟪" x "⟫" => x + 1\n': "notation",
    'scoped notation "⟪" x "⟫" => x + 1\n': "scoped notation",
    'scoped[Foo] infixl:65 " +++ " => Nat.add\n': "scoped infixl",
    'set_option trace.profiler.output "x" in\ntheorem a : True := trivial\n': (
        "set_option trace.profiler.output"
    ),
    "set_option debug.skipKernelTC true\n": "set_option debug.skipKernelTC",
    "theorem t : True := by\n  set_option trace.Meta.Tactic.simp true in\n  trivial\n": (
        "set_option trace.Meta.Tactic.simp"
    ),
    "open Lean in\ntheorem a : True := trivial\n": "Lean",
    "def t := _root_.IO.FS.writeFile\n": "_root_.IO.FS.writeFile",
    "def t := «IO».FS.writeFile\n": "«IO»",
    "#exit\n": "#exit",
}
ALLOWED = (
    PROOF.split("\n", 1)[1],
    'local notation "⟪" x "⟫" => x + 1\n@[inherit_doc] local infixl:65 " +++ " => Nat.add\n',
    "set_option maxHeartbeats 400000 in\ntheorem a : True := by trivial\n",
    "set_option synthInstance.maxHeartbeats 100 in\nset_option linter.unusedVariables false\n",
    "attribute [local simp] Nat.add_comm\n@[simp, macro_inline, elab_as_elim] def g := 1\n",
    "#check Nat.add_comm\n#print axioms Nat.add_comm\ntheorem a : #v[1, 2].size = 2 := rfl\n",
    # Mathlib's card notation is a term: only commands that evaluate are refused.
    "open Finset in\ntheorem card_le (s : Finset ℕ) : #s ≤ #(s) := le_rfl\n",
    "set_option push_neg.use_distrib true in\nset_option simprocs false in\n"
    "set_option tactic.hygienic false in\nset_option backward.isDefEq.lazyWhnfCore false in\n"
    "theorem t : True := trivial\n",
    # Only a name rooted in a metaprogramming or IO namespace is refused.
    "theorem Foo.IO : True := trivial\ndef EIOx : ℕ := 1\ntheorem h : Foo.IO := Foo.«IO»\n",
    '-- run_cmd, #eval\n/- macro_rules -/ theorem a : "run_cmd".length = 7 := rfl\n',
    "theorem x (init : Nat) : List.foldl (· + ·) init [] = init := rfl\n",
    "noncomputable section\nnamespace Foo\nopen Real\n"
    "lemma l (x : ℝ) : x = x := rfl\nend Foo\nend\n",
)


def test_the_publication_gate_refuses_code_and_syntax_beyond_the_module():
    for body, command in REFUSED.items():
        assert refused_command(f"import Lean\nimport Mathlib\n\n{body}") == command, body
    for body in ALLOWED:
        assert refused_command(f"import Mathlib\n\n{body}") is None, body


def test_the_gate_refuses_unsafe_only_as_a_declaration_modifier():
    """PR 37 re-audit: aesop's `unsafe` rule phase (87 Mathlib lines) is no declaration."""
    hints = (
        "theorem t (p : Prop) (h : p) : p := by aesop (add unsafe 50% apply id)\n",
        "@[aesop unsafe 50% apply] theorem l (n : ℕ) : n ≤ n + 1 := by omega\n",
        "attribute [aesop unsafe 20% apply] Nat.le_succ\n",
    )
    for body in hints:
        assert refused_command(f"import Mathlib\n{body}") is None, body
    for body in ("unsafe def f : Nat := 1\n", "@[inline] private unsafe def f : Nat := 1\n"):
        assert refused_command(f"import Mathlib\n{body}") == "unsafe", body


def test_each_refusal_names_its_workaround():
    """PR 37 re-audit: a refusal says what to write instead."""
    assert "local notation" in gate_remedy("scoped notation")
    assert "local infixl" in gate_remedy("infixl")
    assert "Drop" in gate_remedy("set_option trace.Meta.Tactic.simp")
    assert "trace.*" in gate_remedy("set_option trace.Meta.Tactic.simp")
    assert "#s" in gate_remedy("#eval")
    assert "IO" in gate_remedy("IO.println")


def plant(service, node_id, **fields):
    """Write fields straight into a node's row, as a record from before the gate reads."""
    with service.db.transaction() as session:
        row = session.get(RecordRow, node_id)
        service._replace(session, row, fields)


def test_a_module_that_runs_code_is_neither_published_nor_inlined(lab):
    """PR 37 review: a published module's run_cmd ran in every importer's VM, where it could
    read the importer's private files and overwrite its checker."""
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = lemma(service, exp, alpha, "Helper", "helper")
    evil = (
        "import Lean\ntheorem helper : 1 + 1 = 2 := rfl\n\nrun_cmd do\n"
        '  let secret ← IO.FS.readFile "/work/private.lean"\n'
        '  IO.FS.writeFile "/work/.physharness/statement_check.lean" secret\n'
    )
    assert publish(service, node["id"], beta, "complete", "evil", content=evil) == {
        "recorded": False,
        "module": node["lean_module"],
        "reason": "refused_command",
        "command": "run_cmd",
        "remediation": gate_remedy("run_cmd"),
    }
    assert service.read_node(node["id"], alpha)["node"]["lean_source"] is None
    # A source stored before the gate is refused when imported or fetched, too.
    publish(service, node["id"], beta, "complete", "clean", content=PROOF)
    artifact = service.create_artifact(
        ArtifactCreate(
            experiment_id=exp["id"], branch_id=beta.branch_id, kind="lean_source", content=evil
        ),
        beta,
        "evil-artifact",
    )
    source = service.read_node(node["id"], alpha)["node"]["lean_source"]
    plant(
        service,
        node["id"],
        lean_source={**source, "artifact_id": artifact["id"], "sha256": artifact["sha256"]},
    )
    importer = f"import {node['lean_module']}\n\ntheorem mine : 2 = 1 + 1 := helper.symm\n"
    for attempt in (
        lambda: service.expand_commons(exp["id"], importer, alpha, max_bytes=30_000),
        lambda: service.commons_module(node["id"], alpha),
    ):
        with pytest.raises(HarnessError) as refused:
            attempt()
        assert (refused.value.code, refused.value.details) == (
            "COMMONS_MODULE_REFUSED",
            {"module": node["lean_module"], "command": "run_cmd"},
        )
        assert "republish" in refused.value.remediation.lower()


def test_a_statement_that_runs_code_is_never_stored_or_imported_as_a_stub(lab):
    """A node's statement is elaborated in importers' VMs (its sorry stub) and in every
    publisher's statement check, so the gate reads it too."""
    service, _, exp, _, (alpha, _) = society_lab(lab)
    node = lemma(service, exp, alpha, "Evil", "evil")
    statement = ": (by_elab do return default) = (0 : Nat)"
    with pytest.raises(HarnessError) as refused:
        service.set_lean_statement(
            node["id"], "import Mathlib", "evil", statement, ELABORATED, alpha, "stated"
        )
    assert (refused.value.code, refused.value.details) == (
        "INVALID_LEAN_STATEMENT",
        {"command": "by_elab"},
    )
    plant(
        service,
        node["id"],
        lean_header="import Mathlib",
        lean_name="evil",
        lean_statement=statement,
        lean_elaborated=True,
    )
    with pytest.raises(HarnessError) as stub:
        service.expand_commons(
            exp["id"], f"import {node['lean_module']}\n", alpha, max_bytes=30_000
        )
    assert (stub.value.code, stub.value.details["command"]) == (
        "COMMONS_MODULE_REFUSED",
        "by_elab",
    )


@pytest.mark.lean
def test_real_local_notation_ends_with_the_section_around_its_module(tmp_path):
    """Run with PHYSHARNESS_LEAN_CMD (e.g. 'lean +leanprover/lean4:v4.33.0'). The gate allows
    local notation, which Lean drops at the `end` of the section the inliner wraps the module
    in; global notation, which it refuses, would reach the importer's lines."""
    command = os.environ.get("PHYSHARNESS_LEAN_CMD")
    if not command:
        pytest.skip("set PHYSHARNESS_LEAN_CMD")
    caller = f"import {A}\n\ntheorem outside : ⟪(1 : Nat)⟫ = 2 := rfl\n"
    errors = {}
    for kind in ("local notation", "notation"):
        text = f'{kind} "⟪" x "⟫" => x + 1\ntheorem inside : ⟪(1 : Nat)⟫ = 2 := rfl\n'
        flat = inline_commons(caller, resolver(module(A, text)), max_bytes=30_000)
        path = tmp_path / "Flat.lean"
        path.write_text(flat.source, encoding="utf-8")
        completed = subprocess.run(
            [*shlex.split(command), str(path)], capture_output=True, text=True, timeout=300
        )
        found = parse_lean_output(completed.stdout, str(path))
        errors[kind] = [remap({"messages": found, "holes": []}, flat)["messages"], text]
    (message,) = [m for m in errors["local notation"][0] if m["severity"] == "error"]
    assert message["line"] == 3 and "module" not in message  # the caller's own line only
    assert refused_command(errors["local notation"][1]) is None
    assert not [m for m in errors["notation"][0] if m["severity"] == "error"]
    assert refused_command(errors["notation"][1]) == "notation"
