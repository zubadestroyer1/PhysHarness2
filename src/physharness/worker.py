"""Temporal worker and transactional-outbox pump. Missing configuration is a fatal startup error."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from .bootstrap import build_service
from .config import Settings
from .domain import BranchCreate, Principal, TaskCreate
from .errors import HarnessError
from .logging import configure_logging
from .orchestration import OutboxDispatcher
from .orchestration.research_worker import ResearchTaskExecutor
from .orchestration.sandbox import workflow_runner
from .orchestration.workflows import ExperimentWorkflow, TaskWorkflow, VerificationWorkflow

log = logging.getLogger(__name__)


class Activities:
    def __init__(self, service, executor):
        self.service, self.executor = service, executor

    @activity.defn
    def apply_experiment_command(self, item: dict) -> dict:
        actor = Principal(id="research-controller", project_id=item["project_id"], role="operator")
        experiment = self.service.get_record("experiment", item["aggregate_id"], actor)
        if item["kind"] != "experiment.queued" or experiment["status"] not in {"queued", "running"}:
            return {"status": experiment["status"]}
        if experiment["policy"] not in {"independent", "direct"}:
            raise HarnessError(
                "POLICY_NOT_INTEGRATED",
                "This worker currently executes direct and independent policies.",
                remediation=(
                    "Evaluate other portfolio planners through explicit manifests before promotion."
                ),
            )
        models = (
            experiment["models"]
            if experiment["policy"] == "independent"
            else experiment["models"][:1]
        )
        task_ids = []
        for index, _ in enumerate(models):
            branch = self.service.create_branch(
                experiment["id"],
                BranchCreate(
                    title=f"Independent approach {index + 1}",
                    objective="Investigate the complete target using a method of your choosing.",
                    model_index=index,
                ),
                actor,
                f"seed-branch:{experiment['id']}:{index}",
            )

            task = self.service.create_task(
                TaskCreate(branch_id=branch["id"], objective=branch["objective"]),
                actor,
                f"seed-task:{branch['id']}",
            )
            task_ids.append(task["id"])
        return {
            "experiment_id": experiment["id"],
            "seeded_approaches": len(models),
            "task_ids": task_ids,
        }

    @activity.defn
    async def run_research_task(self, item: dict) -> dict:
        async def heartbeat():
            while True:
                activity.heartbeat({"task_id": item["aggregate_id"]})
                await asyncio.sleep(10)

        beat = asyncio.create_task(heartbeat())
        try:
            return await self.executor.execute(item["aggregate_id"], item["project_id"])
        except HarnessError as error:
            actor = Principal(
                id="research-controller", project_id=item["project_id"], role="operator"
            )
            task = self.service.get_record("task", item["aggregate_id"], actor)
            experiment = self.service.get_record("experiment", task["experiment_id"], actor)
            waiting = error.code in {"DEPENDENCIES_PENDING", "CONCURRENCY_EXCEEDED", "LEASE_HELD"}
            waiting = waiting or (
                error.code == "EXPERIMENT_NOT_ACTIVE" and experiment["status"] == "paused"
            )
            log.warning("Task dispatch stopped: %s", error.code, extra={"task_id": task["id"]})
            if not waiting and task["status"] == "queued":

                def block(session, op, error=error):
                    row = self.service._get(session, "task", task["id"], actor)
                    if row.payload["status"] != "queued":
                        return row.payload
                    result = self.service._replace(
                        session,
                        row,
                        {
                            "status": "blocked",
                            "error_code": error.code,
                            "remediation": error.remediation,
                        },
                    )
                    self.service._event(
                        session, actor, op, "task.blocked", row.id, {"code": error.code}
                    )
                    return result

                self.service._execute(
                    actor,
                    f"dispatch-blocked:{item['id']}",
                    "task.dispatch-blocked",
                    {"task_id": task["id"]},
                    block,
                )
            return {
                "task_id": task["id"],
                "status": "waiting" if waiting else "blocked",
                "code": error.code,
            }
        finally:
            beat.cancel()
            try:
                await beat
            except asyncio.CancelledError:
                pass

    @activity.defn
    def verify_candidate_activity(self, item: dict) -> dict:
        actor = Principal(id="acceptance-worker", project_id=item["project_id"], role="verifier")
        result = self.service.process_verification(item["aggregate_id"], actor)
        return {"receipt_id": result["id"], "status": result["status"], "code": result["code"]}


async def main():
    configure_logging()
    settings = Settings()
    configure_logging(settings=settings)
    if not settings.temporal_address:
        raise HarnessError(
            "TEMPORAL_REQUIRED", "Set PHYSHARNESS_TEMPORAL_ADDRESS before starting the worker."
        )
    service = build_service(settings)
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        tls=settings.temporal_tls,
        api_key=settings.temporal_api_key.get_secret_value() if settings.temporal_api_key else None,
    )
    workspace_factory = None
    if settings.worker_workspace is not None:
        from .orchestration.workspace_tools import e2b_workspace_factory

        workspace_factory = e2b_workspace_factory(settings.worker_workspace)
    activities = Activities(
        service,
        ResearchTaskExecutor(
            service,
            prices=settings.model_prices,
            workspace_factory=workspace_factory,
        ),
    )

    from .orchestration.temporal_delivery import TemporalDelivery

    dispatcher = OutboxDispatcher(service, TemporalDelivery(client, settings.temporal_task_queue))
    with ThreadPoolExecutor(max_workers=16) as pool:
        async with Worker(
            client,
            task_queue=settings.temporal_task_queue,
            workflows=[ExperimentWorkflow, TaskWorkflow, VerificationWorkflow],
            workflow_runner=workflow_runner(),
            activities=[
                activities.apply_experiment_command,
                activities.run_research_task,
                activities.verify_candidate_activity,
            ],
            activity_executor=pool,
        ):
            while True:
                await dispatcher.run_once()
                await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.getLogger("physharness.worker").exception(
            "Worker startup/execution failed; no fallback controller is running"
        )
        raise SystemExit(1) from None
