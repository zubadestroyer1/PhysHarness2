"""Opt-in real Docker check of the broker's pre-dispatch rejection boundary.

Requires the dedicated workbench socket and pinned image. This uses no model API.
"""

import base64
import os

import pytest
from test_workspace_service import setup

from physharness.errors import HarnessError
from physharness.execution.local_docker import LocalDockerWorkspaceProvider
from physharness.execution.types import CommandRequest
from physharness.orchestration.workspaces import WorkspaceBroker


@pytest.mark.integration
async def test_real_broker_rejects_bad_paths_then_runs_valid_lean(lab):
    host = os.environ.get("PHYSHARNESS_WORKBENCH_DOCKER_HOST")
    image = os.environ.get("PHYSHARNESS_WORKBENCH_IMAGE_DIGEST")
    if not host or not image:
        pytest.skip("Dedicated workbench endpoint and image digest are required")

    fixture_broker, service, experiment, _, _, args = setup(lab, concurrency=1)
    providers = []

    def provider_factory(*, journal, timeout_seconds):
        provider = LocalDockerWorkspaceProvider(
            docker_host=host,
            image_digest=image,
            timeout_seconds=timeout_seconds,
            journal=journal,
        )
        providers.append(provider)
        return provider

    broker = WorkspaceBroker(
        service,
        actor=fixture_broker.actor,
        task_id=fixture_broker.task_id,
        holder=fixture_broker.holder,
        fence=fixture_broker.fence,
        provider_factory=provider_factory,
        provider_spec={"provider": "local_docker", "template_id": image, "timeout_seconds": 180},
    )
    workspace = None
    try:
        workspace = await broker.provision(cost_bound_usd="0", operation_id="real-provision")
        execution_id = workspace["execution_id"]
        before = len(service.list_records("workspace_operation", broker.actor, experiment["id"]))

        async def rejected(call, code="UNSAFE_PATH"):
            with pytest.raises(HarnessError) as error:
                await call()
            assert error.value.code == code
            current = broker.inspect(workspace["id"])
            assert current["status"] == "ready"
            assert current["active_operation_id"] is None
            operations = service.list_records("workspace_operation", broker.actor, experiment["id"])
            assert len(operations) == before
            assert service.ledger(experiment["id"], broker.actor)["uncertain_operations"] == 0
            assert providers[0]._container_id == execution_id

        await rejected(
            lambda: broker.run(
                workspace["id"],
                expected_execution_id=execution_id,
                request=CommandRequest(
                    operation_id="bad-cwd",
                    argv=["python3", "-c", "print('not dispatched')"],
                    cwd="/work",
                ),
            )
        )
        for index, path in enumerate(("/work/Bad.lean", "../Bad.lean")):
            await rejected(
                lambda path=path, index=index: broker.upload_file(
                    workspace["id"],
                    expected_execution_id=execution_id,
                    path=path,
                    data=b"not dispatched",
                    operation_id=f"bad-upload-{index}",
                )
            )
            await rejected(
                lambda path=path, index=index: broker.read_workspace_range(
                    workspace["id"],
                    expected_execution_id=execution_id,
                    path=path,
                    offset=0,
                    length=20,
                    operation_id=f"bad-read-{index}",
                )
            )

        source = b"import Mathlib\n#check Nat.add_comm\n"
        await broker.upload_file(
            workspace["id"],
            expected_execution_id=execution_id,
            path="scratch/Check.lean",
            data=source,
            operation_id="valid-upload",
        )
        read = await broker.read_workspace_range(
            workspace["id"],
            expected_execution_id=execution_id,
            path="scratch/Check.lean",
            offset=0,
            length=len(source),
            operation_id="valid-read",
        )
        assert base64.b64decode(read["data"]) == source
        lean = await broker.run(
            workspace["id"],
            expected_execution_id=execution_id,
            request=CommandRequest(
                operation_id="valid-lean",
                argv=["lake", "--offline", "env", "lean", "/work/scratch/Check.lean"],
                cwd="/opt/sources/physlib",
                timeout_seconds=90,
            ),
        )
        assert lean["exit_code"] == 0, lean["stderr"]
        assert "Nat.add_comm" in lean["stdout"]
        destroyed = await broker.destroy(
            workspace["id"],
            expected_execution_id=execution_id,
            operation_id="real-destroy",
            actual_cost_usd="0",
        )
        assert destroyed["status"] == "destroyed"
        ledger = service.ledger(experiment["id"], broker.actor)
        assert ledger["active_workers"] == 0
        assert ledger["reserved_cost_usd"] == "0"
        assert ledger["uncertain_operations"] == 0
    finally:
        for provider in providers:
            await provider.close()
