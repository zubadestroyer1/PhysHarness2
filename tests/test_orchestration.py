from decimal import Decimal

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


@pytest.mark.asyncio
async def test_active_temporal_duplicate_validates_identity_before_acknowledgement():
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.common import WorkflowIDConflictPolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from physharness.errors import HarnessError
    from physharness.orchestration.temporal_delivery import TemporalDelivery

    class Client:
        async def start_workflow(self, *args, **kwargs):
            if kwargs["id_conflict_policy"] == WorkflowIDConflictPolicy.FAIL:
                raise WorkflowAlreadyStartedError("task:task-id", "TaskWorkflow")
            return self

        def get_workflow_handle(self, identifier):
            return self

        async def describe(self):
            return self

        workflow_type = "TaskWorkflow"
        status = WorkflowExecutionStatus.RUNNING

        async def memo(self):
            return {"canonical_aggregate": "different-task", "project_id": "lab"}

    item = {
        "id": "command",
        "project_id": "lab",
        "kind": "task.queued",
        "aggregate_id": "task-id",
        "payload": {},
    }
    with pytest.raises(HarnessError) as error:
        await TemporalDelivery(Client(), "queue")(item)
    assert error.value.code == "WORKFLOW_IDENTITY_CONFLICT"


@pytest.mark.asyncio
async def test_experiment_start_embeds_first_command_without_signal_with_start():
    from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

    from physharness.orchestration.temporal_delivery import TemporalDelivery
    from physharness.orchestration.workflows import ExperimentWorkflow

    item = {
        "id": "start-command",
        "project_id": "lab",
        "kind": "experiment.queued",
        "aggregate_id": "experiment-id",
        "payload": {"revision": 2},
    }
    calls = []

    class Client:
        async def start_workflow(self, run, argument, **options):
            calls.append((run, argument, options))
            assert "start_signal" not in options and "start_signal_args" not in options

    await TemporalDelivery(Client(), "queue")(item)
    assert len(calls) == 1
    run, argument, options = calls[0]
    assert run == ExperimentWorkflow.run
    assert argument == {"experiment_id": "experiment-id", "pending_commands": [item]}
    assert options["id_conflict_policy"] == WorkflowIDConflictPolicy.FAIL
    assert options["id_reuse_policy"] == WorkflowIDReusePolicy.REJECT_DUPLICATE
    assert options["memo"] == {"canonical_aggregate": "experiment-id", "project_id": "lab"}


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", [None, "project", "workflow_type"])
async def test_experiment_duplicate_checks_identity_before_explicit_signal(conflict):
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from physharness.errors import HarnessError
    from physharness.orchestration.temporal_delivery import TemporalDelivery
    from physharness.orchestration.workflows import ExperimentWorkflow

    item = {
        "id": "cancel-command",
        "project_id": "lab",
        "kind": "experiment.cancelled",
        "aggregate_id": "experiment-id",
        "payload": {"revision": 3},
    }
    events = []

    class Client:
        workflow_type = "TaskWorkflow" if conflict == "workflow_type" else "ExperimentWorkflow"
        status = WorkflowExecutionStatus.RUNNING

        async def start_workflow(self, *args, **kwargs):
            assert "start_signal" not in kwargs
            events.append("start")
            raise WorkflowAlreadyStartedError("experiment:experiment-id", "ExperimentWorkflow")

        def get_workflow_handle(self, identifier):
            assert identifier == "experiment:experiment-id"
            return self

        async def describe(self):
            events.append("describe")
            return self

        async def memo(self):
            events.append("memo")
            return {
                "canonical_aggregate": "experiment-id",
                "project_id": "other-lab" if conflict == "project" else "lab",
            }

        async def signal(self, handler, command, **options):
            assert handler == ExperimentWorkflow.command and command == item
            assert options["rpc_timeout"].total_seconds() == 20
            events.append("signal")

    if conflict:
        with pytest.raises(HarnessError) as error:
            await TemporalDelivery(Client(), "queue")(item)
        assert error.value.code == "WORKFLOW_IDENTITY_CONFLICT"
        assert "signal" not in events
    else:
        await TemporalDelivery(Client(), "queue")(item)
        assert events == ["start", "describe", "memo", "signal"]


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_signal_start", [False, True])
async def test_experiment_initial_command_and_legacy_signal_are_both_consumed(
    monkeypatch, legacy_signal_start
):
    from physharness.orchestration import workflows

    instance = workflows.ExperimentWorkflow()
    queued = {"id": "queued", "kind": "experiment.queued"}
    cancelled = {"id": "cancelled", "kind": "experiment.cancelled"}
    initial = {"experiment_id": "experiment-id"}
    if legacy_signal_start:
        await instance.command(queued)
    else:
        initial["pending_commands"] = [queued]
    # Temporal can deliver signals before the workflow run coroutine starts.
    await instance.command(cancelled)
    seen = []

    async def wait_condition(predicate):
        assert predicate()

    async def execute_activity(name, item, **options):
        assert name == "apply_experiment_command"
        seen.append(item)
        return {"status": "replay_fixture"}

    monkeypatch.setattr(workflows.workflow, "wait_condition", wait_condition)
    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    assert await instance.run(initial) == {"status": "cancelled"}
    assert seen == [queued, cancelled]


