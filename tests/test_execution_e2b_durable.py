import hashlib
import json
import shlex
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from physharness.execution.e2b import (
    E2BSandboxProvider,
    NativeWorkspaceCheckpoint,
    WorkspaceArchive,
)
from physharness.execution.storage import CommandJournal
from physharness.execution.types import ExecutionError


@pytest.mark.parametrize("cwd", [".", "nested"])
async def test_command_write_run_export_use_same_workspace(tmp_path, cwd):
    from physharness.execution.types import CommandRequest

    p = provider(tmp_path)
    guest_home = tmp_path / "guest-home"
    guest_home.mkdir()

    class LocalGuestCommands:
        """Run only this test's authored commands; no model code or paid SDK calls."""

        async def run(self, command, **kwargs):
            result = subprocess.run(
                shlex.split(command),
                cwd=kwargs.get("cwd") or guest_home,
                capture_output=True,
                text=True,
                check=False,
            )
            return SimpleNamespace(
                stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode
            )

    p._sandbox.commands = LocalGuestCommands()
    prefix = "" if cwd == "." else cwd + "/"
    script = b"from pathlib import Path\nPath('result.txt').write_text('42')\nprint('42')\n"
    await p.upload_file(prefix + "candidate.py", script, expected_execution_id="vm-source")
    result = await p.run(CommandRequest(argv=["python3", "candidate.py"], cwd=cwd))
    assert result.exit_code == 0, result.stderr
    assert result.stdout == "42\n"
    archive = await p.export_workspace(expected_execution_id="vm-source")
    assert archive.files() == {prefix + "candidate.py": script, prefix + "result.txt": b"42"}
    assert list(guest_home.iterdir()) == []


@pytest.mark.parametrize("cwd", ["../other", "nested/../other", "./nested", "", "a\\b", "a\x00b"])
async def test_relative_command_cwd_rejects_ambiguous_paths_before_dispatch(tmp_path, cwd):
    from physharness.execution.types import CommandRequest

    p = provider(tmp_path)
    p._sandbox.commands.run = AsyncMock()
    with pytest.raises(ExecutionError) as error:
        await p.run(CommandRequest(argv=["true"], cwd=cwd))
    assert error.value.code == "UNSAFE_PATH"
    p._sandbox.commands.run.assert_not_awaited()
    p._sandbox.kill.assert_not_awaited()
    assert not p._active and not p._quarantined


async def test_explicit_absolute_guest_cwd_is_preserved(tmp_path):
    from physharness.execution.types import CommandRequest

    p = provider(tmp_path)
    p._sandbox.commands.run = AsyncMock(
        return_value=SimpleNamespace(stdout="", stderr="", exit_code=0)
    )
    await p.run(CommandRequest(argv=["true"], cwd="/opt/science"))
    assert p._sandbox.commands.run.await_args.kwargs["cwd"] == "/opt/science"


def test_archive_canonical_and_integrity():
    a = WorkspaceArchive.build({"b": b"\xff", "dir/a": b"hello"})
    b = WorkspaceArchive.build({"dir/a": b"hello", "b": b"\xff"})
    assert a.to_bytes() == b.to_bytes()
    assert a.sha256 == hashlib.sha256(a.to_bytes()).hexdigest()
    assert WorkspaceArchive.from_bytes(a.to_bytes(), sha256=a.sha256).files() == a.files()
    with pytest.raises(ExecutionError, match="checksum"):
        WorkspaceArchive.from_bytes(a.to_bytes() + b" ", sha256=a.sha256)


@pytest.mark.parametrize(
    "path", ["../escape", "/absolute", "a/../b", "a//b", "./a", "a\\b", "a\x00b"]
)
def test_archive_rejects_paths(path):
    with pytest.raises(ExecutionError):
        WorkspaceArchive.build({path: b"x"})


def test_archive_rejects_duplicate_link_and_shadow_entries():
    a = WorkspaceArchive.build({"a": b"x"})
    raw = json.loads(a.to_bytes())
    raw["files"].append(raw["files"][0])
    encoded = json.dumps(raw).encode()
    with pytest.raises(ExecutionError):
        WorkspaceArchive.from_bytes(encoded, sha256=hashlib.sha256(encoded).hexdigest())
    with pytest.raises(ExecutionError):
        WorkspaceArchive.build({"a": b"x", "a/b": b"y"})
    raw["files"][0]["type"] = "symlink"
    encoded = json.dumps(raw).encode()
    with pytest.raises(ExecutionError):
        WorkspaceArchive.from_bytes(encoded, sha256=hashlib.sha256(encoded).hexdigest())


