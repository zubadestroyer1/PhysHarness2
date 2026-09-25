"""Coordination gaps: peer waits, delivery availability, strategies. MOCK provider only."""

import json
from datetime import timedelta

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError
from test_core import setup_experiment
from test_execution_responses import message
from test_research_loop_integration import PRICES, response, tool_call

from physharness import continuation
from physharness.domain import BranchCreate, ExperimentCreate, Principal, TaskCreate, utcnow
from physharness.errors import HarnessError
from physharness.execution import ResponsesRuntime, RuntimeLimits
from physharness.orchestration import research_worker
from physharness.storage import RecordRow
from physharness.worker_authority import worker_effects


def ideas_lab(lab, concurrency=1):
    service, author, _ = lab
    original, _ = setup_experiment(lab, concurrency=concurrency)
    request = ExperimentCreate.model_validate(
        {k: original[k] for k in ("campaign_id", "problem_id", "models", "budget")}
    ).model_copy(update={"sharing": "ideas"})
    experiment = service.create_experiment(request, author, "ideas-experiment")
    service.transition_experiment(experiment["id"], "start", 1, author, "ideas-start")
    branches = [
        service.create_branch(
            experiment["id"], BranchCreate(title=name, objective=name), author, name
        )
        for name in ("alpha", "beta")
    ]
    agents = [
        Principal(
            id=name,
            role="agent",
            project_id=author.project_id,
            experiment_id=experiment["id"],
            branch_id=branch["id"],
        )
        for name, branch in zip(("worker-a", "worker-b"), branches, strict=True)
    ]
    controller = Principal(id="controller", project_id=author.project_id, role="operator")
    return service, author, controller, experiment, agents


def set_payload(service, record_id, changes):
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, record_id), changes)


def waiting(service, controller, alpha, beta, timeout=60):
    task = service.create_task(TaskCreate(branch_id=alpha.branch_id, objective="Wait"), alpha, "t")
    lease = service.acquire_task(task["id"], "holder", 60, controller, "lease")
    with worker_effects(alpha, task["id"], "holder", lease["fence"]):
        wait = service.request_peer_wait(task["id"], beta.branch_id, timeout, alpha, "wait")
    return task, wait["intent"]["peer_wait"]


def mock_client(route):
    async def wrapped(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        return await route(request, json.loads(request.content))

    return AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(wrapped)),
    )


def executor_for(service, client):
    return research_worker.ResearchTaskExecutor(
        service,
        prices=PRICES,
        limits=RuntimeLimits(max_turns=30),
        runtime_factory=lambda **kw: ResponsesRuntime(client=client, **kw),
    )


def objective_of(payload):
    for item in reversed(payload["input"]):
        if item.get("role") == "user" and isinstance(item.get("content"), str):
            try:
                prompt = json.loads(item["content"])
            except ValueError:
                continue
            if isinstance(prompt, dict) and "objective" in prompt:
                return prompt["objective"]
    raise AssertionError("No task prompt")


# Task 1: peer wait robustness


def test_peer_wait_scope_withdrawn_when_sharing_flips(lab):
    service, _, controller, experiment, (alpha, beta) = ideas_lab(lab)
    _, ticket = waiting(service, controller, alpha, beta)
    set_payload(service, experiment["id"], {"sharing": "none"})
    assert service.peer_wait_status(ticket, alpha) == {
        "ready": True,
        "reason": "scope_withdrawn",
        "message_id": None,
    }
    with pytest.raises(HarnessError) as forbidden:
        service.peer_wait_status(ticket, beta)
    assert forbidden.value.code == "BRANCH_AUTHORITY"


def test_peer_wait_scope_withdrawn_when_recipient_branch_leaves(lab):
    service, _, controller, _, (alpha, beta) = ideas_lab(lab)
    _, ticket = waiting(service, controller, alpha, beta)
    set_payload(service, beta.branch_id, {"experiment_id": "elsewhere"})
    assert service.peer_wait_status(ticket, alpha)["reason"] == "scope_withdrawn"


