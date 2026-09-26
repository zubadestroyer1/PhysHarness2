"""Required handoff workspace cannot disappear behind a changed policy."""

import httpx
import pytest
from openai import AsyncOpenAI
from test_controller_continuation import response
from test_core import setup_experiment
from test_research_loop_integration import PRICES, tool_call

from physharness.domain import BranchCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import ResponsesRuntime
from physharness.orchestration.research_worker import ResearchTaskExecutor


async def test_changed_policy_preserves_ticket_and_does_not_call_model(lab):
    service, researcher, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, researcher, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), researcher, "branch"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), researcher, "task"
    )
    calls = 0

    async def route(request):
        nonlocal calls
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        calls += 1
        if calls != 1:
            raise AssertionError("Model must not be called after incompatible workspace ticket")
        return httpx.Response(
            200,
            json=response([tool_call("request_handoff", {"reason": "continue research"}, "yield")]),
        )

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )

    def runtime_factory(**kwargs):
        return ResponsesRuntime(client=client, **kwargs)

    first = ResearchTaskExecutor(service, prices=PRICES, runtime_factory=runtime_factory)
    assert (await first.execute(task["id"], researcher.project_id))["status"] == "continuation"
    controller = Principal(
        id="research-controller", project_id=researcher.project_id, role="operator"
    )
    saved = service.get_record("task", task["id"], controller)["ready_continuation"]
    source_artifact_id = next(
        row["checkpoint_artifact_id"]
        for row in service.list_records("session", controller, experiment["id"])
        if row["native_record_id"] == saved["source_session_id"]
    )
    ticket = {"artifact_id": "saved-checkpoint", "archive_sha256": "f" * 64}
    with service.db.transaction() as session:
        row = service._get(session, "task", task["id"], controller)
        service._replace(
            session, row, {"ready_continuation": {**saved, "workspace_ticket": ticket}}
        )

    class WorkspaceStub:
        workspace = None

        def __init__(self):
            self.policy = self

        def model_dump(self, *, mode):
            return {"template_id": "different", "environment_digest": "a" * 64}

        async def close(self):
            return None

        def unresolved(self):
            return []

    stub = WorkspaceStub()
    successor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=runtime_factory,
        workspace_factory=lambda *args: stub,
    )
    with pytest.raises(HarnessError) as raised:
        await successor.execute(task["id"], researcher.project_id)
    assert raised.value.code == "WORKSPACE_RESTORE_INCOMPATIBLE"
    assert calls == 1
    current = service.get_record("task", task["id"], controller)
    assert current["ready_continuation"]["workspace_ticket"] == ticket
    assert current["status"] == "blocked"
    assert service.artifact_content(source_artifact_id, controller)
    await client.close()
