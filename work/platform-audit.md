# Independent evaluation, learning and infrastructure audit

**Historical findings and rechecks.** The lifecycle findings below were subsequently corrected;
the final independent reproduction results are in [integration-audit.md](integration-audit.md).
References below to pending correction describe the state when those reproductions were made,
not the current code. Live qualification remains outstanding.

Audited 2026-09-14. Read-only implementation audit of `evaluation/`, `learning/`,
their tests, AWS Terraform, Compose, Dockerfile, migrations, infrastructure scripts
and CI workflows. Only this report was written. Science/knowledge/benchmark
implementation authored by this auditor was excluded from independent certification.
No AWS API, Terraform plan/apply, hosted provider or paid call was made.

Three platform P2 defects were reproduced and subsequently fixed and independently
rechecked: authentication secrets in startup errors, stale qualification success
after a failed rerun, and physically inconsistent elapsed metrics. A follow-up
E2B review reproduced three further P2 lifecycle defects documented below. None of these
reproduction is evidence of a verified scientific theorem. Findings were sent to
the parent for remediation before commits. Initial scoped tests: **33 passed,
1 skipped**; the skip is the absent dedicated PostgreSQL endpoint.

## P2: Malformed authentication entries expose bearer tokens in startup errors

**Location:** `src/physharness/config.py:14-20`, `Settings.auth_tokens`; traceback
logging in `src/physharness/worker.py`'s main exception handler and normal Uvicorn
startup error reporting. Configuration was checked because it consumes the secret
JSON injected by both Compose and ECS.

`auth_tokens` is a dictionary whose keys are secret bearer tokens and whose values
are validated `Principal` models. When a value is malformed, Pydantic includes the
full dictionary key in the validation error location. `repr=False` only hides the
field from model repr; it does not hide this key. A typo during credential rotation
can therefore send a token to application/CloudWatch logs. The token can still be
valid in healthy replicas or after the malformed role is corrected.

**Reproduction:** no real credential was read or printed:

```python
secret = "SYNTHETIC_TOKEN_FOR_AUDIT_" * 2
Settings(auth_file="/nonexistent", auth_tokens={
    secret: {"id": "x", "project_id": "p", "role": "bad-role"}
})
```

Observed `str(ValidationError)` contains:

```text
auth_tokens.SYNTHETIC_TOKEN_FOR_AUDIT_SYNTHETIC_TOKEN_FOR_AUDIT_.role
```

**Fix:** sanitize secret-bearing configuration validation at a boundary that removes
secret dictionary keys from error locations and input values. Raise/log a safe,
actionable configuration error without retaining the original secret-bearing
exception chain. Merely adding `hide_input_in_errors=True` does not redact the
location. Test the complete exception/traceback output for a unique synthetic token,
including nested malformed auth-file records and deployment-validator failures.

**Independent recheck:** fixed. The configuration boundary now converts malformed
authentication safely and turns raw Settings construction errors into a sanitized
`ConfigurationError` without the original exception chain. The original synthetic
token is absent from the full formatted traceback. Constructor, environment and
file-source security regressions pass; field repr suppression alone is no longer
relied upon.

## P2: Failed qualification rerun can preserve a stale passed report

**Location:** `infra/run_qualified_lean.py:89-97`, with partial-result writes at
lines 74-76.

The command's exception handler writes a blocked report only if the output path
does not already exist. If an operator reruns the command against the same output
path and fails preflight, the file can still contain a previous run's `passed`
status. If execution instead fails after writing any case result, it leaves the
artifact marked `running`. The process correctly exits nonzero, but the report
consumed separately from that exit code does not describe the current outcome.
The CI workflow uploads this report with `if: always()`.

**Reproduction:** in a temporary directory, write an explicitly synthetic previous
report, then run the real CLI on this Darwin host:

```python
output.write_text('{"status":"passed","results":[{"id":"previous-run-fixture"}]}')
result = subprocess.run(
    [sys.executable, "infra/run_qualified_lean.py", "--output", str(output)],
    capture_output=True, text=True,
)
```

Observed:

```text
CURRENT_EXIT_CODE 1
ERROR_TYPE RuntimeError: Qualified verifier CI requires Linux
RETAINED_STATUS passed
```

The same exception-handler behavior applies on Linux when required inputs are
missing or fail their digest checks. This demonstrates stale report handling,
not a way to make the verifier accept a candidate or turn a failed CI job green.

**Fix:** begin a fresh run record with a unique run identity, overwrite stale success
before preflight, and always finalize exceptions as blocked/failed while preserving
only this run's partial results and diagnostics. Prefer atomic report replacement.
Add regression cases for an existing passed file plus preflight failure and for
failure after at least one recorded case; preserve the nonzero exit.

