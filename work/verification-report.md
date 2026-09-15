# Verification subsystem implementation report

## Delivered interfaces and files

Owned implementation is confined to `src/physharness/verification/`, `tests/test_verification.py`,
`formal/`, and `docs/VERIFICATION.md`, plus this requested report. No commits, new dependencies,
core/API edits, or subagents were used.

Public imports from `physharness.verification`:

- `VerificationRequest`, `VerificationOutcome`: frozen strict Pydantic contracts with forbidden
  extra fields, SHA256 validation and assurance/status consistency checks.
- `Verifier`: synchronous `verify(request) -> VerificationOutcome` protocol.
- `UnavailableVerifier()`: safe default; explicit blocked result and remediation.
- `ComparatorVerifier(config: ComparatorConfig | None = None)`: independently configured service.
- `ComparatorConfig(bundle_directory: Path, manifest_sha256: str, qualification:
  LinuxQualification, timeout_seconds=120, output_limit_bytes=256000)`.
- `LinuxQualification(image_digest, qualification_report_sha256, driver_sha256,
  launcher_sha256, seccomp_sha256, linux_boundary="docker-landlock-seccomp-v1", independent_kernel=False)`.
- `driver_digest()`, `launcher_digest()`, `seccomp_digest()`: hash the exact trusted driver,
  host launcher source, and canonical seccomp profile for qualification binding.

Requests match the parent brief exactly. Configuration, review flags, target/environment selection,
and qualification references must come from trusted services, never candidate public payloads.
Parent can inject `UnavailableVerifier` immediately without external infrastructure. Actual
Comparator usage requires a per-revision trusted pinned bundle; its schema and creation obligations
are documented in `docs/VERIFICATION.md`.

## Trust boundary

Candidate source bytes are hashed before execution. Immutable service-owned manifest pins bind
revision, target, environment, theorem names, trusted project sources, exact image and checker
binaries. Bundle validation rejects missing or altered files and symlinks. Fresh byte copies avoid
re-reading the original files after validation.

No arbitrary shell/checker command or worker receipt is configurable. The fixed Docker launcher
uses an independently administered local image with a content digest and no pull. The fixed Python
driver validates Linux/nonroot/Landlock/socket/no-new-privileges prerequisites and checker hashes,
then invokes actual upstream `lake env comparator config.json`. Candidate elaboration/export is
performed by Comparator under real Landrun, with read-only trusted/candidate mounts and fresh
build directories. All candidate and Comparator stdout is captured as diagnostics; only the
trusted driver creates the protocol response after the checker exits. Host parsing enforces schema,
identity, version and assurance correspondence.

Comparator is responsible for exact referenced definitions/statements, transitive axiom policy and
real kernel replay. Allowed axioms are exactly `propext`, `Quot.sound`, `Classical.choice`.
Publication requests require qualification for nanoda and successful upstream `enable_nanoda` replay.
Definition holes always block pending a new reviewed concrete target. Reported `axioms` is explicitly
the enforced policy upper bound, not the candidate's measured minimal axiom closure.

The Docker CLI, daemon, pinned image, kernel, Landrun and qualification administration remain trusted.
A qualification record is an operator-owned archived evidence reference; the presence of a string
hash does not establish that qualification actually occurred. No such production record is shipped.

## Test-first evidence and verification

1. Before implementation, `.venv/bin/python -m pytest tests/test_verification.py -q` produced
   **21 failed**. Each failed the explicit assertion that `ComparatorVerifier` was not implemented.
2. Initial implementation produced **21 passed** after the fixed driver was added.
3. Additional hardening tests then produced **2 failed, 23 passed**: missing binary pins were not
   rejected by bundle validation, and arbitrary launcher configuration remained possible.
4. Added mandatory binary hashes and removed arbitrary launcher configuration.
5. Final command `.venv/bin/python -m pytest tests/test_verification*.py` produced
   **25 passed in 1.16 seconds** under Python 3.12.13 / pytest 9.1.1 on Darwin.
6. `.venv/bin/ruff check src/physharness/verification tests/test_verification.py` passed.

Coverage includes forged candidate hashes; semantic review and definition holes; missing verifier;
trusted file and revision mismatch; symlink inputs; fake extra/sorry axioms; malformed/mismatched
status, versions and digests; missing publication replay; incomplete proof rejection through a
controlled checker; generated source attempting a host write; absent launcher; required binary
pins; subprocess timeout and output bounds; Docker containment flags and cleanup; and rejection
of configurable arbitrary launcher paths.

Synthetic successful and unsuccessful checker results exist **only in tests**, via monkeypatching
private transport. They validate application protocol handling, not mathematical truth. The host-write
attack test confirms no source is executed when the launcher is unavailable. It does not establish
live Linux escape resistance. The incomplete-proof/extra-axiom tests are controlled transport tests,
not actual Lean rejection evidence. No kernel, sandbox or science qualification is inferred from them.

