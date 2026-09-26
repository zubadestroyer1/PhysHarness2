"""Platform-private artifact kinds are controller output, never generic agent input."""

import json

import pytest
from fastapi.testclient import TestClient
from test_core import setup_experiment

from physharness.api import create_app
from physharness.config import Settings
from physharness.domain import ArtifactCreate, BranchCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import ModelConfig, RuntimeCheckpoint, RuntimeLimits, RuntimeSession
from physharness.orchestration.research_worker import CanonicalRuntimeStore, research_tools
from physharness.service import HarnessService

RESERVED = sorted(HarnessService._private_artifact_kinds - {"workspace_recovery_observation"})
POISON = json.dumps({"format": "physharness.native_checkpoint.v2"})


def running_branch(lab):
    service, researcher, _ = lab
    operator = researcher.model_copy(update={"role": "operator"})
    experiment, _ = setup_experiment(lab)
    service.transition_experiment(experiment["id"], "start", 1, operator, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Branch", objective="Research"), operator, "branch"
    )
    agent = Principal(
        id="holder-1",
        project_id=researcher.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=branch["id"],
    )
    return service, researcher, operator, experiment, branch, agent


@pytest.mark.parametrize("kind", RESERVED)
@pytest.mark.parametrize("role", ["agent", "researcher", "verifier"])
def test_generic_create_refuses_private_kinds_and_export_survives(lab, kind, role):
    service, researcher, operator, experiment, branch, agent = running_branch(lab)
    actor = agent if role == "agent" else researcher.model_copy(update={"role": role})
    with pytest.raises(HarnessError) as error:
        service.create_artifact(
            ArtifactCreate(
                experiment_id=experiment["id"],
                kind=kind,
                content=POISON,
                provenance={"branch_id": branch["id"], "task_id": "forged"},
            ),
            actor,
            "poison",
        )
    assert error.value.code == "ARTIFACT_KIND_RESERVED"
    assert error.value.status == 403
    assert not any(
        row["artifact_kind"] == kind for row in service.list_records("artifact", operator)
    )
    service.export_experiment(experiment["id"], operator)


async def test_model_store_artifact_tool_cannot_wedge_export(lab):
    service, _, operator, experiment, branch, agent = running_branch(lab)
    dispatcher = research_tools(service, agent, branch["id"])
    envelope = await dispatcher.dispatch(
        "store_artifact", {"kind": "native_checkpoint", "content": POISON}, "tool-op-1"
    )
    assert "ARTIFACT_KIND_RESERVED" in json.dumps(envelope)
    service.export_experiment(experiment["id"], operator)
    stored = await dispatcher.dispatch(
        "store_artifact", {"kind": "lean_source", "content": "theorem x : True := trivial"}, "k"
    )
    assert "ARTIFACT_KIND_RESERVED" not in json.dumps(stored)


async def test_worker_runtime_store_still_writes_and_exports_native_checkpoints(lab):
    service, _, operator, experiment, branch, _ = running_branch(lab)
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), operator, "task"
    )
    lease = service.acquire_task(task["id"], "worker", 60, operator, "lease")
    store = CanonicalRuntimeStore(
        service, operator, experiment["id"], task["id"], "worker", lease["fence"]
    )
    session = RuntimeSession(
        runtime="openai_responses",
        model=ModelConfig(model="explicit-test-model"),
        limits=RuntimeLimits(),
    )
    checkpoint = RuntimeCheckpoint.build(
        session, {"input": [{"content": "x" * 4096, "id": str(i)} for i in range(40)]}
    )
    await store.save(checkpoint)
    assert await store.load(session.id) == checkpoint
    exported = service.export_experiment(experiment["id"], operator)
    kinds = {row["artifact_kind"] for row in exported["records"]["artifact"]}
    assert {"native_checkpoint", "native_checkpoint_chunk"} <= kinds


def test_http_artifact_route_refuses_private_kind(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        artifact_root=tmp_path / "artifacts",
        auth_tokens={"research-key": {"id": "r", "project_id": "lab", "role": "researcher"}},
        auto_create_schema=True,
    )
    with TestClient(create_app(settings)) as api:
        response = api.post(
            "/v1/artifacts",
            headers={"Authorization": "Bearer research-key", "Idempotency-Key": "poison"},
            json={"kind": "native_checkpoint", "content": POISON},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ARTIFACT_KIND_RESERVED"