**Independent recheck:** fixed. The command begins a fresh report/run ID, atomically
replaces the old file, and finalizes exceptions as blocked with this run's partial
results. The original CLI reproduction now exits 1 with `status=blocked`, a fresh
run ID and no previous-run fixture in results. The partial-results regression passes.

## P2: Evaluation accepts impossible campaign elapsed time

**Location:** `src/physharness/evaluation/statistics.py:59-72`, `summarize`;
actual-wall matching at `compare` lines 144-155.

The summary checks that elapsed time is finite, nonnegative and below the budget,
but never checks consistency with observed attempt durations. A completed attempt
lasting 20 seconds can be summarized as a solved target in zero elapsed seconds.
`compare(..., matching="actual")` subsequently treats equal reported elapsed times
as equal wall-clock exposure. Ordinary data-assembly mistakes can therefore produce
internally impossible speed/exposure metrics without any validation error.

**Reproduction:** reuse the existing synthetic evaluation fixtures:

```python
from test_evaluation import manifest, observation, evidence
from physharness.evaluation import PortfolioPlanner, summarize
m = manifest()
plans = PortfolioPlanner(m).plan()
obs = observation(plans[0], "receipt-p1", wall_seconds=20)
summary = summarize(m, plans, [obs], evidence(), elapsed_seconds=0)
```

Observed:

```text
OBSERVED_ATTEMPT_WALL_SECONDS 20.0
SUMMARY_ELAPSED_SECONDS 0.0
SUMMARY_SOLVED 1
```

**Fix:** reject elapsed durations shorter than any contained attempt and shorter
than aggregate attempt duration divided by the declared concurrency limit, using
a documented timing tolerance if measurements require one. This enforces internal
consistency; authentic runtime timestamps and ledger provenance remain the trusted
loader's responsibility. Add one single-attempt and one multi-attempt/concurrency
regression. No claim that scalar consistency authenticates invented telemetry is needed.

**Independent recheck:** fixed. `summarize` now checks both the longest observed
duration and total duration divided by concurrency. The original 20-second attempt
with zero elapsed time raises an explicit consistency error. Single-attempt and
aggregate-duration regressions pass.

## Follow-up E2B lifecycle and authority review

Scope added by parent: `execution/e2b.py` and
`tests/test_execution_e2b_durable.py`, with inspection of the actual installed
`e2b==2.49.1` SDK. No E2B API request or remote VM allocation was performed.
The following reproductions controlled only SDK transport/disk failure responses;
they are not live provider qualification results.

### P2: Concurrent initial creation leaks an allocated VM

**Location:** `src/physharness/execution/e2b.py:278-312`, `create`.

The method checks `_sandbox is None` and then awaits `AsyncSandbox.create` without
marking creation in flight. Two concurrent calls pass the check and each allocate
a VM. Both return success, but the second result overwrites the first VM handle.
No cleanup occurs for the first allocation, which can continue incurring charges.
The exclusive-operation checks used elsewhere do not cover initial creation.

**Reproduction:** replace the SDK create call with an async transport fixture that
records a new distinct VM, yields once, and returns it. Run
`await asyncio.gather(provider.create(), provider.create())`. Observed:

```text
allocations = 2
errors = []
owned VM = vm-1
kill calls = 0
```

**Fix:** reserve the creation state before awaiting the provider. Reject overlapping
creation and handle uncertain allocation results explicitly; never silently overwrite
an existing owned VM. Test that one concurrent caller succeeds and the other fails
before a second allocation occurs.

### P2: Journal failure after fork/restore loses an allocated child's identity

**Location:** `src/physharness/execution/e2b.py`, the `_complete_native` calls after
successful `fork` and `restore_snapshot` (original lines 692-695 and 751-754).

The remote allocation/network check is protected by cleanup handling, but journal
completion occurs after that protected block and before `_native_children` stores
the child. If journal completion fails, the allocated child is neither killed nor
retained and its ID is absent from the pending journal record and raised disk error.
The retry is correctly blocked as uncertain, but the caller has lost the known
resource identity needed to reconcile the allocation.

**Reproduction:** return a valid no-egress child `vm-leaked` from the controlled SDK
fork, then make `journal.complete` raise `OSError('injected disk failure')`. Observed:

```text
raised = OSError: injected disk failure
child kill calls = 0
retained children = 0
journal status = pending
journal result = None
```

