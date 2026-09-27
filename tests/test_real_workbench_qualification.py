"""Opt-in qualification against the dedicated Linux Docker endpoint.

Set PHYSHARNESS_WORKBENCH_DOCKER_HOST and PHYSHARNESS_WORKBENCH_IMAGE_DIGEST.
These tests allocate and remove local containers; they make no paid model calls.
"""

import base64
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from physharness.execution.local_docker import LocalDockerWorkspaceProvider
from physharness.execution.types import CommandRequest, ExecutionError
from physharness.orchestration.lean_session import LeanSession


@pytest.mark.integration
async def test_real_isolated_workbench_checkpoint_and_science():
    host = os.environ.get("PHYSHARNESS_WORKBENCH_DOCKER_HOST")
    image = os.environ.get("PHYSHARNESS_WORKBENCH_IMAGE_DIGEST")
    if not host or not image:
        pytest.skip("Dedicated workbench endpoint and image digest are required")

    async def command(provider, operation, argv, *, cwd=".", timeout=30):
        return await provider.run(
            CommandRequest(
                operation_id=operation,
                argv=argv,
                cwd=cwd,
                timeout_seconds=timeout,
                max_output_bytes=65536,
            )
        )

    first = LocalDockerWorkspaceProvider(
        docker_host=host,
        image_digest=image,
        timeout_seconds=180,
    )
    second = LocalDockerWorkspaceProvider(
        docker_host=host,
        image_digest=image,
        timeout_seconds=180,
    )
    try:
        await first.create()
        metadata = await command(
            first,
            "metadata",
            [
                "python3",
                "-c",
                "import os,numpy,scipy,sympy;print(os.getuid());"
                "print(numpy.__version__,scipy.__version__,sympy.__version__);"
                "print(os.path.isdir('/opt/sources/physlib'))",
            ],
        )
        assert metadata.exit_code == 0
        assert metadata.stdout.splitlines()[0] == "65532"
        assert metadata.stdout.splitlines()[-1] == "True"
        assert first.last_command_diagnostics["phase"] == "completed"
        assert first.last_command_diagnostics["memory_after"]["peak_bytes"] > 0

        isolated = await command(
            first,
            "isolated",
            [
                "python3",
                "-c",
                "import os,socket;print(os.path.exists('/var/run/docker.sock'));"
                "s=socket.socket();s.settimeout(1);"
                "s.connect(('1.1.1.1',53))",
            ],
        )
        assert isolated.exit_code != 0
        assert isolated.stdout.startswith("False")

        source = b"import Mathlib\n#check Nat.add_comm\n"  # Scratch proof only.
        await first.upload_file(
            "scratch/Check.lean", source, expected_execution_id=first.execution_id
        )
        lean = await command(
            first,
            "lean",
            ["lake", "--offline", "env", "lean", "/work/scratch/Check.lean"],
            cwd="/opt/sources/physlib",
            timeout=90,
        )
        assert lean.exit_code == 0, lean.stderr
        assert "Nat.add_comm" in lean.stdout

        typed = b"import QuantumInfo.States.Mixed.MState\n#check MState.Hermitian\n"
        await first.upload_file(
            "scratch/QualifiedName.lean", typed, expected_execution_id=first.execution_id
        )
        declaration = await command(
            first,
            "declaration",
            ["lake", "--offline", "env", "lean", "/work/scratch/QualifiedName.lean"],
            cwd="/opt/sources/physlib",
            timeout=90,
        )
        assert declaration.exit_code == 0, declaration.stderr
        assert "MState.Hermitian" in declaration.stdout

        data = b"n" * 100_000
        await first.upload_file("notes/large.txt", data, expected_execution_id=first.execution_id)
        archive = await first.export_workspace(expected_execution_id=first.execution_id)
        assert archive.files()["notes/large.txt"] == data
        assert archive.to_bytes().startswith(b"PHW2")

        await first.close()
        await second.create()
        await second.restore_workspace(archive, expected_execution_id=second.execution_id)
        assert (
            await second.download_file("notes/large.txt", expected_execution_id=second.execution_id)
            == data
        )
        exact = await second.read_range(
            "notes/large.txt",
            offset=99_990,
            length=20,
            expected_execution_id=second.execution_id,
        )
        assert base64.b64decode(exact["data"]) == b"n" * 10
        assert exact["sha256"] == hashlib.sha256(data).hexdigest()
        with pytest.raises(ExecutionError):
            await command(
                second,
                "background",
                [
                    "python3",
                    "-c",
                    "import subprocess;subprocess.Popen(['sleep','30'],"
                    "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
                    "stderr=subprocess.DEVNULL,start_new_session=True)",
                ],
            )
        assert second._container_id is None
    finally:
        await first.close()
        await second.close()


