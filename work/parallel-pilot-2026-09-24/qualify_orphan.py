"""Opt-in crash/orphan observation against the dedicated local Docker VM."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from physharness.execution.local_docker import LocalDockerWorkspaceProvider

ROOT = Path(__file__).resolve().parents[2]
HOST = "unix:///Users/kieranpi/.colima/physharness-pilot/docker.sock"
IMAGE = "sha256:48e4f60a07c289baf846c0ff6fa2624870c59547c2a00971db0510e767161be0"
OUT = ROOT / "work/parallel-pilot-2026-09-24/worker-qualification.json"


def docker(*args):
    return subprocess.run(
        ["docker", "--host", HOST, *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


async def child(label):
    worker = LocalDockerWorkspaceProvider(
        docker_host=HOST,
        image_digest=IMAGE,
        max_active_workspaces=2,
        timeout_seconds=300,
        journal=SimpleNamespace(workspace_id=label),
    )
    await worker.create()
    print(json.dumps({"id": worker.execution_id, "label": label}), flush=True)
    os._exit(0)


def parent():
    label = "qualification-orphan-" + uuid4().hex
    report = json.loads(OUT.read_text())
    child_process = subprocess.run(
        [sys.executable, __file__, "child", label],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if child_process.returncode:
        raise RuntimeError(child_process.stderr[-2000:])
    observed = json.loads(child_process.stdout)
    identifier = observed["id"]
    try:
        listed = docker(
            "ps",
            "--filter",
            f"label=physharness.workspace={label}",
            "--format",
            "{{.ID}}",
        ).splitlines()
        full_id = docker("inspect", "--format", "{{.Id}}", identifier)
        assert len(listed) == 1 and full_id == identifier
        assert identifier.startswith(listed[0])
        report["crash_orphan"] = {
            "journal_workspace_label": label,
            "execution_id": identifier,
            "found_after_creator_exit": True,
            "status": "explicitly_uncertain_until_reconciled",
        }
    finally:
        docker("rm", "-f", identifier)
        remaining = docker("ps", "--filter", f"label=physharness.workspace={label}", "--format", "{{.ID}}")
        report.setdefault("crash_orphan", {})["removed_exact_container"] = remaining == ""
        OUT.write_text(json.dumps(report, indent=2) + "\n")
    assert report["crash_orphan"]["removed_exact_container"]


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "child":
        asyncio.run(child(sys.argv[2]))
    else:
        parent()
