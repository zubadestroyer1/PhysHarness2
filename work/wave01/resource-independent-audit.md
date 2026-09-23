# Independent verifier-resource integration audit

Date: 2026-09-22

## Verdict

**Specification compliance: not yet compliant.** The implementation consistently applies the bounded 8 GiB / 4 CPU / 600 second / one-slot profile to Docker, the in-container comparator, the engineering runner, the fixed boundary probe, benchmark assessment, and qualification evidence. It also separates timeout, output-overflow, transport/termination, and positively observed OOM outcomes; captures Docker state before cleanup; preserves the prior failure when cleanup itself fails; includes the policy source in the image build context; and leaves human/deployment approval pending.

One material binding defect remains: the production startup qualification object does not pin the raw resource-profile source hash or the resource-policy implementation hash. Both hashes exist in engineering and qualification reports, but they are absent from `ExecutionPins`/`LinuxQualification`. Therefore startup and the normal verifier preflight can accept a mixed or stale qualification after a policy-only change, and startup can accept byte-different profile JSON so long as it canonicalizes to the same values. This violates the requirement to reject stale, mixed, or missing resource pins at startup and to keep source, canonical-profile, and policy hashes distinct and bound.

**Code quality: generally focused and sound, with the binding gap above requiring repair.** The resource policy is small and bounded, no generalized scheduler was introduced, failure cleanup is explicit, and the synthetic/local verification claims are accurately labeled. The lock implementation is appropriately local, although one docstring overstates its scope.

## Findings

### [P1] Production qualification omits two required resource identities

- `src/physharness/verification/boundary.py:106-121` defines `ExecutionPins` and `LinuxQualification` with only `resource_profile_sha256`; there is no `resource_profile_source_sha256` or `resource_policy_sha256`.
- `src/physharness/bootstrap.py:45-70` loads that incomplete qualification record and checks only the canonical profile digest. With no explicit resource file it silently constructs `ResourceProfile()`; with an explicit file it accepts any byte representation that parses to the same canonical profile.
- `src/physharness/verification/boundary.py:396-431` checks the canonical profile, driver, launcher, and seccomp hashes during bundle validation, but never checks a qualification-owned policy hash or profile-source hash.
- `src/physharness/verification/boundary.py:509-516` compares the worker response to the *current host* policy hash. This prevents host/image disagreement, but does not prove that either policy was covered by the supplied qualification. A policy-only edit can be copied into a new image and used with an old qualification whose other pins still match.
- `infra/run_qualified_lean.py:159-180` has the same issue in legacy/CI qualification consumption: it records source and policy hashes in the report, then derives `ExecutionPins` from the qualification model, which cannot contain either pin.
- In contrast, `src/physharness/verification/qualification.py:432-448` correctly requires all three identities in suite reports, showing that the hashes are available and intentionally distinct at evidence-assessment time.

**Required repair:** add explicit `resource_profile_source_sha256` and `resource_policy_sha256` fields to `ExecutionPins` (and consequently `LinuxQualification`); bind both in `_bundle`; require startup to read a pinned resource-profile file and compare both its raw digest and canonical digest; compare the policy pin to `resource_policy.policy_digest()` before execution; and carry those fields through all qualification-to-runner conversions. Add regressions proving that (1) a whitespace-only/profile-byte change is rejected at startup despite an unchanged canonical hash, (2) a policy-only change invalidates qualification before container launch, and (3) missing legacy fields fail closed. Qualification issuance must populate these fields from the reviewed scope; no code path should infer human approval from their presence.

### [P3] Slot-lock documentation overstates its scope

- `src/physharness/verification/boundary.py:313-324` documents the lock as “One service-host checker,” but the actual guarantee is one process holding the same filesystem lock path for the same visible lock namespace and compatible UID. Different temporary directories, containers/mount namespaces, or service users do not share this lock.

**Required repair:** change the docstring to state the exact local lock-path/UID scope, matching the completion report. No scheduler or fleet-wide abstraction is needed.

## Confirmed compliant areas

