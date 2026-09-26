"""Streamed checkpoint manifest, dependency closure and fenced broker behavior."""

import hashlib
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from test_workspace_service import setup

from physharness.domain import Principal
from physharness.execution.types import ExecutionError
from physharness.execution.workspace_archive import CHUNK_SIZE, StreamedWorkspaceArchive
from physharness.orchestration.workspace_tools import WorkspaceTools
from physharness.orchestration.workspaces import WorkspaceBroker
from physharness.storage import LeaseRow


def digest(data):
    return hashlib.sha256(data).hexdigest()


def example_manifest():
    chunk = b"x" * 70_000
    return StreamedWorkspaceArchive.build(
        [
            {
                "path": "a.txt",
                "size": len(chunk) * 2,
                "sha256": digest(chunk * 2),
                "chunks": [digest(chunk), digest(chunk)],
            }
        ],
        [{"sha256": digest(chunk), "size": len(chunk), "artifact_id": "chunk-id"}],
    )


def test_v3_manifest_canonical_and_expansion_bounds():
    archive = example_manifest()
    assert StreamedWorkspaceArchive.from_bytes(archive.data, sha256=archive.sha256) == archive
    raw = json.loads(archive.data)
    raw["files"][0]["size"] = True
    with pytest.raises(ExecutionError):
        StreamedWorkspaceArchive.from_bytes(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        )
    raw = json.loads(archive.data)
    raw["files"][0]["chunks"] *= 200
    raw["files"][0]["size"] *= 200
    with pytest.raises(ExecutionError):
        StreamedWorkspaceArchive.from_bytes(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode(),
            quota_bytes=CHUNK_SIZE,
        )
    raw = json.loads(archive.data)
    raw["files"].append({"path": "a.txt/child", "size": 0, "sha256": digest(b""), "chunks": []})
    with pytest.raises(ExecutionError):
        StreamedWorkspaceArchive.from_bytes(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        )
    with pytest.raises(ExecutionError):
        StreamedWorkspaceArchive.from_bytes(archive.data + b" ")


