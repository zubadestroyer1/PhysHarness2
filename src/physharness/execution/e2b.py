"""Optional E2B AsyncSandbox provider (verified with e2b 2.49.1).

Remote execution returns bounded output, but E2B SDK may buffer full remote
streams internally. Use provider limits for adversarial large-output workloads.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import posixpath
import shlex
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .storage import CommandJournal
from .types import Capabilities, CommandRequest, CommandResult, ExecutionError

# Portable archives intentionally contain regular files only. The canonical JSON
# envelope is small enough for one bounded, shell-quoted helper invocation.
ARCHIVE_LIMIT = 65_536
FILE_LIMIT = 32_768
FILE_COUNT_LIMIT = 64


def _path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode()) > 256
        or "\\" in value
        or "\x00" in value
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ExecutionError("UNSAFE_PATH", "Workspace path must be a canonical relative file path")
    return value


def _json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


@dataclass(frozen=True)
class WorkspaceArchive:
    """Canonical physharness.workspace.v1 JSON bytes, not a tar/zip or VM snapshot."""

    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def to_bytes(self) -> bytes:
        return self.data

    @classmethod
    def build(cls, files: dict[str, bytes]) -> WorkspaceArchive:
        if len(files) > FILE_COUNT_LIMIT:
            raise ExecutionError("WORKSPACE_LIMIT", "Workspace has too many files")
        entries = []
        for path, data in sorted(files.items()):
            _path(path)
            if not isinstance(data, bytes) or len(data) > FILE_LIMIT:
                raise ExecutionError("WORKSPACE_LIMIT", "Workspace file exceeds byte limit")
            if any("/".join(path.split("/")[:i]) in files for i in range(1, len(path.split("/")))):
                raise ExecutionError("UNSAFE_PATH", "File shadows a workspace directory")
            entries.append(
                {
                    "path": path,
                    "data": base64.b64encode(data).decode(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        encoded = _json({"format": "physharness.workspace.v1", "files": entries})
        if len(encoded) > ARCHIVE_LIMIT:
            raise ExecutionError(
                "WORKSPACE_LIMIT", "Canonical workspace archive exceeds byte limit"
            )
        return cls(encoded)

    @classmethod
    def from_bytes(cls, data: bytes, *, sha256: str) -> WorkspaceArchive:
        if len(data) > ARCHIVE_LIMIT:
            raise ExecutionError("WORKSPACE_LIMIT", "Workspace archive exceeds byte limit")
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ExecutionError("CHECKPOINT_MISMATCH", "Workspace archive checksum mismatch")
        try:
            obj = json.loads(data)
            if set(obj) != {"format", "files"} or obj["format"] != "physharness.workspace.v1":
                raise ValueError("Unsupported archive format")
            files = {}
            for entry in obj["files"]:
                if set(entry) != {"path", "data", "sha256"} or entry["path"] in files:
                    raise ValueError("Unexpected or duplicate file entry")
                content = base64.b64decode(entry["data"], validate=True)
                if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                    raise ValueError("File checksum mismatch")
                files[entry["path"]] = content
            archive = cls.build(files)
            if archive.data != data:
                raise ValueError("Archive is not canonical")
            return archive
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
            raise ExecutionError("INVALID_ARCHIVE", "Invalid canonical workspace archive") from exc

    def files(self) -> dict[str, bytes]:
        checked = self.from_bytes(self.data, sha256=self.sha256)
        return {
            entry["path"]: base64.b64decode(entry["data"], validate=True)
            for entry in json.loads(checked.data)["files"]
        }


class NativeWorkspaceCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    kind: Literal["pause", "snapshot"]
    execution_id: str
    template_id: str
    snapshot_id: str | None = None
    state_sha256: str

    @classmethod
    def build(
        cls, *, kind: str, execution_id: str, template_id: str, snapshot_id: str | None = None
    ) -> NativeWorkspaceCheckpoint:
        state = dict(
            version=1,
            kind=kind,
            execution_id=execution_id,
            template_id=template_id,
            snapshot_id=snapshot_id,
        )
        return cls(**state, state_sha256=hashlib.sha256(_json(state)).hexdigest())

    def verify(self) -> None:
        state = self.model_dump(exclude={"state_sha256"})
        if hashlib.sha256(_json(state)).hexdigest() != self.state_sha256:
            raise ExecutionError("CHECKPOINT_MISMATCH", "Native checkpoint checksum mismatch")


# Executed inside the VM only. Open every component with O_NOFOLLOW, reject
# symlinks/hardlinks/devices, and replace regular files atomically by directory FD.
# Payload is JSON data; it is never evaluated as Python or shell code.
_WORKSPACE_HELPER = r"""
import base64, json, os, stat, sys, uuid
req = json.loads(base64.b64decode(sys.argv[1], validate=True))
flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
root = os.open('/', flags)
for part in req['root'].split('/')[1:]:
    try: os.mkdir(part, mode=0o700, dir_fd=root)
    except FileExistsError: pass
    nxt = os.open(part, flags, dir_fd=root)
    os.close(root)
    root = nxt

