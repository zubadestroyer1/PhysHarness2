"""Fenced workspace export and fresh-VM restore across a task handoff."""

import pytest
from test_workspace_service import FakeVM, setup

from physharness.domain import Principal
from physharness.errors import HarnessError
from physharness.execution.e2b import WorkspaceArchive
from physharness.orchestration.workspace_tools import WorkspacePolicy, WorkspaceTools
from physharness.orchestration.workspaces import WorkspaceBroker
from physharness.storage import LeaseRow


class StatefulVM(FakeVM):
    def __init__(self, journal, calls, execution_id):
        super().__init__(journal, calls)
        self.execution_id = execution_id

    async def restore_workspace(self, archive, *, expected_execution_id):
        assert expected_execution_id == self.execution_id
        self.calls.append("restore")
        self.files = archive.files()


async def test_handoff_archives_workspace_and_restores_bytes_to_fresh_vm(lab):
    first_broker, service, experiment, calls, _, args = setup(lab, concurrency=1)
    task = service.get_record("task", args["task_id"], first_broker.actor)
    problem = service.get_record("problem", experiment["problem_id"], first_broker.actor)
    policy = WorkspacePolicy(
        template_id="qualified-template",
        environment_digest=problem["environment_digest"],
        qualification_report_sha256="a" * 64,
        timeout_seconds=60,
        cost_bound_usd="0.25",
        cost_source="test",
    )
    made = []

    def factory(*, journal):
        vm = StatefulVM(journal, calls, f"vm-{len(made) + 1}")
        made.append(vm)
        return vm

    first_broker.provider_factory = factory
    first = WorkspaceTools(first_broker, policy)
    await first.write(
        {"path": "research/lemma.lean", "content": "theorem lemma : True := by trivial"}, "write"
    )
    assert (await first.prepare_handoff("handoff"))["source_execution_id"] == "vm-1"
    ticket = await first.prepare_handoff("handoff")
    assert ticket["artifact_id"]
    assert ticket["environment_digest"] == policy.environment_digest
    assert ticket["template_id"] == policy.template_id
    with pytest.raises(HarnessError) as reused:
        await first.restore_handoff(ticket, "reuse-source")
    assert reused.value.code == "WORKSPACE_IDENTITY_MISMATCH"
    assert calls == ["create", "upload", "export"]
    await first.close()

    with service.db.transaction() as session:
        session.get(LeaseRow, task["id"]).expires_at = 0
    next_lease = service.acquire_task(
        task["id"], "successor", 300, first_broker.actor, "next-lease"
    )
    successor = WorkspaceTools(
        WorkspaceBroker(
            service,
            actor=Principal(
                id="vm-operator", project_id=first_broker.actor.project_id, role="operator"
            ),
            task_id=task["id"],
            holder="successor",
            fence=next_lease["fence"],
            provider_factory=factory,
            provider_spec=args["provider_spec"],
        ),
        policy,
    )
    restored = await successor.restore_handoff(ticket, "restore-handoff")
    assert restored["execution_id"] == "vm-2"
    assert made[1].files == {"research/lemma.lean": b"theorem lemma : True := by trivial"}
    exported = await successor.checkpoint({}, "export-restored")
    archive = WorkspaceArchive.from_bytes(
        service.artifact_content(exported["artifact"]["id"], successor.broker.actor),
        sha256=exported["archive_sha256"],
    )
    assert archive.files() == made[0].files
    assert calls == ["create", "upload", "export", "close", "create", "restore", "export"]
    await successor.close()


async def test_handoff_rejects_mismatched_policy_before_vm_allocation(lab):
    broker, service, experiment, calls, _, _ = setup(lab)
    problem = service.get_record("problem", experiment["problem_id"], broker.actor)
    policy = WorkspacePolicy(
        template_id="qualified-template",
        environment_digest=problem["environment_digest"],
        qualification_report_sha256="a" * 64,
        timeout_seconds=60,
        cost_bound_usd="0.25",
        cost_source="test",
    )
    tools = WorkspaceTools(broker, policy)
    assert await tools.prepare_handoff("unused") is None
    with pytest.raises(HarnessError) as error:
        await tools.restore_handoff(
            {
                "artifact_id": "untrusted",
                "archive_sha256": "0" * 64,
                "source_execution_id": "old",
                "environment_digest": policy.environment_digest,
                "qualification_report_sha256": "b" * 64,
                "template_id": policy.template_id,
                "workspace_policy_digest": "0" * 64,
            },
            "restore",
        )
    assert error.value.code == "WORKSPACE_HANDOFF_MISMATCH"
    assert calls == []
