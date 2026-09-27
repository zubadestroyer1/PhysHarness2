"""Native checkpoint payloads remain exact while repeated prefixes are shared."""

import hashlib
import json
from pathlib import Path

import pytest
from test_core import setup_experiment

from physharness.domain import (
    ArtifactCreate,
    BranchCreate,
    TaskCreate,
    canonical_json,
    digest_json,
)
from physharness.errors import HarnessError
from physharness.execution import (
    ModelConfig,
    RuntimeCheckpoint,
    RuntimeLimits,
    RuntimeSession,
    checkpoint_chunks,
)
from physharness.execution.checkpoint_chunks import decode, encode
from physharness.orchestration.research_worker import CanonicalRuntimeStore
from physharness.reproduction import validate_export

GOLDEN = Path(__file__).parent / "fixtures" / "native_checkpoint_golden.json"

GOLDEN_SESSION = RuntimeSession(
    id="golden-session",
    runtime="openai_responses",
    model=ModelConfig(model="exact-model"),
    limits=RuntimeLimits(),
)


def golden_cases():
    unicode, tool = "∀ ε > 0, ∃ δ ≥ 0 — ℝ", {"type": "string", "description": "d" * 300}
    return {
        "small": {"input": [{"role": "user", "content": "hi"}], "settled_boundary": True},
        "paged_list": {"input": [{"id": str(i), "content": "x" * 4096} for i in range(40)]},
        "nested_map": {
            "tool_results": {f"s:{i}": {"result": {"text": unicode * 200}} for i in range(30)}
        },
        "long_text": {"initial_anchor": ("é" * 3000 + "a") * 20},
        "legacy_response": {
            "responses": [
                {
                    "id": "r1",
                    "output": [],
                    "tools": [{"name": f"t{i}", "parameters": tool} for i in range(40)],
                }
            ]
        },
    }


def encode_to_memory(state):
    chunks, order = {}, []

    def put(content):
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        chunks[digest] = content.encode("utf-8")
        order.append(digest)
        return {"id": digest, "sha256": digest}

    checkpoint = RuntimeCheckpoint.build(GOLDEN_SESSION, state)
    return checkpoint, encode(checkpoint, put), chunks, order


def chunk_digests(state):
    _, manifest, _, order = encode_to_memory(state)
    return {
        "chunks": order,
        "manifest": hashlib.sha256(canonical_json(manifest).encode()).hexdigest(),
    }


def nested_state(shape, depth):
    """A state nested ``depth`` levels deep whose every level is chunked, not inlined."""
    node = "z" * 20000
    for _ in range(depth):
        if shape == "list":
            node = [node, *range(300)]  # 38 pages, so one index level
        else:
            width = 40 if shape == "map" else 0  # 41 keys split into dict branches
            node = {**{f"k{i}": i for i in range(width)}, "child": node}
    return {"doc": node}


def encodes(state):
    try:
        encode_to_memory(state)
    except HarnessError:
        return False
    return True


def decodes(manifest, chunks, checkpoint):
    try:
        raw = canonical_json(manifest).encode()
        return decode(raw, lambda ref: chunks[ref["sha256"]]) == checkpoint
    except HarnessError:
        return False


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


def test_encoder_is_byte_identical_to_golden_and_round_trips():
    assert {n: chunk_digests(s) for n, s in golden_cases().items()} == json.loads(
        GOLDEN.read_text()
    )
    for state in golden_cases().values():
        checkpoint, manifest, chunks, _ = encode_to_memory(state)
        assert (
            decode(
                canonical_json(manifest).encode(), lambda ref, chunks=chunks: chunks[ref["sha256"]]
            )
            == checkpoint
        )


@pytest.mark.parametrize("shape", ["map", "single_key", "list"])
def test_encoder_refuses_exactly_the_depths_decode_refuses(shape, monkeypatch):
    accepted = {depth: encodes(nested_state(shape, depth)) for depth in range(4, 34)}
    assert set(accepted.values()) == {True, False}
    for depth, ok in accepted.items():
        # Build the same graph with the depth bound lifted, then ask decode's real bound.
        with monkeypatch.context() as unbounded:
            unbounded.setattr(checkpoint_chunks, "MAX_DEPTH", 10**6)
            checkpoint, manifest, chunks, _ = encode_to_memory(nested_state(shape, depth))
        assert decodes(manifest, chunks, checkpoint) == ok, (shape, depth)


