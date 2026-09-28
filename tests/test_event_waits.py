"""S1 audit #14: waits that wake on relevant events, not only on one peer's message."""

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy
from commons_helpers import set_status, society_lab
from test_commons_sources import publish
from test_execution_responses import message
from test_research_loop_integration import PRICES, response, tool_call
from test_sharing import approaches
from test_society_tools import (
    LEAN,
    PROOF,
    FakeWorkspace,
    call,
    finish_task,
    lemma_args,
    mock_client,
    profile,
    run_manifest,
    running,
    scripted_society_route,
    society_runner,
)
from test_swarm_coordination_gaps import verified_receipt

from physharness import continuation, discussion
from physharness.commons_models import NodeCreate, NodePostCreate
from physharness.domain import ArtifactCreate, ContextBudget, Principal, TaskCreate, new_id
from physharness.errors import HarnessError
from physharness.execution import ResponsesRuntime, RuntimeLimits
from physharness.execution.admission import TokenRateGovernor
from physharness.orchestration import research_worker
from physharness.orchestration.research_worker import (
    ResearchTaskExecutor,
    ResearchTeamRunner,
    TeamRunManifest,
)
from physharness.storage import RecordRow
from physharness.worker_authority import worker_effects
from physharness.workforce_models import ConfigureWorkforceRequest

OPERATOR = Principal(id="operator", project_id="lab", role="operator")


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


def test_a_relevant_update_behind_a_hundred_skipped_events_wakes(lab):
    """Final review B-M1: the scan pages past skipped events (here the waiter's own posts)."""
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    mine = lemma(service, exp, alpha, "Mine")
    agent, ticket = park(service, author, exp, alpha.branch_id)
    for i in range(100):
        own = NodePostCreate(kind="finding", abstract=f"Note {i}.")
        service.post_on_node(mine["id"], own, alpha, f"own-{i}")
    assert reason(service, ticket, agent) == "waiting"
    service.post_on_node(
        mine["id"], NodePostCreate(kind="objection", abstract="Gap."), beta, "peer"
    )
    assert reason(service, ticket, agent) == "relevant_update"


