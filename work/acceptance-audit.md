# Independent proof-acceptance audit

**Historical initial findings.** The code corrections and regression evidence are recorded in
[the acceptance implementation follow-up](verification-report.md#independent-acceptance-audit-corrections).
The descriptions below preserve the original reproductions; they are not a list of still-open
code defects. Real Linux/kernel qualification remains outstanding. The follow-up reports code
and controlled-test fixes, not a completed containment qualification.

Audited 2026-09-14. Scope: `src/physharness/verification/`, `formal/`,
`tests/test_verification.py`, `docs/VERIFICATION.md`, and `work/verification-report.md`.
This audit did not edit implementation, compile generated Lean, run a Linux container,
or review the application/API integration.

The default unavailable verifier fails closed. I found **one P1 containment defect and
three P2 operational correctness defects** in the configured path. I did not demonstrate
a forged proof receipt or a kernel escape. The existing documentation correctly says
that Linux containment, real proof acceptance, independent-kernel compatibility, and
expert review remain unqualified; Python test success must not change those statuses.

## Findings

### P1 — The socket restriction can be bypassed through io_uring

**Location:** `src/physharness/verification/boundary.py:425-442`;
startup probes at `src/physharness/verification/container_driver.py:48-56`.

The seccomp profile defaults to `SCMP_ACT_ALLOW`, denies `socket` and `socketpair`,
and allows `io_uring_setup`, `io_uring_enter`, and `io_uring_register`. On a Linux
deployment that enables unprivileged io_uring, candidate native code can submit
`IORING_OP_SOCKET` to create an AF_UNIX socket without issuing the denied `socket`
syscall. Linux implements this by calling `__sys_socket_file` internally from
`io_socket`. The ordinary Python socket probes still fail as expected, so they do
not detect this path. See the primary [Linux io_uring networking implementation](https://raw.githubusercontent.com/torvalds/linux/master/io_uring/net.c).

This breaks the advertised all-socket restriction used as the AF_UNIX workaround.
`--network=none` does not remove AF_UNIX operations inside the container. The minimum
Landlock ABI accepted by this driver also predates its newer IPC controls. This is
a concrete policy hole, not a demonstrated full sandbox escape or proof forgery.
Another deployment-wide restriction might block io_uring, but this launcher neither
requires nor checks one.

**Fix:** deny all three io_uring syscalls, or use a qualified default-deny seccomp
policy with the required socket restrictions. Extend the boundary startup/qualification
probes to cover io_uring. Requalify the resulting complete policy.

**Evidence:** captured the actual generated seccomp JSON through a controlled Docker
transport; its default was `SCMP_ACT_ALLOW` and all three io_uring syscalls were absent
from the deny list. This inspection ran on Darwin; live exploit execution was not run.
Add a regression assertion over the generated profile and a live Linux native probe
that attempts an io_uring socket operation in the same container/landrun boundary.

### P2 — Cleanup failures disappear, including after a verified result

**Location:** `src/physharness/verification/boundary.py:489-495`.

`docker rm --force` exceptions are swallowed, and its nonzero return code is ignored.
The outcome contains neither a cleanup warning nor the random container name needed
for reconciliation. A timeout followed by loss of the Docker daemon can therefore
leave a running container without reporting the failed cleanup. A synthetic successful
driver response followed by a cleanup timeout still returns `verified/kernel_checked`
with no cleanup diagnostic. The report currently says daemon failure cannot produce
an accepted run, which is stronger than the implementation.

**Fix:** preserve cleanup outcome, container identity, exit code and bounded output
in diagnostics or an operational event. Treat indeterminate containment as blocked
when termination cannot be established. Distinguish confirmed container absence from
real cleanup failure: `--rm` may already have removed a successfully exited container,
so blindly rejecting every `docker rm` nonzero exit would break normal successful runs.

**Evidence:** patched `bounded_process` only in an isolated audit process: `docker run`
returned the existing test's synthetic valid response, and `docker rm` raised
`ExecutionFailure('checker_timeout', ...)`. Observed:

```text
Cleanup failure result: verified kernel_checked
diagnostics: axioms_are_policy_upper_bound, qualification_report_sha256
```

Add controlled transport regressions for cleanup timeout, nonzero cleanup, and
confirmed already-absent containers after both successful and failed verification.

### P2 — Restrictive service umask makes the staged bundle unreadable

**Location:** `src/physharness/verification/boundary.py:409-420`.

`mkdir(mode=0o755)` is still filtered by the service umask, and `request.json` never
receives an explicit read permission. With service umask `0077`, the mount directories
become `0700` and the request becomes `0600`. The fixed container UID 65532 cannot read
those host-owned inputs in the normal case where the service uses another UID. Even
an otherwise correct, fully provisioned verifier then fails before its driver can
construct a structured outcome; the initial request read occurs outside the driver's
try block. Nested trusted directories have the same umask sensitivity.

**Fix:** set final permissions explicitly on the mount roots, nested directories,
and request metadata, or deliberately map ownership to the container's service UID.
Keep the outer temporary directory private. Test the final staging permissions with
umask `0077`, and exercise an actual nonroot container reading the mounted files.

**Evidence:** captured the live staging modes inside the controlled Docker transport
while running with umask `0077`; restored the original umask afterward:

```text
trusted_mode = 0o700
request_mode = 0o600
challenge_mode = 0o444
```

### P2 — A signal-killed checker is classified as a rejected proof

**Location:** `src/physharness/verification/container_driver.py:158-166`.

Every nonzero comparator exit becomes `rejected/comparator_failed`, including a
negative subprocess return code for a signal. An OOM kill, SIGSEGV, or externally
killed Comparator never completes proof checking and must not become negative
mathematical evidence. This also contradicts the documentation's distinction between
proof rejection and process failure.

**Fix:** classify signal termination as `blocked` with a distinct code, signal and
bounded diagnostics. For positive exit codes, upstream Comparator currently uses
process errors for multiple failure phases; preserve that uncertainty unless a trusted
structured interface can distinguish actual proof rejection from infrastructure
failure. Do not infer trusted phase/status from candidate-controlled stdout text.

**Evidence:** ran the real `main()` classification code with in-memory trusted paths,
successful preflight probes and a controlled `run_comparator` return of `(-9, b'')`.
Observed `rejected comparator_failed -9`. No candidate or kernel ran. Add direct
driver tests for signal termination and operational errors, independently of the host
response-validation tests.

## Trust-boundary assessment

- **Identity:** host preflight hashes UTF-8 candidate bytes. Manifest, target,
  environment, reviewed theorem names, project files, image and binary pins are
  service-owned inputs. The staged bytes come from the checked reads, and returned
  digests/version values are compared against the request/environment. I found no
  candidate-controlled route around these bindings in this scope. Service ownership
  and immutability are prerequisites, not properties established merely by SHA256.
- **Worker authority and forged output:** candidate/Comparator output is captured
  inside a JSON diagnostics string; host code validates the trusted driver response.
  A worker saying “verified” on stdout is not parsed as a receipt. This depends on
  actually containing generated code away from the driver and its output channel.
- **Actual Comparator API:** the configured JSON keys, `lake env comparator config`,
  executable environment variables, and `enable_nanoda` compatibility path match
  upstream. Upstream builds/exports the challenge before the solution, compares
  declarations, audits axioms, and runs configured kernels. The code path propagates
  independent-kernel failure to an unsuccessful run. See [Comparator Main.lean](https://raw.githubusercontent.com/leanprover/comparator/refs/heads/master/Main.lean)
  and its [README](https://github.com/leanprover/comparator/blob/master/README.md).
- **Independent kernel:** the driver's publication result is justified only if the
  pinned, audited Comparator build actually executes the compatible pinned nanoda
  binary as upstream does. No real nanoda receipt was observed. The implementation
  correctly blocks unqualified publication and labels the reported axioms as an
  allowed-set upper bound rather than a measured per-proof closure.
- **Generated Lean and caches:** candidate build artifacts remain untrusted; their
  export and kernel replay are the acceptance mechanism. The existing host-write
  test deliberately disables the launcher, so it proves only that unavailable
  execution does not run source on the host. It is not containment evidence.
- **Linux qualification identity:** qualification pins image and driver, but the
  host launcher/seccomp policy and actual kernel/runtime identity are not checked
  against that record. A host-policy change can preserve `driver_digest()` and reuse
  the old configuration. This is a deployment design gap to close before signoff:
  bind the complete policy and applicable runtime evidence to qualification, or
  enforce equivalent deployment-version controls. The documented report hash is an
  operator's evidence reference, not an automatic certificate.

## Verification and remaining qualification

The scoped suite ran successfully:

```text
.venv/bin/python -m pytest tests/test_verification.py -q
25 passed in 1.17s
```

All additional audit reproductions above were temporary, controlled Python transport
or driver tests. No implementation changes or new persistent test files were made.
Source inspection used primary upstream sources as they existed during this audit;
the deployment still needs exact source commits and reproducible binary/image pins.

`formal/qualification.json` honestly records blocked/unreviewed/not-run states.
The Dockerfile is only a final driver layer on an absent audited toolchain image;
neither formal fixture has been compiled or independently reviewed. Real positive
and negative Lean cases, forged-output attempts, socket/io_uring probes, malicious
cache manipulation, process interference, and independent-kernel replay must run on
the exact qualified Linux deployment. Those are outstanding evidence obligations,
not test results supplied by this audit.