def test_encoder_refuses_exactly_the_bytes_decode_refuses(monkeypatch):
    state = golden_cases()["paged_list"]
    checkpoint, manifest, chunks, order = encode_to_memory(state)
    total = len(canonical_json(manifest).encode()) + sum(len(chunks[d]) for d in order)
    # The band: the whole checkpoint fits the bound while its graph does not.
    assert len(canonical_json(checkpoint.model_dump(mode="json")).encode()) < total - 1
    for limit, ok in ((total, True), (total - 1, False)):
        monkeypatch.setattr(checkpoint_chunks, "MAX_BYTES", limit)
        assert encodes(state) == ok
        assert decodes(manifest, chunks, checkpoint) == ok


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", ["depth", "bytes"])
async def test_save_refuses_an_unloadable_graph_and_keeps_the_last_good_checkpoint(
    native_store, monkeypatch, bound
):
    service, actor, _, _, store, session = native_store
    first = RuntimeCheckpoint.build(session, {"input": ["first"]})
    await store.save(first)
    before = (service.list_records("session", actor)[0], service.list_records("artifact", actor))
    state = nested_state("map", 20) if bound == "depth" else golden_cases()["paged_list"]
    checkpoint = RuntimeCheckpoint.build(session, state)
    if bound == "bytes":
        whole = canonical_json(checkpoint.model_dump(mode="json")).encode()
        monkeypatch.setattr(checkpoint_chunks, "MAX_BYTES", len(whole))
    with pytest.raises(HarnessError) as caught:
        await store.save(checkpoint)
    assert caught.value.code == "NATIVE_CHECKPOINT_INVALID"
    assert (
        service.list_records("session", actor)[0],
        service.list_records("artifact", actor),
    ) == before
    assert await store.load(session.id) == first


@pytest.mark.asyncio
async def test_save_verifies_the_checkpoint_digest_exactly_once(native_store, monkeypatch):
    _, _, _, _, store, session = native_store
    calls, original = [], RuntimeCheckpoint.verify
    checkpoint = RuntimeCheckpoint.build(
        session, {"input": [{"content": "x" * 4096, "id": str(i)} for i in range(80)]}
    )
    monkeypatch.setattr(
        RuntimeCheckpoint,
        "verify",
        lambda self, runtime=None: calls.append(1) or original(self, runtime),
    )
    await store.save(checkpoint)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_single_transaction_commit_is_atomic(native_store, monkeypatch):
    service, actor, _, _, store, session = native_store
    first = RuntimeCheckpoint.build(session, {"input": ["first"]})
    await store.save(first)

    def chunk_rows():
        return [
            a["id"]
            for a in service.list_records("artifact", actor)
            if a["artifact_kind"] == "native_checkpoint_chunk"
        ]

    before = (service.list_records("session", actor)[0], service.list_records("artifact", actor))
    chunks_before, inserted = chunk_rows(), []
    original = service._artifact_record

    def fail_manifest(db_session, request, *args, **kwargs):
        if request.kind == "native_checkpoint":
            raise RuntimeError("crash before manifest")
        inserted.append(original(db_session, request, *args, **kwargs))
        return inserted[-1]

    monkeypatch.setattr(service, "_artifact_record", fail_manifest)
    with pytest.raises(RuntimeError, match="crash before manifest"):
        await store.save(
            RuntimeCheckpoint.build(
                session, {"input": [{"content": "x" * 4096, "id": str(i)} for i in range(80)]}
            )
        )
    # The failed save inserted chunk rows in its transaction; none of them survive.
    assert inserted
    assert chunk_rows() == chunks_before
    assert (
        service.list_records("session", actor)[0],
        service.list_records("artifact", actor),
    ) == before
    assert await store.load(session.id) == first


@pytest.mark.asyncio
async def test_restart_dedupes_existing_chunks_without_cache(native_store):
    service, actor, experiment, task, store, session = native_store
    history = [{"content": "x" * 4096, "id": str(i)} for i in range(80)]
    await store.save(RuntimeCheckpoint.build(session, {"input": history}))

    def chunk_rows():
        return sum(
            a["artifact_kind"] == "native_checkpoint_chunk"
            for a in service.list_records("artifact", actor)
        )

    before = chunk_rows()
    restarted = CanonicalRuntimeStore(
        service, actor, experiment["id"], task["id"], "worker", store.fence
    )
    await restarted.save(
        RuntimeCheckpoint.build(session, {"input": [*history, {"content": "y", "id": "80"}]})
    )
    assert chunk_rows() - before <= 6  # new last page, sequence, map leaf, root; not all 11 pages
    assert (await restarted.load(session.id)).native_state["input"][-1] == {
        "content": "y",
        "id": "80",
    }


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
    # One row insert per new chunk inside the single fenced save transaction.
    assert all(sql <= 2 * new + 40 for new, sql in costs), costs
    event.listen(service.db.engine, "before_cursor_execute", count)
    assert (await store.load(session.id)).native_state["input"] == history
    event.remove(service.db.engine, "before_cursor_execute", count)
    # Depth-batched reads: independent of the number of referenced chunks.
    assert len(statements) <= 15, (len(statements), total)