- The single typed bounded profile and canonical hash are implemented in `src/physharness/verification/resource_policy.py:9-61`; strict Pydantic validation delegates to the same bounds in `src/physharness/verification/boundary.py:35-50`.
- Host timeout/output limits derive from the profile, and contradictory legacy values are rejected in `src/physharness/verification/boundary.py:124-150`. The old hidden 110-second cap is absent.
- Docker limits are profile-derived in `src/physharness/verification/boundary.py:625-650`; the comparator deadline/output bound are profile-derived in `src/physharness/verification/container_driver.py:127-174`.
- OOM requires a positive typed counter increase inside the driver (`container_driver.py:42-60`) or Docker's typed `OOMKilled: true` state (`boundary.py:678-687`, `694-703`). Exit 137 and candidate/comparator text alone remain uncertain blocked termination codes.
- State inspection precedes cleanup on every container path, cleanup failure retains `prior_failure`, and successful outcomes cannot survive unconfirmed cleanup (`boundary.py:690-712`, `738-783`).
- Benchmark and deployment qualification assessment reject mismatched report-level canonical profile, source-profile, and policy hashes (`benchmark_artifacts.py:268-315`; `qualification.py:422-495`, `541-565`). Historical evidence is not rewritten.
- `formal/Dockerfile:48-58` copies the policy into both verifier image targets, and `tools/formal_environment.py` includes that source in the curated build context. No tracked mathematical benchmark manifests appear in the reviewed diff.
- The completion report explicitly labels all cited test evidence synthetic/local and leaves real Docker/Lean execution, independent human review, and production qualification pending.

## Evidence reviewed

Reviewed the completion brief, completion report, all 3,041 lines of `.state/wave01/resource-review.diff`, and the explicitly named untracked policy, profile, and test files. I also inspected the current driver, launcher, probe, engineering runner, bootstrap/configuration, benchmark assessment, qualification models/checks, Dockerfile, build-context generator, and resource-focused regressions. `git diff --check` exited 0 during this audit. I did not run Docker or Lean, alter implementation or frozen evidence, commit, or claim human approval. The completion report's existing Python test evidence was reused; no broad duplicate test run was necessary to establish the model-level missing-pin defect.

## Resolution re-audit — 2026-09-22

**Final specification verdict: compliant at the ordinary Python/synthetic evidence level.** The accepted P1 and P3 findings above are resolved. Real Docker/Lean execution, deployment evidence, and independent human review remain pending and are not inferred by this verdict.

- `ExecutionPins`/`LinuxQualification` now require the canonical profile, raw profile-source, and policy-source SHA256 fields (`boundary.py:106-121`). Strict extra-forbid validation makes legacy records missing either new pin fail closed.
- `RunConfig` keeps the raw source hash separately from the parsed `ResourceProfile` (`boundary.py:124-154`). `_bundle` compares both profile identities and the current policy hash against qualification before container launch (`boundary.py:398-409`).
- Single-bundle configuration now requires an explicit resource-profile path (`config.py:88-114`). Startup reads those exact bounded, non-symlink bytes once, computes their raw hash, validates their canonical profile, checks all three qualification pins, and only then constructs the verifier (`bootstrap.py:52-88`). This closes the canonical-equal whitespace bypass and policy-only stale-qualification bypass.
- Qualified-CI and engineering runner paths carry all three identities into `ExecutionPins` and `RunConfig` (`run_qualified_lean.py:156-184`, `219-269`, `299-311`). The qualification matrix includes the adversarial startup and pre-launch regressions, including missing legacy fields; their inclusion remains mechanical evidence and grants no approval.
- The lock docstring now states one holder for the same lock path, visible namespace, and compatible service UID (`boundary.py:317-328`). It makes no fleet scheduling claim and introduces no scheduler abstraction.
- The repair did not alter the verifier image inputs recorded in the completion report: Dockerfile `41b0cdd6…671b6`, build-context generator `360c56bd…aa07`, driver `cb1b6852…b58f`, and policy `10f33fbd…02bd`. The final host launcher digest after formatting is `16f2800d8ea861adb169dbd9cdc6cf207024d231f1f64d762bef7a2837cb1572`; qualification scope must use that final value. Frozen mathematical manifests and historical evidence remain unchanged.

Independent focused reproduction after final formatting: `.venv/bin/pytest -q tests/test_verifier_resource_bootstrap.py tests/test_verifier_resources.py` exited 0 with `39 passed in 1.49s`. The completion report additionally records `165 passed` for the repaired verifier/qualification focus set, `269 passed` for the expanded affected set, and `800 passed, 4 skipped` for the full ordinary suite. No Docker, Lean, GitHub, commit, implementation edit, or approval issuance was performed by this re-audit.
