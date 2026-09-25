## S1 research society — 2026-09-25

**Status:** implemented; the final whole-branch review's findings are fixed. The society
is opt-in: only experiments created with a `society` policy (which requires
`sharing="ideas"`) behave differently. Legacy experiments keep their exact payloads, 63
tools, prompts, delivery shapes and exports; pinned digests guard each of these. The
evidence is deterministic and mocked-provider tests only. **No live model run, VM, image
build or E2B sandbox has exercised any society path, and no research-performance claim is
made.** See the [S1 plan](superpowers/plans/2026-09-25-s1-research-society.md) and
[PLAN.md](../PLAN.md) §7.

What exists (Tasks 1–10):
- **Commons.**
  - Attributed nodes: a platform-created goal mirroring the reviewed target, plus lemma,
    definition, conjecture, approach, tangent, obstacle, counterexample and computation
    nodes, each in its author's lab.
  - Typed edges with cycle checks, bounded query and read, and a transparent frontier
    score.
  - A status ladder that only platform code moves, apart from abandonment by the author.
- **Discourse.**
  - Expiring work claims; several branches may hold one node.
  - A thread per node, with best-effort auto-subscriptions and bounded digests that put
    urgent items first (objections to your node, and followed nodes becoming accepted or
    refuted).
- **Checks.**
  - Referees are platform-created, parentless, lab-less branches, isolated from other
    branches and assigned a different model family when one exists.
  - Informal verdicts are sound, gaps or wrong; fidelity verdicts are faithful or
    unfaithful. Ladder moves are bound to evidence: the review quorum, Lean elaboration,
    and a complete local compile of the node's exact top-level statement using only
    standard axioms. Elaboration and local compiles run in the agent-controlled workspace
    VM, so they are VM-attested evidence, not trusted platform checks; only independent
    acceptance is trusted.
  - Goal acceptance is persisted from the independent target receipt.
- **Labs.** Membership is capped, lab broadcast exists, and direct messages across labs
  are blocked by default.
- **Toolkit.**
  - A Lean session: a REPL daemon, an inline REPL on local_docker, or a one-shot fallback,
    with automation on holes and sketch-goal extraction.
  - `run_computation` with reproducibility records.
  - A literature broker: arXiv, OpenAlex and allowlisted fetch, with a benchmark
    blocklist and an overlap screen against the masked reference.
  - Ten technique skills, a constitution, check-ins and stagnation nudges.
  - The `workbench-v2` image **definition** (numerics and a pinned REPL). It is not built.
- **Society tool profile.** Twenty-five tools in all: 24 for a worker at most, and a
  read-and-check profile of 17 for a referee. The legacy tools remain as adapters. The
  finite runner runs referee tasks, synthesis tasks without a parent branch, and the
  reviews those platform-rooted tasks request.
- **Task 10.**
  - A no-model end-to-end simulation (three agents plus referees, through the tool
    dispatchers).
  - `tools/society_metrics.py` for the PLAN §9 metrics.
  - Society exports now carry commons nodes, claims, reviews, literature fetches and
    edges.
  - `RunPlan` has an optional society policy, and the preflight blocks benchmark mode
    without its masked reference.
  - The [S1 live-run plan](../work/society-s1/RUN_PLAN.md) and an example society-arm
    manifest.
  - The simulation found one integration gap: nodes did not record their author's lab.
    It is fixed, with a regression test.
- **Final review fixes.** Local compiles count only for the node's real top-level
  theorem (comments, strings, namespaces and forged one-shot axiom lines no longer
  count); referees get a read-and-check profile, and reviews requested from
  platform-rooted lineages run; own and claimed node threads survive the subscription
  cap. Minor fixes: infrastructure failures never demote a node, one withheld-source
  reason code, batched hole elaboration, benchmark refusal of search pages, and an
  opt-in PostgreSQL commons smoke in CI.
- **Residual fixes after the final review.**
  - The one-shot Lean fallback reads `#print axioms` from `lean --json`, because plain
    `lean` prints those reports without a position. A complete proof is now reported
    complete, so `compiles_locally` is reachable on images without the REPL. This was
    checked against real Lean 4.32 and 4.33.
  - Referees get referee-specific norms, check-ins, nudges and skill lists, which name
    only the tools they have.
  - In society profiles, a call to an unregistered tool name is a recoverable rejection
    rather than a fatal error. Repeating such a call trips the stagnation detector.
