"""Blueprint commons: society policy, attributed nodes, typed edges and the platform ladder."""

from datetime import timedelta

import pytest
from commons_helpers import set_status, society_lab
from pydantic import ValidationError
from sqlalchemy import select
from test_core import setup_experiment
from test_sharing import approaches, artifact

from physharness.commons import PLATFORM
from physharness.commons_models import NodeCreate
from physharness.domain import (
    ArtifactCreate,
    ExperimentCreate,
    LiteraturePolicy,
    SocietyPolicy,
    utcnow,
)
from physharness.errors import HarnessError
from physharness.storage import EdgeRow, RecordRow, record_json_text


def lemma(title="Trace lemma", statement="The trace is additive.", **extra):
    return NodeCreate(node_type="lemma", title=title, statement=statement, **extra)


def experiment_request(original, **update):
    return ExperimentCreate.model_validate(
        {**{k: original[k] for k in ("campaign_id", "problem_id", "models", "budget")}, **update}
    )


def events(service, actor, kind):
    return [e for e in service.events(actor, limit=1000) if e["kind"] == kind]


def test_society_requires_ideas_sharing(lab):
    original, _ = setup_experiment(lab)
    with pytest.raises(ValidationError, match="SOCIETY_REQUIRES_IDEAS"):
        experiment_request(original, sharing="verified", society=SocietyPolicy())
    request = experiment_request(original, sharing="ideas", society=SocietyPolicy())
    assert request.society.tool_profile == "society"


def test_benchmark_literature_requires_masked_reference(lab):
    original, _ = setup_experiment(lab)
    with pytest.raises(ValidationError, match="masked_reference_artifact_id"):
        experiment_request(
            original,
            sharing="ideas",
            society=SocietyPolicy(literature=LiteraturePolicy(mode="benchmark")),
        )
    request = experiment_request(
        original,
        sharing="ideas",
        society=SocietyPolicy(
            literature=LiteraturePolicy(mode="benchmark", masked_reference_artifact_id="ref")
        ),
    )
    assert request.society.literature.mode == "benchmark"


def test_legacy_experiment_payload_has_no_society_key(lab):
    service, author, _ = lab
    legacy, _ = setup_experiment(lab)
    assert "society" not in legacy
    assert "society" not in service.get_record("experiment", legacy["id"], author)
    assert service.society_policy(legacy["id"], author) is None
    _, _, society, _, _ = society_lab(lab, claim_ttl_seconds=120)
    assert society["society"] == SocietyPolicy(claim_ttl_seconds=120).model_dump(mode="json")
    assert service.society_policy(society["id"], author)["claim_ttl_seconds"] == 120


def test_commons_disabled_without_policy(lab):
    service, author, exp, _, (alpha, _) = approaches(lab, "ideas")
    for call in (
        lambda: service.create_node(exp["id"], lemma(), alpha, "node"),
        lambda: service.query_nodes(exp["id"], alpha),
        lambda: service.ensure_goal_node(exp["id"], author),
    ):
        with pytest.raises(HarnessError) as err:
            call()
        assert err.value.code == "SOCIETY_DISABLED"
        assert err.value.status == 409


def test_create_node_attribution_and_event(lab):
    service, author, exp, branches, (alpha, beta) = society_lab(lab)
    node = service.create_node(
        exp["id"],
        lemma(lean_name="trace_add", lean_statement=": (1 : Nat) + 1 = 2"),
        alpha,
        "node",
    )
    assert node["status"] == "informal"
    assert node["lean_elaborated"] is False
    assert node["branch_id"] == alpha.branch_id == branches[0]["id"]
    assert node["origin_actor_id"] == alpha.id
    assert node["experiment_id"] == exp["id"]
    assert node["target_digest"] == exp["target_digest"]
    assert node["topic_id"] is None and node["lab"] is None
    assert node["citation_count"] == 0 and node["status_evidence"] == {}
    assert len(node["lean_statement_sha256"]) == 64
    created = events(service, beta, "commons.node_created")
    assert [e["payload"] for e in created] == [
        {"experiment_id": exp["id"], "node_id": node["id"], "node_type": "lemma"}
    ]
    plain = service.create_node(exp["id"], lemma(title="Plain"), alpha, "plain")
    assert plain["lean_statement_sha256"] is None