**Fix:** include durable result commit in the allocation failure boundary. On commit
failure retain/report the known child identity, attempt cleanup or explicitly
quarantine it, preserve cleanup failures, and return an actionable uncertain result.
Never allow retries to create a replacement for this uncertain allocation. Exercise
both fork and snapshot restore, including journal failure after a commit actually
occurred and cleanup failure.

### P2: Timed-out or cancelled file helper can overlap new VM work

**Location:** `src/physharness/execution/e2b.py:433-471`, `_exclusive` and `_file_action`.

The installed E2B `Commands.run` documents its timeout as a command-connection
timeout; its wait path does not kill the remote process on failure. `_file_action`
turns a timeout into a transfer error, but leaves the VM alive. `_exclusive` then
clears the active-operation marker. A restore/write helper may still be running
while the next arbitrary command is accepted. Cancellation also escapes the
`except Exception` block and clears the marker without termination. Ordinary
`run` already closes the VM for timeouts/cancellation; file operations omit that
protection.

**Reproduction:** have the controlled SDK file-helper call raise its actual
`TimeoutException`, then submit a new command. Observed:

```text
transfer error = WORKSPACE_TRANSFER_FAILED
VM kill calls = 0
active operations = set()
next command accepted with exit code 0
```

This demonstrates the adapter's state transition. Continued remote mutation is an
inference from the installed SDK's connection-timeout/wait contract, not a live VM
experiment.

**Fix:** terminate or quarantine the VM when a transfer times out/is cancelled or
has indeterminate remote completion. Preserve identity and cleanup diagnostics and
prohibit further work until the uncertainty is resolved. A disconnected stream is
not proof that the helper stopped.

**Original E2B finding rechecks:** creation now permits one allocation and rejects
the concurrent caller before its SDK call. A failed child journal commit now raises
`OPERATION_UNCERTAIN`, reports the exact child ID, retains an observation and attempts
bounded cleanup. A timed-out file transfer now terminates/quarantines the VM and
rejects the next command. I reran all three original reproductions and observed
those corrected behaviors; the expanded scoped suite passed 77 tests with one
dedicated-PostgreSQL skip.

**Regression found during that recheck, pending correction:** the first repair
treated definite helper errors as uncertain and killed the VM for all of them.
Using the actual local helper with a controlled remote kill, I uploaded an existing
uncheckpointed file and requested restore of a different archive. The helper
correctly refused the nonempty workspace, but the adapter called VM kill once and
removed its handle. On a real ephemeral VM that would discard the very workspace
the refusal was intended to protect. Completed validation errors (including actual
SDK `CommandExitException`) must preserve the VM. Partial completed writes may
need quarantine/reconciliation without deleting recoverable data; transport timeout
and cancellation are separate cases. This is a concrete destructive regression,
not a live demonstration of lost user data.

A related first-repair issue quarantined an already-owned healthy VM when a second
`create()` merely returned the preflight `OPERATION_CONFLICT`; no allocation had
been attempted. The preflight rejection should occur outside the uncertain-side-effect
region. Both regressions were sent to the implementer and parent before signoff.

The archive code validates canonical relative paths, count/size limits and per-file
hashes; helper traversal uses directory descriptors/O_NOFOLLOW and rejects ordinary
symlinks, hardlinks and special files. Existing local helper regressions pass. No
host escape was demonstrated. VM-supplied archive contents remain untrusted data,
not proof receipts. Checkpoint hashes protect integrity, not principal authorization.

Fork/resume/restore inspect VM identity and returned no-egress metadata; creation
requests `allow_internet_access=False`, `secure=True`, and empty envs. These are
provider contract/configuration checks, not measured network-isolation evidence.
Version-like snapshot text plus operator pin equality cannot itself establish that
an arbitrary provider tag is immutable; the explicit operator qualification remains
necessary. `workspace_capabilities.live_qualified` correctly remains false.

## Evaluation and learning assessment

- `CanonicalEvidence` explicitly assumes an authenticated application snapshot.
  It deep-copies records and validates exact problem/review/receipt/artifact/project
  relationships, candidate and environment identities, verified outcome schema and
  publication assurance. It does not claim that a digest authenticates caller-made
  dictionaries. The public worker API does not expose this constructor as authority.
- Success counting is per target, not per repeated proof receipt. Invalid evidence
  gets a reason; repeated receipt and trace IDs cannot silently create extra wins.
  Observed model substitutions and budget violations are rejected. Live trace
  provenance is a supplied digest, not independently authenticated by this module;
  that limitation is explicitly documented and no production loader is claimed.
- Planning is offline and conservative about funded capacity. Adaptive candidate
  pools are explicitly larger than launchable capacity; callers must use selection
  and the separate execution layer. UCB scores are not labeled calibrated proof
  probabilities. Uniform/adaptive policy execution qualification is not inferred
  from deterministic planner tests.
