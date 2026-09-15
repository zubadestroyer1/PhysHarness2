import asyncio
import json
from types import SimpleNamespace

import pytest
from test_core import setup_experiment

from physharness.domain import BranchCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.execution.e2b import WorkspaceArchive
from physharness.execution.types import CommandRequest, CommandResult
from physharness.orchestration.workspaces import WorkspaceBroker
from physharness.storage import LeaseRow


class FakeVM:
    def __init__(self, journal, calls):
        self.journal, self.calls = journal, calls
        self.template_id = "qualified-template"
        self.timeout_seconds = 60
        self.network_disabled = True
        self.capabilities = SimpleNamespace(isolation="provider_vm", available=True)
        self.execution_id = "vm-123"
        self.files = {}
        self.fail_create = False
        self.fail_close = False
        self.after_create = None

    async def create(self):
        self.calls.append("create")
        if self.after_create:
            self.after_create()
        if self.fail_create:
            raise RuntimeError("uncertain provider response")
        return self

    async def run(self, request):
        self.calls.append("run")
        return CommandResult(
            operation_id=request.operation_id,
            execution_id=self.execution_id,
            exit_code=0,
            stdout="ok",
            stderr="",
        )

    async def upload_file(self, path, data, **kwargs):
        self.calls.append("upload")
        self.files[path] = data
        return WorkspaceArchive.build({path: data}).sha256

    async def export_workspace(self, **kwargs):
        self.calls.append("export")
        return WorkspaceArchive.build(self.files)

    async def close(self):
        self.calls.append("close")
        if self.fail_close:
            raise RuntimeError("destruction unknown")


def setup(lab, **kw):
    service, researcher, _ = lab
    experiment, _ = setup_experiment(lab, **kw)
    experiment = service.transition_experiment(
        experiment["id"], "start", experiment["revision"], researcher, "start-vm-experiment"
    )
    operator = Principal(id="vm-operator", project_id=researcher.project_id, role="operator")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="vm", objective="test"), researcher, "branch-vm"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="vm work"), researcher, "task-vm"
    )
    lease = service.acquire_task(task["id"], "holder", 300, operator, "lease-vm")
    calls, made = [], []

    def factory(*, journal):
        vm = FakeVM(journal, calls)
        made.append(vm)
        return vm

    args = dict(
        actor=operator,
        task_id=task["id"],
        holder="holder",
        fence=lease["fence"],
        provider_factory=factory,
        provider_spec={
            "provider": "e2b",
            "template_id": "qualified-template",
            "timeout_seconds": 60,
        },
    )
    return WorkspaceBroker(service, **args), service, experiment, calls, made, args


async def test_lifecycle_budget_replay_and_artifact(lab):
    b, s, e, calls, made, args = setup(lab)
    w = await b.provision(cost_bound_usd="0.25", operation_id="provision")
    assert calls == ["create"]
    assert s.ledger(e["id"], b.actor)["reserved_cost_usd"] == "0.25"
    assert s.ledger(e["id"], b.actor)["active_workers"] == 1
    assert (await b.provision(cost_bound_usd="0.25", operation_id="provision"))["id"] == w["id"]
    await b.upload_file(
        w["id"], expected_execution_id="vm-123", path="a", data=b"x", operation_id="u"
    )
    export = await b.export_workspace(w["id"], expected_execution_id="vm-123", operation_id="x")
    assert export["artifact"]["artifact_kind"] == "checkpoint"
    assert s.artifact_content(export["artifact"]["id"], b.actor)
    req = CommandRequest(operation_id="r", argv=["true"])
    await b.run(w["id"], expected_execution_id="vm-123", request=req)
    await b.run(w["id"], expected_execution_id="vm-123", request=req)
    assert calls.count("run") == 1
    done = await b.destroy(
        w["id"], expected_execution_id="vm-123", operation_id="d", actual_cost_usd="0.1"
    )
    assert done["status"] == "destroyed"
    ledger = s.ledger(e["id"], b.actor)
    assert ledger["active_workers"] == 0 and ledger["reserved_cost_usd"] == "0"
    assert ledger["spent_cost_usd"] == "0.1"


