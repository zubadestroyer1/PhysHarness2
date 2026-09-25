"""Joined child lifecycle using a fake Responses provider and canonical records."""

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI
from test_core import setup_experiment
from test_execution_responses import message
from test_execution_responses import response as base_response
from test_research_loop_integration import PRICES, tool_call

from physharness.domain import ArtifactCreate, BranchCreate, ExperimentCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import ResponsesRuntime, RuntimeLimits
from physharness.orchestration.research_worker import (
    ResearchTaskExecutor,
    ResearchTeamRunner,
    TeamRunManifest,
)
from physharness.orchestration.temporal_delivery import TemporalDelivery
from physharness.orchestration.workspace_selection import configured_workspace_factory
from physharness.orchestration.workspace_tools import WorkspacePolicy
from physharness.run_control import run_preflight
from physharness.worker_authority import worker_effects


def response(items, text="", response_id="resp_1"):
    native = base_response(items, text, response_id)
    native["model"] = "explicit-test-model"
    return native


@pytest.mark.asyncio
async def test_parent_final_response_joins_child_with_one_slot_and_no_paid_replay(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, "root"
    )
    parent = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Parent"), actor, "parent"
    )
    phases = {"parent": 0, "child": 0}
    seen_joined = []

    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        payload = json.loads(request.content)
        prompt = json.loads(
            next(
                item["content"] for item in reversed(payload["input"]) if item.get("role") == "user"
            )
        )
        if prompt["objective"] == "Child":
            phase = phases["child"]
            phases["child"] += 1
            if phase == 0:
                return httpx.Response(
                    200,
                    json=response(
                        [
                            tool_call(
                                "return_result",
                                {
                                    "evidence_status": "unverified",
                                    "artifact_ids": [],
                                    "unresolved_obligations": ["Check the final equality"],
                                    "summary": "A provisional route uses trace linearity.",
                                    "execution_failure": None,
                                },
                                "child-result",
                            )
                        ]
                    ),
                )
            return httpx.Response(200, json=response([message("Provisional child finding.")]))
        phase = phases["parent"]
        phases["parent"] += 1
        if phase == 0:
            return httpx.Response(
                200,
                json=response(
                    [
                        tool_call(
                            "delegate",
                            {"branch_id": branch["id"], "objective": "Child", "dependency_ids": []},
                            "parent-delegate",
                        )
                    ]
                ),
            )
        if phase == 1:
            return httpx.Response(200, json=response([message("Parent awaits child result.")]))
        assert any(
            item.get("type") == "function_call_output" and item.get("call_id") == "parent-delegate"
            for item in payload["input"]
        )
        seen_joined.append(prompt["joined_results"])
        return httpx.Response(200, json=response([message("Parent integrated child result.")]))

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=lambda **kw: ResponsesRuntime(client=client, **kw),
        limits=RuntimeLimits(max_turns=30),
    )
    report = await ResearchTeamRunner(service, executor=executor).run(
        TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=actor.project_id,
            mode="replay",
            task_ids=[parent["id"]],
            max_concurrency=1,
            max_tasks=2,
            timeout_seconds=10,
        )
    )
    assert report["status"] == "completed"
    assert phases == {"parent": 3, "child": 2}
    assert seen_joined[0]["all_terminal"] is True
    assert seen_joined[0]["children"][0]["execution_status"] == "completed"
    assert (
        seen_joined[0]["children"][0]["return_result"]["evidence_status"]
        == "withheld_by_sharing_policy"
    )
    assert service.get_record("task", parent["id"], actor)["continuation_count"] == 1
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    await client.close()


