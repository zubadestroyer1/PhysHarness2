"""Commons discourse: expiring work claims, node threads, subscriptions and urgent digests."""

import json

import pytest
from commons_helpers import set_status, society_lab
from pydantic import ValidationError
from sqlalchemy import update
from test_sharing import approaches, artifact

from physharness import commons_discourse
from physharness.commons import PLATFORM
from physharness.commons_models import NodeCreate, NodePostCreate
from physharness.discussion_models import DiscussionCreate, DiscussionPostCreate
from physharness.domain import Principal, TaskCreate, digest_json, new_id
from physharness.errors import HarnessError
from physharness.storage import CommandRow, RecordRow

# Recorded from the pre-change code (tests/commons-free legacy discussion flow).
LEGACY_ITEM_KEYS = [
    "id",
    "topic_id",
    "sequence",
    "post_kind",
    "attributed_to",
    "branch_id",
    "excerpt",
    "truncated",
    "retrieval_post_id",
    "retrieval_id",
    "source_kind",
    "evidence_status",
]
LEGACY_TOPIC_KEYS = [
    "experiment_id",
    "branch_id",
    "title",
    "summary",
    "attributed_to",
    "evidence_status",
    "problem_revision_id",
    "target_digest",
    "environment_digest",
    "origin_actor_id",
    "id",
    "kind",
    "project_id",
    "revision",
    "created_at",
]
LEGACY_SUBSCRIPTION_KEYS = [
    "experiment_id",
    "topic_id",
    "reader_key",
    "branch_id",
    "subscribed",
    "start_sequence",
    "origin_actor_id",
    "id",
    "kind",
    "project_id",
    "revision",
    "created_at",
]
LEGACY_POST_KEYS = [
    "experiment_id",
    "topic_id",
    "branch_id",
    "attributed_to",
    "post_kind",
    "content",
    "reply_to_post_id",
    "artifact_ids",
    "reference_post_ids",
    "evidence_status",
    "problem_revision_id",
    "target_digest",
    "environment_digest",
    "origin_actor_id",
    "id",
    "kind",
    "project_id",
    "revision",
    "created_at",
    "sequence",
]


def lemma(title="Trace lemma", statement="The trace is additive.", **extra):
    return NodeCreate(node_type="lemma", title=title, statement=statement, **extra)


def depends(target_id):
    return [{"relation": "depends_on", "target_id": target_id}]


def note(kind="finding", abstract="Claim: bound holds. Evidence: sketch. Ask: check.", **extra):
    return NodePostCreate(kind=kind, abstract=abstract, **extra)


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fixed = Clock()
    monkeypatch.setattr(commons_discourse, "_now", fixed)
    return fixed


def drain(service, experiment_id, actor):
    """Read one delivery and acknowledge it."""
    batch = service.discussion_updates(experiment_id, actor)
    if batch["delivery_id"]:
        service.acknowledge_discussion_updates(
            experiment_id, batch["delivery_id"], actor, f"ack-{batch['delivery_id']}"
        )
    return batch


def subscribed_topics(service, actor, experiment_id):
    return {
        s["topic_id"]
        for s in service.list_records("discussion_subscription", actor, experiment_id)
        if s["subscribed"]
    }


def test_node_has_thread_and_author_subscribed(lab):
    service, author, exp, branches, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(statement="S" * 5000), alpha, "node")
    assert node["topic_id"] and node["auto_subscribed"] is True
    stored = service.get_record("commons_node", node["id"], beta)
    assert stored["topic_id"] == node["topic_id"] and "auto_subscribed" not in stored
    topic = service.get_record("discussion_topic", node["topic_id"], beta)
    assert topic["title"] == "[lemma] Trace lemma"
    assert topic["summary"] == "S" * 4000
    assert topic["node_id"] == node["id"]
    assert topic["branch_id"] == branches[0]["id"]
    assert subscribed_topics(service, alpha, exp["id"]) == {node["topic_id"]}
    assert subscribed_topics(service, beta, exp["id"]) == set()
    # Long titles are clipped to the topic bound.
    long = service.create_node(exp["id"], lemma(title="T" * 200), beta, "long")
    assert service.get_record("discussion_topic", long["topic_id"], alpha)["title"] == (
        "[lemma] " + "T" * 192
    )
    goal = service.ensure_goal_node(exp["id"], author)
    goal_topic = service.get_record("discussion_topic", goal["topic_id"], alpha)
    assert goal_topic["title"] == f"[goal] {goal['title']}"[:200]
    assert goal_topic["node_id"] == goal["id"] and goal_topic["branch_id"] is None
    assert goal_topic["attributed_to"] == PLATFORM
    everyone = service.list_records("discussion_subscription", author, exp["id"])
    assert goal["topic_id"] not in {s["topic_id"] for s in everyone}
    # The thread is a real topic: peers' posts reach the subscribed author.
    posted = service.post_on_node(node["id"], note(), beta, "post")
    assert posted["topic_id"] == node["topic_id"] and posted["node_id"] == node["id"]
    assert [item["id"] for item in drain(service, exp["id"], alpha)["items"]] == [posted["id"]]