def test_peer_wait_timeout_wake(lab, monkeypatch):
    service, _, controller, _, (alpha, beta) = ideas_lab(lab)
    _, ticket = waiting(service, controller, alpha, beta, timeout=5)
    assert service.peer_wait_status(ticket, alpha)["ready"] is False
    later = utcnow() + timedelta(seconds=6)
    monkeypatch.setattr(continuation, "utcnow", lambda: later)
    assert service.peer_wait_status(ticket, alpha) == {
        "ready": True,
        "reason": "timeout",
        "message_id": None,
    }


def test_peer_wait_cancelled_wake(lab):
    service, author, controller, experiment, (alpha, beta) = ideas_lab(lab)
    task, ticket = waiting(service, controller, alpha, beta)
    assert ticket["task_id"] == task["id"]
    set_payload(service, task["id"], {"status": "blocked"})
    assert service.peer_wait_status(ticket, alpha)["reason"] == "cancelled"
    set_payload(service, task["id"], {"status": "running"})
    service.transition_experiment(experiment["id"], "cancel", 2, author, "cancel")
    assert service.peer_wait_status(ticket, alpha)["reason"] == "cancelled"


async def test_supervisor_resumes_waiter_when_sharing_withdrawn(lab, monkeypatch):
    service, author, _, experiment, (alpha, beta) = ideas_lab(lab)
    task = service.create_task(TaskCreate(branch_id=alpha.branch_id, objective="A"), author, "a")
    original = service.request_peer_wait

    def wait_then_withdraw(*args, **kwargs):
        result = original(*args, **kwargs)
        set_payload(service, experiment["id"], {"sharing": "none"})
        return result

    monkeypatch.setattr(service, "request_peer_wait", wait_then_withdraw)
    calls = 0

    async def route(request, payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            item = tool_call(
                "wait_for_peer",
                {"recipient_branch_id": beta.branch_id, "timeout_seconds": 600},
                "wait",
            )
            return httpx.Response(200, json=response([item], response_id="wait"))
        return httpx.Response(200, json=response([message("Resumed alone")], response_id="done"))

    client = mock_client(route)
    report = await research_worker.ResearchTeamRunner(
        service, executor=executor_for(service, client)
    ).run(
        research_worker.TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=author.project_id,
            mode="replay",
            task_ids=[task["id"]],
            max_concurrency=1,
            timeout_seconds=15,
        )
    )
    assert calls == 2
    assert report["status"] == "completed", report
    assert service.get_record("task", task["id"], author)["status"] == "completed"
    await client.close()


async def test_waiting_peer_releases_capacity_and_resumes_on_reply(lab):
    service, author, _, experiment, agents = ideas_lab(lab)
    # Root lineages dispatch in branch-ID order; the waiter must be dispatched first.
    alpha, beta = sorted(agents, key=lambda agent: agent.branch_id)
    task_a = service.create_task(TaskCreate(branch_id=alpha.branch_id, objective="A"), author, "a")
    task_b = service.create_task(TaskCreate(branch_id=beta.branch_id, objective="B"), author, "b")
    order = []

    async def route(request, payload):
        objective = objective_of(payload)
        order.append(objective)
        count = order.count(objective)
        if objective == "A" and count == 1:
            item = tool_call(
                "wait_for_peer",
                {"recipient_branch_id": beta.branch_id, "timeout_seconds": 600},
                "wait",
            )
        elif objective == "B" and count == 1:
            item = tool_call(
                "send_message",
                {
                    "recipient_id": alpha.branch_id,
                    "content": "Try the trace lemma",
                    "artifact_ids": [],
                },
                "reply",
            )
        else:
            item = message(f"{objective} done")
        return httpx.Response(200, json=response([item], response_id=f"{objective}-{count}"))

    client = mock_client(route)
    report = await research_worker.ResearchTeamRunner(
        service, executor=executor_for(service, client)
    ).run(
        research_worker.TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=author.project_id,
            mode="replay",
            task_ids=[task_a["id"], task_b["id"]],
            max_concurrency=1,
            timeout_seconds=15,
        )
    )
    assert order == ["A", "B", "B", "A"], order
    assert report["status"] == "completed", report
    assert service.get_record("task", task_a["id"], author)["continuation_count"] == 1
    assert service.get_record("task", task_b["id"], author)["status"] == "completed"
    await client.close()


