"""Bounded Temporal histories; activities carry identifiers, never large scientific artifacts."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class ExperimentWorkflow:
    def __init__(self):
        self.commands = []

    @workflow.signal
    async def command(self, item: dict):
        self.commands.append(item)

    @workflow.run
    async def run(self, initial: dict):
        self.commands = initial.get("pending_commands", []) + self.commands
        while True:
            await workflow.wait_condition(lambda: bool(self.commands))
            for _ in range(min(len(self.commands), 100)):
                command = self.commands.pop(0)
                await workflow.execute_activity(
                    "apply_experiment_command",
                    command,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=5),
                )
                if command["kind"] == "experiment.cancelled":
                    return {"status": "cancelled"}
            if workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(
                    {"experiment_id": initial["experiment_id"], "pending_commands": self.commands}
                )


@workflow.defn
class TaskWorkflow:
    @workflow.run
    async def run(self, item: dict):
        # Only a declared preflight wait may repeat. Uncertain provider effects do not retry.
        while True:
            result = await workflow.execute_activity(
                "run_research_task",
                item,
                start_to_close_timeout=timedelta(hours=24),
                heartbeat_timeout=timedelta(seconds=40),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            if result.get("status") != "waiting":
                return result
            await workflow.sleep(5)
            if workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(item)


@workflow.defn
class VerificationWorkflow:
    @workflow.run
    async def run(self, item: dict):
        return await workflow.execute_activity(
            "verify_candidate_activity",
            item,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
