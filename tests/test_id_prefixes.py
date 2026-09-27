"""Tier-0 #5d: model-supplied ids accept a unique prefix of at least 8 hex characters."""

import pytest
from commons_helpers import society_lab
from test_society_tools import call, lemma_args, profile, running

from physharness.commons_models import NodeCreate
from physharness.errors import HarnessError
from physharness.storage import RecordRow

NODE = ("commons_node",)


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
