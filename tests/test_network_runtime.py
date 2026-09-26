"""Durable delivery at settled Responses boundaries."""

import json

import pytest
from test_execution_responses import client_for, message, response
from test_sharing import approaches

from physharness.discussion_models import DiscussionCreate, DiscussionPostCreate
from physharness.domain import Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import (
    ExecutionError,
    ModelConfig,
    ResponsesRuntime,
    RuntimeLimits,
    SQLiteRuntimeStore,
)
from physharness.execution.stagnation import observe
from physharness.orchestration.research_network import fair_ready_order
from physharness.orchestration.research_worker import research_tools
from physharness.storage import RecordRow
from physharness.worker_authority import worker_effects
from physharness.workforce_models import RecruitResearcherRequest


async def test_delivery_is_saved_before_ack_and_visible_to_provider(tmp_path):
    requests, events = [], []
    store = SQLiteRuntimeStore(tmp_path / "network.db")
    client = client_for([response([message("done")])], requests)

    async def source(checkpoint):
        events.append("read")
        return {"delivery_id": "d-1", "items": [{"post_id": "p-1", "excerpt": "try lemma"}]}

    async def acknowledge(delivery_id):
        row = store.db.execute("SELECT data FROM runtime_sessions").fetchone()
        events.append(("ack", delivery_id, json.loads(row[0]) if row else None))

    runtime = ResponsesRuntime(
        store=store, client=client, update_source=source, update_ack=acknowledge
    )
    result = await runtime.start("objective", ModelConfig(model="exact-model"), RuntimeLimits())
    creates = [payload for url, payload in requests if not url.endswith("/input_tokens")]
    assert len(creates) == 1
    delivered = json.loads(creates[0]["input"][1]["content"])
    assert delivered["delivery_id"] == "d-1"
    assert delivered["authority"] == "unverified peer data"
    assert (await runtime.checkpoint(result.session.id)).native_state["network_delivery_ids"] == [
        "d-1"
    ]
    assert events[0] == "read"
    assert events[1][0:2] == ("ack", "d-1")
    assert events[1][2]["native_state"]["network_delivery_ids"] == ["d-1"]
    await client.close()
    store.close()


async def test_boundary_hook_can_complete_after_settled_response_without_successor(tmp_path):
    store = SQLiteRuntimeStore(tmp_path / "stop.db")
    requests = []
    client = client_for([response([message("Progress retained")])], requests)

    async def boundary(checkpoint):
        assert checkpoint.native_state["settled_boundary"] is True
        assert checkpoint.native_state.get("pending_operation") is None
        return {"complete_reason": "target_verified"}

    runtime = ResponsesRuntime(store=store, client=client, boundary_hook=boundary)
    result = await runtime.start("target", ModelConfig(model="exact-model"), RuntimeLimits())
    assert result.session.status == "completed"
    assert result.completion_reason == "target_verified"
    assert result.continuation is None
    assert result.output_text == "Progress retained"
    await client.close()
    store.close()


async def test_verified_guard_stops_before_generation_is_marked_pending(tmp_path):
    store = SQLiteRuntimeStore(tmp_path / "guard.db")
    requests = []
    client = client_for([], requests)

    async def verified():
        return True

    runtime = ResponsesRuntime(store=store, client=client, pre_generation_guard=verified)
    result = await runtime.start("target", ModelConfig(model="exact-model"), RuntimeLimits())
    checkpoint = await runtime.checkpoint(result.session.id)
    assert result.completion_reason == "target_verified"
    assert checkpoint.native_state.get("pending_operation") is None
    assert requests == []
    await client.close()
    store.close()


async def test_registered_discussion_tools_page_and_retrieve_exact_source(lab):
    service, _, experiment, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        experiment["id"], DiscussionCreate(title="Ideas", summary="Open"), alpha, "topic"
    )
    post = service.post_discussion(
        topic["id"],
        DiscussionPostCreate(kind="finding", content="Exact long source"),
        alpha,
        "post",
    )
    dispatcher = research_tools(service, beta, beta.branch_id)
    page = await dispatcher.dispatch(
        "discussion_posts", {"topic_id": topic["id"], "after": None, "limit": 1}, "read-1"
    )
    assert page["items"][0]["id"] == post["id"]
    exact = await dispatcher.dispatch("read_discussion_post", {"post_id": post["id"]}, "read-2")
    assert exact["content"] == "Exact long source"