@pytest.mark.asyncio
async def test_experiment_continue_as_new_preserves_pending_and_inflight_signals(monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace

    from physharness.orchestration import workflows

    instance = workflows.ExperimentWorkflow()
    queued = [{"id": str(index), "kind": "experiment.queued"} for index in range(103)]
    arriving = {"id": "arrived-during-activity", "kind": "experiment.queued"}
    cancelled = {"id": "cancelled", "kind": "experiment.cancelled"}
    seen, continuations = [], []

    class Continued(Exception):
        pass

    async def wait_condition(predicate):
        assert predicate()

    async def execute_activity(name, item, **options):
        seen.append(item)
        if item["id"] == "50":
            await instance.command(arriving)
        return {"status": "replay_fixture"}

    def continue_as_new(argument, **options):
        # An omitted memo inherits the prior run's canonical identity in the SDK.
        assert "memo" not in options
        continuations.append(deepcopy(argument))
        raise Continued

    monkeypatch.setattr(workflows.workflow, "wait_condition", wait_condition)
    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(
        workflows.workflow,
        "info",
        lambda: SimpleNamespace(is_continue_as_new_suggested=lambda: True),
    )
    monkeypatch.setattr(workflows.workflow, "continue_as_new", continue_as_new)
    with pytest.raises(Continued):
        await instance.run({"experiment_id": "experiment-id", "pending_commands": queued})
    assert seen == queued[:100]
    assert continuations == [
        {"experiment_id": "experiment-id", "pending_commands": queued[100:] + [arriving]}
    ]
    resumed = workflows.ExperimentWorkflow()
    await resumed.command(cancelled)
    assert await resumed.run(continuations[0]) == {"status": "cancelled"}
    assert seen == queued + [arriving, cancelled]


PRICES = {"explicit-test-model": {"input_usd_per_million": "1", "output_usd_per_million": "2"}}


def started_task(lab, experiment=None):
    """A started experiment with one root task."""
    from physharness.domain import BranchCreate, TaskCreate

    service, actor, _ = lab
    experiment = experiment or setup_experiment(lab)[0]
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="B", objective="Explore"), actor, "branch"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task"
    )
    return service, actor, experiment, task


