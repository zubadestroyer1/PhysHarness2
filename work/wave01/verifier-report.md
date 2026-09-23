# Wave 1 verifier evidence implementation report

Task 3 implementation is ready for root-scheduled Linux observations. This report records host implementation and validation only. It does not assert that the new fixed boundary probe or fresh image suites have run; the root's actual execution reports are separate evidence. Scientific review and deployment approval remain pending, and production qualification is false.

## Delivered behavior

`src/physharness/verification/qualification.py` captures an exact deployment scope and assesses bounded, pinned evidence offline. It creates a readable pending operator packet. It performs no Docker/Lean execution, service/database write, semantic review, receipt creation or approval. Current input hashes are checked before and after evidence processing, including secondary JUnit bytes.

`formal/qualification-matrix.json` requires the same core nine and library three cases in both Lean and independent nanoda modes; the fixed benign boundary probe; and named transport, authority, atomicity and reporting regressions. Reports from different image/runtime inputs cannot be pooled. All required fixture sources and trusted project bytes are included, as are implementation/test/runner/probe hashes. Successful controls need matching assurance and actual expected kernel completion text; negative controls need their own causal diagnostics and ordinary Comparator failure. Syntax errors, unsupported setup, timeouts and cleanup failures cannot count as the intended negative observation.

`infra/run_qualified_lean.py` accepts optional `--runtime-identity`, records its own source and runtime file hashes before execution and rejects changed inputs before marking a run passed. Older callers can omit the option, but such reports cannot satisfy the new qualification matrix. Both execution paths now pass the actual requested mode into positive-result validation. The standalone producer can no longer label a downgraded independent result passed while relying on the offline assessor to reject it later.

`infra/probe_verifier_boundary.py` has a fixed, benign Python probe and no arbitrary command/source input. Its root-scheduled CLI checks nonroot identity, empty capabilities, no-new-privileges, seccomp, denied AF_UNIX/AF_INET sockets, intact/read-only own canaries, root write denial, writable temporary positive controls, exact inspected Docker mounts/configuration and cleanup. It checks the image's driver and six checker binaries. The host script is pinned, mounted read-only and run using the unchanged verifier isolation flags. The output binds image/metadata/runtime/probe/launcher/driver/seccomp identities. Interruption and cleanup failure preserve blocked evidence, including the original failure when cleanup also fails. A root review identified missing process/inspection diagnostics: new failing regressions reproduced the loss, and returned probe exit/output are now checkpointed before validation. Failed or malformed inspections retain kind/exit status and bounded sanitized context; successful inspection environment values remain absent from reports.

The invocation and Python API are documented in `docs/VERIFIER_QUALIFICATION.md`. The fixed probe adds `BoundaryEvidence(report=EvidenceFile(...))` to `assess_qualification`; missing boundary evidence is explicitly incomplete. Even a mechanically satisfied packet has literal `production_qualified=false`, `deployment_approval="pending"`, `scientific_review="not_provided"`, and the complete review gates/coverage gaps. Approval-shaped regression inputs are rejected rather than copied into the packet.

## Authority and isolation audit

The reviewed acceptance path constructs the scientific request from canonical problem/receipt fields, requires its actual approved review, binds target/challenge/candidate/environment identities, rejects independent-assurance downgrade, locks and refreshes the canonical problem row before final identity checks, and commits the receipt/claim atomically. Canonical evidence reuse rechecks current review/source/selector identity. Registry entries accept only exact `ComparatorConfig` routes and have no engineering route. No new module is installed as a verifier or imported as an approval source by those paths.

`LinuxQualification` remains an operator-owned configuration record. This offline packet is not that record and has no conversion/promotion method. Hashes establish consistency, not report authenticity: an internally consistent fabricated report can satisfy a mechanical parser, as the explicitly synthetic unit fixtures demonstrate. An authorized human must independently establish collection provenance and deployment authority. Neither generated JSON flags nor this AI engineering review satisfy that obligation.