@pytest.mark.parametrize(("own_posts", "woken"), [(3, "relevant_update"), (4, "waiting")])
def test_the_update_scan_is_bounded(lab, monkeypatch, own_posts, woken):
    monkeypatch.setattr(discussion, "UPDATE_SCAN_PAGE", 2)
    monkeypatch.setattr(discussion, "MAX_UPDATE_SCAN", 4)
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    mine = lemma(service, exp, alpha, "Mine")
    agent, ticket = park(service, author, exp, alpha.branch_id)
    for i in range(own_posts):
        own = NodePostCreate(kind="finding", abstract=f"Note {i}.")
        service.post_on_node(mine["id"], own, alpha, f"own-{i}")
    service.post_on_node(
        mine["id"], NodePostCreate(kind="objection", abstract="Gap."), beta, "peer"
    )
    assert reason(service, ticket, agent) == woken


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
    event = [e for e in service.events(author, limit=1000) if e["kind"] == "commons.node_claim"][-1]
    assert status == {
        "ready": True,
        "reason": "watched_event",
        "message_id": None,
        "detail": {"kind": "commons.node_claim", "aggregate_id": second["id"]},
        "sequence": event["sequence"],  # where the woken session is anchored
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


async def test_an_s1_peer_wait_resumed_mid_call_is_answered_not_fatal(lab):
    """Merge audit: an S1 checkpoint saved during wait(for="peer") re-dispatches that call on
    resume. The current schema has no such wait, so it is answered with a recoverable
    rejection, as a removed tool is, instead of a fatal INVALID_TOOL_ARGUMENTS."""
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    agent, context = running(service, author, exp, alpha.branch_id)
    tools = profile(service, agent, context)
    legacy = {"for": "peer", "ids": [beta.branch_id], "timeout_seconds": 60}
    rejected = await call(tools, "wait", legacy)
    assert set(rejected) == {"error"} and rejected["error"]["code"] == "TOOL_UNAVAILABLE"
    assert rejected["error"]["details"] == {"available_waits": ["tasks", "events"]}
    assert "for='events'" in rejected["error"]["remediation"]
    assert service.get_record("task", context["task_id"], author).get("handoff_intent") is None


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


@pytest.mark.parametrize("mover", ["peer", "own"])
def test_a_wait_anchors_on_what_the_agents_last_request_showed(lab, mover):
    """Merge audit: news that commits after the agent's last request was sent (while it
    generated, or while earlier tools of its response ran) and before its wait registers is
    still unseen, so it wakes the wait: a watched node's new claimant, and a long pole a peer
    moved. The waiter's own moves in that response stay no news."""
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    agent, context = running(service, author, exp, alpha.branch_id)  # the waiter, on alpha
    peer = beta if mover == "peer" else agent
    goal = service.query_nodes(exp["id"], alpha, node_type="goal")["items"][0]
    first, second = lemma(service, exp, peer, "First"), lemma(service, exp, peer, "Second")
    for target in (first, second):
        service.link_nodes(
            exp["id"], goal["id"], "depends_on", target["id"], alpha, f"l-{target['id']}"
        )
    anchor = service.event_anchor(exp["id"], agent)  # the last request's content, captured
    service.anchor_request(context["task_id"], context["holder"], context["fence"], anchor, agent)
    assert set(anchor["long_pole_ids"]) == {first["id"], second["id"]}
    service.claim_node(second["id"], "claim", peer, "claims-during-generation")
    service.abandon_node(first["id"], "Dead end.", peer, "moves-during-generation")

    def wait(ids, key):
        with worker_effects(agent, context["task_id"], context["holder"], context["fence"]):
            waited = service.request_event_wait(context["task_id"], ids, 600, agent, key)
        return {**waited["intent"]["peer_wait"], "min_sleep_until": 0}

    watched, unwatched = wait([second["id"]], "watch"), wait([], "no-watch")
    assert watched["event_after"] == unwatched["event_after"] == anchor["event_sequence"]
    if mover == "peer":
        assert set(unwatched["long_pole_ids"]) == {first["id"], second["id"]}
        assert reason(service, watched, agent) == "watched_event"
        assert reason(service, unwatched, agent) == "long_pole_changed"
    else:
        assert unwatched["long_pole_ids"] == [second["id"]]
        assert reason(service, watched, agent) == reason(service, unwatched, agent) == "waiting"


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


def test_a_wait_at_an_unchanged_graph_reads_the_long_pole_memo_under_the_lock(lab, monkeypatch):
    """Final review B-M9: the ticket's long-pole ids come from the memo, so a wait request
    at an unchanged graph computes the long pole only for its reply, after its command."""
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    goal = service.query_nodes(exp["id"], alpha, node_type="goal")["items"][0]
    part = lemma(service, exp, beta, "Part")
    service.link_nodes(exp["id"], goal["id"], "depends_on", part["id"], beta, "goal-part")
    park(service, author, exp, alpha.branch_id)  # the first request fills the memo
    commands, calls = [], []
    execute, compute = service._execute, service._goal_long_pole

    def command(*args, **kwargs):
        commands.append(True)
        try:
            return execute(*args, **kwargs)
        finally:
            commands.pop()

    monkeypatch.setattr(service, "_execute", command)
    monkeypatch.setattr(
        service, "_goal_long_pole", lambda *a, **k: calls.append(bool(commands)) or compute(*a, **k)
    )
    agent, context = running(service, author, exp, alpha.branch_id)
    with worker_effects(agent, context["task_id"], context["holder"], context["fence"]):
        waited = service.request_event_wait(context["task_id"], [], 600, agent, "again")
    assert calls == [False]  # only the reply's long pole, outside the command
    assert waited["intent"]["peer_wait"]["long_pole_ids"] == [part["id"]]
    assert [item["id"] for item in waited["long_pole"]] == [part["id"]]


async def scoped_waiter(service, author, exp, alpha, *, helper=False):
    """A joined until_proved recruit of alpha's elaborated trace lemma, parked on events;
    with ``helper``, it first recruits a joined helper of its own (``helper_id``).
    ``tools`` are those of alpha, the node's author."""
    agent, context = running(service, author, exp, alpha.branch_id)
    tools = profile(service, agent, context, workspace=FakeWorkspace())
    node = await call(tools, "commons_node", lemma_args())
    await call(
        tools, "commons_node", {"action": "set_lean_statement", "node_id": node["id"], **LEAN}
    )
    brief = {"brief": "Prove it.", "title": "Prover", "focus_node_id": node["id"]}
    recruited = await call(tools, "recruit", {**brief, "until_proved": True})
    task = service.get_record("task", recruited["task_id"], author)
    recruit, recruit_context = running(service, author, exp, task["branch_id"], task=task)
    helper_id = None
    if helper:
        recruit_tools = profile(service, recruit, recruit_context, workspace=FakeWorkspace())
        lookup = {"brief": "Look up.", "title": "Lookup"}
        helper_id = (await call(recruit_tools, "recruit", lookup))["task_id"]
    with worker_effects(recruit, task["id"], recruit_context["holder"], recruit_context["fence"]):
        waited = service.request_event_wait(task["id"], [], 600, recruit, "recruit-waits")
    ticket = {**waited["intent"]["peer_wait"], "min_sleep_until": 0}
    return SimpleNamespace(
        node=node, tools=tools, recruit=recruit, ticket=ticket, helper_id=helper_id
    )


@pytest.mark.parametrize("delivery", ["proved", "closed", "restated"])
async def test_a_scoped_waiter_wakes_once_its_scope_is_delivered(lab, delivery):
    """Final review B-I2: a scoped recruit's wait watches its own node, so it wakes (and then
    ends) once the node is proved, closed or restated, with or without a live claim."""
    service, author, exp, _, (alpha, _) = society_lab(lab)
    scoped = await scoped_waiter(service, author, exp, alpha)
    node_id = scoped.node["id"]
    assert reason(service, scoped.ticket, scoped.recruit) == "waiting"
    if delivery == "proved":
        await call(scoped.tools, "lean_check", {"source": PROOF, "node_id": node_id})
    elif delivery == "closed":
        set_status(service, node_id, "abandoned")
    else:
        changed = {**LEAN, "lean_statement": ": (2 : Nat) + 2 = 4"}
        await call(
            scoped.tools,
            "commons_node",
            {"action": "set_lean_statement", "node_id": node_id, **changed},
        )
    assert reason(service, scoped.ticket, scoped.recruit) == "scope_delivered"


async def test_a_scoped_waiter_is_woken_by_its_scope_only_once_it_can_end(lab):
    """A scoped recruit ends only once its own joined recruits settle; until then a wake for
    its delivered scope would only cost it a request (and repeat on its next wait)."""
    service, author, exp, _, (alpha, _) = society_lab(lab)
    scoped = await scoped_waiter(service, author, exp, alpha, helper=True)
    set_status(service, scoped.node["id"], "abandoned")
    assert reason(service, scoped.ticket, scoped.recruit) == "waiting"
    finish_task(service, scoped.helper_id)
    assert reason(service, scoped.ticket, scoped.recruit) == "scope_delivered"


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


# Runner side: native wake, event-head gating and the idle stop --------------------------------


def waiting_route(payloads, timeout_seconds, *, waits=1, ids=(), before_wait=None):
    """A provider whose first ``waits`` requests wait for events on ``ids`` (calling
    ``before_wait()`` first, when given); later requests finish."""

    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        payloads.append(json.loads(request.content))
        count = len(payloads)
        if count <= waits and before_wait is not None:
            before_wait()
        wait = {"for": "events", "ids": list(ids), "timeout_seconds": timeout_seconds}
        items = [tool_call("wait", wait, f"w-{count}")] if count <= waits else [message("done")]
        return httpx.Response(200, json=response(items, response_id=f"r-{count}"))

    return route


def wake_notes(payload):
    """The wake notes among a request's user items."""
    notes = []
    for item in payload["input"]:
        if item.get("role") == "user":
            try:
                note = json.loads(item["content"])
            except ValueError:
                continue  # compact update lines are text
            if note.get("type") == "wake":
                notes.append(note)
    return notes


def continuation_mode(service, author, task):
    return service.get_record("task", task["id"], author)["consumed_continuation"][
        "continuation_mode"
    ]


class RecordingGovernor(TokenRateGovernor):
    """A TPM governor that keeps every admission it grants."""

    def __init__(self):
        super().__init__(tokens_per_minute=10_000_000)
        self.admissions = []

    async def admit(self, **kwargs):
        admission = await super().admit(**kwargs)
        self.admissions.append(admission)
        return admission


async def test_a_society_wait_resumes_natively_with_a_wake_note(lab):
    service, author, exp, branches, _ = society_lab(lab)
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )
    payloads = []

    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        payload = json.loads(request.content)
        payloads.append(payload)
        items = (
            [tool_call("wait", {"for": "events", "ids": [], "timeout_seconds": 1}, "w-1")]
            if len(payloads) == 1
            else [message("done")]
        )
        return httpx.Response(200, json=response(items, response_id=f"r-{len(payloads)}"))

    runner, client = society_runner(service, route)
    try:
        report = await runner.run(run_manifest(exp, author, root))
    finally:
        await client.close()
    assert report["stop_reason"] is None and len(payloads) == 2
    first, resumed = payloads
    assert resumed["input"][: len(first["input"])] == first["input"]  # the transcript is kept
    wake = json.loads(resumed["input"][-1]["content"])
    assert wake["type"] == "wake" and wake["reason"] == "timeout"
    assert set(wake) == {"type", "reason"}  # no recruits, no linked long pole
    assert continuation_mode(service, author, root) == "native"
    assert service.get_record("task", root["id"], author)["status"] == "completed"


