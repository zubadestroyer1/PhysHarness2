# Scoped verifier qualification evidence

This workflow checks engineering evidence for one explicitly pinned Linux deployment and prepares a human review packet. It never grants deployment approval, semantic review, a verification receipt or a claim. Even a packet with `mechanical_status="satisfied"` retains `production_qualified=false`, `deployment_approval="pending"` and its coverage gaps.

The required coverage is in [qualification-matrix.json](../formal/qualification-matrix.json). Its current automatic requirements are:

| Requirement | Evidence required |
| --- | --- |
| Core algebra controls and seven fixed adverse cases | All nine cases in both Lean and independent nanoda modes, against the same image and runtime |
| Physlib/QuantumInfo integration controls | Both library positives and the specific `sorryAx` failure, in both modes |
| Fixed boundary observations | Current pinned probe: denied socket/write operations, process restrictions, intact canaries, writable temporary controls, actual Docker configuration and cleanup |
| Transport and isolation implementation | Named host regressions for fixed container flags, source execution boundary, output/deadline bounds, syscall checks, theorem selection and exact manifest guards |
| Acceptance authority and atomicity | Named host regressions for queued-only submission, semantic review, review replacement, atomic receipt/claim commit, assurance, revoked evidence, candidate-size bounds and reserved-code identity guards |
| Engineering reporting | Named regressions for causal diagnostics and failure/checkpoint preservation |

The new forty-target scientific benchmark has its own review/evaluation workflow. These verifier controls neither establish that benchmark's scientific fidelity nor measure model difficulty.

Qualification requires an explicit trusted, configurable bounded profile file. The repository
default is 8 GiB / 4 CPUs / 600 seconds / one local checker slot. The scope and reports keep
separate hashes for canonical parsed profile content, exact profile-file bytes and shared
resource-policy source. Old qualification pins do
not acquire those identities retroactively and fail closed. Any relevant profile, policy,
embedded image or collector change requires fresh matching evidence.

## Capture before running

Root/operator scheduling owns Linux execution and runtime observation. No command in the qualification module starts Docker, runs Lean, queries a service or writes a review. First capture the actual deployment's image metadata and Linux runtime identity as files in the repository/work directory. The runtime observation includes `purpose="engineering_runtime_observation"`, `production_qualified=false`, `OSType="linux"`, and nonempty `KernelVersion`, `Architecture`, `ServerVersion`, `CgroupVersion` and `DefaultRuntime` fields. Existing Docker observation snapshots use this format.

Use the module directly:

```python
from pathlib import Path
from physharness.verification.qualification import (
    EvidenceFile, SuiteEvidence, RegressionEvidence, BoundaryEvidence,
    capture_scope, assess_qualification, render_review_packet,
)

root = Path.cwd()
scope = capture_scope(
    root,
    image_metadata=EvidenceFile(path=".state/wave01/image-metadata.json", sha256=image_sha),
    runtime_identity=EvidenceFile(path=".state/wave01/runtime-identity.json", sha256=runtime_sha),
)
# Preserve scope.model_dump(mode="json") and scope.sha256 BEFORE scheduled runs.
```

Paths are relative to `root`; traversal, symlinks, duplicate JSON keys and oversized files fail. The scope binds the source lock, executable pins and source revisions, image and runtime observation, current launcher/driver/seccomp, engineering runner, matrix, selected implementation/tests, complete fixture manifests, trusted project files and exact challenge/candidate bytes. Source preparation overlays remain distinguished from original source provenance by the pinned image metadata. The source lock and embedded driver must match current local inputs.

The operator schedules the existing engineering runner with the observed runtime file:

```console
.venv/bin/python infra/run_qualified_lean.py \
  --engineering-image-metadata .state/wave01/image-metadata.json \
  --runtime-identity .state/wave01/runtime-identity.json \
  --fixtures formal/adversarial/cases.json \
  --output .state/wave01/core-kernel.json
```