def parent(path):
    parts = path.split('/')
    assert all(p not in ('', '.', '..') and '\\' not in p and '\x00' not in p for p in parts)
    fd = os.dup(root)
    for part in parts[:-1]:
        try: os.mkdir(part, mode=0o700, dir_fd=fd)
        except FileExistsError: pass
        nxt = os.open(part, flags, dir_fd=fd)
        os.close(fd)
        fd = nxt
    return fd, parts[-1]

def read(fd, name):
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        info = os.fstat(handle)
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 32768
        with os.fdopen(os.dup(handle), 'rb') as stream: data = stream.read(32769)
        assert len(data) <= 32768
        return base64.b64encode(data).decode()
    finally: os.close(handle)

def walk(fd, prefix='', result=None):
    if result is None: result = {}
    for name in sorted(os.listdir(fd)):
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        path = prefix + name
        assert len(path.encode()) <= 256
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, flags, dir_fd=fd)
            try: walk(child, path + '/', result)
            finally: os.close(child)
        else:
            assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            assert len(result) < 64
            result[path] = read(fd, name)
            assert sum(len(v) for v in result.values()) <= 65536
    return result

def write(path, data):
    fd, name = parent(path)
    temp = '.physharness-' + uuid.uuid4().hex
    try:
        try:
            old = os.stat(name, dir_fd=fd, follow_symlinks=False)
            assert stat.S_ISREG(old.st_mode) and old.st_nlink == 1
        except FileNotFoundError: pass
        handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=fd)
        with os.fdopen(handle, 'wb') as out:
            out.write(base64.b64decode(data, validate=True))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
    finally:
        try: os.unlink(temp, dir_fd=fd)
        except FileNotFoundError: pass
        os.close(fd)

if req['action'] == 'read':
    fd, name = parent(req['path'])
    try: result = {'data': read(fd, name)}
    finally: os.close(fd)
elif req['action'] == 'write':
    write(req['path'], req['data'])
    result = {'written': True}
elif req['action'] == 'export': result = {'files': walk(root)}
elif req['action'] == 'restore':
    existing = walk(root)
    assert not existing or existing == req['files'], 'Restore requires empty or identical workspace'
    if not existing:
        for path, data in sorted(req['files'].items()): write(path, data)
    assert walk(root) == req['files']
    result = {'restored': True}
