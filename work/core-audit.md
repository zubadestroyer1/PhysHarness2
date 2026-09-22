# Independent application and control audit

Audited 2026-09-14. Scope: application authority, domain/storage/artifacts, API,
client/config/bootstrap/CLI, collaboration/acceptance, worker and orchestration,
and the core/API/authority/orchestration/Temporal tests. Read-only implementation
audit; only this report was written. The parent changed implementation while the
audit ran; findings below distinguish the original reproductions from rechecks.

Four concrete P2 defects were reproduced and fixed during the audit. Their fixes
were independently rechecked, including completed-task and cancelled-experiment
redelivery against actual local Temporal servers. No outstanding demonstrated
P1/P2 defect remains from this scope at the final recheck. No scientific proof
acceptance bypass, duplicate paid model call, or workflow nondeterminism was
demonstrated. This is a scoped audit, not a security or deployment qualification.

## P2: Runtime setup failure permanently consumes a worker slot

**Original location:** `src/physharness/orchestration/research_worker.py:253-344`.
**Current relevant location:** `ResearchTaskExecutor.execute`, lines 261-438.

The worker reserved a slot and acquired the task lease, then constructed the
runtime, assembled its prompt, and validated model/runtime configuration before
entering its cleanup `try/finally`. Any error in that interval left the task
`running` and the budget's `active_workers` incremented, without a failure artifact.
Task lease expiry does not release that separate reservation. At concurrency one,
subsequent work cannot start.

**Reproduction:** create/start an experiment using `tests/test_core.py`'s
`setup_experiment(..., concurrency=1)`, create a branch/task, and construct
`ResearchTaskExecutor` with a `runtime_factory` that raises `RuntimeError` in its
constructor. Call `execute` and inspect the task, ledger and artifacts. Actual
original output:

```text
SETUP_ERROR injected runtime setup failure
task.status = running
active_workers = 1
next reserve_resources(..., workers=1) = CONCURRENCY_EXCEEDED
failure artifacts = []
```

**Fix:** cover setup as well as execution with cleanup and failure recording;
initialize optional asyncio task handles before entering that region. Validate
user configuration before acquiring resources where practical.

**Recheck:** the parent extended the protected region. Its constructor-failure
regression passes. I additionally used the real Responses runtime with accepted
experiment input `runtime_limits={"max_turns": 0}`; validation raised before any
provider call, the task became `blocked`, `active_workers` returned to zero, and
one failure artifact was retained. Validation of that input still occurs late,
but it no longer leaks resources.

## P2: Cached command response bypasses changed agent scope

**Location:** `src/physharness/service.py:224-253`, `HarnessService._execute`.

The command cache was keyed by project, principal ID and idempotency key, with a
fingerprint containing only operation and inputs. A matching cache hit returned
the prior object before the action's scope check. Reusing a principal ID after
its role or experiment assignment changed could reveal a record that the current
identity was forbidden to read. This does not require another project's token.

**Reproduction:** create a branch under experiment A using researcher identity X
and key `branch`. Create actual experiment B. Construct the same project/principal
ID X as an agent assigned B. A direct read of A's branch returns `NOT_FOUND`, but
repeating the original `create_branch(A, same_input, X, "branch")` returned A's
complete branch record. Original output:

```text
SCOPED_READ NOT_FOUND
SCOPED_REPLAY_LEAK True True
```

**Fix:** bind cache identity to authorization scope, or perform current authorization
before returning prior results. Roles and assignments must not silently reuse a
prior authorization decision.

**Recheck:** fingerprint now includes `actor.role` and `actor.experiment_id`; changed
scope produces an explicit idempotency conflict. The new authority regression passes.

## P2: Identical checkpoint retry conflicts with its own first result

**Location:** `src/physharness/collaboration.py:285-361`, `checkpoint_branch`.

The operation assembled a live restart brief before checking the command cache
and included that snapshot in its fingerprint. Its first success changed branch
revision/checkpoint and added an artifact. Retrying exactly the same arguments
and idempotency key recomputed a different snapshot and therefore rejected the
original request. A lost successful response could not be recovered through the
advertised idempotent mutation contract.

**Reproduction:** call twice with the same arguments:

```python
args = (branch["id"], branch["revision"], "approach",
        "b" * 64, "a" * 64, None, actor, "checkpoint")
first = service.checkpoint_branch(*args)
second = service.checkpoint_branch(*args)
```

The original second call raised `IDEMPOTENCY_CONFLICT`.

**Fix:** fingerprint stable caller intent only; assemble/store the live brief in the
new-command action after the cache decision.

**Recheck:** the parent made that change and the immediate identical-retry regression
passes. Broader concurrent export/restart snapshot consistency remains a documented
limitation rather than a claim established by this fix.

## P2: Redelivery after workflow completion leaves outbox events pending forever

**Original location:** `src/physharness/worker.py:156-185`, nested `deliver`;
`src/physharness/orchestration/outbox.py:54-89`.

The delivery code passed both `WorkflowIDReusePolicy.REJECT_DUPLICATE` and
`WorkflowIDConflictPolicy.USE_EXISTING` to Temporal. The conflict policy covers an
already-running workflow. It does not make a new start against a closed workflow
succeed when the reuse policy rejects duplicates. If the start reaches Temporal,
the worker loses its outbox acknowledgment, and that workflow completes before
redelivery, every subsequent delivery raises `WorkflowAlreadyStartedError`.
The dispatcher returns that row to `pending` each time. A batch filled with such
rows can also delay new events. The policy prevents duplicate work; the defect is
failure to reconcile the already executed operation and acknowledge delivery.

