"""Research-board scope and durable delivery contracts."""

import json

import pytest
from test_sharing import approaches, artifact

from physharness.discussion_models import DiscussionCreate, DiscussionPostCreate
from physharness.domain import ArtifactCreate, Principal
from physharness.errors import HarnessError
from physharness.service import HarnessService
from physharness.storage import RecordRow


def test_ideas_posts_are_attributed_and_scoped_across_generic_reads(lab):
    service, _, exp, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Invariant", summary="Compare approaches"), alpha, "topic"
    )
    source = artifact(service, alpha, "candidate source")
    post = service.post_discussion(
        topic["id"],
        DiscussionPostCreate(
            kind="finding", content="Try a conserved quantity", artifact_ids=[source["id"]]
        ),
        alpha,
        "post",
    )
    reply = service.post_discussion(
        topic["id"],
        DiscussionPostCreate(
            kind="objection",
            content="Assumption is missing",
            reply_to_post_id=post["id"],
            reference_post_ids=[post["id"]],
        ),
        beta,
        "reply",
    )
    assert post["evidence_status"] == "unverified_discussion"
    assert post["attributed_to"] == alpha.id
    assert service.get_record("discussion_post", post["id"], beta)["content"] == post["content"]
    assert [p["id"] for p in service.discussion_posts(topic["id"], beta)["items"]] == [
        post["id"],
        reply["id"],
    ]
    assert service.discussion_page(exp["id"], beta)["items"][0]["id"] == topic["id"]
    assert source["id"] in str(
        service.export_experiment(exp["id"], beta)["records"]["discussion_post"]
    )


@pytest.mark.parametrize("sharing", ["none", "verified"])
def test_unverified_discussion_stays_private_even_via_generic_records(lab, sharing):
    service, _, exp, _, (alpha, beta) = approaches(lab, sharing)
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Private", summary="Idea"), alpha, "topic"
    )
    post = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="question", content="Secret idea"), alpha, "post"
    )
    for kind, identifier in (("discussion_topic", topic["id"]), ("discussion_post", post["id"])):
        with pytest.raises(HarnessError) as error:
            service.get_record(kind, identifier, beta)
        assert error.value.code == "NOT_FOUND"
        assert service.page_records(kind, beta, exp["id"])["items"] == []
    with pytest.raises(HarnessError):
        service.discussion_posts(topic["id"], beta)
    assert service.discussion_page(exp["id"], beta)["items"] == []
    assert "Secret idea" not in str(service.export_experiment(exp["id"], beta))


def test_delivery_redelivers_until_exact_ack_and_rejects_forged_or_skipped_cursor(lab):
    service, _, exp, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Research"), alpha, "topic"
    )
    subscription = service.subscribe_discussion(topic["id"], True, beta, "subscribe")
    assert subscription["subscribed"] is True
    post = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="finding", content="A" * 2000), alpha, "post"
    )
    first = service.discussion_updates(exp["id"], beta)
    assert first["delivery_id"] and first["items"][0]["id"] == post["id"]
    assert first["items"][0]["truncated"] is True
    assert len(first["items"][0]["excerpt"].encode()) <= 1024
    assert service.discussion_updates(exp["id"], beta)["delivery_id"] == first["delivery_id"]
    with pytest.raises(HarnessError) as error:
        service.discussion_updates(exp["id"], beta, after=first["next_cursor"])
    assert error.value.code == "INVALID_CURSOR"
    with pytest.raises(HarnessError) as error:
        service.acknowledge_discussion_updates(exp["id"], "forged", beta, "bad-ack")
    assert error.value.code == "DELIVERY_MISMATCH"
    restarted = HarnessService(service.db, service.artifacts)
    assert restarted.discussion_updates(exp["id"], beta)["items"] == first["items"]
    ack = restarted.acknowledge_discussion_updates(exp["id"], first["delivery_id"], beta, "ack")
    assert ack["next_cursor"] == post["sequence"]
    assert restarted.discussion_updates(exp["id"], beta)["items"] == []
    assert (
        restarted.acknowledge_discussion_updates(exp["id"], first["delivery_id"], beta, "ack")
        == ack
    )