async def test_real_unified_inbox_reaches_next_provider_request_with_retrieval_ids(lab, tmp_path):
    service, _, experiment, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        experiment["id"], DiscussionCreate(title="Shared", summary="Discuss"), alpha, "topic"
    )
    service.subscribe_discussion(topic["id"], True, beta, "subscribe")
    post = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="finding", content="P" * 2000), alpha, "post"
    )
    note = service.send_message(alpha.branch_id, beta.branch_id, "Addressed hint", [], alpha, "msg")
    requests = []
    client = client_for([response([message("considered")])], requests)
    store = SQLiteRuntimeStore(tmp_path / "real-delivery.db")

    async def source(checkpoint):
        return service.discussion_updates(experiment["id"], beta, limit=10)

    async def acknowledge(delivery_id):
        service.acknowledge_discussion_updates(experiment["id"], delivery_id, beta, "ack-1")

    runtime = ResponsesRuntime(
        store=store, client=client, update_source=source, update_ack=acknowledge
    )
    result = await runtime.start("Inspect ideas", ModelConfig(model="exact-model"), RuntimeLimits())
    assert result.output_text == "considered"
    provider_request = next(
        payload for url, payload in requests if not url.endswith("/input_tokens")
    )
    delivery = json.loads(provider_request["input"][1]["content"])
    kinds = {item["source_kind"] for item in delivery["items"]}
    assert kinds == {"discussion_post", "message"}
    assert {item["retrieval_id"] for item in delivery["items"]} == {post["id"], note["id"]}
    assert service.read_discussion_post(post["id"], beta)["content"] == "P" * 2000
    assert service.read_research_message(note["id"], beta)["content"] == "Addressed hint"
    assert service.discussion_updates(experiment["id"], beta)["items"] == []
    await client.close()
    store.close()


async def test_escaped_peer_message_does_not_stop_recipient_before_generation(lab, tmp_path):
    service, _, experiment, _, (alpha, beta) = approaches(lab, "ideas")
    escaped = service.send_message(alpha.branch_id, beta.branch_id, "\\" * 1024, [], alpha, "m")
    requests = []
    client = client_for([response([message("considered")])], requests)
    store = SQLiteRuntimeStore(tmp_path / "escaped-delivery.db")

    async def source(checkpoint):
        return service.discussion_updates(experiment["id"], beta, limit=10)

    async def acknowledge(delivery_id):
        service.acknowledge_discussion_updates(experiment["id"], delivery_id, beta, "ack-1")

    runtime = ResponsesRuntime(
        store=store, client=client, update_source=source, update_ack=acknowledge
    )
    result = await runtime.start("Inspect ideas", ModelConfig(model="exact-model"), RuntimeLimits())
    assert result.output_text == "considered"
    provider_request = next(
        payload for url, payload in requests if not url.endswith("/input_tokens")
    )
    [item] = json.loads(provider_request["input"][1]["content"])["items"]
    assert item["retrieval_id"] == escaped["id"]
    assert item["truncated"] is True
    assert service.discussion_updates(experiment["id"], beta)["items"] == []
    await client.close()
    store.close()


def test_empty_peer_poll_and_membership_are_not_scientific_progress():
    state = {}
    assert observe(state, "discussion_updates", {"after": None}, {"items": []}) is None
    assert state.get("read_counts", {}) == {}
    assert observe(state, "join_research_team", {"team": "A"}, {"joined": True}) is None
    assert state.get("progress_epoch", 0) == 0


async def test_recruited_synthesis_prompt_and_compaction_anchor_show_sampled_source_ids(lab):
    from physharness.execution import RuntimeCheckpoint, RuntimeResult, RuntimeSession
    from physharness.orchestration.research_worker import ResearchTaskExecutor

    service, _, experiment, _, (alpha, _) = approaches(lab, "ideas")
    operator = Principal(id="operator", project_id=alpha.project_id, role="operator")
    topic = service.create_discussion(
        experiment["id"], DiscussionCreate(title="Source", summary="S"), alpha, "topic"
    )
    post = service.post_discussion(
        topic["id"], DiscussionPostCreate(kind="objection", content="Check premise"), alpha, "post"
    )
    recruit = service.recruit_researcher(
        experiment["id"],
        RecruitResearcherRequest(
            parent_branch_id=alpha.branch_id,
            title="Synthesis",
            objective="Compare source objections",
            synthesis=True,
            discussion_refs=[post["id"]],
        ),
        operator,
        "recruit",
    )

    class CaptureRuntime:
        def __init__(self, store, dispatcher, event_sink, context_anchor, **kwargs):
            self.store = store
            self.context_anchor = context_anchor

        async def start(self, prompt, model, limits):
            initial = json.loads(prompt)
            compacted = json.loads(await self.context_anchor())
            assert initial["assigned_source_post_ids"] == [post["id"]]
            assert compacted["assigned_source_post_ids"] == [post["id"]]
            assert initial["synthesis_scope"] == compacted["synthesis_scope"]
            session = RuntimeSession(runtime="responses", model=model, limits=limits)
            await self.store.save(RuntimeCheckpoint.build(session, {"observed": True}))
            return RuntimeResult(session=session, output_text="Unverified comparison")

    executor = ResearchTaskExecutor(
        service,
        prices={
            "explicit-test-model": {"input_usd_per_million": "1", "output_usd_per_million": "1"}
        },
        runtime_factory=CaptureRuntime,
    )
    result = await executor.execute(recruit["task"]["id"], operator.project_id)
    assert result["status"] == "completed"