- **Tests.** The full suite passes 1,573 tests with 2 opt-in PostgreSQL skips (1,258
  before S1). Ruff check and format are clean.

Deferred by design:
- node-level independent acceptance (the `accepted` status for non-root nodes);
- the root fidelity ensemble before launch;
- background computation jobs and Ray;
- general web search, which needs a paid search API key;
- the attention allocator with reserves, fresh-eyes reseeding, synthesizer and maintainer
  agents, and an automated stagnation stop;
- hierarchical budgets and model tiers.

In S1, `refuted` has no platform path.

Needs user approval before the live 8–16 agent comparison ([RUN_PLAN §8](../work/society-s1/RUN_PLAN.md#8-prerequisites-and-approvals)):
- the budget;
- the choice of target (candidates are proposed) and its masked reference;
- the tool-matching design;
- the two model families (both on the Responses runtime);
- the workbench v2 rebuild and qualification (every `TODO(pin-at-rebuild)` resolved);
- verifier bundle registration for the chosen target;
- the choice between E2B and local_docker, and a larger VM for concurrency 12.

## Persistent-swarm hardening — 2026-09-25

The four fix groups from the harder-target audit are implemented with deterministic regressions.
- **Work coordination:** FIFO scheduling within round-robin roots, revision-fenced amendment of queued objectives, current objectives at lease time, a component ownership registry, honest delivery states (including `recipient_unavailable`), peer availability, durable peer waits that release capacity, and exact-target stop with bounded drain.
- **Durable knowledge:** chunked native checkpoints. Across 96 real checkpoints from the retry, unique payload fell 93% and every checkpoint restored exactly.
- **Execution efficiency:** direct workspace-file submission, event-based waits, and bounded wrap-up.
- **Research resilience:** finite root replans, optional strategy descriptions, and a three-handoff evidence-status regression.

The suite passes 1,258 tests (16 opt-in skips); ruff check and format are clean. The only real-VM evidence is the earlier bounded file-capture check. No live swarm, fleet or wave qualification is claimed. See the [delivery report and limits](../work/swarm-hardening-2026-09-25/DELIVERY.md). The proposed research-society direction, a draft under review, is in [PLAN.md](../PLAN.md).

## Harder nonlinear-physics qualification — 2026-09-24

A fresh four-worker retry completed cleanly on a substantially longer known-type nonlinear Duffing-network energy target: one exact-target proof accepted by Comparator, Lean and Nanoda after 17m03s, two roots plus four model-requested helpers, and observed helper-source reuse in the accepted proof. All six tasks/sessions completed; 3,246 exported artifacts and native usage reconciled. Conservative retry usage was $49.102475 under the user's explicit $100 live amendment. All three attempts in this round, including an earlier faulted-but-proved run, total $92.305730; prior historical usage remains separately recorded. This is not a novelty, human expert publication or fleet qualification claim.

Pure workspace path validation now occurs before external-operation reservations and yields correctable model errors; genuine post-dispatch uncertainty still blocks. Durable repeated-continuation lineage and settled-compaction crash recovery have deterministic tests, and the earlier successful root continued through one real native compaction. The final retry had no compaction or handoff. The frozen main suite passed 1,194 tests (14 opt-in skips, 21 upstream warnings), with two additional standalone operator budget-amendment tests passing. A real Docker path-recovery regression and four-worker/verification/restore qualification passed separately. The dedicated VM is stopped and monitor paused. No changes or private results were pushed. See the [full outcome, faults and limits](../work/hardening-final-2026-09-24/REPORT.md). Next: measured 8–16-worker recovery/coordination qualification; the current single-team concurrency schema is capped at 100, so 128 requires a reviewed change and real endurance evidence.

## Source retrieval repair — 2026-09-24

The live-pilot search/read mismatch is now fixed: search returns canonical lookup-ready paths and separate absolute provenance; lookup preserves those paths and rejects malformed input explicitly. Root verification passed 1,097 full-suite tests (8 opt-in skips), plus 13 focused tests with the actual pinned VM libraries; lint and diff checks passed. No new model experiment was launched. See the [repair evidence](../work/source-lookup-fix-2026-09-24/DELIVERY.md) and [next-problem recommendation](../work/next-physics-problem-2026-09-24/RECOMMENDATION.md). Earlier pilot findings below describe the pre-fix revision.

## Parallel collaboration pilot — 2026-09-24

Capacity and dispatch checks now support two real simultaneous proof workbenches on the dedicated 16 GiB VM. Budget contention waits for confirmed reservations; unexpectedly large settlements retain actual usage and block new allocations. The full frozen suite passed 1,080 tests; seven opt-in skips were covered separately by PostgreSQL and real-VM checks. Fresh verifier qualification and both strengthened target controls passed.

The four-arm GPT-6 Sol pilot completed: both targets were independently verified in both sharing configurations, with nine accepted candidates and a conservative model-cost total of $3.658018 including the probe (within $100 authorized). First proofs took 67–93 seconds; no output limits, compactions, handoffs, or peer messages occurred. These targets were too short to qualify long-horizon collaboration. The audit found a source-search/read path mismatch still requiring repair; a post-run delegation counter correction passed its regression. Exact target review was assistant-led under explicit delegation, not independent human expert review or publication approval. All four experiments are paused, exports passed artifact integrity checks, the VM is stopped and monitor paused. See the [full results and limitations](../work/parallel-pilot-2026-09-24/REPORT.md).

# Implementation evidence ledger

## Next collaboration pilot preparation

Two step-up known-result targets (Bell-state entanglement/marginal and damped-oscillator
energy nonincrease) have exact pending-review bundles and four unstarted comparison
experiments. Fresh preparation checks passed 46 pipeline tests and eight expected kernel
outcomes. A real VM probe confirmed a launch blocker: the local provider permits only one
active workbench, and the current preflight does not compare requested team concurrency
with that physical limit. The proposed two-worker live test is **not ready** until the
capacity/preflight change is qualified and new target/launch reviews are completed.
No runtime source changed and no model API calls were made; the VM is stopped. See the
[preparation and audit report](../work/collaboration-pilot-preparation-2026-09-23/README.md).

## Current research-network implementation

The [research-network plan](superpowers/plans/2026-09-23-research-network.md) is implemented:
atomic portfolios and recruitment, opt-in researcher/team discovery, attributed discussions,
a durable unified inbox, optional sampled synthesis, and shared admission/fair local dispatch.
Responses checkpoints incoming peer data before acknowledgement; other runtimes use manual
tools. Independent audit findings were repaired and rechecked. Fresh validation reports
1,044 Python passes with PostgreSQL and Temporal enabled, 50 final network passes, and three
separately run real VM passes. The refreshed verifier packet satisfies ten mechanical checks
with 24 expected kernel outcomes and 16 boundary checks. See the
[delivery report](../work/research-network-2026-09-23/DELIVERY.md) and
[operator guide](RESEARCH_NETWORK.md). The 128-task queue replay used only two mock workers;
scientific effectiveness and live fleet scale remain unqualified. No live research model
API experiment was run. The dedicated VM is stopped.

## Current research-effectiveness regression

The [research-effectiveness plan](superpowers/plans/2026-09-23-research-effectiveness.md) adds research-sized compaction, joined delegation, bounded scientific context, isolated Lean/scientific workbenches, and streamed checkpoint restoration. Current implementation checks pass: 987 host tests (10 opt-in skips) and three dedicated-VM workbench checks. Independent reviews and current-source verifier evidence are recorded in the [delivery report](../work/research-effectiveness-2026-09-23/DELIVERY.md). Two startup faults were found and repaired. Both fresh known-result tasks now have exact-target, independent-kernel accepted proofs. Total recorded model cost is $0.756902, including the failed startup, within the original two $25 envelopes. Both exports passed artifact integrity checks, experiments are paused with no resource uncertainty, and the dedicated VM is stopped and monitor paused. These short trials did not exercise compaction or delegation; they do not qualify production, fleet capacity, or any complete wave.

Updated 2026-09-23 UTC. The [approved specification](IMPLEMENTATION_PLAN.md) remains the scope.
Every wave is **unqualified**. Several components are implemented and tested; none of the live
scientific/fleet exit criteria has been substituted with a mock or a schema check.
The [current Wave 0/1 delivery](../work/wave01/DELIVERY-2026-09-22.md) records the
final 8 GiB control evidence and completed physics reports in both kernel modes.

## 2026-09-23 long-horizon implementation and live trials

The [continuation plan](superpowers/plans/2026-09-23-durable-research-continuation.md) now has implemented native Responses compaction, immutable discarded-history archives, bounded exact scientific context and retrieval, attributed handoff notes, fenced continuation tickets, shared descendant accounting, workspace restoration contracts, and settled-checkpoint recovery. Public HTTP/client/MCP tools expose scientific memory without exposing native session archives. Independent acceptance remains separate from model-authored summaries and task completion.

The [current evidence ledger](../work/long-horizon-2026-09-23/LEDGER.md) records 894 ordinary Python tests, 5 real local Temporal tests, 3 real PostgreSQL tests, 36 frontend tests/build, Terraform validation and application container smoke. The [final scoped verifier packet](../work/pilot-qualification-2026-09-23/attempt-long-horizon-03/QUALIFICATION_REVIEW.md) satisfies all ten mechanical checks. These observations supersede earlier source snapshots only within their stated scope.

The first fresh known-result trial completed autonomously: two accepted submissions through independent kernels, 42 native compactions, one delegated task and $3.419262 recorded model usage. The second trial made nine rejected submissions and 77 native compactions, then stopped at its shared token admission limit without an accepted proof ($7.878868). A misleading local budget error code found in terminal audit was corrected, independently audited and regression-tested. Both experiments are quiescent; the dedicated VM is stopped and the monitor paused. See the [delivery report](../work/long-horizon-2026-09-23/DELIVERY.md). These are local engineering/reproduction tests with deliberately aggressive compaction, not open-problem success, production deployment approval, E2B recovery qualification or fleet/endurance evidence. Expert semantic/novelty and broader wave exit gates remain separate.

## 2026-09-23 pilot preparation evidence

The fresh [pilot qualification packet](../work/pilot-qualification-2026-09-23/attempt-01/QUALIFICATION_REVIEW.md) binds current source scope `f13defb821a8043a16978a83058abd1e6f7cbed8a60bd36549fb647efe3cd70f` to the restored consolidated image and dedicated Linux runtime. All ten automatic checks are mechanically satisfied: 24/24 core and library cases across both kernel modes, 16/16 fixed boundary observations, and all 56 required host regressions passed within a JUnit run of 226 passes and one conditional PostgreSQL skip. The [independent audit](../work/pilot-qualification-2026-09-23/independent-audit.md) rechecked the packet and the separate selected-target fixture reports, which accepted two known reference proofs and rejected one alteration in each mode. The [retention record](../work/pilot-qualification-2026-09-23/retention-and-shutdown.json) confirms the named persistent VM retained the exact image across restart and was stopped after collection. These are engineering observations. Deployment approval, target scientific review, live agent proofs, and wave qualification remain pending; see the [pilot preparation review](../work/first-pilot-review.md).

## Initial development evidence

| Check | Observed result | What it does not establish |
|---|---|---|
| Research-loop Python aggregate | 525 passed, 1 explicit infrastructure skip, 3 integration/Lean deselections, 21 upstream warnings locally; Ruff lint and formatting passed | Live provider behavior or a proof kernel |
| Console tests/build | 10 tests passed; TypeScript/Vite production build passed | Large-graph capacity or full accessibility qualification |
| Browser smoke | Authenticated API connection, visible connection failure, real local campaign creation | A scientific experiment or publication |
| Temporal integration | Both real engine tests passed with CLI 1.8.3/server 1.31.2; startup, task/verification lifecycle, duplicate identity and cancellation exercised | Temporal Cloud operation, regional failures or production scale |
| Ledger replay | 1,000 reservations/settlements with 128 local concurrent clients; 2.13 s total, p95 0.405 s | 128 live models/VMs; this used SQLite and simulated accounting only |
| Infrastructure | Terraform 1.16.2/AWS 6.10.0 validation, Compose configuration, SQLite migrations, real PostgreSQL 16.15 migration and acceptance review-lock regression | Terraform plan/apply, managed recovery or fleet capacity |
| Acceptance audits | Seeded contract attacks, independent code reviews and 9 + 9 real core Lean/nanoda engineering outcomes; reproduced defects fixed/rechecked | Universal soundness, production containment qualification or expert-reviewed physics |
| GitHub CI on Linux | [Research-loop run 34947302989](https://github.com/zubadestroyer1/PhysHarness2/actions/runs/34947302989) passed all five jobs at `0668f862`: ordinary Python 524 passed/2 skipped/3 deselected, plus 2 actual Temporal tests; PostgreSQL, console, Terraform and application container checks passed | Managed deployment, production adversarial isolation, live model throughput or any complete wave qualification |

Test counts are snapshots, not a continuously updated badge. Each delivery must run a fresh
aggregate suite after integration. Local evidence reports are retained in `work/`; no credentials
or live private research transcripts belong in repository reports.

The GitHub run adds actual Linux container and PostgreSQL evidence beyond this Mac's local
checks. Its container job builds and imports the installed application; it does not start a
complete deployment or qualify generated-code containment. The PostgreSQL test exercises the
live migration/repository path; it does not establish managed-database recovery or load capacity.

## PR #1 correction evidence

At source `207e013`, the fresh local aggregate reports **482 Python tests passed, 2 explicit
skips and 21 upstream warnings**; Ruff lint/format (96 files), deployment metadata and whitespace
checks passed. Supported Node 24.19.0 reports **36 console tests passed** and a successful
TypeScript/Vite build. Browser smoke covered canonical controls, selected state and accounting.

The corrected source combined with the committed research-loop wave (`60e8254`) reports
**639 Python tests passed, 4 explicit infrastructure skips and 21 upstream warnings**;
Ruff passed for 112 files. All original review findings and additional scoped review findings
were corrected and re-reviewed. See the [correction report](../work/pr-1-fix-validation.md) for
reproductions, exact source/integration identities, query/read measurements, compatibility
resolutions and remaining costs. Current head CI and required independent approval are tracked
on [PR #1](https://github.com/zubadestroyer1/PhysHarness2/pull/1).

Comparator v2 requires separately pinned canonical target/source identities and the reviewed
theorem. Old ambiguous manifests/receipts require explicit repinning/resubmission. The new
immutable migration adds ordered visibility/receipt indexes; it does not alter revision 0001.
These corrections do not extend historical kernel/provider evidence to changed source bytes.

## Wave progress and remaining gates

The research-loop implementation adds a real pinned Linux checker image, source-pinned
Mathlib/Physlib/QuantumInfo build, a 27-declaration source inventory and actual Lean axiom report, exact target/source/theorem
and review binding, multiple trusted target bundles, typed live-run preparation, and a bounded
canonical team runner. The current delivery evidence is in
[the implementation record](../work/research-loop-implementation.md),
[formal environment report](../work/formal-environment-report.md),
[acceptance report](../work/acceptance-integration-report.md), and
[execution report](../work/research-execution-report.md).

- Real core image: two algebraic positive cases and seven seeded nonacceptance cases passed
  with Lean replay, and again with nanoda independent replay. All 18 observations also passed
  an offline causal-diagnostic audit. These are engineering observations, not expert-reviewed
  physics or complete containment qualification.
- The selected physics build completed 8,790 jobs. Lean checked all 27 selected declarations
  and reported their axioms. A separate library suite passed all three expected outcomes in
  both Lean and nanoda modes: oscillator identity, Pauli-X involution and incomplete-proof
  rejection. This does not provide expert semantic review or qualify the 60 benchmark entries.
- A PostgreSQL concurrency test reproduced a review update crossing receipt creation; the
  row-lock fix passed the live regression and adjacent migration/integration checks.
- Real Temporal tests exercise task completion, blocked verification, duplicate identity,
  experiment startup and cancellation. The engine rejected the initial signal-with-start
  conflict-policy implementation; the corrected ordinary-start path passed.
- Real local CLI preparation using measured image metadata produced a pending target and
  immutable bundle. Preflight reported all four missing scientific/live inputs; no review or
  model call was created.
- Model transport/coordination tests remain explicitly mocked. They cover overlapping workers,
  delegation, canonical receipt waiting/reuse, fencing, cancellation, uncertain calls and context
  preservation. They do not establish live scientific throughput or a qualified fleet.
- Optional additional initializer-probe coverage is blocked/incomplete and excluded from pass
  counts. An unrelated syntax error cannot satisfy a negative case's required causal diagnosis.
- Wave 0 now contains 40 proposed real physics targets and 20 altered cases (11 mechanical
  nonacceptance controls and nine valid semantic-hold controls), separate from the tiny algebra
  controls. Their references were historically elaborated, but scientific human review,
  calibration and contamination decisions remain pending.
- Wave 1 resource enforcement and qualification parsing have current 8 GiB control evidence:
  image `sha256:84deccc518a7aa5ce916d15236dac5ae416a5288449bd8620a2c8bb374c24b67`,
  final scope `e8f8c011e29242aa16f7464522b061545ac189f392c729655c57183a578ddb42`,
  24/24 core/library expected outcomes across both modes, and 16/16 fixed boundary
  observations. All 10 automatic qualification checks were mechanically satisfied;
  production approval and scientific review remain pending. Both 60-case physics
  modes passed all expected outcomes: per mode, 40 positive references verified,
  11 mechanical controls blocked, and nine valid semantic controls mechanically
  verified but expert-held. The independent audit matched the stored full-suite
  assessment without discrepancies; older 2 GiB reports are historical only.
  The recorded 8 GiB scope also predates the combined PR #1/#20 and assessor changes;
  its automatic checks are historical. The fresh current-source pilot control run
  is recorded above and still requires authorized deployment review.
  [CI run 35796735015](https://github.com/zubadestroyer1/PhysHarness2/actions/runs/35796735015)
  passed all five jobs at `a58b94d`.

| Wave | Implemented engineering | Required before the wave can qualify |
|---|---|---|
| 0 | Repository, pinned environments and schemas, 40 proposed real physics targets and 20 altered cases (11 mechanical nonacceptance, nine valid semantic-hold) with historically elaborated references, separate from tiny algebra controls; exact formal source/toolchain locks and 27-declaration inventory | Human review and calibration of the 40 targets and 20 altered cases, including fidelity, difficulty, contamination and holdouts |
| 1 | Trusted bundles and registry, isolated Comparator, actual Lean/nanoda engineering runs, source/theorem/review-bound receipts, causal negative-case diagnostics and PostgreSQL review locking | Production containment qualification, expert semantic-review process, and larger proof/dependency replay compatibility |
| 2 | API/CLI/MCP, typed Responses loop, canonical tool/accounting integration, finite single/team supervisor, optional VM tools, live-run preparation/preflight; standalone Codex adapter and accepted-source retrieval | Live automated accepted proof plus subsequent lemma reuse in each program; approved execution deployment and optional research skills |
| 3 | Temporal/outbox/leases/reservations, canonical VM broker with shared slots, external checkpoints, S3 adapter, E2B lifecycle and managed deployment configuration | Actual managed deployment, safe lease adoption/reconnect, uncertain-operation reconciliation, live fault injection and qualified recovery |
| 4 | Helpers/collaborators/competing branches, nested queues, sharing policy, Claude/OpenHands adapters, evidence-preserving portable memory, VM-only JS runner; mixed-SDK sandbox regressions | Mixed-runtime controller integration, automatic compaction/native continuation and safe restart integration, subscription/orphan qualification |
| 5 | Markdown/LaTeX source spans, canonical lexical/type-token search, hash-checked accepted lemma source bundles, provenance models | PDF/paper ingestion, semantic/type-directed indexing, library tracing, source-to-formal review UI, held-out applicability and accepted autoformalization |
| 6 | Uniform and experimental adaptive portfolio planning, protected attempts, strict evaluation accounting and sharing modes | Executed matched-budget comparisons; tactic/blueprint/decomposition engines, composition checks, stagnation diagnostics and measured policy promotion |
| 7 | Exact rational matrix/polynomial certificates checked in Python; numerical records; generated Lean obligations | Compile/check certificates in Lean; interval/SOS witnesses, constructive/evolutionary search and discovery-to-proof runs in both programs |
| 8 | Authenticated research console, evidence/graph/ledger views, paginated events/records, scoped snapshot exports and private local validation, CI, migration/deployment/incident guidance | Production authentication/operations, complete proof package/publication workflow, backup drills, measured latency/cancellation/recovery, 72-hour live 128-slot run |
| 9 | Bounded outbox concurrency, Temporal Continue-As-New, adapter contracts and explicit self-host qualification gates | Sharded/fair/verifier-aware scheduling, self-hosted VM isolation and Kubernetes/Ray paths based on measured need, alternate VM qualification and real 1,000-worker run; evaluate existing lifecycle controllers and isolation before deciding whether a custom Firecracker host pool is warranted |
| 10 | Licensed canonical dataset pipeline, family/content holdouts, fitted retriever variant, held-out promotion and rollback contracts | Demonstrated held-out benefit, training recipe on real accepted data, open-weight proof-policy adaptation, test-time training/RL, exploitation/regression evaluation |
| 11 | Campaign/problem records and dual program registries | Expert-selected novel targets, library readiness, diverse sustained groups, week/month operation and independently checked nontrivial new results |

## Fault and authority policy

- An exception, timeout, unsupported backend or missing credential produces a coded failure or
  blocked state. It never becomes a successful empty result.
- Configuration errors omit authentication values and secret dictionary keys. API faults carry
  operation IDs; server logs retain a traceback for diagnosis. Do not paste secret-bearing raw
  provider data into public issues.
- Target/definition changes create explicit revisions. A receipt applies to its recorded target,
  environment and artifact. Publication assurance cannot silently downgrade.
- Worker-authored receipt JSON, proof status, provenance flags and graph labels cannot promote
  results. Tests with synthetic checker outcomes are explicitly fixtures.
- `none`, `verified` and `ideas` sharing are enforced on reads, history, messages and native-state
  access. A model's branch identity is issued by the controller, never taken from its tool text.
- Uncertain paid operations retain reservations until reconciled. A local cancellation does not
  prove provider billing or remote work stopped. VM allocations must be tracked even on failure.
- Confirmed VM destruction releases capacity while preserving unknown invoice cost. Pending or
  failed destruction retains identity and capacity. Slow checkpoint uploads recheck task fences
  before canonical issuance; expired ownership never receives successful publication.
- Optional SDKs cannot silently disable Temporal restrictions or replace application logging.
  Mixed-import regressions cover the pinned OpenHands/Beartype compatibility configuration.
- A fresh qualification run replaces any prior passed report before preflight. Partial results
  remain attached to the current failed run. Impossible timing/concurrency measurements fail.

## Environmental and publication blockers

The PR #1 correction run did not execute a live provider, a Lean kernel or a managed deployment.
The wave observations below apply to their recorded source/image hashes; changed verifier bytes
require a separate rebuild, rerun and repinning.

A dedicated local Colima VM was used for real Linux builds and proof tests. Both the current
and historical images were archived with a recorded SHA-256 and passing `zstd -t`; the
VM was observed stopped on 2026-09-22. A fresh-VM restore and exact image retention
through a restart were later observed for the pilot above. Details of the earlier build are
in the [current delivery](../work/wave01/DELIVERY-2026-09-22.md). Lean candidate execution stays
inside that Linux boundary, not the Mac's default environment. The temporary PostgreSQL container
and tunnel were removed after the concurrency test. Hosted-model identifiers, credentials,
qualified E2B templates, reviewed proof bundles, cloud inputs and explicit live experiment
envelopes remain operator inputs. Expert meaning/novelty decisions cannot be supplied by this
implementation agent. Use [the first live-run guide](FIRST_LIVE_RUN.md) for the pending inputs.

The historical VM used temporary Colima metadata. Future provisioning must set `COLIMA_HOME` to
persistent user-owned storage such as `$HOME/.local/share/physharness-colima`. During recovery,
check the Docker endpoint and host agent directly; `colima status` cannot establish absence after
temporary metadata is lost.

These are separate from engineering gaps above. Resolving credentials alone will not qualify the
system; implement and exercise the remaining contracts before promoting a wave.
