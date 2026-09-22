# Independent verification boundary

The real Linux engineering suite passed on 2026-09-15: two algebraic fixtures passed Lean replay and seven adversarial fixtures were blocked, in both single-kernel and independent nanoda modes. The complete outputs, executable pins, runtime observation and hashes are archived in [acceptance evidence](../work/acceptance-evidence/index.json). No expert scientific review or production sandbox qualification is claimed by these results. The application defaults to `UnavailableVerifier` until an operator supplies an independently approved deployment configuration.

## Scientific acceptance and engineering observations

`ComparatorVerifier.verify(VerificationRequest)` is the scientific acceptance interface. Its service-owned `ComparatorConfig` requires a `LinuxQualification` record. The service constructs requests from stored problem, review and artifact records; public clients cannot supply authoritative checker outcomes or semantic-review flags.

A scientific request binds:

- `problem_revision_id`: immutable scientific revision identifier.
- `target_digest`: canonical digest of the complete problem metadata, including assumptions, source text, environment and selected theorem.
- `target_theorem`: exactly the selected theorem in the reviewed problem. The bundle must select `[target_theorem]`.
- `challenge_sha256`: SHA-256 of the exact UTF-8 `formal_statement`, which becomes `Challenge.lean` without newline normalization.
- `environment_digest`: SHA-256 of the exact `environment.json` bytes.
- `candidate_sha256`: SHA-256 of the submitted UTF-8 candidate artifact.

The submission receipt also captures `review_id`. The acceptance worker checks the original review, all identities, source digest, definition-hole flag and publication requirement before calling the checker. A replacement review or changed source/environment blocks the queued check. It rechecks revision identity before atomically persisting the receipt and creating its claim. Artifact-read failure, checker identity mismatch and publication assurance downgrade retain distinct blocked codes. Failed persistence rolls back both claim and receipt; retries cannot create duplicate claims.

Unreviewed target meaning and definition holes block acceptance. A trusted `Challenge.lean` may have theorem proof holes for the candidate to fill; this is distinct from unreviewed definitions. Only the allowed theorem declaration selected by the reviewed problem is checked. Changing theorem selection requires a new reviewed scientific revision.

`EngineeringVerifier.run(EngineeringRequest)` is a separate interface. Its `EngineeringConfig` has `ExecutionPins`, but no qualification-report hash. Engineering requests cannot contain semantic-review fields. Results are wrapped as `EngineeringResult(purpose="engineering_smoke", outcome=...)`. This object is not a `VerificationOutcome`, and the engineering verifier has no `verify` method that the acceptance service can call. Its nested outcome records observed kernel behavior; it does not create or approve a scientific target, review, receipt or claim.

`ComparatorVerifier.preflight(request)` checks review and bundle pins without launching a candidate. A structurally configured deployment returns `blocked/configured_unprobed` with no assurance. Missing independent-kernel configuration blocks publication preflight. Preflight never qualifies the runtime or verifies a proof.

## Preparing trusted bundles

`create_bundle` writes an exclusive new directory from service-controlled bytes and returns the manifest SHA-256 to pin in configuration. It rejects reserved/traversing paths, missing project configuration and missing executable pins; it never constructs a review or executes Lean.

```python
from pathlib import Path
from physharness.verification import create_bundle

manifest_sha256 = create_bundle(
    Path("/srv/verifier/bundles/new-revision"),
    problem_revision_id=problem["id"],
    target_digest=problem["target_digest"],
    challenge_source=problem["formal_statement"],
    theorem_names=[problem["target_theorem"]],
    image_digest=image_metadata["image"],
    checker_versions=image_metadata["checker_versions"],
    binaries=image_metadata["binaries"],
    project_files={
        "lakefile.toml": trusted_lakefile_bytes,
        "lean-toolchain": trusted_toolchain_bytes,
    },
)
```

A v2 manifest has this schema:

```json
{
  "protocol": "physharness-comparator-v2",
  "problem_revision_id": "stored-revision-id",
  "target_digest": "canonical scientific revision SHA-256",
  "challenge_sha256": "Challenge.lean byte SHA-256",
  "environment_digest": "environment.json byte SHA-256",
  "theorem_names": ["ReviewedNamespace.target"]
}
```