**Real reproduction:** pinned official Temporal CLI 1.8.3, server 1.31.2, Darwin
arm64, local loopback, in-memory server, no hosted model or cloud provider calls.
Registered the existing `TaskWorkflow` and `scripted_task` fixture, started
`audit-task` using the exact two policies, awaited its successful result, then
called `start_workflow` again with the same ID/inputs/options:

```text
FIRST {'evidence': 'replay_fixture', 'status': 'completed', 'task_id': 'audit-task'}
REDELIVERY_FAILED WorkflowAlreadyStartedError Workflow execution already started
```

The initial sandbox attempt could not download the CLI; the authorized escalation
downloaded the pinned official CLI and completed the actual local test. No fallback
or simulated result is represented as live evidence.

**Fix:** handle a closed existing workflow explicitly without starting another run.
Resolve its exact workflow identity/type and relevant status, then acknowledge an
already delivered operation or retain an explicit actionable failure/reconciliation
state. Do not use `ALLOW_DUPLICATE` as a shortcut: that can repeat external effects.
Add a real Temporal regression for completion between successful delivery and a
lost acknowledgment, alongside running-workflow duplicate handling.

**Recheck:** the parent extracted `orchestration/temporal_delivery.py`, handles
`WorkflowAlreadyStartedError`, and checks stored workflow type, project, aggregate
and stable command hash before acknowledging task/verification duplicates. Against
a second actual local Temporal server, the repaired `TemporalDelivery` acknowledged
redelivery of the completed task, retained the same run ID, and rejected altered
payload as `WORKFLOW_IDENTITY_CONFLICT`.

**Additional edge case found and fixed:** the first repair explicitly
rejected every closed experiment's non-cancellation event. A historical queued/paused
event can have been delivered before its acknowledgment was lost, followed by an
acknowledged cancellation that closes the workflow; retrying that historical event
would still leave it pending forever. The parent added a gate requiring a completed
workflow with the exact cancellation result before acknowledging these historical
commands. Failed or indeterminate experiment runs retain the explicit recovery
error without starting duplicate work.

I tested this final implementation against a third actual local Temporal server:
delivered `experiment.queued`, delivered `experiment.cancelled`, awaited
`{'status': 'cancelled'}`, then redelivered the historical queued event. It was
acknowledged successfully. The fixture activity only recorded command handling;
no paid provider or scientific proof was involved.

## Scientific authority and explicit limitations

- Public candidate submission does not accept a client-supplied outcome. Agents can
  submit Lean artifacts and unproved claims; operator/verifier authority processes
  receipts and only a verified result promotes a formal claim. Scope checks bind
  ordinary artifact/branch/task operations to the project and experiment, subject
  to the now-fixed cached-response defect above.
- Acceptance checks returned candidate/target/environment identities, rejects
  publication assurance downgrades, and detects review changes during verification.
  The configured verifier remains a trusted service boundary. A malicious injected
  verifier object is not a worker-accessible API route.
- Task completion creates research-output evidence, not a formal proof claim.
  Unknown provider side effects are not automatically retried by TaskWorkflow;
  the Responses adapter disables SDK retries. Native-session reconciliation,
  distributed native-provider integration and unsupported live search policies
  remain declared capability gaps; they were not recast as implementation defects.
- SQLite tests exercise transaction/CAS accounting and lease behavior. They do not
  establish PostgreSQL concurrency, remote artifact-store behavior or production
  failover. Real Temporal activity execution here does not qualify paid providers.
- The workflow code uses Temporal activities, waits and sleeps rather than wall
  clock/random I/O in workflow logic. SDK sandbox preparation passed; no replay
  nondeterminism was demonstrated. Exhaustive history/restart testing was not done.
- Pagination was reviewed after the parent finished its patch: the public path
  returns keyset cursors and the internal list method exhausts pages. This does not
  make multiple-page reads a transactionally consistent export snapshot.
- Brief review of the newly connected `ResearchMixin` found no critical promotion
  bypass: knowledge retrieval uses canonical verified claim/receipt pairs, requires
  current approved semantic review and matching environment, enforces sharing and
  discovery filters, and rechecks stored artifact bytes. Source ingestion records
  remain pending; worker-provided receipt-like artifact JSON is not a premise source.

## Recheck of the earlier verification audit

The earlier findings in `work/acceptance-audit.md` are historical reproductions.
The revised implementation denies all three io_uring syscalls and requires EPERM
probes; checks seccomp mode; binds host-launcher and seccomp digests in qualification;
sets final staged permissions explicitly; and blocks indeterminate container cleanup
with container identity and prior-failure diagnostics. Source review found those
changes address the reported code defects.

I re-executed the real driver `main()` with controlled trusted paths/preflight and
Comparator return codes -9, 1 and 137. All three now return `blocked`; signal cases
return `comparator_terminated` with signal diagnostics. This is a direct driver
protocol test, not Linux containment or a real Lean/kernel run.

## Commands and observed verification

```text
.venv/bin/python -m pytest tests/test_core.py tests/test_api.py tests/test_authority.py tests/test_orchestration.py -q
Before fixes: 31 passed, 2 deprecation warnings
After first three fixes plus pagination coverage: 35 passed, 2 deprecation warnings

.venv/bin/python -m pytest tests/test_verification.py -q
41 passed

.venv/bin/python -m pytest tests/test_core.py tests/test_api.py tests/test_authority.py tests/test_orchestration.py tests/test_verification.py -q
Final recheck: 77 passed, 2 deprecation warnings in 2.18 seconds
```

The two warnings concern Starlette/httpx and anyio deprecations. The live Temporal
duplicate-start reproduction completed with the expected failure shown above.
No real positive Lean acceptance, Linux hostile-candidate containment, independent
kernel replay, expert scientific review or production cloud qualification was run.
