"""Real local Temporal engine tests; no hosted models or cloud provider calls."""

import os
from datetime import timedelta

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from physharness.orchestration.sandbox import workflow_runner
from physharness.orchestration.workflows import TaskWorkflow, VerificationWorkflow

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