async def test_no_allocation_without_budget_or_changed_replay(lab):
    b, s, e, calls, made, args = setup(lab, cost="0.1")
    with pytest.raises(HarnessError, match="budget|envelope"):
        await b.provision(cost_bound_usd="0.2", operation_id="p")
    assert not calls
    await b.provision(cost_bound_usd="0.1", operation_id="p")
    with pytest.raises(HarnessError, match="different|changed"):
        await b.provision(cost_bound_usd="0.09", operation_id="p")
    assert calls == ["create"]


async def test_uncertain_create_holds_reservation_and_blocks_restart_replay(lab):
    b, s, e, calls, made, args = setup(lab)
    old = b.provider_factory

    def broken(**kwargs):
        vm = old(**kwargs)
        vm.fail_create = True
        return vm

    b.provider_factory = broken
    with pytest.raises(HarnessError, match="reconcil"):
        await b.provision(cost_bound_usd="0.2", operation_id="p")
    restarted = WorkspaceBroker(s, **args)
    with pytest.raises(HarnessError, match="reconcil"):
        await restarted.provision(cost_bound_usd="0.2", operation_id="p")
    assert calls == ["create"]
    assert s.ledger(e["id"], b.actor)["active_workers"] == 1
    assert s.ledger(e["id"], b.actor)["uncertain_operations"] == 1


async def test_lease_change_during_create_never_becomes_ready(lab):
    b, s, e, calls, made, args = setup(lab)
    old = b.provider_factory

    def change_lease():
        with s.db.transaction() as session:
            session.get(LeaseRow, b.task_id).fence += 1

    def factory(**kwargs):
        vm = old(**kwargs)
        vm.after_create = change_lease
        return vm

    b.provider_factory = factory
    with pytest.raises(HarnessError, match="reconcil"):
        await b.provision(cost_bound_usd="0.2", operation_id="p")
    w = s.list_records("workspace", b.actor, e["id"])[0]
    assert w["status"] == "reconciliation_required" and w["execution_id"] == "vm-123"
    assert s.ledger(e["id"], b.actor)["active_workers"] == 1


async def test_cancellation_blocks_execution_allows_fenced_cleanup(lab):
    b, s, e, calls, made, args = setup(lab)
    w = await b.provision(cost_bound_usd="0.2", operation_id="p")
    current = s.get_record("experiment", e["id"], b.actor)
    s.transition_experiment(e["id"], "cancel", current["revision"], b.actor, "cancel")
    with pytest.raises(HarnessError):
        await b.run(
            w["id"],
            expected_execution_id="vm-123",
            request=CommandRequest(operation_id="r", argv=["true"]),
        )
    with pytest.raises(HarnessError):
        await b.destroy(
            w["id"], expected_execution_id="wrong", operation_id="d", actual_cost_usd="0"
        )
    await b.destroy(
        w["id"], expected_execution_id="vm-123", operation_id="d", actual_cost_usd="0.1"
    )
    assert "run" not in calls and calls.count("close") == 1


async def test_uncertain_destroy_and_stale_cleanup_hold_reservation(lab):
    b, s, e, calls, made, args = setup(lab)
    w = await b.provision(cost_bound_usd="0.2", operation_id="p")
    made[0].fail_close = True
    with pytest.raises(HarnessError, match="reconcil"):
        await b.destroy(
            w["id"], expected_execution_id="vm-123", operation_id="d", actual_cost_usd="0.1"
        )
    assert s.ledger(e["id"], b.actor)["active_workers"] == 1
    with s.db.transaction() as session:
        session.get(LeaseRow, b.task_id).fence += 1
    with pytest.raises(HarnessError):
        await b.destroy(
            w["id"], expected_execution_id="vm-123", operation_id="d2", actual_cost_usd="0.1"
        )
    assert calls.count("close") == 1


