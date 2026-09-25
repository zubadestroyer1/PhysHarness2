import pytest
from test_workspace_service import FakeVM, setup

from physharness.errors import HarnessError
from physharness.execution.types import CommandRequest, ExecutionError
from physharness.orchestration.workspaces import WorkspaceBroker


async def test_known_uncreated_capacity_rejection_releases_reservation(lab):
    old, service, experiment, calls, _, args = setup(lab)

    class Busy(FakeVM):
        def __init__(self, journal):
            super().__init__(journal, calls)
            self.template_id = "sha256:" + "a" * 64
            self._container_id = None
            self._quarantined = False

        async def create(self):
            raise ExecutionError("WORKSPACE_CAPACITY", "At most one active workbench")

    args["provider_spec"] = {
        "provider": "local_docker",
        "template_id": "sha256:" + "a" * 64,
        "timeout_seconds": 60,
    }

    def factory(*, journal, timeout_seconds):
        provider = Busy(journal)
        provider.timeout_seconds = timeout_seconds
        return provider

    args["provider_factory"] = factory
    broker = WorkspaceBroker(service, **args)
    with pytest.raises(HarnessError) as err:
        await broker.provision(cost_bound_usd="0", operation_id="capacity")
    assert err.value.code == "WORKSPACE_CAPACITY"
    ledger = service.ledger(experiment["id"], broker.actor)
    assert ledger["active_workers"] == 0
    assert ledger["uncertain_operations"] == 0


async def test_predispatch_command_rejection_leaves_workspace_ready(lab):
    broker, service, experiment, calls, made, args = setup(lab)
    original = broker.provider_factory

    class Checked(FakeVM):
        def validate_command(self, request):
            if request.cwd != ".":
                raise ExecutionError("UNSAFE_PATH", "bad cwd")
            if request.env:
                raise ExecutionError("UNSAFE_RUNTIME", "bad environment")
            if request.timeout_seconds > self.timeout_seconds:
                raise ExecutionError("TIMEOUT_LIMIT", "bad deadline")

    def factory(**kwargs):
        base = original(**kwargs)
        return Checked(base.journal, calls)

    broker.provider_factory = factory
    workspace = await broker.provision(cost_bound_usd="0.1", operation_id="p")
    for request in (
        CommandRequest(operation_id="bad-cwd", argv=["true"], cwd="/outside"),
        CommandRequest(operation_id="bad-env", argv=["true"], env={"X": "1"}),
        CommandRequest(operation_id="bad-timeout", argv=["true"], timeout_seconds=61),
    ):
        with pytest.raises(HarnessError) as error:
            await broker.run(workspace["id"], expected_execution_id="vm-123", request=request)
        assert error.value.code in {"UNSAFE_PATH", "UNSAFE_RUNTIME", "TIMEOUT_LIMIT"}
        current = service.get_record("workspace", workspace["id"], broker.actor)
        assert current["status"] == "ready" and current["active_operation_id"] is None
        assert service.ledger(experiment["id"], broker.actor)["uncertain_operations"] == 0
    assert (
        service.list_records("workspace_operation", broker.actor, experiment["id"])[0]["command"]
        == "provision"
    )
    await broker.run(
        workspace["id"],
        expected_execution_id="vm-123",
        request=CommandRequest(operation_id="good", argv=["true"]),
    )
    assert calls.count("run") == 1


async def test_unknown_error_after_dispatch_still_requires_reconciliation(lab):
    broker, service, experiment, calls, made, args = setup(lab)
    original = broker.provider_factory

    class Unknown(FakeVM):
        def validate_command(self, request):
            return None

        async def run(self, request):
            raise RuntimeError("provider outcome unknown")

    def factory(**kwargs):
        base = original(**kwargs)
        return Unknown(base.journal, calls)

    broker.provider_factory = factory
    workspace = await broker.provision(cost_bound_usd="0.1", operation_id="p")
    with pytest.raises(HarnessError) as error:
        await broker.run(
            workspace["id"],
            expected_execution_id="vm-123",
            request=CommandRequest(operation_id="unknown", argv=["true"]),
        )
    assert error.value.code == "WORKSPACE_RECONCILIATION_REQUIRED"
    assert (
        service.get_record("workspace", workspace["id"], broker.actor)["status"]
        == "reconciliation_required"
    )
    assert service.ledger(experiment["id"], broker.actor)["uncertain_operations"] >= 1
