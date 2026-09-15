# Independent integration audit

Audited 2026-09-14. Read-only implementation review of accepted dependency retrieval,
experiment export, offline export validation, logging/configuration/API correlation,
portable memory, and their API/model-tool wiring. Only this report was written. No
hosted model, E2B allocation, paid service, cloud deployment, or live proof checker
was called. Knowledge/science implementation previously authored by this auditor
is not independently certified here; this review concerns the new canonical-service
integration and the portable-memory implementation by another agent.

Three P2 defects were independently reproduced, reported before commits, fixed by
the parent, and independently rechecked. **No open reproduced defect remains in
this integration scope at this checkpoint.** This is a bounded code review, not
production or scientific qualification.

## P2 — Private exports inherit public filesystem permissions — fixed

**Location:** `src/physharness/cli.py:175`, `export`, destination creation and
artifact/manifest writes.

Previously, the CLI used default `mkdir`, `write_bytes`, and `write_text` modes.
With the common `umask 022`, the export directory was `0755` and artifact/manifest
files were `0644`. Operator exports intentionally include private branch/session
artifacts, so another local account able to traverse the selected parent could
read the private bundle.

**Independent reproduction:** invoke the real `cli.export` with a controlled
in-process transport returning one synthetic private artifact and a correctly
hashed manifest. Set and restore `os.umask(0o022)`. Inspect `stat.S_IMODE` for the
new destination, content-addressed artifact, and manifest. Observed before fix:
`0755, 0644, 0644`. No actual private credential or conversation was used.

**Fix/recheck:** destination is created and set to `0700`; files use exclusive,
nofollow creation with mode `0600`. The same independent reproduction now observes
`0700, 0600, 0600`. Content-addressed duplicates are deduplicated. The repository
regression `test_cli_export_is_private_independently_of_umask` also passes.

## P2 — Scoped workers cannot export their reviewed target — fixed

**Location:** `src/physharness/service.py`, `export_experiment`, and `_in_scope`
(current review exception at lines 154–162).

Export loaded the assigned target's current review with `_get`, but review records
do not carry `experiment_id`. The worker scope check rejected them before any
target-specific authorization. A worker could read its experiment, target and own
artifacts but exporting the same authorized state returned `NOT_FOUND`.

**Independent reproduction:** create the ordinary `test_sharing.approaches(lab,
"none")` fixture and call `service.export_experiment(exp["id"], alpha)`. It raised
`NOT_FOUND` despite a valid assigned branch and approved target.

**Fix/recheck:** worker access now permits the exact current review identified by
its assigned target, checking project, problem identity and target digest. Review
paging is scoped accordingly. The original export now succeeds and includes the
matching review. An added independent private-sibling artifact is absent from the
entire serialized export. Repository reproduction and sharing tests pass. This
does not grant broad review browsing.

## P2 — Special-file export input can hang validation — fixed

**Location:** `src/physharness/reproduction.py:13–29`, `_read_file`.

The checker used blocking `os.open(O_RDONLY | O_NOFOLLOW)` and only then checked
`fstat` for a regular file. Opening a FIFO without a writer blocks before that
check, so an untrusted local export can indefinitely hang validation instead of
producing the intended explicit invalid-file error. The defect applied to both
`manifest.json` and a content-addressed artifact path.

**Independent reproduction:** create a temporary export directory with
`os.mkfifo(directory / "manifest.json")`, invoke `validate_export` in a separate
Python subprocess, and enforce a one-second subprocess timeout. Before the fix it
timed out with no writer. The subprocess was killed by the test harness.

**Fix/recheck:** open includes `O_NONBLOCK`, followed by descriptor-level regular
file checking. Independent bounded subprocess checks now reject both a FIFO
manifest and a FIFO artifact with `EXPORT_FILE_INVALID` within the timeout.

## Authority, memory and qualification observations

