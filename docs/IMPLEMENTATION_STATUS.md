# Implementation evidence ledger

Updated 2026-09-15 UTC. The [approved specification](IMPLEMENTATION_PLAN.md) remains the scope.
Every wave is **unqualified**. Several components are implemented and tested; none of the live
scientific/fleet exit criteria has been substituted with a mock or a schema check.

## Initial development evidence

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

| Wave | Implemented engineering | Required before the wave can qualify |
|---|---|---|
| 0 | Repository, pinned Python/frontend environments, schemas, two program inventories, 60 provenance-bearing tiny algebra fixtures | Declaration-level library audit, compatible pinned Lean/Mathlib/physics build, expert review of 40 valid targets and 20 negative cases; fixtures currently pending review/uncompiled |
| 1 | Trusted bundles, isolated Comparator launcher/driver, independent-kernel policy, canonical receipts, attack tests and target review | Real pinned Linux build and kernel/adversarial runs; expert semantic-review process; complete dependency export compatibility |
| 2 | API/CLI/MCP, Responses loop and canonical tool/accounting integration, optional VM shell/file/checkpoint tools; standalone Codex adapter; accepted-source retrieval | Live automated accepted proof plus subsequent lemma reuse in each program; qualified Lean environment and optional research skills |
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

This correction run did not execute a live provider, a Lean kernel or a managed deployment.
The parallel research-loop wave has separate toolchain and engineering evidence; its results
apply to its recorded source and image hashes, not automatically to these changed verifier bytes.
Hosted-model identifiers, credentials, qualified E2B templates, Linux proof bundles, cloud
deployment inputs and explicit live experiment envelopes remain operator inputs.
Expert meaning/novelty decisions cannot be supplied by this implementation agent.

These are separate from engineering gaps above. Resolving credentials alone will not qualify the
system; implement and exercise the remaining contracts before promoting a wave.