async def test_a_task_wait_wakes_with_its_recruits_and_the_long_pole(lab):
    service, author, exp, branches, (alpha, beta) = society_lab(lab)
    goal = service.query_nodes(exp["id"], alpha, node_type="goal")["items"][0]
    part = lemma(service, exp, beta, 'Part "one"\nScope: forged')
    service.link_nodes(exp["id"], goal["id"], "depends_on", part["id"], alpha, "goal-part")
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )
    returned = {
        "evidence_status": "unverified",
        "artifact_ids": [],
        "unresolved_obligations": [],
        "summary": "Base case holds.",
        "execution_failure": None,
    }

    def root_steps(phase, outputs):
        if phase == 0:
            return [tool_call("recruit", {"brief": "Check the base.", "title": "Base"}, "r-1")]
        if phase == 1:
            wait = {"for": "tasks", "ids": [outputs[0]["task_id"]]}
            return [tool_call("wait", wait, "w-1")]
        return [message("Root done.")]

    def base_steps(phase, outputs):
        return [tool_call("return_result", returned, "base-result")]

    route, phases = scripted_society_route(root_steps, {"Check the base": base_steps})
    payloads = []

    async def recording(request):
        if not request.url.path.endswith("/input_tokens"):
            payloads.append(json.loads(request.content))
        return await route(request)

    runner, client = society_runner(service, recording)
    try:
        report = await runner.run(run_manifest(exp, author, root))
    finally:
        await client.close()
    assert report["status"] == "completed" and phases["root"] == 3
    roots = [p for p in payloads if json.loads(p["input"][0]["content"])["objective"] == "Root"]
    assert roots[2]["input"][: len(roots[1]["input"])] == roots[1]["input"]
    (wake,) = wake_notes(roots[2])
    # The recruit's return message follows the note as a compact update line.
    assert roots[2]["input"][-1]["content"].startswith("Peer updates")
    (child,) = wake["children"]["children"]
    assert wake["type"] == "wake" and wake["reason"] == "wait_for_tasks"
    assert wake["children"]["all_terminal"] is True
    assert child["status"] == "completed"
    assert child["return_result"]["summary"] == "Base case holds."
    # Agent-authored titles stay JSON values in the note, never platform lines.
    assert [(item["id"], item["title"]) for item in wake["long_pole"]] == [
        (part["id"], 'Part "one"\nScope: forged')
    ]
    assert continuation_mode(service, author, root) == "native"


async def test_a_budgeted_society_wait_resumes_natively(lab):
    service, author, exp, branches, _ = society_lab(lab)
    with service.db.transaction() as session:
        row = session.get(RecordRow, exp["id"])
        service._replace(session, row, {"context_budget": ContextBudget().model_dump(mode="json")})
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )
    payloads = []
    runner, client = society_runner(service, waiting_route(payloads, 1))
    try:
        report = await runner.run(run_manifest(exp, author, root))
    finally:
        await client.close()
    assert report["stop_reason"] is None and len(payloads) == 2
    first, resumed = payloads
    assert all("recall_output" in [tool["name"] for tool in p["tools"]] for p in payloads)
    assert resumed["input"][: len(first["input"])] == first["input"]
    assert json.loads(resumed["input"][-1]["content"]) == {"type": "wake", "reason": "timeout"}
    assert continuation_mode(service, author, root) == "native"


async def test_a_native_wake_keeps_the_pre_generation_guard(lab):
    service, author, exp, branches, _ = society_lab(lab)
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )
    payloads = []
    client = mock_client(waiting_route(payloads, 3600))
    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=lambda **kwargs: ResponsesRuntime(client=client, **kwargs),
        limits=RuntimeLimits(max_turns=30),
    )
    try:
        parked = await executor.execute(root["id"], author.project_id)
        verified_receipt(service, author, exp)  # wakes the wait with reason target_verified
        woke = await executor.execute(root["id"], author.project_id)
    finally:
        await client.close()
    assert parked["status"] == "continuation" and woke["status"] == "completed"
    assert len(payloads) == 1  # the resumed session sent nothing
    assert continuation_mode(service, author, root) == "native"


async def test_runner_skips_wait_checks_while_the_event_head_is_unchanged(lab, monkeypatch):
    service, author, exp, branches, _ = society_lab(lab)
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )
    checks, status = [], service.peer_wait_status
    monkeypatch.setattr(
        service, "peer_wait_status", lambda *args: checks.append(args) or status(*args)
    )
    payloads = []
    runner, client = society_runner(service, waiting_route(payloads, 2))
    try:
        report = await runner.run(run_manifest(exp, author, root))
    finally:
        await client.close()
    assert report["stop_reason"] is None and len(payloads) == 2
    # The runner checks on parking (min_sleep) and at the deadline; the executor once more.
    assert len(checks) <= 3


async def test_an_all_parked_society_stops_idle(lab, monkeypatch):
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 1)
    service, author, exp, branches, _ = society_lab(lab)
    roots = [
        service.create_task(
            TaskCreate(branch_id=branch["id"], objective=f"Root {i}"), author, f"root-{i}"
        )
        for i, branch in enumerate(branches)
    ]
    payloads = []
    client = mock_client(waiting_route(payloads, 3600, waits=2))
    governor = RecordingGovernor()
    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=lambda **kwargs: ResponsesRuntime(client=client, **kwargs),
        limits=RuntimeLimits(max_turns=30),
        token_governor=governor,
    )
    manifest = TeamRunManifest(
        experiment_id=exp["id"],
        project_id=author.project_id,
        mode="replay",
        task_ids=[root["id"] for root in roots],
        max_concurrency=2,
        max_tasks=4,
        timeout_seconds=20,
    )
    started = asyncio.get_running_loop().time()
    try:
        report = await ResearchTeamRunner(service, executor=executor).run(manifest)
    finally:
        await client.close()
    assert report["stop_reason"] == "SOCIETY_IDLE" and len(payloads) == 2
    assert asyncio.get_running_loop().time() - started < 10
    for root in roots:
        task = service.get_record("task", root["id"], author)
        assert task["status"] == "queued"
        assert task["ready_continuation"]["reason"] == "wait_for_events"
    # A parked task holds no worker slot and no rate admission.
    assert service.ledger(exp["id"], author)["active_workers"] == 0
    assert len(governor.admissions) == 2
    assert not any(admission.open for admission in governor.admissions)


async def test_a_new_event_wakes_a_checked_wait_through_the_runner(lab, monkeypatch):
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, _ = society_lab(lab, referee_slots=0)
    roots = [
        service.create_task(TaskCreate(branch_id=branch["id"], objective=name), author, name)
        for branch, name in zip(branches, ("Waiter", "Sender"), strict=True)
    ]
    reasons, status = [], service.peer_wait_status

    def recording(*args):
        result = status(*args)
        reasons.append(result["reason"])
        return result

    monkeypatch.setattr(service, "peer_wait_status", recording)
    requests = {"Waiter": [], "Sender": []}

    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        payload = json.loads(request.content)
        name = json.loads(payload["input"][0]["content"])["objective"]
        requests[name].append(payload)
        if name == "Waiter" and len(requests[name]) == 1:
            wait = {"for": "events", "ids": [], "timeout_seconds": 3600}
            items = [tool_call("wait", wait, "w-1")]
        elif name == "Sender" and len(requests[name]) == 1:
            while "waiting" not in reasons:  # message only once the runner found nothing
                await asyncio.sleep(0.05)
            sent = {"to": branches[0]["id"], "content": "Try the trace lemma."}
            items = [tool_call("message", sent, "m-1")]
        else:
            items = [message(f"{name} done.")]
        return httpx.Response(
            200, json=response(items, response_id=f"{name}-{len(requests[name])}")
        )

    runner, client = society_runner(service, route)
    manifest = TeamRunManifest(
        experiment_id=exp["id"],
        project_id=author.project_id,
        mode="replay",
        task_ids=[root["id"] for root in roots],
        max_concurrency=2,
        timeout_seconds=20,
    )
    try:
        report = await runner.run(manifest)
    finally:
        await client.close()
    assert report["status"] == "completed" and report["stop_reason"] is None
    assert reasons[0] == "waiting" and reasons[-1] == "relevant_update"
    first, resumed = requests["Waiter"]
    assert resumed["input"][: len(first["input"])] == first["input"]
    assert wake_notes(resumed) == [{"type": "wake", "reason": "relevant_update"}]
    assert "Try the trace lemma." in resumed["input"][-1]["content"]  # the compact update line


