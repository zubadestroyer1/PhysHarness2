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

from .types import GUEST_PYTHON, Capabilities, CommandRequest, CommandResult, ExecutionError
from .workspace_archive import CHUNK_SIZE, DEFAULT_QUOTA, WorkspaceArchive, checked_path

_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RUN_LOCKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_GUEST = r"""
import base64, hashlib, json, os, stat, sys
root='/work'
action=sys.argv[1]
path=sys.argv[2] if len(sys.argv)>2 else None
class Refused(Exception):pass
def refuse(kind,value,trace):
    # Exit 3 only when /work is provably unchanged: read-only actions, or an undone write.
    if issubclass(kind,Refused) or (action in ('read','slice','chunk','list','list3')
                                    and issubclass(kind,(AssertionError,OSError,ValueError))):
        sys.stderr.write('physharness-refused: '+kind.__name__+'\n');sys.stderr.flush();os._exit(3)
    sys.__excepthook__(kind,value,trace)
sys.excepthook=refuse
def secret(name):
    return (name in ('.git','.ssh','.aws','.config','__pycache__','.cache','node_modules')
            or name.startswith('.env') or name.endswith('.pyc'))
def portable(p):
    # The host checked_path rule: a name a checkpoint can hold and restore exactly.
    try:size=len(p.encode())
    except UnicodeEncodeError:return False
    return 0<size<=1024 and all(x not in ('','.','..') and '\\' not in x and '\x00' not in x
                                and len(x.encode())<=255 for x in p.split('/'))
def checked(p):
    assert portable(p) and not any(secret(x) for x in p.split('/'))
    return p.split('/')
def parent(p,create=False):
    parts=checked(p)
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
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
    try:parts=checked(p)
    except AssertionError:raise Refused('unsafe path refused before any change')
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    made=[];temp=None
    try:
        try:
            for part in parts[:-1]:
                owner=os.dup(fd)
                try:os.mkdir(part,mode=0o700,dir_fd=fd);made.append((owner,part))
                except FileExistsError:os.close(owner)
                nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                os.close(fd);fd=nxt
            name=parts[-1]
            try:
                s=os.stat(name,dir_fd=fd,follow_symlinks=False)
                assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
            except FileNotFoundError:pass
            candidate='.physharness-'+os.urandom(16).hex()
            h=os.open(candidate,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
            temp=candidate
            with os.fdopen(h,'wb') as f:
                f.write(data);f.flush();os.fsync(f.fileno())
            os.replace(temp,name,src_dir_fd=fd,dst_dir_fd=fd)
        except (AssertionError,OSError,ValueError):
            # Undo only this helper's own temp file and directories; a failed undo stays uncertain.
            if temp is not None:
                try:os.unlink(temp,dir_fd=fd)
                except FileNotFoundError:pass
            for owner,part in reversed(made):os.rmdir(part,dir_fd=owner)
            raise Refused('write refused before any lasting change')
    finally:
        os.close(fd)
        for owner,_ in made:os.close(owner)
if action=='chunk':
    offset=int(sys.argv[3]);length=int(sys.argv[4]);size=int(sys.argv[5]);mtime=int(sys.argv[6]);ctime=int(sys.argv[7])
    assert 0<=offset<=size and 0<=length<=1048576 and offset+length<=size
    fd,name=parent(path)
    try:
        h=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        try:
            s=os.fstat(h)
            assert stat.S_ISREG(s.st_mode) and s.st_dev==os.lstat(root).st_dev
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
    device=os.lstat(root).st_dev
    def omit(relative):
        # Links, special files, secrets, caches, unreadable entries and names no archive can
        # hold are never read. Each is reported as bounded portable text: U+FFFD replaces
        # backslashes and undecodable bytes, and an over-long path ends in an ellipsis.
        text=os.fsencode(relative).decode('utf-8','replace').replace('\\','\ufffd')
        if len(text.encode())>1024:
            text=text.encode()[:1000].decode('utf-8','ignore').rstrip('/')+'\u2026'
        excluded.append(text)
    def unlisted(error):
        # A directory that cannot be listed is reported, never silently skipped.
        if error.filename==root:raise error
        omit(os.path.relpath(error.filename,root))
    def status(full):
        try:return os.lstat(full)
        except PermissionError:return None
    for folder,dirs,files in os.walk(root,onerror=unlisted,followlinks=False):
        dirs.sort();files.sort()
        for d in list(dirs):
            full=os.path.join(folder,d);relative=os.path.relpath(full,root)
            s=None if d=='.lake' or secret(d) or not portable(relative) else status(full)
            if s is None or not stat.S_ISDIR(s.st_mode):
                dirs.remove(d);omit(relative)
        for f in files:
            full=os.path.join(folder,f);relative=os.path.relpath(full,root)
            s=None if secret(f) or not portable(relative) else status(full)
            # Hard links cannot leave /work's own file system, so every name of a regular
            # file there is ordinary workspace content.
            if s is None or not stat.S_ISREG(s.st_mode) or s.st_dev!=device:
                omit(relative);continue
            fd,name=parent(relative)
            try:
                try:h=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                except PermissionError:
                    omit(relative);continue
                try:
                    observed=os.fstat(h)
                    assert stat.S_ISREG(observed.st_mode)
                    assert (s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)==(
                        observed.st_ino,observed.st_size,observed.st_mtime_ns,observed.st_ctime_ns)
                    sha=hashlib.sha256()
                    if action=='list3':
                        with os.fdopen(os.dup(h),'rb') as stream:
                            while part:=stream.read(1048576):sha.update(part)
                finally:os.close(h)
            finally:os.close(fd)
            if action=='list3':
                after=os.lstat(full)
                assert (s.st_size,s.st_mtime_ns,s.st_ctime_ns)==(
                    after.st_size,after.st_mtime_ns,after.st_ctime_ns)
                result.append([relative,s.st_size,sha.hexdigest(),s.st_mtime_ns,s.st_ctime_ns])
            else:result.append([relative,s.st_size])
    result.sort(key=lambda row:row[0])
    print(json.dumps({'files':result,'excluded_paths':excluded},separators=(',',':')))
else:raise ValueError('invalid action')
"""
# Isolated mode: agent files in the /work exec directory cannot shadow helper imports.
_GUEST_ARGV = (*GUEST_PYTHON, "-c", _GUEST)
_GUEST_REFUSED = 3
# These actions never write /work, so an oversized complete response is a definite refusal.
_READ_ONLY_GUEST_ACTIONS = frozenset({"read", "slice", "chunk", "capture", "list", "list3"})


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
        # Keep one byte past the bound so callers can report truncation, and drain
        # the rest so the command finishes instead of blocking on a full pipe.
        chunks, size = [], 0
        while part := await stream.read(65536):
            if size <= max_output:
                chunks.append(part[: max_output + 1 - size])
            size += len(part)
        return b"".join(chunks)

    async def feed():
        if input_data:
            proc.stdin.write(input_data)
            await proc.stdin.drain()
        proc.stdin.close()

    readers = [
        asyncio.ensure_future(bounded(proc.stdout)),
        asyncio.ensure_future(bounded(proc.stderr)),
    ]
    try:
        async with asyncio.timeout(timeout):
            await feed()
            out, err = await asyncio.gather(*readers)
            await proc.wait()
            return proc.returncode, out, err
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        # wait() also needs both pipes at EOF, so discard what the killed CLI left.
        await asyncio.gather(
            bounded(proc.stdout), bounded(proc.stderr), proc.wait(), return_exceptions=True
        )
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

    async def _call(self, args, *, input_data=b"", timeout=30, max_output=65536, guest_action=None):
        result = await self._runner(
            ["docker", "--host", self.docker_host, *args],
            input_data=input_data,
            timeout=timeout,
            max_output=max_output,
        )
        # Only the helper's own marker proves a refusal; transport failures stay uncertain.
        if (
            guest_action is not None
            and result[0] == _GUEST_REFUSED
            and result[2].startswith(b"physharness-refused:")
        ):
            raise ExecutionError(
                "WORKSPACE_TRANSFER_REJECTED",
                "Guest refused a missing, linked, non-regular or unsafe workspace path; "
                "/work is unchanged",
            )
        if result[0]:
            diagnostic = result[2].decode("utf-8", errors="replace")[:1000].strip()
            raise ExecutionError(
                "PROVIDER_FAILED",
                "Dedicated Docker operation failed" + (f": {diagnostic}" if diagnostic else ""),
            )
        if len(result[1]) > max_output:
            if guest_action in _READ_ONLY_GUEST_ACTIONS:
                raise ExecutionError(
                    "WORKSPACE_TRANSFER_REJECTED",
                    "Guest response exceeded its bound; /work is unchanged",
                )
            raise ExecutionError("OUTPUT_LIMIT", "Docker command output exceeded bound")
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
            self._quarantined = True
            after = await self._resource_observation()
            self.last_command_diagnostics = self._diagnostics(
                before, after, "timeout" if isinstance(exc, TimeoutError) else "failed"
            )
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
        # The transport keeps one byte past the bound; excess output is reported, not fatal.
        limit = request.max_output_bytes
        return CommandResult(
            operation_id=request.operation_id,
            execution_id=self.execution_id,
            exit_code=code,
            stdout=out[:limit].decode("utf-8", errors="replace"),
            stderr=err[:limit].decode("utf-8", errors="replace"),
            stdout_truncated=len(out) > limit,
            stderr_truncated=len(err) > limit,
        )

    async def _resource_observation(self) -> dict | None:
        try:
            return json.loads(await self._guest("resource", max_output=4096))
        except (ExecutionError, ValueError, TypeError):
            return None

    @staticmethod
    def _diagnostics(before: dict | None, after: dict | None, phase: str) -> dict:
        # Guest resource reports are untrusted; malformed counters are simply unknown.
        def oom(report):
            events = report.get("events") if isinstance(report, dict) else None
            count = events.get("oom", 0) if isinstance(events, dict) and events else None
            return count if type(count) is int else None

        old, new = oom(before), oom(after)
        oom_delta = new - old if old is not None and new is not None else None
        return {
            "phase": phase,
            "memory_before": before,
            "memory_after": after,
            "oom_delta": oom_delta,
        }

    async def _guest(
        self, action: str, path: str | None = None, *, arguments=(), data=b"", max_output=65536
    ):
        args = ["exec", "-i", self.execution_id, *_GUEST_ARGV, action]
        if path is not None:
            args.append(checked_path(path))
        args.extend(arguments)
        return await self._call(
            args,
            input_data=data,
            timeout=self.timeout_seconds,
            max_output=max_output,
            guest_action=action,
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
        response = await self._guest(
            "capture", path, arguments=[str(max_bytes)], max_output=max_bytes + 2
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
        response = await self._guest(
            "slice", path, arguments=[str(offset), str(length)], max_output=100_000
        )
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
        if (
            len(listing) > 10_000
            or len(before["excluded_paths"]) > 10_000
            or sum(row[1] for row in listing) > self.workspace_quota_bytes
        ):
            raise ExecutionError("WORKSPACE_LIMIT", "Workspace exceeds checkpoint quota")
        files = []
        chunks = {}
        for path, size, expected_hash, mtime, ctime in listing:
            checked_path(path)
            file_hash = hashlib.sha256()
            refs = []
            for offset in range(0, size, CHUNK_SIZE):
                length = min(CHUNK_SIZE, size - offset)
                piece = await self._guest(
                    "chunk",
                    path,
                    arguments=[str(offset), str(length), str(size), str(mtime), str(ctime)],
                    max_output=CHUNK_SIZE,
                )
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
        if existing["files"] or existing["excluded_paths"]:
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
                await self._guest(
                    "stage_chunk", path, arguments=[str(offset), str(total), token], data=piece
                )
                offset += len(piece)
            if not entry["chunks"]:
                await self._guest("stage_chunk", path, arguments=["0", "0", token])
            if offset != total or digest.hexdigest() != entry["sha256"]:
                raise ExecutionError("CHECKPOINT_MISMATCH", "Checkpoint file integrity mismatch")
            await self._guest("commit_stage", path, arguments=[str(total), entry["sha256"], token])
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
        if existing["files"] or existing["excluded_paths"]:
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