def test_guest_listing_globally_sorts_root_file_and_nested_scratch(tmp_path):
    from physharness.execution.local_docker import _GUEST

    (tmp_path / "scratch").mkdir()
    (tmp_path / "solution.lean").write_bytes(b"theorem answer : True := trivial\n")
    (tmp_path / "scratch" / "Check.lean").write_bytes(b"#check True\n")
    # Run the actual guest listing script against a temporary root. macOS has
    # no /proc, so omit only the VM process enumeration in this local test.
    guest = _GUEST.replace("root='/work'", f"root={str(tmp_path)!r}").replace(
        "for item in os.listdir('/proc'):", "for item in ():"
    )
    observed = json.loads(
        subprocess.run(
            [sys.executable, "-c", guest, "list3"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    paths = [entry[0] for entry in observed["files"]]
    assert paths == ["scratch/Check.lean", "solution.lean"]
    files = []
    chunks = []
    for path, size, sha256, *_ in observed["files"]:
        files.append({"path": path, "size": size, "sha256": sha256, "chunks": [sha256]})
        chunks.append({"sha256": sha256, "size": size, "artifact_id": path})
    chunks.sort(key=lambda entry: entry["sha256"])
    archive = StreamedWorkspaceArchive.build(files, chunks)
    assert StreamedWorkspaceArchive.from_bytes(archive.data) == archive
    with pytest.raises(ExecutionError, match="Invalid streamed"):
        StreamedWorkspaceArchive.build(list(reversed(files)), chunks)


class StreamVM:
    sequence = 0

    def __init__(self, journal, files):
        type(self).sequence += 1
        self.execution_id = f"stream-vm-{type(self).sequence}"
        self.template_id = "qualified-template"
        self.timeout_seconds = 60
        self.network_disabled = True
        self.capabilities = SimpleNamespace(isolation="provider_vm", available=True)
        self.workspace_quota_bytes = 256 * CHUNK_SIZE
        self.files = dict(files)
        self.export_calls = 0
        self.restore_calls = 0

    async def create(self):
        return self

    async def export_workspace_stream(
        self, *, expected_execution_id, accept_chunk, before_read=None
    ):
        assert expected_execution_id == self.execution_id
        self.export_calls += 1
        entries, chunks = [], {}
        for path, data in sorted(self.files.items()):
            refs = []
            for offset in range(0, len(data), CHUNK_SIZE):
                if before_read is not None:  # The broker's hook precedes each guest read.
                    await before_read()
                piece = data[offset : offset + CHUNK_SIZE]
                ref = digest(piece)
                refs.append(ref)
                if ref not in chunks:
                    chunks[ref] = {
                        "sha256": ref,
                        "size": len(piece),
                        "artifact_id": await accept_chunk(piece, ref),
                    }
            entries.append(
                {"path": path, "size": len(data), "sha256": digest(data), "chunks": refs}
            )
        return entries, sorted(chunks.values(), key=lambda item: item["sha256"]), []

    async def restore_workspace_stream(self, archive, *, expected_execution_id, read_chunk):
        assert expected_execution_id == self.execution_id and not self.files
        self.restore_calls += 1
        chunks = {row["sha256"]: row for row in archive.manifest["chunks"]}
        for row in archive.manifest["files"]:
            collected = bytearray()
            for ref in row["chunks"]:
                collected.extend(await read_chunk(chunks[ref]))
            assert digest(collected) == row["sha256"]
            self.files[row["path"]] = bytes(collected)

    async def close(self):
        self.last_execution_observation = {
            "execution_id": self.execution_id,
            "destruction_confirmed": True,
        }


async def test_streamed_broker_checkpoint_restore_and_export_closure(lab):
    broker, service, experiment, _, _, args = setup(lab, concurrency=1)
    task = service.get_record("task", args["task_id"], broker.actor)
    payload = b"x" * CHUNK_SIZE + b"z" * 90_000 + b"x" * CHUNK_SIZE
    files = {"a/big.bin": payload, "b/duplicate.bin": b"x" * CHUNK_SIZE, "empty": b""}
    made = []

    def factory(*, journal, timeout_seconds):
        vm = StreamVM(journal, files if not made else {})
        vm.timeout_seconds = timeout_seconds
        made.append(vm)
        return vm

    args["provider_factory"] = factory
    args["provider_spec"] = {
        "provider": "local_docker",
        "template_id": "qualified-template",
        "timeout_seconds": 60,
    }
    broker = WorkspaceBroker(service, **args)
    workspace = await broker.provision(cost_bound_usd="0", operation_id="provision-stream")
    first = await broker.export_workspace(
        workspace["id"],
        expected_execution_id=workspace["execution_id"],
        operation_id="export-stream",
    )
    replay = await broker.export_workspace(
        workspace["id"],
        expected_execution_id=workspace["execution_id"],
        operation_id="export-stream",
    )
    assert replay == first and made[0].export_calls == 1
    archive = broker.load_handoff_archive(
        first["artifact"]["id"], first["archive_sha256"], workspace["execution_id"]
    )
    assert len(archive.manifest["chunks"]) == 3
    assert len(archive.manifest["files"]) == 3
    export = service.export_experiment(experiment["id"], broker.actor)
    artifact_ids = {row["id"] for row in export["records"]["artifact"]}
    assert set(archive.chunk_artifact_ids) <= artifact_ids
    assert first["artifact"]["id"] in artifact_ids
    await broker.destroy(
        workspace["id"],
        expected_execution_id=workspace["execution_id"],
        operation_id="destroy-stream",
        actual_cost_usd="0",
    )
    with service.db.transaction() as session:
        session.get(LeaseRow, task["id"]).expires_at = 0
    lease = service.acquire_task(task["id"], "successor", 300, broker.actor, "lease-successor")
    successor = WorkspaceBroker(
        service,
        actor=Principal(id="vm-operator", project_id=broker.actor.project_id, role="operator"),
        task_id=task["id"],
        holder="successor",
        fence=lease["fence"],
        provider_factory=factory,
        provider_spec=args["provider_spec"],
    )
    fresh = await successor.provision(cost_bound_usd="0", operation_id="provision-successor")
    await successor.restore_workspace(
        fresh["id"],
        expected_execution_id=fresh["execution_id"],
        archive_artifact_id=first["artifact"]["id"],
        archive_sha256=first["archive_sha256"],
        source_execution_id=workspace["execution_id"],
        operation_id="restore-stream",
    )
    assert made[1].files == files
    assert made[1].restore_calls == 1
    await successor.destroy(
        fresh["id"],
        expected_execution_id=fresh["execution_id"],
        operation_id="destroy-successor",
        actual_cost_usd="0",
    )


@pytest.mark.integration
async def test_real_streamed_restore_on_dedicated_vm(tmp_path):
    """Opt-in final image smoke; allocates and removes only workbench containers."""
    import os

    from physharness.artifacts import LocalArtifactStore
    from physharness.execution.local_docker import LocalDockerWorkspaceProvider

    host = os.environ.get("PHYSHARNESS_WORKBENCH_DOCKER_HOST")
    image = os.environ.get("PHYSHARNESS_WORKBENCH_IMAGE_DIGEST")
    if not host or not image:
        pytest.skip("Dedicated endpoint and pinned image required")
    store = LocalArtifactStore(tmp_path / "cas")
    first = LocalDockerWorkspaceProvider(docker_host=host, image_digest=image, timeout_seconds=180)
    second = LocalDockerWorkspaceProvider(docker_host=host, image_digest=image, timeout_seconds=180)
    expected = {
        "solution.lean": b"theorem answer : True := trivial\n",
        "scratch/Check.lean": b"#check True\n",
        "research/large.txt": b"a" * CHUNK_SIZE + b"b" * 80_000,
        "research/copy.txt": b"a" * CHUNK_SIZE,
        "research/empty.txt": b"",
    }
    try:
        await first.create()
        for path, data in expected.items():
            await first.upload_file(path, data, expected_execution_id=first.execution_id)

        async def accept(piece, sha):
            assert len(piece) <= CHUNK_SIZE and store.put(piece) == sha
            return sha

        files, chunks, exclusions = await first.export_workspace_stream(
            expected_execution_id=first.execution_id, accept_chunk=accept
        )
        assert len(chunks) == 4
        assert [entry["path"] for entry in files] == sorted(expected)
        archive = StreamedWorkspaceArchive.build(files, chunks, excluded_paths=exclusions)
        await first.close()
        await second.create()

        async def read_chunk(chunk):
            return store.get(chunk["artifact_id"])

        await second.restore_workspace_stream(
            archive, expected_execution_id=second.execution_id, read_chunk=read_chunk
        )
        for path, data in expected.items():
            assert (
                await second.download_file(path, expected_execution_id=second.execution_id) == data
            )
    finally:
        if first._container_id:
            await first.close()
        if second._container_id:
            await second.close()


@pytest.mark.parametrize("failure", ["interrupt", "stale_lease"])
async def test_streamed_checkpoint_failure_keeps_source_and_no_manifest(lab, failure):
    from physharness.errors import HarnessError

    broker, service, experiment, _, _, args = setup(lab, concurrency=1)
    task = service.get_record("task", args["task_id"], broker.actor)

    class FailingVM(StreamVM):
        closed = False

        async def export_workspace_stream(self, *, expected_execution_id, accept_chunk):
            await accept_chunk(b"a" * CHUNK_SIZE, digest(b"a" * CHUNK_SIZE))
            if failure == "stale_lease":
                with service.db.transaction() as session:
                    session.get(LeaseRow, task["id"]).expires_at = 0
                await accept_chunk(b"b", digest(b"b"))
            raise RuntimeError("interrupted after first persisted chunk")

        async def close(self):
            self.closed = True
            await super().close()

    made = []

    def factory(*, journal, timeout_seconds):
        vm = FailingVM(journal, {"large": b"a" * CHUNK_SIZE + b"b"})
        vm.timeout_seconds = timeout_seconds
        made.append(vm)
        return vm

    args["provider_factory"] = factory
    args["provider_spec"] = {
        "provider": "local_docker",
        "template_id": "qualified-template",
        "timeout_seconds": 60,
    }
    broker = WorkspaceBroker(service, **args)
    workspace = await broker.provision(cost_bound_usd="0", operation_id="provision")
    with pytest.raises(HarnessError) as raised:
        await broker.export_workspace(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            operation_id="export-failed",
        )
    assert raised.value.code == "WORKSPACE_RECONCILIATION_REQUIRED"
    current = broker.inspect(workspace["id"])
    assert current["status"] == "reconciliation_required"
    assert current["checkpoint_artifact_id"] is None
    assert current["destruction_confirmed"] is False
    assert service.ledger(experiment["id"], broker.actor)["active_workers"] == 1
    tools = WorkspaceTools.__new__(WorkspaceTools)
    tools.broker, tools.workspace = broker, workspace
    with pytest.raises(HarnessError) as cleanup:
        await tools.close()
    assert cleanup.value.code == "WORKSPACE_RECONCILIATION_REQUIRED"
    assert made[0].closed is False
    assert broker.inspect(workspace["id"])["status"] == "reconciliation_required"
    exported = service.export_experiment(experiment["id"], broker.actor)
    assert all(row["artifact_kind"] != "checkpoint" for row in exported["records"]["artifact"])


@pytest.mark.parametrize("failure", ["missing", "corrupt"])
async def test_missing_or_corrupt_chunk_rejected_before_new_allocation(lab, monkeypatch, failure):
    from physharness.errors import HarnessError

    broker, service, _, _, _, args = setup(lab)
    made = []

    def factory(*, journal, timeout_seconds):
        vm = StreamVM(journal, {"data": b"evidence"})
        vm.timeout_seconds = timeout_seconds
        made.append(vm)
        return vm

    args["provider_factory"] = factory
    args["provider_spec"] = {
        "provider": "local_docker",
        "template_id": "qualified-template",
        "timeout_seconds": 60,
    }
    broker = WorkspaceBroker(service, **args)
    workspace = await broker.provision(cost_bound_usd="0", operation_id="provision")
    ticket = await broker.export_workspace(
        workspace["id"], expected_execution_id=workspace["execution_id"], operation_id="export"
    )
    original = service.artifacts.get
    chunk_digest = digest(b"evidence")

    def broken(sha):
        if sha == chunk_digest:
            if failure == "missing":
                raise HarnessError("ARTIFACT_NOT_FOUND", "Chunk missing")
            return b"corrupt"
        return original(sha)

    monkeypatch.setattr(service.artifacts, "get", broken)
    with pytest.raises(HarnessError):
        broker.load_handoff_archive(
            ticket["artifact"]["id"], ticket["archive_sha256"], workspace["execution_id"]
        )
    assert len(made) == 1
    assert broker.inspect(workspace["id"])["status"] == "ready"


async def test_chunk_artifacts_stay_private_under_ideas_sharing(lab):
    from test_sharing import approaches

    from physharness.domain import ArtifactCreate
    from physharness.errors import HarnessError

    service, author, experiment, _, (alpha, beta) = approaches(lab, "ideas")
    chunk = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            branch_id=beta.branch_id,
            kind="checkpoint_chunk",
            content="private checkpoint bytes",
        ),
        author.model_copy(update={"role": "operator"}),
        "private-chunk",
    )
    assert service.artifact_content(chunk["id"], author) == b"private checkpoint bytes"
    with pytest.raises(HarnessError):
        service.artifact_content(chunk["id"], beta)
    with pytest.raises(HarnessError):
        service.get_record("artifact", chunk["id"], alpha)
    with pytest.raises(HarnessError):
        service.artifact_content(chunk["id"], alpha)
    assert chunk["id"] not in {
        row["id"] for row in service.list_records("artifact", alpha, experiment["id"])
    }
    assert chunk["id"] in {
        row["id"]
        for row in service.export_experiment(experiment["id"], author)["records"]["artifact"]
    }


async def test_interrupted_restore_never_reports_success_or_reuses_vm(lab):
    from physharness.errors import HarnessError

    broker, service, _, _, _, args = setup(lab, concurrency=1)
    task = service.get_record("task", args["task_id"], broker.actor)
    made = []

    class InterruptedRestoreVM(StreamVM):
        async def restore_workspace_stream(self, archive, *, expected_execution_id, read_chunk):
            self.restore_calls += 1
            await read_chunk(archive.manifest["chunks"][0])
            raise RuntimeError("restore stopped after first chunk")

    def factory(*, journal, timeout_seconds):
        vm = (
            StreamVM(journal, {"notes": b"a" * CHUNK_SIZE})
            if not made
            else InterruptedRestoreVM(journal, {})
        )
        vm.timeout_seconds = timeout_seconds
        made.append(vm)
        return vm

    args["provider_factory"] = factory
    args["provider_spec"] = {
        "provider": "local_docker",
        "template_id": "qualified-template",
        "timeout_seconds": 60,
    }
    broker = WorkspaceBroker(service, **args)
    source = await broker.provision(cost_bound_usd="0", operation_id="source")
    checkpoint = await broker.export_workspace(
        source["id"], expected_execution_id=source["execution_id"], operation_id="checkpoint"
    )
    await broker.destroy(
        source["id"],
        expected_execution_id=source["execution_id"],
        operation_id="destroy-source",
        actual_cost_usd="0",
    )
    with service.db.transaction() as session:
        session.get(LeaseRow, task["id"]).expires_at = 0
    lease = service.acquire_task(task["id"], "successor", 300, broker.actor, "lease-next")
    successor = WorkspaceBroker(
        service,
        actor=broker.actor,
        task_id=task["id"],
        holder="successor",
        fence=lease["fence"],
        provider_factory=factory,
        provider_spec=args["provider_spec"],
    )
    target = await successor.provision(cost_bound_usd="0", operation_id="target")
    kwargs = dict(
        expected_execution_id=target["execution_id"],
        archive_artifact_id=checkpoint["artifact"]["id"],
        archive_sha256=checkpoint["archive_sha256"],
        source_execution_id=source["execution_id"],
        operation_id="restore",
    )
    with pytest.raises(HarnessError) as raised:
        await successor.restore_workspace(target["id"], **kwargs)
    assert raised.value.code == "WORKSPACE_RECONCILIATION_REQUIRED"
    current = successor.inspect(target["id"])
    assert current["status"] == "reconciliation_required"
    assert current.get("restored_from_artifact_id") is None
    with pytest.raises(HarnessError):
        await successor.restore_workspace(target["id"], **kwargs)
    assert made[1].restore_calls == 1
