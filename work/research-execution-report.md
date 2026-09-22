# Research execution implementation report

Implemented in `codex/formal-research-loop`; no commits or live API calls were made by this
workstream. The live provider and real reviewed research problem remain external prerequisites.

## Completed behavior

- Added the finite `TeamRunManifest` / `ResearchTeamRunner` API, with explicit live versus replay
  mode, root task IDs, bounded concurrency, task count, time, and verification count; reports and
  manifests are immutable canonical artifacts.
- The scheduler discovers model-created helper/collaborator/competing branches, observes task
  dependencies, uses the common experiment ledger, and retains surviving children after parent
  failure. Duplicate completed-task dispatch does not invoke the model again.
- Wired local team candidate queues to the real `process_verification` service under independent
  verifier authority. Added a bounded `wait_for_verification` tool so receipt waiting does not
  require repeated paid model polling. Dispatch errors never synthesize receipt status.
- Bound every research tool mutation to the root implementation's transactional worker-effect
  guard. Native checkpoint persistence uses its operator-only cancelled-experiment evidence
  exception while retaining task fencing.
- Fixed mutable native checkpoint aliases, tool-call deduplication and changed-intent rejection,
  accounting-marker loss on usage callback failure, the continuation preflight visibility race,
  and explicit resume after a known local interruption without outstanding provider effects.
- Preserved model request IDs in provider correlation headers without claiming provider request
  idempotency. Outstanding requests remain reserved after dropped responses and cancellation.
- Fixed active Temporal workflow duplicate delivery bypassing canonical memo validation.

## Deterministic evidence

`tests/test_research_loop_integration.py` uses the actual OpenAI SDK over `httpx.MockTransport`
and real SQLite service transactions, leases, artifact persistence, portable memory, and budget
accounting. No fixture is a live model result or expert scientific review.

The single-worker demonstration consumes the mock response's 15 reported tokens, leaves zero
active workers, and a repeated manifest invokes the provider only once. The two-worker
integration observes two simultaneous worker slots and 30 reported tokens within one shared
ledger. Neither creates a claim or receipt from model text.

The parent-loss integration performs two context compactions, restores the exact assumptions
and unresolved obligation, creates/delegates a helper, then loses a mock HTTP response. Its
helper completes independently; the parent's unresolved request retains its token reservation;
repeated dispatch does not issue another request. The snapshots retain unverified summary
attribution and both canonical checkpoint artifacts.

The verification demonstration stores a source, queues a receipt, waits for the service,
processes an explicitly synthetic checker outcome through `process_verification`, and retrieves
the exact dependency bundle with `recomposition_required=true`. The fixture's checker versions
and code identify it as mock evidence, and the report remains `mode=replay` /
`evidence_level=mock_provider`. This demonstrates routing and authority bindings, not a proof.

Fault coverage includes stale leases, experiment cancellation during generation, finite
supervisor timeout, duplicate worker dispatch, repeated/changed provider tool IDs, lost usage
callbacks, continuation exclusion, deferred children at a task limit, verifier dispatch failure,
and a verifier still executing after supervisor timeout.

## Remaining deployment/live qualifications

1. A real OpenAI API key and recorded exact model prices; no paid generation was attempted here.
2. A real expert-reviewed research target and review credentials. Synthetic test fixture review
   records are not approval for a live problem.
3. The separately built qualified Lean/compiler/comparator/independent-kernel environment and
   its independently checked receipts; the execution test fixture does not qualify those tools.
4. Deployment-specific Temporal/PostgreSQL recovery and worker-fleet qualification. Other
   workstreams exercise real local servers separately; the local scheduler preserves canonical
   state but is not a distributed process manager or a qualified production fleet.
5. Live provider/VM cancellation and billing reconciliation. Local coroutine cancellation does
   not prove a remote request stopped. Native SDKs without hard token ceilings remain excluded
   from this bounded Responses team executor.

A Python verifier thread cannot be forcibly stopped by the team supervisor. A timeout report
retains pending receipt IDs and says `verification_worker_continues=true`; the underlying
checker must enforce its own bound, and process shutdown may wait for it. Abrupt worker process
loss also retains worker/VM reservations until independent reconciliation. These limitations
are explicit, not treated as successful termination.

## Validation run

Executed successfully in this worktree:

```text
.venv/bin/python -m pytest tests/test_research_loop_integration.py \
  tests/test_execution_responses.py tests/test_orchestration.py \
  tests/test_worker_vm_tools.py tests/test_worker_authority.py \
  tests/test_sharing.py tests/test_memory.py tests/test_execution.py -q
94 passed in 5.62s
```

