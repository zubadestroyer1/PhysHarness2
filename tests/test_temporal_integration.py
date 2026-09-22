"""Real local Temporal engine tests; no hosted models or cloud provider calls."""

import asyncio
import os
from datetime import timedelta

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from physharness.errors import HarnessError
from physharness.orchestration.sandbox import workflow_runner
from physharness.orchestration.temporal_delivery import TemporalDelivery
from physharness.orchestration.workflows import (
    ExperimentWorkflow,
    TaskWorkflow,
    VerificationWorkflow,
)

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
