"""Opt-in local Docker observation; no model requests or scientific publication."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from physharness.execution.local_docker import LocalDockerWorkspaceProvider
from physharness.execution.types import CommandRequest, ExecutionError

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "work/parallel-pilot-2026-09-24/worker-qualification.json"
HOST = "unix:///Users/kieranpi/.colima/physharness-pilot/docker.sock"
IMAGE = "sha256:48e4f60a07c289baf846c0ff6fa2624870c59547c2a00971db0510e767161be0"
SOURCE = b"import Mathlib\n#check Nat.add_comm\n"


def provider():
    return LocalDockerWorkspaceProvider(
        docker_host=HOST, image_digest=IMAGE, max_active_workspaces=2, timeout_seconds=300
    )


async def command(worker, name, code, timeout=120):
    started = time.monotonic()
    result = await worker.run(
        CommandRequest(
            operation_id=name,
            argv=["python3", "-c", code],
            cwd="/opt/sources/physlib",
            timeout_seconds=timeout,
            max_output_bytes=65536,
        )
    )
    return {
        "exit_code": result.exit_code,
        "stdout_tail": result.stdout[-500:],
        "stderr_tail": result.stderr[-500:],
        "start_monotonic": started,
        "end_monotonic": time.monotonic(),
        "diagnostics": worker.last_command_diagnostics,
    }


async def main():
    first, second, third = provider(), provider(), provider()
    report = {"schema_version": 1, "docker_host": HOST, "worker_image": IMAGE}
    try:
        initial = await first.probe_capacity()
        report["initial_probe"] = initial
        if initial["active_workspaces"]:
            raise RuntimeError("existing labeled workbenches must be reconciled first")
        await asyncio.gather(first.create(), second.create())
        report["two_active_probe"] = await first.probe_capacity()
        report["worker_ids"] = [first.execution_id, second.execution_id]
        try:
            await third.create()
            report["third_result"] = "unexpected admission"
        except ExecutionError as exc:
            report["third_result"] = exc.code
        await asyncio.gather(
            first.upload_file("scratch/Check.lean", SOURCE, expected_execution_id=first.execution_id),
            second.upload_file("scratch/Check.lean", SOURCE, expected_execution_id=second.execution_id),
        )
        verifier = await asyncio.create_subprocess_exec(
            sys.executable,
            "infra/run_qualified_lean.py",
            "--engineering-image-metadata",
            "work/pilot-qualification-2026-09-23/attempt-network-01/image-metadata.json",
            "--runtime-identity",
            "work/pilot-qualification-2026-09-23/attempt-network-01/runtime-identity.json",
            "--fixtures",
            ".state/parallel-pilot-2026-09-24/evaluator/qualification-cases.json",
            "--output",
            ".state/parallel-pilot-2026-09-24/concurrent-targets-kernel.json",
            cwd=ROOT,
            env={
                **os.environ,
                "TMPDIR": str(ROOT / ".state/parallel-pilot-2026-09-24/tmp"),
                "DOCKER_HOST": HOST,
                "PATH": "/opt/homebrew/bin:" + os.environ.get("PATH", ""),
                "PYTHONPATH": str(ROOT / "src"),
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        report["verifier_start_monotonic"] = time.monotonic()
        code = (
            "import subprocess,time,sympy; "
            "p=subprocess.run(['lake','--offline','env','lean','/work/scratch/Check.lean'],"
            "capture_output=True,text=True); "
            "print(p.returncode,p.stdout[-200:],p.stderr[-200:]);p.check_returncode(); "
            "print(sympy.Matrix([[1,2],[3,4]]).det()); "
            "time.sleep(12)"
        )
        first_task = asyncio.create_task(command(first, "worker-lean-a", code))
        second_task = asyncio.create_task(command(second, "worker-lean-b", code))
        report["commands"] = await asyncio.gather(first_task, second_task)
        report["verifier_alive_after_commands"] = verifier.returncode is None
        stdout, stderr = await asyncio.wait_for(verifier.communicate(), 300)
        report["verifier_end_monotonic"] = time.monotonic()
        report["verifier"] = {
            "exit_code": verifier.returncode,
            "stdout_tail": stdout.decode(errors="replace")[-1000:],
            "stderr_tail": stderr.decode(errors="replace")[-1000:],
            "output": ".state/parallel-pilot-2026-09-24/concurrent-targets-kernel.json",
        }
        verifier_report = json.loads(
            (ROOT / ".state/parallel-pilot-2026-09-24/concurrent-targets-kernel.json").read_text()
        )
        report["verifier"]["report_status"] = verifier_report["status"]
        report["verifier"]["cases"] = [
            {
                "id": entry["id"],
                "expected_status": entry["expected_status"],
                "outcome_status": entry["outcome"].get("status"),
                "outcome_code": entry["outcome"].get("code"),
            }
            for entry in verifier_report["results"]
        ]
        await first.close()
        report["after_first_close_probe"] = await second.probe_capacity()
        replacement = provider()
        try:
            await replacement.create()
            report["replacement_id"] = replacement.execution_id
            report["replacement_probe"] = await replacement.probe_capacity()
            sleeper = asyncio.create_task(
                command(replacement, "cancel", "import time;time.sleep(30)", timeout=60)
            )
            await asyncio.sleep(1)
            sleeper.cancel()
            try:
                await sleeper
            except (asyncio.CancelledError, ExecutionError) as exc:
                report["cancel_result"] = type(exc).__name__
            report["after_cancel_probe"] = await second.probe_capacity()
        finally:
            await replacement.close()
        report["final_probe_before_cleanup"] = await second.probe_capacity()
    finally:
        cleanup = await asyncio.gather(
            first.close(), second.close(), third.close(), return_exceptions=True
        )
        report["cleanup_errors"] = [str(item) for item in cleanup if isinstance(item, BaseException)]
        report["final_probe"] = await first.probe_capacity()
        commands = report.get("commands", [])
        report["passed"] = bool(
            len(commands) == 2
            and all(
                item["exit_code"] == 0
                and "Nat.add_comm" in item["stdout_tail"]
                and "-2" in item["stdout_tail"]
                and item["diagnostics"]["oom_delta"] == 0
                for item in commands
            )
            and max(item["start_monotonic"] for item in commands)
            < min(item["end_monotonic"] for item in commands)
            and len(set(report.get("worker_ids", []))) == 2
            and report.get("third_result") == "WORKSPACE_CAPACITY"
            and report.get("verifier", {}).get("exit_code") == 0
            and report.get("verifier", {}).get("report_status") == "passed"
            and report.get("verifier_alive_after_commands") is True
            and report.get("cancel_result") == "CancelledError"
            and not report["cleanup_errors"]
            and report["final_probe"]["active_workspaces"] == 0
        )
        OUT.write_text(json.dumps(report, indent=2, default=str) + "\n")
    if not report["passed"]:
        raise RuntimeError("Parallel worker qualification failed; inspect saved report")
    return report


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=540))