`environment.json` pins an immutable Docker image ID, checker version/source identities, every trusted project file and the executable hashes for `lean`, `lake`, `comparator`, `lean4export`, `landrun`, and `nanoda` for publication. Its `files` map is computed by the bundle builder. Dependencies must already be built in read-only paths of the pinned image and referenced by the trusted Lake configuration and manifest. The full dependency/build closure belongs in the image's archived build records. Checking has no network access and cannot fetch dependencies.

Configure `ComparatorConfig(bundle_directory=Path(...), manifest_sha256=..., qualification=...)`. `LinuxQualification` binds image digest, archived qualification-report SHA-256, current `driver_digest()`, `launcher_digest()`, `seccomp_digest()`, `linux_boundary="docker-landlock-seccomp-v1"` and the explicit independent-kernel capability. These are operator-managed evidence references, not certificates minted by this code. Runtime upgrades require operational requalification.

The operator-pinned manifest binds the canonical problem revision, canonical metadata digest,
source hash and environment. `theorem_names` must be exactly `[problem.target_theorem]`; a
bundle selecting another or additional theorem fails closed. Both host and trusted driver check
these bindings, and both compare `Challenge.lean` bytes to `challenge_sha256`. The shared driver
requires theorem equality for trusted scientific requests (which always contain
`semantic_reviewed`); engineering requests omit review fields but retain every common
protocol/revision/metadata/source/environment check. Checker diagnostic codes cannot disable
the service's final locked review/source identity check.

**Migration:** v1 conflated canonical scientific revision identity with Lean source bytes. It cannot represent the current contract. Regenerate bundles from stored revisions with the explicit v2 protocol and `challenge_sha256`; do not relabel old digests. Old manifests and responses fail closed. Submit fresh verification receipts for revisions whose receipts predate source/review binding. Legacy CI case requests must now be engineering requests with no semantic-review fields and explicit expected codes.

## Actual execution and checker protocol

The host launches only the service-owned Docker CLI. Candidate execution happens in the Linux image at the fixed entrypoint `/usr/bin/python3 /opt/physharness/container_driver.py`. Docker applies no network, read-only root, nonroot UID/GID 65532, dropped capabilities, no-new-privileges, bounded CPU/memory/PIDs, size-limited `/work` and `/tmp`, and distinct read-only trusted/candidate mounts. Docker itself and its socket, service PATH, trusted storage and image store remain part of the trusted computing base.

The seccomp policy denies `socket`, `socketpair`, all three `io_uring` syscalls, ptrace and specified privileged syscalls. The driver probes Linux architecture, nonroot status, Landlock ABI >= 3, no-new-privileges, seccomp filtering, denied AF_UNIX/AF_INET sockets, and explicit `EPERM` from `io_uring_setup`, `io_uring_enter` and `io_uring_register`. It checks its own bytes, seccomp policy, executables and mounted inputs against the pins. Fresh build directories avoid candidate-supplied caches. Explicit file and directory modes work even when the service has a private umask.

The pinned Comparator `3927ad383f208ae977c340a91c48ac9b497d2097` runs with this upstream-supported invocation:

```text
/opt/lean/bin/lake env /opt/verifier/bin/comparator /work/config.json
```

The JSON configuration contains `challenge_module=Challenge`, `solution_module=Solution`, trusted `theorem_names`, `permitted_axioms=[propext, Quot.sound, Classical.choice]`, and `enable_nanoda` for publication. `COMPARATOR_LANDRUN`, `COMPARATOR_LEAN4EXPORT` and `COMPARATOR_NANODA` point to the pinned executables. No invented CLI flags or fake Landrun wrapper is used. Comparator itself uses real Landrun with its upstream `--best-effort` behavior; the outer Docker/seccomp boundary is essential, and still needs full production containment review.

Comparator builds and exports the trusted challenge first, then builds and exports the candidate under Landrun. It compares the selected theorem type and its dependency definitions, requires theorem declaration kind, checks the transitive axiom closure and replays the exported environment into a fresh Lean kernel. Publication also replays through nanoda. Allowed axioms are enforced by the checker. The receipt's `axioms` list is the allowed-set upper bound, explicitly labeled `axioms_are_policy_upper_bound`; minimal axiom-closure extraction is not implemented.

