"""Opt-in N-workbench and verifier resource observation for S1; no model calls.

Run only on the dedicated pilot VM after all other workbenches are gone. This
checks capacity and portable workspace files, not the scientific target. On a
macOS host it also reads host free memory once while all N commands run.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from physharness.execution.local_docker import LocalDockerWorkspaceProvider
from physharness.execution.types import CommandRequest, ExecutionError

ROOT = Path(__file__).resolve().parents[2]
LEAN_SOURCE = b"import Mathlib\n#check Nat.add_comm\n"
GENERATIONS = 4
# Each command imports Mathlib and then sleeps 12 s, so all N should be running by now.
HOST_MEMORY_SAMPLE_DELAY = 6.0


def make_provider(args):
    # Workbench containers live for the provider timeout, so it matches the overall bound.
    return LocalDockerWorkspaceProvider(
        docker_host=args.docker_host,
        image_digest=args.worker_image,
        max_active_workspaces=args.capacity,
        timeout_seconds=args.timeout_seconds,
    )


async def workbench_command(provider, index):
    started = time.monotonic()
    result = await provider.run(
        CommandRequest(
            operation_id=f"capacity-lean-{index}",
            argv=[
                "python3",
                "-c",
                "import json,subprocess,time; "
                "start=time.monotonic(); "
                "p=subprocess.run(['/opt/lean/bin/lake','--offline','env','lean',"
                "'/work/scratch/Check.lean'],capture_output=True,text=True); "
                "print(p.returncode,p.stdout[-200:],p.stderr[-200:]); "
                "p.check_returncode();time.sleep(12); "
                "print('CAPACITY_TIMING='+json.dumps([start,time.monotonic()]))",
            ],
            cwd="/opt/sources/physlib",
            timeout_seconds=180,
            max_output_bytes=65536,
        )
    )
    timing = next(
        (
            json.loads(line.removeprefix("CAPACITY_TIMING="))
            for line in result.stdout.splitlines()
            if line.startswith("CAPACITY_TIMING=")
        ),
        None,
    )
    return {
        "exit_code": result.exit_code,
        "check_seen": "Nat.add_comm" in result.stdout,
        "started": started,
        "ended": time.monotonic(),
        "oom_delta": provider.last_command_diagnostics["oom_delta"],
        "guest_timing": timing,
    }


async def verifier_run(args):
    args.private_output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = args.private_output.with_suffix(".log")
    env = {
        **os.environ,
        "DOCKER_HOST": args.docker_host,
        "TMPDIR": str(args.private_output.parent / "tmp"),
        "PYTHONPATH": str(ROOT / "src"),
    }
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as log:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "infra/run_qualified_lean.py",
            "--engineering-image-metadata",
            str(args.image_metadata),
            "--runtime-identity",
            str(args.runtime_identity),
            "--fixtures",
            str(args.fixtures),
            "--output",
            str(args.private_output),
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=asyncio.subprocess.STDOUT,
        )
    return process, log_path


async def docker_capture(args, *command: str) -> bytes:
    process = await asyncio.create_subprocess_exec(
        "docker",
        "--host",
        args.docker_host,
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=10)
    except TimeoutError:
        process.kill()
        await asyncio.wait_for(process.communicate(), timeout=5)
        raise
    if process.returncode != 0:
        raise RuntimeError("dedicated Docker observation failed")
    return output


async def running_containers(args) -> dict[str, str]:
    output = await docker_capture(args, "ps", "--no-trunc", "--format", "{{.ID}} {{.Names}}")
    return dict(line.split(" ", 1) for line in output.decode().splitlines() if " " in line)


def verifier_ids(containers: dict[str, str]) -> set[str]:
    return {
        identifier
        for identifier, name in containers.items()
        if name.startswith("physharness-check-")
    }


async def guest_monotonic(args, worker_id: str) -> float:
    observed = await docker_capture(
        args,
        "exec",
        "-i",
        worker_id,
        "/usr/bin/python3",
        "-c",
        "import time;print(time.monotonic())",
    )
    return float(observed)


async def watch_verifier_container(args, worker_ids: set[str], until: asyncio.Event) -> list[dict]:
    """Sample Linux time only while all N exact workers and one verifier run."""
    observations = []
    while not until.is_set():
        before = await running_containers(args)
        possible = verifier_ids(before)
        if worker_ids.issubset(before) and possible:
            observed = await guest_monotonic(args, sorted(worker_ids)[0])
            after = await running_containers(args)
            common = possible & verifier_ids(after)
            if worker_ids.issubset(after) and len(common) == 1:
                observations.append(
                    {"verifier_id": next(iter(common)), "guest_monotonic": observed}
                )
        await asyncio.sleep(0.2)
    return observations


async def host_memory_level() -> int:
    """Return macOS kern.memorystatus_level, the host's free-memory percentage."""
    process = await asyncio.create_subprocess_exec(
        "sysctl",
        "-n",
        "kern.memorystatus_level",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=10)
    except TimeoutError:
        process.kill()
        await asyncio.wait_for(process.communicate(), timeout=5)
        raise
    if process.returncode != 0:
        raise RuntimeError("host memory observation failed")
    return int(output)