class LocalCommands:
    """Executes only adapter-authored file helper, never model code or live SDK calls."""

    async def run(self, command, **kwargs):
        result = subprocess.run(shlex.split(command), capture_output=True, text=True, check=False)
        return SimpleNamespace(
            stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode
        )


def provider(tmp_path, identity="vm-source"):
    p = E2BSandboxProvider(
        api_key="test",
        template_id="template:qualified-v1",
        workspace_root=str(tmp_path / "workspace"),
        journal=CommandJournal(tmp_path / "journal.db"),
    )
    p._sandbox = SimpleNamespace(
        sandbox_id=identity,
        commands=LocalCommands(),
        pause=AsyncMock(return_value=True),
        connect=AsyncMock(),
        kill=AsyncMock(),
        get_info=AsyncMock(
            return_value=SimpleNamespace(
                sandbox_id=identity, allow_internet_access=False, network=None
            )
        ),
    )
    return p


async def test_files_export_restore_and_symlink_safety(tmp_path):
    p = provider(tmp_path)
    await p.upload_file("dir/file", b"hello", expected_execution_id="vm-source")
    assert await p.download_file("dir/file", expected_execution_id="vm-source") == b"hello"
    archive = await p.export_workspace(expected_execution_id="vm-source")
    qroot = tmp_path / "other"
    qroot.mkdir()
    q = provider(qroot, "vm-destination")
    await q.restore_workspace(archive, expected_execution_id="vm-destination")
    assert await q.download_file("dir/file", expected_execution_id="vm-destination") == b"hello"
    await q.restore_workspace(
        archive, expected_execution_id="vm-destination"
    )  # safe identical replay
    (tmp_path / "workspace" / "link").symlink_to(tmp_path)
    with pytest.raises(ExecutionError):
        await p.download_file("link/journal.db", expected_execution_id="vm-source")
    with pytest.raises(ExecutionError):
        await p.export_workspace(expected_execution_id="vm-source")
    with pytest.raises(ExecutionError):
        await p.upload_file("link/escape", b"x", expected_execution_id="vm-source")
    assert not (tmp_path / "escape").exists()


async def test_restore_refuses_stale_files_and_identity(tmp_path):
    p = provider(tmp_path)
    await p.upload_file("existing", b"old", expected_execution_id="vm-source")
    with pytest.raises(ExecutionError, match="identity"):
        await p.upload_file("x", b"x", expected_execution_id="stale")
    with pytest.raises(ExecutionError):
        await p.restore_workspace(
            WorkspaceArchive.build({"new": b"x"}), expected_execution_id="vm-source"
        )


async def test_native_pause_resume_serialization_and_stale_identity(tmp_path):
    p = provider(tmp_path)
    checkpoint = await p.pause(expected_execution_id="vm-source", operation_id="pause-1")
    record = NativeWorkspaceCheckpoint.model_validate_json(checkpoint.model_dump_json())
    await p.resume(record, operation_id="resume-1")
    p._sandbox.pause.assert_awaited_once_with(keep_memory=True)
    p._sandbox.connect.assert_awaited_once_with(timeout=300, on_resume="restore")
    await p.resume(record, operation_id="resume-1")
    assert p._sandbox.connect.await_count == 1
    p._sandbox.sandbox_id = "different-vm"
    with pytest.raises(ExecutionError, match="identity"):
        await p.resume(record, operation_id="resume-2")


async def test_native_fork_identity_network_and_replay(tmp_path):
    p = provider(tmp_path)
    child = SimpleNamespace(
        sandbox_id="vm-child",
        kill=AsyncMock(),
        get_info=AsyncMock(
            return_value=SimpleNamespace(
                sandbox_id="vm-child", allow_internet_access=False, network=None
            )
        ),
    )
    p._sandbox.fork = AsyncMock(return_value=[child])
    q = await p.fork(expected_execution_id="vm-source", operation_id="fork-1")
    assert q.execution_id == "vm-child" and p.execution_id == "vm-source"
    assert await p.fork(expected_execution_id="vm-source", operation_id="fork-1") is q
    p._sandbox.fork.assert_awaited_once_with(timeout=300, count=1)
    child2 = SimpleNamespace(
        sandbox_id="vm-other",
        kill=AsyncMock(),
        get_info=AsyncMock(
            return_value=SimpleNamespace(
                sandbox_id="vm-other", allow_internet_access=True, network=None
            )
        ),
    )
    p._sandbox.fork.return_value = [child2]
    with pytest.raises(ExecutionError):
        await p.fork(expected_execution_id="vm-source", operation_id="fork-2")
    child2.kill.assert_awaited_once()
    with pytest.raises(ExecutionError, match="reconcile"):
        await p.fork(expected_execution_id="vm-source", operation_id="fork-2")