def test_ready_dispatch_rotates_root_lineages_without_starving_later_branches():
    tasks = [
        {"id": "a1", "branch_id": "a"},
        {"id": "a2", "branch_id": "a-child"},
        {"id": "a3", "branch_id": "a"},
        {"id": "b1", "branch_id": "b"},
    ]
    parents = {"a": None, "a-child": "a", "b": None}
    assert [task["id"] for task in fair_ready_order(tasks, parents)] == ["a1", "b1", "a2", "a3"]
    assert [task["id"] for task in fair_ready_order(tasks, parents, last_lineage="a")] == [
        "b1",
        "a1",
        "a2",
        "a3",
    ]


def test_ready_dispatch_uses_creation_age_inside_each_lineage_not_pagination_order():
    tasks = [
        {"id": "0-new", "branch_id": "a", "created_at": "2026-09-24T00:03:00Z"},
        {"id": "b-old", "branch_id": "b", "created_at": "2026-09-24T00:02:00Z"},
        {"id": "z-old", "branch_id": "a", "created_at": "2026-09-24T00:01:00Z"},
    ]
    assert [task["id"] for task in fair_ready_order(tasks, {"a": None, "b": None})] == [
        "z-old",
        "b-old",
        "0-new",
    ]


def test_ready_dispatch_rotates_only_ready_tasks_not_settled_history():
    def task(identifier, branch, status, second, **extra):
        return {
            "id": identifier,
            "branch_id": branch,
            "status": status,
            "created_at": f"2026-09-24T00:{second // 60:02d}:{second % 60:02d}Z",
            **extra,
        }

    tasks = [
        *[task(f"a-done-{n}", "a", "completed", n) for n in range(10)],
        task("a-queued", "a", "queued", 60),
        task("a-after", "a", "queued", 30, dependency_ids=["b-queued-0"]),
        task("b-done", "b", "failed", 90),
        *[task(f"b-queued-{n}", "b", "queued", 120 + n) for n in range(3)],
    ]
    settled = [f"a-done-{n}" for n in range(10)] + ["b-done"]
    order = [item["id"] for item in fair_ready_order(tasks, {"a": None, "b": None})]
    assert order == [
        *settled,
        "a-queued",
        "b-queued-0",
        "b-queued-1",
        "b-queued-2",
        "a-after",
    ]
    rotated = fair_ready_order(tasks, {"a": None, "b": None}, last_lineage="a")
    assert [item["id"] for item in rotated][len(settled) : len(settled) + 2] == [
        "b-queued-0",
        "a-queued",
    ]


def test_ready_dispatch_keeps_rotation_after_a_root_with_no_ready_task():
    tasks = [
        {"id": "a1", "branch_id": "a", "status": "queued"},
        {"id": "b-done", "branch_id": "b", "status": "completed"},
        {"id": "c1", "branch_id": "c", "status": "queued"},
    ]
    parents = {"a": None, "b": None, "c": None}
    order = fair_ready_order(tasks, parents, last_lineage="b")
    assert [task["id"] for task in order] == ["b-done", "c1", "a1"]


def test_ready_dispatch_breaks_equal_creation_times_by_task_id():
    tasks = [
        {"id": "z", "branch_id": "a", "status": "queued", "created_at": "2026-09-24T00:00:00Z"},
        {"id": "m", "branch_id": "a", "status": "queued", "created_at": "2026-09-24T00:00:00Z"},
    ]
    assert [task["id"] for task in fair_ready_order(tasks, {"a": None})] == ["m", "z"]