async def test_concurrent_provision_and_concurrency_limit(lab):
    import asyncio

    b, s, e, calls, made, args = setup(lab, concurrency=1)
    entered, release = asyncio.Event(), asyncio.Event()
    old = b.provider_factory

    def factory(**kwargs):
        vm = old(**kwargs)
        original = vm.create

        async def create():
            entered.set()
            await release.wait()
            return await original()

        vm.create = create
        return vm

    b.provider_factory = factory
    first = asyncio.create_task(b.provision(cost_bound_usd="0.2", operation_id="p"))
    await entered.wait()
    try:
        with pytest.raises(HarnessError, match="reconcil"):
            await b.provision(cost_bound_usd="0.2", operation_id="p")
        with pytest.raises(HarnessError) as error:
            await b.provision(cost_bound_usd="0.2", operation_id="another")
        assert error.value.code == "CONCURRENCY_EXCEEDED"
    finally:
        release.set()
    await first
    assert calls == ["create"]


async def test_stale_fence_mid_run_and_destroy_cannot_commit_success(lab):
    b, s, e, calls, made, args = setup(lab)
    w = await b.provision(cost_bound_usd="0.2", operation_id="p")

    def stale():
        with s.db.transaction() as session:
            session.get(LeaseRow, b.task_id).fence += 1

    original = made[0].close

    async def close():
        await original()
        stale()

    made[0].close = close
    with pytest.raises(HarnessError, match="reconcil"):
        await b.destroy(
            w["id"], expected_execution_id="vm-123", operation_id="d", actual_cost_usd="0.1"
        )
    canonical = s.get_record("workspace", w["id"], b.actor)
    assert canonical["status"] == "reconciliation_required"
    assert canonical["destruction_confirmed"] is True
    ledger = s.ledger(e["id"], b.actor)
    assert ledger["reserved_cost_usd"] == "0.2" and ledger["active_workers"] == 1


async def test_canonical_native_journal_and_checkpoint_artifact(lab):
    from physharness.execution.e2b import NativeWorkspaceCheckpoint
    from physharness.execution.types import ExecutionError
    from physharness.orchestration.workspaces import CanonicalWorkspaceJournal

    b, s, e, calls, made, args = setup(lab)
    w = await b.provision(cost_bound_usd="0.2", operation_id="p")
    journal = made[0].journal
    assert journal.begin("e2b:vm-123", "pause-1", "pause", {"keep_memory": True}) is None
    with pytest.raises(HarnessError, match="reconcil"):
        journal.begin("e2b:vm-123", "pause-1", "pause", {"keep_memory": True})
    record = NativeWorkspaceCheckpoint.build(
        kind="pause", execution_id="vm-123", template_id="qualified-template"
    ).model_dump()
    journal.complete("e2b:vm-123", "pause-1", record)
    rebuilt = CanonicalWorkspaceJournal(WorkspaceBroker(s, **args), w["id"])
    assert rebuilt.begin("e2b:vm-123", "pause-1", "pause", {"keep_memory": True}) == record
    canonical = s.get_record("workspace", w["id"], b.actor)
    artifact = s.get_record("artifact", canonical["checkpoint_artifact_id"], b.actor)
    assert artifact["artifact_kind"] == "native_checkpoint"
    assert s.artifact_content(artifact["id"], b.actor)
    with pytest.raises(ExecutionError, match="reservation"):
        rebuilt.begin("e2b:vm-123", "fork", "fork", {})
    assert len(s.list_records("workspace_operation", b.actor, e["id"])) == 2


async def test_agent_cannot_construct_broker_or_forge_cross_task_workspace(lab):
    b, s, e, calls, made, args = setup(lab)
    agent = Principal(
        id="agent", role="agent", project_id=b.actor.project_id, experiment_id=e["id"]
    )
    with pytest.raises(HarnessError) as error:
        WorkspaceBroker(s, **{**args, "actor": agent})
    assert error.value.code == "FORBIDDEN"
    w = await b.provision(cost_bound_usd="0.2", operation_id="p")
    other = WorkspaceBroker(s, **{**args, "task_id": "other-task"})
    with pytest.raises(HarnessError):
        await other.destroy(
            w["id"], expected_execution_id="vm-123", operation_id="d", actual_cost_usd="0"
        )
    assert calls == ["create"]


async def test_replay_after_destruction_returns_current_workspace_state(lab):
    b, s, e, calls, made, args = setup(lab)
    w = await b.provision(cost_bound_usd="0.2", operation_id="p")
    await b.destroy(
        w["id"], expected_execution_id="vm-123", operation_id="d", actual_cost_usd="0.1"
    )
    replay = await b.provision(cost_bound_usd="0.2", operation_id="p")
    assert replay["status"] == "destroyed"
    assert calls == ["create", "close"]