def test_claim_expires_lazily(lab, clock):
    service, _, exp, _, (alpha, beta) = society_lab(lab, claim_ttl_seconds=120)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    claim = service.claim_node(node["id"], "claim", beta, "claim")
    assert claim["expires_at"] == clock.now + 120
    assert claim["released"] is False and claim["task_id"] is None
    assert claim["branch_id"] == beta.branch_id and claim["node_id"] == node["id"]
    assert claim["experiment_id"] == exp["id"]
    live = {"branch_id": beta.branch_id, "task_id": None, "expires_at": clock.now + 120}
    assert service.read_node(node["id"], alpha)["claimants"] == [live]
    clock.now += 119
    assert service.read_node(node["id"], alpha)["claimants"] == [live]
    clock.now += 1
    assert service.read_node(node["id"], alpha)["claimants"] == []
    # Nothing was written to expire the claim; expiry is a read-time comparison.
    assert service.get_record("commons_claim", claim["id"], alpha)["released"] is False
    again = service.claim_node(node["id"], "claim", beta, "claim-again")
    assert again["id"] == claim["id"] and again["expires_at"] == clock.now + 120


def test_renew_requires_live_claim(lab, clock):
    service, _, exp, _, (alpha, beta) = society_lab(lab, claim_ttl_seconds=120)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    with pytest.raises(HarnessError) as err:
        service.claim_node(node["id"], "renew", alpha, "renew-none")
    assert err.value.code == "CLAIM_NOT_HELD"
    service.claim_node(node["id"], "claim", alpha, "claim")
    clock.now += 60
    renewed = service.claim_node(node["id"], "renew", alpha, "renew")
    assert renewed["expires_at"] == clock.now + 120
    clock.now += 120
    with pytest.raises(HarnessError) as err:
        service.claim_node(node["id"], "renew", alpha, "renew-expired")
    assert err.value.code == "CLAIM_NOT_HELD"
    with pytest.raises(HarnessError) as err:
        service.claim_node(node["id"], "steal", alpha, "bad-action")
    assert err.value.status == 422


def test_release_hides_claimant(lab, clock):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    service.claim_node(node["id"], "claim", beta, "claim")
    released = service.claim_node(node["id"], "release", beta, "release")
    assert released["released"] is True
    assert service.read_node(node["id"], alpha)["claimants"] == []
    frontier = service.query_nodes(exp["id"], alpha, frontier=True)["items"]
    item = next(i for i in frontier if i["id"] == node["id"])
    assert item["score_components"]["claimants"] == 0.0
    with pytest.raises(HarnessError) as err:
        service.claim_node(node["id"], "renew", beta, "renew-released")
    assert err.value.code == "CLAIM_NOT_HELD"
    with pytest.raises(HarnessError) as err:
        service.claim_node(node["id"], "release", alpha, "release-never-claimed")
    assert err.value.code == "CLAIM_NOT_HELD"
    with pytest.raises(HarnessError) as err:
        service.claim_node(node["id"], "claim", author, "branchless")
    assert err.value.code == "BRANCH_AUTHORITY"


def test_multiple_claimants_visible_and_lower_frontier_score(lab, clock):
    service, _, exp, _, (alpha, beta) = society_lab(lab, claim_ttl_seconds=300)
    claimed = service.create_node(exp["id"], lemma("Claimed"), alpha, "claimed")
    free = service.create_node(exp["id"], lemma("Free"), alpha, "free")
    service.claim_node(claimed["id"], "claim", alpha, "claim-a")
    clock.now += 5
    service.claim_node(claimed["id"], "claim", beta, "claim-b")
    claimants = service.read_node(claimed["id"], beta)["claimants"]
    assert sorted(claimants, key=lambda c: c["branch_id"]) == claimants
    assert {c["branch_id"]: c["expires_at"] for c in claimants} == {
        alpha.branch_id: clock.now - 5 + 300,
        beta.branch_id: clock.now + 300,
    }
    frontier = service.query_nodes(exp["id"], beta, frontier=True)["items"]
    by_id = {item["id"]: item for item in frontier}
    assert by_id[claimed["id"]]["score_components"]["claimants"] == -2.0
    assert by_id[free["id"]]["score_components"]["claimants"] == 0.0
    assert by_id[claimed["id"]]["score"] == pytest.approx(
        by_id[free["id"]]["score"] - 2.0, abs=0.01
    )
    order = [item["id"] for item in frontier]
    assert order.index(free["id"]) < order.index(claimed["id"])


