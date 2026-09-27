"""Tier-0 #5d: model-supplied ids accept a unique prefix of at least 8 hex characters."""

import itertools

import pytest
from commons_helpers import society_lab
from test_sharing import artifact
from test_society_tools import call, lemma_args, profile, running

from physharness import domain
from physharness.commons_models import NodeCreate
from physharness.domain import TaskCreate
from physharness.errors import HarnessError
from physharness.storage import RecordRow

NODE = ("commons_node",)
UNKNOWN = "0" * 8 + "-0000-4000-8000-" + "0" * 12


def node_with_id(service, experiment, agent, identifier, title):
    with service.db.transaction() as session:
        row = session.get(RecordRow, experiment["id"])
        payload = service._node_payload(
            row,
            node_type="lemma",
            title=title,
            statement=title,
            status="open",
            status_reason="test",
        )
        return service._insert(
            session,
            "commons_node",
            agent,
            {**payload, "branch_id": agent.branch_id},
            record_id=identifier,
        )


def test_unique_prefix_resolves_and_anything_else_passes_through(lab):
    service, _, exp, _, (alpha, _) = society_lab(lab)
    node = service.create_node(
        exp["id"], NodeCreate(node_type="lemma", title="L", statement="L holds."), alpha, "node"
    )
    for prefix in (node["id"][:8], node["id"][:13], node["id"]):
        assert service.resolve_id(prefix, alpha, NODE) == node["id"]
    assert service.resolve_id(node["id"][:7], alpha, NODE) == node["id"][:7]
    assert service.resolve_id(node["id"][:8], alpha, ("branch",)) == node["id"][:8]
    assert service.resolve_id("0" * 8, alpha, NODE) == "0" * 8
    _, _, other, _, (gamma, _) = society_lab(lab, prefix="other")
    hidden = service.create_node(
        other["id"], NodeCreate(node_type="lemma", title="H", statement="H holds."), gamma, "h"
    )
    assert service.resolve_id(hidden["id"][:8], alpha, NODE) == hidden["id"][:8]


def test_ambiguous_prefix_lists_the_candidates(lab):
    service, _, exp, _, (alpha, _) = society_lab(lab)
    first = node_with_id(service, exp, alpha, "abcdef12-0000-4000-8000-000000000001", "A")
    second = node_with_id(service, exp, alpha, "abcdef12-0000-4000-8000-000000000002", "B")
    with pytest.raises(HarnessError) as error:
        service.resolve_id("abcdef12", alpha, NODE)
    assert error.value.code == "AMBIGUOUS_ID"
    assert [c["id"] for c in error.value.details["candidates"]] == [first["id"], second["id"]]


async def test_society_tools_accept_prefixes_for_id_arguments(lab):
    service, author, exp, _, (alpha, _) = society_lab(lab)
    agent, context = running(service, author, exp, alpha.branch_id)
    tools = profile(service, agent, context)
    created = await call(tools, "commons_node", lemma_args())
    short = created["id"][:8]
    assert (await call(tools, "commons_read", {"node_id": short}))["node"]["id"] == created["id"]
    assert (await call(tools, "commons_claim", {"node_id": short, "action": "claim"}))[
        "node_id"
    ] == created["id"]
    posted = await call(
        tools, "commons_post", {"node_id": short, "kind": "finding", "abstract": "A finding."}
    )
    assert posted["node_id"] == created["id"]


async def test_prefixes_resolve_inside_lists_and_nested_objects(lab):
    service, author, exp, _, (alpha, _) = society_lab(lab)
    agent, context = running(service, author, exp, alpha.branch_id)
    tools = profile(service, agent, context)
    base = await call(tools, "commons_node", lemma_args())
    evidence = artifact(service, agent, "Base case holds for n = 0.")
    edge = {"relation": "depends_on", "target_id": base["id"][:8]}
    derived = await call(
        tools,
        "commons_node",
        lemma_args(title="Derived", edges=[edge], artifact_ids=[evidence["id"][:8]]),
    )
    edges = service.read_node(derived["id"], agent)["edges_out"]
    assert [(item["relation"], item["node_id"]) for item in edges] == [("depends_on", base["id"])]
    assert service.get_record("commons_node", derived["id"], agent)["artifact_ids"] == [
        evidence["id"]
    ]


def error(result):
    return result["error"]["code"], result["error"]["message"]


async def recruited_pair(service, author, exp, branches, **recruit):
    """A running parent on alpha and its joined recruit, each with a society catalog."""
    alpha, context = running(service, author, exp, branches[0]["id"])
    tools = profile(service, alpha, context)
    recruited = await call(
        tools, "recruit", {"brief": "Check the base case.", "title": "Base", **recruit}
    )
    task = service.get_record("task", recruited["task_id"], author)
    child, child_context = running(service, author, exp, recruited["branch_id"], task=task)
    return (alpha, tools), (child, profile(service, child, child_context)), recruited