@pytest.mark.asyncio
async def test_two_join_epochs_deliver_each_child_once_without_rejoining_old_child(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, "root"
    )
    parent = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Parent"), actor, "parent"
    )
    phase = 0
    joined_counts = []

    async def route(request):
        nonlocal phase
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        payload = json.loads(request.content)
        prompt = json.loads(
            next(
                item["content"] for item in reversed(payload["input"]) if item.get("role") == "user"
            )
        )
        if prompt["objective"].startswith("Child"):
            return httpx.Response(200, json=response([message("Unverified child work.")]))
        current = phase
        phase += 1
        if current in {0, 2}:
            if current == 2:
                joined_counts.append(len(prompt["joined_results"]["children"]))
            number = 1 if current == 0 else 2
            return httpx.Response(
                200,
                json=response(
                    [
                        tool_call(
                            "delegate",
                            {
                                "branch_id": branch["id"],
                                "objective": f"Child{number}",
                                "dependency_ids": [],
                            },
                            f"delegate-{number}",
                        )
                    ]
                ),
            )
        if current == 4:
            joined_counts.append(len(prompt["joined_results"]["children"]))
        return httpx.Response(200, json=response([message(f"Parent answer {current}.")]))

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=lambda **kw: ResponsesRuntime(client=client, **kw),
        limits=RuntimeLimits(max_turns=30),
    )
    report = await ResearchTeamRunner(service, executor=executor).run(
        TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=actor.project_id,
            mode="replay",
            task_ids=[parent["id"]],
            max_concurrency=1,
            max_tasks=3,
            timeout_seconds=10,
        )
    )
    assert report["status"] == "completed"
    assert phase == 5 and joined_counts == [1, 2]
    task = service.get_record("task", parent["id"], actor)
    assert task["continuation_count"] == 2
    assert len(task["delivered_child_task_ids"]) == 2
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    await client.close()


def test_joined_lineage_rejects_ancestor_dependency_and_preserves_detached(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, "root"
    )
    parent = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Parent"), actor, "parent"
    )
    controller = Principal(id="controller", project_id=actor.project_id, role="operator")
    lease = service.acquire_task(parent["id"], "holder", 60, controller, "lease")
    agent = Principal(
        id="holder",
        project_id=actor.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=branch["id"],
    )
    with worker_effects(agent, parent["id"], "holder", lease["fence"]):
        with pytest.raises(HarnessError) as rejected:
            service.create_task(
                TaskCreate(
                    branch_id=branch["id"],
                    objective="Impossible",
                    dependency_ids=[parent["id"]],
                ),
                agent,
                "cycle",
            )
        assert rejected.value.code == "JOIN_DEPENDENCY_CYCLE"
        joined = service.create_task(
            TaskCreate(branch_id=branch["id"], objective="Joined"), agent, "joined"
        )
        detached = service.create_task(
            TaskCreate(branch_id=branch["id"], objective="Detached", detached=True),
            agent,
            "detached",
        )
    assert service.joined_task_statuses(parent["id"], agent)["pending_ids"] == [joined["id"]]
    assert detached["id"] not in service.joined_task_statuses(parent["id"], agent)["pending_ids"]
    with pytest.raises(HarnessError) as private:
        service.delegated_task_statuses(detached["id"], [joined["id"]], agent)
    assert private.value.code in {"TASK_SCOPE", "HANDOFF_CHILD_SCOPE"}


def test_local_workbench_selection_requires_pinned_explicit_configuration():
    policy = WorkspacePolicy(
        template_id="sha256:" + "a" * 64,
        environment_digest="b" * 64,
        qualification_report_sha256="c" * 64,
        timeout_seconds=60,
        cost_bound_usd="0",
        cost_source="local_no_external_invoice",
    )
    settings = SimpleNamespace(
        worker_workspace=policy,
        worker_workspace_provider="local_docker",
        worker_docker_host=None,
        worker_image_digest=None,
        worker_workspace_quota_bytes=256 * 1024 * 1024,
    )
    with pytest.raises(HarnessError) as missing:
        configured_workspace_factory(settings)
    assert missing.value.code == "WORKSPACE_CONFIG_REQUIRED"
    settings.worker_docker_host = "unix:///tmp/physharness-dedicated.sock"
    settings.worker_image_digest = policy.template_id
    factory = configured_workspace_factory(settings)
    assert "isolated_workspace" in factory.capabilities
    assert callable(factory.preflight)