def test_subscription_starts_now_and_old_history_does_not_starve_updates(lab):
    service, _, exp, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="History", summary="Old"), alpha, "topic"
    )
    for n in range(105):
        service.post_discussion(
            topic["id"], DiscussionPostCreate(kind="update", content=f"old {n}"), alpha, f"old-{n}"
        )
    service.subscribe_discussion(topic["id"], True, beta, "subscribe")
    fresh = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="finding", content="fresh"), alpha, "fresh"
    )
    batch = service.discussion_updates(exp["id"], beta)
    assert [item["id"] for item in batch["items"]] == [fresh["id"]]


def test_subscription_and_delivery_are_private_through_generic_reads(lab):
    service, _, exp, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Research"), alpha, "topic"
    )
    subscription = service.subscribe_discussion(topic["id"], True, beta, "subscribe")
    service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="update", content="hello"), alpha, "post"
    )
    batch = service.discussion_updates(exp["id"], beta)
    for kind, identifier in (
        ("discussion_subscription", subscription["id"]),
        ("discussion_delivery", batch["delivery_id"]),
    ):
        with pytest.raises(HarnessError):
            service.get_record(kind, identifier, alpha)
        assert service.page_records(kind, alpha, exp["id"])["items"] == []
    assert batch["delivery_id"] not in str(service.export_experiment(exp["id"], alpha))


def test_post_schema_rejects_forged_proof_status_and_cross_topic_reply(lab):
    service, _, exp, _, (alpha, _) = approaches(lab, "ideas")
    one = service.create_discussion(
        exp["id"], DiscussionCreate(title="One", summary="One"), alpha, "one"
    )
    two = service.create_discussion(
        exp["id"], DiscussionCreate(title="Two", summary="Two"), alpha, "two"
    )
    post = service.post_discussion(
        one["id"], DiscussionPostCreate(kind="question", content="Why?"), alpha, "post"
    )
    with pytest.raises(ValueError):
        DiscussionPostCreate.model_validate(
            {"kind": "finding", "content": "proved", "proof_status": "verified"}
        )
    with pytest.raises(HarnessError) as error:
        service.post_discussion(
            two["id"],
            DiscussionPostCreate(kind="objection", content="No", reply_to_post_id=post["id"]),
            alpha,
            "bad-reply",
        )
    assert error.value.code == "DISCUSSION_SCOPE"


def test_unsubscribe_resubscribe_has_new_start_and_no_old_replay(lab):
    service, _, exp, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Updates"), alpha, "topic"
    )
    service.subscribe_discussion(topic["id"], True, beta, "subscribe")
    first = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="update", content="first"), alpha, "first"
    )
    batch = service.discussion_updates(exp["id"], beta)
    assert batch["items"][0]["id"] == first["id"]
    with pytest.raises(HarnessError) as error:
        service.subscribe_discussion(topic["id"], False, beta, "premature-unsubscribe")
    assert error.value.code == "DELIVERY_PENDING"
    service.acknowledge_discussion_updates(exp["id"], batch["delivery_id"], beta, "ack")
    service.subscribe_discussion(topic["id"], False, beta, "unsubscribe")
    service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="update", content="while away"), alpha, "away"
    )
    service.subscribe_discussion(topic["id"], True, beta, "resubscribe")
    fresh = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="update", content="fresh"), alpha, "fresh"
    )
    assert [item["id"] for item in service.discussion_updates(exp["id"], beta)["items"]] == [
        fresh["id"]
    ]


def test_private_artifact_and_stale_target_pins_fail_closed(lab):
    service, author, exp, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Research"), alpha, "topic"
    )
    private = service.create_artifact(
        ArtifactCreate(
            experiment_id=exp["id"],
            branch_id=alpha.branch_id,
            kind="native_checkpoint",
            content="private",
        ),
        author.model_copy(update={"role": "operator"}),
        "private",
    )
    with pytest.raises(HarnessError) as error:
        service.post_discussion(
            topic["id"],
            DiscussionPostCreate(
                kind="finding", content="see private", artifact_ids=[private["id"]]
            ),
            alpha,
            "bad",
        )
    assert error.value.code == "NOT_FOUND"
    post = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="finding", content="public"), alpha, "post"
    )
    with service.db.transaction() as session:
        row = session.get(RecordRow, topic["id"])
        service._replace(session, row, {"environment_digest": "0" * 64})
    with pytest.raises(HarnessError):
        service.discussion_posts(topic["id"], beta)
    with pytest.raises(HarnessError):
        service.get_record("discussion_post", post["id"], beta)


