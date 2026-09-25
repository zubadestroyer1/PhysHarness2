# First live pilot — 2026-09-23

**Final outcome: a model-authored projection proof is independently verified.** The autonomous loop stopped on its aggregate token cap before submitting its fourth saved candidate. The operator later submitted those exact, unchanged bytes: Lean and the independent kernel accepted them. This is a valid proof with operator-assisted final submission, not a completed autonomous workflow. It does not qualify Wave 2 or demonstrate lemma reuse.

| Item | Observed result |
| --- | --- |
| Target | Complete dephasing projection on a finite qubit state |
| Experiment | `ff884e1f-6600-40c2-a704-4072c2c163f4` |
| Model/runtime | `gpt-6-sol`, high reasoning, direct Responses runtime |
| Active attempt | Approximately 1 minute 55 seconds, from first task records to durable team report |
| Model-accounting ceiling | $25 |
| Accounted model cost | **$0.215614**; configured standard rates, not an invoice |
| Aggregate tokens | 93,963 of 96,000; 90,502 input and 3,461 output |
| Candidate submissions | 3 by the model; 1 additional exact saved candidate submitted afterward by the operator |
| Accepted proofs | **1**, from the operator-submitted unchanged fourth candidate |
| Stop | Task `BUDGET_EXHAUSTED`; token preflight could not reserve another request |
| Uncertain operations / remaining reservations | 0 / 0 |
| Pending verification / active workers | 0 / 0 |
| Reuse target | Prepared with $25 ceiling; **not launched**. Automatic compaction and the aggregate-token configuration need attention before a meaningful longer run. |

The $25 ceiling was correctly installed in new experiment records. The previous short-pilot bounds were also retained: 96,000 aggregate input-plus-output tokens, 24 turns, 16,384 output tokens per response, 1,800 seconds and one worker. Aggregate token accounting includes context resent on each request. Consequently the token allowance, not money or elapsed time, became the binding constraint. This run does not measure what the model can achieve with $25 of computation.

The three candidates submitted during the autonomous loop failed in Lean with unresolved matrix-expression goals. The comparator correctly withheld acceptance. The third candidate made progress simplifying those expressions, but still did not prove the statement. No reference solution or human-supplied proof repair was supplied to the live model. This is a known-result reproduction task, not a contamination-free discovery benchmark.

The target's intentional `sorry` placeholder appears in challenge-build logs; it is not an accepted solution. The first three receipts have assurance `none`. Follow-up receipt `d3c9db0a-a9f5-42ea-9c10-61661a0f31b3` has assurance `independent_kernel`, code `kernel_checked`, and the allowed axioms `propext`, `Quot.sound`, `Classical.choice`.

## Execution and evidence audit

- All **114** retained attempt artifacts match their content hashes.
- Receipts retain the reviewed target, candidate, challenge and environment bindings.
- All three verifier containers exited and were removed. Their diagnostics report no OOM or OOM kill. Before shutdown the VM had 11,480 MiB available out of 11,933 MiB; no swap was configured.
- Rejected proofs are reported as comparator failures; their retained Lean diagnostics identify the unresolved goals. There were no supervisor verification exceptions.
- The finite runner reported the task as blocked but left the experiment lifecycle as `queued`; its top-level `stop_reason` was null. These are reporting limitations, not proof success. The explicit task outcome records `BUDGET_EXHAUSTED`. The operator subsequently **paused** the experiment through the canonical service to prevent further allocation.
- The dedicated `physharness-pilot` VM was stopped after the autonomous run, briefly restarted solely to check the fourth saved candidate, and stopped again after that check. The scheduled monitor is paused.
- Original $5 preparations and the unsuccessful $25 attempt remain retained. No failed history was overwritten and no automatic mathematical retry was launched.

Preparation needed a small helper correction: the first check omitted two existing runtime-limit fields and failed before mutation or any paid call. The corrected helper preserves those limits, reports fixed diagnostic codes and has five passing focused tests. Its monitor also distinguishes artifact kinds from record kinds and includes snapshot timestamps. No core acceptance code was changed.

## What follows

A useful next attempt should use a fresh experiment with a larger aggregate token allowance and suitable context/turn limits while retaining the $25 ceiling and a finite time bound. That is a configuration change and should be recorded as a different experimental condition. Check per-request context length against the configured pricing tier when increasing it. A fresh run must not receive the hidden reference solution or these operator-side proof diagnostics as an extra hint.

Two small reporting improvements are also warranted: surface the specific exhausted resource in the team summary, and make terminal task state visible alongside experiment lifecycle state. They must preserve the distinction between a finished execution, a blocked task and a verified proof.

The projection now has an independent-kernel receipt. The purity-loss reuse trial remains outstanding; actual retrieval/use of the first lemma must be demonstrated separately from solving the second target.

Evidence: `projection-attempt-01-summary.json`, `final-status.json`, `final-evidence-audit.json`, `projection-attempt-01-closure.json`, and `independent-attempt-audit.md`. Full run stdout/stderr and immutable scientific artifacts remain in private local state. Launch approval provenance is in `AUTHORIZATION.md`; it is project-owner approval, not invented independent expert review.

## Operator-assisted final-candidate check

The model saved artifact `dc9e7152-f052-490c-9af1-1408dbdb7b0f` before exhaustion. Its original and checked SHA-256 are both `0fc36413e53a2ea0f599819310b15d6cd57d290710b3395f9b75ceaedbb2c762`. No source edit, reference proof, additional model call or proof hint was involved in this follow-up. The exact model-authored source is retained as `ProjectionSolution.lean`; `operator-followup-result.json` records its independent receipt. Accounted model cost remains $0.215614. The original team report is immutable and continues to describe the blocked autonomous execution.

Runtime inspection confirms that checkpoint_context and restore_context preserve and retrieve portable scientific records, but the live Responses loop appends them to the conversation like other tool results. It does not automatically replace/compact active input. Long-horizon automatic compaction remains unimplemented in this execution path, despite tested checkpoint storage.
