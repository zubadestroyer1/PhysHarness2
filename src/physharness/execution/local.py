"""Development-only subprocess runner. This is NOT a security sandbox.

Cwd validation does not stop a trusted command from opening another host path.
Never offer this executor to untrusted model code on a production API host.
"""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from .types import Capabilities, CommandRequest, CommandResult, ExecutionError, identifier


class LocalShellExecutor:
    def __init__(self, root: str | Path, *, allow_local_execution: bool = False):
        self.root = Path(root).resolve(strict=True)
        self.allow_local_execution = allow_local_execution
        self.execution_id = identifier()
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._starting: set[str] = set()
        self._cancelled: set[str] = set()
        self.capabilities = Capabilities(
            available=allow_local_execution,
            start=allow_local_execution,
            interrupt=allow_local_execution,
            isolation="development_process",
            reason="Development only: subprocesses have host-user access; no VM boundary",
        )

    @property
    def active_operations(self) -> tuple[str, ...]:
        return tuple(self._processes)

    def confined_path(self, path: str) -> Path:
        requested = Path(path)
        candidate = requested if requested.is_absolute() else self.root / requested
        # Reject all symlink components beneath the root, including inward links.
        try:
            relative = candidate.relative_to(self.root)
            current = self.root
            for part in relative.parts:
                if part == "..":
                    raise ValueError("parent traversal")
                current /= part
                if current.is_symlink():
                    raise ValueError("symlink")
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.root)
            if not resolved.is_dir():
                raise ValueError("not a directory")
        except (ValueError, OSError) as exc:
            raise ExecutionError(
                "PATH_ESCAPE", "Working directory must be a real directory inside executor root"
            ) from exc
        return resolved

    @staticmethod
    def _kill_group(process: asyncio.subprocess.Process) -> None:
        # Kill descendants even if the process leader has exited.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    async def cancel(self, operation_id: str) -> bool:
        process = self._processes.get(operation_id)
        if process is None:
            return False
        self._cancelled.add(operation_id)
        self._kill_group(process)
        return True

    async def run(self, request: CommandRequest) -> CommandResult:
        if not self.allow_local_execution:
            raise ExecutionError(
                "PROVIDER_UNAVAILABLE",
                "Local execution requires explicit development opt-in",
                remediation="Set allow_local_execution=True only for trusted development",
            )
        if os.name != "posix":
            raise ExecutionError(
                "PROVIDER_UNAVAILABLE", "Local process-group executor requires POSIX"
            )
        cwd = self.confined_path(request.cwd)
        if request.operation_id in self._processes or request.operation_id in self._starting:
            raise ExecutionError("OPERATION_CONFLICT", "Operation is already running")
        forbidden = {
            "PYTHONPATH",
            "PYTHONHOME",
            "NODE_OPTIONS",
            "LD_PRELOAD",
            "DYLD_INSERT_LIBRARIES",
        }
        if forbidden.intersection(request.env):
            raise ExecutionError(
                "INVALID_CONFIG", "Environment contains a prohibited interpreter injection setting"
            )
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.root), "LANG": "C.UTF-8"}
        env.update(request.env)
        self._starting.add(request.operation_id)
        try:
            process = await asyncio.create_subprocess_exec(
                *request.argv,
                cwd=cwd,
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            raise ExecutionError(
                "COMMAND_START_FAILED",
                "Could not start configured executable",
                operation_id=request.operation_id,
            ) from exc
        finally:
            self._starting.discard(request.operation_id)
        self._processes[request.operation_id] = process

        async def capture(stream: asyncio.StreamReader) -> tuple[str, bool]:
            buffer = bytearray()
            total = 0
            while chunk := await stream.read(16384):
                total += len(chunk)
                buffer.extend(chunk[: max(0, request.max_output_bytes - len(buffer))])
            encoded = buffer.decode("utf-8", errors="replace").encode()
            text = encoded[: request.max_output_bytes].decode("utf-8", errors="ignore")
            return text, max(total, len(encoded)) > request.max_output_bytes

        stdout = asyncio.create_task(capture(process.stdout))
        stderr = asyncio.create_task(capture(process.stderr))
        try:
            async with asyncio.timeout(request.timeout_seconds):
                await process.wait()
                out, err = await asyncio.gather(stdout, stderr)
            if request.operation_id in self._cancelled:
                raise ExecutionError(
                    "CANCELLED", "Command was cancelled", operation_id=request.operation_id
                )
            return CommandResult(
                operation_id=request.operation_id,
                execution_id=self.execution_id,
                exit_code=process.returncode,
                stdout=out[0],
                stderr=err[0],
                stdout_truncated=out[1],
                stderr_truncated=err[1],
            )
        except TimeoutError as exc:
            raise ExecutionError(
                "TIMEOUT", "Command exceeded wall-clock limit", operation_id=request.operation_id
            ) from exc
        finally:
            self._kill_group(process)
            await process.wait()
            for task in (stdout, stderr):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stdout, stderr, return_exceptions=True)
            self._processes.pop(request.operation_id, None)
            self._cancelled.discard(request.operation_id)