def test_peer_wait_is_scoped_to_exact_sender_and_has_finite_timeout(lab):
    service, author, experiment, _, (alpha, beta) = approaches(lab, "ideas")
    controller = Principal(id="controller", project_id=author.project_id, role="operator")
    task = service.create_task(
        TaskCreate(branch_id=alpha.branch_id, objective="Wait"), alpha, "task"
    )
    lease = service.acquire_task(task["id"], "holder", 60, controller, "lease")
    with worker_effects(alpha, task["id"], "holder", lease["fence"]):
        wait = service.request_peer_wait(task["id"], beta.branch_id, 60, alpha, "peer-wait")
    assert wait["intent"]["peer_wait"]["recipient_branch_id"] == beta.branch_id
    assert service.peer_wait_status(wait["intent"]["peer_wait"], alpha)["ready"] is False
    service.send_message(beta.branch_id, alpha.branch_id, "Result", [], beta, "result")
    woken = service.peer_wait_status(wait["intent"]["peer_wait"], alpha)
    assert woken["reason"] == "message_received"
    with pytest.raises(HarnessError) as forbidden:
        service.peer_wait_status(wait["intent"]["peer_wait"], beta)
    assert forbidden.value.code == "BRANCH_AUTHORITY"


def test_sender_sees_honest_delivery_state_without_recipient_mailbox(lab):
    service, _, experiment, _, (alpha, beta) = approaches(lab, "ideas")
    # A recipient with no unfinished work is reported as recipient_unavailable instead.
    service.create_task(TaskCreate(branch_id=beta.branch_id, objective="B"), beta, "beta-task")
    sent = service.send_message(alpha.branch_id, beta.branch_id, "Private note", [], alpha, "send")
    before = service.message_delivery_status(sent["id"], alpha)
    assert before["state"] == "queued"
    assert "content" not in before
    service.discussion_updates(experiment["id"], beta)
    pending = service.message_delivery_status(sent["id"], alpha)
    assert pending["state"] == "presented_unacknowledged"
    delivery = service.discussion_updates(experiment["id"], beta)
    service.acknowledge_discussion_updates(experiment["id"], delivery["delivery_id"], beta, "ack")
    assert service.message_delivery_status(sent["id"], alpha)["state"] == "acknowledged"
    with pytest.raises(HarnessError):
        service.message_delivery_status(sent["id"], beta)


def test_withdrawn_message_is_never_reported_as_acknowledged(lab):
    service, _, experiment, _, (alpha, beta) = approaches(lab, "ideas")
    sent = service.send_message(alpha.branch_id, beta.branch_id, "Retracted", [], alpha, "send")
    first = service.discussion_updates(experiment["id"], beta)
    assert service.message_delivery_status(sent["id"], alpha)["state"] == "presented_unacknowledged"
    with service.db.transaction() as session:
        row = session.get(RecordRow, experiment["id"])
        service._replace(session, row, {"sharing": "none"})
    redelivery = service.discussion_updates(experiment["id"], beta)
    assert redelivery["delivery_id"] == first["delivery_id"]
    assert redelivery["items"][0]["source_kind"] == "withdrawal"
    service.acknowledge_discussion_updates(experiment["id"], first["delivery_id"], beta, "ack")
    assert service.message_delivery_status(sent["id"], alpha)["state"] == "withdrawn_unavailable"


def test_component_registry_shows_overlap_and_terminal_owner_without_proof_promotion(lab):
    service, author, experiment, _, (alpha, beta) = approaches(lab, "ideas")
    alpha_task = service.create_task(
        TaskCreate(branch_id=alpha.branch_id, objective="A"), alpha, "a"
    )
    beta_task = service.create_task(TaskCreate(branch_id=beta.branch_id, objective="B"), beta, "b")
    first = service.register_component(
        experiment["id"], "scalar-decay", "x ≤ y", alpha_task["id"], [], alpha, "claim-a"
    )
    updated = service.register_component(
        experiment["id"],
        "scalar-decay",
        "x ≤ y with local check",
        alpha_task["id"],
        [],
        alpha,
        "claim-a-update",
        expected_revision=first["revision"],
    )
    assert updated["id"] == first["id"] and updated["revision"] == first["revision"] + 1
    service.register_component(
        experiment["id"], "scalar-decay", "x ≤ y", beta_task["id"], [], beta, "claim-b"
    )
    entries = service.component_directory(experiment["id"], alpha)["items"]
    assert len(entries) == 2
    assert all(item["proof_status"] == "unverified" for item in entries)
    assert all(item["owner_status"] == "queued" for item in entries)
    with service.db.sessions() as session:
        row = session.get(RecordRow, alpha_task["id"])
        service._replace(session, row, {"status": "blocked"})
        session.commit()
    after = service.component_directory(experiment["id"], beta)["items"]
    assert next(item for item in after if item["id"] == first["id"])["owner_status"] == "stale"