async def test_a_stale_wait_check_is_repeated_without_new_events(lab, monkeypatch):
    """A PostgreSQL event can commit below a head already seen, so a parked wait is checked
    at least every EVENT_WAIT_MAX_STALE_SECONDS even while the head stands still."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, _ = society_lab(lab, referee_slots=0)
    roots = [
        service.create_task(TaskCreate(branch_id=branch["id"], objective=name), author, name)
        for branch, name in zip(branches, ("Waiter", "Busy"), strict=True)
    ]
    reasons, status = [], service.peer_wait_status

    def recording(*args):
        result = status(*args)
        reasons.append(result["reason"])
        return result

    monkeypatch.setattr(service, "peer_wait_status", recording)
    skew, now = [0.0], research_worker.utcnow  # the runner's injected wall clock
    monkeypatch.setattr(research_worker, "utcnow", lambda: now() + timedelta(seconds=skew[0]))
    counts = {}
    requests = {"Waiter": 0, "Busy": 0}

    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        name = json.loads(json.loads(request.content)["input"][0]["content"])["objective"]
        requests[name] += 1
        if name == "Waiter":
            wait = {"for": "events", "ids": [], "timeout_seconds": 3600}
            return httpx.Response(200, json=response([tool_call("wait", wait, "w-1")]))
        # Busy holds its slot, writing nothing, while the Waiter stays parked.
        while not reasons:
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)  # a check owed to a move before Busy's request lands now
        before = len(reasons)
        await asyncio.sleep(1)  # four runner loops at an unchanged head
        counts["quiet"] = len(reasons) - before
        skew[0] = research_worker.EVENT_WAIT_MAX_STALE_SECONDS
        for _ in range(40):
            if len(reasons) > before:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)  # and no more until it is stale again
        counts["stale"] = len(reasons) - before
        return httpx.Response(200, json=response([message("Busy done.")]))

    runner, client = society_runner(service, route)
    manifest = TeamRunManifest(
        experiment_id=exp["id"],
        project_id=author.project_id,
        mode="replay",
        task_ids=[root["id"] for root in roots],
        max_concurrency=2,
        timeout_seconds=20,
    )
    try:
        report = await runner.run(manifest)
    finally:
        await client.close()
    assert counts == {"quiet": 0, "stale": 1}
    assert requests == {"Waiter": 1, "Busy": 1}
    assert report["stop_reason"] == "SOCIETY_IDLE"  # once Busy is done, all wait


def manifest_for(exp, author, roots, **limits):
    return TeamRunManifest(
        experiment_id=exp["id"],
        project_id=author.project_id,
        mode="replay",
        task_ids=[root["id"] for root in roots],
        **{"max_concurrency": 2, "timeout_seconds": 20, **limits},
    )


@pytest.mark.parametrize("state", [None, "queued", "running"])
async def test_another_live_task_of_the_experiment_keeps_the_run_going(lab, monkeypatch, state):
    """The idle stop does not assume one runner: a task this run does not own, queued or
    running (another runner's or worker's), may still wake a waiter. Without one the run
    stops idle well within the same timeout (merge audit: an idle stop takes over 3 s)."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, _ = society_lab(lab)
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )
    if state:
        other = service.create_task(
            TaskCreate(branch_id=branches[1]["id"], objective="Elsewhere"), author, "other"
        )
        if state == "running":
            service.acquire_task(other["id"], "another-runner", 60, OPERATOR, "lease-other")
        assert service.get_record("task", other["id"], author)["status"] == state
    payloads = []
    runner, client = society_runner(service, waiting_route(payloads, 3600))
    try:
        report = await runner.run(manifest_for(exp, author, [root], timeout_seconds=10))
    finally:
        await client.close()
    assert report["stop_reason"] == ("TEAM_TIMEOUT" if state else "SOCIETY_IDLE")
    assert len(payloads) == 1
    assert service.get_record("task", root["id"], author)["ready_continuation"]


async def test_a_recruit_beyond_max_tasks_stops_the_idle_run_at_the_task_limit(lab, monkeypatch):
    """Merge audit: a recruit this run may not start (max_tasks reached) is no live work, so
    once the rest of the society waits the run stops TEAM_TASK_LIMIT instead of sleeping to
    TEAM_TIMEOUT; the recruit stays queued for a later run."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, _ = society_lab(lab)
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )

    def root_steps(phase, outputs):
        if phase == 0:
            helper = {"brief": "Help.", "title": "Helper", "detached": True}
            return [tool_call("recruit", helper, "r-1")]
        if phase == 1:
            wait = {"for": "events", "ids": [], "timeout_seconds": 3600}
            return [tool_call("wait", wait, "w-1")]
        return [message("Root done.")]

    route, phases = scripted_society_route(root_steps, {"Help": lambda p, o: [message("ok")]})
    runner, client = society_runner(service, route)
    started = asyncio.get_running_loop().time()
    try:
        report = await runner.run(manifest_for(exp, author, [root], max_tasks=1))
    finally:
        await client.close()
    assert report["stop_reason"] == "TEAM_TASK_LIMIT" and phases == {"root": 2, "referee": 0}
    assert asyncio.get_running_loop().time() - started < 10
    (helper,) = [
        task for task in service.list_records("task", author, exp["id"]) if task["id"] != root["id"]
    ]
    assert helper["status"] == "queued" and helper["id"] in report["remaining_task_ids"]


@pytest.mark.parametrize("woken", [False, True])
async def test_another_runners_parked_waiter_counts_as_waiting(lab, monkeypatch, woken):
    """Merge audit: a task another runner parked on a society wait is waiting, not live work,
    once this run checks its wait the same way: two runners of one society each stop idle.
    If its wait can wake (here a message reached it), its runner may act, so no idle stop."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, (alpha, beta) = society_lab(lab)
    theirs = service.create_task(
        TaskCreate(branch_id=branches[1]["id"], objective="Theirs"), author, "theirs"
    )
    payloads = []
    runner, client = society_runner(service, waiting_route(payloads, 3600, waits=2))
    try:
        first = await runner.run(manifest_for(exp, author, [theirs]))
        if woken:
            service.send_society_message(alpha.branch_id, beta.branch_id, "Hi.", [], alpha, "m")
        mine = service.create_task(
            TaskCreate(branch_id=branches[0]["id"], objective="Mine"), author, "mine"
        )
        report = await runner.run(manifest_for(exp, author, [mine], timeout_seconds=10))
    finally:
        await client.close()
    assert first["stop_reason"] == "SOCIETY_IDLE" and len(payloads) == 2
    assert report["stop_reason"] == ("TEAM_TIMEOUT" if woken else "SOCIETY_IDLE")
    for task in (mine, theirs):
        assert service.get_record("task", task["id"], author)["ready_continuation"]