async def test_vm_timeout_must_fit_remaining_experiment_runtime(lab):
    b, s, e, calls, made, args = setup(lab)
    b.provider_spec["timeout_seconds"] = 601
    with pytest.raises(HarnessError, match="runtime|deadline"):
        await b.provision(cost_bound_usd="0.2", operation_id="p")
    assert not calls
    assert s.ledger(e["id"], b.actor)["active_workers"] == 0


async def test_native_pending_journal_serializes_workspace_commands(lab):
    b, s, e, calls, made, args = setup(lab)
    w = await b.provision(cost_bound_usd="0.2", operation_id="p")
    journal = made[0].journal
    journal.begin("e2b:vm-123", "native", "pause", {})
    with pytest.raises(HarnessError):
        await b.run(
            w["id"],
            expected_execution_id="vm-123",
            request=CommandRequest(operation_id="r", argv=["true"]),
        )
    assert calls == ["create"]


async def test_no_success_from_lost_fence_mid_command(lab):
    b, s, e, calls, made, args = setup(lab)
    w = await b.provision(cost_bound_usd="0.2", operation_id="p")
    original = made[0].run

    async def run(request):
        result = await original(request)
        with s.db.transaction() as session:
            session.get(LeaseRow, b.task_id).fence += 1
        return result

    made[0].run = run
    with pytest.raises(HarnessError, match="reconcil"):
        await b.run(
            w["id"],
            expected_execution_id="vm-123",
            request=CommandRequest(operation_id="r", argv=["true"]),
        )
    op = [
        r for r in s.list_records("workspace_operation", b.actor, e["id"]) if r["command"] == "run"
    ][0]
    assert op["status"] == "reconciliation_required" and op["result"] is None


async def test_exact_provider_spec_bound_and_zero_cost_not_assumed(lab):
    b, s, e, calls, made, args = setup(lab)
    with pytest.raises(HarnessError, match="positive"):
        await b.provision(cost_bound_usd="0", operation_id="zero")
    await b.provision(cost_bound_usd="0.2", operation_id="p")
    other = WorkspaceBroker(
        s, **{**args, "provider_spec": {**args["provider_spec"], "template_id": "different"}}
    )
    with pytest.raises(HarnessError, match="different"):
        await other.provision(cost_bound_usd="0.2", operation_id="p")
    assert calls == ["create"]


async def test_database_failure_after_allocation_retains_known_identity(lab, monkeypatch):
    b, s, e, calls, made, args = setup(lab)
    replace = s._replace

    def unavailable(*args, **kwargs):
        raise OSError("database unavailable")

    monkeypatch.setattr(s, "_replace", unavailable)
    with pytest.raises(HarnessError, match="vm-123") as error:
        await b.provision(cost_bound_usd="0.2", operation_id="p")
    assert error.value.code == "WORKSPACE_RECONCILIATION_REQUIRED"
    observation = next(iter(b.reconciliation_observations.values()))
    assert observation["execution_id"] == "vm-123"
    monkeypatch.setattr(s, "_replace", replace)
    with pytest.raises(HarnessError, match="reconcil"):
        await b.provision(cost_bound_usd="0.2", operation_id="p")
    assert calls == ["create"] and s.ledger(e["id"], b.actor)["active_workers"] == 1


async def test_shared_controller_slot_avoids_double_count_and_is_not_settled_by_vm(lab):
    b, s, e, calls, made, args = setup(lab, concurrency=1)
    slot = s.reserve_resources(e["id"], "0", 1, b.actor, "controller-slot")
    with s.db.transaction() as session:
        s._fenced(session, b.task_id, b.holder, b.fence)
        row = s._get(session, "task", b.task_id, b.actor)
        s._replace(session, row, {"worker_slot_id": slot["id"]})
    shared = WorkspaceBroker(s, **args, worker_slot_id=slot["id"])
    w = await shared.provision(cost_bound_usd="0.2", operation_id="p")
    assert w["shared_worker_slot_id"] == slot["id"]
    assert s.ledger(e["id"], b.actor)["active_workers"] == 1
    with pytest.raises(HarnessError, match="workspace|slot"):
        await shared.provision(cost_bound_usd="0.2", operation_id="second")
    await shared.destroy(
        w["id"], expected_execution_id="vm-123", operation_id="d", actual_cost_usd="0.1"
    )
    assert s.ledger(e["id"], b.actor)["active_workers"] == 1
    assert shared.inspect(w["id"])["status"] == "destroyed"
    s.settle_resources(slot["id"], "0", False, b.actor, "controller-slot-settle")
    assert s.ledger(e["id"], b.actor)["active_workers"] == 0


