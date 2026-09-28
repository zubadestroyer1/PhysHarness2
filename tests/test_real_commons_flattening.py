"""Opt-in: a flattened commons candidate compiles and passes the statement check in the real
workbench (S1 audit #12).

Set PHYSHARNESS_WORKBENCH_DOCKER_HOST and PHYSHARNESS_WORKBENCH_IMAGE_DIGEST, and pre-warm the
VM first (docs/FORMAL_ENVIRONMENT.md). This test allocates and removes one local container; it
makes no paid model calls. The independent verifier's run on a flattened candidate is left to
the first A/B smoke run.
"""

import os
from types import SimpleNamespace

import pytest

from physharness.commons_models import STANDARD_AXIOMS
from physharness.commons_sources import Module, inline_commons, remap
from physharness.execution.local_docker import LocalDockerWorkspaceProvider
from physharness.execution.types import CommandRequest
from physharness.orchestration.lean_session import LeanSession, parse_lean_output

HEADER = "import Mathlib.Data.Real.Basic"
A, B = "Commons.Naaaaaaaa", "Commons.Nbbbbbbbb"
# Module A leaves a namespace open, and B imports A: the inliner closes one and orders both.
MODULES = {
    A: Module(
        A,
        "node-a",
        f"{HEADER}\nopen Real\nnamespace PhysA\n\ntheorem shift (x : ℝ) : x + 0 = x := by simp\n",
        "verified",
        "a" * 64,
    ),
    B: Module(
        B,
        "node-b",
        f"{HEADER}\nimport {A}\n\ntheorem physharness_twice (x : ℝ) : x + 0 + 0 = x := by\n"
        "  rw [PhysA.shift, PhysA.shift]\n",
        "verified",
        "b" * 64,
    ),
}
NAME, SIGNATURE = "physharness_flat_check", "(x : ℝ) : x + 0 + 0 = x"


@pytest.mark.integration
async def test_real_flattened_candidate_compiles_and_passes_the_statement_check():
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

    async def compile_flat(expansion, path):
        await write({"path": path, "content": expansion.source}, f"write-{path}")
        return await run(
            {
                "argv": ["lake", "--offline", "env", "lean", "/work/" + path],
                "cwd": "/opt/sources/physlib",
                "timeout_seconds": 300,
            },
            f"compile-{path}",
        )

    session = LeanSession(
        SimpleNamespace(policy=SimpleNamespace(timeout_seconds=300), run=run, write=write)
    )
    caller = f"import {B}\n{HEADER}\n\ntheorem {NAME} {SIGNATURE} :=\n  physharness_twice x\n"
    flat = inline_commons(caller, MODULES.__getitem__, max_bytes=30_000)
    assert [module.name for module in flat.modules] == [A, B]
    # An error on the caller's line 7 is reported there, not at its flattened line.
    broken = inline_commons(
        caller + "\ntheorem physharness_wrong : (1 : ℝ) = 2 := rfl\n",
        MODULES.__getitem__,
        max_bytes=30_000,
    )
    try:
        await provider.create()
        compiled = await compile_flat(flat, "scratch/Flat.lean")
        assert compiled["exit_code"] == 0, compiled["stdout"] + compiled["stderr"]
        assert provider.last_command_diagnostics["oom_delta"] == 0
        failed = await compile_flat(broken, "scratch/Broken.lean")
        output = failed["stdout"] + "\n" + failed["stderr"]
        messages = parse_lean_output(output, "/work/scratch/Broken.lean")
        errors = remap({"messages": messages, "holes": []}, broken)["messages"]
        assert {message["line"] for message in errors if message["severity"] == "error"} == {7}
        verdict = await session.verify_statement(
            flat.source, HEADER, NAME, SIGNATURE, operation_id="flat-check"
        )
        assert provider.last_command_diagnostics["oom_delta"] == 0, verdict
        assert verdict["ok"] is True, verdict
        assert set(verdict["axioms"]) <= STANDARD_AXIOMS
    finally:
        await provider.close()
