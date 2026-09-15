# Research loop implementation ledger

Scope approved September 15, 2026: implement the pinned formal environment, scientific review
preparation, real acceptance tests, live-model launch scaffolding and bounded multi-agent execution.
The user will supply a model API credential and reviewed problem later. Those inputs are not
fabricated here. Existing twelve-wave qualification requirements remain in force.

Base: `3cc5185e9ab19672538eacd0400f3aae6e2e6a43`; worktree branch
`codex/formal-research-loop`, stacked on the unmerged foundation PR.

## Work and ownership

1. Formal environment: compatible exact source/toolchain pins, reproducible Linux builder,
   declaration audit records and actual build evidence. Owner: formal_environment agent.
2. Acceptance: semantic/source identity separation, immutable bundle construction, real checker
   protocol and positive/adversarial qualification runner. Owner: acceptance_pipeline agent.
3. Research execution: transactional worker authority, bounded concurrent task runner, resource
   uncertainty, cancellation/recovery and evidence-preserving context. Owner: research_execution
   agent with application transaction guard integrated by root.
4. Operator workflow: strict run manifests, preparation without manufactured review, preflight,
   launch/review commands, morning runbook and integration checks. Owner: root.
5. Independent scoped reviews, fixes, aggregate validation and reviewable GitHub delivery.

## Binding constraints

- No credentials, invented reviews, fabricated proof receipts or silent assurance downgrades.
- Source compilation, independent proof checking, semantic review and live model throughput
  receive separate evidence statuses.
- Agents choose mathematical approaches; mandatory checks govern authority and acceptance.
- Every external live experiment needs explicit recorded resources; tests use no paid model API.
- Worker mutations must check live experiment status and current fencing token in their actual
  database transaction. Provider uncertainty keeps reservations until reconciled.
- Preserve canonical target digest semantics; formal source receives a distinct SHA256 binding.
- Qualification attacks execute in Linux isolation, never directly on the development Mac.

## Initial evidence and environment

- Clean baseline: 368 passed, 1 skipped, 1 deselected, 21 upstream warnings (22.99 s).
- Dedicated local Colima VM: 6 CPUs, 12 GiB RAM, 60 GiB sparse disk; aarch64 Linux
  6.8.0-117-generic, Docker 29.5.2. Only this worktree mounted, SSH agent disabled,
  active Docker context unchanged. This is a build/test environment, not a qualified worker fleet.
- Found and queued fixes: semantic target digest versus Lean-source hash mismatch; missing
  transaction-level fencing for some model tool effects; ambiguous upstream verifier exits.

## Completion record

Core implementation, cross-audits and required local proof tests are complete. The selected
physics libraries compiled, their declaration audit executed and both proof-checker modes passed
the library smoke suite. No scientific review, model credential or production qualification was
invented. Live scientific outcomes and the roadmap qualification gates remain pending.

| Check | Observed evidence |
|---|---|
| Integrated Python checks | 525 passed, 1 skipped, 3 deselected, 21 dependency warnings in 17.35 s; `pytest -m 'not integration and not lean' -q` |
| Hygiene | Ruff lint passed; 111 Python files already formatted (including the formal preparation helpers); `git diff --check` clean; infrastructure and formal source-lock validation passed |
| Real Temporal | Both opt-in tests passed against CLI 1.8.3/server 1.31.2; task/verification lifecycle, duplicate identity, initial experiment command and cancellation checked. Ten selected integration/contract tests passed in 5.92 s before seven additional passing orchestration regressions were added |
| Real PostgreSQL | Review race reproduced before locking; concurrent update correctly blocked after locking, then succeeded after commit. Sixteen acceptance/migration checks passed on pinned PostgreSQL 16.15; temporary container/network/tunnel removed |
| Real core proof checking | Nine expected outcomes in Lean mode and nine in independent nanoda mode; two positives and seven nonacceptance cases in each; 18 container removals confirmed |
| Actual physics libraries | 8,790 source build jobs completed; all 27 selected declarations checked with their Lean axiom reports; three expected library outcomes passed in Lean mode and three in nanoda mode |
| Causal diagnostic audit | All 18 archived core observations match the original source bytes and required failure diagnostics; offline checking performed no new candidate execution |
| Actual operator CLI | Private initialization, measured-image environment pin, idempotent pending target, canonical bundle and four missing-prerequisite reports passed; zero model calls and zero reviews |
| Bounded team execution | Explicitly mocked OpenAI transport over real canonical tasks/artifacts/ledger; overlapping workers, delegation, receipts, source reuse, cancellation, faults and portable context. No live throughput claim |