async def test_routing_arguments_resolve_prefixes_among_their_targets(lab):
    """A routed record need not be readable: a recruit's task, a parent or a watched branch."""
    service, author, exp, branches, _ = society_lab(lab)
    (alpha, tools), (_, child_tools), recruited = await recruited_pair(
        service, author, exp, branches
    )
    waited = await call(tools, "wait", {"for": "tasks", "ids": [recruited["task_id"][:8]]})
    assert waited["intent"]["wait_task_ids"] == [recruited["task_id"]]
    sent = await call(
        child_tools, "message", {"to": branches[0]["id"][:8], "content": "Base case holds."}
    )
    assert sent["to"] == branches[0]["id"] and sent["message_ids"]
    inbox = service.mailbox_page(branches[0]["id"], alpha)["items"]
    assert [item["content"] for item in inbox] == ["Base case holds."]
    watched = await call(tools, "wait", {"for": "events", "ids": [branches[1]["id"][:8]]})
    assert watched["intent"]["peer_wait"]["watch_branch_ids"] == [branches[1]["id"]]


async def test_routing_prefix_outside_the_targets_fails_like_an_unknown_id(lab):
    service, author, exp, branches, _ = society_lab(lab)
    (_, tools), _, _ = await recruited_pair(service, author, exp, branches)
    unrelated = service.create_task(
        TaskCreate(branch_id=branches[1]["id"], objective="Elsewhere"), author, "unrelated"
    )
    missing = await call(tools, "wait", {"for": "tasks", "ids": [UNKNOWN]})
    assert error(missing)[0] == "HANDOFF_CHILD_SCOPE"
    hidden = await call(tools, "wait", {"for": "tasks", "ids": [unrelated["id"][:8]]})
    assert error(hidden) == error(missing)
    # A watch takes this experiment's nodes and branches; a task's prefix names neither.
    missing = await call(tools, "wait", {"for": "events", "ids": [UNKNOWN]})
    assert error(missing)[0] == "EVENT_WAIT_SCOPE"
    hidden = await call(tools, "wait", {"for": "events", "ids": [unrelated["id"][:8]]})
    assert error(hidden) == error(missing)
    # A referee's branch: its full id is refused as isolated, its prefix as unknown.
    with service.db.transaction() as session:
        payload = {"title": "R", "objective": "R", "experiment_id": exp["id"], "status": "open"}
        referee = service._insert(session, "branch", author, {**payload, "hat": "referee"})
    isolated = await call(tools, "message", {"to": referee["id"], "content": "Hi."})
    assert error(isolated)[0] == "REFEREE_ISOLATED"
    missing = await call(tools, "message", {"to": UNKNOWN, "content": "Hi."})
    assert error(missing) == ("NOT_FOUND", "Recipient branch was not found.")
    hidden = await call(tools, "message", {"to": referee["id"][:8], "content": "Hi."})
    assert error(hidden) == error(missing)


async def test_ambiguous_routing_prefix_is_refused_like_an_unknown_id(lab, monkeypatch):
    service, author, exp, branches, _ = society_lab(lab)
    alpha, context = running(service, author, exp, branches[0]["id"])
    tools = profile(service, alpha, context)
    counter = itertools.count(1)
    with monkeypatch.context() as patch:  # every new record id begins abcdef12
        patch.setattr(domain, "new_id", lambda: f"abcdef12-0000-4000-8000-{next(counter):012d}")
        first = await call(tools, "recruit", {"brief": "One.", "title": "One"})
        second = await call(tools, "recruit", {"brief": "Two.", "title": "Two"})
    assert first["task_id"][:8] == second["task_id"][:8] == "abcdef12"
    ambiguous = await call(tools, "wait", {"for": "tasks", "ids": ["abcdef12"]})
    unknown = await call(tools, "wait", {"for": "tasks", "ids": [UNKNOWN]})
    assert error(ambiguous) == error(unknown)
    assert "abcdef12" not in str(ambiguous)  # no candidate list
    ambiguous = await call(tools, "wait", {"for": "events", "ids": ["abcdef12"]})
    unknown = await call(tools, "wait", {"for": "events", "ids": [UNKNOWN]})
    assert error(ambiguous) == error(unknown) and "abcdef12" not in str(ambiguous)
    both = await call(tools, "wait", {"for": "tasks", "ids": [first["task_id"], second["task_id"]]})
    assert both["intent"]["wait_task_ids"] == [first["task_id"], second["task_id"]]
