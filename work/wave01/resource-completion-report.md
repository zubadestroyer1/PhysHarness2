# Verifier resource integration completion report

Date: 2026-09-22

## Outcome

The interrupted bounded-resource integration is complete at the ordinary Python-test level. The 8 GiB / 4 CPU / 600 second / one local slot profile now drives the Docker limits, trusted request and response binding, runner, fixed boundary probe, benchmark assessment, bootstrap, and qualification assessment. Raw profile-source SHA256, canonical profile SHA256, and policy-source SHA256 remain separate fields.

The final correction captures sanitized Docker state before cleanup on successful as well as failed verifier runs. A typed `OOMKilled: true` observation blocks even a nominally successful transport receipt; exit 137 and worker output alone still do not establish OOM. Cleanup remains inside the local checker-slot lifetime and its result is retained with success and failure diagnostics.

The formal build-context allowlist now includes `src/physharness/verification/resource_policy.py`, matching the Dockerfile copy instruction. Its exact allowlist regression prevents a real image build from failing due to the missing policy source.

The local file lock claims only one checker for the same service UID and lock path. It makes no fleet, VM-wide, or distributed scheduling claim.

## Focused corrections made during completion

- `src/physharness/verification/boundary.py`: capture sanitized Docker state before cleanup for every run, retain it in diagnostics, and block a nominal success on positive Docker OOM evidence.
- `infra/run_qualified_lean.py`: hash the exact resource-profile snapshot already read and validated, avoiding a second read when recording the raw source hash.
- `tools/formal_environment.py`: include the new resource-policy module in the curated image build context.
- `tests/test_verifier_resources.py`: cover state capture ordering and positive OOM handling on a successful transport receipt.
- `tests/test_formal_environment.py`: cover the resource-policy file in the exact context allowlist.

The broader interrupted integration already present in the dirty worktree affects the resource policy, driver, qualification, probe, bootstrap/configuration, benchmark assessment, formal Dockerfile/matrix, documentation, and their tests. Existing dirty files and historical evidence were preserved. Mathematical manifests and the generated reference package were not modified.

## Verification

All verification below was synthetic/local Python execution. No Docker image, container, Lean process, GitHub operation, commit, or push was run by this task.

- Initial focused integration suite: exit 0, `214 passed in 3.49s`.
- Expanded focused suite after corrections: exit 0, `237 passed in 3.97s`.
- Full ordinary Python suite after corrections: exit 0, `794 passed, 4 skipped, 21 warnings in 25.76s`.
- `git diff --check`: exit 0.
- Ruff over all affected Python implementation and test files: exit 0, `All checks passed!`.

The four full-suite skips are the repository's conditional skips. The 21 warnings are upstream Starlette/AnyIO/OpenHands SDK deprecation or unsupported warnings; there were no test failures.

## Current fixed image-input hashes

These hashes were measured after the final local checks. Fixture sources under the curated smoke/adversarial directories are also included by the tested context generator and remain unchanged by this task.

| Input | SHA256 |
|---|---|
| `formal/Dockerfile` | `41b0cdd6b094c55b4b8c58ad7877645a641f897a89fd25926645902e7d8671b6` |
| `formal/environment.lock.json` | `c5615b4f818bb8dfefc0281f116d2ece500597a488eb4ee244b330d41c9235c5` |
| `formal/prepare_lake.py` | `4aff00dfabebcf860e25fa84543356a32be09d8e610276d0d3e4b554eb44c572` |
| `formal/record_build.py` | `0f579a352b1891d6c9ee54f04c063290332da1ca5084d56953a21595fc9c0866` |
| `formal/DeclarationAudit.lean` | `179cc31b931926c96e2410bfa791837464a8bb05df62523658130b24c4bc7668` |
| `tools/formal_environment.py` | `360c56bd18ed5861bc6a0d8acf921fe4aceac9265feedef689f9a26d6937aa07` |
| `src/physharness/verification/container_driver.py` | `cb1b6852f4fbd89f528fed384afcc275c27fbe7f7584c3e74927e151bff8b58f` |
| `src/physharness/verification/resource_policy.py` | `10f33fbd312fc8dbdbcdd508f88720a5ead8ec96720645178aaa8946745a02bd` |
| `formal/verifier-resources.json` (profile source, outside image context) | `c85c68cc4329b1c622c2909b9fd99ea5c029fe04cbed120036d15893d5afc6d4` |