def test_update_batches_fit_runtime_context_and_page_without_loss(lab):
    service, _, exp, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Updates"), alpha, "topic"
    )
    service.subscribe_discussion(topic["id"], True, beta, "subscribe")
    posts = [
        service.post_discussion(
            topic["id"], DiscussionPostCreate(kind="update", content="λ" * 6000), alpha, f"post-{n}"
        )
        for n in range(10)
    ]
    delivered = []
    while len(delivered) < len(posts):
        batch = service.discussion_updates(exp["id"], beta)
        assert batch["items"]
        assert len(json.dumps(batch["items"], ensure_ascii=False).encode()) <= 12000
        assert service.discussion_updates(exp["id"], beta)["items"] == batch["items"]
        delivered.extend(item["id"] for item in batch["items"])
        service.acknowledge_discussion_updates(
            exp["id"], batch["delivery_id"], beta, f"ack-{len(delivered)}"
        )
    assert delivered == [post["id"] for post in posts]


def test_post_pages_use_exact_event_cursors(lab):
    service, _, exp, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Updates"), alpha, "topic"
    )
    posts = [
        service.post_discussion(
            topic["id"], DiscussionPostCreate(kind="update", content=str(n)), alpha, f"post-{n}"
        )
        for n in range(3)
    ]
    cursor = None
    seen = []
    while True:
        page = service.discussion_posts(topic["id"], beta, after=cursor, limit=1)
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [post["id"] for post in posts]
    assert service.read_discussion_post(posts[1]["id"], beta)["content"] == "1"


def test_another_readers_real_delivery_id_cannot_be_acked(lab):
    service, _, exp, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Updates"), alpha, "topic"
    )
    service.subscribe_discussion(topic["id"], True, alpha, "sub-alpha")
    service.subscribe_discussion(topic["id"], True, beta, "sub-beta")
    service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="update", content="shared"), alpha, "post"
    )
    alpha_batch = service.discussion_updates(exp["id"], alpha)
    beta_batch = service.discussion_updates(exp["id"], beta)
    assert alpha_batch["delivery_id"] != beta_batch["delivery_id"]
    with pytest.raises(HarnessError) as error:
        service.acknowledge_discussion_updates(
            exp["id"], alpha_batch["delivery_id"], beta, "forged-ack"
        )
    assert error.value.code == "DELIVERY_MISMATCH"


def test_policy_revocation_withdraws_pending_excerpt_and_allows_later_message(lab):
    service, author, exp, branches, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Updates"), alpha, "topic"
    )
    service.subscribe_discussion(topic["id"], True, beta, "subscribe")
    post = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="update", content="sensitive excerpt"), alpha, "post"
    )
    batch = service.discussion_updates(exp["id"], beta)
    with service.db.transaction() as session:
        row = session.get(RecordRow, exp["id"])
        service._replace(session, row, {"sharing": "none"})
    with pytest.raises(HarnessError):
        service.get_record("discussion_delivery", batch["delivery_id"], beta)
    assert "sensitive excerpt" not in str(service.export_experiment(exp["id"], beta))
    following = service.send_message(
        branches[1]["id"], branches[1]["id"], "valid after revocation", [], beta, "self"
    )
    restarted = HarnessService(service.db, service.artifacts)
    redelivery = restarted.discussion_updates(exp["id"], beta)
    assert redelivery["delivery_id"] == batch["delivery_id"]
    assert redelivery["items"][0]["source_kind"] == "withdrawal"
    assert post["id"] not in str(redelivery)
    assert "sensitive excerpt" not in str(redelivery)
    assert post["id"] not in str(
        restarted.get_record("discussion_delivery", batch["delivery_id"], beta)
    )
    assert restarted.page_records("discussion_withdrawal", beta, exp["id"])["items"] == []
    assert restarted.page_records("discussion_withdrawal", author, exp["id"])["items"] == []
    assert restarted.export_experiment(exp["id"], author)["records"]["discussion_withdrawal"] == []
    operator = Principal(id="audit-operator", project_id=author.project_id, role="operator")
    audit = restarted.page_records("discussion_withdrawal", operator, exp["id"])["items"]
    assert len(audit) == 1 and audit[0]["source_record_id"] == post["id"]
    assert restarted.get_record("discussion_withdrawal", audit[0]["id"], operator) == audit[0]
    with pytest.raises(HarnessError):
        restarted.get_record("discussion_withdrawal", audit[0]["id"], author)
    assert (
        restarted.export_experiment(exp["id"], operator)["records"]["discussion_withdrawal"]
        == audit
    )
    assert "discussion.source_withdrawn" not in str(restarted.events(author, limit=1000))
    ack = restarted.acknowledge_discussion_updates(exp["id"], batch["delivery_id"], beta, "ack")
    assert ack["withdrawn_count"] == 1 and ack["delivered_count"] == 0
    assert (
        restarted.acknowledge_discussion_updates(exp["id"], batch["delivery_id"], beta, "ack")
        == ack
    )
    assert restarted.discussion_updates(exp["id"], beta)["items"][0]["id"] == following["id"]