The pinned real driver already checks Linux/nonroot, Landlock ABI, seccomp/no-new-privileges, socket denial and all three `io_uring` denials. The new fixed probe checks ordinary properties and the actual Docker configuration separately. It does not establish exhaustive syscall/host containment. Task 3 does not modify launcher or driver source. Root synchronized the newer PR 20 base (470a286), which adds manifest/request/selector guards and acceptance corrections. The matrix includes those exact guard cases. The historical image driver now differs and is correctly rejected for a current scope; only temporary synthetic test metadata is adapted to the copied current source.

## Test-first evidence and independent review

Meaningful failing regressions were observed before fixes for missing fixed-boundary requirements (a packet incorrectly reached satisfied), interruption checkpointing (report stayed running after cleanup), secondary JUnit mutation, input snapshot path traversal, and the independent auditor's version/report consistency findings. Added mutations cover exact scoped pins, source identities, assurance, absent controls, incorrect causal diagnostics, cleanup, duplicate executions, skipped/missing tests, symlinks and post-read changes. The fixed-probe tests use synthetic transports; no host syscall probe, Docker or Lean runs during these tests.

Independent audit: `work/wave01/qualification-audit.md`. It reproduced the permissive Lean version substring, downgraded producer success and contradictory regression approval fields. The implementation now compares the exact Lean banner version token to the lock, validates requested positive kernel evidence in both producer paths, and rejects the contradictory flags. The independent follow-up confirmed that all three original reproductions now fail closed and ran 77 focused tests successfully. It reported no outstanding actionable finding in this scope. The original findings remain recorded rather than rewritten as if they had never occurred.

Latest owner validation command:

```sh
.venv/bin/pytest tests/test_verifier_boundary_probe.py tests/test_verifier_qualification.py \
  tests/test_verification.py tests/test_acceptance_integration.py \
  tests/test_qualification_diagnostics.py tests/test_authority.py \
  tests/test_research_services.py tests/test_acceptance_corrections.py \
  -q --junitxml=.state/checks/wave01-verifier.xml
```

Before the upstream sync, the owner checkpoint was 158 passed and 1 skipped. After synchronization, diagnostic hardening and new exact guard requirements, the latest owner result was **221 passed, 1 skipped in 3.98 seconds**. The skip is the opt-in real PostgreSQL concurrency path; this wave did not schedule a database instance. Earlier historical PostgreSQL evidence is not recounted as a fresh run. Ruff passed for both infra scripts, qualification module and both new test files. `git diff --check` passed. Root owns the final aggregate test run and scoped regression sidecar creation after code freeze.

## Remaining execution and review gates

- Root must run the fixed probe and both modes of both fixed suites against the fresh pinned deployment, retain the measured runtime identity and exact reports, and assemble the offline packet from that scope. This task has started no containers, sessions, tunnels or Linux processes and has no infrastructure to clean up.
- The earlier optional process-exit probe remains blocked/incomplete after a security filter; its initializer failed syntax before execution. It was not retried. No new process-exit candidate, exploit or unsupported probe was added.
- The unchanged driver has a fixed 110-second Comparator deadline and 100,000-byte output bound independent of larger host settings. Root observed a contended library run reaching that deadline and remaining blocked with cleanup. The generic `boundary_unqualified` code is not a mathematical rejection; the limitation remains explicit in the matrix.
- Ordinary fixed probes do not cover all syscall/resource exhaustion/cancellation behavior, current deployment PostgreSQL concurrency, fleet capacity or exhaustive host containment.
- The consolidated fresh source build/recovery evidence and collector provenance require human deployment review. Scientific interpretation and assumptions require separate authorized review. Axiom fields remain an allowed-set upper bound; no minimal dependency closure or scientific correctness is claimed.

Historical core and physics reports remain unchanged and available. They are not silently supplied with new runtime/runner pins or upgraded into fresh deployment evidence.
