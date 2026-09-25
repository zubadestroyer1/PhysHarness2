"""Society labs: capped branch membership and lab-scoped direct messaging."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from commons_helpers import society_lab
from pydantic import ValidationError
from sqlalchemy import select
from test_sharing import approaches, artifact

from physharness.domain import BranchCreate, Principal, digest_json
from physharness.errors import HarnessError
from physharness.storage import CommandRow, RecordRow, record_json_text
from physharness.workforce_models import (
    PortfolioRoot,
    RecruitResearcherRequest,
    SeedPortfolioRequest,
)

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


def recruit(service, actor, experiment, parent, key, **extra):
    return service.recruit_researcher(
        experiment["id"],
        RecruitResearcherRequest(parent_branch_id=parent["id"], title=key, objective=key, **extra),
        actor,
        key,
    )["branch"]


def agent_for(branch, author, name):
    return Principal(
        id=name,
        role="agent",
        project_id=author.project_id,
        experiment_id=branch["experiment_id"],
        branch_id=branch["id"],
    )


def messages(service, author, experiment):
    return service.list_records("message", author, experiment["id"])


def rejected(call):
    with pytest.raises(HarnessError) as error:
        call()
    return error.value


def test_root_branch_gets_lab_only_in_society(lab):
    service, author, experiment, (alpha, beta), _ = society_lab(lab)
    assert alpha["lab"] == "lab-" + alpha["id"][:8]
    assert beta["lab"] == "lab-" + beta["id"][:8]
    operator = Principal(id="operator", project_id=author.project_id, role="operator")
    root = service.seed_portfolio(
        experiment["id"],
        SeedPortfolioRequest(roots=[PortfolioRoot(title="Seed", objective="Seed")]),
        operator,
        "seed",
    )["roots"][0]["branch"]
    assert root["lab"] == "lab-" + root["id"][:8]
    # A directly created child inherits its parent's lab.
    child = service.create_branch(
        experiment["id"],
        BranchCreate(title="Fork", objective="Fork", parent_id=alpha["id"]),
        author,
        "fork",
    )
    assert child["lab"] == alpha["lab"]

    service, author, legacy, branches, _ = approaches(lab, "ideas")
    assert all("lab" not in branch for branch in branches)
    seeded = service.seed_portfolio(
        legacy["id"],
        SeedPortfolioRequest(roots=[PortfolioRoot(title="Legacy", objective="Legacy")]),
        operator,
        "legacy-seed",
    )["roots"][0]["branch"]
    assert "lab" not in seeded


def test_recruit_inherits_parent_lab(lab):
    service, author, experiment, (alpha, _), _ = society_lab(lab)
    child = recruit(service, author, experiment, alpha, "child")
    assert child["lab"] == alpha["lab"]
    grandchild = recruit(service, author, experiment, child, "grandchild")
    assert grandchild["lab"] == alpha["lab"]
    stored = service.get_record("branch", child["id"], author)
    assert stored["lab"] == alpha["lab"]
    assert stored["revision"] == 1


def test_recruit_new_lab(lab):
    service, author, experiment, (alpha, _), _ = society_lab(lab)
    child = recruit(service, author, experiment, alpha, "founder", lab="new")
    assert child["lab"] == "lab-" + child["id"][:8]
    assert child["lab"] != alpha["lab"]
    assert child["parent_id"] == alpha["id"]
    roster = service.lab_members(experiment["id"], child["lab"], author)
    assert roster == {
        "lab": child["lab"],
        "members": [{"branch_id": child["id"], "title": "founder", "status": "open"}],
        "size_max": 8,
    }


def test_recruit_named_lab_must_exist(lab):
    service, author, experiment, (alpha, beta), _ = society_lab(lab)
    joined = recruit(service, author, experiment, alpha, "visitor", lab=beta["lab"])
    assert joined["lab"] == beta["lab"]
    assert joined["parent_id"] == alpha["id"]
    missing = rejected(lambda: recruit(service, author, experiment, alpha, "x", lab="lab-00000000"))
    assert missing.code == "LAB_NOT_FOUND"
    for bad in ("Lab-Upper", "a" * 41, "", "lab_1", "lab 1"):
        with pytest.raises(ValidationError):
            RecruitResearcherRequest(
                parent_branch_id=alpha["id"], title="t", objective="o", lab=bad
            )
    bad_name = rejected(lambda: service.lab_members(experiment["id"], "Not A Lab", author))
    assert bad_name.code == "INVALID_LAB"
    unknown = rejected(lambda: service.lab_members(experiment["id"], "lab-00000000", author))
    assert unknown.code == "LAB_NOT_FOUND"


def test_lab_full_rejected(lab):
    service, author, experiment, (alpha, beta), _ = society_lab(lab, lab_size_max=2)
    member = recruit(service, author, experiment, alpha, "member")
    assert member["lab"] == alpha["lab"]
    before = len(service.list_records("branch", author, experiment["id"]))
    for call in (
        lambda: recruit(service, author, experiment, alpha, "overflow"),
        lambda: recruit(service, author, experiment, beta, "named", lab=alpha["lab"]),
        lambda: service.create_branch(
            experiment["id"],
            BranchCreate(title="Fork", objective="Fork", parent_id=alpha["id"]),
            author,
            "fork",
        ),
    ):
        error = rejected(call)
        assert (error.code, error.status) == ("LAB_FULL", 409)
    assert len(service.list_records("branch", author, experiment["id"])) == before
    # A new lab is always open, and a full lab stays reachable as a parent.
    founder = recruit(service, author, experiment, alpha, "founder", lab="new")
    assert founder["lab"] == "lab-" + founder["id"][:8]
    roster = service.lab_members(experiment["id"], alpha["lab"], author)
    assert {m["branch_id"] for m in roster["members"]} == {alpha["id"], member["id"]}
    assert roster["size_max"] == 2


def test_unlabelled_branch_neither_joins_nor_counts(lab):
    service, author, experiment, (alpha, _), _ = society_lab(lab, lab_size_max=2)
    with service.db.transaction() as session:
        row = session.get(RecordRow, experiment["id"])
        referee = service._new_branch_task(
            session,
            "op",
            row,
            author,
            title="Referee",
            objective="Review",
            parent_id=alpha["id"],
            lab=None,
        )["branch"]
    assert referee["lab"] is None
    # The referee does not occupy a seat in its requester's lab.
    member = recruit(service, author, experiment, alpha, "member")
    assert member["lab"] == alpha["lab"]
    roster = service.lab_members(experiment["id"], alpha["lab"], author)
    assert referee["id"] not in {m["branch_id"] for m in roster["members"]}
    # Without a lab, a referee reaches only its parent directly and cannot broadcast.
    reviewer = agent_for(referee, author, "referee")
    service.send_message(referee["id"], alpha["id"], "objection", [], reviewer, "to-parent")
    sibling = rejected(
        lambda: service.send_message(referee["id"], member["id"], "hi", [], reviewer, "to-member")
    )
    assert sibling.code == "CROSS_LAB_MESSAGE"
    broadcast = rejected(lambda: service.send_lab_message(referee["id"], "hi", [], reviewer, "b"))
    assert broadcast.code == "LAB_NOT_FOUND"


def test_cross_lab_direct_message_rejected_by_default(lab):
    service, author, experiment, (alpha, beta), (worker_a, _) = society_lab(lab)
    error = rejected(
        lambda: service.send_message(alpha["id"], beta["id"], "hello", [], worker_a, "cross")
    )
    assert (error.code, error.status) == ("CROSS_LAB_MESSAGE", 403)
    assert error.remediation == (
        "Post on the relevant commons node; cross-lab discourse goes through the commons."
    )
    assert messages(service, author, experiment) == []
    # Siblings share a lab without being parent and child.
    first = recruit(service, author, experiment, alpha, "first")
    second = recruit(service, author, experiment, alpha, "second")
    sent = service.send_message(
        first["id"], second["id"], "same lab", [], agent_for(first, author, "w1"), "sibling"
    )
    assert sent["recipient_branch_id"] == second["id"]
    assert set(sent) >= {"sender_branch_id", "recipient_branch_id", "content", "evidence_status"}
    assert "lab" not in sent
    # Self-addressed notes stay available.
    service.send_message(alpha["id"], alpha["id"], "note", [], worker_a, "self")


def test_parent_child_direct_message_allowed_across_labs(lab):
    service, author, experiment, (alpha, _), (worker_a, _) = society_lab(lab)
    child = recruit(service, author, experiment, alpha, "founder", lab="new")
    assert child["lab"] != alpha["lab"]
    down = service.send_message(alpha["id"], child["id"], "down", [], worker_a, "down")
    up = service.send_message(
        child["id"], alpha["id"], "up", [], agent_for(child, author, "child"), "up"
    )
    assert (down["recipient_branch_id"], up["recipient_branch_id"]) == (child["id"], alpha["id"])
    # A grandchild in yet another lab is neither parent nor child of alpha.
    grandchild = recruit(service, author, experiment, child, "grand", lab="new")
    error = rejected(
        lambda: service.send_message(alpha["id"], grandchild["id"], "skip", [], worker_a, "skip")
    )
    assert error.code == "CROSS_LAB_MESSAGE"


def test_cross_lab_allowed_when_policy_enables(lab):
    service, author, experiment, (alpha, beta), (worker_a, _) = society_lab(
        lab, cross_lab_direct_messages=True
    )
    assert alpha["lab"] != beta["lab"]
    sent = service.send_message(alpha["id"], beta["id"], "hello", [], worker_a, "cross")
    assert sent["recipient_branch_id"] == beta["id"]


def test_lab_broadcast_fans_out_and_is_idempotent(lab):
    service, author, experiment, (alpha, beta), (worker_a, worker_b) = society_lab(lab)
    first = recruit(service, author, experiment, alpha, "first")
    second = recruit(service, author, experiment, alpha, "second")
    evidence = artifact(service, worker_a, "shared lemma")
    result = service.send_lab_message(
        alpha["id"], "lab update", [evidence["id"]], worker_a, "broadcast"
    )
    assert result["lab"] == alpha["lab"]
    assert len(result["message_ids"]) == 2
    stored = messages(service, author, experiment)
    assert {m["id"] for m in stored} == set(result["message_ids"])
    assert {m["recipient_branch_id"] for m in stored} == {first["id"], second["id"]}
    for message in stored:
        assert message["sender_branch_id"] == alpha["id"]
        assert message["attributed_to"] == worker_a.id
        assert message["content"] == "lab update"
        assert message["artifact_ids"] == [evidence["id"]]
        assert message["evidence_status"] == "attributed_idea"
        assert message["lab"] == alpha["lab"]
        assert message["delivery_key"] == f"broadcast:{message['recipient_branch_id']}"
    created = [e for e in service.events(author, limit=1000) if e["kind"] == "message.created"]
    assert {e["aggregate_id"] for e in created} == {first["id"], second["id"]}
    # Each recipient reads its own copy through the normal mailbox path.
    reader = agent_for(first, author, "reader")
    inbox = service.mailbox_page(first["id"], reader)["items"]
    assert [item["content"] for item in inbox] == ["lab update"]

    replay = service.send_lab_message(
        alpha["id"], "lab update", [evidence["id"]], worker_a, "broadcast"
    )
    assert replay == result
    assert len(messages(service, author, experiment)) == 2
    conflict = rejected(
        lambda: service.send_lab_message(alpha["id"], "changed", [], worker_a, "broadcast")
    )
    assert conflict.code == "IDEMPOTENCY_CONFLICT"

    alone = rejected(lambda: service.send_lab_message(beta["id"], "hi", [], worker_b, "alone"))
    assert alone.code == "LAB_EMPTY"
    forged = rejected(lambda: service.send_lab_message(beta["id"], "hi", [], worker_a, "forged"))
    assert forged.code in {"BRANCH_AUTHORITY", "NOT_FOUND"}
    empty = rejected(lambda: service.send_lab_message(alpha["id"], " ", [], worker_a, "blank"))
    assert empty.code == "INVALID_MESSAGE"


def test_lab_features_require_society(lab):
    service, author, experiment, (alpha, beta), (worker_a, _) = approaches(lab, "ideas")
    new_lab = rejected(lambda: recruit(service, author, experiment, alpha, "x", lab="new"))
    assert new_lab.code == "SOCIETY_DISABLED"
    broadcast = rejected(lambda: service.send_lab_message(alpha["id"], "hi", [], worker_a, "b"))
    assert broadcast.code == "SOCIETY_DISABLED"
    roster = rejected(lambda: service.lab_members(experiment["id"], "lab-00000000", author))
    assert roster.code == "SOCIETY_DISABLED"
    # Legacy direct messages keep today's routing and payload shape.
    sent = service.send_message(alpha["id"], beta["id"], "hello", [], worker_a, "legacy")
    assert set(sent) == {
        "experiment_id",
        "sender_branch_id",
        "branch_id",
        "recipient_branch_id",
        "attributed_to",
        "content",
        "artifact_ids",
        "evidence_status",
        "origin_actor_id",
        "id",
        "kind",
        "project_id",
        "revision",
        "created_at",
    }


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
    # Society recruits fingerprint the lab only when it is supplied.
    service, author, society, (alpha, _), _ = society_lab(lab, prefix="society2")
    implicit = RecruitResearcherRequest(parent_branch_id=alpha["id"], title="A", objective="A")
    explicit = implicit.model_copy(update={"lab": "new"})
    service.recruit_researcher(society["id"], implicit, author, "implicit")
    service.recruit_researcher(society["id"], explicit, author, "explicit")
    base = {**implicit.model_dump(mode="json", exclude={"lab"}), "experiment_id": society["id"]}
    assert recruit_fingerprint(service, author, "implicit") == expected_fingerprint(author, base)
    assert recruit_fingerprint(service, author, "explicit") == expected_fingerprint(
        author, {**base, "lab": "new"}
    )


def test_concurrent_joins_respect_lab_cap(lab):
    service, author, experiment, (alpha, _), _ = society_lab(lab, lab_size_max=2)

    def attempt(key):
        try:
            return recruit(service, author, experiment, alpha, key)
        except HarnessError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["one", "two"]))
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    assert "LAB_FULL" in outcomes
    roster = service.lab_members(experiment["id"], alpha["lab"], author)
    assert len(roster["members"]) == 2


def test_lab_roster_is_scoped_to_the_agents_experiment(lab):
    service, author, experiment, (alpha, _), (worker_a, _) = society_lab(lab)
    _, _, other, (other_root, _), _ = society_lab(lab, prefix="other")
    own = service.lab_members(experiment["id"], alpha["lab"], worker_a)
    assert own["members"] == [{"branch_id": alpha["id"], "title": "alpha", "status": "open"}]
    assert "objective" not in str(own)
    hidden = rejected(lambda: service.lab_members(other["id"], other_root["lab"], worker_a))
    assert hidden.code == "NOT_FOUND"
    # A lab name from another experiment is not a lab here.
    foreign = rejected(lambda: service.lab_members(experiment["id"], other_root["lab"], worker_a))
    assert foreign.code == "LAB_NOT_FOUND"
