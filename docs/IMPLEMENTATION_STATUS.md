# Implementation evidence ledger

Updated 2026-09-15 UTC. The [approved specification](IMPLEMENTATION_PLAN.md) remains the scope.
Every wave is **unqualified**. Several components are implemented and tested; none of the live
scientific/fleet exit criteria has been substituted with a mock or a schema check.

## Recorded evidence

| Check | Observed result | What it does not establish |
|---|---|---|
| Python aggregate suite | 368 passed, 2 explicit infrastructure skips, 21 upstream deprecation warnings; Ruff lint and format checks passed | Live provider behavior or a proof kernel |
| Console tests/build | 10 tests passed; TypeScript/Vite production build passed | Large-graph capacity or full accessibility qualification |
| Browser smoke | Authenticated API connection, visible connection failure, real local campaign creation | A scientific experiment or publication |
| Temporal integration | Real pinned local Temporal CLI 1.8.3 server; 1 engine test passed after sandbox compatibility fix; duplicate-delivery contract checks passed | Temporal Cloud operation, regional failures or production scale |
| Ledger replay | 1,000 reservations/settlements with 128 local concurrent clients; 2.13 s total, p95 0.405 s | 128 live models/VMs; this used SQLite and simulated accounting only |
| Infrastructure | Terraform 1.16.2/AWS 6.10.0 validation, Compose configuration, SQLite migrations, PostgreSQL DDL | Terraform plan/apply, container boot or a live PostgreSQL migration |
| Acceptance audits | Seeded contract attacks and independent code review; reproduced defects fixed/rechecked | Universal soundness, Linux sandbox qualification or actual Lean acceptance |
| GitHub CI on Linux | [Run 34939315898](https://github.com/zubadestroyer1/PhysHarness2/actions/runs/34939315898) passed all five jobs at `156eb2b`: Python 367 passed/2 skipped/1 deselected; live PostgreSQL 1 passed; console 10 passed and built; Terraform validated; application container built and imported | Managed deployment, adversarial proof isolation, a live model/VM experiment or any complete wave qualification |

Test counts are snapshots, not a continuously updated badge. Each delivery must run a fresh
aggregate suite after integration. Local evidence reports are retained in `work/`; no credentials
or live private research transcripts belong in repository reports.

The GitHub run adds actual Linux container and PostgreSQL evidence beyond this Mac's local
checks. Its container job builds and imports the installed application; it does not start a
complete deployment or qualify generated-code containment. The PostgreSQL test exercises the
live migration/repository path; it does not establish managed-database recovery or load capacity.

## Wave progress and remaining gates

The research-loop implementation adds a real pinned Linux checker image, source-pinned
Mathlib/Physlib/QuantumInfo build, a 27-declaration source inventory, exact target/source/theorem
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

| Wave | Implemented engineering | Required before the wave can qualify |
|---|---|---|
| 0 | Repository, pinned Python/frontend environments, schemas, two program inventories, 60 provenance-bearing tiny algebra fixtures; exact formal source/toolchain locks and 27-declaration inventory | Review the recorded physics build/declaration evidence; expert review of 40 valid targets and 20 negative cases; benchmark inventory remains pending review/uncompiled |
| 1 | Trusted bundles and registry, isolated Comparator, actual Lean/nanoda engineering runs, source/theorem/review-bound receipts, causal negative-case diagnostics and PostgreSQL review locking | Production containment qualification, expert semantic-review process, and larger proof/dependency replay compatibility |
| 2 | API/CLI/MCP, typed Responses loop, canonical tool/accounting integration, finite single/team supervisor, optional VM tools, live-run preparation/preflight; standalone Codex adapter and accepted-source retrieval | Live automated accepted proof plus subsequent lemma reuse in each program; approved execution deployment and optional research skills |
| 3 | Temporal/outbox/leases/reservations, canonical VM broker with shared slots, external checkpoints, S3 adapter, E2B lifecycle and managed deployment configuration | Actual managed deployment, safe lease adoption/reconnect, uncertain-operation reconciliation, live fault injection and qualified recovery |
| 4 | Helpers/collaborators/competing branches, nested queues, sharing policy, Claude/OpenHands adapters, evidence-preserving portable memory, VM-only JS runner; mixed-SDK sandbox regressions | Mixed-runtime controller integration, automatic compaction/native continuation and safe restart integration, subscription/orphan qualification |
| 5 | Markdown/LaTeX source spans, canonical lexical/type-token search, hash-checked accepted lemma source bundles, provenance models | PDF/paper ingestion, semantic/type-directed indexing, library tracing, source-to-formal review UI, held-out applicability and accepted autoformalization |
| 6 | Uniform and experimental adaptive portfolio planning, protected attempts, strict evaluation accounting and sharing modes | Executed matched-budget comparisons; tactic/blueprint/decomposition engines, composition checks, stagnation diagnostics and measured policy promotion |
| 7 | Exact rational matrix/polynomial certificates checked in Python; numerical records; generated Lean obligations | Compile/check certificates in Lean; interval/SOS witnesses, constructive/evolutionary search and discovery-to-proof runs in both programs |
| 8 | Authenticated research console, evidence/graph/ledger views, paginated events/records, scoped snapshot exports and private local validation, CI, migration/deployment/incident guidance | Production authentication/operations, complete proof package/publication workflow, backup drills, measured latency/cancellation/recovery, 72-hour live 128-slot run |
| 9 | Bounded outbox concurrency, Temporal Continue-As-New, adapter contracts and explicit self-host qualification gates | Sharded/fair/verifier-aware scheduling, Firecracker host pool, Kubernetes/Ray deployments, alternate VM qualification and real 1,000-worker run |
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

A dedicated local Colima VM was used for real Linux builds and proof tests; its lifecycle and
final image preservation are recorded in the delivery report. Lean candidate execution stays
inside that Linux boundary, not the Mac's default environment. The temporary PostgreSQL container
and tunnel were removed after the concurrency test. Hosted-model identifiers, credentials,
qualified E2B templates, reviewed proof bundles, cloud inputs and explicit live experiment
envelopes remain operator inputs. Expert meaning/novelty decisions cannot be supplied by this
implementation agent. Use [the first live-run guide](FIRST_LIVE_RUN.md) for the pending inputs.

These are separate from engineering gaps above. Resolving credentials alone will not qualify the
system; implement and exercise the remaining contracts before promoting a wave.