@pytest.mark.integration
async def test_real_login_shell_path():
    host = os.environ.get("PHYSHARNESS_WORKBENCH_DOCKER_HOST")
    image = os.environ.get("PHYSHARNESS_WORKBENCH_IMAGE_DIGEST")
    if not host or not image:
        pytest.skip("Dedicated workbench endpoint and image digest are required")
    provider = LocalDockerWorkspaceProvider(
        docker_host=host, image_digest=image, timeout_seconds=180
    )

    async def run(arguments, operation_id):
        request = CommandRequest(operation_id=operation_id, max_output_bytes=65536, **arguments)
        return (await provider.run(request)).model_dump()

    try:
        await provider.create()
        login = await run(
            {
                "argv": ["bash", "-lc", "command -v lake && command -v lean"],
                "cwd": ".",
                "timeout_seconds": 30,
            },
            "login-path",
        )
        assert login["exit_code"] == 0, login["stderr"]
        assert [Path(line).name for line in login["stdout"].split()] == ["lake", "lean"]
        listed = await run(
            {"argv": ["ls", "-A", "/etc/profile.d"], "cwd": ".", "timeout_seconds": 30}, "ls"
        )
        assert listed["stdout"].split() == ["physharness-path.sh"]
    finally:
        await provider.close()


@pytest.mark.integration
async def test_real_statement_check_end_to_end():
    """The statement check completes in one 2 GiB workbench: an ``import Lean`` source (it was
    OOM-killed), a Mathlib source, and a mismatched statement."""
    host = os.environ.get("PHYSHARNESS_WORKBENCH_DOCKER_HOST")
    image = os.environ.get("PHYSHARNESS_WORKBENCH_IMAGE_DIGEST")
    if not host or not image:
        pytest.skip("Dedicated workbench endpoint and image digest are required")
    provider = LocalDockerWorkspaceProvider(
        docker_host=host, image_digest=image, timeout_seconds=900
    )

    async def run(arguments, operation_id):
        request = CommandRequest(operation_id=operation_id, max_output_bytes=65536, **arguments)
        return (await provider.run(request)).model_dump()

    async def write(arguments, operation_id):
        data = arguments["content"].encode()
        await provider.upload_file(
            arguments["path"], data, expected_execution_id=provider.execution_id
        )
        return {"path": arguments["path"]}

    session = LeanSession(
        SimpleNamespace(policy=SimpleNamespace(timeout_seconds=300), run=run, write=write)
    )
    real = "import Mathlib.Data.Real.Basic"
    cases = [  # header, name, the node's signature, and what the source proves
        ("import Lean", "physharness_checker_self_test", ": True", ": True := trivial"),
        (real, "physharness_real_check", "(x : ℝ) : x + 0 = x", "(x : ℝ) : x + 0 = x := by simp"),
        (real, "physharness_real_check", "(x : ℝ) : x + 0 = x", "(x : ℝ) : 0 + x = x := by simp"),
    ]
    try:
        await provider.create()
        verdicts = []
        for index, (header, name, signature, proof) in enumerate(cases):
            source = f"{header}\n\ntheorem {name} {proof}\n"
            verdicts.append(
                await session.verify_statement(
                    source, header, name, signature, operation_id=f"real-check-{index}"
                )
            )
            assert provider.last_command_diagnostics["oom_delta"] == 0, verdicts[-1]
        lean, mathlib, mismatch = verdicts
        assert lean["ok"] is True and lean["axioms"] == [], lean
        assert mathlib["ok"] is True, mathlib
        assert set(mathlib["axioms"]) <= {"propext", "Classical.choice", "Quot.sound"}
        assert mismatch["ok"] is False and mismatch["reason"] == "statement_mismatch", mismatch
    finally:
        await provider.close()
