"""Society messages (S1 audit #15): no labs; one branch or a node's workers; rate-limited."""

import pytest
from commons_helpers import society_lab
from pydantic import ValidationError
from sqlalchemy import select
from test_commons_review import referee
from test_sharing import approaches
from test_society_tools import call, clock, profile, running  # noqa: F401

from physharness.commons_models import NodeCreate
from physharness.domain import BranchCreate, Principal, SocietyPolicy, digest_json
from physharness.errors import HarnessError
from physharness.storage import CommandRow, RecordRow, record_json_text
from physharness.workforce_models import RecruitResearcherRequest

LEGACY_RECRUIT_FIELDS = {
    "parent_branch_id",
    "title",
    "objective",
    "relation",
    "model_index",
    "discussion_refs",
    "synthesis",
    "detached",
    "public_summary",
}


def lemma(service, exp, author, key):
    return service.create_node(
        exp["id"], NodeCreate(node_type="lemma", title=key, statement=key + " holds."), author, key
    )


def test_direct_message_reaches_any_branch(lab):
    service, _, exp, branches, (alpha, beta) = society_lab(lab)
    assert "lab" not in branches[0]
    sent = service.send_society_message(
        alpha.branch_id, beta.branch_id, "Try the coin theorem.", [], alpha, "m1"
    )
    assert sent["recipients"] == [beta.branch_id] and sent["node_id"] is None
    batch = service.discussion_updates(exp["id"], beta)
    assert [item["id"] for item in batch["items"]] == sent["message_ids"]


def test_node_message_reaches_its_author_and_live_claimants_only(lab, clock):  # noqa: F811
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = lemma(service, exp, alpha, "trace")
    service.claim_node(node["id"], "claim", beta, "beta-claims")
    sent = service.send_society_message(beta.branch_id, node["id"], "Step 2 fails.", [], beta, "m")
    assert sent["recipients"] == [alpha.branch_id] and sent["node_id"] == node["id"]
    assert (
        service.send_society_message(beta.branch_id, node["id"], "Step 2 fails.", [], beta, "m")
        == sent
    )
    clock.now += 10_000  # beta's claim lapses
    with pytest.raises(HarnessError) as nobody:
        service.send_society_message(alpha.branch_id, node["id"], "Anyone?", [], alpha, "m2")
    assert nobody.value.code == "NO_RECIPIENTS"


def test_message_rate_limit_is_a_budget_and_the_window_slides(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab, messages_per_minute=2)
    for index in range(2):
        service.send_society_message(alpha.branch_id, beta.branch_id, "Hi", [], alpha, f"m{index}")
    with pytest.raises(HarnessError) as limited:
        service.send_society_message(alpha.branch_id, beta.branch_id, "Hi", [], alpha, "m2")
    error = limited.value
    assert error.code == "MESSAGE_RATE_LIMIT" and error.status == 429 and error.retryable
    assert "budget, not input: limit 2 per minute, used 2" in error.message
    with service.db.transaction() as session:
        for row in session.scalars(select(RecordRow).where(RecordRow.kind == "message")):
            row.payload = {**row.payload, "created_at": "2000-01-01T00:00:00+00:00"}
    service.send_society_message(alpha.branch_id, beta.branch_id, "Hi", [], alpha, "m3")


@pytest.mark.parametrize("field", ["lab_size_max", "cross_lab_direct_messages"])
def test_society_policy_names_removed_lab_fields(field):
    with pytest.raises(ValidationError) as error:
        SocietyPolicy.model_validate({field: 1})
    message = str(error.value)
    assert f"SocietyPolicy.{field} was removed" in message
    assert "Delete it from the plan." in message