# Task 2: failed delivery and peer availability


def test_message_to_branch_with_only_blocked_tasks_is_recipient_unavailable(lab):
    service, author, _, _, (alpha, beta) = ideas_lab(lab)
    idle = service.send_message(alpha.branch_id, beta.branch_id, "Idle", [], alpha, "idle")
    assert service.message_delivery_status(idle["id"], alpha)["state"] == "recipient_unavailable"
    task = service.create_task(TaskCreate(branch_id=beta.branch_id, objective="B"), author, "b")
    sent = service.send_message(alpha.branch_id, beta.branch_id, "Hint", [], alpha, "send")
    assert service.message_delivery_status(sent["id"], alpha)["state"] == "queued"
    set_payload(service, task["id"], {"status": "blocked"})
    status = service.message_delivery_status(sent["id"], alpha)
    assert status["state"] == "recipient_unavailable"
    assert "content" not in status


def test_presented_message_is_not_recipient_unavailable(lab):
    service, author, _, experiment, (alpha, beta) = ideas_lab(lab)
    task = service.create_task(TaskCreate(branch_id=beta.branch_id, objective="B"), author, "b")
    sent = service.send_message(alpha.branch_id, beta.branch_id, "Hint", [], alpha, "send")
    delivery = service.discussion_updates(experiment["id"], beta)
    service.acknowledge_discussion_updates(experiment["id"], delivery["delivery_id"], beta, "ack")
    set_payload(service, task["id"], {"status": "failed"})
    assert service.message_delivery_status(sent["id"], alpha)["state"] == "acknowledged"


def test_peer_availability_reports_states_and_hides_invisible_branches(lab):
    service, author, controller, experiment, (alpha, beta) = ideas_lab(lab)
    gamma = service.create_branch(
        experiment["id"], BranchCreate(title="gamma", objective="gamma"), author, "gamma"
    )
    service.create_task(TaskCreate(branch_id=beta.branch_id, objective="B"), author, "b")
    running = service.create_task(TaskCreate(branch_id=gamma["id"], objective="G"), author, "g")
    service.acquire_task(running["id"], "holder", 60, controller, "lease-g")
    set_payload(service, running["id"], {"status": "running"})
    states = {
        item["branch_id"]: item["state"]
        for item in service.peer_availability(experiment["id"], alpha)["items"]
    }
    assert states == {beta.branch_id: "queued", gamma["id"]: "active"}
    set_payload(service, experiment["id"], {"sharing": "none"})
    assert service.peer_availability(experiment["id"], alpha)["items"] == []
    with pytest.raises(HarnessError):
        service.peer_availability(experiment["id"], alpha, limit=0)