- Accepted dependency retrieval reads canonical claim/target/receipt/artifact/
  review records, checks exact statements, assumptions, environment and source
  hashes, and enforces sharing and discovery restrictions. Worker-provided receipt
  shapes do not supply those canonical records. Bundles explicitly require proof
  recomposition. No new self-verification path was reproduced.
- Portable checkpoints preserve the full target/review, assumptions, definitions,
  environment and branch policy, retain canonical open obligations and failures,
  and label supplied summaries and approaches unverified. Restoration checks
  issuance metadata, content hashes, lineage, live core and selected references.
  Tests exercise stale review/status, changed assumptions/definitions/environment,
  forged issuance/status, cross-branch privacy and task fencing. No compaction
  acceptance/status laundering was reproduced.
- Export assembles metadata and ledger within one explicit database transaction;
  the SQLite path is exercised locally. PostgreSQL repeatable-read behavior was
  inspected, not tested against a dedicated PostgreSQL server in this pass.
  Immutable artifact bytes are checked after the metadata snapshot.
- Offline validation deliberately reports only `artifact_integrity_checked`;
  it explicitly reports no kernel replay and no publication approval, including
  when a caller rehashes a manifest with invented qualification fields. Missing
  complete dependencies or kernel replay remain explicit capability limits.
- Correlated API failures return opaque diagnostics while server logging preserves
  tracebacks and redacts configured secrets. The focused logging test uses a
  synthetic secret. This is not an exhaustive audit of every vendor logger or
  external infrastructure log sink.

## Validation

Initial requested integration selection: **31 passed**. After fixes and expanded
sharing/API checks, plus the previous E2B lifecycle follow-up:

```text
.venv/bin/python -m pytest tests/test_research_services.py \
  tests/test_reproduction.py tests/test_observability.py tests/test_memory.py \
  tests/test_sharing.py tests/test_api.py tests/test_execution_e2b_durable.py -q
94 passed, 2 warnings in 1.94s
```

The two warnings concern deprecated Starlette/httpx and anyio interfaces. Independent
subprocess/transport reproductions described above also pass after remediation.

The previous E2B follow-up now also includes a passing creation/native-resume race
regression: `_exclusive` rejects `_creating` before an operation can reconnect an
old VM and then have its handle overwritten by the pending allocation. Earlier
known helper rejections preserve VM data; uncertain operations retain identity
and require reconciliation. These tests use controlled transports and local
adapter-authored file helpers, not live E2B or containment qualification.

## Subsequent workspace-broker review

The parent subsequently requested a read-only review of
`orchestration/workspaces.py` and `tests/test_workspace_service.py`, including shared
worker slots and unknown-billing cleanup. This follow-up is separate from the
94-test checkpoint above. Its reproduced broker, adapter and configuration
findings are now fixed and independently rechecked. The later runner/tool wiring
was checked only for the cleanup/lease ordering and shared-capacity behavior
described below; this is not a broader live integration qualification.

### P2 — Definite helper refusal quarantines a healthy VM — fixed

**Location:** `orchestration/workspaces.py`, `_perform` exception path (currently
lines 662–705).

The broker treated every provider exception as an uncertain external effect,
including `ExecutionError("WORKSPACE_TRANSFER_REJECTED", ...)`, which the E2B
adapter uses specifically for a completed helper refusal with preserved VM data.
An export encountering an unsupported file therefore set workspace status to
`reconciliation_required` and its reservation to uncertain. Both subsequent `run`
and `destroy` were blocked before provider dispatch. Healthy data and the reserved
worker slot became inaccessible through normal lifecycle operations.

**Reproduction:** use the canonical-service broker fixture, provision a VM, and
make its controlled `export_workspace` raise that exact definite-refusal code.
Before remediation the canonical state was `reconciliation_required`, execution
and cleanup both raised `WORKSPACE_RECONCILIATION_REQUIRED`, and the ledger held
USD 0.2 and one worker. The fake transport recorded only creation.