async def test_snapshot_actual_sdk_fields_and_mutable_restore_rejected(tmp_path):
    sdk = pytest.importorskip("e2b")
    from e2b.sandbox.sandbox_api import SnapshotInfo

    p = provider(tmp_path)
    p._sandbox.create_snapshot = AsyncMock(
        return_value=SnapshotInfo(snapshot_id="snap:latest", names=[])
    )
    c = await p.snapshot(expected_execution_id="vm-source", operation_id="snap-1")
    assert c.snapshot_id == "snap:latest"
    with pytest.raises(ExecutionError, match="mutable"):
        await p.restore_snapshot(c, operation_id="restore-1")
    assert callable(sdk.AsyncSandbox.fork)


async def test_resume_after_controller_restart_uses_actual_class_connect(tmp_path, monkeypatch):
    sdk = pytest.importorskip("e2b")
    p = provider(tmp_path)
    checkpoint = await p.pause(expected_execution_id="vm-source", operation_id="pause-1")
    live = p._sandbox
    p._sandbox = None
    connect = AsyncMock(return_value=live)
    monkeypatch.setattr(sdk.AsyncSandbox, "connect", connect)
    await p.resume(checkpoint, operation_id="reconnect-1")
    assert p.execution_id == "vm-source"
    connect.assert_awaited_once_with("vm-source", timeout=300, on_resume="restore", api_key="test")


async def test_restore_snapshot_survives_deleted_source_and_replay(tmp_path, monkeypatch):
    sdk = pytest.importorskip("e2b")
    p = provider(tmp_path)
    c = NativeWorkspaceCheckpoint.build(
        kind="snapshot",
        execution_id="vm-source",
        template_id=p.template_id,
        snapshot_id="snap:qualified-v1",
    )
    child = SimpleNamespace(
        sandbox_id="vm-restored",
        kill=AsyncMock(),
        get_info=AsyncMock(
            return_value=SimpleNamespace(
                sandbox_id="vm-restored", allow_internet_access=False, network=None
            )
        ),
    )
    create = AsyncMock(return_value=child)
    monkeypatch.setattr(sdk.AsyncSandbox, "create", create)
    p._sandbox = None
    q = await p.restore_snapshot(c, operation_id="restore-1", pinned_snapshot_id=c.snapshot_id)
    assert q.execution_id == "vm-restored"
    assert (
        await p.restore_snapshot(c, operation_id="restore-1", pinned_snapshot_id=c.snapshot_id) is q
    )
    create.assert_awaited_once_with(
        template="snap:qualified-v1",
        api_key="test",
        timeout=300,
        allow_internet_access=False,
        secure=True,
        envs={},
    )


async def test_snapshot_tamper_and_independent_forks(tmp_path):
    p = provider(tmp_path)
    c = NativeWorkspaceCheckpoint.build(
        kind="pause", execution_id="vm-source", template_id=p.template_id
    )
    with pytest.raises(ExecutionError, match="checksum"):
        await p.resume(c.model_copy(update={"execution_id": "tampered"}), operation_id="r")
    children = []
    for name in ["child-a", "child-b"]:
        children.append(
            SimpleNamespace(
                sandbox_id=name,
                kill=AsyncMock(),
                get_info=AsyncMock(
                    return_value=SimpleNamespace(
                        sandbox_id=name, allow_internet_access=False, network=None
                    )
                ),
            )
        )
    p._sandbox.fork = AsyncMock(side_effect=[[children[0]], [children[1]]])
    a = await p.fork(expected_execution_id="vm-source", operation_id="a")
    b = await p.fork(expected_execution_id="vm-source", operation_id="b")
    assert len({p.execution_id, a.execution_id, b.execution_id}) == 3
    await a.close()
    assert b.execution_id == "child-b" and p.execution_id == "vm-source"
    assert children[1].kill.await_count == 0
    p._native_children.clear()  # Simulated controller restart with durable journal.
    with pytest.raises(ExecutionError, match="reconcile"):
        await p.fork(expected_execution_id="vm-source", operation_id="b")
    assert p._sandbox.fork.await_count == 2


