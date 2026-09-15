"""Outbox delivery tolerates both running and completed workflow duplicates."""

from datetime import timedelta

from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from ..domain import digest_json
from ..errors import HarnessError
from .workflows import ExperimentWorkflow, TaskWorkflow, VerificationWorkflow


class TemporalDelivery:
    def __init__(self, client, task_queue):
        self.client, self.task_queue = client, task_queue

    async def __call__(self, item):
        options = {
            "task_queue": self.task_queue,
            "id_reuse_policy": WorkflowIDReusePolicy.REJECT_DUPLICATE,
            "id_conflict_policy": WorkflowIDConflictPolicy.FAIL,
            "rpc_timeout": timedelta(seconds=20),
        }
        memo = {"canonical_aggregate": item["aggregate_id"], "project_id": item["project_id"]}
        if item["kind"].startswith("experiment."):
            run, workflow_type = ExperimentWorkflow.run, "ExperimentWorkflow"
            workflow_id = f"experiment:{item['aggregate_id']}"
            # Signal-with-start does not support FAIL and can deliver a signal
            # before canonical memo validation. Atomically start with the first
            # pending command; duplicates take the checked explicit-signal path.
            argument = {"experiment_id": item["aggregate_id"], "pending_commands": [item]}
        elif item["kind"] == "task.queued":
            run, workflow_type = TaskWorkflow.run, "TaskWorkflow"
            workflow_id, argument = f"task:{item['aggregate_id']}", item
            memo["command_sha256"] = digest_json({k: v for k, v in item.items() if k != "attempt"})
        elif item["kind"] == "verification.queued":
            run, workflow_type = VerificationWorkflow.run, "VerificationWorkflow"
            workflow_id, argument = f"verify:{item['aggregate_id']}", item
            memo["command_sha256"] = digest_json({k: v for k, v in item.items() if k != "attempt"})
        elif item["kind"] in {"task.completed", "task.failed", "task.blocked"}:
            return
        else:
            raise HarnessError(
                "UNKNOWN_OUTBOX_EVENT", f"No workflow route exists for {item['kind']}."
            )
        try:
            await self.client.start_workflow(run, argument, id=workflow_id, memo=memo, **options)
        except WorkflowAlreadyStartedError:
            # Validate both active and completed identities. USE_EXISTING would
            # silently acknowledge an active workflow with different command input.
            execution = await self.client.get_workflow_handle(workflow_id).describe()
            if execution.workflow_type != workflow_type or await execution.memo() != memo:
                raise HarnessError(
                    "WORKFLOW_IDENTITY_CONFLICT",
                    "Existing workflow has different canonical inputs.",
                ) from None
            if item["kind"].startswith("experiment."):
                if execution.status == WorkflowExecutionStatus.RUNNING:
                    await self.client.get_workflow_handle(workflow_id).signal(
                        ExperimentWorkflow.command, item, rpc_timeout=timedelta(seconds=20)
                    )
                    return
                if execution.status == WorkflowExecutionStatus.COMPLETED:
                    result = await self.client.get_workflow_handle(workflow_id).result()
                    if result == {"status": "cancelled"}:
                        return

                raise HarnessError(
                    "EXPERIMENT_WORKFLOW_CLOSED",
                    "A closed campaign workflow needs explicit recovery.",
                ) from None