async def test_a_due_synthesis_is_scheduled_before_an_idle_stop(lab, monkeypatch):
    """Posts made just before the last agent parks make a synthesis due; the runner ticks
    the synthesis schedule before it may stop idle, and runs the synthesis."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, (_, beta) = society_lab(lab)
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )

    def discuss():
        # Platform status posts on four node threads, then synthesis every four posts.
        for title in ("Trace lemma", "Gap lemma", "Cut lemma", "Sum lemma"):
            set_status(service, lemma(service, exp, beta, title)["id"], "abandoned")
        request = ConfigureWorkforceRequest(synthesis_interval_posts=4)
        service.configure_workforce(exp["id"], request, OPERATOR, "synthesis-on")

    payloads = []
    runner, client = society_runner(service, waiting_route(payloads, 3600, before_wait=discuss))
    try:
        report = await runner.run(run_manifest(exp, author, root))
    finally:
        await client.close()
    synthesis = [
        task for task in service.list_records("task", author, exp["id"]) if task.get("synthesis")
    ]
    assert [task["status"] for task in synthesis] == ["completed"]
    objectives = [json.loads(p["input"][0]["content"])["objective"] for p in payloads]
    assert objectives[0] == "Root"
    assert any(objective.startswith("Compare only the sampled") for objective in objectives)
    assert report["stop_reason"] == "SOCIETY_IDLE"
    assert service.get_record("task", root["id"], author)["ready_continuation"]


async def test_a_due_synthesis_refused_admission_is_not_scheduled(lab, monkeypatch):
    """Merge audit: near the end of a budget, dollar admission refuses a due synthesis. The
    tick schedules nothing, the run stops idle and writes its report instead of raising."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, (_, beta) = society_lab(lab)
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )

    def discuss():
        for title in ("Trace lemma", "Gap lemma", "Cut lemma", "Sum lemma"):
            set_status(service, lemma(service, exp, beta, title)["id"], "abandoned")
        request = ConfigureWorkforceRequest(
            synthesis_interval_posts=4, admission_floor_usd="1000000"
        )
        service.configure_workforce(exp["id"], request, OPERATOR, "synthesis-on")

    payloads = []
    runner, client = society_runner(service, waiting_route(payloads, 3600, before_wait=discuss))
    try:
        report = await runner.run(run_manifest(exp, author, root))
    finally:
        await client.close()
    assert report["stop_reason"] == "SOCIETY_IDLE" and len(payloads) == 1
    tasks = service.list_records("task", author, exp["id"])
    assert not any(task.get("synthesis") for task in tasks)
    assert service.get_record("artifact", report["artifact_id"], author)["artifact_kind"] == (
        "team_run_report"
    )


async def test_the_wake_note_carries_the_watched_events_detail(lab, monkeypatch):
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, (_, beta) = society_lab(lab)
    node = lemma(service, exp, beta, "Watched")
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )
    payloads = []
    client = mock_client(waiting_route(payloads, 3600, ids=[node["id"]]))
    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=lambda **kwargs: ResponsesRuntime(client=client, **kwargs),
        limits=RuntimeLimits(max_turns=30),
    )
    try:
        parked = await executor.execute(root["id"], author.project_id)
        service.claim_node(node["id"], "claim", beta, "beta-claims")
        woke = await executor.execute(root["id"], author.project_id)
    finally:
        await client.close()
    assert parked["status"] == "continuation" and woke["status"] == "completed"
    assert wake_notes(payloads[1]) == [
        {
            "type": "wake",
            "reason": "watched_event",
            "detail": {"kind": "commons.node_claim", "aggregate_id": node["id"]},
        }
    ]


def anchoring_executor(service, route):
    client = mock_client(route)
    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=lambda **kwargs: ResponsesRuntime(client=client, **kwargs),
        limits=RuntimeLimits(max_turns=30),
    )
    return executor, client


def during_reservations(monkeypatch, actions):
    """Run ``actions[n]()``, when given, inside the worker's n-th model reservation: after the
    request's input was built and before it is sent, as a reservation that waits for other
    holds to settle (or a TPM admission wait) would."""
    reserve, count = research_worker._reserve_model_with_wait, []

    async def reserving(*args, **kwargs):
        count.append(1)
        if (action := actions.get(len(count) - 1)) is not None:
            action()
        return await reserve(*args, **kwargs)

    monkeypatch.setattr(research_worker, "_reserve_model_with_wait", reserving)


@pytest.mark.parametrize("when", ["generation", "reservation"])
async def test_a_watched_event_during_the_waiters_last_request_wakes_it(lab, monkeypatch, when):
    """Merge audit: a builder request's anchor is taken when its content is captured, so a
    claim on a watched node made while the final request generates, or while it waits for its
    reservation (or TPM admission) with its input already built, wakes the wait it asks for."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, (_, beta) = society_lab(lab)
    node = lemma(service, exp, beta, "Watched")
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )
    claimed = []

    def claim():
        claimed.append(service.claim_node(node["id"], "claim", beta, "beta-claims"))

    if when == "reservation":
        during_reservations(monkeypatch, {0: claim})
    payloads = []
    during = claim if when == "generation" else None
    route = waiting_route(payloads, 3600, ids=[node["id"]], before_wait=during)
    executor, client = anchoring_executor(service, route)
    try:
        parked = await executor.execute(root["id"], author.project_id)
        woke = await executor.execute(root["id"], author.project_id)
    finally:
        await client.close()
    assert claimed and parked["status"] == "continuation" and woke["status"] == "completed"
    assert "beta-claims" not in json.dumps(payloads[0])  # the request never showed it
    assert wake_notes(payloads[1]) == [
        {
            "type": "wake",
            "reason": "watched_event",
            "detail": {"kind": "commons.node_claim", "aggregate_id": node["id"]},
        }
    ]


async def test_a_woken_session_is_anchored_at_the_event_its_wake_note_names(lab, monkeypatch):
    """Merge audit: a woken wait resumes anchored at the watched event its wake note names,
    not when the resumed request is sent. A second watched event before the wake (unnamed),
    or one while the resumed request waits for its reservation, wakes the next wait; the
    named event never wakes it again."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, (_, beta) = society_lab(lab)
    first, second, third = (lemma(service, exp, beta, title) for title in ("A", "B", "C"))
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )
    agent = Principal(
        id="checker",
        project_id=author.project_id,
        role="agent",
        experiment_id=exp["id"],
        branch_id=branches[0]["id"],
    )

    def claim(node):
        return lambda: service.claim_node(node["id"], "claim", beta, f"claim-{node['id']}")

    def woke_on():
        """The parked wait's wake reason and the watched node it names."""
        task = service.get_record("task", root["id"], author)
        status = service.peer_wait_status(task["ready_continuation"]["peer_wait"], agent)
        return status["reason"], (status["detail"] or {}).get("aggregate_id")

    during_reservations(monkeypatch, {2: claim(third)})  # the third request's input is built
    payloads = []
    ids = [first["id"], second["id"], third["id"]]
    executor, client = anchoring_executor(service, waiting_route(payloads, 3600, waits=4, ids=ids))
    try:
        await executor.execute(root["id"], author.project_id)
        claim(first)()
        claim(second)()  # both before the wake: the note names only the first
        await executor.execute(root["id"], author.project_id)
        assert wake_notes(payloads[1])[-1]["detail"]["aggregate_id"] == first["id"]
        assert woke_on() == ("watched_event", second["id"])
        await executor.execute(root["id"], author.project_id)
        assert wake_notes(payloads[2])[-1]["detail"]["aggregate_id"] == second["id"]
        assert woke_on() == ("watched_event", third["id"])
        await executor.execute(root["id"], author.project_id)
        assert wake_notes(payloads[3])[-1]["detail"]["aggregate_id"] == third["id"]
        assert woke_on() == ("waiting", None)  # all shown: nothing wakes it again
    finally:
        await client.close()