async def sample_host_memory(args, worker_id: str) -> dict:
    """Read host memory once, bracketed by guest time to prove all commands were running."""
    sample = {"platform": sys.platform, "memorystatus_level": None}
    if sys.platform != "darwin":
        return sample
    await asyncio.sleep(HOST_MEMORY_SAMPLE_DELAY)
    try:
        before = await guest_monotonic(args, worker_id)
        sample["memorystatus_level"] = await host_memory_level()
        sample["guest_window"] = [before, await guest_monotonic(args, worker_id)]
    except (OSError, RuntimeError, TimeoutError, ValueError) as error:
        # Informational only: a failed read must not mask the capacity outcome.
        sample["error"] = type(error).__name__
    return sample


async def observe(args):
    capacity = args.capacity
    providers = [make_provider(args) for _ in range(capacity + 1)]
    root = ROOT.resolve()
    report = {
        "protocol": "s1-capacity-workbench-observation-v1",
        "capacity": capacity,
        "timeout_seconds": args.timeout_seconds,
        "worker_image": args.worker_image,
        "verifier_image_metadata_sha256": hashlib.sha256(
            args.image_metadata.read_bytes()
        ).hexdigest(),
        "runtime_identity_sha256": hashlib.sha256(args.runtime_identity.read_bytes()).hexdigest(),
        "fixture_sha256": hashlib.sha256(args.fixtures.read_bytes()).hexdigest(),
        # Repo-relative, so a committed report never carries a local absolute path.
        "verifier_log": str(args.private_output.resolve().with_suffix(".log").relative_to(root)),
        "verifier_output": str(args.private_output.resolve().relative_to(root)),
    }
    verifier = None
    try:
        initial = await providers[0].probe_capacity()
        report["initial_active"] = initial["active_workspaces"]
        if report["initial_active"] != 0:
            raise RuntimeError("existing labeled workbenches must be reconciled first")
        if verifier_ids(await running_containers(args)):
            raise RuntimeError("existing verifier containers must be reconciled first")
        await asyncio.gather(*(provider.create() for provider in providers[:capacity]))
        first_ids = [provider.execution_id for provider in providers[:capacity]]
        report["capacity_active"] = (await providers[0].probe_capacity())["active_workspaces"]
        try:
            await providers[capacity].create()
        except ExecutionError as error:
            report["over_capacity_admission"] = error.code
        else:
            report["over_capacity_admission"] = "unexpected"
            await providers[capacity].close()
            raise RuntimeError("workbench was admitted beyond capacity")
        await asyncio.gather(
            *(
                provider.upload_file(
                    "scratch/Check.lean", LEAN_SOURCE, expected_execution_id=provider.execution_id
                )
                for provider in providers[:capacity]
            )
        )
        verifier, _ = await verifier_run(args)
        verifier_started = time.monotonic()
        workers_done = asyncio.Event()
        verifier_observation = asyncio.create_task(
            watch_verifier_container(args, set(first_ids), workers_done)
        )
        memory_sample = asyncio.create_task(sample_host_memory(args, first_ids[0]))
        try:
            commands = await asyncio.gather(
                *(
                    workbench_command(provider, index)
                    for index, provider in enumerate(providers[:capacity])
                )
            )
        finally:
            workers_done.set()
            verifier_observations = await verifier_observation
            report["host_memory"] = await memory_sample
        window = report["host_memory"].get("guest_window")
        report["host_memory"]["during_all_commands"] = window is not None and all(
            item["guest_timing"] is not None
            and item["guest_timing"][0] <= window[0]
            and window[1] <= item["guest_timing"][1]
            for item in commands
        )
        verifier_container_overlapped = any(
            all(
                item["guest_timing"] is not None
                and item["guest_timing"][0]
                <= observation["guest_monotonic"]
                <= item["guest_timing"][1]
                for item in commands
            )
            for observation in verifier_observations
        )
        report["observed_verifier_ids"] = sorted(
            {observation["verifier_id"] for observation in verifier_observations}
        )
        verifier_alive_at_worker_finish = verifier.returncode is None
        await asyncio.wait_for(verifier.wait(), timeout=300)
        verifier_ended = time.monotonic()
        verifier_report = (
            json.loads(args.private_output.read_text()) if args.private_output.is_file() else {}
        )
        report.update(
            first_execution_ids_unique=len(set(first_ids)) == capacity,
            commands=commands,
            verifier={
                "exit_code": verifier.returncode,
                "status": verifier_report.get("status"),
                "started": verifier_started,
                "ended": verifier_ended,
                "alive_at_worker_finish": verifier_alive_at_worker_finish,
                "container_overlapped_workers": verifier_container_overlapped,
            },
        )

        # Keep N-1 original workbenches active while checking portable state.
        holder = providers[0]
        generations = []
        expected_files = {"scratch/Check.lean": LEAN_SOURCE}
        for generation in range(GENERATIONS):
            execution_id = holder.execution_id
            payload = f"generation-{generation}".encode()
            path = f"scratch/generation-{generation}.txt"
            await holder.upload_file(path, payload, expected_execution_id=execution_id)
            expected_files[path] = payload
            archive = await holder.export_workspace(expected_execution_id=execution_id)
            if archive.files() != expected_files:
                raise RuntimeError("exported workspace bytes differ")
            generations.append(
                {
                    "execution_id": execution_id,
                    "archive_sha256": archive.sha256,
                    "file_sha256": {
                        name: hashlib.sha256(data).hexdigest()
                        for name, data in sorted(expected_files.items())
                    },
                }
            )
            await holder.close()
            if generation == GENERATIONS - 1:
                break
            holder = make_provider(args)
            providers.append(holder)
            await holder.create()
            if holder.execution_id == execution_id:
                raise RuntimeError("restored generation reused execution identity")
            try:
                await holder.download_file("scratch/Check.lean", expected_execution_id=execution_id)
                raise RuntimeError("stale execution identity unexpectedly accepted")
            except ExecutionError as error:
                if error.code != "WORKSPACE_IDENTITY_MISMATCH":
                    raise
            await holder.restore_workspace(archive, expected_execution_id=holder.execution_id)
            if (
                await holder.export_workspace(expected_execution_id=holder.execution_id)
            ).files() != expected_files:
                raise RuntimeError("restored workspace bytes differ")
        report["generations"] = generations
        report["original_active_after_rotation"] = (await providers[1].probe_capacity())[
            "active_workspaces"
        ]

        # Cancellation intentionally retires this still-active provider.
        sleeper = asyncio.create_task(
            providers[1].run(
                CommandRequest(
                    operation_id="capacity-cancel",
                    argv=["python3", "-c", "import time;time.sleep(30)"],
                    cwd="/opt/sources/physlib",
                    timeout_seconds=60,
                    max_output_bytes=4096,
                )
            )
        )
        await asyncio.sleep(1)
        sleeper.cancel()
        try:
            await sleeper
            report["cancel_result"] = "unexpected_completion"
        except asyncio.CancelledError:
            report["cancel_result"] = "CancelledError"
        except ExecutionError as error:
            report["cancel_result"] = error.code
        report["active_after_cancellation"] = (await providers[2].probe_capacity())[
            "active_workspaces"
        ]
    finally:
        if verifier is not None and verifier.returncode is None:
            verifier.terminate()
            try:
                await asyncio.wait_for(verifier.wait(), timeout=10)
            except TimeoutError:
                verifier.kill()
                await asyncio.wait_for(verifier.wait(), timeout=10)
        if verifier is not None:
            report.setdefault("verifier", {})["exit_code"] = verifier.returncode
        try:
            cleanup = await asyncio.wait_for(
                asyncio.gather(*(item.close() for item in providers), return_exceptions=True),
                timeout=120,
            )
            report["cleanup_errors"] = [
                type(item).__name__ for item in cleanup if isinstance(item, BaseException)
            ]
        except TimeoutError:
            report["cleanup_errors"] = ["cleanup_timeout"]
        try:
            report["final_active"] = (
                await asyncio.wait_for(providers[0].probe_capacity(), timeout=15)
            )["active_workspaces"]
        except (ExecutionError, TimeoutError):
            report["final_active"] = None
        try:
            report["final_verifier_ids"] = sorted(
                verifier_ids(await asyncio.wait_for(running_containers(args), timeout=15))
            )
        except (RuntimeError, TimeoutError):
            report["final_verifier_ids"] = None
        report["passed"] = bool(
            report.get("capacity_active") == capacity
            and report.get("over_capacity_admission") == "WORKSPACE_CAPACITY"
            and report.get("first_execution_ids_unique")
            and len(report.get("commands", [])) == capacity
            and all(
                item["exit_code"] == 0 and item["check_seen"] and item["oom_delta"] == 0
                for item in report.get("commands", [])
            )
            and max(item["started"] for item in report.get("commands", []))
            < min(item["ended"] for item in report.get("commands", []))
            and report.get("verifier", {}).get("exit_code") == 0
            and report.get("verifier", {}).get("status") == "passed"
            and report.get("verifier", {}).get("alive_at_worker_finish") is True
            and report.get("verifier", {}).get("container_overlapped_workers") is True
            and len(report.get("observed_verifier_ids", [])) >= 1
            and report.get("cancel_result") == "CancelledError"
            and len(report.get("generations", [])) == GENERATIONS
            and len({row["execution_id"] for row in report.get("generations", [])}) == GENERATIONS
            and report.get("original_active_after_rotation") == capacity - 1
            and report.get("active_after_cancellation") == capacity - 2
            and not report["cleanup_errors"]
            and report["final_active"] == 0
            and report["final_verifier_ids"] == []
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if not report["passed"]:
        raise RuntimeError(f"{capacity}-workbench qualification failed; inspect private report")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-host", required=True)
    parser.add_argument("--worker-image", required=True)
    parser.add_argument("--image-metadata", type=Path, required=True)
    parser.add_argument("--runtime-identity", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--capacity", type=int, required=True)
    # 900 s leaves headroom for N concurrent Mathlib imports beside the verifier.
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    if not args.private_output.resolve().is_relative_to((ROOT / ".state").resolve()):
        parser.error("verifier output must be under private .state")
    if not 2 <= args.capacity <= 100:
        parser.error("capacity must be an integer from 2 to 100")
    if not 600 <= args.timeout_seconds <= 86400:
        parser.error("timeout must be from 600 to 86400 seconds")
    asyncio.run(asyncio.wait_for(observe(args), timeout=args.timeout_seconds))


if __name__ == "__main__":
    main()