- Dataset export requires canonical receipts, exact proof bytes and administrative
  licensing decisions. Family IDs, identical target digests and identical proof
  bytes cannot cross partitions. Licensing and semantic family labels remain
  curator assertions; no automatic legal review or semantic leakage detection is
  claimed.
- TF-IDF vocabulary/weights are fitted from training rows only. Model-state mutation
  under an old digest is detected. Holdout evaluation checks training-family overlap
  and available relevance targets; the promotion gate pairs the same corpus/cases/
  mode/cutoff and counts independent family groups. Repeated tuning on one holdout
  still requires the explicitly absent campaign-level registry.
- Offline promotion may be approved on synthetic fixtures, but retains the synthetic
  mode and `production_qualified=False`. Rollback output binds evaluated model IDs
  and retains `applied=False`. These are accurately labeled proposals, not deployed
  improvements, LLM training, RL success or scientific discovery.

## Infrastructure and CI assessment

Apart from the configuration-validation disclosure above, no additional concrete
unsafe-host-execution or credential-disclosure defect was demonstrated in the
reviewed configuration. This is not a production signoff.

- Local ports bind loopback. Generated local credentials are random, mode 0600 and
  not overwritten; no model-provider key is generated. The Compose parser test
  passes, but it does not run the service containers or qualify startup ordering.
- The Dockerfile uses digest inputs, a nonroot user, a dedicated writable state
  path and no embedded credentials. Docker exclusions omit private environment,
  state, private keys, Terraform state and generated research content. The included
  PEM is a public RDS trust bundle, with digest metadata and no private key.
- The ECS scratch path matches the Dockerfile's `VOLUME` and has deliberate image
  ownership. This follows the documented ECS mechanism for copying Dockerfile
  volume contents/permissions; an empty Fargate mount was not assumed automatically
  writable merely because the task uses a nonroot UID. See the primary
  [ECS bind-mount documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/bind-mounts.html).
- Terraform declares private tasks/RDS/internal ALB, explicit secret ARNs, distinct
  execution/task roles, encrypted/versioned artifacts, TLS and zero initial service
  counts. External VPN/DNS/certificate/secret provisioning and a separately qualified
  verifier fleet are stated prerequisites. Zero task counts do not prevent charges
  for RDS/NAT resources; deployment docs say so. No cloud deployment was attempted.
- The PostgreSQL schema migration is frozen and does not import mutable ORM metadata.
  SQLite migration/rollback and PostgreSQL SQL generation pass; no dedicated live
  PostgreSQL endpoint was available in this audit. Constraints and supplied-connection
  behavior are covered by the scoped tests.
- The Temporal schema setup uses versioned migrations; upstream 1.31.0 setup skips
  resetting a database whose current schema version exceeds its initial version.
  That repeated-start concern was investigated and not reported as a defect. See
  primary [Temporal setup task source](https://raw.githubusercontent.com/temporalio/temporal/v1.31.0/tools/common/schema/setuptask.go).
- CI separates unit/metadata checks from manual Linux proof checks, pins external
  actions and images, and supplies no publishing/deployment credentials to PR jobs.
  Self-hosted proof execution requires a protected environment and trusted revisions;
  repository files alone do not establish those external settings. Presence of the
  workflow is explicitly not proof or containment evidence.
- Because Comparator currently cannot reliably distinguish mathematical rejection
  from process failure, nonzero checks are blocked. The manual case runner's demand
  for at least one `rejected` expected case can be met by a preflight digest mismatch;
  it is not itself evidence that a well-formed false theorem was kernel-rejected.
  Qualification reviewers must inspect the pinned cases and real outcome phases.

## Verification and limits

```text
.venv/bin/python -m pytest tests/test_evaluation.py tests/test_learning.py tests/test_infrastructure.py -q
33 passed, 1 skipped in 0.24 seconds

.venv/bin/python -m pytest tests/test_config_security.py tests/test_infrastructure.py tests/test_evaluation.py tests/test_learning.py tests/test_execution_e2b_durable.py -q
Follow-up platform-fix and initial E2B review: 64 passed, 1 skipped in 0.72 seconds
```

The extra reproductions used temporary files, synthetic credentials and existing
synthetic fixtures.
No implementation/test files were edited, no child agents spawned and no commits
created. No cloud API, container build/start, actual Linux qualification, scientific
proof replay, production snapshot, licensing approval or live model experiment was
performed. These unavailable evidence obligations remain distinct from the
reproduced correctness defects above.