async def test_a_woken_wait_keeps_news_on_nodes_it_did_not_watch(lab, monkeypatch):
    """Merge audit: the agent waits on X; then Y changes, and X's later event wakes it. Its
    wake note names only X's event, so when it next waits on X and Y, Y's earlier event still
    wakes it: only the named event counts as seen, not everything before it."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, (_, beta) = society_lab(lab)
    x, y = lemma(service, exp, beta, "X"), lemma(service, exp, beta, "Y")
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )
    watches, payloads = [[x["id"]], [x["id"], y["id"]], [x["id"], y["id"]]], []

    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        payloads.append(json.loads(request.content))
        count = len(payloads)
        wait = {"for": "events", "ids": watches[count - 1], "timeout_seconds": 3600}
        items = [tool_call("wait", wait, f"w-{count}")] if count <= len(watches) else []
        return httpx.Response(
            200, json=response(items or [message("done")], response_id=f"r-{count}")
        )

    agent = Principal(
        id="checker",
        project_id=author.project_id,
        role="agent",
        experiment_id=exp["id"],
        branch_id=branches[0]["id"],
    )

    def woke_on():
        task = service.get_record("task", root["id"], author)
        status = service.peer_wait_status(task["ready_continuation"]["peer_wait"], agent)
        return status["reason"], (status["detail"] or {}).get("aggregate_id")

    executor, client = anchoring_executor(service, route)
    try:
        await executor.execute(root["id"], author.project_id)  # waits on X
        service.claim_node(y["id"], "claim", beta, "claims-y")  # unwatched yet
        service.claim_node(x["id"], "claim", beta, "claims-x")  # wakes the wait
        await executor.execute(root["id"], author.project_id)  # waits on X and Y
        assert wake_notes(payloads[1])[-1]["detail"]["aggregate_id"] == x["id"]
        assert woke_on() == ("watched_event", y["id"])
        await executor.execute(root["id"], author.project_id)
        assert wake_notes(payloads[2])[-1]["detail"]["aggregate_id"] == y["id"]
        assert woke_on() == ("waiting", None)  # neither named event wakes it again
    finally:
        await client.close()


async def test_a_long_run_of_bare_waits_moves_the_anchor_to_the_named_event(lab):
    """Merge audit: the seen events a woken anchor carries are bounded; past the bound it
    moves on to the named event, as a later anchor would."""
    service, author, exp, branches, _ = society_lab(lab)
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )
    agent = Principal(
        id="worker",
        project_id=author.project_id,
        role="agent",
        experiment_id=exp["id"],
        branch_id=branches[0]["id"],
    )
    executor, client = anchoring_executor(service, waiting_route([], 1))
    await client.close()

    def anchor(seen):
        ticket = {"kind": "events", "event_after": 5, "seen_sequences": seen}
        woken = {"reason": "wait_for_events", "peer_wait": ticket}
        wake = {"reason": "watched_event", "sequence": 99}
        return executor._session_anchor(root["id"], agent, exp, woken, wake, recovering=False)

    full = list(range(6, 6 + continuation.MAX_SEEN_EVENTS))
    assert anchor(full[:-1]) == {
        "event_sequence": 5,
        "long_pole_ids": None,
        "seen_sequences": [*full[:-1], 99],
    }
    assert anchor(full) == {"event_sequence": 99, "long_pole_ids": None}


def test_the_event_head_moves_only_on_events_that_can_wake_a_waiter(lab):
    """Final review B-I3: model-turn accounting and other experiments' commons events leave
    the head alone, so they cause no wake checks."""
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    lemma(service, exp, beta, "First")
    head = service.event_head(author, exp["id"])
    assert head > 0
    with service.db.transaction() as session:  # what every model request writes
        for kind in ("resources.reserved", "resources.settled"):
            service._event(session, author, new_id(), kind, exp["id"], {"id": new_id()})
    assert service.event_head(author, exp["id"]) == head
    _, _, other, _, (stranger, _) = society_lab(lab, prefix="other")
    lemma(service, other, stranger, "Elsewhere")
    assert service.event_head(author, exp["id"]) == head
    lemma(service, exp, beta, "New")
    moved = service.event_head(author, exp["id"])
    assert moved > head
    service.send_society_message(beta.branch_id, alpha.branch_id, "Hi.", [], beta, "m")
    assert service.event_head(author, exp["id"]) > moved
    stranger = Principal(id="stranger", project_id="elsewhere", role="operator")
    assert service.event_head(stranger, exp["id"]) == 0


def query_plans(service, run, marker):
    """The SQLite plans of the statements containing ``marker`` that ``run()`` executes."""
    queries = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if marker in statement:
            queries.append((statement, parameters))

    sqlalchemy.event.listen(service.db.engine, "before_cursor_execute", capture)
    try:
        run()
    finally:
        sqlalchemy.event.remove(service.db.engine, "before_cursor_execute", capture)
    assert queries
    with service.db.engine.connect() as connection:
        return [
            [row[-1] for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + sql, params)]
            for sql, params in queries
        ]


async def test_wait_queries_use_the_experiment_indexes(lab):
    """Merge audit: a bound JSON path never matches an expression index, so the event head and
    the graph checks inline theirs, and a scoped waiter's recruit lookup names its experiment."""
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    scoped = await scoped_waiter(service, author, exp, alpha)
    set_status(service, lemma(service, exp, beta, "Moved")["id"], "abandoned")
    indexed = "events_discussion_experiment_sequence (project_id=? AND kind=? AND <expr>=?"
    (head,) = query_plans(service, lambda: service.event_head(author, exp["id"]), "UNION ALL")
    assert sum(indexed in step for step in head) == len(continuation.WAKE_KINDS)
    graph = query_plans(
        service, lambda: service.peer_wait_status(scoped.ticket, scoped.recruit), "events.kind IN"
    )
    assert [plan for plan in graph if not any(indexed in step for step in plan)] == []
    set_status(service, scoped.node["id"], "abandoned")  # delivered: its recruits are read
    (children,) = query_plans(
        service,
        lambda: service.peer_wait_status(scoped.ticket, scoped.recruit),
        "reply_to_parent_task_id",
    )
    assert any(
        "records_project_kind_experiment_keyset (project_id=? AND kind=? AND <expr>=?)" in step
        for step in children
    )


async def test_legacy_waits_still_resume_portably(lab, monkeypatch):
    service, author, exp, branches, _ = approaches(lab, "ideas")
    heads = []
    monkeypatch.setattr(service, "event_head", lambda actor: heads.append(actor) or 0)
    task = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Legacy"), author, "legacy"
    )
    payloads = []

    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        payloads.append(json.loads(request.content))
        wait = {"recipient_branch_id": branches[1]["id"], "timeout_seconds": 1}
        items = [tool_call("wait_for_peer", wait, "w-1")] if len(payloads) == 1 else [message("ok")]
        return httpx.Response(200, json=response(items, response_id=f"r-{len(payloads)}"))

    runner, client = society_runner(service, route)
    try:
        report = await runner.run(run_manifest(exp, author, task))
    finally:
        await client.close()
    assert report["status"] == "completed" and len(payloads) == 2
    assert continuation_mode(service, author, task) == "portable"
    resumed = payloads[1]["input"]
    assert not any(item.get("type") == "function_call" for item in resumed)  # a fresh prompt
    assert heads == []  # a legacy run never reads the event head


