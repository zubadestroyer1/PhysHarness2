"""The lemma store: node modules and ranked lean_source publication (S1 audit #12)."""

import pytest
from commons_helpers import society_lab
from test_commons_review import referee

from physharness import commons
from physharness.commons import _lean_digest
from physharness.commons_models import NodeCreate
from physharness.commons_sources import module_prefix, node_module, source_state
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
    # A cycle (second -> first -> second) and a self import are skipped, not raised.
    cyclic = publish(service, second["id"], beta, "complete", "p2", imports=imports(first, second))
    assert cyclic["recorded"] is True
    assert service.read_node(second["id"], alpha)["edges_out"] == []
    stored = service.read_node(second["id"], alpha)["node"]["lean_source"]
    assert [entry["node_id"] for entry in stored["imports"]] == [first["id"], second["id"]]


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
