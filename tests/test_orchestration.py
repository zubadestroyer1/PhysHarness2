import pytest
from test_core import setup_experiment

from physharness.orchestration import ModelPrice, OutboxDispatcher


@pytest.mark.asyncio
async def test_dispatch_failure_is_visible_and_replay_reuses_operation_id(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    seen = []

    async def delivery(item):
        seen.append(item["id"])
        if len(seen) == 1:
            raise ConnectionError("injected delivery failure")

    dispatcher = OutboxDispatcher(service, delivery, owner="dispatcher-a", retry_backoff_seconds=0)
    first = await dispatcher.run_once()
    assert first == {"delivered": 0, "failed": 1}
    assert service.pending_outbox()[0]["id"] == seen[0]
    second = await dispatcher.run_once()
    assert second == {"delivered": 1, "failed": 0}
    assert seen[0] == seen[1]
    assert service.pending_outbox() == []


def test_explicit_pricing_never_rounds_reservation_down():
    price = ModelPrice(input_usd_per_million="0.001", output_usd_per_million="1")
    assert str(price.cost(1, 1)) == "0.000002"
    with pytest.raises(ValueError):
        ModelPrice(input_usd_per_million="NaN", output_usd_per_million="1")


@pytest.mark.asyncio
async def test_worker_runs_recorded_model_preserves_checkpoint_and_accounts_usage(lab):
    from physharness.domain import BranchCreate, TaskCreate
    from physharness.execution import RuntimeCheckpoint, RuntimeEvent, RuntimeResult, RuntimeSession
    from physharness.orchestration.research_worker import ResearchTaskExecutor

    class ProtocolRuntime:
        def __init__(self, store, dispatcher, event_sink):
            self.store, self.dispatcher, self.event_sink = store, dispatcher, event_sink

        async def start(self, prompt, model, limits):
            assert model.model == "explicit-test-model"
            assert "Finite-dimensional setting" in prompt
            state = RuntimeSession(runtime="responses", model=model, limits=limits)
            await self.store.save(
                RuntimeCheckpoint.build(state, {"source": "test-only protocol fixture"})
            )
            await self.event_sink(
                RuntimeEvent(
                    kind="generation_started",
                    session_id=state.id,
                    operation_id="fake-call",
                    payload={"input_tokens_reserved": 10, "output_tokens_reserved": 20},
                )
            )
            await self.event_sink(
                RuntimeEvent(
                    kind="usage",
                    session_id=state.id,
                    operation_id="fake-call",
                    payload={"input_tokens": 10, "output_tokens": 5},
                )
            )
            state.status = "completed"
            await self.store.save(RuntimeCheckpoint.build(state, {"result": "Unresolved"}))
            return RuntimeResult(
                session=state, output_text="No proof; remaining assumptions need review."
            )

    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="B", objective="Explore"), actor, "branch"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task"
    )
    executor = ResearchTaskExecutor(
        service,
        prices={
            "explicit-test-model": {"input_usd_per_million": "1", "output_usd_per_million": "2"}
        },
        runtime_factory=ProtocolRuntime,
    )
    result = await executor.execute(task["id"], actor.project_id)
    assert result["status"] == "completed"
    assert service.list_records("claim", actor) == []
    ledger = service.ledger(experiment["id"], actor)
    assert ledger["spent_cost_usd"] == "0.00002"
    assert ledger["tokens_spent"] == 15
    assert ledger["tokens_reserved"] == 0
    assert ledger["active_workers"] == 0
    assert service.list_records("session", actor)[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_temporal_workflow_definitions_prepare_in_actual_sdk_sandbox():
    from temporalio import workflow

    from physharness.orchestration.sandbox import workflow_runner
    from physharness.orchestration.workflows import (
        ExperimentWorkflow,
        TaskWorkflow,
        VerificationWorkflow,
    )

    for definition in [ExperimentWorkflow, TaskWorkflow, VerificationWorkflow]:
        workflow_runner().prepare_workflow(workflow._Definition.must_from_class(definition))


@pytest.mark.asyncio
async def test_runtime_constructor_failure_releases_worker_slot_and_records_fault(lab):
    from physharness.domain import BranchCreate, TaskCreate
    from physharness.orchestration.research_worker import ResearchTaskExecutor

    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="B", objective="Explore"), actor, "branch"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task"
    )

    def failing_constructor(**kwargs):
        raise RuntimeError("injected constructor failure")

    executor = ResearchTaskExecutor(
        service,
        prices={
            "explicit-test-model": {"input_usd_per_million": "1", "output_usd_per_million": "2"}
        },
        runtime_factory=failing_constructor,
    )
    with pytest.raises(RuntimeError):
        await executor.execute(task["id"], actor.project_id)
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    assert service.get_record("task", task["id"], actor)["status"] == "blocked"
    assert any(
        a["artifact_kind"] == "execution_failure" for a in service.list_records("artifact", actor)
    )


@pytest.mark.asyncio
async def test_closed_temporal_duplicate_is_acknowledged_without_restart():
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from physharness.domain import digest_json
    from physharness.orchestration.temporal_delivery import TemporalDelivery

    item = {
        "id": "command-id",
        "project_id": "lab",
        "kind": "task.queued",
        "aggregate_id": "task-id",
        "payload": {},
        "attempt": 2,
    }

    class Description:
        workflow_type = "TaskWorkflow"

        async def memo(self):
            return {
                "canonical_aggregate": "task-id",
                "project_id": "lab",
                "command_sha256": digest_json({k: v for k, v in item.items() if k != "attempt"}),
            }

    class Client:
        async def start_workflow(self, *args, **kwargs):
            raise WorkflowAlreadyStartedError("task:task-id", "TaskWorkflow")

        def get_workflow_handle(self, identifier):
            assert identifier == "task:task-id"
            return self

        async def describe(self):
            return Description()

    await TemporalDelivery(Client(), "queue")(item)


@pytest.mark.asyncio
async def test_obsolete_campaign_command_after_cancellation_is_acknowledged():
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from physharness.orchestration.temporal_delivery import TemporalDelivery

    item = {
        "id": "old-start",
        "project_id": "lab",
        "kind": "experiment.queued",
        "aggregate_id": "experiment-id",
        "payload": {"revision": 2},
    }

    class Description:
        workflow_type = "ExperimentWorkflow"
        status = WorkflowExecutionStatus.COMPLETED

        async def memo(self):
            return {"canonical_aggregate": "experiment-id", "project_id": "lab"}

    class Client:
        async def start_workflow(self, *args, **kwargs):
            raise WorkflowAlreadyStartedError("experiment:experiment-id", "ExperimentWorkflow")

        def get_workflow_handle(self, identifier):
            return self

        async def describe(self):
            return Description()

        async def result(self):
            return {"status": "cancelled"}

    await TemporalDelivery(Client(), "queue")(item)