**Fix/recheck:** the broker now handles only the narrow definite-refusal code as
rejected. It rechecks lease and operation ownership, stores a rejected operation,
and clears the busy marker while retaining a ready VM. Replaying the operation
returns the same rejection without dispatch. An independent repeat then executed
a command and destroyed the VM successfully; transport calls were exactly
`create, export, run, close`.

Unknown billing after confirmed destruction retains USD 0.2 as uncertain while
releasing the dead VM's worker capacity. A subsequent USD 0.15 invoice settles the
reservation without decrementing workers twice. This behavior was independently
checked. Shared-slot guards and stale-fence regressions were inspected and run:
**20 broker tests passed**. Correct runner ordering still requires cleanup before
`finish_task` expires the lease and before the parent worker slot is settled.

### P2 — Direct E2B command transport failure permits reuse — fixed

**Location:** `execution/e2b.py`, `E2BSandboxProvider.run`, generic exception path
around lines 428–434 and the `finally` block.

Ordinary command transport errors raise `PROVIDER_FAILED` but neither quarantine
nor terminate the VM. The `finally` block clears `_active`. A subsequent direct
adapter command can therefore execute while the first remote command's outcome
and possible continued execution are unknown. The broker's canonical uncertainty
handling protects broker callers, but the public direct adapter remains affected.
The recently fixed file-helper path already takes the safer approach.

**Independent reproduction:** attach a controlled SDK command transport with
`run.side_effect = [OSError("lost transport while outcome unknown"), success]` to
the existing local provider fixture. Run operations `first` and `second`. Observed:

```text
FIRST PROVIDER_FAILED QUARANTINED False KILLS 0
SECOND second command dispatched SDK_DISPATCHES 2
```

No actual VM or generated command ran. The reproduction uses only a mocked SDK
transport. The first error is correctly loud, but it does not prevent unsafe
continuation after an unknown process outcome.

**Required fix:** quarantine uncertain ordinary command failures, preserve the
known execution identity and termination outcome, and use bounded cleanup.
Failed timeout/cancellation cleanup must not leave a reusable VM either. Preserve
normal `CommandResult` handling for actual `CommandExitException` (a completed
nonzero exit). Add next-command/repeated-create rejection tests for uncertain
transport and failed termination, plus the known-nonzero regression. Reported to
the parent and execution implementer; no implementation edit was made here.

**Partial recheck:** ordinary transport, wall timeout, SDK timeout and task
cancellation now quarantine with a bounded cleanup observation; actual nonzero
exits remain normal results. E2B/provider/broker selection: **66 passed**. An
independent actual `provider.cancel(operation_id)` check still exposed the same
missing quarantine on failed termination: blocked `run`, `kill` raises `OSError`,
`cancel` fails with no observation, then the original run reports termination and
a second run dispatches. This is distinct from injecting `CancelledError` inside
`run`. That public cancellation path was subsequently fixed as described next.

**Independent final recheck:** fixed. Actual public cancellation now quarantines
before awaiting bounded termination, records the exact VM identity and truthful
destruction outcome, and blocks another command even if the original command
finishes while termination remains pending. The original failed-kill reproduction
now yields `OPERATION_UNCERTAIN` with destruction false; it no longer claims VM
termination. The pending-kill reproduction also blocks reuse after `_active`
clears, then retains confirmed destruction when the kill finishes. Each path
dispatches exactly one command and one kill. Known nonzero command exits remain
normal results and retain a usable VM in their regression test.

### P2 — Broker loses confirmed destruction from failed command cleanup — fixed

**Location:** `orchestration/workspaces.py`, `_perform` failure path and
`_record_uncertainty`.

The E2B adapter can now confirm that a timed-out/cancelled/uncertain command's VM
was destroyed and retain `last_execution_observation` with the exact execution
ID. The broker ignores that observation and records `destruction_confirmed=False`
unless the operation itself was explicit `destroy`. Normal timeout cleanup thus
leaves a dead VM occupying capacity; canonical uncertainty prevents a subsequent
`destroy` from reaching the already terminated provider.