class UsageRuntime:
    """Emits one reserved generation with the class's usage payload, then completes."""

    usage = {"input_tokens": 10, "output_tokens": 5}

    def __init__(self, store, dispatcher, event_sink):
        self.store, self.event_sink = store, event_sink

    async def start(self, prompt, model, limits):
        from physharness.execution import (
            RuntimeCheckpoint,
            RuntimeEvent,
            RuntimeResult,
            RuntimeSession,
        )

        session = RuntimeSession(runtime="responses", model=model, limits=limits)
        await self.store.save(RuntimeCheckpoint.build(session, {"source": "usage fixture"}))
        for kind, payload in (
            ("generation_started", {"input_tokens_reserved": 10, "output_tokens_reserved": 20}),
            ("usage", self.usage),
        ):
            await self.event_sink(
                RuntimeEvent(
                    kind=kind, session_id=session.id, operation_id="usage-call", payload=payload
                )
            )
        session.status = "completed"
        await self.store.save(RuntimeCheckpoint.build(session, {"result": "Unresolved"}))
        return RuntimeResult(
            session=session, output_text="No proof; remaining assumptions need review."
        )


def price_provenance(service, actor):
    return [
        a["provenance"]["price"]
        for a in service.list_records("artifact", actor)
        if a["artifact_kind"] == "runtime_event"
    ]


def test_cached_input_rate_is_optional_bounded_and_exact():
    plain = ModelPrice(input_usd_per_million="2.50", output_usd_per_million="10", source="s1")
    assert plain.cost(1000, 10, 900) == plain.cost(1000, 10)
    assert plain.model_dump(mode="json", exclude_none=True) == {
        "input_usd_per_million": "2.50",
        "output_usd_per_million": "10",
        "source": "s1",
    }
    cached = ModelPrice(
        input_usd_per_million="2.50",
        output_usd_per_million="10",
        cached_input_usd_per_million="0.25",
        cache_write_usd_per_million="3",
    )
    assert cached.cost(1000, 10, 900) == Decimal("0.000575")  # 100·2.50 + 900·0.25 + 10·10
    # 100·2.50 + 800·0.25 + 100·3 + 10·10
    assert cached.cost(1000, 10, 800, 100) == Decimal("0.000850")
    assert cached.reservation_cost(1000, 10) == Decimal("0.003100")  # 1000·3 + 10·10
    assert plain.reservation_cost(1000, 10) == plain.cost(1000, 10)
    for fields in (
        {"cached_input_usd_per_million": "2", "cache_write_usd_per_million": "2"},
        # A cache hit discount without the write rate would under-settle cache writes.
        {"cached_input_usd_per_million": "0.1"},
    ):
        with pytest.raises(ValueError):
            ModelPrice(input_usd_per_million="1", output_usd_per_million="1", **fields)
    for bad in ((11, 0), (-1, 0), (6, 5), (0, -1)):
        with pytest.raises(ValueError):
            plain.cost(10, 1, *bad)


@pytest.mark.asyncio
async def test_worker_settles_cached_input_at_the_cached_rate(lab, monkeypatch):
    from physharness.orchestration.research_worker import ResearchTaskExecutor

    class CachedUsage(UsageRuntime):
        usage = {
            "input_tokens": 10,
            "output_tokens": 5,
            "cached_input_tokens": 4,
            "cache_write_input_tokens": 6,
        }

    service, actor, experiment, task = started_task(lab)
    reserved = []
    reserve = service.reserve_resources

    def recording(experiment_id, cost, *args, **kwargs):
        reserved.append(Decimal(cost))
        return reserve(experiment_id, cost, *args, **kwargs)

    monkeypatch.setattr(service, "reserve_resources", recording)
    prices = {
        "explicit-test-model": {
            **PRICES["explicit-test-model"],
            "cached_input_usd_per_million": "0.1",
            "cache_write_usd_per_million": "3",
        }
    }
    await ResearchTaskExecutor(service, prices=prices, runtime_factory=CachedUsage).execute(
        task["id"], actor.project_id
    )
    # Reserved: every input token at the cache-write rate, the highest input rate.
    assert Decimal("0.000070") in reserved  # (10·3 + 20·2)/1e6
    ledger = service.ledger(experiment["id"], actor)
    assert ledger["spent_cost_usd"] == "0.000029"  # (4·0.1 + 6·3 + 5·2)/1e6, rounded up
    assert (ledger["tokens_spent"], ledger["tokens_reserved"]) == (15, 0)
    assert all(p["cached_input_usd_per_million"] == "0.1" for p in price_provenance(service, actor))


