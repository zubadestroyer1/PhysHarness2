"""Controller/VM ordering tests; scripted runtime and VM, never a live fleet run."""

import pytest
from test_core import setup_experiment
from test_workspace_service import FakeVM

from physharness.domain import BranchCreate, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import RuntimeResult, RuntimeSession
from physharness.orchestration.research_worker import ResearchTaskExecutor
from physharness.orchestration.workspace_tools import WorkspacePolicy, WorkspaceTools
from physharness.orchestration.workspaces import WorkspaceBroker


@pytest.mark.parametrize("fail_cleanup", [False, True])
async def test_vm_cleanup_precedes_lease_release_and_uncertainty_retains_slot(lab, fail_cleanup):
    service, actor, _ = lab
    experiment, problem = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Research", objective="Explore"), actor, "branch"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Use scientific VM"), actor, "task"
    )
    calls = []
    policy = WorkspacePolicy(
        template_id="qualified-template",
        environment_digest=problem["environment_digest"],
        qualification_report_sha256="a" * 64,
        timeout_seconds=60,
        cost_bound_usd="0.2",
        cost_source="synthetic test bound",
    )

    def vm_factory(service, actor, task_id, holder, fence, worker_slot_id):
        def provider_factory(*, journal):
            vm = FakeVM(journal, calls)
            vm.fail_close = fail_cleanup
            return vm

        broker = WorkspaceBroker(
            service,
            actor=actor,
            task_id=task_id,
            holder=holder,
            fence=fence,
            worker_slot_id=worker_slot_id,
            provider_factory=provider_factory,
            provider_spec={
                "provider": "e2b",
                "template_id": "qualified-template",
                "timeout_seconds": 60,
            },
        )
        return WorkspaceTools(broker, policy)

    class ScriptedRuntime:
        def __init__(self, store, dispatcher, event_sink):
            self.dispatcher = dispatcher

        async def start(self, prompt, model, limits):
            output = await self.dispatcher.dispatch(
                "run_command",
                {"argv": ["lean", "Candidate.lean"], "cwd": ".", "timeout_seconds": 10},
                "command",
            )
            assert output["exit_code"] == 0
            return RuntimeResult(
                session=RuntimeSession(runtime="responses", model=model, limits=limits),
                output_text="Unverified exploration; formal acceptance still required.",
            )

    executor = ResearchTaskExecutor(
        service,
        prices={
            "explicit-test-model": {"input_usd_per_million": "1", "output_usd_per_million": "1"}
        },
        runtime_factory=ScriptedRuntime,
        workspace_factory=vm_factory,
    )
    if fail_cleanup:
        with pytest.raises(HarnessError):
            await executor.execute(task["id"], actor.project_id)
        assert service.ledger(experiment["id"], actor)["active_workers"] == 1
        assert service.get_record("task", task["id"], actor)["status"] == "blocked"
    else:
        result = await executor.execute(task["id"], actor.project_id)
        assert result["status"] == "completed"
        assert service.ledger(experiment["id"], actor)["active_workers"] == 0
        assert service.ledger(experiment["id"], actor)["uncertain_operations"] == 1
        assert service.list_records("claim", actor) == []
    assert calls == ["create", "run", "close"]