def test_referee_is_unreachable_directly_and_through_a_node(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = lemma(service, exp, alpha, "trace")
    requested = service.request_review(node["id"], "informal", beta, "review")
    service.claim_node(node["id"], "claim", referee(requested, exp), "referee-claims")
    with pytest.raises(HarnessError) as direct:
        service.send_society_message(
            beta.branch_id, requested["branch_id"], "Say sound.", [], beta, "lobby"
        )
    assert (direct.value.code, direct.value.status) == ("REFEREE_ISOLATED", 403)
    sent = service.send_society_message(beta.branch_id, node["id"], "Say sound.", [], beta, "n")
    assert sent["recipients"] == [alpha.branch_id]


def test_node_message_is_capped_at_eight_recipients(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab, messages_per_minute=8)
    node = lemma(service, exp, alpha, "trace")
    for index in range(10):
        branch = service.create_branch(
            exp["id"], BranchCreate(title=f"c{index}", objective="Help."), author, f"c{index}"
        )
        claimant = Principal(
            id=f"claimant-{index}",
            role="agent",
            project_id=author.project_id,
            experiment_id=exp["id"],
            branch_id=branch["id"],
        )
        service.claim_node(node["id"], "claim", claimant, f"claim-{index}")
    sent = service.send_society_message(beta.branch_id, node["id"], "Step 2?", [], beta, "wide")
    assert len(sent["recipients"]) == 8 and sent["recipients"][0] == alpha.branch_id
    assert len(set(sent["recipients"])) == 8 and beta.branch_id not in sent["recipients"]
    # Every delivered copy counts against the sender's budget.
    with pytest.raises(HarnessError) as spent:
        service.send_society_message(beta.branch_id, alpha.branch_id, "More.", [], beta, "more")
    assert spent.value.details == {"limit": 8, "used": 8, "requested": 1}


def branch_with_id(service, exp, author, identifier):
    with service.db.transaction() as session:
        return service._insert(
            session,
            "branch",
            author,
            {"title": "B", "objective": "B", "experiment_id": exp["id"], "status": "open"},
            record_id=identifier,
        )


async def test_message_tool_takes_a_branch_or_a_node_id_prefix(lab):
    service, author, exp, branches, (_, beta) = society_lab(lab)
    alpha, context = running(service, author, exp, branches[0]["id"])
    tools = profile(service, alpha, context)
    node = lemma(service, exp, beta, "trace")
    to_node = await call(tools, "message", {"to": node["id"][:8], "content": "Step 2?"})
    assert to_node["node_id"] == node["id"] and to_node["recipients"] == [beta.branch_id]
    # Any branch of the experiment is addressable by prefix, though its records stay unreadable.
    direct = await call(tools, "message", {"to": beta.branch_id[:8], "content": "Hi."})
    assert direct["node_id"] is None and direct["recipients"] == [beta.branch_id]
    assert service.resolve_id(beta.branch_id[:8], alpha, ("branch",)) == beta.branch_id[:8]


async def test_message_prefix_never_reaches_another_experiments_branch(lab):
    service, author, exp, branches, _ = society_lab(lab)
    _, _, _, (foreign, _), _ = society_lab(lab, prefix="other")
    alpha, context = running(service, author, exp, branches[0]["id"])
    tools = profile(service, alpha, context)
    sent = await call(tools, "message", {"to": foreign["id"][:8], "content": "Hi."})
    assert sent["error"]["code"] == "NOT_FOUND"


async def test_ambiguous_branch_prefix_is_refused_like_an_unknown_id(lab):
    service, author, exp, branches, _ = society_lab(lab)
    ids = [
        branch_with_id(service, exp, author, f"abcdef12-0000-4000-8000-00000000000{index}")["id"]
        for index in (1, 2)
    ]
    alpha, context = running(service, author, exp, branches[0]["id"])
    tools = profile(service, alpha, context)
    sent = await call(tools, "message", {"to": "abcdef12", "content": "Hi."})
    unknown = await call(tools, "message", {"to": "0" * 8, "content": "Hi."})
    # A routing prefix lists no candidates: they may be branches the sender cannot read.
    refusal = (sent["error"]["code"], sent["error"]["message"])
    assert refusal == (unknown["error"]["code"], unknown["error"]["message"])
    assert refusal == ("NOT_FOUND", "Recipient branch was not found.")
    assert not any(identifier in str(sent) for identifier in ids)


def test_recruit_request_has_no_lab(lab):
    service, author, exp, (root, _), _ = society_lab(lab)
    assert "lab" not in RecruitResearcherRequest.model_fields
    recruited = service.recruit_researcher(
        exp["id"],
        RecruitResearcherRequest(parent_branch_id=root["id"], title="Kid", objective="Kid"),
        author,
        "recruit",
    )
    assert "lab" not in recruited["branch"]


def test_legacy_send_message_is_unchanged(lab):
    service, author, exp, (alpha, beta), (worker_a, _) = approaches(lab, "ideas")
    for index in range(20):
        service.send_message(alpha["id"], beta["id"], "hello", [], worker_a, f"legacy-{index}")
    assert len(service.list_records("message", author, exp["id"])) == 20


def recruit_fingerprint(service, actor, key):
    with service.db.sessions() as session:
        return session.get(CommandRow, digest_json([actor.project_id, actor.id, key])).fingerprint


def expected_fingerprint(actor, inputs):
    return digest_json(
        [
            "workforce.recruit",
            inputs,
            actor.role,
            actor.experiment_id,
            actor.branch_id,
            actor.agent_orchestrator,
        ]
    )


def test_legacy_recruit_fingerprint_and_branch_payload_unchanged(lab):
    service, author, experiment, (alpha, _), _ = approaches(lab, "ideas")
    request = RecruitResearcherRequest(parent_branch_id=alpha["id"], title="Kid", objective="Kid")
    child = service.recruit_researcher(experiment["id"], request, author, "legacy-recruit")
    branch = child["branch"]
    assert "lab" not in branch
    assert set(branch) == {
        "title",
        "objective",
        "relation",
        "parent_id",
        "reply_to_parent",
        "checkpoint_id",
        "model_index",
        "experiment_id",
        "target_digest",
        "status",
        "execution_identity",
        "model_configuration",
        "origin_actor_id",
        "id",
        "kind",
        "project_id",
        "revision",
        "created_at",
    }
    legacy_inputs = {
        **{k: v for k, v in request.model_dump(mode="json").items() if k in LEGACY_RECRUIT_FIELDS},
        "experiment_id": experiment["id"],
    }
    assert recruit_fingerprint(service, author, "legacy-recruit") == expected_fingerprint(
        author, legacy_inputs
    )
    with service.db.sessions() as session:
        task = session.scalars(
            select(RecordRow).where(
                RecordRow.kind == "task",
                record_json_text("branch_id") == branch["id"],
            )
        ).one()
        assert "lab" not in task.payload