@pytest.mark.asyncio
async def test_formal_profile_rejects_missing_workbench_before_lease_or_model(lab):
    service, actor, _ = lab
    baseline, _ = setup_experiment(lab)
    experiment = service.create_experiment(
        ExperimentCreate(
            campaign_id=baseline["campaign_id"],
            problem_id=baseline["problem_id"],
            models=baseline["models"],
            budget=baseline["budget"],
            execution_profile="formal-research",
        ),
        actor,
        "formal-experiment",
    )
    operator = Principal(id="operator", project_id=actor.project_id, role="operator")
    preflight = run_preflight(
        service,
        operator,
        experiment["id"],
        prices=PRICES,
        environment={"OPENAI_API_KEY": "mock-only"},
        workbench_factory=None,
    )
    assert "WORKBENCH_CAPABILITY_REQUIRED" in {x["code"] for x in preflight["blockers"]}
    service.transition_experiment(experiment["id"], "start", 1, actor, "formal-start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Formal", objective="Explore"), actor, "formal-branch"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "formal-task"
    )
    executor = ResearchTaskExecutor(service, prices=PRICES, workspace_factory=None)
    with pytest.raises(HarnessError) as blocked:
        await executor.execute(task["id"], actor.project_id)
    assert blocked.value.code == "WORKBENCH_CAPABILITY_REQUIRED"
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    assert service.list_records("session", actor, experiment["id"]) == []


@pytest.mark.asyncio
async def test_formal_profile_optional_cumulative_token_guard_crosses_tool_boundary(lab):
    service, actor, _ = lab
    baseline, _ = setup_experiment(lab)
    experiment = service.create_experiment(
        ExperimentCreate(
            campaign_id=baseline["campaign_id"],
            problem_id=baseline["problem_id"],
            models=baseline["models"],
            budget=baseline["budget"],
            execution_profile="formal-research",
            runtime_limits={
                "max_turns": 10,
                "max_output_tokens": 16384,
                "max_context_tokens": 128000,
                "max_total_tokens": None,
            },
        ),
        actor,
        "formal-optional-tokens",
    )
    service.transition_experiment(experiment["id"], "start", 1, actor, "formal-open")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Formal", objective="Research"), actor, "formal-root"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "formal-work"
    )

    class DummyTools:
        policy = SimpleNamespace(model_dump=lambda **kw: {"fixture": True})

        def register(self, register):
            pass

        async def close(self):
            pass

    def factory(*args):
        return DummyTools()

    factory.capabilities = frozenset(
        {
            "isolated_workspace",
            "checkpoint_restore",
            "library_source_lookup",
            "library_source_search",
            "library_declaration_lookup",
            "lean_scratch",
            "scientific_command",
            "workspace_files",
            "exact_polynomial",
            "exact_matrix",
        }
    )
    factory.preflight = lambda: {"vm_started": False}
    calls = 0

    async def route(request):
        nonlocal calls
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        calls += 1
        payload = json.loads(request.content)
        assert payload["context_management"][0]["compact_threshold"] == 96000
        if calls == 1:
            return httpx.Response(200, json=response([tool_call("working_context", {}, "read")]))
        return httpx.Response(200, json=response([message("Still unresolved.")]))

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=lambda **kw: ResponsesRuntime(client=client, **kw),
        workspace_factory=factory,
    )
    result = await executor.execute(task["id"], actor.project_id)
    assert result["status"] == "completed" and calls == 2
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    await client.close()