def test_claim_closed_node_rejected(lab, clock):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    service.claim_node(node["id"], "claim", beta, "claim")
    service.abandon_node(node["id"], "Dead end.", alpha, "abandon")
    for action in ("claim", "renew"):
        with pytest.raises(HarnessError) as err:
            service.claim_node(node["id"], action, beta, f"closed-{action}")
        assert err.value.code == "NODE_CLOSED"
    # A holder may still let go of work on a closed node.
    assert service.claim_node(node["id"], "release", beta, "release")["released"] is True
    accepted = service.create_node(exp["id"], lemma("Done"), alpha, "done")
    set_status(service, accepted["id"], "formally_stated", "accepted")
    with pytest.raises(HarnessError) as err:
        service.claim_node(accepted["id"], "claim", beta, "accepted-claim")
    assert err.value.code == "NODE_CLOSED"


def test_claim_records_bound_worker_task_and_subscribes(lab, clock):
    from physharness.worker_authority import worker_effects

    service, author, exp, branches, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    task = service.create_task(
        TaskCreate(branch_id=branches[1]["id"], objective="Prove it"), author, "task"
    )
    operator = Principal(id="controller", project_id=author.project_id, role="operator")
    lease = service.acquire_task(task["id"], "holder", 60, operator, "lease")
    with worker_effects(beta, task["id"], "holder", lease["fence"]):
        claim = service.claim_node(node["id"], "claim", beta, "claim")
    assert claim["task_id"] == task["id"] and claim["auto_subscribed"] is True
    assert service.read_node(node["id"], alpha)["claimants"][0]["task_id"] == task["id"]
    assert subscribed_topics(service, beta, exp["id"]) == {node["topic_id"]}
    assert {e["kind"] for e in service.events(author, limit=1000)} >= {"commons.node_claim"}


def test_post_renews_posters_claim(lab, clock):
    service, _, exp, _, (alpha, beta) = society_lab(lab, claim_ttl_seconds=120)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    before = service.get_record("commons_node", node["id"], alpha)["last_activity_at"]
    service.claim_node(node["id"], "claim", alpha, "claim-a")
    service.claim_node(node["id"], "claim", beta, "claim-b")
    start = clock.now
    clock.now += 100
    service.post_on_node(node["id"], note(), alpha, "post")
    expiry = {
        c["branch_id"]: c["expires_at"] for c in service.read_node(node["id"], beta)["claimants"]
    }
    assert expiry == {alpha.branch_id: clock.now + 120, beta.branch_id: start + 120}
    assert service.get_record("commons_node", node["id"], alpha)["last_activity_at"] > before
    # A post never creates a claim for a poster who holds none.
    other = service.create_node(exp["id"], lemma("Other"), alpha, "other")
    service.post_on_node(other["id"], note(), beta, "post-other")
    assert service.read_node(other["id"], alpha)["claimants"] == []