def test_component_directory_pages_past_200_and_private_rows_do_not_block(lab):
    service, _, experiment, _, (alpha, beta) = approaches(lab, "none")
    with service.db.transaction() as session:
        for owner, count in ((beta, 205), (alpha, 2)):
            for index in range(count):
                service._insert(
                    session,
                    "component_registry",
                    owner,
                    {
                        "experiment_id": experiment["id"],
                        "branch_id": owner.branch_id,
                        "component_key": f"piece-{index}",
                        "statement": "S",
                        "owner_task_id": "missing",
                        "artifact_ids": [],
                        "proof_status": "unverified",
                    },
                )
    private = service.component_directory(experiment["id"], alpha, limit=10)
    assert len(private["items"]) == 2 and private["next_cursor"] is None
    with service.db.transaction() as session:
        row = session.get(RecordRow, experiment["id"])
        service._replace(session, row, {"sharing": "ideas"})
    seen, cursor = set(), None
    while True:
        page = service.component_directory(experiment["id"], alpha, after=cursor, limit=17)
        seen.update(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 207


def test_old_or_unrelated_verified_receipt_cannot_stop_current_target(lab):
    service, author, experiment, _, _ = approaches(lab, "ideas")
    assert service.verified_target_receipt(experiment["id"], author) is None
    with service.db.transaction() as session:
        service._insert(
            session,
            "verification",
            author,
            {
                "experiment_id": experiment["id"],
                "status": "verified",
                "assurance": "independent_kernel",
                "target_digest": "old-target",
                "problem_revision_id": experiment["problem_id"],
            },
        )
    assert service.verified_target_receipt(experiment["id"], author) is None


async def test_ack_failure_does_not_repeat_durable_context(tmp_path):
    requests = []
    store = SQLiteRuntimeStore(tmp_path / "network.db")
    client = client_for([response([message("done")])], requests)
    attempts = 0

    async def source(checkpoint):
        return {"delivery_id": "d-1", "items": [{"post_id": "p-1", "excerpt": "idea"}]}

    async def acknowledge(delivery_id):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("ack unavailable")

    runtime = ResponsesRuntime(
        store=store, client=client, update_source=source, update_ack=acknowledge
    )
    with pytest.raises(ExecutionError) as failure:
        await runtime.start("objective", ModelConfig(model="exact-model"), RuntimeLimits())
    assert failure.value.code == "PROVIDER_FAILED"
    assert not requests
    # The first session is persisted before acknowledgement, so it can resume.
    session_id = store.db.execute("SELECT id FROM runtime_sessions").fetchone()[0]
    checkpoint = await store.load(session_id)
    assert checkpoint.native_state["network_delivery_ids"] == ["d-1"]
    await runtime.resume(checkpoint)
    result = await runtime.continue_session(session_id, "continue")
    assert result.output_text == "done"
    creates = [payload for url, payload in requests if not url.endswith("/input_tokens")]
    assert sum("d-1" in json.dumps(item) for item in creates[0]["input"]) == 1
    assert attempts == 2
    await client.close()
    store.close()


async def test_changed_withdrawal_for_same_delivery_is_persisted_before_ack(tmp_path):
    requests = []
    store = SQLiteRuntimeStore(tmp_path / "withdrawal.db")
    client = client_for([response([message("done")])], requests)
    phase = "original"
    ack_snapshots = []

    async def source(checkpoint):
        if phase == "original":
            items = [{"source_kind": "discussion_post", "retrieval_id": "p-1", "excerpt": "old"}]
        else:
            items = [{"source_kind": "withdrawal", "notice": "Source withdrawn"}]
        return {"delivery_id": "d-1", "items": items}

    async def acknowledge(delivery_id):
        row = store.db.execute("SELECT data FROM runtime_sessions").fetchone()
        ack_snapshots.append(json.loads(row[0]))
        if len(ack_snapshots) == 1:
            raise RuntimeError("ack interrupted")

    runtime = ResponsesRuntime(
        store=store, client=client, update_source=source, update_ack=acknowledge
    )
    with pytest.raises(ExecutionError):
        await runtime.start("objective", ModelConfig(model="exact-model"), RuntimeLimits())
    phase = "withdrawal"
    session_id = store.db.execute("SELECT id FROM runtime_sessions").fetchone()[0]
    await runtime.resume(await store.load(session_id))
    await runtime.continue_session(session_id, "continue")
    visible = [
        json.loads(item["content"])
        for item in ack_snapshots[-1]["native_state"]["input"]
        if item.get("role") == "user" and "research_network_updates" in item["content"]
    ]
    assert [item["items"][0]["source_kind"] for item in visible] == [
        "discussion_post",
        "withdrawal",
    ]
    assert ack_snapshots[-1]["native_state"]["network_delivery_ids"] == ["d-1"]
    await client.close()
    store.close()


async def test_ack_race_rereads_changed_delivery_once_before_provider_request(tmp_path):
    requests = []
    store = SQLiteRuntimeStore(tmp_path / "ack-race.db")
    client = client_for([response([message("done")])], requests)
    changed = False
    ack_attempts = 0

    async def source(checkpoint):
        items = (
            [{"source_kind": "withdrawal", "notice": "Source withdrawn"}]
            if changed
            else [{"source_kind": "message", "retrieval_id": "m-1", "excerpt": "hint"}]
        )
        return {"delivery_id": "d-1", "items": items}

    async def acknowledge(delivery_id):
        nonlocal changed, ack_attempts
        ack_attempts += 1
        if ack_attempts == 1:
            changed = True
            raise HarnessError("DELIVERY_CHANGED", "Delivery was sanitized", status=409)
        row = store.db.execute("SELECT data FROM runtime_sessions").fetchone()
        saved = json.loads(row[0])["native_state"]["input"]
        assert any("withdrawal" in item.get("content", "") for item in saved)

    runtime = ResponsesRuntime(
        store=store, client=client, update_source=source, update_ack=acknowledge
    )
    await runtime.start("objective", ModelConfig(model="exact-model"), RuntimeLimits())
    provider_request = next(
        payload for url, payload in requests if not url.endswith("/input_tokens")
    )
    assert ack_attempts == 2
    assert any("withdrawal" in item.get("content", "") for item in provider_request["input"])
    await client.close()
    store.close()


async def test_invalid_network_tool_arguments_are_recoverable_model_visible_rejections(lab):
    service, _, experiment, _, (alpha, beta) = approaches(lab, "ideas")
    topic = service.create_discussion(
        experiment["id"], DiscussionCreate(title="Bounds", summary="Open"), alpha, "topic"
    )
    dispatcher = research_tools(service, beta, beta.branch_id)
    post = {
        "topic_id": topic["id"],
        "kind": "finding",
        "reply_to_post_id": None,
        "artifact_ids": [],
        "reference_post_ids": [],
    }
    recruit = {
        "parent_branch_id": beta.branch_id,
        "title": "Helper",
        "objective": "Explore",
        "relation": "helper",
        "model_index": None,
        "discussion_refs": [],
        "synthesis": False,
        "detached": True,
        "public_summary": None,
    }
    cases = [
        ("post_discussion", {**post, "content": "x" * 12001}),
        ("post_discussion", {**post, "content": "   "}),
        ("create_discussion", {"title": "t" * 201, "summary": "s", "branch_id": None}),
        ("recruit_researcher", {**recruit, "title": " "}),
        (
            "publish_research_profile",
            {
                "branch_id": beta.branch_id,
                "published": True,
                "summary": " ",
                "interests": [],
                "assignment": "",
            },
        ),
        ("join_research_team", {"branch_id": beta.branch_id, "team": "x" * 101, "joined": True}),
        (
            "request_research_capacity",
            {"branch_id": beta.branch_id, "requested_workers": 1001, "rationale": "r"},
        ),
    ]
    for index, (name, args) in enumerate(cases):
        result = await dispatcher.dispatch(name, args, f"invalid-{index}")
        assert result["error"]["code"] == "VALIDATION_ERROR", name
        assert result["error"]["details"]["fields"], name
        assert "x" * 100 not in json.dumps(result)
    accepted = await dispatcher.dispatch(
        "post_discussion", {**post, "content": "Valid after rejection"}, "valid"
    )
    assert accepted["content"] == "Valid after rejection"