Only exit zero establishes checker success. Upstream returns the same nonzero exit for mathematical checking failures and infrastructure/build errors. The adapter therefore records these as `blocked/comparator_failed`, never as negative mathematical evidence; signals have a separate `comparator_terminated` code. Candidate byte mismatch can be `rejected`, but is not a theorem refutation.

Candidate and Comparator stdout/stderr are captured as opaque diagnostics. The host accepts only the trusted driver's single v2 response, validating schema, source/revision/environment/candidate identity, checker provenance, axiom policy and assurance. A candidate's forged JSON was exercised in the real suite and did not become a receipt.

Timeout and output bounds apply at host and driver. The host explicitly removes each uniquely named container in `finally`; success requires confirmed removal or an authoritative empty exact-name listing. Unconfirmed cleanup blocks acceptance and preserves the original failure and container name. The archived final suites confirmed 18 explicit removals. Report checkpoints use atomic replacement, file fsync and directory fsync. A checkpoint failure ends the run as blocked when storage is writable; an unwritable report destination raises rather than announcing success.

## Reproducing engineering evidence

Build the real toolchain using the pinned [formal environment](../formal/README.md), then extract its image metadata. The engineering runner uses that metadata directly, avoiding a circular requirement for a qualification report before generating any evidence:

```sh
export DOCKER_HOST=unix:///private/tmp/physharness-colima/default/docker.sock
export TMPDIR="$PWD/.state/tmp"
mkdir -p "$TMPDIR"
.venv/bin/python infra/run_qualified_lean.py \
  --engineering-image-metadata .state/formal/image-metadata.json \
  --output .state/formal/engineering-kernel-report.json
.venv/bin/python infra/run_qualified_lean.py \
  --engineering-image-metadata .state/formal/image-metadata.json \
  --output .state/formal/engineering-independent-report.json --publication
```

Use a service-controlled local Docker endpoint and a shared bind-mount directory appropriate to the runner. The documented endpoint is the dedicated development Colima VM, not a production deployment. The host may be macOS; candidate execution and the boundary probes still run only in Linux. The legacy qualification-environment mode deliberately requires a Linux CI host.

The default fixture manifest is [formal/adversarial/cases.json](../formal/adversarial/cases.json). `--fixtures` selects another versioned engineering suite. A suite must contain an actual `verified/kernel_checked` positive and a `blocked/comparator_failed` attack. Exact status, code and comparator exit evidence must match; missing Docker, preflight rejection, timeout or a malformed response cannot count as a passed attack. Every negative case must also specify `required_diagnostic_substrings`: a nonempty list whose entries must all appear in the recorded Comparator output. For example, the `sorry` fixture requires the complete `Illegal axiom detected: 'sorryAx'` diagnostic; a generic syntax error or challenge warning cannot satisfy it. Expected markers are copied into each new report. These checks improve fixed-fixture reporting; diagnostic text remains untrusted and grants no scientific acceptance authority. Every report retains `expert_review=not_provided` and `production_qualified=false`, including reports with `status=passed`.

An [offline diagnostic audit](../work/acceptance-evidence/offline-diagnostic-audit.json) applied these stricter expectations to all 18 archived core results and checked their exact source/candidate hashes. It executed no new candidates. A separate optional initializer probe remains blocked/incomplete: its syntax failure does not satisfy the initializer execution marker. The original reports and their hashes remain unchanged.

The archived core run used Linux 6.8.0-117 on aarch64, Docker 29.5.2, Lean 4.33.0, the pinned Comparator/exporter, real Landrun and nanoda. It verified translation composition and bit-flip involution, and blocked `sorry`, an extra transitive axiom, forged stdout, target/config writes, changed definitions and `native_decide`'s extra axiom. These are algebraic prerequisites and engineering attacks, not novel physics results or exhaustive sandbox qualification. Genuine Physlib/QuantumInfo import checks use the separately provisioned library image and its own recorded evidence.