async def test_shared_slot_requires_canonical_binding_active_reservation_and_fence(lab):
    b, s, e, calls, made, args = setup(lab)
    slot = s.reserve_resources(e["id"], "0", 1, b.actor, "slot")
    forged = WorkspaceBroker(s, **args, worker_slot_id=slot["id"])
    with pytest.raises(HarnessError, match="slot"):
        await forged.provision(cost_bound_usd="0.2", operation_id="p")
    with s.db.transaction() as session:
        row = s._get(session, "task", b.task_id, b.actor)
        s._replace(session, row, {"worker_slot_id": slot["id"]})
    s.settle_resources(slot["id"], None, True, b.actor, "slot-uncertain")
    with pytest.raises(HarnessError, match="slot"):
        await forged.provision(cost_bound_usd="0.2", operation_id="p")
    assert not calls


async def test_confirmed_destroy_releases_capacity_but_unknown_billing_stays_reserved(lab):
    b, service, experiment, _, _, _ = setup(lab, concurrency=1)
    workspace = await b.provision(cost_bound_usd="0.2", operation_id="p")
    result = await b.destroy(
        workspace["id"],
        expected_execution_id="vm-123",
        operation_id="destroy",
        actual_cost_usd=None,
    )
    assert result["status"] == "destroyed"
    assert result["billing_status"] == "unreconciled"
    ledger = service.ledger(experiment["id"], b.actor)
    assert ledger["active_workers"] == 0
    assert ledger["reserved_cost_usd"] == "0.2"
    assert ledger["uncertain_operations"] == 1
    service.settle_resources(workspace["reservation_id"], "0.15", False, b.actor, "invoice")
    assert service.ledger(experiment["id"], b.actor)["active_workers"] == 0


async def test_definite_transfer_refusal_is_replayed_without_quarantine(lab):
    from physharness.execution import ExecutionError

    broker, service, experiment, calls, providers, _ = setup(lab)
    workspace = await broker.provision(cost_bound_usd="0.2", operation_id="p")
    refusals = []

    async def refuse(**kwargs):
        refusals.append(True)
        raise ExecutionError("WORKSPACE_TRANSFER_REJECTED", "definite helper refusal")

    providers[0].export_workspace = refuse
    for _ in range(2):
        with pytest.raises(HarnessError) as error:
            await broker.export_workspace(
                workspace["id"], expected_execution_id="vm-123", operation_id="export"
            )
        assert error.value.code == "WORKSPACE_TRANSFER_REJECTED"
    assert len(refusals) == 1
    assert broker.inspect(workspace["id"])["status"] == "ready"
    await broker.destroy(
        workspace["id"],
        expected_execution_id="vm-123",
        operation_id="destroy",
        actual_cost_usd=None,
    )
    assert service.ledger(experiment["id"], broker.actor)["active_workers"] == 0


@pytest.mark.parametrize("confirmed", [True, False])
async def test_provider_cleanup_evidence_is_preserved_without_invented_billing(lab, confirmed):
    from physharness.execution import ExecutionError

    broker, service, experiment, _, providers, _ = setup(lab, concurrency=1)
    workspace = await broker.provision(cost_bound_usd="0.2", operation_id="p")

    async def fail(request):
        providers[0].last_execution_observation = {
            "execution_id": "vm-123",
            "destruction_confirmed": confirmed,
        }
        raise ExecutionError("TIMEOUT", "Actual cleanup observation supplied by adapter")

    providers[0].run = fail
    with pytest.raises(HarnessError):
        await broker.run(
            workspace["id"],
            expected_execution_id="vm-123",
            request=CommandRequest(argv=["long-task"], operation_id="timeout"),
        )
    observed = broker.inspect(workspace["id"])
    assert observed["destruction_confirmed"] is confirmed
    assert observed["status"] == ("destroyed" if confirmed else "reconciliation_required")
    assert service.ledger(experiment["id"], broker.actor)["active_workers"] == (
        0 if confirmed else 1
    )
    assert service.ledger(experiment["id"], broker.actor)["spent_cost_usd"] == "0"
    assert service.ledger(experiment["id"], broker.actor)["uncertain_operations"] == 1


