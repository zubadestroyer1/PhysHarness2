"""S1 audit #14: waits that wake on relevant events, not only on one peer's message."""

import pytest
from commons_helpers import set_status, society_lab
from test_commons_sources import publish
from test_society_tools import call, profile, running

from physharness.commons_models import NodeCreate, NodePostCreate
from physharness.errors import HarnessError
from physharness.storage import RecordRow
from physharness.worker_authority import worker_effects


def park(service, author, exp, agent_branch, ids=(), timeout=600):
    agent, context = running(service, author, exp, agent_branch)
    with worker_effects(agent, context["task_id"], context["holder"], context["fence"]):
        waited = service.request_event_wait(context["task_id"], list(ids), timeout, agent, "wait")
    return agent, {**waited["intent"]["peer_wait"], "min_sleep_until": 0}


def reason(service, ticket, agent):
    return service.peer_wait_status(ticket, agent)["reason"]


def lemma(service, exp, agent, title):
    return service.create_node(
        exp["id"], NodeCreate(node_type="lemma", title=title, statement=title + "."), agent, title
    )


def test_routed_peer_post_wakes_and_own_or_unrelated_posts_do_not(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    mine, theirs = lemma(service, exp, alpha, "Mine"), lemma(service, exp, beta, "Theirs")
    agent, ticket = park(service, author, exp, alpha.branch_id)
    service.post_on_node(mine["id"], NodePostCreate(kind="finding", abstract="Me."), alpha, "own")
    service.post_on_node(
        theirs["id"], NodePostCreate(kind="finding", abstract="Them."), beta, "other"
    )
    assert service.peer_wait_status(ticket, agent)["reason"] == "waiting"
    service.post_on_node(
        mine["id"], NodePostCreate(kind="objection", abstract="Gap."), beta, "peer"
    )
    assert service.peer_wait_status(ticket, agent)["reason"] == "relevant_update"


def test_a_message_to_the_waiter_wakes_it(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    agent, ticket = park(service, author, exp, alpha.branch_id)
    service.send_society_message(beta.branch_id, alpha.branch_id, "Try traces.", [], beta, "m")
    assert service.peer_wait_status(ticket, agent)["reason"] == "relevant_update"


def test_watched_claims_and_the_long_pole_wake(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    goal = service.query_nodes(exp["id"], alpha, node_type="goal")["items"][0]
    first, second = lemma(service, exp, beta, "First"), lemma(service, exp, beta, "Second")
    for target in (first, second):
        service.link_nodes(
            exp["id"], goal["id"], "depends_on", target["id"], alpha, f"l-{target['id']}"
        )
    agent, ticket = park(service, author, exp, alpha.branch_id, ids=[second["id"]])
    assert set(ticket["long_pole_ids"]) == {first["id"], second["id"]}
    set_status(service, first["id"], "abandoned")
    assert service.peer_wait_status(ticket, agent)["reason"] == "long_pole_changed"
    _, watched = park(service, author, exp, alpha.branch_id, ids=[second["id"]])
    service.claim_node(second["id"], "claim", beta, "beta-claims")
    status = service.peer_wait_status(watched, agent)
    assert status == {
        "ready": True,
        "reason": "watched_event",
        "message_id": None,
        "detail": {"kind": "commons.node_claim", "aggregate_id": second["id"]},
    }


def test_min_sleep_debounces_and_the_deadline_wakes(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    mine = lemma(service, exp, alpha, "Mine")
    agent, ticket = park(service, author, exp, alpha.branch_id)
    service.post_on_node(mine["id"], NodePostCreate(kind="finding", abstract="Hi."), beta, "p")
    assert service.peer_wait_status({**ticket, "min_sleep_until": 9e18}, agent)["reason"] == (
        "min_sleep"
    )
    assert service.peer_wait_status({**ticket, "deadline_at": 0}, agent)["reason"] == "timeout"


def test_claim_renewals_and_existing_claimants_do_not_wake(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = lemma(service, exp, beta, "Watched")
    service.claim_node(node["id"], "claim", beta, "first-claim")
    agent, ticket = park(service, author, exp, alpha.branch_id, ids=[node["id"]])
    service.claim_node(node["id"], "renew", beta, "renew")
    service.claim_node(node["id"], "claim", beta, "reclaim")  # already held: not new
    service.claim_node(node["id"], "claim", alpha, "own-claim")  # the waiter's own branch
    service.claim_node(node["id"], "release", beta, "release")
    assert service.peer_wait_status(ticket, agent)["reason"] == "waiting"
    service.claim_node(node["id"], "claim", beta, "claim-again")  # no live claim before
    assert service.peer_wait_status(ticket, agent)["reason"] == "watched_event"
    claims = [e for e in service.events(author, limit=1000) if e["kind"] == "commons.node_claim"]
    assert [(e["payload"]["action"], e["payload"]["new_claimant"]) for e in claims] == [
        ("claim", True),
        ("renew", False),
        ("claim", False),
        ("claim", True),
        ("release", False),
        ("claim", True),
    ]


def test_same_rank_republication_does_not_wake_and_a_rank_increase_does(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = lemma(service, exp, beta, "Published")
    agent, ticket = park(service, author, exp, alpha.branch_id, ids=[node["id"]])
    publish(service, node["id"], beta, "partial", "p1")  # the first publication
    assert service.peer_wait_status(ticket, agent)["reason"] == "watched_event"
    agent, ticket = park(service, author, exp, alpha.branch_id, ids=[node["id"]])
    publish(service, node["id"], beta, "partial", "p2")  # a retry at the same rank
    assert service.peer_wait_status(ticket, agent)["reason"] == "waiting"
    publish(service, node["id"], beta, "complete", "c1")
    status = service.peer_wait_status(ticket, agent)
    assert status["reason"] == "watched_event"
    assert status["detail"] == {"kind": "commons.source_published", "aggregate_id": node["id"]}
    published = [
        e["payload"]
        for e in service.events(author, limit=1000)
        if e["kind"] == "commons.source_published"
    ]
    assert [(p["rank"], p["previous_rank"]) for p in published] == [
        ("partial", None),
        ("partial", "partial"),
        ("complete", "partial"),
    ]


def test_watched_branches_wake_on_their_new_work(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    watched = [alpha.branch_id, beta.branch_id]
    agent, ticket = park(service, author, exp, alpha.branch_id, ids=watched)
    lemma(service, exp, alpha, "Own")  # the waiter's own work is not news
    assert service.peer_wait_status(ticket, agent)["reason"] == "waiting"
    node = lemma(service, exp, beta, "New")
    assert service.peer_wait_status(ticket, agent)["detail"] == {
        "kind": "commons.node_created",
        "aggregate_id": node["id"],
    }


def test_an_ended_waiter_or_cancelled_experiment_ends_the_wait(lab):
    service, author, exp, _, (alpha, _) = society_lab(lab)
    agent, ticket = park(service, author, exp, alpha.branch_id)
    with service.db.transaction() as session:
        task = session.get(RecordRow, ticket["task_id"])
        service._replace(session, task, {"status": "blocked"})
    assert service.peer_wait_status(ticket, agent)["reason"] == "cancelled"
    agent, ticket = park(service, author, exp, alpha.branch_id)
    service.transition_experiment(exp["id"], "cancel", 2, author, "cancel")
    assert service.peer_wait_status(ticket, agent)["reason"] == "cancelled"


def test_event_waits_are_bounded_and_scoped_to_the_experiment(lab):
    service, author, exp, _, (alpha, _) = society_lab(lab)
    agent, context = running(service, author, exp, alpha.branch_id)
    binding = (agent, context["task_id"], context["holder"], context["fence"])
    for ids, timeout in (([], 0), ([], 3601), ([], "600"), ([alpha.branch_id] * 101, 600)):
        with worker_effects(*binding), pytest.raises(HarnessError) as invalid:
            service.request_event_wait(context["task_id"], ids, timeout, agent, "bad")
        assert invalid.value.code == "EVENT_WAIT_INVALID"
    with pytest.raises(HarnessError) as unbound:
        service.request_event_wait(context["task_id"], [], 600, agent, "unbound")
    assert unbound.value.code == "EVENT_WAIT_INVALID"
    _, _, other, _, (stranger, _) = society_lab(lab, prefix="other")
    elsewhere = lemma(service, other, stranger, "Elsewhere")["id"]
    unknown = "00000000-0000-4000-8000-000000000000"
    for foreign in (context["task_id"], unknown, elsewhere, stranger.branch_id):
        with worker_effects(*binding), pytest.raises(HarnessError) as scope:
            service.request_event_wait(context["task_id"], [foreign], 600, agent, foreign)
        assert scope.value.code == "EVENT_WAIT_SCOPE"


async def test_wait_tool_parks_on_events_and_shows_the_long_pole(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    goal = service.query_nodes(exp["id"], alpha, node_type="goal")["items"][0]
    part = lemma(service, exp, beta, "Part")
    service.link_nodes(exp["id"], goal["id"], "depends_on", part["id"], alpha, "goal-part")
    agent, context = running(service, author, exp, alpha.branch_id)
    tools = profile(service, agent, context)
    waited = await call(tools, "wait", {"for": "events", "ids": [part["id"][:8]]})
    assert waited["long_pole"] == [
        {
            "id": part["id"],
            "node_type": "lemma",
            "title": "Part",
            "open_minutes": 0,
            "claimants": [],
        }
    ]
    ticket = waited["intent"]["peer_wait"]
    assert (ticket["kind"], ticket["watch_node_ids"], ticket["watch_branch_ids"]) == (
        "events",
        [part["id"]],
        [],
    )
    assert ticket["deadline_at"] - ticket["min_sleep_until"] == pytest.approx(1800 - 20)
    intent = service.get_record("task", context["task_id"], author)["handoff_intent"]
    assert intent["reason"] == "wait_for_events" and intent["peer_wait"] == ticket
    rejected = await call(tools, "wait", {"for": "tasks"})
    assert rejected["error"]["code"] == "INVALID_ARGUMENTS"


def test_the_waiters_own_moves_do_not_wake_it_and_a_peers_do(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    goal = service.query_nodes(exp["id"], alpha, node_type="goal")["items"][0]
    mine, theirs = lemma(service, exp, alpha, "Mine"), lemma(service, exp, beta, "Theirs")
    extra = lemma(service, exp, alpha, "Extra")
    for target in (mine, theirs):
        service.link_nodes(exp["id"], goal["id"], "depends_on", target["id"], beta, target["id"])
    agent, ticket = park(service, author, exp, alpha.branch_id, ids=[mine["id"]])
    # An own edge from a watched node moves the long pole, yet neither wakes the waiter.
    service.link_nodes(exp["id"], mine["id"], "depends_on", extra["id"], alpha, "own-link")
    assert reason(service, ticket, agent) == "waiting"
    publish(service, mine["id"], alpha, "partial", "own-publish")
    service.abandon_node(extra["id"], "Not needed.", alpha, "own-abandon")
    assert reason(service, ticket, agent) == "waiting"
    service.abandon_node(theirs["id"], "Dead end.", beta, "peer-abandon")
    assert reason(service, ticket, agent) == "long_pole_changed"
    _, ticket = park(service, author, exp, alpha.branch_id, ids=[mine["id"]])
    service.link_nodes(exp["id"], mine["id"], "motivated_by", theirs["id"], beta, "peer-link")
    assert service.peer_wait_status(ticket, agent)["detail"] == {
        "kind": "commons.edge_added",
        "aggregate_id": mine["id"],
    }
    events = service.events(author, limit=1000)
    edges = [e["payload"]["branch_id"] for e in events if e["kind"] == "commons.edge_added"]
    assert edges == [beta.branch_id] * 2 + [alpha.branch_id, beta.branch_id]
    moves = [e["payload"]["branch_id"] for e in events if e["kind"] == "commons.node_status"]
    assert moves == [alpha.branch_id, beta.branch_id]
    set_status(service, mine["id"], "abandoned")  # a platform move names no branch
    events = service.events(author, limit=1000)
    assert [e for e in events if e["kind"] == "commons.node_status"][-1]["payload"] == {
        "experiment_id": exp["id"],
        "node_id": mine["id"],
        "from": "open",
        "to": "abandoned",
        "reason": "platform test",
        "branch_id": None,
    }


def test_the_long_pole_is_recomputed_only_when_the_graph_changes(lab, monkeypatch):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    goal = service.query_nodes(exp["id"], alpha, node_type="goal")["items"][0]
    first, second = lemma(service, exp, beta, "First"), lemma(service, exp, beta, "Second")
    for target in (first, second):
        service.link_nodes(exp["id"], goal["id"], "depends_on", target["id"], beta, target["id"])
    agent, ticket = park(service, author, exp, alpha.branch_id)
    _, other = park(service, author, exp, alpha.branch_id)
    loads, read = [], service._experiment_nodes
    monkeypatch.setattr(
        service, "_experiment_nodes", lambda *args: loads.append(args) or read(*args)
    )
    service.abandon_node(first["id"], "Dead end.", beta, "abandon")
    for waiting in (ticket, ticket, other):  # one recompute serves every poll and waiter
        assert reason(service, waiting, agent) == "long_pole_changed"
    assert len(loads) == 1
    service.link_nodes(exp["id"], second["id"], "motivated_by", first["id"], beta, "more")
    assert reason(service, ticket, agent) == "long_pole_changed"
    assert len(loads) == 2


def test_a_graph_limit_wakes_the_waiter_instead_of_failing_the_run(lab, monkeypatch):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = lemma(service, exp, beta, "Node")
    agent, ticket = park(service, author, exp, alpha.branch_id)

    def too_large(*args):
        raise HarnessError("COMMONS_GRAPH_TOO_LARGE", "The commons graph is too large.")

    monkeypatch.setattr(service, "_experiment_nodes", too_large)
    service.abandon_node(node["id"], "Dead end.", beta, "abandon")
    assert service.peer_wait_status(ticket, agent) == {
        "ready": True,
        "reason": "wait_error",
        "message_id": None,
        "detail": {"code": "COMMONS_GRAPH_TOO_LARGE"},
    }

    def broken(*args):
        raise RuntimeError("database gone")

    monkeypatch.setattr(service, "_experiment_nodes", broken)
    with pytest.raises(RuntimeError):
        service.peer_wait_status(ticket, agent)