async def test_hardlink_root_symlink_and_archive_limits(tmp_path):
    import os

    p = provider(tmp_path)
    await p.upload_file("a", b"x", expected_execution_id="vm-source")
    os.link(tmp_path / "workspace/a", tmp_path / "workspace/b")
    with pytest.raises(ExecutionError):
        await p.download_file("a", expected_execution_id="vm-source")
    with pytest.raises(ExecutionError):
        WorkspaceArchive.build({"a": b"x" * 32769})
    with pytest.raises(ExecutionError):
        WorkspaceArchive.build({str(i): b"x" for i in range(65)})
    p.workspace_root = str(tmp_path / "rootlink")
    (tmp_path / "rootlink").symlink_to(tmp_path / "workspace")
    with pytest.raises(ExecutionError):
        await p.upload_file("a", b"x", expected_execution_id="vm-source")


async def test_replay_rejects_changed_configuration_and_source_egress(tmp_path):
    p = provider(tmp_path)
    await p.pause(expected_execution_id="vm-source", operation_id="p")
    p.timeout_seconds = 200
    with pytest.raises(ExecutionError, match="changed"):
        await p.pause(expected_execution_id="vm-source", operation_id="p")
    p._paused = False
    p._sandbox.fork = AsyncMock()
    p._sandbox.get_info.return_value.allow_internet_access = True
    with pytest.raises(ExecutionError):
        await p.fork(expected_execution_id="vm-source", operation_id="unsafe")
    p._sandbox.fork.assert_not_awaited()


async def test_snapshot_source_requires_explicit_resume(tmp_path):
    from e2b.sandbox.sandbox_api import SnapshotInfo

    from physharness.execution.types import CommandRequest

    p = provider(tmp_path)
    p._sandbox.create_snapshot = AsyncMock(return_value=SnapshotInfo(snapshot_id="s:v1"))
    checkpoint = await p.snapshot(expected_execution_id="vm-source", operation_id="s")
    with pytest.raises(ExecutionError, match="paused"):
        await p.run(CommandRequest(operation_id="cmd", argv=["true"]))
    await p.resume(checkpoint, operation_id="resume-snapshot-source")
    assert not p._paused


async def test_concurrent_create_allocates_only_once(monkeypatch):
    import asyncio

    from e2b import AsyncSandbox

    entered = asyncio.Event()
    release = asyncio.Event()

    async def create(**kwargs):
        entered.set()
        await release.wait()
        return SimpleNamespace(sandbox_id="only-vm")

    factory = AsyncMock(side_effect=create)
    monkeypatch.setattr(AsyncSandbox, "create", factory)
    p = E2BSandboxProvider(api_key="test", template_id="qualified")
    first = asyncio.create_task(p.create())
    await entered.wait()
    try:
        with pytest.raises(ExecutionError, match="progress|active|conflict"):
            await asyncio.wait_for(p.create(), timeout=0.05)
    finally:
        release.set()
        await first
    assert factory.await_count == 1