@pytest.mark.parametrize("checkpoint_kind", ["archive", "native"])
async def test_checkpoint_upload_outliving_lease_cannot_publish(lab, monkeypatch, checkpoint_kind):
    from datetime import timedelta

    from physharness import collaboration
    from physharness.domain import utcnow
    from physharness.execution.e2b import NativeWorkspaceCheckpoint
    from physharness.orchestration.workspaces import CanonicalWorkspaceJournal

    broker, service, experiment, _, _, _ = setup(lab)
    workspace = await broker.provision(cost_bound_usd="0.2", operation_id="p")
    clock = [utcnow()]
    monkeypatch.setattr(collaboration, "utcnow", lambda: clock[0])
    original_put = service.artifacts.put

    def outlive_lease(data):
        result = original_put(data)
        # Simulate the external artifact upload consuming the remaining lease.
        clock[0] += timedelta(seconds=301)
        return result

    monkeypatch.setattr(service.artifacts, "put", outlive_lease)
    with pytest.raises(HarnessError):
        if checkpoint_kind == "archive":
            await broker.export_workspace(
                workspace["id"], expected_execution_id="vm-123", operation_id="checkpoint"
            )
        else:
            journal = CanonicalWorkspaceJournal(broker, workspace["id"])
            journal.begin("e2b:vm-123", "checkpoint", "pause", {})
            checkpoint = NativeWorkspaceCheckpoint.build(
                kind="pause", execution_id="vm-123", template_id="qualified-template"
            )
            journal.complete("e2b:vm-123", "checkpoint", checkpoint.model_dump(mode="json"))
    assert service.list_records("artifact", broker.actor, experiment["id"]) == []
    assert broker.inspect(workspace["id"])["checkpoint_artifact_id"] is None
    operations = service.list_records("workspace_operation", broker.actor, experiment["id"])
    assert all(op["status"] != "completed" for op in operations if op["command"] != "provision")
    assert service.ledger(experiment["id"], broker.actor)["active_workers"] == 1