The real Temporal test exposed a server incompatibility missed by mocks: FAIL is not supported
by SignalWithStart. Delivery now starts with the initial command in the workflow's pending
queue and uses explicit signals only after validating an existing workflow's memo. Existing
workflow code, legacy histories and Continue-As-New remain compatible; regression tests preserve
pending commands and pre-run signals. CI now runs the real Temporal tests and PostgreSQL review
race, in addition to ordinary checks.

Independent reviews found and rechecked source/semantic digest confusion, missing theorem
selection binding, missing worker-effect fencing, stale review reuse, the PostgreSQL review
race, an assurance mismatch between model submission and lemma sharing, malformed execution
configuration accepted too late, and the Temporal startup incompatibility. These are documented
in the subsystem reports; implementations were corrected rather than papered over with success
labels. New v2 receipts/bundles are required; old receipts cannot silently inherit acceptance.

The optional process-exit probe is explicitly **blocked/incomplete**. One case reached a missing
module failure; another failed parsing before its intended behavior. A tool security filter
interrupted completion and no retry was made. Its raw diagnostics and corrected incomplete
status are retained separately and excluded from passing coverage. The original core suites are
unchanged. Negative cases now require specific diagnostic evidence, including when the overall
checker status happens to match.

The [first live-run guide](../docs/FIRST_LIVE_RUN.md) and
[versioned plan template](../examples/research_runs/plan.template.json) cover the morning inputs.
The remaining gates include an expert-reviewed problem, exact model/API/prices and resource
envelope, operator-approved execution deployment, a live accepted proof, subsequent accepted-lemma
reuse and measured live team experiments. All twelve wave qualifications remain open.

## Build failures and recovery

The initial physics-image export exhausted the 60 GiB VM data disk after source compilation.
The VM was stopped gracefully, its sparse disk expanded to 160 GiB, and the saved image layers
recovered. A thin audit layer recorded all selected declarations. The first real library proof
then exposed Lake artifact-cache writes to immutable imported artifacts. The pinned preparation
now preserves the original Physlib Lake configuration and disables only artifact-cache writes;
upstream/prepared hashes are recorded separately. An independent review confirmed that proof
sources and runtime permissions are unchanged. `--offline --no-build` confirmed all 8,790 jobs
remain current, and both actual library suites passed on the adjusted image. A Buildx stdin
archive-detection issue was also reproduced and fixed by emitting USTAR headers.

Exact recovery Dockerfiles, input identities and the failed pre-fix observation are retained in
the formal report and associated evidence. The measured recovery image is distinguished from a
fresh full build using the final recipe; no unperformed rebuild is claimed.

## GitHub handoff

Draft [PR #20](https://github.com/zubadestroyer1/PhysHarness2/pull/20) is stacked on the unmerged
foundation PR #1. Subsystem commits were created through GitHub MCP under the repository owner's
account. All five CI jobs passed the first PR revision, including two real Temporal engine tests
and the PostgreSQL race regression. The final evidence update receives its own CI run. Independent
review and the approved main-branch protections remain required; neither PR is merged here.

## Retention and VM shutdown

All four core/recovery/final image tags were exported to the ignored local file
`.state/formal/preserved-images.tar.zst`: **7,142,252,079 bytes**, SHA-256
`68188a32d08672b18336bd763d912499e9cca40e91a98c6f01e4829430c7e7b4`.
Both Docker export and compression completed successfully; the compressed archive passed
`zstd --test`. A complete restore drill was not performed. Exact image IDs and log hashes are
in [the VM lifecycle record](testing-vm-lifecycle.json).

All test containers had been removed. The dedicated Colima VM then shut down successfully;
`colima list --json` confirmed **Stopped** with its configured 6 CPUs, 12 GiB RAM and 160 GiB
data disk. No further VM work is running. Other user VM profiles were not changed. The image
archive lives in the persistent worktree so removing the temporary Colima profile will not
remove the only copy of the expensive compilation.

Final local validation after the recovery changes: 525 ordinary tests passed, 1 explicit skip,
3 integration/Lean deselections; 111 files formatted; lint and both metadata validators passed.
A separate root audit verified all 23 public physics evidence/input hashes and the six final
library container removals. Real model use, expert review and production qualification are
still pending; neither passing engineering tests nor this archive authorizes scientific acceptance.