def test_undelivered_revocation_yields_notice_before_later_valid_message(lab):
    service, _, exp, branches, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Updates"), alpha, "topic"
    )
    service.subscribe_discussion(topic["id"], True, beta, "subscribe")
    post = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="finding", content="now private"), alpha, "post"
    )
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, exp["id"]), {"sharing": "none"})
    following = service.send_message(
        branches[1]["id"], branches[1]["id"], "still readable", [], beta, "self"
    )
    batch = service.discussion_updates(exp["id"], beta)
    assert [item["source_kind"] for item in batch["items"]] == ["withdrawal", "message"]
    assert post["id"] not in str(batch)
    assert batch["items"][1]["id"] == following["id"]
    assert (
        service.acknowledge_discussion_updates(exp["id"], batch["delivery_id"], beta, "ack")[
            "withdrawn_count"
        ]
        == 1
    )


def test_historical_unreadable_attachment_withdraws_without_leaking_id(lab):
    service, author, exp, branches, (alpha, beta) = approaches(lab, "ideas")
    checkpoint = service.create_artifact(
        ArtifactCreate(
            experiment_id=exp["id"],
            branch_id=alpha.branch_id,
            kind="checkpoint",
            content="private state",
        ),
        author.model_copy(update={"role": "operator"}),
        "checkpoint",
    )
    poisoned = service.send_message(
        branches[0]["id"], branches[1]["id"], "old message", [], alpha, "old"
    )
    # Simulate a message persisted before recipient-side attachment admission existed.
    with service.db.transaction() as session:
        service._replace(
            session, session.get(RecordRow, poisoned["id"]), {"artifact_ids": [checkpoint["id"]]}
        )
    healthy = service.send_message(
        branches[0]["id"], branches[1]["id"], "healthy message", [], alpha, "healthy"
    )
    with pytest.raises(HarnessError):
        service.get_record("message", poisoned["id"], beta)
    assert poisoned["id"] not in str(service.mailbox_page(branches[1]["id"], beta))
    assert poisoned["id"] not in str(service.page_records("message", beta, exp["id"]))
    assert poisoned["id"] not in str(service.events(beta, limit=1000))
    assert checkpoint["id"] not in str(service.export_experiment(exp["id"], beta))
    batch = service.discussion_updates(exp["id"], beta)
    assert [item["source_kind"] for item in batch["items"]] == ["withdrawal", "message"]
    assert batch["items"][1]["id"] == healthy["id"]
    assert poisoned["id"] not in str(batch) and checkpoint["id"] not in str(batch)


def test_same_branch_readable_checkpoint_message_is_delivered(lab):
    service, author, exp, branches, (alpha, _) = approaches(lab, "ideas")
    checkpoint = service.create_artifact(
        ArtifactCreate(
            experiment_id=exp["id"],
            branch_id=alpha.branch_id,
            kind="checkpoint",
            content="own state",
        ),
        author.model_copy(update={"role": "operator"}),
        "checkpoint",
    )
    message = service.send_message(
        branches[0]["id"],
        branches[0]["id"],
        "resume from own state",
        [checkpoint["id"]],
        alpha,
        "self-message",
    )
    batch = service.discussion_updates(exp["id"], alpha)
    assert batch["items"][0]["source_kind"] == "message"
    assert batch["items"][0]["id"] == message["id"]


