"""Real local Temporal engine tests; no hosted models or cloud provider calls."""

import asyncio
import os
from datetime import timedelta

import httpx
import pytest
from openai import AsyncOpenAI
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from test_core import setup_experiment
from test_execution_responses import message
from test_execution_responses import response as base_response
from test_research_loop_integration import PRICES, tool_call

from physharness.domain import BranchCreate, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import ResponsesRuntime, RuntimeLimits
from physharness.orchestration.research_worker import ResearchTaskExecutor
from physharness.orchestration.sandbox import workflow_runner
from physharness.orchestration.temporal_delivery import TemporalDelivery
from physharness.orchestration.workflows import (
    ExperimentWorkflow,
    TaskWorkflow,
    VerificationWorkflow,
)


def response(items, text="", response_id="resp_1"):
    native = base_response(items, text, response_id)
    native["model"] = "explicit-test-model"
    return native


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("PHYSHARNESS_RUN_TEMPORAL_TESTS") != "1",
        reason="Explicit local Temporal test-server opt-in required; not a live-model trial.",
    ),
]


@activity.defn(name="run_research_task")
async def scripted_task(item: dict) -> dict:
    activity.heartbeat({"test": True})
    return {"task_id": item["aggregate_id"], "status": "completed", "evidence": "replay_fixture"}


@activity.defn(name="verify_candidate_activity")
def unavailable_checker(item: dict) -> dict:
    return {"receipt_id": item["aggregate_id"], "status": "blocked", "code": "verifier_unavailable"}


@pytest.mark.asyncio
async def test_real_temporal_executes_and_preserves_explicit_blocked_verification(tmp_path):
    async with await WorkflowEnvironment.start_local(
        download_dest_dir=str(tmp_path),
        dev_server_download_version="v1.8.3",
        dev_server_database_filename=str(tmp_path / "temporal.db"),
    ) as environment:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(2) as pool:
            async with Worker(
                environment.client,
                task_queue="integration-fixtures",
                workflows=[TaskWorkflow, VerificationWorkflow],
                workflow_runner=workflow_runner(),
                activities=[scripted_task, unavailable_checker],
                activity_executor=pool,
            ):
                result = await environment.client.execute_workflow(
                    TaskWorkflow.run,
                    {"aggregate_id": "replay-task"},
                    id="replay-task",
                    task_queue="integration-fixtures",
                    execution_timeout=timedelta(seconds=30),
                )
                assert result["evidence"] == "replay_fixture"
                receipt = await environment.client.execute_workflow(
                    VerificationWorkflow.run,
                    {"aggregate_id": "blocked-check"},
                    id="blocked-check",
                    task_queue="integration-fixtures",
                    execution_timeout=timedelta(seconds=30),
                )
                assert receipt["status"] == "blocked"