# Final review: scoped recruits, wake-check cost and the idle stop ------------------------------


async def test_a_parked_scoped_recruit_wakes_when_a_peer_proves_its_node(lab, monkeypatch):
    """Final review B-I2 (the probe): a joined recruit parks on events with its focus claim
    lapsed, then a peer publishes its node's complete source. The recruit wakes and ends
    scope_proved without another request, and its parent resumes: no false SOCIETY_IDLE."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, (alpha, _) = society_lab(lab)
    agent, context = running(service, author, exp, alpha.branch_id)
    tools = profile(service, agent, context, workspace=FakeWorkspace())
    node = await call(tools, "commons_node", lemma_args())
    await call(
        tools, "commons_node", {"action": "set_lean_statement", "node_id": node["id"], **LEAN}
    )
    node = service.read_node(node["id"], agent)["node"]
    finish_task(service, context["task_id"])  # alpha's writer leaves no live task
    root = service.create_task(
        TaskCreate(branch_id=branches[1]["id"], objective="Root"), author, "root"
    )
    reasons, proved, status = [], [], service.peer_wait_status

    def proving(ticket, actor):
        result = status(ticket, actor)
        reasons.append(result["reason"])
        if result["reason"] == "waiting" and not proved:
            proved.append(ticket["task_id"])
            recruit = Principal(
                id="lapse",
                role="agent",
                project_id=author.project_id,
                experiment_id=exp["id"],
                branch_id=ticket["branch_id"],
            )
            service.claim_node(node["id"], "release", recruit, "lapse")  # the claim lapsed
            digest = node["lean_statement_sha256"]
            publish(service, node["id"], alpha, "complete", "alpha", lean_statement_sha256=digest)
        return result

    monkeypatch.setattr(service, "peer_wait_status", proving)

    def root_steps(phase, outputs):
        if phase == 0:
            brief = {"brief": "Prove it.", "title": "Prover", "focus_node_id": node["id"]}
            return [tool_call("recruit", {**brief, "until_proved": True}, "r-1")]
        if phase == 1:
            return [tool_call("wait", {"for": "tasks", "ids": [outputs[0]["task_id"]]}, "w-1")]
        return [message("Root done.")]

    def prover_steps(phase, outputs):
        wait = {"for": "events", "ids": [], "timeout_seconds": 3600}
        return [tool_call("wait", wait, "w-2")] if phase == 0 else [message("Unneeded.")]

    route, phases = scripted_society_route(root_steps, {"Prove it": prover_steps})
    runner, client = society_runner(service, route)
    try:
        report = await runner.run(run_manifest(exp, author, root))
    finally:
        await client.close()
    assert report["stop_reason"] is None and report["status"] == "completed"
    assert phases["Prove it"] == 1 and phases["root"] == 3  # no request after the proof
    assert "scope_delivered" in reasons
    recruit = service.get_record("task", proved[0], author)
    assert recruit["status"] == "completed"
    source = service.read_node(node["id"], alpha)["node"]["lean_source"]
    assert recruit["return_result"]["artifact_ids"][0] == source["artifact_id"]
    note = service.artifact_content(recruit["evidence_ids"][0], author).decode()
    assert note == research_worker.COMPLETION_NOTES["scope_proved"]
    assert service.get_record("task", root["id"], author)["status"] == "completed"


async def test_a_scoped_recruit_parked_on_a_detached_helper_ends_when_its_node_is_proved(
    lab, monkeypatch
):
    """Merge audit: the root waits for its until_proved recruit, which waits for tasks on a
    detached helper parked on events. A peer then proves the recruit's node. The recruit
    wakes without another request although its helper is pending, ends scope_proved, and
    the root resumes: no false SOCIETY_IDLE with both stranded. The helper, not joined,
    keeps its wait."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, (alpha, _) = society_lab(lab)
    agent, context = running(service, author, exp, alpha.branch_id)
    tools = profile(service, agent, context, workspace=FakeWorkspace())
    node = await call(tools, "commons_node", lemma_args())
    await call(
        tools, "commons_node", {"action": "set_lean_statement", "node_id": node["id"], **LEAN}
    )
    node = service.read_node(node["id"], agent)["node"]
    finish_task(service, context["task_id"])
    root = service.create_task(
        TaskCreate(branch_id=branches[1]["id"], objective="Root"), author, "root"
    )
    proved, status = [], service.peer_wait_status

    def proving(ticket, actor):
        result = status(ticket, actor)
        if result["reason"] == "waiting" and not proved:  # the helper parked, checked
            proved.append(True)
            digest = node["lean_statement_sha256"]
            publish(service, node["id"], alpha, "complete", "peer", lean_statement_sha256=digest)
        return result

    monkeypatch.setattr(service, "peer_wait_status", proving)

    def root_steps(phase, outputs):
        if phase == 0:
            brief = {"brief": "Prove it.", "title": "Prover", "focus_node_id": node["id"]}
            return [tool_call("recruit", {**brief, "until_proved": True}, "r-1")]
        if phase == 1:
            return [tool_call("wait", {"for": "tasks", "ids": [outputs[0]["task_id"]]}, "w-1")]
        return [message("Root done.")]

    def prover_steps(phase, outputs):
        if phase == 0:
            side = {"brief": "Side lookup.", "title": "Side", "detached": True}
            return [tool_call("recruit", side, "r-2")]
        if phase == 1:
            return [tool_call("wait", {"for": "tasks", "ids": [outputs[-1]["task_id"]]}, "w-2")]
        return [message("Unneeded.")]

    def side_steps(phase, outputs):
        wait = {"for": "events", "ids": [], "timeout_seconds": 3600}
        return [tool_call("wait", wait, "w-3")] if phase == 0 else [message("Side done.")]

    route, phases = scripted_society_route(
        root_steps, {"Prove it": prover_steps, "Side lookup": side_steps}
    )
    runner, client = society_runner(service, route)
    try:
        report = await runner.run(run_manifest(exp, author, root))
    finally:
        await client.close()
    tasks = service.list_records("task", author, exp["id"])
    prover = next(task for task in tasks if task.get("scope"))
    side = next(task for task in tasks if task["objective"].startswith("Side lookup"))
    assert proved and phases["Prove it"] == 2 and phases["root"] == 3
    assert prover["status"] == "completed"
    source = service.read_node(node["id"], alpha)["node"]["lean_source"]
    assert prover["return_result"]["artifact_ids"][0] == source["artifact_id"]
    assert service.get_record("task", root["id"], author)["status"] == "completed"
    # Only the detached helper still waits, on events that nothing can now bring.
    assert side["ready_continuation"]["reason"] == "wait_for_events"
    assert report["stop_reason"] == "SOCIETY_IDLE"


def waiter_and_peer(service, author, branches, peer="Busy"):
    return [
        service.create_task(TaskCreate(branch_id=branch["id"], objective=name), author, name)
        for branch, name in zip(branches, ("Waiter", peer), strict=True)
    ]


def recorded_reasons(service, monkeypatch):
    """Every wait check's reason, in order."""
    reasons, status = [], service.peer_wait_status

    def recording(*args):
        result = status(*args)
        reasons.append(result["reason"])
        return result

    monkeypatch.setattr(service, "peer_wait_status", recording)
    return reasons


def objective_of(request):
    return json.loads(json.loads(request.content)["input"][0]["content"])["objective"]