class KeywordRuntime:
    """Accepts every runtime keyword, records them, and completes without a model call."""

    seen: dict = {}

    def __init__(self, **kwargs):
        KeywordRuntime.seen = kwargs
        self.store = kwargs["store"]

    async def start(self, prompt, model, limits):
        from physharness.execution import RuntimeCheckpoint, RuntimeResult, RuntimeSession

        session = RuntimeSession(runtime="responses", model=model, limits=limits)
        await self.store.save(RuntimeCheckpoint.build(session, {"source": "keyword fixture"}))
        session.status = "completed"
        await self.store.save(RuntimeCheckpoint.build(session, {"result": "Unresolved"}))
        return RuntimeResult(
            session=session, output_text="No proof; remaining assumptions need review."
        )


@pytest.mark.asyncio
async def test_executor_passes_shared_governor_and_role_priority(lab):
    from physharness.execution.admission import TokenRateGovernor
    from physharness.orchestration.research_worker import ResearchTaskExecutor

    service, actor, _, task = started_task(lab)
    governor = TokenRateGovernor(tokens_per_minute=1_000_000)
    executor = ResearchTaskExecutor(
        service, prices=PRICES, runtime_factory=KeywordRuntime, token_governor=governor
    )
    assert (await executor.execute(task["id"], actor.project_id))["status"] == "completed"
    assert KeywordRuntime.seen["token_governor"] is governor
    assert KeywordRuntime.seen["admission_priority"] == 0  # a root is on the critical path


def budgeted_task(lab):
    """A started experiment with ``context_budget`` set, and its root task."""
    from physharness.domain import ExperimentCreate

    service, actor, _ = lab
    _, problem = setup_experiment(lab)
    budgeted = service.create_experiment(
        ExperimentCreate(
            campaign_id=problem["campaign_id"],
            problem_id=problem["id"],
            models=[{"runtime": "responses", "model": "explicit-test-model"}],
            budget={"max_cost_usd": "1.00", "max_concurrency": 2, "max_runtime_seconds": 600},
            context_budget={"elide_every_turns": 8},
        ),
        actor,
        "budgeted-experiment",
    )
    return started_task(lab, budgeted)


@pytest.mark.asyncio
async def test_executor_passes_context_budget_and_digests_recall_tool(lab):
    from physharness.domain import digest_json
    from physharness.execution.responses import RECALL_OUTPUT_TOOL
    from physharness.orchestration.research_worker import ResearchTaskExecutor

    service, actor, experiment, task = budgeted_task(lab)
    executor = ResearchTaskExecutor(service, prices=PRICES, runtime_factory=KeywordRuntime)
    assert (await executor.execute(task["id"], actor.project_id))["status"] == "completed"
    assert KeywordRuntime.seen["context_budget"].elide_every_turns == 8
    record = service.list_records("session", actor, experiment["id"])[0]
    assert record["tool_definition_digest"] == digest_json(
        [*KeywordRuntime.seen["dispatcher"].definitions, RECALL_OUTPUT_TOOL]
    )


@pytest.mark.asyncio
async def test_executor_refuses_a_budget_the_runtime_cannot_apply(lab):
    from physharness.errors import HarnessError
    from physharness.orchestration.research_worker import ResearchTaskExecutor

    built = []

    class Unbudgeted(UsageRuntime):  # takes no context_budget keyword
        def __init__(self, store, dispatcher, event_sink):
            built.append(True)
            super().__init__(store, dispatcher, event_sink)

    service, actor, experiment, task = budgeted_task(lab)
    executor = ResearchTaskExecutor(service, prices=PRICES, runtime_factory=Unbudgeted)
    with pytest.raises(HarnessError) as refused:
        await executor.execute(task["id"], actor.project_id)
    # A budgeted arm never runs silently unbudgeted, and the refusal precedes any provider request.
    assert refused.value.code == "CONTEXT_BUDGET_UNSUPPORTED"
    assert built == []
    assert service.get_record("task", task["id"], actor)["status"] == "blocked"
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