## Installed environment and upstream evidence

Non-destructive probes found:

- Docker CLI `/opt/homebrew/bin/docker` exists; `docker info` failed because
  `/var/run/docker.sock` was absent.
- Lean/lake elan launchers exist; `lean --version` failed because no default toolchain is configured.
- Network git source lookup could not resolve github.com in the shell sandbox. Primary upstream
  README and lean-toolchain were inspected with the browser tool instead.
- No dependency installation, generated Lean compilation on Mac, live container run, expert review,
  or fabrication of source/image qualification pins occurred.

Inspected primary upstream sources:
https://github.com/leanprover/comparator/blob/master/README.md
https://github.com/leanprover/comparator/blob/master/lean-toolchain

The README establishes JSON keys, fixed invocation, `COMPARATOR_*` executable variables,
`enable_nanoda`, statement/axiom/kernel behavior, definition-hole limitations, and an AF_UNIX
sandbox issue. Toolchain content was `leanprover/lean4:v4.34.0`. The launcher denies all socket
creation and requires an explicitly qualified Linux boundary. It never uses development
`fake-landrun.sh`.

## Remaining qualification and deployment obligations

- Actual Comparator/Landrun/lean4export/nanoda installation and compatible source commit pins remain
  missing. `formal/Dockerfile` supplies the trusted final driver layer on a separately audited base;
  it does not pretend to build an absent complete toolchain.
- Real Linux attack corpus, accepted smoke proofs, independent-kernel results and full containment
  qualification must run before enabling configured production verification.
- `formal/smoke/quantum` and `formal/smoke/classical` provide honest tiny algebraic smoke fixtures.
  Both are uncompiled and unreviewed. `formal/qualification.json` records the blocked status.
- The custom seccomp deny list is not Docker's complete default profile. Qualify the actual
  profile with runtime/kernel/image versions and adversarial generated Lean.
- The environment supports immutable dependencies provisioned inside the image or hashed project
  sources. Network dependency retrieval during proof checks is forbidden.
- Minimal per-proof axiom closure reporting is not implemented; Comparator enforces closure is
  within the reported policy upper bound.
- If the Docker daemon becomes unreachable, cleanup can fail after the client is killed. Unconfirmed cleanup blocks
  acceptance with container identity and prior-error diagnostics; operators must reconcile lingering
  named containers after recovery.
- Expert semantic review and scientific claim/novelty review remain outside kernel acceptance.

No proof has been falsely promoted to verified in this implementation session.


## Independent acceptance audit corrections

The independent audit (`work/acceptance-audit.md`) identified a P1 io_uring socket-policy gap and
P2 cleanup, restrictive-umask, and checker-exit issues, plus incomplete qualification binding.
All implementation findings were addressed in the same owned files:

- Seccomp now explicitly denies `io_uring_setup`, `io_uring_enter`, `io_uring_register` with EPERM,
  alongside socket/socketpair. Driver startup probes all three on supported x86_64/aarch64 Linux,
  requires seccomp filter mode, and hashes the mounted policy. This closes the identified policy
  omission at the code level; real `IORING_OP_SOCKET` and containment probes remain unrun.
- `LinuxQualification` additionally requires `launcher_sha256` and `seccomp_sha256`. Stale host
  launcher source or policy bytes block before Docker runs. Helper functions compute these pins.
  The record remains operator-owned evidence, not a claim accepted from workers. Actual kernel/
  runtime identity is an operational qualification obligation, not automatically authenticated.
- Host mount roots, nested directories and every input file get explicit final modes, independent
  of umask. The outer staging directory remains private. A regression runs under umask 0077.
- Automatic `--rm` was removed. Explicit cleanup must succeed, or an authoritative successful
  exact-name container listing must confirm absence. Otherwise the outcome is blocked and retains
  container name, bounded cleanup output, absence-check errors and the original execution failure.
  Successful outcomes also contain cleanup diagnostics. Both timeout and nonzero cleanup are tested.
- Every nonzero Comparator exit now blocks. Negative signal returns and conventional 128+signal
  returns have a distinct termination code and signal diagnostics. Positive exits are ambiguous
  between proof-check failure and infrastructure failure; stdout is not used to infer a phase.
  These outcomes are never negative mathematical evidence. Direct candidate digest and explicitly
  reported disallowed-axiom rejections remain separate.

Test-first follow-up evidence: the new audit regressions produced **12 failed, 25 passed** before
fixes. Additional confirmed-absence tests produced **2 failed, 39 passed** before absence handling
was implemented. The final scoped run produced **41 passed in 1.18 seconds**, and scoped Ruff passed.
All controlled transports and syscall stubs remain exclusively in tests. No Linux exploit, Lean
compilation, independent-kernel acceptance, or expert review was performed. Real qualification
status remains blocked in `formal/qualification.json`.