def test_peer_availability_waiting_terminal_and_paging(lab):
    service, author, controller, experiment, (alpha, beta) = ideas_lab(lab)
    _, _ = waiting(service, controller, beta, alpha)
    waiter = service.list_records("task", author, experiment["id"])[0]
    set_payload(
        service,
        waiter["id"],
        {
            "status": "queued",
            "ready_continuation": {"peer_wait": {"branch_id": beta.branch_id}},
        },
    )
    items = service.peer_availability(experiment["id"], alpha)["items"]
    assert items == [{"branch_id": beta.branch_id, "state": "waiting"}]
    set_payload(service, waiter["id"], {"status": "completed", "ready_continuation": None})
    extra = [
        service.create_branch(
            experiment["id"], BranchCreate(title=f"p{i}", objective="p"), author, f"p{i}"
        )["id"]
        for i in range(3)
    ]
    seen, cursor = {}, None
    while True:
        page = service.peer_availability(experiment["id"], alpha, after=cursor, limit=2)
        seen.update((item["branch_id"], item["state"]) for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert set(seen) == {beta.branch_id, *extra}
    assert set(seen.values()) == {"terminal"}


async def test_peer_availability_tool_registered_only_for_ideas(lab):
    service, _, _, experiment, (alpha, _) = ideas_lab(lab)
    dispatcher = research_worker.research_tools(service, alpha, alpha.branch_id)
    assert "peer_availability" in {tool["name"] for tool in dispatcher.definitions}
    page = await dispatcher.dispatch("peer_availability", {"after": None, "limit": 5}, "avail")
    assert [item["state"] for item in page["items"]] == ["terminal"]
    set_payload(service, experiment["id"], {"sharing": "none"})
    dispatcher = research_worker.research_tools(service, alpha, alpha.branch_id)
    assert "peer_availability" not in {tool["name"] for tool in dispatcher.definitions}


# Task 3: optional strategy descriptions


def test_strategy_is_optional_bounded_and_listed(lab):
    service, author, controller, experiment, (alpha, beta) = ideas_lab(lab)
    plain = service.create_task(TaskCreate(branch_id=alpha.branch_id, objective="P"), author, "p")
    assert "strategy" not in plain
    with pytest.raises(ValidationError):
        TaskCreate(branch_id=alpha.branch_id, objective="X", strategy="s" * 501)
    parent = service.create_task(TaskCreate(branch_id=alpha.branch_id, objective="R"), author, "r")
    lease = service.acquire_task(parent["id"], "holder", 60, controller, "lease")
    with worker_effects(alpha, parent["id"], "holder", lease["fence"]):
        child = service.create_task(
            TaskCreate(branch_id=alpha.branch_id, objective="Sub", strategy="Induct on n"),
            alpha,
            "child",
        )
        listed = service.delegated_task_statuses(parent["id"], [child["id"]], alpha)
        joined = service.joined_task_statuses(parent["id"], alpha)
    assert child["strategy"] == "Induct on n"
    assert listed["children"][0]["strategy"] == "Induct on n"
    assert joined["children"][0]["strategy"] == "Induct on n"
    service.register_component(
        experiment["id"], "lemma", "x ≤ y", child["id"], [], alpha, "component"
    )
    item = service.component_directory(experiment["id"], beta)["items"][0]
    assert item["owner_strategy"] == "Induct on n"


async def test_delegate_tool_carries_strategy_into_helper_prompt(lab):
    service, author, _, experiment, (alpha, _) = ideas_lab(lab)
    root = service.create_task(TaskCreate(branch_id=alpha.branch_id, objective="Root"), author, "r")
    seen = {}

    async def route(request, payload):
        prompt = next(
            json.loads(item["content"]) for item in payload["input"] if item.get("role") == "user"
        )
        seen.setdefault(prompt["objective"], []).append(prompt)
        outputs = [
            json.loads(item["output"])
            for item in payload["input"]
            if item.get("type") == "function_call_output"
        ]
        if prompt["objective"] == "Root" and not outputs:
            item = tool_call(
                "delegate_detached",
                {
                    "branch_id": alpha.branch_id,
                    "objective": "Helper",
                    "dependency_ids": [],
                    "strategy": "Bound the trace via Cauchy-Schwarz",
                },
                "delegate",
            )
        elif prompt["objective"] == "Root" and len(outputs) == 1:
            assert outputs[0]["strategy"] == "Bound the trace via Cauchy-Schwarz"
            item = tool_call(
                "delegate_detached",
                {
                    "branch_id": alpha.branch_id,
                    "objective": "Too long",
                    "dependency_ids": [],
                    "strategy": "s" * 501,
                },
                "oversize",
            )
        elif prompt["objective"] == "Root":
            item = message("Root done")
        else:
            item = message("Helper done")
        return httpx.Response(200, json=response([item], response_id=f"r{len(seen)}"))

    client = mock_client(route)
    report = await research_worker.ResearchTeamRunner(
        service, executor=executor_for(service, client)
    ).run(
        research_worker.TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=author.project_id,
            mode="replay",
            task_ids=[root["id"]],
            max_concurrency=1,
            max_tasks=3,
            timeout_seconds=15,
        )
    )
    assert report["status"] == "completed", report
    assert seen["Helper"][0]["task_contract"]["strategy"] == "Bound the trace via Cauchy-Schwarz"
    assert seen["Root"][0]["task_contract"]["strategy"] is None
    assert "Too long" not in seen
    await client.close()


# Task 5: bounded amendment history


