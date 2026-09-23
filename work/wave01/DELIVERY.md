# Wave 0/1 engineering delivery — 2026-09-15

> Historical delivery snapshot. Work resumed on 2026-09-22; see
> [the current delivery](DELIVERY-2026-09-22.md) and
> [execution ledger](RESUME-2026-09-22.md). The checks below cover
> the older 2 GiB verifier scope. The full benchmark subsequently encountered
> confirmed cgroup OOM failures. Current 8 GiB controls are reported separately;
> historical qualification does not approve the current scope.

This delivery prepares a substantive mathematical-physics benchmark and scoped verifier
evidence. Human scientific review, deployment approval and model difficulty calibration
remain pending. No hosted model was called and no fleet capacity is claimed.

## Source and review

Work is on `codex/benchmark-verifier-qualification`, stacked on the synchronized research
loop at `470a286bc2e42d839c9d3a51a885bad703e9f67e`. The initial working base was `60e8254`;
upstream acceptance, VM and console corrections were incorporated without overwriting local
work. Commits were created through GitHub MCP. [Draft PR21](https://github.com/zubadestroyer1/PhysHarness2/pull/21)
is stacked on PR20 and retains the repository's independent human review requirements.

- [Physics selection and review procedure](../../docs/PHYSICS_BENCHMARK_REVIEW.md).
- [Readable 40-target review packet](benchmark-package/REVIEW.md), with exact sources and
  evaluator references. This package is not a discovery-worker workspace.
- [Quantum author report](quantum-report.md) and [classical author report](classical-report.md).
- [Benchmark code audit](benchmark-audit.md), [qualification code audit](qualification-audit.md)
  and [verifier implementation report](verifier-report.md).

The proposed inventory has20 quantum and20 classical positives across19 mathematical
families, plus20 altered cases. Development/holdout positives are23/17; difficulty estimates
are8 foundation,26 intermediate and6 stretch. All direct library shortcuts are disclosed.
Public family holdouts do not establish unseen data or pretraining independence.

Eleven altered candidates require mechanical nonacceptance; nine are valid theorems that
change the intended physics and require a semantic hold. These categories are deliberately
separate. Kernel acceptance does not establish semantic faithfulness or novelty.

## Recorded engineering checks

| Check | Observed result | Limit |
| --- | --- | --- |
| Integrated Python suite |747 passed,1 infrastructure skip,3 integration/Lean deselections,21 upstream warnings | Model transports and many authority tests are synthetic; no live scientific run |
| Ruff | Lint passed;121 files formatted | Static checks only |
| Console |36 tests and TypeScript/Vite production build passed | No fleet or full accessibility qualification |
| GitHub CI at9f05c71 | All five jobs passed in [run35024092733](https://github.com/zubadestroyer1/PhysHarness2/actions/runs/35024092733) | Separate CI environment; not the verifier deployment |
| Fresh physics source build |8,790 jobs completed; declaration audit completed | Unchanged checker-builder stages reused; physics stages rebuilt from pinned source |
| Final image |`sha256:82497fa412f10a76e515ddc8590f1c387a8383c8b99b1cd215261f6a11151246` | Scope is this local Linux image/runtime |
| Core acceptance |9/9 expected outcomes in each of Lean and nanoda modes | Fixed controls and adverse cases, not exhaustive soundness |
| Physics library integration |3/3 expected outcomes in each mode | Oscillator identity, Pauli control and proof-hole rejection |
| Fixed containment probe |15/15 process/socket/filesystem/configuration observations | Ordinary fixed checks, not an exhaustive host attack suite |
| Scope-bound host regressions |166 passed,1 non-required PostgreSQL skip | Required individual tests passed; actual current deployment DB concurrency not rerun |
| Qualification assessment | All configured mechanical requirements satisfied | Human approval and explicit coverage gaps remain |
| New physics benchmark | Running; final evidence pending | No full acceptance claim yet |

[Build inputs](evidence/build-inputs.json) distinguish the original context from the final
context. Only the driver changed after upstream synchronization. The same consolidated
Dockerfile then reused the freshly built dependency layer and incorporated the new driver.
Actual image metadata and extracted driver bytes were compared with local source; no image
entrypoint ran during metadata capture. The final driver digest is
`0aa043a827abe8dd79960b59e3fcd3d249f5b0600e5e2c68aeb6dfb69e34445f`.

The [qualification review packet](evidence/QUALIFICATION_REVIEW.md) binds image/runtime,
current implementation, fixtures, causal outcomes, assurance and cleanup. Hashes identify
evidence; an authorized reviewer must establish collector and deployment provenance. The
packet cannot create a canonical review, claim or verification receipt.

## Failures retained and fixed

- Initial draft runs used a host temporary path not mounted in the VM. They failed before
  Lean execution. The corrected `TMPDIR` is the shared worktree's `.state/tmp`.
- A contended draft Comparator run hit the fixed110-second driver deadline during the source
  build. Its failure and cleanup remain visible. Final proof runs start after the build and
  use at most two checker slots. The deadline and output bound remain documented limits.
- Direct elaboration found notation scopes, derivative-instance conversion and matrix
  normalization errors. The authors fixed sources and repeated exact source-hash checks.
- Independent audits found family-label bypass, malformed metadata diagnostics, manifest
  approval inconsistencies, loose Lean-version matching and insufficient requested-assurance
  checks. Each was reproduced, fixed and independently rechecked.
- Upstream driver changes correctly invalidated synthetic fixtures using historical metadata.
  Only explicitly synthetic test metadata was adapted. Archived real evidence was unchanged.
- Missing local console dependencies were restored with `npm ci` before successful checks.
- Automatic approval review timed out on one read-only Docker resource inspection. Its one
  authorized retry succeeded; this was not a verifier failure. A sampled worker used738MiB of
  its2GiB limit; this single observation is not a throughput or peak-memory measurement.

Private raw logs and failed drafts remain under `.state/wave01`. The previous optional
process-exit probe remains excluded after a security filter; it was not retried. The matrix
also identifies untested host interactions, cgroup exhaustion, current-deployment database
concurrency, driver resource bounds and fresh-environment recovery review.

## Retention and next decisions

Final image preservation and VM shutdown are pending while proof testing runs. The earlier
image archive remains untouched. No successful shutdown or new archive is claimed here yet.

After engineering checks, an identified domain expert reviews every intended target and
altered case against the exact sources. An authorized deployment reviewer assesses the scoped
evidence and remaining containment/recovery gaps. Actual models then calibrate difficulty
under a frozen information policy and budget; a reviewed target and model API are still
needed for the Wave2 live proof-and-lemma-reuse demonstration.