## Readiness and remaining concerns

The Dockerfile, curated build context, driver, and resource policy are stable enough for root to start the expensive real image build and runtime evidence collection.

Real Docker/Lean execution remains pending. In particular, synthetic tests do not establish cgroup `memory.events` availability, actual 8 GiB capacity, runtime timeout/cancellation behavior, Docker-state availability on the target daemon, or successful cleanup on the deployment host. The existing historical image and qualification evidence is intentionally stale for these new hashes and profile. Independent human review and production qualification remain pending, as required.

## Independent-audit repair

The accepted P1 and P3 findings in `work/wave01/resource-independent-audit.md` were repaired without changing frozen image inputs or benchmark/historical evidence.

- `ExecutionPins` and `LinuxQualification` now require `resource_profile_sha256`, `resource_profile_source_sha256`, and `resource_policy_sha256`. Strict model validation makes legacy records missing either new field fail closed.
- `RunConfig` retains the raw profile-source hash separately from its parsed canonical `ResourceProfile`.
- Single-bundle startup requires `PHYSHARNESS_VERIFICATION_RESOURCES`, reads its bytes once through the trusted bounded reader, and checks raw source, canonical profile, and current policy hashes against the qualification before constructing a verifier.
- Normal bundle preflight checks raw profile and policy pins before container launch. Both qualified-CI and engineering runner conversions carry all three identities.
- The slot-lock docstring now states its actual same-lock-path, visible-namespace, compatible-UID scope.
- `formal/qualification-matrix.json` requires the new source, policy, and missing-pin regressions. Their presence records mechanical coverage only and does not infer human approval.

Audit-repair verification:

- `.venv/bin/pytest -q tests/test_verifier_resource_bootstrap.py tests/test_verifier_resources.py tests/test_verification.py tests/test_verifier_qualification.py`: exit 0, `165 passed in 4.02s` after one assertion-message correction.
- `.venv/bin/pytest -q tests/test_api.py tests/test_config_security.py tests/test_memory_api.py tests/test_verifier_registry.py tests/test_formal_environment.py tests/test_verifier_resources.py tests/test_verifier_resource_bootstrap.py tests/test_verification.py tests/test_verifier_boundary_probe.py tests/test_verifier_qualification.py tests/test_physics_benchmarks.py`: exit 0, `269 passed, 2 warnings in 4.88s`.
- `.venv/bin/pytest -q`: exit 0, `800 passed, 4 skipped, 21 warnings in 32.34s`.
- `git diff --check`: exit 0.
- `.venv/bin/ruff check` over the audit-repair implementation/tests: exit 0, `All checks passed!` after correcting import order.

One attempted aggregate command named nonexistent `tests/test_config.py` and `tests/test_bootstrap.py`; pytest exited 4 with no tests run. It was replaced by the explicit existing configuration/API/registry files in the successful 269-test command above.

Frozen image inputs were rehashed after the repair and are unchanged: Dockerfile `41b0cdd6...671b6`, build-context generator `360c56bd...aa07`, driver `cb1b6852...b58f`, and policy `10f33fbd...02bd`. No Docker or Lean execution was performed by this repair.

Post-audit formatting was applied with Ruff only to the changed Python files. It reformatted `src/physharness/config.py` and `src/physharness/verification/boundary.py`; the other five repair files were already formatted. Ruff format-check, Ruff lint, and `git diff --check` all exited 0. The focused resource/verification suite then exited 0 with `165 passed in 3.93s`. The finalized host launcher (`boundary.py`) SHA256 is `16f2800d8ea861adb169dbd9cdc6cf207024d231f1f64d762bef7a2837cb1572`. Frozen image-input hashes remain unchanged.
