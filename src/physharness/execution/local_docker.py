"""Dedicated-socket Docker workbench. Docker is only a transport to an isolated VM.

No default Docker endpoint, host bind mount, host shell, network, or credentials are
accepted. The caller pins an image digest and supplies the dedicated VM socket.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import shutil
import weakref
from collections.abc import Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from .types import Capabilities, CommandRequest, CommandResult, ExecutionError
from .workspace_archive import CHUNK_SIZE, DEFAULT_QUOTA, WorkspaceArchive, checked_path

_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RUN_LOCKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_GUEST = r"""
import base64, hashlib, json, os, stat, sys
root='/work'
action=sys.argv[1]
path=sys.argv[2] if len(sys.argv)>2 else None
def checked(p):
    parts=p.split('/')
    assert p and all(x not in ('','.','..') and '\\' not in x and '\x00' not in x for x in parts)
    assert not any(
        x in ('.git','.ssh','.aws','.config','__pycache__','.cache','node_modules')
        or x.startswith('.env') or x.endswith('.pyc') for x in parts
    )
    return parts
def parent(p,create=False):
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    parts=checked(p)
    for part in parts[:-1]:
        if create:
            try: os.mkdir(part,mode=0o700,dir_fd=fd)
            except FileExistsError: pass
        nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
        os.close(fd);fd=nxt
    return fd,parts[-1]
def get(p):
    fd,name=parent(p)
    try:
        h=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        try:
            s=os.fstat(h);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
            with os.fdopen(os.dup(h),'rb') as f:return f.read()
        finally:os.close(h)
    finally:os.close(fd)
def put(p,data):
    fd,name=parent(p,True)
    try:
        try:
            s=os.stat(name,dir_fd=fd,follow_symlinks=False)
            assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
        except FileNotFoundError:pass
        temp='.physharness-'+os.urandom(16).hex()
        h=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
        try:
            with os.fdopen(h,'wb') as f:
                f.write(data);f.flush();os.fsync(f.fileno())
            os.replace(temp,name,src_dir_fd=fd,dst_dir_fd=fd)
        finally:
            try:os.unlink(temp,dir_fd=fd)
            except FileNotFoundError:pass
    finally:os.close(fd)
if action=='chunk':
    offset=int(sys.argv[3]);length=int(sys.argv[4]);size=int(sys.argv[5]);mtime=int(sys.argv[6]);ctime=int(sys.argv[7])
    assert 0<=offset<=size and 0<=length<=1048576 and offset+length<=size
    fd,name=parent(path)
    try:
        h=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        try:
            s=os.fstat(h)
            assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
            assert (s.st_size,s.st_mtime_ns,s.st_ctime_ns)==(size,mtime,ctime)
            with os.fdopen(os.dup(h),'rb') as stream:
                stream.seek(offset);piece=stream.read(length)
            assert len(piece)==length
            s=os.fstat(h)
            assert (s.st_size,s.st_mtime_ns,s.st_ctime_ns)==(size,mtime,ctime)
            sys.stdout.buffer.write(piece)
        finally:os.close(h)
    finally:os.close(fd)
elif action=='stage_chunk':
    offset=int(sys.argv[3]);total=int(sys.argv[4]);token=sys.argv[5]
    assert len(token)==32 and all(x in '0123456789abcdef' for x in token)
    assert 0<=offset<=total<=268435456
    data=sys.stdin.buffer.read(1048577)
    assert len(data)<=1048576 and offset+len(data)<=total
    fd,name=parent(path,True)
    temp='.physharness-stage-'+token
    try:
        flags=os.O_WRONLY|os.O_NOFOLLOW|(os.O_CREAT|os.O_EXCL if offset==0 else 0)
        h=os.open(temp,flags,0o600,dir_fd=fd)
        try:
            s=os.fstat(h)
            assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size==offset
            os.lseek(h,offset,os.SEEK_SET)
            assert os.write(h,data)==len(data)
            os.fsync(h)
        finally:os.close(h)
    finally:os.close(fd)
    print('ok')