@pytest.mark.parametrize("stage", ["provision", "run"])
@pytest.mark.parametrize("stop", ["timeout", "interrupt"])
async def test_runtime_cancellation_through_workspace_stops_generation(lab, tmp_path, stage, stop):
    from test_execution_responses import client_for, message, response

    from physharness.execution import (
        ExecutionError,
        ModelConfig,
        ResponsesRuntime,
        RuntimeLimits,
        SQLiteRuntimeStore,
    )
    from physharness.orchestration.research_worker import research_tools
    from physharness.orchestration.workspace_tools import WorkspacePolicy, WorkspaceTools

    broker, service, experiment, calls, providers, _ = setup(lab)
    target = service.get_record("problem", experiment["problem_id"], broker.actor)
    workspace_tools = WorkspaceTools(
        broker,
        WorkspacePolicy(
            template_id="qualified-template",
            environment_digest=target["environment_digest"],
            qualification_report_sha256="a" * 64,
            timeout_seconds=60,
            cost_bound_usd="0.2",
            cost_source="test fixture only",
        ),
    )
    entered = asyncio.Event()

    async def stalled(*args):
        entered.set()
        await asyncio.Event().wait()

    if stage == "run":
        await workspace_tools._ensure()
        providers[0].run = stalled
    else:
        factory = broker.provider_factory

        def stalled_factory(**kwargs):
            vm = factory(**kwargs)
            vm.create = stalled
            return vm

        broker.provider_factory = stalled_factory
    task = service.get_record("task", broker.task_id, broker.actor)
    agent = Principal(
        id="holder",
        project_id=broker.actor.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=task["branch_id"],
    )
    dispatcher = research_tools(service, agent, task["branch_id"], workspace_tools=workspace_tools)
    call = {
        "id": "fc_1",
        "type": "function_call",
        "call_id": "call_1",
        "name": "run_command",
        "status": "completed",
        "arguments": json.dumps({"argv": ["sleep", "10"], "cwd": ".", "timeout_seconds": 30}),
    }
    requests = []
    client = client_for(
        [response([call]), response([message("must never generate")], response_id="resp_2")],
        requests,
    )
    store = SQLiteRuntimeStore(tmp_path / "runtime-cancel.db")
    runtime = ResponsesRuntime(store=store, dispatcher=dispatcher, client=client)
    running = asyncio.create_task(
        runtime.start(
            "run",
            ModelConfig(model="exact-model"),
            RuntimeLimits(timeout_seconds=1 if stop == "timeout" else 10),
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        session_id = next(iter(runtime._active))
        if stop == "interrupt":
            assert await runtime.interrupt(session_id)
            with pytest.raises(asyncio.CancelledError):
                await running
        else:
            with pytest.raises(ExecutionError) as error:
                await running
            assert error.value.code == "TIMEOUT"
        checkpoint = await runtime.checkpoint(session_id)
        assert checkpoint.session.status == "uncertain"
        assert checkpoint.native_state["pending_operation"]
        assert len([url for url, _ in requests if not url.endswith("/input_tokens")]) == 1
        workspace = service.list_records("workspace", broker.actor, experiment["id"])[0]
        assert workspace["status"] == "reconciliation_required"
        assert workspace["execution_id"] == "vm-123"
        ledger = service.ledger(experiment["id"], broker.actor)
        assert ledger["reserved_cost_usd"] == "0.2"
        assert ledger["active_workers"] == 1 and ledger["uncertain_operations"] == 1
    finally:
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        await client.close()
        store.close()


@pytest.mark.parametrize("stage", ["provision", "run"])
@pytest.mark.parametrize("persistence_fails", [False, True])
@pytest.mark.parametrize("handle_retained", [False, True])
async def test_original_cancellation_survives_observation_failures(
    lab, monkeypatch, stage, persistence_fails, handle_retained
):
    broker, service, experiment, _, providers, _ = setup(lab)
    cancellation = asyncio.CancelledError("operator cancelled")

    async def cancel(*args):
        if not handle_retained:
            providers[0].execution_id = None
            providers[0].last_execution_observation = {
                "execution_id": "vm-123",
                "destruction_confirmed": stage == "run",
            }
        raise cancellation

    if stage == "run":
        workspace = await broker.provision(cost_bound_usd="0.2", operation_id="p")
        providers[0].run = cancel
        providers[0].last_execution_observation = {
            "execution_id": "vm-123",
            "destruction_confirmed": True,
        }
        call = broker.run(
            workspace["id"],
            expected_execution_id="vm-123",
            request=CommandRequest(argv=["true"], operation_id="run"),
        )
    else:
        factory = broker.provider_factory

        def cancelling_factory(**kwargs):
            vm = factory(**kwargs)
            vm.create = cancel
            return vm

        broker.provider_factory = cancelling_factory
        call = broker.provision(cost_bound_usd="0.2", operation_id="p")

    def fail(*args, **kwargs):
        raise OSError("uncertainty persistence unavailable")

    if persistence_fails:
        monkeypatch.setattr(broker, "_record_uncertainty", fail)
    with pytest.raises(asyncio.CancelledError) as error:
        await call
    assert error.value is cancellation
    observed = next(iter(broker.reconciliation_observations.values()))
    assert observed["execution_id"] == "vm-123"
    assert observed["destruction_confirmed"] is (stage == "run")
    if persistence_fails:
        assert "Cannot persist reconciliation" in cancellation.__notes__[0]
    else:
        workspace = broker.inspect(observed["workspace_id"])
        assert workspace["status"] == "reconciliation_required"
        assert workspace["destruction_confirmed"] is (stage == "run")
    ledger = service.ledger(experiment["id"], broker.actor)
    assert ledger["reserved_cost_usd"] == "0.2" and ledger["spent_cost_usd"] == "0"
