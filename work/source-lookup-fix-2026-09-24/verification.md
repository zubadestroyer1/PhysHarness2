# Source lookup roundtrip fix evidence

Baseline snapshot: `workspace_tools.py.before`, SHA-256
`275e59d81bb3dabbcfcd209464e442c115db1f582d24dbb07bd3d6ec92a92793`.
This preserves the already modified source file as it stood before this fix.

Red, before production edits: `.venv/bin/pytest -q tests/test_library_source_roundtrip.py`
reported **3 failed, 8 passed**. Both Physlib and Mathlib search-hit assertions saw
absolute `/opt/sources/...` paths without `guest_path`; the missing-file assertion
saw an absolute path instead of the canonical lookup argument. The subsequently
added NUL-path case failed with `ValueError: embedded null byte` from subprocess
before adding validation.

Green, after edits: `.venv/bin/pytest -q tests/test_library_source_roundtrip.py
tests/test_workbench_tool_schemas.py` reported **15 passed, 1 skipped**; the skip
is the opt-in pinned-image test without its two environment variables. `.venv/bin/ruff
check src/physharness/orchestration/workspace_tools.py tests/test_library_source_roundtrip.py`
reported **All checks passed**. The new test file passes `ruff format --check`.
The pre-existing dirty source file has unrelated formatting differences, so it was
not reformatted wholesale.

The temporary-fixture tests execute the generated scan and read Python scripts
through a local broker that maps `/opt/sources` to a temporary tree. The opt-in
test uses the dedicated pinned Docker provider and requires
`PHYSHARNESS_WORKBENCH_DOCKER_HOST` and
`PHYSHARNESS_WORKBENCH_IMAGE_DIGEST`; it allocates and closes one container.
