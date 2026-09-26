"""Native checkpoint payloads remain exact while repeated prefixes are shared."""

import json

import pytest
from test_core import setup_experiment

from physharness.domain import ArtifactCreate, BranchCreate, TaskCreate, digest_json
from physharness.errors import HarnessError
from physharness.execution import ModelConfig, RuntimeCheckpoint, RuntimeLimits, RuntimeSession
from physharness.orchestration.research_worker import CanonicalRuntimeStore
from physharness.reproduction import validate_export


@pytest.fixture
def native_store(lab):
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
    session = RuntimeSession(
        runtime="openai_responses",
        model=ModelConfig(model="explicit-test-model"),
        limits=RuntimeLimits(),
    )
    return service, actor, experiment, task, store, session


def current_artifact(native_store):
    service, actor, _, _, _, _ = native_store
    row = service.list_records("session", actor)[0]
    return service.get_record("artifact", row["checkpoint_artifact_id"], actor)


@pytest.mark.asyncio
async def test_old_full_checkpoint_and_new_chunked_checkpoint_restore_exactly(native_store):
    service, actor, experiment, task, store, session = native_store
    old = RuntimeCheckpoint.build(
        session, {"input": [{"content": "old"}], "settled_boundary": True}
    )
    old_artifact = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            kind="native_checkpoint",
            content=old.model_dump_json(),
            provenance={"task_id": task["id"], "session_id": session.id},
        ),
        actor,
        "historical-full",
    )
    assert service.load_native_checkpoint(old_artifact["id"], actor) == old

    state = {
        "input": [{"content": "x" * 4096, "id": str(i)} for i in range(80)],
        "responses": [{"output": "complete"}],
        "settled_boundary": True,
    }
    new = RuntimeCheckpoint.build(session, state)
    await store.save(new)
    artifact = current_artifact(native_store)
    assert json.loads(service.artifact_content(artifact["id"], actor))["format"] == (
        "physharness.native_checkpoint.v2"
    )
    assert await store.load(session.id) == new
    assert service.load_native_checkpoint(artifact["id"], actor) == new


@pytest.mark.asyncio
async def test_chunk_missing_or_tampered_fails_closed(native_store):
    service, actor, _, _, store, session = native_store
    await store.save(
        RuntimeCheckpoint.build(
            session, {"input": [{"content": "x" * 4096, "id": str(i)} for i in range(80)]}
        )
    )
    manifest = json.loads(service.artifact_content(current_artifact(native_store)["id"], actor))
    root = manifest["root"]
    chunk = service.get_record("artifact", root["artifact_id"], actor)
    path = service.artifacts.path_for(chunk["sha256"])
    original = path.read_bytes()
    try:
        path.write_bytes(b"tampered")
        with pytest.raises(HarnessError, match="digest|integrity|match"):
            await store.load(session.id)
        path.unlink()
        with pytest.raises(HarnessError, match="unavailable|missing|found"):
            await store.load(session.id)
    finally:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(original)


@pytest.mark.asyncio
async def test_interrupted_chunk_save_does_not_publish_manifest(native_store, monkeypatch):
    service, actor, _, _, store, session = native_store
    first = RuntimeCheckpoint.build(session, {"input": ["first"]})
    await store.save(first)
    before = service.list_records("session", actor)[0]
    original = service.create_artifact

    def fail_manifest(request, *args):
        if request.kind == "native_checkpoint":
            raise RuntimeError("crash before manifest")
        return original(request, *args)

    monkeypatch.setattr(service, "create_artifact", fail_manifest)
    with pytest.raises(RuntimeError, match="crash before manifest"):
        await store.save(
            RuntimeCheckpoint.build(
                session, {"input": [{"content": "x" * 4096, "id": str(i)} for i in range(80)]}
            )
        )
    assert service.list_records("session", actor)[0] == before
    assert await store.load(session.id) == first


@pytest.mark.asyncio
async def test_stale_fence_cannot_publish_new_chunked_checkpoint(native_store):
    service, actor, _, _, store, session = native_store
    first = RuntimeCheckpoint.build(session, {"input": ["first"]})
    await store.save(first)
    before = service.list_records("session", actor)[0]
    store.fence += 1
    with pytest.raises(HarnessError) as caught:
        await store.save(
            RuntimeCheckpoint.build(
                session, {"input": [{"id": str(i), "content": "x" * 4096} for i in range(80)]}
            )
        )
    assert caught.value.code == "STALE_LEASE"
    assert service.list_records("session", actor)[0] == before
    assert await store.load(session.id) == first