def test_superseded_objectives_keep_last_eight_and_digest_dropped(lab):
    service, author, controller, _, (alpha, _) = ideas_lab(lab)
    task = service.create_task(TaskCreate(branch_id=alpha.branch_id, objective="v0"), author, "t")
    for index in range(1, 12):
        task = service.amend_queued_task_objective(
            task["id"], task["revision"], f"v{index}", controller, f"amend-{index}"
        )
    history = task["superseded_objectives"]
    assert [item["objective"] for item in history] == [f"v{i}" for i in range(3, 11)]
    dropped = task["superseded_objectives_dropped"]
    assert dropped["count"] == 3 and len(dropped["digest"]) == 64
    again = service.amend_queued_task_objective(
        task["id"], task["revision"], "v12", controller, "amend-12"
    )
    assert again["superseded_objectives_dropped"]["count"] == 4
    assert again["superseded_objectives_dropped"]["digest"] != dropped["digest"]
    assert len(again["superseded_objectives"]) == 8


# Task 4: regressions


class ExplicitSyntheticChecker:
    """Synthetic test checker; never Lean or scientific evidence."""

    def verify(self, request):
        from physharness.verification import VerificationOutcome

        return VerificationOutcome(
            status="verified",
            assurance="independent_kernel",
            code="mock_checker_fixture",
            message="Synthetic test",
            remediation="",
            target_digest=request.target_digest,
            challenge_sha256=request.challenge_sha256,
            environment_digest=request.environment_digest,
            candidate_sha256=request.candidate_sha256,
            checker_versions={name: "mock-only" for name in ("lean", "comparator", "nanoda")},
            axioms=[],
        )


def verified_receipt(service, author, experiment):
    from physharness.domain import ArtifactCreate

    service.verifier = ExplicitSyntheticChecker()
    candidate = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            kind="lean_source",
            content="theorem target : (1 : Nat) = 1 := by rfl",
        ),
        author,
        "candidate",
    )
    receipt = service.verify_candidate(experiment["id"], candidate["id"], True, author, "verify")
    verifier = Principal(id="checker", project_id=author.project_id, role="verifier")
    assert service.process_verification(receipt["id"], verifier)["status"] == "verified"
    assert service.verified_target_receipt(experiment["id"], author)["receipt_id"] == receipt["id"]
    return receipt


async def test_amended_queued_objective_reaches_first_provider_request(lab):
    service, author, controller, experiment, (alpha, _) = ideas_lab(lab)
    task = service.create_task(
        TaskCreate(branch_id=alpha.branch_id, objective="Stale objective"), author, "t"
    )
    service.amend_queued_task_objective(
        task["id"], task["revision"], "Fresh objective", controller, "amend"
    )
    requests = []

    async def route(request, payload):
        requests.append(json.dumps(payload))
        return httpx.Response(200, json=response([message("done")]))

    client = mock_client(route)
    result = await executor_for(service, client).execute(task["id"], author.project_id)
    assert result["status"] == "completed"
    assert "Fresh objective" in requests[0] and "Stale objective" not in requests[0]
    await client.close()


def test_verified_target_retires_queued_tasks_including_ready_continuation(lab):
    service, author, controller, experiment, (alpha, beta) = ideas_lab(lab)
    plain = service.create_task(TaskCreate(branch_id=alpha.branch_id, objective="A"), author, "a")
    ready = service.create_task(TaskCreate(branch_id=beta.branch_id, objective="B"), author, "b")
    leased = service.create_task(TaskCreate(branch_id=beta.branch_id, objective="C"), author, "c")
    with service.db.transaction() as session:
        link = service._insert(
            session,
            "continuation_link",
            controller,
            {
                "experiment_id": experiment["id"],
                "task_id": ready["id"],
                "ordinal": 1,
                "status": "issued",
            },
        )
        service._replace(
            session,
            session.get(RecordRow, ready["id"]),
            {"ready_continuation": {"ordinal": 1, "wait_task_ids": []}},
        )
    service.acquire_task(leased["id"], "holder", 60, controller, "lease")
    receipt = verified_receipt(service, author, experiment)
    for task in (plain, ready):
        retired = service.retire_queued_after_verified(
            task["id"], receipt["id"], controller, f"retire-{task['id']}"
        )
        assert retired == {
            "retired": True,
            "task_id": task["id"],
            "status": "blocked",
            "code": "TARGET_ALREADY_VERIFIED",
        }
        row = service.get_record("task", task["id"], controller)
        assert row["superseded_by_receipt_id"] == receipt["id"]
        assert row["ready_continuation"] is None
    retired_row = service.get_record("task", ready["id"], controller)
    assert retired_row["retired_continuation"]["ordinal"] == 1
    with service.db.sessions() as session:
        assert session.get(RecordRow, link["id"]).payload["status"] == "retired"
    kept = service.retire_queued_after_verified(leased["id"], receipt["id"], controller, "keep")
    assert kept["retired"] is False