else: raise ValueError('Unknown action')
os.close(root)
print(json.dumps(result, sort_keys=True, separators=(',', ':')))
"""


class E2BSandboxProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        template_id: str | None = None,
        timeout_seconds: int = 300,
        workspace_root: str = "/home/user/workspace",
        journal: CommandJournal | None = None,
    ):
        if timeout_seconds <= 0:
            raise ValueError("Sandbox timeout must be positive")
        if not workspace_root.startswith("/") or workspace_root == "/":
            raise ValueError("Workspace root must be an absolute non-root path")
        _path(workspace_root[1:])
        self.workspace_root = workspace_root
        self.journal = journal
        self._native_children: dict[str, E2BSandboxProvider] = {}
        self._paused = False
        self._creating = False
        self._closing = False
        self._workspace_active = False
        self._quarantined = False
        self.native_child_observations: dict[str, dict[str, Any]] = {}
        self.last_execution_observation: dict[str, Any] | None = None
        self.api_key = api_key
        self.template_id = template_id
        self.timeout_seconds = timeout_seconds
        self._sandbox: Any = None
        self._active: set[str] = set()
        self._cancelled: set[str] = set()
        self.network_disabled = True
        configured = bool(api_key and template_id and template_id.strip() == template_id)
        self.capabilities = Capabilities(
            available=configured,
            start=configured,
            interrupt=configured,
            isolation="provider_vm",
            reason=None if configured else "Exact template ID and E2B API key required",
        )

    async def create(self) -> E2BSandboxProvider:
        if self._sandbox is not None:
            raise ExecutionError("OPERATION_CONFLICT", "Provider already owns a VM")
        if self._creating or self._active:
            raise ExecutionError(
                "OPERATION_CONFLICT", "VM creation or another operation is in progress"
            )
        if self._quarantined:
            raise ExecutionError(
                "OPERATION_UNCERTAIN", "Provider requires reconciliation before reuse"
            )
        self._creating = True
        try:
            return await self._create_once()
        except ExecutionError as exc:
            if exc.code not in {"PROVIDER_UNAVAILABLE", "OPERATION_CONFLICT"}:
                self._quarantined = True
            raise
        except BaseException:
            self._quarantined = True
            raise
        finally:
            self._creating = False

    async def _create_once(self) -> E2BSandboxProvider:
        if not self.capabilities.available:
            raise ExecutionError(
                "PROVIDER_UNAVAILABLE",
                "E2B requires an API key and exact template ID",
                remediation="Set E2B_API_KEY and an explicitly qualified template ID",
            )
        if self._sandbox is not None:
            raise ExecutionError(
                "OPERATION_CONFLICT",
                "Provider already owns a VM; create another provider for a new execution identity",
            )
        try:
            from e2b import AsyncSandbox
        except ImportError as exc:
            raise ExecutionError(
                "PROVIDER_UNAVAILABLE",
                "Optional E2B SDK unavailable",
                remediation="Install physharness[e2b] (e2b>=2.49,<3)",
            ) from exc
        try:
            self._sandbox = await AsyncSandbox.create(
                template=self.template_id,
                api_key=self.api_key,
                timeout=self.timeout_seconds,
                allow_internet_access=False,
                secure=True,
                envs={},
            )
        except Exception as exc:
            raise ExecutionError(
                "PROVIDER_FAILED",
                "E2B sandbox creation failed; configured template was not substituted",
            ) from exc
        return self

    @property
    def execution_id(self) -> str:
        if self._sandbox is None:
            raise ExecutionError("SESSION_NOT_READY", "E2B VM has not been created")
        return self._sandbox.sandbox_id

    async def run(self, request: CommandRequest) -> CommandResult:
        if self._quarantined:
            raise ExecutionError("OPERATION_UNCERTAIN", "VM requires reconciliation before reuse")
        if self._sandbox is None:
            raise ExecutionError("SESSION_NOT_READY", "Call create() before running E2B commands")
        if self._paused:
            raise ExecutionError("SESSION_NOT_READY", "VM is paused; explicitly resume it first")
        if self._active:
            raise ExecutionError(
                "OPERATION_CONFLICT",
                "One command per VM is required for reliable VM-wide cancellation",
            )
        # Relative command directories share the file transfer/archive root.
        # Explicit absolute guest directories are preserved; their files are
        # outside portable exports unless they reside beneath workspace_root.
        if request.cwd == ".":
            cwd = self.workspace_root
        elif request.cwd.startswith("/"):
            cwd = request.cwd
        else:
            cwd = posixpath.join(self.workspace_root, _path(request.cwd))
        self._active.add(request.operation_id)
        execution_id = self.execution_id
        try:
            async with asyncio.timeout(request.timeout_seconds):
                result = await self._sandbox.commands.run(
                    shlex.join(request.argv),
                    cwd=cwd,
                    envs=request.env,
                    timeout=request.timeout_seconds,
                )
            if request.operation_id in self._cancelled:
                raise self._cancellation_result(execution_id, request.operation_id)
            out, err = result.stdout.encode(), result.stderr.encode()
            return CommandResult(
                operation_id=request.operation_id,
                execution_id=execution_id,
                exit_code=result.exit_code,
                stdout=out[: request.max_output_bytes].decode(errors="ignore"),
                stderr=err[: request.max_output_bytes].decode(errors="ignore"),
                stdout_truncated=len(out) > request.max_output_bytes,
                stderr_truncated=len(err) > request.max_output_bytes,
            )
        except TimeoutError as exc:
            confirmed = await self._quarantine_command(execution_id)
            raise ExecutionError(
                "TIMEOUT",
                f"VM {execution_id} command exceeded wall-clock limit; reconcile. "
                f"Destruction confirmed: {confirmed}.",
                operation_id=request.operation_id,
            ) from exc
        except asyncio.CancelledError:
            await self._quarantine_command(execution_id)
            raise
        except ExecutionError:
            raise
        except Exception as exc:
            if request.operation_id in self._cancelled:
                raise self._cancellation_result(execution_id, request.operation_id) from exc
            # Nonzero command exits are raised by the SDK with actual result fields.
            from e2b import CommandExitException, TimeoutException

            if isinstance(exc, TimeoutException):
                confirmed = await self._quarantine_command(execution_id)
                raise ExecutionError(
                    "TIMEOUT",
                    f"VM {execution_id} command timed out; reconcile. "
                    f"Destruction confirmed: {confirmed}.",
                    operation_id=request.operation_id,
                ) from exc

            if isinstance(exc, CommandExitException):
                return CommandResult(
                    operation_id=request.operation_id,
                    execution_id=execution_id,
                    exit_code=exc.exit_code,
                    stdout=exc.stdout.encode()[: request.max_output_bytes].decode(errors="ignore"),
                    stderr=exc.stderr.encode()[: request.max_output_bytes].decode(errors="ignore"),
                    stdout_truncated=len(exc.stdout.encode()) > request.max_output_bytes,
                    stderr_truncated=len(exc.stderr.encode()) > request.max_output_bytes,
                )
            confirmed = await self._quarantine_command(execution_id)
            raise ExecutionError(
                "PROVIDER_FAILED",
                f"VM {execution_id} command outcome is unknown; reconcile. "
                f"Destruction confirmed: {confirmed}.",
                operation_id=request.operation_id,
            ) from exc
        finally:
            self._active.discard(request.operation_id)
            self._cancelled.discard(request.operation_id)

    def _cancellation_result(self, execution_id: str, operation_id: str) -> ExecutionError:
        observation = self.last_execution_observation or {}
        confirmed = (
            observation.get("execution_id") == execution_id
            and observation.get("destruction_confirmed") is True
        )
        return ExecutionError(
            "CANCELLED" if confirmed else "OPERATION_UNCERTAIN",
            f"Cancellation requested for VM {execution_id}; reconcile. "
            f"Destruction confirmed: {confirmed}.",
            operation_id=operation_id,
        )

    async def _quarantine_command(self, execution_id: str) -> bool:
        """A lost command stream does not prove the guest process has stopped."""
        self._quarantined = True
        if (
            self.last_execution_observation is None
            or self.last_execution_observation.get("execution_id") != execution_id
        ):
            self.last_execution_observation = {
                "execution_id": execution_id,
                "destruction_confirmed": False,
            }
        try:
            await self.close()
        except BaseException:
            # Cleanup records its own outcome. Preserve the original command or
            # cancellation exception, and never retry an already running kill.
            pass
        observation = self.last_execution_observation or {}
        return (
            observation.get("execution_id") == execution_id
            and observation.get("destruction_confirmed") is True
        )

    async def cancel(self, operation_id: str) -> bool:
        if self._workspace_active:
            raise ExecutionError("OPERATION_CONFLICT", "Native workspace operation is in progress")
        if operation_id not in self._active:
            return False
        self._cancelled.add(operation_id)
        execution_id = (
            self._sandbox.sandbox_id
            if self._sandbox is not None
            else (self.last_execution_observation or {}).get("execution_id")
        )
        if not execution_id:
            self._quarantined = True
            raise ExecutionError(
                "OPERATION_UNCERTAIN", "Cancellation has no known VM identity; reconcile"
            )
        if not await self._quarantine_command(execution_id):
            raise self._cancellation_result(execution_id, operation_id)
        return True

    async def close(self) -> None:
        if self._workspace_active:
            raise ExecutionError("OPERATION_CONFLICT", "Native workspace operation is in progress")
        await self._close_vm()

    async def _close_vm(self) -> None:
        """Internal cleanup also works from the operation that currently owns the VM."""
        if self._creating or self._closing:
            raise ExecutionError("OPERATION_CONFLICT", "VM creation or cleanup is in progress")
        if self._sandbox is None:
            if self._active and not (self.last_execution_observation or {}).get(
                "destruction_confirmed"
            ):
                raise ExecutionError("OPERATION_CONFLICT", "Native connection is still in progress")
            return
        sandbox = self._sandbox
        execution_id = sandbox.sandbox_id
        self._closing = True
        self._quarantined = True
        self._cancelled.update(self._active)
        observation = {"execution_id": execution_id, "destruction_confirmed": False}
        self.last_execution_observation = observation
        try:
            async with asyncio.timeout(min(self.timeout_seconds, 10)):
                await sandbox.kill()
            self._sandbox = None
            self._paused = False
            observation["destruction_confirmed"] = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ExecutionError(
                "OPERATION_UNCERTAIN",
                f"VM {execution_id} destruction is unconfirmed; reconcile. "
                "Destruction confirmed: False.",
            ) from exc
        finally:
            self._closing = False

    @property
    def workspace_capabilities(self) -> dict[str, Any]:
        return {
            "portable_regular_files": self.capabilities.available,
            "portable_process_memory": False,
            "native_pause_resume_same_identity": self.capabilities.available
            and self.journal is not None,
            "native_snapshot": self.capabilities.available and self.journal is not None,
            "native_fork_new_identity": self.capabilities.available and self.journal is not None,
            "native_snapshot_restore_requires_operator_pin": True,
            "live_qualified": False,
            "archive_max_bytes": ARCHIVE_LIMIT,
            "file_max_bytes": FILE_LIMIT,
            "file_count_max": FILE_COUNT_LIMIT,
        }

    def _identity(self, expected: str) -> None:
        if self.execution_id != expected:
            raise ExecutionError("CHECKPOINT_MISMATCH", "Native execution identity is stale")

    @asynccontextmanager
    async def _exclusive(
        self, expected: str, *, allow_paused: bool = False, allow_missing: bool = False
    ):
        if self._quarantined:
            raise ExecutionError("OPERATION_UNCERTAIN", "VM requires reconciliation before reuse")
        if self._creating:
            raise ExecutionError("OPERATION_CONFLICT", "VM creation is in progress")
        if not (allow_missing and self._sandbox is None):
            self._identity(expected)
        if self._active:
            raise ExecutionError("OPERATION_CONFLICT", "VM already has an active operation")
        if self._paused and not allow_paused:
            raise ExecutionError("SESSION_NOT_READY", "VM is paused; explicitly resume first")
        self._active.add("workspace")
        self._workspace_active = True
        try:
            yield
        finally:
            self._workspace_active = False
            self._active.discard("workspace")

    async def _file_action(self, action: str, **payload: Any) -> dict[str, Any]:
        request = base64.b64encode(
            _json(dict(root=self.workspace_root, action=action, **payload))
        ).decode()
        if len(request) > 100_000:
            raise ExecutionError("WORKSPACE_LIMIT", "Workspace transfer exceeds command envelope")
        completed = False
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self._sandbox.commands.run(
                    shlex.join(["python3", "-I", "-c", _WORKSPACE_HELPER, request]),
                    envs={},
                    timeout=self.timeout_seconds,
                )
            completed = True
            if result.exit_code != 0 or len(result.stdout.encode()) > 100_000:
                raise ValueError("Workspace helper failed or response exceeded limit")
            value = json.loads(result.stdout)
            if not isinstance(value, dict):
                raise ValueError("Invalid workspace response")
            return value
        except BaseException as exc:
            try:
                from e2b import CommandExitException

                completed = completed or isinstance(exc, CommandExitException)
            except ImportError:
                pass
            if completed:
                raise ExecutionError(
                    "WORKSPACE_TRANSFER_REJECTED",
                    "Workspace helper completed unsuccessfully; inspect files before retry. "
                    "VM preserved; operation may have changed files.",
                ) from exc
            execution_id = self.execution_id
            self._quarantined = True
            confirmed = False
            try:
                async with asyncio.timeout(min(self.timeout_seconds, 10)):
                    await self._close_vm()
                confirmed = True
            except BaseException:
                pass  # Quarantine remains in force; retain identity and cleanup outcome below.
            self.last_execution_observation = {
                "execution_id": execution_id,
                "destruction_confirmed": confirmed,
            }
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise ExecutionError(
                "WORKSPACE_TRANSFER_FAILED",
                f"Workspace transfer for VM {execution_id} failed; reconcile VM and writes. "
                f"Destruction confirmed: {confirmed}.",
            ) from exc

    async def upload_file(self, path: str, data: bytes, *, expected_execution_id: str) -> str:
        archive = WorkspaceArchive.build({_path(path): data})
        async with self._exclusive(expected_execution_id):
            await self._file_action("write", path=path, data=base64.b64encode(data).decode())
        return archive.sha256

    async def download_file(self, path: str, *, expected_execution_id: str) -> bytes:
        _path(path)
        async with self._exclusive(expected_execution_id):
            result = await self._file_action("read", path=path)
        try:
            data = base64.b64decode(result["data"], validate=True)
            WorkspaceArchive.build({path: data})
            return data
        except (ValueError, TypeError, KeyError) as exc:
            raise ExecutionError("INVALID_ARCHIVE", "VM returned invalid file data") from exc

    async def export_workspace(self, *, expected_execution_id: str) -> WorkspaceArchive:
        async with self._exclusive(expected_execution_id):
            result = await self._file_action("export")
        try:
            return WorkspaceArchive.build(
                {
                    path: base64.b64decode(data, validate=True)
                    for path, data in result["files"].items()
                }
            )
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
            raise ExecutionError("INVALID_ARCHIVE", "VM returned invalid workspace data") from exc

    async def restore_workspace(
        self, archive: WorkspaceArchive, *, expected_execution_id: str
    ) -> None:
        files = archive.files()  # Validate the entire archive before writing any VM file.
        async with self._exclusive(expected_execution_id):
            await self._file_action(
                "restore",
                files={path: base64.b64encode(data).decode() for path, data in files.items()},
            )

    def _begin_native(
        self, execution_id: str, operation_id: str | None, command: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not self.capabilities.available or self.journal is None or not operation_id:
            raise ExecutionError(
                "CAPABILITY_UNAVAILABLE",
                f"Native {command} requires a durable journal and operation ID",
            )
        return self.journal.begin(
            "e2b:" + execution_id,
            operation_id,
            command,
            {
                "template_id": self.template_id,
                "workspace_root": self.workspace_root,
                "timeout_seconds": self.timeout_seconds,
                "arguments": arguments,
            },
        )

    def _complete_native(
        self, execution_id: str, operation_id: str, result: dict[str, Any]
    ) -> None:
        assert self.journal is not None
        self.journal.complete("e2b:" + execution_id, operation_id, result)

    async def _verify_network(self, sandbox: Any, expected: str) -> None:
        info = await sandbox.get_info()
        network = info.network or {}
        if (
            info.sandbox_id != expected
            or info.allow_internet_access is not False
            or network.get("allow_out")
            or network.get("rules")
            or network.get("egress_proxy")
        ):
            raise ExecutionError(
                "NETWORK_POLICY_UNVERIFIED",
                "Native VM identity or inherited no-egress policy is unverified",
            )

    async def pause(
        self, *, expected_execution_id: str, operation_id: str
    ) -> NativeWorkspaceCheckpoint:
        async with self._exclusive(expected_execution_id, allow_paused=True):
            replay = self._begin_native(expected_execution_id, operation_id, "pause", {})
            if replay:
                record = NativeWorkspaceCheckpoint.model_validate(replay)
                record.verify()
                return record
            try:
                await self._sandbox.pause(keep_memory=True)
            except Exception as exc:
                raise ExecutionError(
                    "OPERATION_UNCERTAIN", "Native pause failed; reconcile before retry"
                ) from exc
            self._paused = True
            record = NativeWorkspaceCheckpoint.build(
                kind="pause", execution_id=self.execution_id, template_id=self.template_id
            )
            self._complete_native(expected_execution_id, operation_id, record.model_dump())
            return record

    async def resume(self, checkpoint: NativeWorkspaceCheckpoint, *, operation_id: str) -> None:
        checkpoint.verify()
        if checkpoint.template_id != self.template_id:
            raise ExecutionError("CHECKPOINT_MISMATCH", "Native pause checkpoint does not match VM")
        async with self._exclusive(checkpoint.execution_id, allow_paused=True, allow_missing=True):
            if self._begin_native(
                checkpoint.execution_id, operation_id, "resume", checkpoint.model_dump()
            ):
                if self._sandbox is None:
                    raise ExecutionError(
                        "NATIVE_RECONNECT_REQUIRED",
                        "Resume already completed; use a new reconnect operation ID",
                    )
                return
            try:
                if self._sandbox is None:
                    from e2b import AsyncSandbox

                    self._sandbox = await AsyncSandbox.connect(
                        checkpoint.execution_id,
                        timeout=self.timeout_seconds,
                        on_resume="restore",
                        api_key=self.api_key,
                    )
                else:
                    await self._sandbox.connect(timeout=self.timeout_seconds, on_resume="restore")
                await self._verify_network(self._sandbox, checkpoint.execution_id)
            except Exception as exc:
                if self._sandbox is not None:
                    await self._close_vm()
                raise ExecutionError(
                    "OPERATION_UNCERTAIN", "Native resume failed; reconcile VM before retry"
                ) from exc
            self._paused = False
            self._complete_native(checkpoint.execution_id, operation_id, {"resumed": True})

    async def snapshot(
        self, *, expected_execution_id: str, operation_id: str
    ) -> NativeWorkspaceCheckpoint:
        async with self._exclusive(expected_execution_id):
            replay = self._begin_native(expected_execution_id, operation_id, "snapshot", {})
            if replay:
                record = NativeWorkspaceCheckpoint.model_validate(replay)
                record.verify()
                return record
            try:
                info = await self._sandbox.create_snapshot()
                if not isinstance(info.snapshot_id, str) or not info.snapshot_id:
                    raise ValueError("SDK returned no snapshot ID")
            except Exception as exc:
                raise ExecutionError(
                    "OPERATION_UNCERTAIN", "Snapshot result uncertain; reconcile before retry"
                ) from exc
            # SDK snapshot creation pauses the source; require explicit connect even
            # on control planes that resume automatically after snapshot capture.
            self._paused = True
            record = NativeWorkspaceCheckpoint.build(
                kind="snapshot",
                execution_id=expected_execution_id,
                template_id=self.template_id,
                snapshot_id=info.snapshot_id,
            )
            self._complete_native(expected_execution_id, operation_id, record.model_dump())
            return record

    def _child(self, sandbox: Any) -> E2BSandboxProvider:
        child = E2BSandboxProvider(
            api_key=self.api_key,
            template_id=self.template_id,
            timeout_seconds=self.timeout_seconds,
            workspace_root=self.workspace_root,
            journal=self.journal,
        )
        child._sandbox = sandbox
        return child

    def _replay_child(self, operation_id: str, replay: dict[str, Any]) -> E2BSandboxProvider:
        child = self._native_children.get(operation_id)
        if child is None or child.execution_id != replay.get("execution_id"):
            raise ExecutionError(
                "NATIVE_RECONNECT_REQUIRED",
                "Allocation already completed; reconcile recorded child identity "
                "instead of reallocating",
            )
        return child

    async def fork(
        self, *, expected_execution_id: str | None = None, operation_id: str | None = None
    ) -> E2BSandboxProvider:
        if expected_execution_id is None or operation_id is None:
            raise ExecutionError(
                "CAPABILITY_UNAVAILABLE",
                "Native fork requires explicit source identity and operation ID",
            )
        async with self._exclusive(expected_execution_id):
            replay = self._begin_native(expected_execution_id, operation_id, "fork", {})
            if replay:
                return self._replay_child(operation_id, replay)
            sandbox = None
            try:
                await self._verify_network(self._sandbox, expected_execution_id)
                results = await self._sandbox.fork(timeout=self.timeout_seconds, count=1)
                if len(results) != 1 or isinstance(results[0], Exception):
                    raise ValueError("Native fork did not return one successful child")
                sandbox = results[0]
                if sandbox.sandbox_id == expected_execution_id:
                    sandbox = None  # Never kill the source on a malformed provider response.
                    raise ValueError("Native fork reused source identity")
                await self._verify_network(sandbox, sandbox.sandbox_id)
            except Exception as exc:
                if sandbox is not None:
                    await sandbox.kill()
                raise ExecutionError(
                    "OPERATION_UNCERTAIN", "Native fork unverified; reconcile before retry"
                ) from exc
            child = self._child(sandbox)
            await self._commit_child(expected_execution_id, operation_id, child)
            return child

    async def restore_snapshot(
        self,
        checkpoint: NativeWorkspaceCheckpoint,
        *,
        operation_id: str,
        pinned_snapshot_id: str | None = None,
    ) -> E2BSandboxProvider:
        checkpoint.verify()
        snapshot = checkpoint.snapshot_id
        if not snapshot or ":" not in snapshot or snapshot.rsplit(":", 1)[1] == "latest":
            raise ExecutionError(
                "CAPABILITY_UNAVAILABLE",
                "Snapshot reference is mutable or unversioned; pinned restore unavailable",
            )
        if (
            checkpoint.kind != "snapshot"
            or checkpoint.template_id != self.template_id
            or pinned_snapshot_id != snapshot
        ):
            raise ExecutionError(
                "CAPABILITY_UNAVAILABLE",
                "Restore requires matching operator-qualified immutable snapshot reference",
            )
        async with self._exclusive(checkpoint.execution_id, allow_paused=True, allow_missing=True):
            replay = self._begin_native(
                checkpoint.execution_id, operation_id, "restore_snapshot", checkpoint.model_dump()
            )
            if replay:
                return self._replay_child(operation_id, replay)
            sandbox = None
            try:
                from e2b import AsyncSandbox

                sandbox = await AsyncSandbox.create(
                    template=snapshot,
                    api_key=self.api_key,
                    timeout=self.timeout_seconds,
                    allow_internet_access=False,
                    secure=True,
                    envs={},
                )
                if sandbox.sandbox_id == checkpoint.execution_id:
                    sandbox = None
                    raise ValueError("Snapshot restore reused source identity")
                await self._verify_network(sandbox, sandbox.sandbox_id)
            except Exception as exc:
                if sandbox is not None:
                    await sandbox.kill()
                raise ExecutionError(
                    "OPERATION_UNCERTAIN",
                    "Native snapshot restore uncertain; reconcile before retry",
                ) from exc
            child = self._child(sandbox)
            await self._commit_child(checkpoint.execution_id, operation_id, child)
            return child

    async def _commit_child(
        self, source_id: str, operation_id: str, child: E2BSandboxProvider
    ) -> None:
        identity = child.execution_id
        self._native_children[operation_id] = child
        observation = {"execution_id": identity, "destruction_confirmed": False}
        self.native_child_observations[operation_id] = observation
        try:
            self._complete_native(source_id, operation_id, {"execution_id": identity})
        except BaseException as exc:
            child._quarantined = True
            try:
                async with asyncio.timeout(min(self.timeout_seconds, 10)):
                    await child.close()
                observation["destruction_confirmed"] = True
            except BaseException:
                pass
            raise ExecutionError(
                "OPERATION_UNCERTAIN",
                f"Native child {identity} allocation could not be committed; reconcile. "
                f"Destruction confirmed: {observation['destruction_confirmed']}.",
                operation_id=operation_id,
                remediation=f"Retain child identity {identity}; reconcile journal and charges. "
                "Never retry this allocation automatically.",
            ) from exc
