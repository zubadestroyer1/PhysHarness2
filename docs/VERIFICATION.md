# Independent verification boundary

**Status: implemented protocol and fail-closed launcher; Linux/kernel qualification is blocked.**
The development Mac has Docker and elan launchers but no running Docker daemon and no configured
Lean toolchain. No candidate in this repository has received a real kernel receipt. The smoke
fixtures have not been compiled or reviewed by a domain expert. Protocol tests use controlled
transports exclusively inside tests and cannot establish kernel correctness or sandbox containment.

## Service interface and trust

`physharness.verification` exports synchronous `Verifier.verify(VerificationRequest) -> VerificationOutcome`,
`UnavailableVerifier`, `ComparatorVerifier`, `ComparatorConfig`, `LinuxQualification`, `driver_digest`, `launcher_digest`, and `seccomp_digest`.
The application constructs requests from immutable stored revisions and recorded expert review.
The public candidate API must not accept caller-controlled target/environment selection, semantic
review flags, qualification records, or verification outcomes as authority. A digest names bytes;
it never establishes mathematical truth. Only a trusted application service should persist an
acceptance receipt after checking the returned status and binding all four digests to the request.

A request includes revision id, canonical `target_digest`, `challenge_sha256`, environment and
candidate SHA256, required `target_theorem`, UTF-8 candidate source, semantic review,
definition-hole flag, and publication flag. `target_digest` identifies the complete canonical
problem metadata; it is never a hash of Lean source alone. `challenge_sha256` hashes the exact
UTF-8 `problem.formal_statement` bytes, including its original line endings. No second
user-entered source-hash field is added to ProblemCreate. Outcomes distinguish `verified`,
`rejected`, and `blocked`; only verified outcomes carry `kernel` or `independent_kernel` assurance.
Every outcome includes remediation, identity digests, checker versions, axioms and diagnostics.
Candidate digest mismatches reject before any process launch. Unreviewed targets and definition
holes block. Definition holes require a newly reviewed concrete target; this adapter cannot approve
fillable definitions.

The queue and VerificationRequest use `MAX_CANDIDATE_CHARACTERS = 2_000_000`: exactly that
many Unicode characters are supported, even when UTF-8 encoding takes more bytes. Submission
of 2,000,001 characters fails with HTTP 422 `CANDIDATE_TOO_LARGE` before a receipt is queued.
Receipts pin source hash, current `review_id`, and selected `target_theorem`. Processing checks
those pins before calling the verifier and again under a lock on the canonical problem row
before committing a receipt/claim. The canonical review must approve that exact target revision.
Legacy oversized receipts become `blocked` with `candidate_too_large`; artifact-read/UTF-8
faults become `blocked` with `candidate_unavailable`. Request construction and checker faults
also persist terminal diagnostics and remediation. An incompatible legacy receipt gets
`verification_receipt_incompatible`; submit a fresh verification. Accepted sharing and canonical
evidence validation require the current review, exact source hash and selected theorem.

`UnavailableVerifier` is the safe deployment default. `ComparatorVerifier()` without config is
also blocked. Config is service-owned and **not an API request**. Its qualification record is an
operator's archived qualification-evidence reference, not a worker claim or an automatic certificate.
There is deliberately no arbitrary checker command, shell template, or worker-receipt transport.
The Docker CLI on the service PATH, daemon, image store and qualification administration belong
to the trusted computing base. Do not expose the Docker socket or service storage to workers.

## Pinned bundle

Configure `ComparatorConfig(bundle_directory=Path(...), manifest_sha256=..., qualification=...)`.
Use an immutable directory administered by the verifier service. The service reads and hashes
files before copying their bytes into a fresh staging directory, never reusing candidate build caches.
Symlinks, path traversal, reserved candidate/build files, oversized files, missing hashes and
revision/digest disagreement fail closed.

The bundle contains these UTF-8 files:

```json
// manifest.json (remove this comment for actual JSON)
{
  "protocol": "physharness-comparator-v2",
  "problem_revision_id": "stored-revision-id",
  "target_digest": "canonical problem metadata digest from the service",
  "challenge_sha256": "SHA256 of exact UTF-8 problem.formal_statement / Challenge.lean bytes",
  "environment_digest": "SHA256 of environment.json bytes",
  "theorem_names": ["reviewed_theorem_name"]
}
```

```json
// environment.json (replace placeholders; remove this comment)
{
  "image": "sha256:<64 lowercase hex digits>",
  "checker_versions": {
    "lean": "exact release and source commit",
    "comparator": "exact source commit",
    "landrun": "exact source commit",
    "lean4export": "exact source commit",
    "nanoda": "exact source commit, if qualified"
  },
  "binaries": {
    "lean": "SHA256", "lake": "SHA256", "comparator": "SHA256",
    "lean4export": "SHA256", "landrun": "SHA256", "nanoda": "SHA256 if publication"
  },
  "files": {
    "lakefile.toml": "SHA256", "lean-toolchain": "SHA256"
  }
}
```