def test_missing_canonical_source_is_error_not_withdrawal(lab):
    service, _, exp, branches, (alpha, beta) = approaches(lab, "ideas")
    message = service.send_message(
        branches[0]["id"], branches[1]["id"], "source", [], alpha, "message"
    )
    with service.db.transaction() as session:
        session.delete(session.get(RecordRow, message["id"]))
    with pytest.raises(HarnessError) as error:
        service.discussion_updates(exp["id"], beta)
    assert error.value.code == "DELIVERY_SOURCE_MISSING"


def test_ack_requires_revocation_notice_checkpoint_before_advancing(lab):
    service, _, exp, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Updates"), alpha, "topic"
    )
    service.subscribe_discussion(topic["id"], True, beta, "subscribe")
    post = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="finding", content="revoked"), alpha, "post"
    )
    batch = service.discussion_updates(exp["id"], beta)
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, exp["id"]), {"sharing": "none"})
    with pytest.raises(HarnessError) as error:
        service.acknowledge_discussion_updates(exp["id"], batch["delivery_id"], beta, "ack")
    assert error.value.code == "DELIVERY_CHANGED"
    redelivery = service.discussion_updates(exp["id"], beta)
    assert redelivery["delivery_id"] == batch["delivery_id"]
    assert redelivery["items"][0]["source_kind"] == "withdrawal"
    ack = service.acknowledge_discussion_updates(exp["id"], batch["delivery_id"], beta, "ack")
    assert ack["withdrawn_count"] == 1 and ack["delivered_count"] == 0
    assert post["id"] not in str(
        service.get_record("discussion_delivery", batch["delivery_id"], beta)
    )


def test_addressed_message_delivers_without_subscriptions_and_survives_restart(lab):
    service, _, exp, branches, (alpha, beta) = approaches(lab, "ideas")
    message = service.send_message(
        branches[0]["id"], branches[1]["id"], "try symmetry", [], alpha, "message"
    )
    batch = service.discussion_updates(exp["id"], beta)
    assert [(item["source_kind"], item["id"]) for item in batch["items"]] == [
        ("message", message["id"])
    ]
    assert service.read_research_message(message["id"], beta)["content"] == "try symmetry"
    with pytest.raises(HarnessError):
        service.read_research_message(message["id"], alpha)
    with pytest.raises(HarnessError):
        service.get_record("discussion_delivery", batch["delivery_id"], alpha)
    restarted = HarnessService(service.db, service.artifacts)
    assert restarted.discussion_updates(exp["id"], beta)["items"] == batch["items"]
    restarted.acknowledge_discussion_updates(exp["id"], batch["delivery_id"], beta, "ack")
    assert restarted.discussion_updates(exp["id"], beta)["items"] == []


def test_messages_and_posts_share_one_ordered_delivery_cursor(lab):
    service, _, exp, branches, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Updates"), alpha, "topic"
    )
    service.subscribe_discussion(topic["id"], True, beta, "subscribe")
    post = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="finding", content="first"), alpha, "post"
    )
    message = service.send_message(
        branches[0]["id"], branches[1]["id"], "second", [], alpha, "message"
    )
    batch = service.discussion_updates(exp["id"], beta, limit=1)
    assert [(item["source_kind"], item["id"]) for item in batch["items"]] == [
        ("discussion_post", post["id"])
    ]
    service.acknowledge_discussion_updates(exp["id"], batch["delivery_id"], beta, "ack-post")
    next_batch = service.discussion_updates(exp["id"], beta, limit=1)
    assert [(item["source_kind"], item["id"]) for item in next_batch["items"]] == [
        ("message", message["id"])
    ]


def test_irrelevant_messages_do_not_starve_addressed_message(lab):
    service, _, exp, branches, (alpha, beta) = approaches(lab, "ideas")
    for n in range(105):
        service.send_message(
            branches[0]["id"], branches[0]["id"], f"self {n}", [], alpha, f"self-{n}"
        )
    wanted = service.send_message(
        branches[0]["id"], branches[1]["id"], "for beta", [], alpha, "wanted"
    )
    batch = service.discussion_updates(exp["id"], beta)
    assert [item["id"] for item in batch["items"]] == [wanted["id"]]