Source protocol and closure checks were inspected directly at the pinned commits:
[Comparator main](https://github.com/leanprover/comparator/blob/3927ad383f208ae977c340a91c48ac9b497d2097/Main.lean),
[axiom closure](https://github.com/leanprover/comparator/blob/3927ad383f208ae977c340a91c48ac9b497d2097/Comparator/Axioms.lean),
[Comparator trust assumptions](https://github.com/leanprover/comparator/blob/3927ad383f208ae977c340a91c48ac9b497d2097/README.md).

## Multiple target bundles

Set `PHYSHARNESS_VERIFICATION_REGISTRY` to an operator-owned JSON file to route several reviewed revisions through one acceptance service. It is mutually exclusive with the existing `PHYSHARNESS_VERIFICATION_BUNDLE`, `PHYSHARNESS_VERIFICATION_MANIFEST_SHA256` and `PHYSHARNESS_VERIFICATION_QUALIFICATION` settings. The existing single-bundle configuration remains supported.

A registry has `protocol="physharness-verifier-registry-v1"` and an `entries` array. Each entry contains a unique `problem_revision_id` and a complete `ComparatorConfig` JSON object with an absolute `bundle_directory`, `manifest_sha256` and `qualification`. For example, build the file from already approved configurations:

```python
registry = {
    "protocol": "physharness-verifier-registry-v1",
    "entries": [
        {"problem_revision_id": lemma_problem["id"],
         "config": lemma_config.model_dump(mode="json")},
        {"problem_revision_id": next_problem["id"],
         "config": next_config.model_dump(mode="json")},
    ],
}
```

`VerifierRegistry.from_file(path)` validates every manifest/revision, source, environment, project file, image and qualification code pin at startup without executing a candidate. Duplicate revisions, unsupported engineering configurations and invalid pins fail startup. Each verification still revalidates its selected bundle. An unknown revision returns `blocked/verifier_revision_unconfigured`; there is no first-entry or single-bundle fallback. The router accepts only scientific verification requests.

Several targets can share identical `environment.json` bytes while having distinct canonical metadata digests, source digests and selected theorems. The source, revision identity and theorem selection live in each target's manifest. The same accepted lemma may therefore be referenced when composing a proof for another target without changing the pinned toolchain environment. The new proof still requires full independent replay and its own exact reviewed target.

Administrative helpers support preparation before expert review:

```python
environment_bytes = prepare_environment(
    image_metadata_path,
    image_metadata_sha256=recorded_metadata_sha256,
    project_directory=trusted_project_directory,
    project_files=["lakefile.toml", "lean-toolchain"],
)
manifest_sha256 = create_problem_bundle(
    new_bundle_directory,
    problem=canonical_problem_record,
    environment_bytes=environment_bytes,
    project_directory=trusted_project_directory,
)
```

Both functions are exported by `physharness.verification`. Environment preparation bounds and hashes the metadata and project files, rejects symlinks/reserved paths and emits canonical bytes. Bundle preparation checks the stored `ProblemCreate` digest, exact environment digest, selected theorem, source and copied project files before and after creation. The canonical problem's environment digest must already match those bytes. These helpers create no review, qualification record, receipt or claim; a pending target remains pending.

The final acceptance commit locks and refreshes the canonical problem row with `SELECT FOR UPDATE` on PostgreSQL before comparing its review and identity. This serializes concurrent review updates with the receipt/claim commit. A real two-transaction PostgreSQL regression reproduced the previous race and passed after the fix; SQLite alone cannot exercise that race because it serializes writes globally.


## PR correction compatibility

Scientific submission and request validation share a 2,000,000-character candidate limit; larger
submissions fail before queueing. Persisted oversized candidates, unavailable candidate bytes and
incompatible legacy receipts receive explicit blocked diagnostics. Scientific receipts bind the
current review, exact UTF-8 source hash and selected theorem, including during evidence reuse.
Engineering requests remain separate and do not acquire a manufactured semantic review.

The combined PR corrections change host/driver bytes. Earlier recorded engineering results remain
evidence for their recorded image and code hashes; they do not validate this combined source.
Rebuild and rerun genuine engineering/qualification checks before supplying new deployment pins.