@pytest.mark.parametrize("mode", ["fork", "restore"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_child_journal_failure_retains_identity_and_attempts_cleanup(
    tmp_path, monkeypatch, mode, cleanup_fails
):
    from e2b import AsyncSandbox

    p = provider(tmp_path)
    child = SimpleNamespace(
        sandbox_id="known-child",
        kill=AsyncMock(),
        get_info=AsyncMock(
            return_value=SimpleNamespace(
                sandbox_id="known-child", allow_internet_access=False, network=None
            )
        ),
    )
    if cleanup_fails:
        child.kill.side_effect = OSError("cleanup failure")
    p._sandbox.fork = AsyncMock(return_value=[child])
    monkeypatch.setattr(AsyncSandbox, "create", AsyncMock(return_value=child))

    def failed_commit(*args):
        raise OSError("database write failure")

    monkeypatch.setattr(p.journal, "complete", failed_commit)
    checkpoint = NativeWorkspaceCheckpoint.build(
        kind="snapshot",
        execution_id="vm-source",
        template_id=p.template_id,
        snapshot_id="snapshot:qualified",
    )
    with pytest.raises(ExecutionError, match="known-child") as error:
        if mode == "fork":
            await p.fork(expected_execution_id="vm-source", operation_id="allocation")
        else:
            await p.restore_snapshot(
                checkpoint, operation_id="allocation", pinned_snapshot_id="snapshot:qualified"
            )
    assert error.value.code == "OPERATION_UNCERTAIN"
    child.kill.assert_awaited_once()
    assert p.native_child_observations["allocation"]["execution_id"] == "known-child"
    assert p.native_child_observations["allocation"]["destruction_confirmed"] is not cleanup_fails
    assert p.journal.export("e2b:vm-source")[0]["status"] == "pending"


@pytest.mark.parametrize("failure", ["timeout", "cancel", "transport"])
async def test_uncertain_file_transfer_quarantines_and_terminates(tmp_path, failure):
    import asyncio

    from e2b import TimeoutException

    from physharness.execution.types import CommandRequest

    p = provider(tmp_path)
    sandbox = p._sandbox
    error = {
        "timeout": TimeoutException("timeout"),
        "cancel": asyncio.CancelledError(),
        "transport": OSError("connection lost"),
    }[failure]
    sandbox.commands = SimpleNamespace(run=AsyncMock(side_effect=error))
    with pytest.raises((ExecutionError, asyncio.CancelledError)):
        await p.upload_file("a", b"x", expected_execution_id="vm-source")
    sandbox.kill.assert_awaited_once()
    assert p.last_execution_observation == {
        "execution_id": "vm-source",
        "destruction_confirmed": True,
    }
    with pytest.raises(ExecutionError):
        await p.run(CommandRequest(operation_id="later", argv=["true"]))


async def test_file_transfer_failed_cleanup_keeps_identity_and_blocks_reuse(tmp_path):
    from physharness.execution.types import CommandRequest

    p = provider(tmp_path)
    p._sandbox.commands = SimpleNamespace(run=AsyncMock(side_effect=OSError("lost")))
    p._sandbox.kill.side_effect = OSError("kill unknown")
    with pytest.raises(ExecutionError, match="vm-source"):
        await p.upload_file("a", b"x", expected_execution_id="vm-source")
    assert p.last_execution_observation["destruction_confirmed"] is False
    with pytest.raises(ExecutionError, match="reconcil"):
        await p.run(CommandRequest(operation_id="later", argv=["true"]))


async def test_definite_helper_rejection_preserves_existing_vm_data(tmp_path):
    p = provider(tmp_path)
    sandbox = p._sandbox
    await p.upload_file("valuable", b"keep me", expected_execution_id="vm-source")
    with pytest.raises(ExecutionError):
        await p.restore_workspace(
            WorkspaceArchive.build({"other": b"new"}), expected_execution_id="vm-source"
        )
    sandbox.kill.assert_not_awaited()
    assert await p.download_file("valuable", expected_execution_id="vm-source") == b"keep me"
    with pytest.raises(ExecutionError):
        await p.download_file("missing", expected_execution_id="vm-source")
    sandbox.kill.assert_not_awaited()


async def test_repeated_create_rejection_does_not_quarantine_healthy_vm(tmp_path):
    p = provider(tmp_path)
    with pytest.raises(ExecutionError):
        await p.create()
    assert not p._quarantined
    await p.upload_file("healthy", b"ok", expected_execution_id="vm-source")


async def test_sdk_nonzero_helper_exit_preserves_vm(tmp_path):
    from e2b import CommandExitException

    p = provider(tmp_path)
    sandbox = p._sandbox
    sandbox.commands = SimpleNamespace(
        run=AsyncMock(
            side_effect=CommandExitException(
                stdout="", stderr="assertion failed", exit_code=1, error="nonzero"
            )
        )
    )
    with pytest.raises(ExecutionError, match="preserved"):
        await p.download_file("missing", expected_execution_id="vm-source")
    sandbox.kill.assert_not_awaited()
    assert not p._quarantined


async def test_native_resume_cannot_race_initial_creation(tmp_path, monkeypatch):
    import asyncio

    from e2b import AsyncSandbox

    p = provider(tmp_path)
    p._sandbox = None
    checkpoint = NativeWorkspaceCheckpoint.build(
        kind="pause", execution_id="old-vm", template_id=p.template_id
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def create(**kwargs):
        entered.set()
        await release.wait()
        return SimpleNamespace(sandbox_id="new-vm")

    connect = AsyncMock(return_value=SimpleNamespace(sandbox_id="old-vm"))
    monkeypatch.setattr(AsyncSandbox, "create", AsyncMock(side_effect=create))
    monkeypatch.setattr(AsyncSandbox, "connect", connect)
    pending = asyncio.create_task(p.create())
    await entered.wait()
    try:
        with pytest.raises(ExecutionError, match="progress|active"):
            await p.resume(checkpoint, operation_id="resume")
    finally:
        release.set()
        await pending
    connect.assert_not_awaited()
    assert p.execution_id == "new-vm"


@pytest.mark.parametrize("failure_kind", ["transport", "sdk_timeout", "wall_timeout", "cancel"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_uncertain_command_quarantines_without_dispatching_again(
    tmp_path, failure_kind, cleanup_fails
):
    import asyncio

    from e2b import TimeoutException

    from physharness.execution.types import CommandRequest

    p = provider(tmp_path)
    sandbox = p._sandbox
    failure = {
        "transport": OSError("lost transport"),
        "sdk_timeout": TimeoutException("timeout"),
        "wall_timeout": TimeoutError(),
        "cancel": asyncio.CancelledError(),
    }[failure_kind]
    sandbox.commands = SimpleNamespace(
        run=AsyncMock(
            side_effect=[failure, SimpleNamespace(stdout="second dispatch", stderr="", exit_code=0)]
        )
    )
    if cleanup_fails:
        sandbox.kill.side_effect = OSError("cleanup transport failed")
    with pytest.raises((ExecutionError, asyncio.CancelledError)) as error:
        await p.run(CommandRequest(operation_id="uncertain", argv=["true"]))
    assert p._quarantined
    assert p.last_execution_observation == {
        "execution_id": "vm-source",
        "destruction_confirmed": not cleanup_fails,
    }
    if not isinstance(error.value, asyncio.CancelledError):
        assert "vm-source" in str(error.value)
    with pytest.raises(ExecutionError, match="reconcil"):
        await p.run(CommandRequest(operation_id="later", argv=["true"]))
    assert sandbox.commands.run.await_count == 1
    sandbox.kill.assert_awaited_once()


async def test_known_nonzero_command_exit_remains_a_normal_result(tmp_path):
    from e2b import CommandExitException

    from physharness.execution.types import CommandRequest

    p = provider(tmp_path)
    sandbox = p._sandbox
    sandbox.commands = SimpleNamespace(
        run=AsyncMock(
            side_effect=[
                CommandExitException(
                    stderr="known failure", stdout="partial", exit_code=9, error=None
                ),
                SimpleNamespace(stdout="next command", stderr="", exit_code=0),
            ]
        )
    )
    failed = await p.run(CommandRequest(operation_id="first", argv=["false"]))
    assert failed.exit_code == 9 and failed.stdout == "partial"
    assert not p._quarantined and p.last_execution_observation is None
    succeeded = await p.run(CommandRequest(operation_id="next", argv=["true"]))
    assert succeeded.exit_code == 0
    sandbox.kill.assert_not_awaited()


@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_public_cancel_retains_truthful_cleanup_and_blocks_future_runs(
    tmp_path, cleanup_fails
):
    import asyncio

    from physharness.execution.types import CommandRequest

    p = provider(tmp_path)
    sandbox = p._sandbox
    entered, release = asyncio.Event(), asyncio.Event()

    async def command(*args, **kwargs):
        entered.set()
        await release.wait()
        return SimpleNamespace(stdout="finished", stderr="", exit_code=0)

    sandbox.commands = SimpleNamespace(run=AsyncMock(side_effect=command))
    if cleanup_fails:
        sandbox.kill.side_effect = OSError("termination unknown")
    active = asyncio.create_task(p.run(CommandRequest(operation_id="active", argv=["true"])))
    await entered.wait()
    try:
        if cleanup_fails:
            with pytest.raises(ExecutionError, match="vm-source") as error:
                await p.cancel("active")
            assert error.value.code == "OPERATION_UNCERTAIN"
        else:
            assert await p.cancel("active") is True
    finally:
        release.set()
    with pytest.raises(ExecutionError) as stopped:
        await active
    assert f"Destruction confirmed: {not cleanup_fails}" in str(stopped.value)
    assert p.last_execution_observation == {
        "execution_id": "vm-source",
        "destruction_confirmed": not cleanup_fails,
    }
    assert p._quarantined
    with pytest.raises(ExecutionError, match="reconcil"):
        await p.run(CommandRequest(operation_id="next", argv=["true"]))
    assert sandbox.commands.run.await_count == 1
    sandbox.kill.assert_awaited_once()


@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_close_quarantines_before_kill_and_serializes_cleanup(tmp_path, cleanup_fails):
    import asyncio

    from physharness.execution.types import CommandRequest

    p = provider(tmp_path)
    sandbox = p._sandbox
    sandbox.commands = SimpleNamespace(run=AsyncMock())
    entered, release = asyncio.Event(), asyncio.Event()

    async def kill():
        entered.set()
        await release.wait()
        if cleanup_fails:
            raise OSError("unknown cleanup")
        return True

    sandbox.kill = AsyncMock(side_effect=kill)
    closing = asyncio.create_task(p.close())
    await entered.wait()
    try:
        assert p._quarantined
        with pytest.raises(ExecutionError):
            await p.close()
        with pytest.raises(ExecutionError, match="reconcil"):
            await p.run(CommandRequest(operation_id="during-close", argv=["true"]))
    finally:
        release.set()
    if cleanup_fails:
        with pytest.raises(ExecutionError, match="vm-source"):
            await closing
    else:
        await closing
    assert p.last_execution_observation == {
        "execution_id": "vm-source",
        "destruction_confirmed": not cleanup_fails,
    }
    sandbox.commands.run.assert_not_awaited()
    sandbox.kill.assert_awaited_once()


async def test_cancelled_close_preserves_unconfirmed_vm_identity(tmp_path):
    import asyncio

    from physharness.execution.types import CommandRequest

    p = provider(tmp_path)
    entered = asyncio.Event()

    async def kill():
        entered.set()
        await asyncio.Event().wait()

    p._sandbox.kill = AsyncMock(side_effect=kill)
    closing = asyncio.create_task(p.close())
    await entered.wait()
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert p._quarantined
    assert p.last_execution_observation == {
        "execution_id": "vm-source",
        "destruction_confirmed": False,
    }
    with pytest.raises(ExecutionError):
        await p.run(CommandRequest(operation_id="after-interrupted-close", argv=["true"]))


async def test_public_cancel_blocks_next_run_while_kill_is_pending(tmp_path):
    import asyncio

    from physharness.execution.types import CommandRequest

    p = provider(tmp_path)
    sandbox = p._sandbox
    command_started, command_release = asyncio.Event(), asyncio.Event()
    kill_started, kill_release = asyncio.Event(), asyncio.Event()

    async def command(*args, **kwargs):
        command_started.set()
        await command_release.wait()
        return SimpleNamespace(stdout="done", stderr="", exit_code=0)

    async def kill():
        kill_started.set()
        await kill_release.wait()
        return True

    sandbox.commands = SimpleNamespace(run=AsyncMock(side_effect=command))
    sandbox.kill = AsyncMock(side_effect=kill)
    active = asyncio.create_task(p.run(CommandRequest(operation_id="first", argv=["true"])))
    await command_started.wait()
    cancelling = asyncio.create_task(p.cancel("first"))
    await kill_started.wait()
    try:
        command_release.set()
        with pytest.raises(ExecutionError, match="Destruction confirmed: False"):
            await active
        assert not p._active
        with pytest.raises(ExecutionError, match="reconcil"):
            await p.run(CommandRequest(operation_id="second", argv=["true"]))
        assert p.last_execution_observation["destruction_confirmed"] is False
    finally:
        kill_release.set()
        await cancelling
    assert sandbox.commands.run.await_count == 1
    sandbox.kill.assert_awaited_once()
    assert p.last_execution_observation["destruction_confirmed"] is True


async def test_close_refuses_inflight_native_operation(tmp_path):
    import asyncio

    p = provider(tmp_path)
    sandbox = p._sandbox
    started, release = asyncio.Event(), asyncio.Event()

    async def pause(**kwargs):
        started.set()
        await release.wait()
        return True

    sandbox.pause = AsyncMock(side_effect=pause)
    pending = asyncio.create_task(p.pause(expected_execution_id="vm-source", operation_id="p"))
    await started.wait()
    try:
        with pytest.raises(ExecutionError, match="progress|active"):
            await p.close()
        sandbox.kill.assert_not_awaited()
    finally:
        release.set()
        await pending