elif action=='commit_stage':
    total=int(sys.argv[3]);digest=sys.argv[4];token=sys.argv[5]
    assert len(digest)==64 and all(x in '0123456789abcdef' for x in digest)
    assert len(token)==32 and all(x in '0123456789abcdef' for x in token)
    fd,name=parent(path)
    temp='.physharness-stage-'+token
    try:
        h=os.open(temp,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
        try:
            s=os.fstat(h);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size==total
            sha=hashlib.sha256()
            with os.fdopen(os.dup(h),'rb') as stream:
                while part:=stream.read(1048576):sha.update(part)
            assert sha.hexdigest()==digest
            try:os.stat(name,dir_fd=fd,follow_symlinks=False);raise ValueError('target exists')
            except FileNotFoundError:pass
            os.rename(temp,name,src_dir_fd=fd,dst_dir_fd=fd)
        finally:os.close(h)
    finally:os.close(fd)
    print('ok')
elif action=='capture':
    try:
        limit=int(sys.argv[3]);assert 0<limit<=4000000
        fd,name=parent(path)
        try:
            h=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
            try:
                before=os.fstat(h)
                assert stat.S_ISREG(before.st_mode) and before.st_nlink==1
                assert 0<before.st_size<=limit
                with os.fdopen(os.dup(h),'rb') as stream:data=stream.read(limit+1)
                after=os.fstat(h)
                assert len(data)==before.st_size
                assert (after.st_size,after.st_mtime_ns,after.st_ctime_ns)==(
                    before.st_size,before.st_mtime_ns,before.st_ctime_ns)
                sys.stdout.buffer.write(b'O'+data)
            finally:os.close(h)
        finally:os.close(fd)
    except (AssertionError,OSError,ValueError):sys.stdout.buffer.write(b'R')
elif action=='read':sys.stdout.buffer.write(get(path))
elif action=='write':put(path,sys.stdin.buffer.read());print('ok')
elif action=='resource':
    def number(path):
        try:return int(open(path).read().strip())
        except (FileNotFoundError,PermissionError,ValueError):return None
    try:
        events=dict(line.split() for line in open('/sys/fs/cgroup/memory.events'))
        events={key:int(value) for key,value in events.items()}
    except (FileNotFoundError,PermissionError,ValueError):events=None
    print(json.dumps({'current_bytes':number('/sys/fs/cgroup/memory.current'),
                      'peak_bytes':number('/sys/fs/cgroup/memory.peak'),
                      'events':events}))
elif action=='slice':
    import base64,hashlib
    offset=int(sys.argv[3]);length=int(sys.argv[4])
    assert 0<=offset and 0<=length<=65536
    fd,name=parent(path)
    try:
        h=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        try:
            s=os.fstat(h);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
            sha=hashlib.sha256()
            with os.fdopen(os.dup(h),'rb') as stream:
                while chunk:=stream.read(1048576):sha.update(chunk)
            with os.fdopen(os.dup(h),'rb') as stream:
                stream.seek(offset);piece=stream.read(length)
            print(json.dumps({'sha256':sha.hexdigest(),'size_bytes':s.st_size,
                              'data':base64.b64encode(piece).decode()}))
        finally:os.close(h)
    finally:os.close(fd)
elif action in ('list','list3','quiescent'):
    live=[]
    for item in os.listdir('/proc'):
        if not item.isdigit() or int(item) in (1,os.getpid()):continue
        try:
            with open('/proc/'+item+'/stat') as stream: state=stream.read().split(') ')[1][0]
        except (FileNotFoundError,PermissionError):continue
        if state!='Z':live.append(item)
    assert not live, 'Checkpoint requires a quiescent workspace'
    if action=='quiescent':
        print('ok');sys.exit(0)
    result=[];excluded=[]
    for folder,dirs,files in os.walk(root,followlinks=False):
        dirs.sort();files.sort()
        for d in list(dirs):
            full=os.path.join(folder,d)
            assert stat.S_ISDIR(os.lstat(full).st_mode)
            if d in ('__pycache__','.cache','.lake','node_modules'):
                dirs.remove(d);excluded.append(os.path.relpath(full,root));continue
            checked(os.path.relpath(full,root))
        for f in files:
            full=os.path.join(folder,f);relative=os.path.relpath(full,root)
            if f.endswith('.pyc'):
                excluded.append(relative);continue
            checked(relative)
            s=os.lstat(full)
            assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
            if action=='list3':
                sha=hashlib.sha256()
                fd,name=parent(relative)
                try:
                    h=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                    try:
                        observed=os.fstat(h)
                        assert stat.S_ISREG(observed.st_mode) and observed.st_nlink==1
                        assert (s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)==(
                            observed.st_ino,observed.st_size,observed.st_mtime_ns,observed.st_ctime_ns)
                        with os.fdopen(os.dup(h),'rb') as stream:
                            while part:=stream.read(1048576):sha.update(part)
                    finally:os.close(h)
                finally:os.close(fd)
                after=os.lstat(full)
                assert (s.st_size,s.st_mtime_ns,s.st_ctime_ns)==(
                    after.st_size,after.st_mtime_ns,after.st_ctime_ns)
                result.append([relative,s.st_size,sha.hexdigest(),s.st_mtime_ns,s.st_ctime_ns])
            else:result.append([relative,s.st_size])
    result.sort(key=lambda row:row[0])
    print(json.dumps({'files':result,'excluded_paths':excluded},separators=(',',':')))
else:raise ValueError('invalid action')
"""


async def _docker(argv, *, input_data=b"", timeout=30, max_output=65536):
    executable = shutil.which("docker")
    if not executable:
        raise ExecutionError("PROVIDER_UNAVAILABLE", "Docker CLI unavailable")
    try:
        proc = await asyncio.create_subprocess_exec(
            executable,
            *argv[1:],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
        )
    except OSError as exc:
        raise ExecutionError("PROVIDER_UNAVAILABLE", "Docker CLI unavailable") from exc

    async def bounded(stream):
        chunks, size = [], 0
        while part := await stream.read(min(65536, max_output - size + 1)):
            size += len(part)
            if size > max_output:
                raise ExecutionError("OUTPUT_LIMIT", "Docker command output exceeded bound")
            chunks.append(part)
        return b"".join(chunks)

    async def feed():
        if input_data:
            proc.stdin.write(input_data)
            await proc.stdin.drain()
        proc.stdin.close()

    try:
        async with asyncio.timeout(timeout):
            _, out, err = await asyncio.gather(feed(), bounded(proc.stdout), bounded(proc.stderr))
            await proc.wait()
            return proc.returncode, out, err
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        raise


class LocalDockerWorkspaceProvider:
    def __init__(
        self,
        *,
        docker_host: str,
        image_digest: str,
        timeout_seconds: int = 300,
        workspace_quota_bytes: int = DEFAULT_QUOTA,
        max_active_workspaces: int = 1,
        runner: Callable | None = None,
        journal=None,
    ):
        if (
            not isinstance(docker_host, str)
            or not docker_host.startswith("unix:///")
            or docker_host == "unix:///var/run/docker.sock"
            or ".." in docker_host
            or "\x00" in docker_host
        ):
            raise ValueError("Explicit dedicated Unix Docker socket required")
        if not isinstance(image_digest, str) or not _IMAGE.fullmatch(image_digest):
            raise ValueError("Exact Docker image sha256 digest required")
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 86400:
            raise ValueError("Positive bounded timeout required")
        if (
            type(workspace_quota_bytes) is not int
            or not 1 <= workspace_quota_bytes <= DEFAULT_QUOTA
        ):
            raise ValueError("Invalid workspace quota")
        if type(max_active_workspaces) is not int or not 1 <= max_active_workspaces <= 100:
            raise ValueError("Active workbench capacity must be an integer from 1 to 100")
        self.docker_host = docker_host
        self.image_digest = image_digest
        self.template_id = image_digest
        self.timeout_seconds = timeout_seconds
        self.workspace_quota_bytes = workspace_quota_bytes
        self.max_active_workspaces = max_active_workspaces
        self._runner = runner or _docker
        # /tmp is a machine-wide path, independent of each process's TMPDIR.
        # Resolve socket aliases so clients using the same socket share one lock.
        self._lock_path = os.path.join(
            "/tmp",
            "physharness-workbench-"
            + hashlib.sha256(
                os.path.realpath(docker_host.removeprefix("unix://")).encode()
            ).hexdigest()
            + ".lock",
        )
        self._container_id: str | None = None
        workspace_id = getattr(journal, "workspace_id", None)
        self._planned_name = "physharness-" + uuid4().hex
        self._workspace_label = workspace_id or self._planned_name
        self._quarantined = False
        self._creating = False
        self._command_lock = asyncio.Lock()
        self.last_command_diagnostics: dict | None = None
        self.last_execution_observation: dict | None = None
        self.network_disabled = True
        self.capabilities = Capabilities(
            available=True,
            start=True,
            interrupt=True,
            checkpoint=True,
            portable_checkpoint=True,
            isolation="provider_vm",
        )

    @property
    def execution_id(self) -> str:
        if not self._container_id:
            raise ExecutionError("SESSION_NOT_READY", "Docker workbench is not running")
        return self._container_id

    async def _call(self, args, *, input_data=b"", timeout=30, max_output=65536):
        result = await self._runner(
            ["docker", "--host", self.docker_host, *args],
            input_data=input_data,
            timeout=timeout,
            max_output=max_output,
        )
        if result[0]:
            diagnostic = result[2].decode("utf-8", errors="replace")[:1000].strip()
            raise ExecutionError(
                "PROVIDER_FAILED",
                "Dedicated Docker operation failed" + (f": {diagnostic}" if diagnostic else ""),
            )
        return result[1]

    @asynccontextmanager
    async def _physical_slot(self):
        loop = asyncio.get_running_loop()
        locks = _RUN_LOCKS.setdefault(loop, {})
        lock = locks.setdefault(self._lock_path, asyncio.Lock())
        async with lock:
            lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            locked = False
            try:
                while not locked:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                    except BlockingIOError:
                        await asyncio.sleep(0.05)
                yield
            finally:
                if locked:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)

    async def _active_workbenches(self) -> list[tuple[str, str | None]]:
        output = await self._call(
            [
                "ps",
                "--filter",
                "label=physharness.workbench=true",
                "--format",
                '{{.ID}}\t{{.Label "physharness.capacity"}}',
            ],
        )
        rows = []
        for line in output.decode("utf-8").splitlines():
            parts = line.split("\t", 1)
            if not parts[0].strip():
                raise ExecutionError("PROVIDER_FAILED", "Invalid Docker workbench listing")
            label = parts[1].strip() if len(parts) == 2 else ""
            rows.append((parts[0].strip(), label or None))
        return rows

    async def probe_capacity(self) -> dict:
        """Read the daemon's active workbench count without reserving a slot."""
        active = await self._active_workbenches()
        conflict = self._capacity_policy_conflict(active)
        return {
            "max_active_workspaces": self.max_active_workspaces,
            "active_workspaces": len(active),
            "available_slots": 0 if conflict else max(0, self.max_active_workspaces - len(active)),
            "capacity_policy_conflict": conflict,
            "memory_per_workspace_bytes": 2 * 1024**3,
            "cpus_per_workspace": 2,
        }

    def _capacity_policy_conflict(self, active: list[tuple[str, str | None]]) -> bool:
        return any(
            label != str(self.max_active_workspaces)
            and not (self.max_active_workspaces == 1 and label is None)
            for _, label in active
        )

    async def create(self):
        if self._container_id or self._quarantined or self._creating:
            raise ExecutionError("OPERATION_CONFLICT", "Docker provider already used")
        self._creating = True
        try:
            return await self._create_once()
        finally:
            self._creating = False

    async def _create_once(self):
        observed = (
            (await self._call(["image", "inspect", "--format", "{{.Id}}", self.image_digest]))
            .decode()
            .strip()
        )
        if observed != self.image_digest:
            raise ExecutionError(
                "PROVIDER_POLICY_MISMATCH", "Docker image identity differs from pinned digest"
            )
        try:
            async with self._physical_slot():
                active = await self._active_workbenches()
                if self._capacity_policy_conflict(active):
                    raise ExecutionError(
                        "PROVIDER_POLICY_MISMATCH",
                        "Active workbenches use a different capacity policy",
                    )
                if len(active) >= self.max_active_workspaces:
                    raise ExecutionError(
                        "WORKSPACE_CAPACITY", "Dedicated workbench capacity is occupied"
                    )
                output = await self._call(
                    [
                        "run",
                        "-d",
                        "--rm",
                        "--name",
                        self._planned_name,
                        "--label",
                        f"physharness.workspace={self._workspace_label}",
                        "--label",
                        "physharness.workbench=true",
                        "--label",
                        f"physharness.capacity={self.max_active_workspaces}",
                        "--network",
                        "none",
                        "--read-only",
                        "--cap-drop",
                        "ALL",
                        "--security-opt",
                        "no-new-privileges",
                        "--pids-limit",
                        "128",
                        "--memory",
                        "2g",
                        "--cpus",
                        "2",
                        "--user",
                        "65532:65532",
                        "--tmpfs",
                        f"/work:rw,noexec,nosuid,nodev,size={self.workspace_quota_bytes},mode=0700,uid=65532,gid=65532",
                        "--entrypoint",
                        "/usr/bin/python3",
                        self.image_digest,
                        "-c",
                        f"import time; time.sleep({self.timeout_seconds})",
                    ],
                    timeout=60,
                )
        except ExecutionError as exc:
            if exc.code in ("WORKSPACE_CAPACITY", "PROVIDER_POLICY_MISMATCH"):
                raise  # Atomic inspection proved this provider created no container.
            self._quarantined = True
            try:
                await asyncio.shield(self._call(["rm", "-f", self._planned_name], timeout=30))
            except BaseException:
                pass
            raise
        except BaseException:
            self._quarantined = True
            try:
                await asyncio.shield(self._call(["rm", "-f", self._planned_name], timeout=30))
            except BaseException:
                pass  # The broker keeps the durable uncertain reservation for reconciliation.
            raise
        self._container_id = output.decode().strip()
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{5,127}", self._container_id):
            self._quarantined = True
            try:
                await self._call(["rm", "-f", self._planned_name], timeout=30)
            except ExecutionError:
                pass
            raise ExecutionError(
                "WORKSPACE_IDENTITY_MISMATCH", "Docker returned invalid container identity"
            )
        return self

    async def run(self, request: CommandRequest) -> CommandResult:
        async with self._command_lock:
            return await self._run_once(request)

    def validate_command(self, request: CommandRequest) -> str:
        """Check request shape without touching Docker or mutable provider state."""
        if request.cwd == ".":
            cwd = "/work"
        elif request.cwd in {"/opt/sources/physlib", "/opt/sources/mathlib"}:
            cwd = request.cwd
        else:
            cwd = "/work/" + checked_path(request.cwd)
        if request.env:
            raise ExecutionError("UNSAFE_RUNTIME", "Command environment overrides are disabled")
        if request.timeout_seconds > self.timeout_seconds:
            raise ExecutionError("TIMEOUT_LIMIT", "Command exceeds workspace timeout")
        return cwd

    @staticmethod
    def validate_workspace_path(path: str) -> str:
        """Pure file-path validation shared with the broker's pre-dispatch gate."""
        return checked_path(path)

    async def _run_once(self, request: CommandRequest) -> CommandResult:
        if self._quarantined:
            raise ExecutionError("OPERATION_UNCERTAIN", "Docker workbench needs reconciliation")
        cwd = self.validate_command(request)
        argv = ["exec", "--workdir", cwd, self.execution_id, *request.argv]
        before = await self._resource_observation()
        self.last_command_diagnostics = {
            "phase": "dispatch",
            "memory_before": before,
            "memory_after": None,
            "oom_delta": None,
        }
        try:
            async with asyncio.timeout(request.timeout_seconds):
                code, out, err = await self._runner(
                    ["docker", "--host", self.docker_host, *argv],
                    timeout=request.timeout_seconds,
                    max_output=request.max_output_bytes,
                )
                await self._guest("quiescent")
        except (TimeoutError, ExecutionError, asyncio.CancelledError) as exc:
            after = await self._resource_observation()
            self.last_command_diagnostics = self._diagnostics(
                before, after, "timeout" if isinstance(exc, TimeoutError) else "failed"
            )
            self._quarantined = True
            await asyncio.shield(self.close())
            raise
        after = await self._resource_observation()
        self.last_command_diagnostics = self._diagnostics(before, after, "completed")
        self.last_command_diagnostics["limit_reason"] = (
            "cgroup_oom_observed"
            if (self.last_command_diagnostics["oom_delta"] or 0) > 0
            else "exit_137_cause_unknown"
            if code == 137
            else "command_nonzero_exit"
            if code != 0
            else None
        )
        return CommandResult(
            operation_id=request.operation_id,
            execution_id=self.execution_id,
            exit_code=code,
            stdout=out.decode("utf-8", errors="replace"),
            stderr=err.decode("utf-8", errors="replace"),
        )

    async def _resource_observation(self) -> dict | None:
        try:
            return json.loads(await self._guest("resource", max_output=4096))
        except (ExecutionError, ValueError, TypeError):
            return None

    @staticmethod
    def _diagnostics(before: dict | None, after: dict | None, phase: str) -> dict:
        old = (before or {}).get("events") or {}
        new = (after or {}).get("events") or {}
        oom_delta = new.get("oom", 0) - old.get("oom", 0) if old and new else None
        return {
            "phase": phase,
            "memory_before": before,
            "memory_after": after,
            "oom_delta": oom_delta,
        }

    async def _guest(self, action: str, path: str | None = None, *, data=b"", max_output=65536):
        args = ["exec", "-i", self.execution_id, "/usr/bin/python3", "-c", _GUEST, action]
        if path is not None:
            args.append(checked_path(path))
        return await self._call(
            args, input_data=data, timeout=self.timeout_seconds, max_output=max_output
        )

    async def upload_file(self, path: str, data: bytes, *, expected_execution_id: str) -> str:
        self._identity(expected_execution_id)
        archive = WorkspaceArchive.build({path: data}, quota_bytes=self.workspace_quota_bytes)
        await self._guest("write", path, data=data)
        return archive.sha256

    async def download_file(self, path: str, *, expected_execution_id: str) -> bytes:
        self._identity(expected_execution_id)
        return await self._guest("read", path, max_output=self.workspace_quota_bytes)

    async def capture_file(self, path: str, *, expected_execution_id: str, max_bytes: int) -> bytes:
        """Read one bounded regular file without following guest symlinks."""
        self._identity(expected_execution_id)
        if type(max_bytes) is not int or not 1 <= max_bytes <= 4_000_000:
            raise ExecutionError("WORKSPACE_LIMIT", "Invalid capture byte limit")
        response = await self._call(
            [
                "exec",
                "-i",
                self.execution_id,
                "/usr/bin/python3",
                "-c",
                _GUEST,
                "capture",
                checked_path(path),
                str(max_bytes),
            ],
            timeout=self.timeout_seconds,
            max_output=max_bytes + 2,
        )
        if response == b"R":
            raise ExecutionError(
                "WORKSPACE_TRANSFER_REJECTED", "Guest refused unsafe or oversized file capture"
            )
        if not response.startswith(b"O"):
            raise ExecutionError("INVALID_TOOL_RESULT", "Guest capture response is malformed")
        return response[1:]

    async def read_range(
        self, path: str, *, offset: int, length: int, expected_execution_id: str
    ) -> dict:
        self._identity(expected_execution_id)
        if (
            type(offset) is not int
            or offset < 0
            or type(length) is not int
            or not 1 <= length <= 65536
        ):
            raise ExecutionError("WORKSPACE_LIMIT", "Read range must be at most 65536 bytes")
        args = [
            "exec",
            "-i",
            self.execution_id,
            "/usr/bin/python3",
            "-c",
            _GUEST,
            "slice",
            checked_path(path),
            str(offset),
            str(length),
        ]
        response = await self._call(args, timeout=self.timeout_seconds, max_output=100_000)
        return json.loads(response)

    async def export_workspace(self, *, expected_execution_id: str) -> WorkspaceArchive:
        self._identity(expected_execution_id)
        observed = json.loads(await self._guest("list", max_output=2_000_000))
        listing = observed["files"]
        if len(listing) > 10_000 or sum(size for _, size in listing) > self.workspace_quota_bytes:
            raise ExecutionError("WORKSPACE_LIMIT", "Workspace exceeds checkpoint quota")
        files = {}
        for path, size in listing:
            checked_path(path)
            content = await self.download_file(path, expected_execution_id=expected_execution_id)
            if len(content) != size:
                raise ExecutionError("CHECKPOINT_MISMATCH", "Workspace changed during export")
            files[path] = content
        return WorkspaceArchive.build(
            files,
            quota_bytes=self.workspace_quota_bytes,
            excluded_paths=observed["excluded_paths"],
        )

    async def export_workspace_stream(self, *, expected_execution_id: str, accept_chunk):
        """Read one bounded chunk at a time; broker persists each before the next read."""
        self._identity(expected_execution_id)
        before = json.loads(await self._guest("list3", max_output=4_000_000))
        listing = before["files"]
        if len(listing) > 10_000 or sum(row[1] for row in listing) > self.workspace_quota_bytes:
            raise ExecutionError("WORKSPACE_LIMIT", "Workspace exceeds checkpoint quota")
        files = []
        chunks = {}
        for path, size, expected_hash, mtime, ctime in listing:
            checked_path(path)
            file_hash = hashlib.sha256()
            refs = []
            for offset in range(0, size, CHUNK_SIZE):
                length = min(CHUNK_SIZE, size - offset)
                args = [
                    "exec",
                    "-i",
                    self.execution_id,
                    "/usr/bin/python3",
                    "-c",
                    _GUEST,
                    "chunk",
                    path,
                    str(offset),
                    str(length),
                    str(size),
                    str(mtime),
                    str(ctime),
                ]
                piece = await self._call(args, timeout=self.timeout_seconds, max_output=CHUNK_SIZE)
                if len(piece) != length:
                    raise ExecutionError("CHECKPOINT_MISMATCH", "Workspace changed during export")
                file_hash.update(piece)
                digest = hashlib.sha256(piece).hexdigest()
                refs.append(digest)
                if digest not in chunks:
                    artifact_id = await accept_chunk(piece, digest)
                    chunks[digest] = {"sha256": digest, "size": length, "artifact_id": artifact_id}
            if file_hash.hexdigest() != expected_hash:
                raise ExecutionError("CHECKPOINT_MISMATCH", "Workspace changed during export")
            files.append({"path": path, "size": size, "sha256": expected_hash, "chunks": refs})
        after = json.loads(await self._guest("list3", max_output=4_000_000))
        if after != before:
            raise ExecutionError("CHECKPOINT_MISMATCH", "Workspace changed during export")
        return (
            files,
            sorted(chunks.values(), key=lambda chunk: chunk["sha256"]),
            sorted(set(before["excluded_paths"])),
        )

    async def restore_workspace_stream(self, archive, *, expected_execution_id: str, read_chunk):
        """Restore v3 into an empty VM via bounded temporary files and verified rename."""
        self._identity(expected_execution_id)
        existing = json.loads(await self._guest("list", max_output=4_000_000))
        if existing["files"]:
            raise ExecutionError("OPERATION_CONFLICT", "Restore requires empty workspace")
        declarations = {entry["sha256"]: entry for entry in archive.manifest["chunks"]}
        for entry in archive.manifest["files"]:
            path, total = entry["path"], entry["size"]
            token = uuid4().hex
            digest = hashlib.sha256()
            offset = 0
            for ref in entry["chunks"]:
                chunk = declarations[ref]
                piece = await read_chunk(chunk)
                if len(piece) != chunk["size"] or hashlib.sha256(piece).hexdigest() != ref:
                    raise ExecutionError(
                        "CHECKPOINT_MISMATCH", "Checkpoint chunk integrity mismatch"
                    )
                digest.update(piece)
                args = [
                    "exec",
                    "-i",
                    self.execution_id,
                    "/usr/bin/python3",
                    "-c",
                    _GUEST,
                    "stage_chunk",
                    path,
                    str(offset),
                    str(total),
                    token,
                ]
                await self._call(args, input_data=piece, timeout=self.timeout_seconds)
                offset += len(piece)
            if not entry["chunks"]:
                args = [
                    "exec",
                    "-i",
                    self.execution_id,
                    "/usr/bin/python3",
                    "-c",
                    _GUEST,
                    "stage_chunk",
                    path,
                    "0",
                    "0",
                    token,
                ]
                await self._call(args, timeout=self.timeout_seconds)
            if offset != total or digest.hexdigest() != entry["sha256"]:
                raise ExecutionError("CHECKPOINT_MISMATCH", "Checkpoint file integrity mismatch")
            args = [
                "exec",
                "-i",
                self.execution_id,
                "/usr/bin/python3",
                "-c",
                _GUEST,
                "commit_stage",
                path,
                str(total),
                entry["sha256"],
                token,
            ]
            await self._call(args, timeout=self.timeout_seconds)
        observed = json.loads(await self._guest("list3", max_output=4_000_000))
        expected = [
            [entry["path"], entry["size"], entry["sha256"]] for entry in archive.manifest["files"]
        ]
        actual = [[row[0], row[1], row[2]] for row in observed["files"]]
        if actual != expected:
            raise ExecutionError(
                "CHECKPOINT_MISMATCH", "Restored workspace differs from checkpoint"
            )

    async def restore_workspace(self, archive: WorkspaceArchive, *, expected_execution_id: str):
        self._identity(expected_execution_id)
        files = archive.files(quota_bytes=self.workspace_quota_bytes)
        existing = json.loads(await self._guest("list", max_output=2_000_000))
        if existing["files"]:
            raise ExecutionError("OPERATION_CONFLICT", "Restore requires empty workspace")
        for path, data in files.items():
            await self.upload_file(path, data, expected_execution_id=expected_execution_id)
        observed = await self.export_workspace(expected_execution_id=expected_execution_id)
        if observed.files() != files:
            raise ExecutionError(
                "CHECKPOINT_MISMATCH", "Restored workspace differs from checkpoint"
            )

    def _identity(self, expected: str):
        if self.execution_id != expected:
            raise ExecutionError("WORKSPACE_IDENTITY_MISMATCH", "Docker container identity changed")

    async def close(self):
        if self._container_id:
            identifier = self._container_id
            await self._call(["rm", "-f", identifier], timeout=30)
            self.last_execution_observation = {
                "execution_id": identifier,
                "destruction_confirmed": True,
            }
            self._container_id = None