def test_agent_without_branch_cannot_author_nodes(lab):
    service, author, exp, _, _ = society_lab(lab)
    orchestrator = author.model_copy(
        update={"role": "agent", "experiment_id": exp["id"], "agent_orchestrator": True}
    )
    with pytest.raises(HarnessError) as err:
        service.create_node(exp["id"], lemma(), orchestrator, "orchestrated")
    assert err.value.code == "BRANCH_AUTHORITY"


def test_tangent_requires_motivation(lab):
    service, _, exp, _, (alpha, _) = society_lab(lab)
    with pytest.raises(ValidationError, match="TANGENT_MOTIVATION_REQUIRED"):
        NodeCreate(node_type="tangent", title="Side", statement="An aside.")
    root = service.create_node(exp["id"], lemma(), alpha, "root")
    tangent = service.create_node(
        exp["id"],
        NodeCreate(
            node_type="tangent",
            title="Side",
            statement="An aside.",
            edges=[{"relation": "motivated_by", "target_id": root["id"]}],
        ),
        alpha,
        "tangent",
    )
    assert service.read_node(tangent["id"], alpha)["edges_out"] == [
        {
            "relation": "motivated_by",
            "node_id": root["id"],
            "title": root["title"],
            "status": "informal",
        }
    ]


def test_lean_fields_both_or_neither():
    with pytest.raises(ValidationError):
        lemma(lean_name="only_name")
    with pytest.raises(ValidationError):
        lemma(lean_statement=": True")
    with pytest.raises(ValidationError):
        lemma(lean_header="import Mathlib")
    with pytest.raises(ValidationError):
        lemma(lean_name="1bad name", lean_statement=": True")
    with pytest.raises(ValidationError):
        lemma(statement="   ")
    ok = lemma(lean_header="import Mathlib", lean_name="Foo.bar'", lean_statement=": True")
    assert ok.lean_name == "Foo.bar'"


def test_goal_type_not_creatable(lab):
    with pytest.raises(ValidationError):
        NodeCreate(node_type="goal", title="Goal", statement="Everything.")
    service, _, exp, _, (alpha, _) = society_lab(lab)
    forged = NodeCreate.model_construct(
        node_type="goal",
        title="Goal",
        statement="Everything.",
        assumptions=[],
        lean_header=None,
        lean_statement=None,
        lean_name=None,
        edges=[],
        artifact_ids=[],
    )
    with pytest.raises(HarnessError) as err:
        service.create_node(exp["id"], forged, alpha, "forged-goal")
    assert err.value.code == "GOAL_NODE_RESERVED"


