"""S1 audit #14: waits that wake on relevant events, not only on one peer's message."""

import asyncio
import json

import httpx
import pytest
from commons_helpers import set_status, society_lab
from test_commons_sources import publish
from test_execution_responses import message
from test_research_loop_integration import PRICES, response, tool_call
from test_sharing import approaches
from test_society_tools import (
    call,
    mock_client,
    profile,
    run_manifest,
    running,
    scripted_society_route,
    society_runner,
)
from test_swarm_coordination_gaps import verified_receipt

from physharness import continuation
from physharness.commons_models import NodeCreate, NodePostCreate
from physharness.domain import ContextBudget, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import ResponsesRuntime, RuntimeLimits
from physharness.execution.admission import TokenRateGovernor
from physharness.orchestration.research_worker import (
    ResearchTaskExecutor,
    ResearchTeamRunner,
    TeamRunManifest,
)
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


# Runner side: native wake, event-head gating and the idle stop --------------------------------


def waiting_route(payloads, timeout_seconds, *, waits=1):
    """A provider whose first ``waits`` requests wait for events; later requests finish."""

    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        payloads.append(json.loads(request.content))
        count = len(payloads)
        wait = {"for": "events", "ids": [], "timeout_seconds": timeout_seconds}
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


def test_the_event_head_is_the_projects_latest_event(lab):
    service, author, exp, _, (_, beta) = society_lab(lab)
    head = service.event_head(author)
    assert head > 0
    lemma(service, exp, beta, "New")
    assert service.event_head(author) > head
    stranger = Principal(id="stranger", project_id="elsewhere", role="operator")
    assert service.event_head(stranger) == 0


async def test_legacy_waits_still_resume_portably(lab):
    service, author, exp, branches, _ = approaches(lab, "ideas")
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