def test_post_on_node_rules(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    _, _, other, _, (stranger, _) = society_lab(lab, prefix="other")
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    evidence = artifact(service, beta, "numeric evidence")
    first = service.post_on_node(
        node["id"], note(body="Full derivation.", artifact_ids=[evidence["id"]]), beta, "first"
    )
    assert first["content"] == "Full derivation."
    assert first["abstract"] == note().abstract and first["cites"] == []
    assert first["post_kind"] == "finding" and first["branch_id"] == beta.branch_id
    assert first["reference_post_ids"] == [] and first["artifact_ids"] == [evidence["id"]]
    reply = service.post_on_node(
        node["id"], note(kind="attempt_failed", reply_to_post_id=first["id"]), alpha, "reply"
    )
    assert reply["content"] == reply["abstract"] and reply["reply_to_post_id"] == first["id"]
    foreign = service.create_node(other["id"], lemma("Foreign"), stranger, "foreign")
    for request, code in (
        (note(cites=[foreign["id"]]), "NOT_FOUND"),
        (note(reply_to_post_id=foreign["topic_id"]), "NOT_FOUND"),
    ):
        with pytest.raises(HarnessError) as err:
            service.post_on_node(node["id"], request, beta, f"bad-{code}-{len(str(request))}")
        assert err.value.code == code
    with pytest.raises(ValidationError):
        note(cites=[node["id"], node["id"]])
    with pytest.raises(ValidationError):
        note(abstract="   ")
    with pytest.raises(ValidationError):
        note(abstract="x" * 601)
    service.abandon_node(node["id"], "Superseded.", alpha, "abandon")
    for kind in ("question", "finding", "objection", "attempt_failed"):
        with pytest.raises(HarnessError) as err:
            service.post_on_node(node["id"], note(kind=kind), beta, f"closed-{kind}")
        assert err.value.code == "NODE_CLOSED"
    for kind in ("synthesis", "update"):
        assert service.post_on_node(node["id"], note(kind=kind), beta, f"ok-{kind}")["id"]


def test_cite_increments_count_and_subscribes(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    cited = service.create_node(exp["id"], lemma("Cited"), alpha, "cited")
    host = service.create_node(exp["id"], lemma("Host"), alpha, "host")
    posted = service.post_on_node(host["id"], note(cites=[cited["id"]]), beta, "post")
    assert posted["cites"] == [cited["id"]] and posted["auto_subscribed"] is True
    assert service.get_record("commons_node", cited["id"], beta)["citation_count"] == 1
    assert service.get_record("commons_node", host["id"], beta)["citation_count"] == 0
    assert subscribed_topics(service, beta, exp["id"]) == {cited["topic_id"]}
    service.post_on_node(host["id"], note(cites=[cited["id"]]), alpha, "again")
    assert service.get_record("commons_node", cited["id"], beta)["citation_count"] == 2
    listed = service.query_nodes(exp["id"], beta, text="Cited")["items"]
    assert [n["citation_count"] for n in listed if n["id"] == cited["id"]] == [2]
    update = service.post_on_node(cited["id"], note(), alpha, "cited-update")
    assert update["id"] in [i["id"] for i in drain(service, exp["id"], beta)["items"]]


def test_depends_on_subscribes_source_author(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    target = service.create_node(exp["id"], lemma("Target"), beta, "target")
    dependent = service.create_node(
        exp["id"], lemma("Dependent", edges=depends(target["id"])), alpha, "dependent"
    )
    assert subscribed_topics(service, alpha, exp["id"]) == {
        dependent["topic_id"],
        target["topic_id"],
    }
    # Linking later subscribes the source's author, whoever draws the edge.
    later = service.create_node(exp["id"], lemma("Later target"), beta, "later")
    service.link_nodes(exp["id"], dependent["id"], "depends_on", later["id"], author, "link")
    assert later["topic_id"] in subscribed_topics(service, alpha, exp["id"])
    other = service.create_node(exp["id"], lemma("Unrelated"), beta, "unrelated")
    service.link_nodes(exp["id"], dependent["id"], "motivated_by", other["id"], beta, "motive")
    assert other["topic_id"] not in subscribed_topics(service, alpha, exp["id"])
    posted = service.post_on_node(later["id"], note(), beta, "news")
    assert [i["id"] for i in drain(service, exp["id"], alpha)["items"]] == [posted["id"]]


def test_status_change_posts_platform_update_to_subscribers(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    service.claim_node(node["id"], "claim", beta, "claim")
    set_status(service, node["id"], "refereed", reason="quorum met")
    for reader in (alpha, beta):
        (item,) = drain(service, exp["id"], reader)["items"]
        assert item["attributed_to"] == PLATFORM and item["post_kind"] == "update"
        assert item["excerpt"] == "Status informal → refereed: quorum met"
        assert item["node_id"] == node["id"] and item["urgent"] is False
        assert item["branch_id"] is None
    full = service.read_discussion_post(item["id"], beta)
    assert full["platform_status"] == {"from": "informal", "to": "refereed", "reason": "quorum met"}
    assert full["topic_id"] == node["topic_id"] and full["node_id"] == node["id"]
    assert full["abstract"] == full["content"] == item["excerpt"]
    long = set_status(service, node["id"], "formally_stated", reason="r" * 2000)
    assert long["status"] == "formally_stated"
    (item,) = drain(service, exp["id"], alpha)["items"]
    assert len(service.read_discussion_post(item["id"], alpha)["abstract"]) == 600


def test_objection_on_own_node_is_urgent_and_first(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    service.claim_node(node["id"], "claim", beta, "claim")
    finding = service.post_on_node(node["id"], note(), beta, "finding")
    objection = service.post_on_node(node["id"], note(kind="objection"), beta, "objection")
    batch = service.discussion_updates(exp["id"], alpha)
    assert [(i["id"], i["urgent"]) for i in batch["items"]] == [
        (objection["id"], True),
        (finding["id"], False),
    ]
    # The acknowledgement cursor is the highest delivered sequence, not the last item's.
    assert batch["next_cursor"] == objection["sequence"] > finding["sequence"]
    again = service.discussion_updates(exp["id"], alpha)
    assert again["redelivered"] is True and again["items"] == batch["items"]
    ack = service.acknowledge_discussion_updates(exp["id"], batch["delivery_id"], alpha, "ack")
    assert ack["next_cursor"] == objection["sequence"]
    assert service.discussion_updates(exp["id"], alpha)["items"] == []
    # Another subscriber's copy of the same objection is not urgent: it is not their node.
    theirs = drain(service, exp["id"], beta)["items"]
    assert [(i["id"], i["urgent"]) for i in theirs] == [
        (finding["id"], False),
        (objection["id"], False),
    ]


def test_accepted_dependency_is_urgent(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    lemma_a = service.create_node(exp["id"], lemma("A"), alpha, "a")
    service.create_node(exp["id"], lemma("B", edges=depends(lemma_a["id"])), beta, "b")
    set_status(service, lemma_a["id"], "formally_stated", "accepted", reason="kernel receipt")
    items = drain(service, exp["id"], beta)["items"]
    assert [(i["excerpt"], i["urgent"]) for i in items] == [
        ("Status formally_stated → accepted: kernel receipt", True),
        ("Status informal → formally_stated: kernel receipt", False),
    ]
    refuted = service.create_node(exp["id"], lemma("C"), alpha, "c")
    drain(service, exp["id"], alpha)
    set_status(service, refuted["id"], "refuted", reason="counterexample")
    (item,) = drain(service, exp["id"], alpha)["items"]
    assert item["urgent"] is True and item["node_id"] == refuted["id"]


def test_node_post_excerpt_uses_abstract(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    abstract = "Claim: gap closes. Evidence: numerics. Ask: referee the bound."
    detailed = service.post_on_node(
        node["id"], note(abstract=abstract, body="B" * 5000), beta, "p1"
    )
    brief = service.post_on_node(node["id"], note(abstract=abstract), beta, "p2")
    wide = service.post_on_node(node["id"], note(abstract="∀" * 600, body="x"), beta, "p3")
    items = {i["id"]: i for i in drain(service, exp["id"], alpha)["items"]}
    assert items[detailed["id"]]["excerpt"] == abstract
    assert items[detailed["id"]]["truncated"] is True
    assert items[brief["id"]]["excerpt"] == abstract
    assert items[brief["id"]]["truncated"] is False
    assert set(items[brief["id"]]) == {*LEGACY_ITEM_KEYS, "node_id", "urgent"}
    # Multi-byte abstracts are clipped to the per-item byte bound instead of failing delivery.
    assert "∀" * 100 in items[wide["id"]]["excerpt"] and items[wide["id"]]["truncated"] is True
    for item in items.values():
        assert len(json.dumps(item, ensure_ascii=False).encode("utf-8")) <= 2048
    assert service.read_discussion_post(detailed["id"], alpha)["content"] == "B" * 5000


def test_auto_subscriptions_respect_reader_cap(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    with service.db.transaction() as session:
        for n in range(100):
            service._insert(
                session,
                "discussion_subscription",
                alpha,
                {
                    "experiment_id": exp["id"],
                    "topic_id": f"filler-{n}",
                    "reader_key": f"branch:{alpha.branch_id}",
                    "branch_id": alpha.branch_id,
                    "subscribed": True,
                    "start_sequence": 0,
                },
            )
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    assert node["auto_subscribed"] is False
    peer = service.create_node(exp["id"], lemma("Peer"), beta, "peer")
    assert service.claim_node(peer["id"], "claim", alpha, "claim")["auto_subscribed"] is False
    cited = service.post_on_node(node["id"], note(cites=[peer["id"]]), alpha, "cite")
    assert cited["auto_subscribed"] is False
    service.link_nodes(exp["id"], node["id"], "depends_on", peer["id"], beta, "link")
    assert len(subscribed_topics(service, alpha, exp["id"])) == 100
    # The inbox keeps working at the cap; explicit subscriptions still report the limit.
    assert service.discussion_updates(exp["id"], alpha)["items"] == []
    with pytest.raises(HarnessError) as err:
        service.subscribe_discussion(peer["topic_id"], True, alpha, "explicit")
    assert err.value.code == "SUBSCRIPTION_LIMIT"


def test_legacy_discussion_delivery_shape_unchanged(lab):
    service, _, exp, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Research"), alpha, "topic"
    )
    subscription = service.subscribe_discussion(topic["id"], True, beta, "subscribe")
    post = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="finding", content="An idea"), alpha, "post"
    )
    objection = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="objection", content="A gap"), beta, "objection"
    )
    assert list(topic) == LEGACY_TOPIC_KEYS
    assert list(subscription) == LEGACY_SUBSCRIPTION_KEYS
    assert list(post) == LEGACY_POST_KEYS
    batch = service.discussion_updates(exp["id"], beta)
    assert list(batch) == ["delivery_id", "items", "next_cursor", "redelivered"]
    assert [list(item) for item in batch["items"]] == [LEGACY_ITEM_KEYS, LEGACY_ITEM_KEYS]
    assert [item["id"] for item in batch["items"]] == [post["id"], objection["id"]]
    assert batch["items"][0]["excerpt"] == "An idea"
    # Command fingerprints of legacy posts are unchanged: no abstract key is fingerprinted.
    inputs = {
        "topic_id": topic["id"],
        "kind": "finding",
        "content": "An idea",
        "reply_to_post_id": None,
        "artifact_ids": [],
        "reference_post_ids": [],
    }
    expected = digest_json(
        ["discussion.post", inputs, alpha.role, alpha.experiment_id, alpha.branch_id, False]
    )
    with service.db.sessions() as session:
        command = session.get(CommandRow, digest_json([alpha.project_id, alpha.id, "post"]))
        assert command.fingerprint == expected
        stored = session.get(RecordRow, post["id"]).payload
    assert list(stored) == LEGACY_POST_KEYS


def test_discussion_post_gains_attempt_failed_and_optional_abstract(lab):
    service, _, exp, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Research"), alpha, "topic"
    )
    failed = service.post_discussion(
        topic["id"],
        DiscussionPostCreate(kind="attempt_failed", content="Tried induction", abstract="Dead"),
        alpha,
        "failed",
    )
    assert failed["post_kind"] == "attempt_failed" and failed["abstract"] == "Dead"
    with pytest.raises(ValidationError):
        DiscussionPostCreate(kind="finding", content="x", abstract="a" * 601)


# Fix round 1 -----------------------------------------------------------------------------


def concurrent_write(service, monkeypatch, node_id, **values):
    """Commit-like write to a node while the command waits for the experiment lock.

    The raw UPDATE bypasses the session identity map, as a write committed by another
    PostgreSQL transaction would: the row loaded before the lock is now stale.
    """
    original = service._commons_experiment

    def locked(session, experiment_id, actor, **kwargs):
        if not getattr(locked, "done", False):
            locked.done = True
            row = session.get(RecordRow, node_id)
            revision = row.revision + 1
            session.execute(
                update(RecordRow)
                .where(RecordRow.id == node_id)
                .values(revision=revision, payload={**row.payload, **values, "revision": revision}),
                execution_options={"synchronize_session": False},
            )
        return original(session, experiment_id, actor, **kwargs)

    monkeypatch.setattr(service, "_commons_experiment", locked)


def test_post_rereads_node_after_experiment_lock(lab, monkeypatch):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    concurrent_write(service, monkeypatch, node["id"], citation_count=5)
    service.post_on_node(node["id"], note(), beta, "post")
    stored = service.get_record("commons_node", node["id"], alpha)
    assert stored["citation_count"] == 5 and stored["last_activity_at"] > node["last_activity_at"]
    closing = service.create_node(exp["id"], lemma("Closing"), alpha, "closing")
    concurrent_write(service, monkeypatch, closing["id"], status="abandoned")
    with pytest.raises(HarnessError) as err:
        service.post_on_node(closing["id"], note(), beta, "late-post")
    assert err.value.code == "NODE_CLOSED"


def test_claim_rereads_node_after_experiment_lock(lab, monkeypatch):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    concurrent_write(service, monkeypatch, node["id"], status="refuted")
    with pytest.raises(HarnessError) as err:
        service.claim_node(node["id"], "claim", beta, "claim")
    assert err.value.code == "NODE_CLOSED"
    assert service.read_node(node["id"], alpha)["claimants"] == []


def test_post_discussion_rejects_node_threads(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    with pytest.raises(HarnessError) as err:
        service.post_discussion(
            node["topic_id"], DiscussionPostCreate(kind="finding", content="Bypass"), beta, "x"
        )
    assert err.value.code == "NODE_THREAD_USE_COMMONS" and err.value.status == 409
    assert "post_on_node" in err.value.remediation
    # Ordinary topics in a society experiment keep the legacy path.
    topic = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Research"), alpha, "topic"
    )
    posted = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="finding", content="Fine"), beta, "ok"
    )
    assert posted["topic_id"] == topic["id"] and "node_id" not in posted