def test_depends_on_cycle_rejected(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    a = service.create_node(exp["id"], lemma("A"), alpha, "a")
    b = service.create_node(
        exp["id"],
        lemma("B", edges=[{"relation": "depends_on", "target_id": a["id"]}]),
        alpha,
        "b",
    )
    c = service.create_node(exp["id"], lemma("C"), beta, "c")
    service.link_nodes(exp["id"], a["id"], "depends_on", c["id"], beta, "a-c")
    with pytest.raises(HarnessError) as err:
        service.link_nodes(exp["id"], c["id"], "depends_on", b["id"], beta, "c-b")
    assert err.value.code == "DEPENDENCY_CYCLE"
    # Non-dependency relations may point backwards; duplicates are no-ops.
    first = service.link_nodes(exp["id"], c["id"], "generalizes", b["id"], beta, "gen")
    again = service.link_nodes(exp["id"], c["id"], "generalizes", b["id"], alpha, "gen-2")
    assert first["created"] is True and again["created"] is False
    assert [e["payload"] for e in events(service, alpha, "commons.edge_added")][-1] == {
        "experiment_id": exp["id"],
        "source_id": c["id"],
        "relation": "generalizes",
        "target_id": b["id"],
    }
    with service.db.sessions() as session:
        relations = set(
            session.scalars(select(EdgeRow.relation).where(EdgeRow.source_id == c["id"]))
        )
    assert relations == {"commons:generalizes"}


def test_self_edge_rejected(lab):
    service, _, exp, _, (alpha, _) = society_lab(lab)
    a = service.create_node(exp["id"], lemma("A"), alpha, "a")
    with pytest.raises(HarnessError) as err:
        service.link_nodes(exp["id"], a["id"], "duplicates", a["id"], alpha, "self")
    assert err.value.code == "SELF_EDGE"
    with pytest.raises(HarnessError) as err:
        service.link_nodes(exp["id"], a["id"], "cites", a["id"], alpha, "bad-relation")
    assert err.value.code == "INVALID_EDGE"


def test_edge_to_other_experiment_node_not_found(lab):
    service, author, exp, _, (alpha, _) = society_lab(lab)
    _, _, other, _, (stranger, _) = society_lab(lab, prefix="other")
    foreign = service.create_node(other["id"], lemma("Foreign"), stranger, "foreign")
    edge = {"relation": "depends_on", "target_id": foreign["id"]}
    with pytest.raises(HarnessError) as err:
        service.create_node(exp["id"], lemma(edges=[edge]), alpha, "cross")
    assert err.value.code == "NOT_FOUND"
    local = service.create_node(exp["id"], lemma("Local"), author, "local")
    with pytest.raises(HarnessError) as err:
        service.link_nodes(exp["id"], local["id"], "depends_on", foreign["id"], author, "x")
    assert err.value.code == "NOT_FOUND"
    with pytest.raises(HarnessError) as err:
        service.link_nodes(other["id"], foreign["id"], "refutes", local["id"], author, "y")
    assert err.value.code == "NOT_FOUND"


def test_node_artifacts_must_be_shareable_experiment_evidence(lab):
    service, _, exp, _, (alpha, _) = society_lab(lab)
    _, _, _, _, (stranger, _) = society_lab(lab, prefix="other")
    own = artifact(service, alpha, "evidence")
    node = service.create_node(exp["id"], lemma(artifact_ids=[own["id"]]), alpha, "with")
    assert node["artifact_ids"] == [own["id"]]
    foreign = artifact(service, stranger, "foreign evidence")
    with pytest.raises(HarnessError) as err:
        service.create_node(exp["id"], lemma(artifact_ids=[foreign["id"]]), alpha, "foreign")
    assert err.value.code == "NOT_FOUND"
    private = service.create_artifact(
        ArtifactCreate(experiment_id=exp["id"], kind="checkpoint", content="context"),
        alpha,
        "checkpoint",
    )
    with pytest.raises(HarnessError) as err:
        service.create_node(exp["id"], lemma(artifact_ids=[private["id"]]), alpha, "private")
    assert err.value.code == "EVIDENCE_SCOPE"


def test_peer_agent_sees_node_other_experiment_does_not(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    _, _, _, _, (stranger, _) = society_lab(lab, prefix="other")
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    assert service.read_node(node["id"], beta)["node"]["id"] == node["id"]
    assert service.get_record("commons_node", node["id"], beta)["title"] == node["title"]
    assert [n["id"] for n in service.query_nodes(exp["id"], beta, node_type="lemma")["items"]] == [
        node["id"]
    ]
    for call in (
        lambda: service.read_node(node["id"], stranger),
        lambda: service.get_record("commons_node", node["id"], stranger),
        lambda: service.query_nodes(exp["id"], stranger),
    ):
        with pytest.raises(HarnessError) as err:
            call()
        assert err.value.code == "NOT_FOUND"
    assert node["id"] not in str(service.events(stranger, limit=1000))
    # Visibility is an ideas-sharing grant, not authorship: revoking sharing hides the commons.
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, exp["id"]), {"sharing": "verified"})
    with pytest.raises(HarnessError) as err:
        service.get_record("commons_node", node["id"], beta)
    assert err.value.code == "NOT_FOUND"


