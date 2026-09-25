# Research-effectiveness implementation and regression trials

Status: approved implementation, audits, and both local regression trials complete. The dedicated VM is stopped and its monitor is paused. This report is not a production, fleet, or open-problem qualification.

## Implemented behavior

- Research compaction defaults to 96,000 active input tokens for the configured 128,000-token window and 16,384-token output reserve. The prior 8,192 setting is retained only as an explicit stress profile. The trials have no cumulative token cap; dollar and wall-clock envelopes remain authoritative.
- Joined helper work returns typed findings to its parent. A parent can continue investigating, then yield its slot when it ends with joined children outstanding. Compatible joined successors retain exact native context; other handoffs use canonical scientific memory. Terminal response recovery avoids repeating already-paid generation.
- Bounded working context preserves the exact target, assumptions, dependencies, active artifacts, diagnostics and obligations. Exact retained artifacts remain available. Repeated unchanged terminal reads warn and request one fresh recovery, with persistent repetition parked explicitly. This heuristic is not a measure of mathematical progress.
- The pinned isolated workbench supplies offline Lean, Mathlib/Physlib/QuantumInfo source access, exact declaration/type elaboration, scientific Python, command/file tools, and bounded rational polynomial/matrix checks. Computation does not confer proof status. Library source search is lexical; full semantic/type-directed premise ranking remains unimplemented.
- V3 checkpoints stream at most one MiB per chunk into canonical artifact storage. A validated manifest records paths, sizes, hashes, and chunk dependencies. Fresh workspaces restore checked bytes. Raw chunks remain private; failed required checkpoints retain the source and capacity for reconciliation.
- Model identity is checked before accepting provider output or tool effects. Provider compaction items are counted separately from active-input pruning. Execution state, exact-target receipt status, resource uncertainty and scientific success are reported separately.

## Validation and audit evidence

The latest post-repair host run passed 987 tests with 10 opt-in skips (21 upstream deprecation warnings). Separate real integration runs passed five Temporal tests, three PostgreSQL tests, and three pinned-image workbench checks, including the public configured factory through broker allocation and fresh restore. Ruff and formatting checks pass. The current-source verifier packet at `../pilot-qualification-2026-09-23/attempt-effectiveness-03/` satisfies all ten mechanical checks, including both kernel paths. Its production/deployment approval remains pending; prior user authorization covers this local pilot only.

Independent reports are retained under `.superpowers/sdd/2026-09-23-research-effectiveness/`: coordination-final-audit.md, workbench-cas-audit.md and pilot-ops-audit.md. Findings were returned to GPT-6 Sol implementation agents and rechecked. Their passing scope does not establish a universal absence of faults.

## Failures retained and corrected

- An initial qualification launch used the host default temporary directory, which Colima cannot mount. Docker rejected the bind before Lean ran. Repository-local scratch corrected the configuration; subsequent packets are distinct and immutable.
- Integration auditing caught incorrect provider-model attribution, missing new-tool stagnation classification, workspace policy changes silently skipping restoration, checkpoint-failure cleanup destroying source state, and private chunk sharing. Regression tests cover the corrected behavior.
- The first attempted live projection run failed in the provider input-token endpoint because a nullable object in `return_result` lacked a closed strict schema. It made zero generation requests, spent zero dollars, allocated no workspace, and retained no uncertain external work. The complete 39-tool dispatcher is now checked recursively, including nullable union arms; the real provider input-token endpoint accepted the repaired definitions. Historical records remain unchanged. A retry requires proof of zero effects and uses a fresh branch/task within the same $25 experiment budget and original deadline.

- The second launch generated one response ($0.009350), then failed before workspace provision because the requested 7,200-second lifetime exceeded the already-started experiment’s remaining time. Local allocation now records a clamped effective lifetime separately from stable policy. A real public-factory regression test covers elapsed time and fresh restoration. The settled restart preserves existing spending and the original deadline; it does not replay the old pending tool call. No VM or verification effect occurred in that failed attempt.