Schedule the independent mode with `--publication`, and both modes for `formal/library-cases.json`. Here `--publication` requests independent kernel replay; it grants no publication or review authority. Runtime identity remains a separately collected operator observation; passing a JSON file does not authenticate that observation. The runner records its own source hash and the runtime file hash before execution, then rechecks runner/runtime/metadata/fixture/project/source inputs before marking a run passed. The runtime flag is optional for old callers; reports without it cannot satisfy this matrix.

Each supplied report must match its entire fixture manifest and current source identities. All cases must appear once, include their expected outcome and causal markers, match the mode's assurance and checker versions, and provide a corresponding ordinary Comparator exit. Positive controls need the expected Lean/nanoda completion diagnostics; negative cases need their specific failure diagnostics. A timeout, unrelated syntax error, malformed response or preflight failure cannot count as the intended negative result. Diagnostics improve fixed-fixture reporting and remain untrusted text.

Exit 137 is likewise insufficient to classify an OOM. Assessment requires an increased cgroup
OOM counter or typed Docker `OOMKilled: true` state. Without that positive evidence, a negative
exit stays blocked with an uncertain cause. Missing required cgroup observations cannot satisfy
engineering qualification, but missing optional Docker state does not by itself invalidate an
otherwise successful kernel result. Resource failures do not satisfy a false-theorem rejection.
The one-slot file lock
serializes only contenders with the same service UID and lock path, through cleanup; fleet and
VM-wide admission remain operator responsibilities.

Cleanup requires a uniquely named checker container and either successful removal of that exact name or a successful authoritative empty listing. Duplicate run IDs, reused containers and duplicate suite modes are invalid. A report from another image or runtime cannot fill a missing requirement.

## Fixed boundary observations

Schedule this fixed probe only after the image is ready, using the same dedicated Docker runtime and shared temporary directory as the real checker:

```console
.venv/bin/python infra/probe_verifier_boundary.py \
  --image-metadata .state/wave01/image-metadata.json \
  --image-metadata-sha256 ACTUAL_METADATA_SHA256 \
  --runtime-identity .state/wave01/runtime-identity.json \
  --runtime-identity-sha256 ACTUAL_RUNTIME_SHA256 \
  --output .state/wave01/fixed-boundary.json
```

The uppercase values are placeholders for actual file hashes. This script accepts no arbitrary command, Lean source or candidate. Its fixed Python probe runs inside the image with the checker's unchanged Docker isolation flags and only its own temporary canaries mounted. It records:

- UID/GID 65532, all capability sets empty, no-new-privileges and seccomp filter mode.
- `AF_UNIX` and `AF_INET` socket creation denied with permission errno, plus no Docker/Podman socket at the fixed conventional locations.
- Unchanged trusted/candidate canary bytes and denied writes to those mounts and the root filesystem. Missing-file or unsupported-operation errors do not count as permission denial.
- Successful create/read/delete controls in both `/work` and `/tmp`, preventing a generally broken filesystem from appearing to prove containment.
- Actual Docker inspection with read-only root/binds, only the two intended bind sources, no extra credential/socket mounts, no forwarded host environment, no credential-like image environment keys, nonprivileged namespaces, dropped capabilities, seccomp/no-new-privileges, and the exact PID/CPU/memory/tmpfs configuration.
- The embedded driver and all six checker binary hashes, followed by explicit removal or authoritative absence of its uniquely named container.

The report binds the current probe source, launcher, driver, seccomp, image metadata and runtime observation. The runtime file is still a separately collected observation whose origin must be established by the operator. Interruption, bad inner provenance, inspection mismatch, failed controls or cleanup failure leave a blocked report. The returned probe exit code and bounded output are checkpointed before exit/JSON validation, including failures. Failed or malformed inspections retain kind, exit code and a sanitized diagnostic capped at 4,096 characters; successful inspection environment values are not copied into reports. The script's bounded launch and inspection operations use the existing process/cleanup transport; it does not change that transport or the container driver.