The operator-pinned manifest binds the canonical problem revision, canonical metadata digest,
source hash and environment. `theorem_names` must be exactly `[problem.target_theorem]`; a
bundle selecting another or additional theorem fails closed. Both host and trusted driver check
these bindings, and both compare `Challenge.lean` bytes to `challenge_sha256`.

**Compatibility:** manifests without protocol v2 and distinct source identity are rejected.
Do not reinterpret an old target metadata digest as a source digest. Regenerate and repin trusted
manifests and operator qualification cases from canonical records. This launcher/driver change
invalidates old launcher and driver pins: rebuild the image and repeat deployment qualification
before acceptance use. Updating a hash alone does not qualify a deployment. Existing blocked
qualification records stay blocked, and synthetic transport tests establish no kernel assurance.

`files` must include all project configuration and reviewed dependency sources used by the target.
For larger libraries, install immutable audited dependencies in the pinned image and reference
those fixed paths in the trusted Lake configuration; retain their full source/build manifest with
the qualification report. The image also pins Lean libraries, dynamic libraries and runtime tools.
No network fetch is permitted during checking. `Challenge.lean` is hashed separately and must
use the default prelude, as required by Comparator. Bundle generation is an administrative step;
this repository deliberately ships no invented qualification digests or expert-review records.

`LinuxQualification` requires image digest, SHA256 of the archived qualification report, current
`driver_sha256=driver_digest()`, `launcher_sha256=launcher_digest()`,
`seccomp_sha256=seccomp_digest()`, `linux_boundary="docker-landlock-seccomp-v1"`, and an explicit
`independent_kernel` boolean. Changing the driver, host launcher source, or serialized seccomp policy invalidates prior qualification. The image
must match both the environment and qualification pins. Archive the actual report and its build
inputs before deploying this config; filling in plausible hashes does not qualify anything.

## Fixed runner and upstream protocol

The host only launches Docker. The image entrypoint is fixed to Python running
`/opt/physharness/container_driver.py`. Docker runs with no network, read-only root, all capabilities
dropped, no new privileges, nonroot UID/GID 65532, CPU/memory/PID limits, writable size-limited
`/work` and `/tmp`, and separate read-only `/trusted` and `/candidate` bind mounts. A seccomp policy
denies all `socket` and `socketpair` calls (including AF_UNIX), all three `io_uring` syscalls,
ptrace and several privileged calls. Blocking only socket syscalls is insufficient because
`IORING_OP_SOCKET` can create sockets inside the kernel without those syscalls.
This custom seccomp profile is not a claim of equivalence to Docker's default profile; qualify its
actual attack surface with the image, kernel, runtime and Landrun versions in use.

Inside Linux, the driver checks nonroot status, Landlock ABI >= 3, no-new-privileges, and failed
AF_UNIX/AF_INET socket probes, seccomp filter mode, and explicit EPERM results from
`io_uring_setup`, `io_uring_enter`, and `io_uring_register` probes. Unsupported architectures other than x86_64/aarch64 block.
It verifies the driver, mounted seccomp policy, checker binaries, candidate, target and environment hashes. Mount roots and files receive explicit permissions, independent of the service umask,
while the outer staging directory stays private. Project inputs
are read-only links to trusted mounts. Candidate source is only a link to the separate candidate
mount; the initially empty build workspace prevents tainted cached oleans. Comparator alone
controls elaboration and export under Landrun. The driver does not compile candidates beforehand.

The exact upstream invocation is:

```text
/opt/lean/bin/lake env /opt/verifier/bin/comparator /work/config.json
```

Trusted JSON config fixes `challenge_module=Challenge`, `solution_module=Solution`, reviewed
`theorem_names`, and `permitted_axioms=[propext, Quot.sound, Classical.choice]`. Publication sets
upstream `enable_nanoda=true`. Fixed environment variables `COMPARATOR_LANDRUN`,
`COMPARATOR_LEAN4EXPORT`, and `COMPARATOR_NANODA` name pinned executable paths. The adapter uses
no invented Comparator CLI flags. Image binaries must reside at `/opt/lean/bin/{lean,lake}` and
`/opt/verifier/bin/{comparator,lean4export,landrun,nanoda_bin}`. Python3 must be `/usr/bin/python3`.

