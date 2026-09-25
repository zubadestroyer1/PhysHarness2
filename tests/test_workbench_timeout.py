"""Local workbench TTL follows the remaining experiment deadline across handoffs."""

import os
from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_workspace_cas import StreamVM
from test_workspace_service import setup

from physharness.domain import utcnow
from physharness.errors import HarnessError
from physharness.orchestration.workspace_selection import configured_workspace_factory
from physharness.orchestration.workspace_tools import WorkspacePolicy
from physharness.orchestration.workspaces import WorkspaceBroker
from physharness.storage import LeaseRow

IMAGE = "sha256:" + "a" * 64


def _policy(service, experiment, actor, image=IMAGE):
    target = service.get_record("problem", experiment["problem_id"], actor)
    return WorkspacePolicy(
        template_id=image,
        environment_digest=target["environment_digest"],
        qualification_report_sha256="c" * 64,
        timeout_seconds=7200,
        cost_bound_usd="0",
        cost_source="local_no_external_invoice",
    )


def _factory(policy, host="unix:///tmp/physharness-dedicated.sock", max_active_workspaces=1):
    return configured_workspace_factory(
        SimpleNamespace(
            worker_workspace=policy,
            worker_workspace_provider="local_docker",
            worker_docker_host=host,
            worker_image_digest=policy.template_id,
            worker_workspace_quota_bytes=256 * 1024 * 1024,
            worker_max_active_workspaces=max_active_workspaces,
        )
    )


def _set_elapsed(service, experiment_id, actor, seconds):
    with service.db.transaction() as session:
        row = service._get(session, "experiment", experiment_id, actor)
        service._replace(
            session, row, {"started_at": (utcnow() - timedelta(seconds=seconds)).isoformat()}
        )


def _successor(service, task_id, actor):
    with service.db.transaction() as session:
        session.get(LeaseRow, task_id).expires_at = 0
    return service.acquire_task(task_id, "successor", 300, actor, "next-lease")


async def test_public_factory_clamps_local_timeout_and_restores_with_same_policy(lab, monkeypatch):
    import physharness.execution.local_docker as docker

    original, service, experiment, _, _, args = setup(lab, concurrency=1)
    task_id = args["task_id"]
    policy = _policy(service, experiment, original.actor)
    made = []

    class FakeDocker(StreamVM):
        def __init__(
            self,
            *,
            docker_host,
            image_digest,
            timeout_seconds,
            workspace_quota_bytes,
            max_active_workspaces,
            journal=None,
        ):
            super().__init__(journal, {"notes/source.txt": b"saved work"} if not made else {})
            self.template_id = image_digest
            self.timeout_seconds = timeout_seconds
            self.workspace_quota_bytes = workspace_quota_bytes
            self.max_active_workspaces = max_active_workspaces
            if journal is not None:
                made.append(self)

    monkeypatch.setattr(docker, "LocalDockerWorkspaceProvider", FakeDocker)
    factory = _factory(policy, max_active_workspaces=2)
    _set_elapsed(service, experiment["id"], original.actor, 5)
    first = factory(service, original.actor, task_id, args["holder"], args["fence"], None)
    source = await first._ensure()
    effective = source["effective_timeout_seconds"]
    assert source["provider_spec"]["timeout_seconds"] == 7200
    assert source["effective_provider_spec"]["timeout_seconds"] == effective
    assert 30 <= effective < experiment["budget"]["max_runtime_seconds"] - 5
    assert made[0].timeout_seconds == effective
    assert made[0].max_active_workspaces == 2
    ticket = await first.prepare_handoff("handoff")
    await first.close()
    lease = _successor(service, task_id, original.actor)
    successor = factory(service, original.actor, task_id, "successor", lease["fence"], None)
    restored = await successor.restore_handoff(ticket, "restore")
    assert restored["execution_id"] != source["execution_id"]
    assert made[1].files == {"notes/source.txt": b"saved work"}
    assert made[1].timeout_seconds == successor.workspace["effective_timeout_seconds"]
    assert made[1].timeout_seconds <= effective
    assert made[1].max_active_workspaces == 2
    assert ticket["workspace_policy_digest"]  # Requested policy remains stable.
    await successor.close()


async def test_near_deadline_rejects_local_allocation_before_provider_creation(lab, monkeypatch):
    import physharness.execution.local_docker as docker

    original, service, experiment, _, _, args = setup(lab)
    policy = _policy(service, experiment, original.actor)
    created = []

    class NeverCreate:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr(docker, "LocalDockerWorkspaceProvider", NeverCreate)
    factory = _factory(policy)
    created.clear()  # Configuration validation is read-only.
    duration = experiment["budget"]["max_runtime_seconds"]
    _set_elapsed(service, experiment["id"], original.actor, duration - 20)
    tools = factory(service, original.actor, args["task_id"], args["holder"], args["fence"], None)
    with pytest.raises(HarnessError) as raised:
        await tools._ensure()
    assert raised.value.code == "EXPERIMENT_DEADLINE"
    assert created == []
    assert service.ledger(experiment["id"], original.actor)["active_workers"] == 0


def test_local_factory_without_effective_timeout_contract_rejected_before_reservation(lab):
    original, service, experiment, _, _, args = setup(lab)
    args["provider_spec"] = {
        "provider": "local_docker",
        "template_id": IMAGE,
        "timeout_seconds": 7200,
    }
    args["provider_factory"] = lambda *, journal: None
    with pytest.raises(HarnessError) as raised:
        WorkspaceBroker(service, **args)
    assert raised.value.code == "PROVIDER_POLICY_MISMATCH"
    assert service.ledger(experiment["id"], original.actor)["active_workers"] == 0


@pytest.mark.integration
async def test_real_public_factory_deadline_and_fresh_restore(lab):
    host = os.environ.get("PHYSHARNESS_WORKBENCH_DOCKER_HOST")
    image = os.environ.get("PHYSHARNESS_WORKBENCH_IMAGE_DIGEST")
    if not host or not image:
        pytest.skip("Dedicated endpoint and pinned image required")
    original, service, experiment, _, _, args = setup(lab, concurrency=1)
    policy = _policy(service, experiment, original.actor, image=image)
    factory = _factory(policy, host=host)
    _set_elapsed(service, experiment["id"], original.actor, 5)
    first = factory(service, original.actor, args["task_id"], args["holder"], args["fence"], None)
    successor = None
    try:
        await first.write({"path": "notes/source.txt", "content": "saved work"}, "write")
        source = first.workspace
        assert source["effective_timeout_seconds"] < policy.timeout_seconds
        ticket = await first.prepare_handoff("handoff")
        await first.close()
        lease = _successor(service, args["task_id"], original.actor)
        successor = factory(
            service, original.actor, args["task_id"], "successor", lease["fence"], None
        )
        await successor.restore_handoff(ticket, "restore")
        restored = await successor.broker.download_file(
            successor.workspace["id"],
            expected_execution_id=successor.workspace["execution_id"],
            path="notes/source.txt",
            operation_id="read-restored",
        )
        assert restored["content_sha256"]
        assert (
            successor.workspace["effective_timeout_seconds"] <= source["effective_timeout_seconds"]
        )
    finally:
        if successor is not None and successor.workspace is not None:
            await successor.close()
        elif (
            first.workspace is not None
            and first.broker.inspect(first.workspace["id"])["status"] == "ready"
        ):
            await first.close()