The real Comparator driver independently requires Linux/nonroot, Landlock ABI support, seccomp/no-new-privileges, denied socket creation and all three denied `io_uring` operations before checking a candidate. The fixed Python probe supplies separate ordinary observations and verifies actual Docker configuration; it is not a comprehensive Landlock or kernel attack suite. The matrix requires both the fixed probe and real positive/causal-negative Comparator runs, against the same deployment inputs.

## Host regression evidence

Run the named test files in the matrix using the captured code/input snapshot and preserve JUnit output. Record the actual command and exit status in a separate JSON file:

```json
{
  "protocol": "physharness-regression-evidence-v1",
  "purpose": "engineering_regression",
  "production_qualified": false,
  "scope_sha256": "<captured scope SHA-256>",
  "exit_code": 0,
  "command": [".venv/bin/pytest", "...actual selected test files...", "--junitxml=.state/wave01/regressions.xml"],
  "junit": {"path": ".state/wave01/regressions.xml", "sha256": "<actual JUnit SHA-256>"}
}
```

The placeholders above are documentation, not valid evidence. Missing, failed or skipped required tests do not satisfy a group. Parameterized manifest/authority guards are selected by exact case IDs; a different parameter does not substitute for a required case. XML entity/document-type input and duplicate test identities are rejected. JUnit and its containing report are rechecked after assessment. The module validates the submitted record; an authorized reviewer must still establish that the command actually produced that JUnit file. Synthetic transport tests are never relabeled real Linux attack observations.

## Prepare the operator packet

```python
packet = assess_qualification(
    root, scope=scope,
    evidence=[
        SuiteEvidence(suite_id="core", report=core_kernel_ref),
        SuiteEvidence(suite_id="core", report=core_independent_ref),
        SuiteEvidence(suite_id="library", report=library_kernel_ref),
        SuiteEvidence(suite_id="library", report=library_independent_ref),
    ],
    regressions=RegressionEvidence(report=regression_report_ref),
    boundary=BoundaryEvidence(report=boundary_report_ref),
)
packet_json = packet.model_dump(mode="json")
packet_markdown = render_review_packet(packet)
```

Each `*_ref` is an `EvidenceFile` containing the actual file path and hash. Assessment checks current input hashes before and after reading observations. Its result is `invalid` for mismatches, `incomplete` for missing requirements or `satisfied` for matching automatic requirements. Human deployment approval is a separate authority decision, with its own record and deployment configuration. This packet is not a `LinuxQualification`, cannot be used as a verifier and has no automatic promotion route. Scientific target approval remains independently required by the acceptance service.

## Explicit limits and review gates

- The previous optional process-exit probe remains blocked/incomplete after a security filter. Its initializer encountered a syntax failure before execution. It must not be retried in this task, and no report hides or counts that coverage gap as passed.
- The current profile gives Comparator 600 seconds and caps its output at 256,000 bytes. Earlier Wave 1 evidence used the historical 2 GiB profile and remains evidence only for those recorded hashes. No `work/wave01/evidence-8g` run exists yet; the current-image benchmark, fixed probe and complete qualification packet remain pending.
- Fixed cases, ordinary boundary observations and host regressions do not establish exhaustive host containment, all Landlock/seccomp syscalls, real cgroup exhaustion, database concurrency for the current deployment, or fleet capacity.
- Review the consolidated source build and recovery in a fresh environment separately. Historical layered recovery evidence cannot prove a later consolidated recipe was rebuilt. The source/image/runtime and evidence collector are part of the human review boundary.
- The axiom field remains the allowed-set upper bound; this workflow does not invent a minimal dependency closure or semantic correctness assessment.

Archived evidence from before runtime/runner binding remains available as historical evidence. It is not silently upgraded, combined across different images or assigned fresh provenance by this module.
