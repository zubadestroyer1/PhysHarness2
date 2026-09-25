"""Worker-visible contracts for optional, scoped collaboration."""

import asyncio
import json

import httpx
import pytest
from test_execution_responses import message
from test_research_loop_integration import campaign, mock_executor, response, tool_call

from physharness.domain import BranchCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import ExecutionError
from physharness.orchestration.research_worker import (
    ResearchTeamRunner,
    TeamRunManifest,
    _task_contract,
    research_tools,
)
from physharness.storage import RecordRow
from physharness.worker_authority import worker_effects


def _names(dispatcher):
    return {item["name"] for item in dispatcher.definitions}


def test_worker_catalog_exposes_only_valid_return_and_message_contracts(lab):
    service, actor, _ = lab
    experiment, branch, root = campaign(lab)
    operator = Principal(id="controller", project_id=actor.project_id, role="operator")
    lease = service.acquire_task(root["id"], "root-worker", 60, operator, "root-lease")
    agent = Principal(
        id="root-worker",
        project_id=operator.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=branch["id"],
    )
    with worker_effects(agent, root["id"], "root-worker", lease["fence"]):
        joined = service.create_task(
            TaskCreate(branch_id=branch["id"], objective="Joined child"), agent, "joined"
        )
        detached = service.create_task(
            TaskCreate(branch_id=branch["id"], objective="Detached child", detached=True),
            agent,
            "detached",
        )

    for task in (root, detached):
        names = _names(
            research_tools(
                service,
                agent,
                branch["id"],
                task_context={"task_id": task["id"], "holder": "h", "fence": 1},
            )
        )
        assert "return_result" not in names
        assert "send_message" not in names
        assert "wait_for_tasks" in names
    joined_names = _names(
        research_tools(
            service,
            agent,
            branch["id"],
            task_context={"task_id": joined["id"], "holder": "h", "fence": 1},
        )
    )
    assert "return_result" in joined_names
    assert "send_message" not in joined_names

    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, experiment["id"]), {"sharing": "verified"})
    verified_names = _names(
        research_tools(
            service,
            agent,
            branch["id"],
            task_context={"task_id": root["id"], "holder": "h", "fence": 1},
        )
    )
    assert "send_message" not in verified_names

    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, experiment["id"]), {"sharing": "ideas"})
    ideas_names = _names(
        research_tools(
            service,
            agent,
            branch["id"],
            task_context={"task_id": root["id"], "holder": "h", "fence": 1},
        )
    )
    assert "send_message" in ideas_names
    assert "return_result" not in ideas_names


def test_nonjoined_child_contract_is_not_mislabelled_as_root():
    assert (
        _task_contract(
            {"id": "child", "detached": False, "delegated_from_task_id": "parent"},
            {"id": "branch", "parent_id": "root-branch", "relation": "collaborator"},
        )["kind"]
        == "independent_child"
    )


@pytest.mark.asyncio
async def test_prompt_names_published_peer_and_explains_capacity_and_task_contract(lab):
    service, operator, _ = lab
    experiment, branch, root = campaign(lab, concurrency=2)
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, experiment["id"]), {"sharing": "ideas"})
    peer = service.create_branch(
        experiment["id"], BranchCreate(title="Peer", objective="Private work"), operator, "peer"
    )
    unpublished = service.create_branch(
        experiment["id"],
        BranchCreate(title="Unpublished", objective="Private objective"),
        operator,
        "unpublished-peer",
    )
    from physharness.workforce_models import PublishResearchProfileRequest

    service.publish_research_profile(
        experiment["id"],
        PublishResearchProfileRequest(
            branch_id=peer["id"],
            published=True,
            summary="Opted-in peer",
            interests=[],
            assignment="",
        ),
        operator,
        "peer-profile",
    )
    seen = {}

    async def handler(request):
        payload = json.loads(request.content)
        seen.update(json.loads(payload["input"][0]["content"]))
        return httpx.Response(200, json=response([message("No accepted proof.")]))

    executor, client = mock_executor(service, handler)
    try:
        await ResearchTeamRunner(service, executor=executor).run(
            TeamRunManifest(
                experiment_id=experiment["id"],
                project_id=operator.project_id,
                mode="replay",
                task_ids=[root["id"]],
                max_concurrency=1,
                max_tasks=1,
                timeout_seconds=10,
            )
        )
    finally:
        await client.close()
    assert seen["task_contract"]["kind"] == "root"
    assert seen["task_contract"]["return_result_available"] is False
    assert seen["peer_routing"]["published_branch_ids"] == [peer["id"]]
    assert unpublished["id"] not in seen["peer_routing"]["published_branch_ids"]
    assert seen["peer_routing"]["recipient_id_kind"] == "branch_id"
    assert seen["capacity_guidance"]["delegated_work_shares_budget"] is True
    assert seen["capacity_guidance"]["optional_wait_for_delegated_task"] is True