def test_own_objection_is_not_urgent_for_its_author(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    own = service.post_on_node(node["id"], note(kind="objection"), alpha, "own")
    peer = service.post_on_node(node["id"], note(kind="objection"), beta, "peer")
    items = drain(service, exp["id"], alpha)["items"]
    assert [(i["id"], i["urgent"]) for i in items] == [(peer["id"], True), (own["id"], False)]


def fill_subscriptions(service, actor, experiment_id, count):
    with service.db.transaction() as session:
        for n in range(count):
            service._insert(
                session,
                "discussion_subscription",
                actor,
                {
                    "experiment_id": experiment_id,
                    "topic_id": f"filler-{n}",
                    "reader_key": f"branch:{actor.branch_id}",
                    "branch_id": actor.branch_id,
                    "subscribed": True,
                    "start_sequence": 0,
                },
            )


def test_auto_subscribe_frees_oldest_closed_node_thread_at_cap(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    older = service.create_node(exp["id"], lemma("Older"), alpha, "older")
    newer = service.create_node(exp["id"], lemma("Newer"), alpha, "newer")
    active = service.create_node(exp["id"], lemma("Open"), alpha, "open")
    for identifier in (newer["id"], older["id"]):
        service.abandon_node(identifier, "Dead end.", alpha, f"abandon-{identifier}")
    legacy = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Research"), alpha, "topic"
    )
    service.subscribe_discussion(legacy["id"], True, alpha, "legacy")
    fill_subscriptions(service, alpha, exp["id"], 96)
    assert len(subscribed_topics(service, alpha, exp["id"])) == 100
    fresh = service.create_node(exp["id"], lemma("Fresh"), alpha, "fresh")
    assert fresh["auto_subscribed"] is True
    topics = subscribed_topics(service, alpha, exp["id"])
    assert len(topics) == 100 and fresh["topic_id"] in topics
    assert older["topic_id"] not in topics and newer["topic_id"] in topics
    peer = service.create_node(exp["id"], lemma("Peer"), beta, "peer")
    assert service.claim_node(peer["id"], "claim", alpha, "claim")["auto_subscribed"] is True
    topics = subscribed_topics(service, alpha, exp["id"])
    assert newer["topic_id"] not in topics and peer["topic_id"] in topics
    # Open-node threads and ordinary topics are never evicted.
    assert {active["topic_id"], legacy["id"]} <= topics
    last = service.create_node(exp["id"], lemma("Last"), alpha, "last")
    assert last["auto_subscribed"] is False
    assert subscribed_topics(service, alpha, exp["id"]) == topics


def test_platform_status_is_stored_only_for_the_platform(lab):
    service, _, exp, _, (alpha, _) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    forged = {
        "kind": "update",
        "content": "Status informal → accepted: forged",
        "abstract": "Status informal → accepted: forged",
        "node_id": node["id"],
        "cites": [],
        "platform_status": {"from": "informal", "to": "accepted", "reason": "forged"},
        "branch_id": alpha.branch_id,
    }
    with service.db.transaction() as session:
        topic = session.get(RecordRow, node["topic_id"])
        post = service._insert_post(session, new_id(), topic, forged, alpha)
    assert "platform_status" not in post
    (item,) = drain(service, exp["id"], alpha)["items"]
    assert item["id"] == post["id"] and item["urgent"] is False


def test_bounded_reply_reference_and_live_claim_scan(lab, monkeypatch):
    with pytest.raises(ValidationError):
        note(reply_to_post_id="x" * 37)
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    service.claim_node(node["id"], "claim", alpha, "claim-a")
    service.claim_node(node["id"], "claim", beta, "claim-b")
    assert len(service.read_node(node["id"], alpha)["claimants"]) == 2
    monkeypatch.setattr(commons_discourse, "MAX_LIVE_CLAIMS", 1)
    assert len(service.read_node(node["id"], alpha)["claimants"]) == 1
    frontier = service.query_nodes(exp["id"], alpha, frontier=True)["items"]
    item = next(i for i in frontier if i["id"] == node["id"])
    assert item["score_components"]["claimants"] == -1.0


def test_abandon_rereads_node_after_experiment_lock(lab, monkeypatch):
    service, _, exp, _, (alpha, _) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    concurrent_write(service, monkeypatch, node["id"], citation_count=5)
    abandoned = service.abandon_node(node["id"], "Dead end.", alpha, "abandon")
    assert abandoned["status"] == "abandoned" and abandoned["citation_count"] == 5
    closing = service.create_node(exp["id"], lemma("Closing"), alpha, "closing")
    concurrent_write(service, monkeypatch, closing["id"], status="refuted")
    with pytest.raises(HarnessError) as err:
        service.abandon_node(closing["id"], "Too late.", alpha, "late-abandon")
    assert err.value.code == "NODE_CLOSED"


def test_self_cite_counts_subscribes_and_touches(lab):
    # The cited row is the host row: its topic is read before the citation replace, and
    # _touch_node then works on the reloaded revision.
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    host = service.create_node(exp["id"], lemma("Host"), alpha, "host")
    posted = service.post_on_node(host["id"], note(cites=[host["id"]]), beta, "self-cite")
    assert posted["auto_subscribed"] is True
    stored = service.get_record("commons_node", host["id"], beta)
    assert stored["citation_count"] == 1
    assert stored["last_activity_at"] > host["last_activity_at"]
    assert subscribed_topics(service, beta, exp["id"]) == {host["topic_id"]}
    news = service.post_on_node(host["id"], note(), alpha, "news")
    assert news["id"] in [i["id"] for i in drain(service, exp["id"], beta)["items"]]


def cite_all(service, actor, host_id, node_ids, key):
    """Follow every node through citations: 20 cites per post."""
    for start in range(0, len(node_ids), 20):
        cites = node_ids[start : start + 20]
        service.post_on_node(host_id, note(cites=cites), actor, f"{key}-{start}")


def test_own_node_subscription_evicts_third_party_follow_at_cap(lab):
    """At the cap, a reader's own node still gets its thread, so objections reach it."""
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    peers = [service.create_node(exp["id"], lemma(f"Peer {n}"), beta, f"p{n}") for n in range(101)]
    cite_all(service, alpha, peers[100]["id"], [peer["id"] for peer in peers[:100]], "cite")
    before = subscribed_topics(service, alpha, exp["id"])
    assert before == {peer["topic_id"] for peer in peers[:100]}  # only third-party follows
    own = service.create_node(exp["id"], lemma("Mine"), alpha, "mine")
    assert own["auto_subscribed"] is True
    after = subscribed_topics(service, alpha, exp["id"])
    assert after == before - {peers[0]["topic_id"]} | {own["topic_id"]}  # the oldest follow
    objection = service.post_on_node(own["id"], note(kind="objection"), beta, "objection")
    first = service.discussion_updates(exp["id"], alpha)["items"][0]
    assert first["id"] == objection["id"] and first["urgent"] is True


def test_auto_subscribe_eviction_order_and_protected_threads(lab, clock):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    old_follow = service.create_node(exp["id"], lemma("Old follow"), beta, "old-follow")
    claimed = service.create_node(exp["id"], lemma("Claimed"), beta, "claimed")
    own = service.create_node(exp["id"], lemma("Own"), alpha, "own")
    closed = service.create_node(exp["id"], lemma("Closed"), beta, "closed")
    host = service.create_node(exp["id"], lemma("Host"), beta, "host")
    cite_all(service, alpha, host["id"], [old_follow["id"], closed["id"]], "cite")
    service.claim_node(claimed["id"], "claim", alpha, "claim")
    service.abandon_node(closed["id"], "Dead end.", beta, "abandon")
    legacy = service.create_discussion(
        exp["id"], DiscussionCreate(title="Board", summary="Research"), alpha, "topic"
    )
    service.subscribe_discussion(legacy["id"], True, alpha, "legacy")
    fill_subscriptions(service, alpha, exp["id"], 95)  # non-node topics are never evicted
    assert len(subscribed_topics(service, alpha, exp["id"])) == 100
    # 1. A closed-node thread goes first, although the third-party follow is older.
    first = service.create_node(exp["id"], lemma("First"), alpha, "first")
    topics = subscribed_topics(service, alpha, exp["id"])
    assert first["auto_subscribed"] is True
    assert closed["topic_id"] not in topics and old_follow["topic_id"] in topics
    # 2. Then the oldest follow of a node the reader neither wrote nor claims.
    second = service.create_node(exp["id"], lemma("Second"), alpha, "second")
    topics = subscribed_topics(service, alpha, exp["id"])
    assert second["auto_subscribed"] is True and old_follow["topic_id"] not in topics
    # Own nodes, live-claimed nodes and non-node topics are never evicted.
    assert {own["topic_id"], claimed["topic_id"], legacy["id"]} <= topics
    third = service.create_node(exp["id"], lemma("Third"), alpha, "third")
    assert third["auto_subscribed"] is False
    assert subscribed_topics(service, alpha, exp["id"]) == topics
    # A lapsed claim no longer protects its thread.
    clock.now += 10_000
    fourth = service.create_node(exp["id"], lemma("Fourth"), alpha, "fourth")
    topics = subscribed_topics(service, alpha, exp["id"])
    assert fourth["auto_subscribed"] is True and claimed["topic_id"] not in topics