async def test_concurrent_peer_stops_generation_after_exact_target_verified(lab):
    import asyncio

    service, author, _, experiment, (alpha, beta) = ideas_lab(lab, concurrency=2)
    service.verifier = ExplicitSyntheticChecker()
    prover = service.create_task(
        TaskCreate(branch_id=alpha.branch_id, objective="Prove"), author, "p"
    )
    peer = service.create_task(
        TaskCreate(branch_id=beta.branch_id, objective="Explore"), author, "e"
    )
    calls = {"Prove": 0, "Explore": 0}

    async def route(request, payload):
        objective = objective_of(payload)
        calls[objective] += 1
        step = calls[objective]
        results = [
            json.loads(item["output"])
            for item in payload["input"]
            if item.get("type") == "function_call_output"
        ]
        if objective == "Explore":
            if step == 2:
                # Hold this response until the exact target is verified; its settled
                # boundary is the last point before any further generation.
                for _ in range(400):
                    if service.verified_target_receipt(experiment["id"], author):
                        break
                    await asyncio.sleep(0.025)
                else:
                    raise AssertionError("Target was never verified")
            if step > 2:
                raise AssertionError("Generation after exact accepted target")
            item = tool_call("research_capacity", {}, f"capacity-{step}")
        elif step == 1:
            item = tool_call(
                "store_artifact",
                {"kind": "lean_source", "content": "theorem target : (1 : Nat) = 1 := by rfl"},
                "candidate",
            )
        elif step == 2:
            item = tool_call("verify_candidate", {"artifact_id": results[-1]["id"]}, "verify")
        elif step == 3:
            item = tool_call(
                "wait_for_verification",
                {"receipt_id": results[-1]["id"], "timeout_seconds": 5},
                "wait",
            )
        else:
            raise AssertionError("Prover generated after exact accepted target")
        return httpx.Response(200, json=response([item], response_id=f"{objective}-{step}"))

    client = mock_client(route)
    report = await research_worker.ResearchTeamRunner(
        service, executor=executor_for(service, client)
    ).run(
        research_worker.TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=author.project_id,
            mode="replay",
            task_ids=[prover["id"], peer["id"]],
            max_concurrency=2,
            timeout_seconds=20,
        )
    )
    assert calls == {"Prove": 3, "Explore": 2}, (calls, report["outcomes"])
    assert report["root_goal_status"] == "verified"
    assert report["ledger"]["active_workers"] == 0
    await client.close()


async def test_helper_final_response_alone_leaves_root_unproved(lab):
    service, author, _, experiment, (alpha, _) = ideas_lab(lab)
    helper_branch = service.create_branch(
        experiment["id"],
        BranchCreate(title="Helper", objective="Sublemma", parent_id=alpha.branch_id),
        author,
        "helper",
    )
    helper = service.create_task(
        TaskCreate(branch_id=helper_branch["id"], objective="Helper"), author, "h"
    )

    async def route(request, payload):
        return httpx.Response(200, json=response([message("The target theorem is proved. QED.")]))

    client = mock_client(route)
    report = await research_worker.ResearchTeamRunner(
        service, executor=executor_for(service, client)
    ).run(
        research_worker.TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=author.project_id,
            mode="replay",
            task_ids=[helper["id"]],
            max_concurrency=1,
            timeout_seconds=15,
        )
    )
    assert service.get_record("task", helper["id"], author)["status"] == "completed"
    assert report["root_goal_status"] == "unproved"
    assert service.verified_target_receipt(experiment["id"], author) is None
    await client.close()