**Reproduction:** in the canonical broker fixture with concurrency one, a
controlled `run` sets `last_execution_observation={execution_id: "vm-123",
destruction_confirmed: True}` then raises `ExecutionError("TIMEOUT", ...)`, matching
the real adapter's new behavior. Canonical status becomes
`reconciliation_required`, canonical destruction is false, and the sole worker
slot remains held. This is conservative overholding, not early release, but it
discards known cleanup evidence and prevents continued work without reconciliation.

**Required fix:** transfer trusted provider destruction observations only after
binding the exact workspace/execution identity; atomically record destruction and
release only worker capacity while preserving unknown charges. Shared controller
capacity remains the runner's responsibility. Test confirmed and unknown cleanup
separately, including later invoice settlement and repeated observations.

**Independent final recheck:** fixed. Exact-VM confirmed destruction now records a
destroyed workspace and failed command, releases capacity, and retains uncertain
cost. The original reproduction now yields zero active workers. Replaying the
failed operation and subsequently settling its invoice keep capacity at zero.
Both a false destruction observation and a true observation for a different VM
leave capacity held. The new worker/VM ordering tests also pass: normal cleanup
occurs before lease release; failed cleanup blocks the task and retains its shared
slot. Broker, worker-VM and configuration selection: **30 passed**.

### P2 — Workspace policy validation leaks accidental credentials at startup — fixed

**Location:** `config.py`, newly added `worker_workspace` raw dictionary, and
`worker.py:147–153`, deferred `WorkspacePolicy.model_validate`.

Workspace policy validation occurs outside the safe Settings-construction boundary.
Pydantic's forbidden-extra error prints the rejected value. If an operator
mistakenly places `api_key` in this policy instead of the dedicated environment
variable, worker startup logs expose that value. The existing logger only redacts
known configured credential sources, so this accidental policy field is not
redacted. This is the earlier configuration-secret defect through a new input path.

**Independent reproduction:** construct otherwise valid `worker_workspace` policy
with an additional `api_key="SYNTHETIC_NEW_WORKSPACE_SECRET_123456"`; construct real
Settings and `configure_logging(settings=settings)`, then validate with real
`WorkspacePolicy.model_validate`. Format the resulting exception through the
configured worker logger's formatter. The synthetic secret occurs in the formatted
log. No actual credential, Temporal connection or provider allocation was used.

**Required fix:** validate through a safe configuration boundary or sanitize the
policy exception without forwarding secret values, arbitrary nested locations or
the original exception chain. Suppress the raw policy's repr as defense in depth.
Test the full configured-log/traceback output, not only model repr.

**Independent final recheck:** fixed. `Settings.worker_workspace` is now a typed
`WorkspacePolicy` with repr suppressed, validated inside the safe Settings
constructor. Worker startup consumes that validated policy directly. The original
synthetic credential reproduction now raises a safe `ConfigurationError`; the
full configured JSON log/traceback includes the field name for diagnosis but not
the supplied secret. The targeted security regression passes.

## Final recheck result

All three findings open at the start of the final recheck are closed. Only these
fixes and their directly associated regressions were rechecked; no new scope was
added. Independent reproductions covered public cancellation with failed and
pending termination, exact/mismatched provider cleanup identity, false cleanup
confirmation, repeated failed-operation replay, invoice settlement and safe
workspace-policy diagnostics.

```text
.venv/bin/python -m pytest tests/test_execution_e2b_durable.py \
  tests/test_execution_providers.py tests/test_workspace_service.py \
  tests/test_worker_vm_tools.py tests/test_config_security.py -q
83 passed in 1.47s
```

There are **no open reproduced findings from this audit**. No hosted VM, model,
paid service, production database or live kernel qualification was exercised.