@pytest.mark.asyncio
async def test_manual_invalid_calls_still_fail_at_service_boundary(lab):
    service, actor, _ = lab
    experiment, branch, root = campaign(lab)
    operator = Principal(id="controller", project_id=actor.project_id, role="operator")
    other = service.create_branch(
        experiment["id"], BranchCreate(title="Other", objective="Other"), operator, "other"
    )
    root_lease = service.acquire_task(root["id"], "worker", 60, operator, "root-lease")
    agent = Principal(
        id="worker",
        project_id=actor.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=branch["id"],
    )
    dispatcher = research_tools(
        service,
        agent,
        branch["id"],
        task_context={"task_id": root["id"], "holder": "worker", "fence": root_lease["fence"]},
    )
    with pytest.raises(ExecutionError) as unavailable:
        await dispatcher.dispatch(
            "send_message",
            {"recipient_id": other["id"], "content": "idea", "artifact_ids": []},
            "forged-tool-call",
        )
    assert unavailable.value.code == "TOOL_UNAVAILABLE"
    with worker_effects(agent, root["id"], "worker", root_lease["fence"]):
        with pytest.raises(HarnessError) as denied:
            service.send_message(branch["id"], other["id"], "idea", [], agent, "direct-send")
        assert denied.value.code == "SHARING_POLICY"
        detached = service.create_task(
            TaskCreate(branch_id=branch["id"], objective="Detached", detached=True),
            agent,
            "detached",
        )
    child_lease = service.acquire_task(detached["id"], "child-worker", 60, operator, "child-lease")
    child_agent = agent.model_copy(update={"id": "child-worker"})
    with worker_effects(child_agent, detached["id"], "child-worker", child_lease["fence"]):
        with pytest.raises(HarnessError) as denied:
            service.return_result(
                detached["id"],
                "unverified",
                [],
                [],
                None,
                child_agent,
                "direct-return",
            )
        assert denied.value.code == "RETURN_RESULT_SCOPE"


@pytest.mark.asyncio
async def test_spare_third_slot_runs_detached_helper_while_two_roots_are_active(lab):
    service, actor, _ = lab
    experiment, root_branch, root_a = campaign(lab, concurrency=3)
    root_b_branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root B", objective="Root B"), actor, "root-b"
    )
    root_b = service.create_task(
        TaskCreate(branch_id=root_b_branch["id"], objective="Root B"), actor, "root-b-task"
    )
    helper_branch = service.create_branch(
        experiment["id"],
        BranchCreate(title="Helper", objective="Helper", parent_id=root_branch["id"]),
        actor,
        "helper-branch",
    )
    root_b_entered, helper_entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    root_a_calls = 0

    async def handler(request):
        nonlocal root_a_calls
        payload = json.loads(request.content)
        objective = json.loads(payload["input"][0]["content"])["objective"]
        if objective == "Root B":
            root_b_entered.set()
            await release.wait()
            return httpx.Response(200, json=response([message("Root B done")], "root-b-done"))
        if objective == "Helper":
            helper_entered.set()
            await release.wait()
            return httpx.Response(200, json=response([message("Helper done")], "helper-done"))
        root_a_calls += 1
        if root_a_calls == 1:
            await root_b_entered.wait()
            return httpx.Response(
                200,
                json=response(
                    [
                        tool_call(
                            "delegate_detached",
                            {
                                "branch_id": helper_branch["id"],
                                "objective": "Helper",
                                "dependency_ids": [],
                            },
                            "delegate-helper",
                        )
                    ],
                    "root-a-delegate",
                ),
            )
        await release.wait()
        return httpx.Response(200, json=response([message("Root A done")], "root-a-done"))

    executor, client = mock_executor(service, handler)
    running = asyncio.create_task(
        ResearchTeamRunner(service, executor=executor).run(
            TeamRunManifest(
                experiment_id=experiment["id"],
                project_id=actor.project_id,
                mode="replay",
                task_ids=[root_a["id"], root_b["id"]],
                max_concurrency=3,
                max_tasks=3,
                timeout_seconds=10,
            )
        )
    )
    try:
        await asyncio.wait_for(helper_entered.wait(), 5)
        assert service.get_record("task", root_a["id"], actor)["status"] == "running"
        assert service.get_record("task", root_b["id"], actor)["status"] == "running"
        assert service.research_capacity(experiment["id"], actor)["active_workers"] == 3
    finally:
        release.set()
        await running
        await client.close()


@pytest.mark.asyncio
async def test_parent_can_yield_only_slot_until_detached_child_finishes(lab):
    service, actor, _ = lab
    experiment, root_branch, root = campaign(lab, concurrency=1)
    helper_branch = service.create_branch(
        experiment["id"],
        BranchCreate(title="Helper", objective="Helper", parent_id=root_branch["id"]),
        actor,
        "helper-branch",
    )
    events = []

    async def handler(request):
        payload = json.loads(request.content)
        prompt = json.loads(payload["input"][0]["content"])
        objective = prompt["objective"]
        if objective == "Helper":
            events.append("helper")
            return httpx.Response(200, json=response([message("Helper done")], "helper-done"))
        if prompt.get("continuation"):
            events.append("parent-resumed")
            return httpx.Response(200, json=response([message("Parent resumed")], "parent-done"))
        outputs = [
            json.loads(item["output"])
            for item in payload["input"]
            if item.get("type") == "function_call_output"
        ]
        if outputs:
            child_id = outputs[-1]["id"]
            events.append("parent-yielded")
            return httpx.Response(
                200,
                json=response(
                    [tool_call("wait_for_tasks", {"task_ids": [child_id]}, "wait-child")],
                    "parent-wait",
                ),
            )
        events.append("parent-delegated")
        return httpx.Response(
            200,
            json=response(
                [
                    tool_call(
                        "delegate_detached",
                        {
                            "branch_id": helper_branch["id"],
                            "objective": "Helper",
                            "dependency_ids": [],
                        },
                        "delegate-helper",
                    )
                ],
                "parent-delegate",
            ),
        )

    executor, client = mock_executor(service, handler)
    try:
        await ResearchTeamRunner(service, executor=executor).run(
            TeamRunManifest(
                experiment_id=experiment["id"],
                project_id=actor.project_id,
                mode="replay",
                task_ids=[root["id"]],
                max_concurrency=1,
                max_tasks=2,
                timeout_seconds=10,
            )
        )
    finally:
        await client.close()
    assert events == ["parent-delegated", "parent-yielded", "helper", "parent-resumed"]
    assert service.get_record("task", root["id"], actor)["status"] == "completed"