@pytest.mark.asyncio
async def test_real_temporal_validates_active_and_completed_duplicate_identity(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    commands = asyncio.Queue()

    @activity.defn(name="apply_experiment_command")
    async def apply_command(item: dict) -> dict:
        await commands.put(item)
        return {"status": "replay_fixture"}

    @activity.defn(name="run_research_task")
    async def held_task(item: dict) -> dict:
        calls.append(item)
        entered.set()
        await release.wait()
        return {"status": "completed", "evidence": "replay_fixture"}

    async with await WorkflowEnvironment.start_local(
        download_dest_dir=str(tmp_path),
        dev_server_download_version="v1.8.3",
        dev_server_database_filename=str(tmp_path / "temporal.db"),
    ) as environment:
        async with Worker(
            environment.client,
            task_queue="duplicate-integration-fixtures",
            workflows=[TaskWorkflow, ExperimentWorkflow],
            workflow_runner=workflow_runner(),
            activities=[held_task, apply_command],
        ):
            deliver = TemporalDelivery(environment.client, "duplicate-integration-fixtures")
            item = {"kind": "task.queued", "aggregate_id": "canonical-task", "project_id": "lab"}
            await deliver(item)
            await asyncio.wait_for(entered.wait(), timeout=15)
            try:
                await deliver({**item, "attempt": 2})
                with pytest.raises(HarnessError, match="different canonical"):
                    await deliver({**item, "project_id": "wrong-project"})
                assert len(calls) == 1
            finally:
                release.set()
            handle = environment.client.get_workflow_handle("task:canonical-task")
            assert (await handle.result())["status"] == "completed"
            await deliver(item)
            assert len(calls) == 1
            with pytest.raises(HarnessError, match="different canonical"):
                await deliver({**item, "payload": "changed semantics"})
            experiment = {
                "kind": "experiment.queued",
                "aggregate_id": "canonical-experiment",
                "project_id": "lab",
            }
            await deliver(experiment)
            assert await asyncio.wait_for(commands.get(), timeout=15) == experiment
            with pytest.raises(HarnessError, match="different canonical"):
                await deliver({**experiment, "project_id": "wrong-project"})
            cancelled = {**experiment, "kind": "experiment.cancelled"}
            await deliver(cancelled)
            assert await asyncio.wait_for(commands.get(), timeout=15) == cancelled
            assert await environment.client.get_workflow_handle(
                "experiment:canonical-experiment"
            ).result() == {"status": "cancelled"}


@pytest.mark.asyncio
async def test_real_temporal_repeats_continuation_epoch_in_same_task_workflow(tmp_path):
    calls = 0
    first = asyncio.Event()

    @activity.defn(name="run_research_task")
    async def continuation_task(item: dict) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            first.set()
            return {"task_id": item["aggregate_id"], "status": "continuation"}
        return {"task_id": item["aggregate_id"], "status": "completed"}

    async with await WorkflowEnvironment.start_local(
        download_dest_dir=str(tmp_path),
        dev_server_download_version="v1.8.3",
        dev_server_database_filename=str(tmp_path / "temporal.db"),
    ) as environment:
        async with Worker(
            environment.client,
            task_queue="continuation-fixture",
            workflows=[TaskWorkflow],
            workflow_runner=workflow_runner(),
            activities=[continuation_task],
        ):
            deliver = TemporalDelivery(environment.client, "continuation-fixture")
            item = {
                "kind": "task.queued",
                "aggregate_id": "continued-task",
                "project_id": "lab",
                "payload": {},
            }
            await deliver(item)
            await asyncio.wait_for(first.wait(), timeout=15)
            await deliver(
                {
                    **item,
                    "id": "continuation-command",
                    "payload": {"continuation": {"source_checkpoint_digest": "fixture"}},
                }
            )
            result = await asyncio.wait_for(
                environment.client.get_workflow_handle("task:continued-task").result(),
                timeout=20,
            )
            assert result["status"] == "completed"
            assert calls == 2


@pytest.mark.asyncio
async def test_real_temporal_retries_lost_activity_through_canonical_executor(tmp_path):
    calls = 0

    @activity.defn(name="run_research_task")
    async def lost_then_recovered(item: dict) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("worker interrupted after a settled controller checkpoint")
        return {"task_id": item["aggregate_id"], "status": "completed"}

    async with await WorkflowEnvironment.start_local(
        download_dest_dir=str(tmp_path),
        dev_server_download_version="v1.8.3",
        dev_server_database_filename=str(tmp_path / "temporal.db"),
    ) as environment:
        async with Worker(
            environment.client,
            task_queue="crash-recovery-fixture",
            workflows=[TaskWorkflow],
            workflow_runner=workflow_runner(),
            activities=[lost_then_recovered],
        ):
            result = await environment.client.execute_workflow(
                TaskWorkflow.run,
                {"aggregate_id": "recovered-task"},
                id="recovered-task",
                task_queue="crash-recovery-fixture",
                execution_timeout=timedelta(seconds=30),
            )
            assert result["status"] == "completed"
            assert calls == 2


@pytest.mark.asyncio
async def test_real_temporal_retry_consumes_canonical_handoff_without_replaying_provider(
    tmp_path, lab
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
    generation_count = 0
    activity_calls = 0

    async def provider(request):
        nonlocal generation_count
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        generation_count += 1
        if generation_count == 1:
            return httpx.Response(
                200, json=response([tool_call("request_handoff", {"reason": "continue"}, "yield")])
            )
        return httpx.Response(200, json=response([message("Unresolved final text.")]))

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
    )
    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=lambda **kw: ResponsesRuntime(client=client, **kw),
        limits=RuntimeLimits(max_turns=30),
    )

    @activity.defn(name="run_research_task")
    async def canonical_task(item: dict) -> dict:
        nonlocal activity_calls
        activity_calls += 1
        result = await executor.execute(item["aggregate_id"], actor.project_id)
        if activity_calls == 1:
            assert result["status"] == "continuation"
            raise RuntimeError("activity result lost after committed handoff")
        return result

    try:
        async with await WorkflowEnvironment.start_local(
            download_dest_dir=str(tmp_path),
            dev_server_download_version="v1.8.3",
            dev_server_database_filename=str(tmp_path / "temporal.db"),
        ) as environment:
            async with Worker(
                environment.client,
                task_queue="canonical-crash-fixture",
                workflows=[TaskWorkflow],
                workflow_runner=workflow_runner(),
                activities=[canonical_task],
            ):
                result = await environment.client.execute_workflow(
                    TaskWorkflow.run,
                    {"aggregate_id": task["id"]},
                    id=f"task:{task['id']}",
                    task_queue="canonical-crash-fixture",
                    execution_timeout=timedelta(seconds=30),
                )
                assert result["status"] == "completed"
                assert generation_count == 2
                assert activity_calls == 2
                sessions = [
                    row
                    for row in service.list_records("session", actor, experiment["id"])
                    if row["task_id"] == task["id"]
                ]
                assert len(sessions) == 2
                assert {row["status"] for row in sessions} == {"handed_off", "completed"}
                assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    finally:
        await client.close()