@pytest.mark.parametrize("child_status", ["completed", "blocked"])
def test_nested_results_are_routed_once_to_direct_parent_under_ideas_policy(lab, child_status):
    service, actor, _ = lab
    baseline, _ = setup_experiment(lab)
    experiment = service.create_experiment(
        ExperimentCreate(
            campaign_id=baseline["campaign_id"],
            problem_id=baseline["problem_id"],
            models=baseline["models"],
            budget=baseline["budget"],
            sharing="ideas",
        ),
        actor,
        "ideas-experiment",
    )
    service.transition_experiment(experiment["id"], "start", 1, actor, "ideas-start")
    parent_branch = service.create_branch(
        experiment["id"], BranchCreate(title="Parent", objective="Explore"), actor, "p-branch"
    )
    child_branch = service.create_branch(
        experiment["id"],
        BranchCreate(
            title="Child",
            objective="Explore part",
            parent_id=parent_branch["id"],
            relation="helper",
        ),
        actor,
        "c-branch",
    )
    assert child_branch["reply_to_parent"] == parent_branch["id"]
    parent = service.create_task(
        TaskCreate(branch_id=parent_branch["id"], objective="Parent"), actor, "p-task"
    )
    controller = Principal(id="controller", project_id=actor.project_id, role="operator")
    parent_lease = service.acquire_task(parent["id"], "p-holder", 60, controller, "p-lease")
    parent_agent = Principal(
        id="p-holder",
        project_id=actor.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=parent_branch["id"],
    )
    with worker_effects(parent_agent, parent["id"], "p-holder", parent_lease["fence"]):
        child = service.create_task(
            TaskCreate(branch_id=child_branch["id"], objective="Child"), parent_agent, "c-task"
        )
    child_lease = service.acquire_task(child["id"], "c-holder", 60, controller, "c-lease")
    child_agent = Principal(
        id="c-holder",
        project_id=actor.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=child_branch["id"],
    )
    with worker_effects(child_agent, child["id"], "c-holder", child_lease["fence"]):
        grandchild = service.create_task(
            TaskCreate(branch_id=child_branch["id"], objective="Grandchild"),
            child_agent,
            "gc-task",
        )
        result = service.return_result(
            child["id"],
            "unverified",
            [],
            ["Show the final step"],
            None,
            child_agent,
            "result",
        )
    assert service.joined_task_statuses(parent["id"], parent_agent)["pending_ids"] == [child["id"]]
    assert service.joined_task_statuses(child["id"], child_agent)["pending_ids"] == [
        grandchild["id"]
    ]
    evidence = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            branch_id=child_branch["id"],
            kind="research_output",
            content="Attribution only",
        ),
        controller,
        "c-evidence",
    )
    with pytest.raises(HarnessError) as pending:
        service.finish_task(
            child["id"],
            "c-holder",
            child_lease["fence"],
            [evidence["id"]],
            "completed",
            controller,
            "premature-child-finish",
        )
    assert pending.value.code == "JOINED_CHILDREN_PENDING"
    grandchild_lease = service.acquire_task(
        grandchild["id"], "gc-holder", 60, controller, "gc-lease"
    )
    service.finish_task(
        grandchild["id"],
        "gc-holder",
        grandchild_lease["fence"],
        [evidence["id"]],
        "blocked",
        controller,
        "gc-blocked",
    )
    first = service.finish_task(
        child["id"],
        "c-holder",
        child_lease["fence"],
        [evidence["id"]],
        child_status,
        controller,
        "c-finish",
    )
    duplicate = service.finish_task(
        child["id"],
        "c-holder",
        child_lease["fence"],
        [evidence["id"]],
        child_status,
        controller,
        "c-finish",
    )
    assert first == duplicate
    visible = service.delegated_task_statuses(parent["id"], [child["id"]], parent_agent)
    assert visible["children"][0]["return_result"]["unresolved_obligations"] == [
        "Show the final step"
    ]
    assert visible["children"][0]["return_result"]["execution_status"] == child_status
    assert visible["children"][0]["return_result"]["summary"] == "Attribution only"
    assert visible["children"][0]["return_result"]["artifact_ids"] == [evidence["id"]]
    if child_status == "blocked":
        assert visible["children"][0]["return_result"]["execution_failure"]["status"] == "blocked"
    assert result["evidence_status"] == "unverified"
    mailbox = service.mailbox_page(parent_branch["id"], parent_agent)
    notices = [item for item in mailbox["items"] if item["child_task_id"] == child["id"]]
    assert len(notices) == 1
    assert notices[0]["reply_to_parent_task_id"] == parent["id"]