Ruff formatting and checks passed for all execution-owned changed Python files and tests.
The installed Temporal SDK's `WorkflowHandle.signal` signature was inspected to confirm the
explicit signal call and bounded RPC timeout are supported. No external Temporal server,
OpenAI model endpoint, or provider VM was contacted by these checks.

## Independent cross-audit follow-up

A subsequent acceptance cross-audit found that the model-facing verification tool still
requested `publication=False`. The real driver runs nanoda only for the independent replay
tier, so ordinary receipts could not become reusable independently accepted lemmas. With root
authorization, the tool now explicitly requests `publication=True`; this selects an assurance
tier and never grants publication approval. A new regression checks the canonical request and
proves that an unavailable verifier creates no claim or knowledge entry. The team + Responses
suite passed all 27 tests after this correction.

## Typed parameter/preallocation follow-up

Added `execution/parameters.py` with `ResponsesParameters` and the safe public
`validate_responses_parameters(dict) -> dict` helper. It follows the installed SDK types rather
than guessing per-model support, preserves general schema JSON and explicit optional nulls,
and rejects malformed/unknown protocol values without echoing input. Runtime start and legacy
continuation validate before changing checkpoints; research dispatch validates before any
worker reservation or task lease. `TeamRunLimits` was factored out for root CLI validation before
canonical task allocation. Twenty-nine new tests cover malformed types/enums/ranges, secret
non-echo, schema preservation, untouched reservations/leases, legacy continuation, and finite
team limits. The parameter + Responses + canonical team suites passed all 56 tests.

Final preallocation audit also moved exact `ModelConfig` identifier validation and
`RuntimeLimits` parsing ahead of any reservation or lease. Execution receives those parsed
objects directly. Two regressions create malformed configurations through the actual HTTP
experiment route (whitespace-padded model and `max_turns=0`) and prove that the worker retains
queued tasks with no reservations, leases, or native sessions. Invalid diagnostics remain
fixed text without model/input echo. The installed SDK declares `text` as a non-null
`ResponseTextConfigParam`, so the shared validator intentionally rejects `text=null`.

The final focused execution validation passed 68 tests across parameters, Responses,
canonical team integration, orchestration and VM-tool contracts in 3.90s. This includes the
explicit-resume regression previously reported by the full-suite run. Ruff remained clean;
the two warnings came from installed Starlette/httpx/anyio dependencies.

## Final independent registry and operator-workflow audit

Read `verification/registry.py`, `verification/preparation.py`, their config/bootstrap wiring,
`run_control.py`, `cli.py`, and `docs/FIRST_LIVE_RUN.md` without editing those owned files.
No additional actionable acceptance promotion, target-identity, authority, or CLI integration
defect was reproduced. The registry/run-control/CLI suites passed all 30 tests in 0.52s.

A separate no-execution mutation sweep using explicitly synthetic registry fixtures confirmed
that revision swaps, semantic/source/environment digest changes, and theorem-selector changes
all block preflight with `trusted_bundle_invalid`. Missing semantic review and definition holes
also block with no assurance. No checker, model, review, claim or scientific receipt was created
by the sweep. Inspected the root workstream's `.state/operator-workflow-smoke/report.json`:
the real-metadata CLI preparation sequence records zero model calls, no review, and all four
expected missing inputs at preflight. Credential files were not read.

Registry and preparation outputs still rely on the operator's authentic qualification evidence,
trusted image/toolchain closure, and host Docker boundary. Hash correspondence establishes input
identity; it does not itself establish semantic review or production sandbox qualification.

## Real Temporal delivery correction

The root workstream's real Temporal Server 1.31.2 integration exposed a server constraint that
the unit mocks missed: `SignalWithStartWorkflowExecution` rejects conflict policy `FAIL`.
Root changed first experiment delivery to ordinary `StartWorkflow` with the first command in
`pending_commands`; already-started workflows still validate canonical memo/type before an
explicit signal. No workflow implementation change is needed because initialization already
supports pending commands and legacy pre-run signals.

Independent assessment found this compatible with existing signal-start histories and
continue-as-new inputs. The installed SDK explicitly documents inherited memo when omitted
from continue-as-new, preserving the existing canonical identity. Seven added unit cases cover
the ordinary-start contract, validation before signals, both initialization forms, and queued
commands/signals across a continue-as-new boundary. All 15 orchestration tests passed in 0.89s;
Ruff passed. Root owns the real-server regression run and its final result.