async def test_a_busy_peers_model_turns_do_not_recheck_a_parked_waiter(lab, monkeypatch):
    """Final review B-I3: every model request writes resources.* events; they never move the
    gating head, so a parked waiter is not checked again while a peer works."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    monkeypatch.setattr(research_worker, "EVENT_WAIT_MIN_RECHECK_SECONDS", 0)  # the head alone
    service, author, exp, branches, _ = society_lab(lab, referee_slots=0)
    roots = waiter_and_peer(service, author, branches)
    reasons = recorded_reasons(service, monkeypatch)
    counts, turns = {}, []

    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        if objective_of(request) == "Waiter":
            wait = {"for": "events", "ids": [], "timeout_seconds": 3600}
            return httpx.Response(200, json=response([tool_call("wait", wait, "w-1")]))
        turns.append(len(turns))
        if len(turns) == 1:
            while not reasons:
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.5)  # any check still owed lands before the burst
            counts["before"] = len(reasons)
        await asyncio.sleep(0.3)  # the runner loops while each turn is in flight
        if len(turns) < 6:
            read = {"action": "read", "query": f"note {len(turns)}", "text": None}
            items = [tool_call("library_notes", read, f"n-{len(turns)}")]
        else:
            counts["after"] = len(reasons)
            items = [message("Busy done.")]
        return httpx.Response(200, json=response(items, response_id=f"busy-{len(turns)}"))

    runner, client = society_runner(service, route)
    try:
        report = await runner.run(manifest_for(exp, author, roots))
    finally:
        await client.close()
    assert len(turns) == 6 and counts["after"] == counts["before"]
    kinds = [event["kind"] for event in service.events(author, limit=1000)]
    assert kinds.count("resources.settled") >= 6  # the burst happened
    assert report["stop_reason"] == "SOCIETY_IDLE"


async def test_a_moving_head_rechecks_a_waiter_at_most_every_two_seconds(lab, monkeypatch):
    """Final review B-I3: however often wake-relevant events arrive, a parked waiter is
    checked at most once per EVENT_WAIT_MIN_RECHECK_SECONDS."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, _ = society_lab(lab, referee_slots=0)
    roots = waiter_and_peer(service, author, branches)
    reasons = recorded_reasons(service, monkeypatch)
    heads, head = iter(range(10**9, 2 * 10**9)), service.event_head
    counts = {}

    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        if objective_of(request) == "Waiter":
            wait = {"for": "events", "ids": [], "timeout_seconds": 3600}
            return httpx.Response(200, json=response([tool_call("wait", wait, "w-1")]))
        while not reasons:
            await asyncio.sleep(0.05)
        monkeypatch.setattr(service, "event_head", lambda *args: next(heads))  # always moving
        before = len(reasons)
        await asyncio.sleep(3)  # about twelve runner loops
        counts["during"] = len(reasons) - before
        monkeypatch.setattr(service, "event_head", head)
        return httpx.Response(200, json=response([message("Busy done.")]))

    runner, client = society_runner(service, route)
    try:
        report = await runner.run(manifest_for(exp, author, roots))
    finally:
        await client.close()
    assert 1 <= counts["during"] <= 2
    assert report["stop_reason"] == "SOCIETY_IDLE"


async def test_a_recruit_finished_elsewhere_after_the_snapshot_keeps_the_run_going(
    lab, monkeypatch
):
    """Final review B-M2: another runner may finish an awaited recruit between this loop's
    snapshot and its idle check. The fresh read must still show a live child for every task
    wait, or the parent, which can now run, would be stopped."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, _ = society_lab(lab)
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )
    reasons = recorded_reasons(service, monkeypatch)
    finished, capacity = [], service.research_capacity

    def racing(experiment_id, actor):
        # A ticking loop reads capacity after its snapshot; the helper's wait was checked.
        if "waiting" in reasons and not finished:
            helper = next(
                task
                for task in service.list_records("task", author, exp["id"])
                if task.get("delegated_from_task_id") == root["id"]
            )
            finish_task(service, helper["id"])  # another runner's work, no event
            finished.append(helper["id"])
        return capacity(experiment_id, actor)

    monkeypatch.setattr(service, "research_capacity", racing)

    def root_steps(phase, outputs):
        if phase == 0:
            return [tool_call("recruit", {"brief": "Help out.", "title": "Helper"}, "r-1")]
        if phase == 1:
            return [tool_call("wait", {"for": "tasks", "ids": [outputs[0]["task_id"]]}, "w-1")]
        return [message("Root done.")]

    def helper_steps(phase, outputs):
        return [tool_call("wait", {"for": "events", "ids": [], "timeout_seconds": 3600}, "w-2")]

    route, phases = scripted_society_route(root_steps, {"Help out": helper_steps})
    runner, client = society_runner(service, route)
    try:
        report = await runner.run(run_manifest(exp, author, root))
    finally:
        await client.close()
    assert finished and report["stop_reason"] != "SOCIETY_IDLE"
    assert phases["root"] == 3
    assert service.get_record("task", root["id"], author)["status"] == "completed"


async def test_a_queued_verification_receipt_keeps_the_run_going(lab, monkeypatch):
    """Final review B-M2: an external verifier may still process a queued receipt, and an
    accepted target wakes every waiter; the runner does not stop idle before that."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, _ = society_lab(lab)
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )
    candidate = service.create_artifact(
        ArtifactCreate(
            experiment_id=exp["id"],
            kind="lean_source",
            content="theorem target : (1 : Nat) = 1 := by rfl",
        ),
        author,
        "candidate",
    )
    receipt = service.verify_candidate(exp["id"], candidate["id"], True, author, "verify")
    assert receipt["status"] == "queued"
    payloads = []
    runner, client = society_runner(service, waiting_route(payloads, 3600))
    try:
        report = await runner.run(
            manifest_for(exp, author, [root], process_verifications=False, timeout_seconds=4)
        )
    finally:
        await client.close()
    assert report["stop_reason"] == "TEAM_TIMEOUT" and len(payloads) == 1


async def test_an_event_behind_the_seen_head_is_found_before_an_idle_stop(lab, monkeypatch):
    """Final review B-M2: on PostgreSQL an event can commit behind a head the runner has seen.
    The idle stop needs a second observation, at least a second later, that checks every
    wait again, so such an event still wakes its waiter."""
    monkeypatch.setattr(continuation, "EVENT_WAIT_MIN_SLEEP_SECONDS", 0)
    service, author, exp, branches, (_, beta) = society_lab(lab)
    root = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root"
    )
    reasons, sent, status = [], [], service.peer_wait_status

    def behind(ticket, actor):
        result = status(ticket, actor)
        reasons.append(result["reason"])
        if result["reason"] == "waiting" and not sent:
            frozen = service.event_head(actor, exp["id"])
            monkeypatch.setattr(service, "event_head", lambda *args: frozen)
            sent.append(
                service.send_society_message(
                    beta.branch_id, branches[0]["id"], "Try traces.", [], beta, "late"
                )
            )
        return result

    monkeypatch.setattr(service, "peer_wait_status", behind)
    payloads = []
    runner, client = society_runner(service, waiting_route(payloads, 3600))
    try:
        report = await runner.run(run_manifest(exp, author, root))
    finally:
        await client.close()
    assert sent and report["stop_reason"] is None and len(payloads) == 2
    assert reasons[-1] == "relevant_update"
    assert wake_notes(payloads[1]) == [{"type": "wake", "reason": "relevant_update"}]