## Live trial contract

Two known reviewed finite-dimensional quantum targets: dephasing projection and purity loss. Exact model `gpt-6-sol`, high reasoning, Responses runtime, one active researcher slot, separate $25 target envelopes and $50 aggregate ceiling. Model costs are estimates from recorded operator prices, not provider invoices. Local VM electricity/host cost is not included. No reference proof, manual solution hint, or historical model trajectory is supplied to the fresh trials.

Both final receipts independently bind to the exact reviewed target. Both private exports passed hash validation. Experiments are paused, tasks completed, workspaces destroyed, and outstanding resource/billing reservations are zero. Historical startup faults remain visible.

## Observed live results

The fresh regression-03 root completed with one exact-target receipt at independent-kernel assurance. Total experiment model cost is $0.341800, including the $0.009350 failed startup; no cost, tokens or uncertainty remain reserved. The task is completed, the experiment is paused, and its workbench is destroyed. The private export passed integrity validation for 147 unique artifacts.

Observed tools include installed-library source lookup/search, Lean type checking, four scratch Lean checks, command execution, candidate submission and verification waiting. There were zero delegated tasks, native compaction items, pruning boundaries, or handoffs in this successful short attempt. This result supports the local proof loop and useful workbench; it does not independently validate long-horizon or multi-agent effectiveness.

| Target | Independent exact-target receipts | Recorded model cost | Generations | Scratch Lean calls | Private export |
|---|---:|---:|---:|---:|---:|
| Dephasing projection | 1 | $0.341800 | 14 including failed startup | 4 | 147 unique artifacts |
| Purity loss | 1 | $0.415102 | 15 | 6 | 148 unique artifacts |
| Total | 2 | $0.756902 | 29 | 10 | 295 across separate packages |

Each fresh successful task submitted one candidate, accepted through the independent pipeline. Neither agent received a reference proof or historical model trajectory. Both completed without native compaction, delegation, handoffs, numerical tools or stagnation recovery. Those capabilities retain their unit/integration evidence, but these short trials do not establish their live effectiveness. Total metered tokens were 355,547 across repeated model calls; this is cumulative billing usage, not peak context size.

The previous purity regression did not solve its target; this one did. The simultaneous harness changes and tiny sample do not establish which change caused the improvement, a reliable solve rate, or performance on unseen open problems. This is known-result engineering reproduction. Installed-source retrieval remains lexical plus exact declaration/type elaboration, not learned semantic premise ranking.

## Cleanup, provenance, and next evaluation

The final read-only result audit is `.superpowers/sdd/2026-09-23-research-effectiveness/live-results-audit.md`. Safe machine-readable snapshots are `projection-status.json`, `purity-status.json` and `monitor-status.json`. The current workbench evidence is `workbench-qualification-02.json`; the superseded report remains historical. Local code changes are uncommitted and have not been pushed. Prior dirty work was preserved.

Private export manifests: projection `c21fd6304d2d00de9de0927ac7e69cf1441b581eeb1dce933cae29a34c632cd1`; purity `e334d995311bb7c0f33690b687bd6a69f44880a920cb75ba15439908ff4879a0`. The old projection native session remains historically uncertain at an unexecuted tool checkpoint; the narrow restart audit proved settled model billing and no VM effect, and never replayed it. This historical native label is distinct from the current resource ledger, which has zero uncertain operations.

Colima confirmed `physharness-pilot` Stopped at the final check; all research/verifier containers had ended before shutdown. The heartbeat is PAUSED. No further model run was launched.

Recommended next evaluation: a larger, family-held-out known-result suite with matched resource budgets, followed by deliberate long-context, joined-agent and recovery trials. Measure actual feature use and compare against the minimal baseline before asserting improved long-horizon solving or increasing concurrency. Scientific semantic/novelty review, cloud recovery, 128-worker endurance and fleet qualification remain separate gates.