@pytest.mark.asyncio
async def test_closed_parent_workflow_uses_digest_scoped_continuation_epoch():
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.exceptions import WorkflowAlreadyStartedError

    command = {
        "id": "ready-event",
        "project_id": "lab",
        "kind": "task.queued",
        "aggregate_id": "parent-task",
        "payload": {"continuation": {"source_checkpoint_digest": "checkpoint-digest"}},
    }
    started = []

    class Description:
        workflow_type = "TaskWorkflow"
        status = WorkflowExecutionStatus.COMPLETED

        async def memo(self):
            return {"canonical_aggregate": "parent-task", "project_id": "lab"}

    class Client:
        async def start_workflow(self, *args, **kwargs):
            started.append(kwargs["id"])
            if kwargs["id"] == "task:parent-task":
                raise WorkflowAlreadyStartedError("task:parent-task", "TaskWorkflow")

        def get_workflow_handle(self, identifier):
            assert identifier == "task:parent-task"
            return self

        async def describe(self):
            return Description()

    await TemporalDelivery(Client(), "fixture-queue")(command)
    assert started == ["task:parent-task", "task:parent-task:resume:checkpoint-digest"]


@pytest.mark.asyncio
async def test_terminal_boundary_failure_recovers_under_fresh_fence_without_paid_replay(
    lab,
    monkeypatch,
):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, "root"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task"
    )
    original_joined = service.joined_task_statuses
    checks = 0

    def flaky_joined(task_id, principal):
        nonlocal checks
        checks += 1
        if checks == 2:
            raise RuntimeError("boundary decision interrupted")
        return original_joined(task_id, principal)

    monkeypatch.setattr(service, "joined_task_statuses", flaky_joined)
    paid_calls = 0

    async def route(request):
        nonlocal paid_calls
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        paid_calls += 1
        native = response([message("Exact terminal text.")])
        native["model"] = "explicit-test-model"
        return httpx.Response(200, json=native)

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=lambda **kw: ResponsesRuntime(client=client, **kw),
    )
    first = await executor.execute(task["id"], actor.project_id)
    assert first["status"] == "continuation"
    assert first["code"] == "TERMINAL_BOUNDARY_RECOVERY"
    assert service.get_record("task", task["id"], actor)["status"] == "queued"
    second = await executor.execute(task["id"], actor.project_id)
    assert second["status"] == "completed"
    assert service.artifact_content(second["artifact_id"], actor) == b"Exact terminal text."
    assert paid_calls == 1
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    await client.close()


@pytest.mark.asyncio
async def test_lost_join_handoff_reply_recovers_without_replaying_parent_final(lab, monkeypatch):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, "root"
    )
    parent = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Parent"), actor, "parent"
    )
    original_handoff = service.request_handoff
    lost_reply = False

    def request_handoff(*args, **kwargs):
        nonlocal lost_reply
        result = original_handoff(*args, **kwargs)
        if args[1] == "joined_children" and not lost_reply:
            lost_reply = True
            raise RuntimeError("reply lost after canonical handoff intent")
        return result

    monkeypatch.setattr(service, "request_handoff", request_handoff)
    parent_calls = 0
    child_calls = 0

    async def route(request):
        nonlocal parent_calls, child_calls
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        payload = json.loads(request.content)
        prompt = json.loads(
            next(
                item["content"] for item in reversed(payload["input"]) if item.get("role") == "user"
            )
        )
        if prompt["objective"] == "Child":
            child_calls += 1
            return httpx.Response(200, json=response([message("Child outcome.")]))
        parent_calls += 1
        if parent_calls == 1:
            return httpx.Response(
                200,
                json=response(
                    [
                        tool_call(
                            "delegate",
                            {
                                "branch_id": branch["id"],
                                "objective": "Child",
                                "dependency_ids": [],
                            },
                            "delegate",
                        )
                    ]
                ),
            )
        if parent_calls == 2:
            native = response([message("Parent awaits child.")])
            native["model"] = "explicit-test-model"
            return httpx.Response(200, json=native)
        return httpx.Response(200, json=response([message("Parent integrated child.")]))

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=lambda **kw: ResponsesRuntime(client=client, **kw),
        limits=RuntimeLimits(max_turns=30),
    )
    report = await ResearchTeamRunner(service, executor=executor).run(
        TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=actor.project_id,
            mode="replay",
            task_ids=[parent["id"]],
            max_concurrency=1,
            max_tasks=2,
            timeout_seconds=10,
        )
    )
    assert report["status"] == "completed"
    assert lost_reply and parent_calls == 3 and child_calls == 1
    assert service.get_record("task", parent["id"], actor)["continuation_count"] == 1
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    await client.close()
