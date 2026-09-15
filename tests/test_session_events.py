"""Canonical runtime sessions must be observable without polling every collection."""

import pytest
from test_core import setup_experiment

from physharness.domain import BranchCreate, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import ModelConfig, RuntimeCheckpoint, RuntimeLimits, RuntimeSession
from physharness.orchestration.research_worker import CanonicalRuntimeStore


@pytest.fixture
def runtime_store(lab):
    service, researcher, _ = lab
    actor = researcher.model_copy(update={"role": "operator"})
    experiment, _ = setup_experiment(lab)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Branch", objective="Research"), actor, "branch"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task"
    )
    lease = service.acquire_task(task["id"], "worker", 60, actor, "lease")
    store = CanonicalRuntimeStore(
        service, actor, experiment["id"], task["id"], "worker", lease["fence"]
    )
    state = RuntimeSession(
        runtime="responses", model=ModelConfig(model="explicit-test-model"), limits=RuntimeLimits()
    )
    return service, actor, store, state


def session_events(service, actor):
    return [event for event in service.events(actor) if event["kind"] == "session.saved"]


@pytest.mark.asyncio
async def test_session_insert_update_and_replay_emit_exactly_one_event_per_committed_save(
    runtime_store,
):
    service, actor, store, state = runtime_store
    first = RuntimeCheckpoint.build(state, {"private_native_contents": "first checkpoint"})
    await store.save(first)
    created = service.list_records("session", actor)[0]
    events = session_events(service, actor)
    assert len(events) == 1
    assert events[0]["aggregate_id"] == created["id"] != state.id
    assert service.get_record("session", events[0]["aggregate_id"], actor) == created
    assert events[0]["payload"] == {
        "experiment_id": store.experiment_id,
        "task_id": store.task_id,
        "revision": 1,
    }
    await store.save(first)
    assert session_events(service, actor) == events
    assert service.get_record("session", created["id"], actor)["revision"] == 1

    state.status = "completed"
    state.output_tokens = 17
    final = RuntimeCheckpoint.build(state, {"private_native_contents": "final checkpoint"})
    await store.save(final)
    updated = service.get_record("session", created["id"], actor)
    events = session_events(service, actor)
    assert len(events) == 2
    assert events[1]["aggregate_id"] == created["id"]
    assert events[1]["payload"] == {**events[0]["payload"], "revision": 2}
    assert events[1]["operation_id"] != events[0]["operation_id"]
    assert updated["status"] == "completed"
    assert updated["revision"] == 2
    assert updated["output_tokens"] == 17
    await store.save(final)
    assert session_events(service, actor) == events
    assert service.list_records("session", actor) == [updated]


@pytest.mark.asyncio
async def test_session_event_and_record_rollback_together(runtime_store, monkeypatch):
    service, actor, store, state = runtime_store
    original = service._event

    def fail_after_event(session, actor, operation, kind, aggregate_id, payload, **kwargs):
        original(session, actor, operation, kind, aggregate_id, payload, **kwargs)
        if kind == "session.saved":
            session.flush()
            raise RuntimeError("session event transaction failed")

    monkeypatch.setattr(service, "_event", fail_after_event)
    with pytest.raises(RuntimeError, match="session event transaction failed"):
        await store.save(RuntimeCheckpoint.build(state, {"checkpoint": "private"}))
    assert service.list_records("session", actor) == []
    assert session_events(service, actor) == []


@pytest.mark.asyncio
async def test_stale_fence_cannot_publish_session_changes(runtime_store):
    service, actor, store, state = runtime_store
    await store.save(RuntimeCheckpoint.build(state, {"checkpoint": "first"}))
    before = service.list_records("session", actor)
    events = session_events(service, actor)
    store.fence += 1
    state.status = "completed"
    with pytest.raises(HarnessError) as caught:
        await store.save(RuntimeCheckpoint.build(state, {"checkpoint": "stale"}))
    assert caught.value.code == "STALE_LEASE"
    assert service.list_records("session", actor) == before
    assert session_events(service, actor) == events