@pytest.mark.asyncio
async def test_chunked_checkpoint_export_has_complete_verified_closure(native_store, tmp_path):
    service, actor, experiment, _, store, session = native_store
    checkpoint = RuntimeCheckpoint.build(
        session, {"input": [{"content": "x" * 4096, "id": str(i)} for i in range(80)]}
    )
    await store.save(checkpoint)
    manifest = service.export_experiment(experiment["id"], actor)
    artifacts = manifest["records"]["artifact"]
    assert any(item["artifact_kind"] == "native_checkpoint_chunk" for item in artifacts)
    directory = tmp_path / "export"
    directory.mkdir()
    for item in artifacts:
        (directory / item["sha256"]).write_bytes(service.artifact_content(item["id"], actor))
    (directory / "manifest.json").write_text(json.dumps(manifest))
    assert validate_export(directory)["status"] == "artifact_integrity_checked"
    chunk = next(item for item in artifacts if item["artifact_kind"] == "native_checkpoint_chunk")
    (directory / chunk["sha256"]).unlink()
    with pytest.raises(HarnessError):
        validate_export(directory)
    (directory / chunk["sha256"]).write_bytes(service.artifact_content(chunk["id"], actor))
    manifest["records"]["artifact"].remove(chunk)
    manifest["manifest_sha256"] = digest_json(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(HarnessError):
        validate_export(directory)


@pytest.mark.asyncio
async def test_append_only_history_reuses_prefix_payloads(native_store):
    service, actor, _, _, store, session = native_store
    history = []
    for i in range(12):
        history.extend({"id": f"{i}-{j}", "content": "x" * 4096} for j in range(8))
        await store.save(RuntimeCheckpoint.build(session, {"input": history.copy()}))
    unique_payload = sum(
        item["size_bytes"]
        for item in service.list_records("artifact", actor)
        if item["artifact_kind"] in {"native_checkpoint", "native_checkpoint_chunk"}
    )
    full_snapshot_payload = sum(
        len(
            RuntimeCheckpoint.build(
                session,
                {
                    "input": [
                        {"id": f"{i}-{j}", "content": "x" * 4096}
                        for i in range(k + 1)
                        for j in range(8)
                    ]
                },
            )
            .model_dump_json()
            .encode()
        )
        for k in range(12)
    )
    assert unique_payload < full_snapshot_payload // 3
    assert (await store.load(session.id)).native_state["input"] == history


@pytest.mark.asyncio
async def test_random_key_tool_results_reuse_prefix_payloads(native_store):
    service, actor, _, _, store, session = native_store
    results = {}
    for i in range(12):
        for j in range(8):
            key = f"call-{(i * 8 + j) * 7919 % 104729:06d}"
            results[key] = {"output": "x" * 4096}
        await store.save(RuntimeCheckpoint.build(session, {"tool_results": results.copy()}))
    unique_payload = sum(
        item["size_bytes"]
        for item in service.list_records("artifact", actor)
        if item["artifact_kind"] in {"native_checkpoint", "native_checkpoint_chunk"}
    )
    full_payload = sum(
        len(
            RuntimeCheckpoint.build(
                session,
                {
                    "tool_results": {
                        f"call-{n * 7919 % 104729:06d}": {"output": "x" * 4096}
                        for n in range((k + 1) * 8)
                    }
                },
            )
            .model_dump_json()
            .encode()
        )
        for k in range(12)
    )
    assert unique_payload < full_payload // 3
    assert (await store.load(session.id)).native_state["tool_results"] == results


@pytest.mark.asyncio
async def test_manifest_cannot_reference_another_tasks_native_chunks(native_store):
    service, actor, experiment, task, store, session = native_store
    branch = service.get_record("branch", task["branch_id"], actor)
    other_task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Other"), actor, "other-task"
    )
    other_lease = service.acquire_task(other_task["id"], "other-worker", 60, actor, "other-lease")
    other_store = CanonicalRuntimeStore(
        service, actor, experiment["id"], other_task["id"], "other-worker", other_lease["fence"]
    )
    other_session = session.model_copy(update={"id": "other-native-session"})
    await other_store.save(
        RuntimeCheckpoint.build(
            other_session,
            {"input": [{"content": "other private" * 500, "id": str(i)} for i in range(40)]},
        )
    )
    foreign_row = next(
        row
        for row in service.list_records("session", actor)
        if row["native_record_id"] == other_session.id
    )
    foreign = json.loads(service.artifact_content(foreign_row["checkpoint_artifact_id"], actor))
    forged = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            kind="native_checkpoint",
            content=json.dumps(foreign),
            provenance={"task_id": task["id"], "session_id": other_session.id},
        ),
        actor,
        "forged-manifest",
    )
    with pytest.raises(HarnessError, match="scope"):
        service.load_native_checkpoint(forged["id"], actor)
    with pytest.raises(HarnessError):
        service.export_experiment(experiment["id"], actor)


@pytest.mark.asyncio
async def test_save_and_load_sql_cost_scales_with_new_chunks_not_history(native_store):
    from sqlalchemy import event

    service, actor, _, _, store, session = native_store
    statements = []

    def count(*args):
        statements.append(1)

    def chunk_count():
        return sum(
            item["artifact_kind"] == "native_checkpoint_chunk"
            for item in service.list_records("artifact", actor)
        )

    history, costs = [], []
    for i in range(12):
        history.extend({"id": f"{i}-{j}", "content": "x" * 1024} for j in range(24))
        before = chunk_count()
        event.listen(service.db.engine, "before_cursor_execute", count)
        await store.save(RuntimeCheckpoint.build(session, {"input": history.copy()}))
        event.remove(service.db.engine, "before_cursor_execute", count)
        costs.append((chunk_count() - before, len(statements)))
        statements.clear()
    total = chunk_count()
    assert total > 60
    # A fixed per-new-chunk transaction plus the fenced manifest publication.
    assert all(sql <= 12 * new + 40 for new, sql in costs), costs
    event.listen(service.db.engine, "before_cursor_execute", count)
    assert (await store.load(session.id)).native_state["input"] == history
    event.remove(service.db.engine, "before_cursor_execute", count)
    # Depth-batched reads: independent of the number of referenced chunks.
    assert len(statements) <= 15, (len(statements), total)