def test_goal_node_idempotent(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    first = service.ensure_goal_node(exp["id"], alpha)
    second = service.ensure_goal_node(exp["id"], beta)
    assert first["id"] == second["id"]
    assert first["node_type"] == "goal" and first["branch_id"] is None
    assert first["origin_actor_id"] == PLATFORM
    assert first["status"] == "formally_stated" and first["status_reason"] == "reviewed target"
    assert first["formal_target"] is True and first["lean_statement"] is None
    problem = service.get_record("problem", exp["problem_id"], author)
    assert first["problem_revision_id"] == problem["id"]
    assert first["title"] == problem["title"]
    assert first["statement"] == problem["informal_statement"]
    assert first["assumptions"] == problem["assumptions"]
    listed = service.query_nodes(exp["id"], beta, node_type="goal")["items"]
    assert [n["id"] for n in listed] == [first["id"]]
    with service.db.sessions() as session:
        goals = session.scalars(
            select(RecordRow.id).where(
                RecordRow.kind == "commons_node",
                record_json_text("experiment_id") == exp["id"],
                record_json_text("node_type") == "goal",
            )
        ).all()
    assert goals == [first["id"]]
    with pytest.raises(HarnessError) as err:
        service.abandon_node(first["id"], "too hard", author, "abandon-goal")
    assert err.value.code == "GOAL_NODE_RESERVED"


def test_query_creates_goal_lazily_without_status_writes(lab):
    service, _, exp, _, (alpha, _) = society_lab(lab)
    items = service.query_nodes(exp["id"], alpha)["items"]
    assert [(n["node_type"], n["status"]) for n in items] == [("goal", "formally_stated")]


def test_goal_node_accepted_when_target_receipt_exists(lab, monkeypatch):
    service, author, exp, _, (alpha, _) = society_lab(lab)
    goal = service.ensure_goal_node(exp["id"], author)
    a = service.create_node(exp["id"], lemma("A"), alpha, "a")
    service.link_nodes(exp["id"], a["id"], "depends_on", goal["id"], alpha, "a-goal")
    monkeypatch.setattr(
        service,
        "verified_target_receipt",
        lambda experiment_id, actor: {"receipt_id": "receipt", "target_digest": "d"},
    )
    read = service.read_node(goal["id"], alpha)["node"]
    assert read["status"] == "accepted" and read["status_derived"] is True
    assert read["status_evidence"] == {"receipt_id": "receipt"}
    assert service.read_node(a["id"], alpha)["rests_on"] == {
        "counts": {"accepted": 1},
        "conditional": False,
        "truncated": False,
    }
    listed = service.query_nodes(exp["id"], alpha, node_type="goal")["items"]
    assert listed[0]["status"] == "accepted" and listed[0]["status_derived"] is True
    assert service.query_nodes(exp["id"], alpha, status="accepted")["items"] == listed
    frontier = service.query_nodes(exp["id"], alpha, frontier=True)["items"]
    assert goal["id"] not in [n["id"] for n in frontier]
    # Reads never persist the derived status.
    assert service.get_record("commons_node", goal["id"], author)["status"] == "formally_stated"
    assert not events(service, author, "commons.node_status")


def test_rests_on_counts_dependency_statuses(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    c = service.create_node(exp["id"], lemma("C"), alpha, "c")
    b = service.create_node(
        exp["id"], lemma("B", edges=[{"relation": "depends_on", "target_id": c["id"]}]), alpha, "b"
    )
    a = service.create_node(
        exp["id"], lemma("A", edges=[{"relation": "depends_on", "target_id": b["id"]}]), beta, "a"
    )
    set_status(service, c["id"], "formally_stated", "accepted")
    set_status(service, b["id"], "refereed")
    read = service.read_node(a["id"], alpha)
    assert read["rests_on"] == {
        "counts": {"refereed": 1, "accepted": 1},
        "conditional": True,
        "truncated": False,
    }
    assert read["claimants"] == []
    assert read["edges_out"] == [
        {"relation": "depends_on", "node_id": b["id"], "title": "B", "status": "refereed"}
    ]
    assert service.read_node(b["id"], beta)["rests_on"] == {
        "counts": {"accepted": 1},
        "conditional": False,
        "truncated": False,
    }
    assert service.read_node(b["id"], beta)["edges_in"] == [
        {"relation": "depends_on", "node_id": a["id"], "title": "A", "status": "informal"}
    ]
    assert service.read_node(c["id"], beta)["rests_on"] == {
        "counts": {},
        "conditional": False,
        "truncated": False,
    }


def test_illegal_transition_rejected(lab):
    service, author, exp, _, (alpha, _) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    with pytest.raises(HarnessError) as err:
        set_status(service, node["id"], "accepted")
    assert err.value.code == "ILLEGAL_STATUS_TRANSITION"
    accepted = set_status(service, node["id"], "formally_stated", "accepted")
    assert accepted["status"] == "accepted"
    assert accepted["status_reason"] == "platform test"
    assert accepted["status_evidence"] == {"fixture": True}
    with pytest.raises(HarnessError) as err:
        set_status(service, node["id"], "informal")
    assert err.value.code == "ILLEGAL_STATUS_TRANSITION"
    moves = [e["payload"] for e in events(service, author, "commons.node_status")]
    assert moves == [
        {
            "experiment_id": exp["id"],
            "node_id": node["id"],
            "from": "informal",
            "to": "formally_stated",
            "reason": "platform test",
        },
        {
            "experiment_id": exp["id"],
            "node_id": node["id"],
            "from": "formally_stated",
            "to": "accepted",
            "reason": "platform test",
        },
    ]


def test_abandon_only_by_author_and_not_goal(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    for actor, reason, code in (
        (beta, "not mine", "NODE_AUTHORITY"),
        (author, "operator override", "NODE_AUTHORITY"),
        (alpha, "", "INVALID_REASON"),
        (alpha, "x" * 2001, "INVALID_REASON"),
    ):
        with pytest.raises(HarnessError) as err:
            service.abandon_node(node["id"], reason, actor, f"abandon-{actor.id}-{len(reason)}")
        assert err.value.code == code
    abandoned = service.abandon_node(node["id"], "Superseded by a sharper lemma.", alpha, "done")
    assert abandoned["status"] == "abandoned"
    assert abandoned["status_reason"] == "Superseded by a sharper lemma."
    with pytest.raises(HarnessError) as err:
        service.abandon_node(node["id"], "again", alpha, "again")
    assert err.value.code == "NODE_CLOSED"
    own = service.create_node(exp["id"], lemma("Operator"), author, "operator-node")
    assert service.abandon_node(own["id"], "Withdrawn.", author, "op-abandon")["status"] == (
        "abandoned"
    )
    goal = service.ensure_goal_node(exp["id"], author)
    with pytest.raises(HarnessError) as err:
        service.abandon_node(goal["id"], "Too hard.", alpha, "goal")
    assert err.value.code == "GOAL_NODE_RESERVED"


def test_frontier_orders_root_path_and_dependents_first(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    goal = service.ensure_goal_node(exp["id"], author)
    ids = {
        name: service.create_node(exp["id"], lemma(name), alpha, name)["id"]
        for name in ("A", "B", "C", "D", "E", "F")
    }
    service.link_nodes(exp["id"], goal["id"], "depends_on", ids["A"], beta, "goal-a")
    for name in ("D", "E", "F"):
        service.link_nodes(exp["id"], ids[name], "depends_on", ids["C"], beta, f"{name}-c")
    service.abandon_node(ids["F"], "Dead end.", alpha, "abandon-f")
    stale = (utcnow() - timedelta(minutes=45)).isoformat()
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, ids["B"]), {"last_activity_at": stale})
    page = service.query_nodes(exp["id"], beta, frontier=True)
    assert page["next_cursor"] is None
    order = [item["id"] for item in page["items"]]
    assert order[:4] == [ids["A"], goal["id"], ids["C"], ids["B"]]
    assert ids["F"] not in order and len(order) == 6
    top = page["items"][0]
    assert top["score_components"]["on_root_path"] == 3.0
    assert top["score_components"]["waiting_dependents"] == 1.0
    assert top["score_components"]["claimants"] == 0.0
    assert page["items"][2]["score_components"]["waiting_dependents"] == 2.0
    assert page["items"][3]["score_components"]["neglect"] == pytest.approx(1.5, abs=0.01)
    assert set(top) >= {
        "id",
        "node_type",
        "title",
        "status",
        "lab",
        "statement",
        "lean_name",
        "citation_count",
        "score",
        "score_components",
    }
    assert [
        i["id"] for i in service.query_nodes(exp["id"], beta, frontier=True, limit=2)["items"]
    ] == order[:2]


def test_query_filters_and_keyset_pages(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    statements = ["Trace identity. " * 30, "Spectral gap bound.", "Trace identity."] * 2
    made = [
        service.create_node(exp["id"], lemma(f"Node {i}", statement=text), alpha, f"n{i}")
        for i, text in enumerate(statements[:5])
    ]
    spectral = service.query_nodes(exp["id"], beta, text="SPECTRAL radius")
    assert {n["id"] for n in spectral["items"]} == {made[1]["id"], made[4]["id"]}
    lemmas = [n["id"] for n in made]
    first = service.query_nodes(exp["id"], beta, node_type="lemma", limit=3)
    assert [n["id"] for n in first["items"]] == sorted(lemmas)[:3]
    assert first["next_cursor"] == sorted(lemmas)[2]
    second = service.query_nodes(
        exp["id"], beta, node_type="lemma", limit=3, after=first["next_cursor"]
    )
    assert [n["id"] for n in second["items"]] == sorted(lemmas)[3:]
    assert second["next_cursor"] is None
    long = next(n for n in first["items"] + second["items"] if n["id"] == made[0]["id"])
    assert long["statement"] == made[0]["statement"][:300] and "score" not in long
    for kwargs in ({"limit": 21}, {"limit": 0}, {"status": "proven"}, {"node_type": "theorem"}):
        with pytest.raises(HarnessError) as err:
            service.query_nodes(exp["id"], beta, **kwargs)
        assert err.value.status == 422


def test_mutations_require_active_experiment(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    service.transition_experiment(exp["id"], "pause", 2, author, "pause")
    with pytest.raises(HarnessError) as err:
        service.create_node(exp["id"], lemma("Late"), alpha, "late")
    assert err.value.code == "EXPERIMENT_NOT_ACTIVE"
    # Reads stay available while paused.
    assert service.read_node(node["id"], beta)["node"]["id"] == node["id"]


def test_idempotent_create_and_conflict(lab):
    service, _, exp, _, (alpha, _) = society_lab(lab)
    first = service.create_node(exp["id"], lemma(), alpha, "same")
    assert service.create_node(exp["id"], lemma(), alpha, "same") == first
    with pytest.raises(HarnessError) as err:
        service.create_node(exp["id"], lemma(title="Changed"), alpha, "same")
    assert err.value.code == "IDEMPOTENCY_CONFLICT"
    assert len(service.query_nodes(exp["id"], alpha, node_type="lemma")["items"]) == 1


def test_society_lab_spreads_branches_over_models(lab):
    service, author, exp, branches, (alpha, beta) = society_lab(lab, models=2, referee_quorum=2)
    assert [m["model"] for m in exp["models"]] == ["explicit-test-model", "explicit-test-model-1"]
    assert [b["model_configuration"] for b in branches] == exp["models"]
    assert service.society_policy(exp["id"], beta)["referee_quorum"] == 2