Comparator checks statement dependency definitions, allowed transitive axioms, and replays the
exported solution environment in the Lean kernel. This is the basis for acceptance, not stdout
text or a source regex. Every nonzero exit blocks because upstream exit codes do not reliably distinguish failed proof
checking from infrastructure failure. Signal termination has a distinct code and signal diagnostics.
Process failure, unsupported sandbox, malformed response, timeout and output overflow also block.
These results must not be used as negative mathematical evidence. **The `axioms` outcome is the enforced allowed-set
upper bound, not a measured minimal axiom closure.** The diagnostics always label this distinction.
Minimal closure extraction is not implemented; disallowed dependencies are checked by Comparator.

Only the trusted driver emits the `physharness-comparator-v2` JSON response after capturing
Comparator stdout/stderr. Worker output is opaque diagnostics, never parsed as a receipt. Host
validation checks response schema, every digest, pinned versions, axiom policy and publication
replay. Publication requires the separately qualified nanoda binary and successful Comparator
execution with nanoda enabled. Single-kernel acceptance never becomes publication assurance.

Host output is bounded to 256 KB by default, total run time to 120 s. Driver Comparator output is
bounded to 100 KB and time to 110 s. Killing the Docker client does not kill the container, so the
host also removes its uniquely named container in a `finally` block. Automatic Docker `--rm` is
disabled so explicit cleanup has a deterministic result. If removal fails, a successful exact-name
container listing with no entries confirms absence. Otherwise verification is blocked with cleanup
errors, bounded outputs, the container name and the original failure. Successful outcomes also
record cleanup diagnostics. Operators must reconcile lingering containers after daemon recovery.

## Reproduction and qualification

The inspected upstream README and Lean toolchain on 2026-09-14 identify Lean `v4.34.0`.
`formal/lean-toolchain` pins that release for the smoke fixtures. Comparator, lean4export, Landrun
and nanoda **are not yet provisioned or source-commit pinned here**. Thus the formal layer remains
unqualified, even if Python tests pass. Before operating it:

1. Resolve and record exact compatible upstream source commits, toolchain archives and compiler
   hashes on an isolated Linux image builder. Build real Landrun (never `fake-landrun.sh`),
   Comparator, matching lean4export, and publication nanoda. Archive lockfiles and binary hashes.
2. Audit read-only trusted dependency closure and install fixed paths above. Build the final image
   using `formal/Dockerfile` from repository root, supplying a digest-pinned
   `QUALIFIED_TOOLCHAIN_IMAGE`. Record the **final** image digest, `driver_digest()`, `launcher_digest()`, and `seccomp_digest()`.
3. Run live containment probes and adversarial Lean cases through the same Docker flags: target
   overwrite, `.lake` cache manipulation, AF_UNIX/socket and `IORING_OP_SOCKET` escape attempts,
   all io_uring entrypoints, process attacks, forged stdout,
   changed definitions, `sorry`, extra axioms and native-computation trust. Include hangs and
   excessive output. Do not call this profile qualified merely because startup probes pass.
4. For each `formal/smoke/{quantum,classical}` fixture, assemble separate fresh trusted bundles
   with exact canonical `formal_statement` bytes as `Challenge.lean`, the root formal lakefile/toolchain,
   and exactly the reviewed `target_theorem`. Record the canonical metadata digest separately from
   the challenge source hash in each protocol-v2 manifest. Submit
   `Solution.lean` only as candidate bytes. Run kernel and publication checks, independently
   verifying rejection of the attacks. Obtain and record expert semantic review separately.
5. Archive exact commands, images, kernel/runtime versions, positive/negative results and
   independent-kernel compatibility evidence; sign off qualification outside worker authority.
   Only then configure the resulting image/report digests in the service.

The quantum fixture tests bit-flip involution on an abstract two-basis vector. The classical
fixture tests composition of discrete translations. These are tiny algebraic prerequisites,
not novel physics results, full program benchmarks, or expert-reviewed claims.

Primary sources inspected:
[Comparator README](https://github.com/leanprover/comparator/blob/master/README.md),
[upstream toolchain](https://github.com/leanprover/comparator/blob/master/lean-toolchain).
The current README additionally documents an AF_UNIX sandbox issue and a systemd restriction;
this launcher denies every socket syscall instead and still requires deployment qualification.
The README's development fake sandbox is explicitly unsuitable for acceptance.


## Audit hardening and limits

The independent acceptance audit identified an io_uring policy gap, swallowed cleanup errors,
umask-sensitive mounts, and ambiguous checker exits. Regression tests now cover these findings,
including stale host-launcher and seccomp qualification pins. Host policy bytes are hashed separately
from the driver; startup checks verify the mounted policy identity and effective denial probes.
The profile still defaults to allow and remains unqualified: passing these probes alone does not
prove Linux containment. Qualification must record and approve the actual kernel, Docker/runtime,
Landrun, image and policy versions. Runtime upgrades require operational requalification; this
adapter does not automatically authenticate the kernel/runtime identity against the report hash.
