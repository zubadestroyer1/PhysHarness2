# Long-horizon implementation and local qualification — 2026-09-23

Status: implementation, independent audit, available local checks and both live tests are complete. One of two physics targets was accepted. The dedicated VM is stopped and the monitor paused. All changes are local in the existing `codex/benchmark-verifier-qualification` worktree; this task has not published or merged them.

## Delivered behavior

- **Exact scientific memory and retrieval:** bounded working views retain the canonical target, review, task and environment; explicitly partial, paginated indices expose outstanding tasks, failures and accepted claims. Scientific records and original artifact bytes remain retrievable with scope, revision and hash checks. Graph fanout and response size have explicit bounds. A compressed summary cannot change assumptions or confer verification.
- **Native compaction:** the Responses runtime accepts provider compaction objects, preserves opaque native state privately, archives the exact discarded history immutably and retains call/result pairing. Each compaction receives a fresh authoritative scientific anchor. Active context, cumulative tokens and shared dollar spending are distinct limits. Provider usage never resets with context.
- **Fresh continuation and collaboration:** helpers, competing branches, waiting parents, durable research notes and explicit handoff tickets use the same experiment resource authority. A waiting parent releases capacity; a successor receives a new fenced execution identity. Unverified notes remain attributed and are checked against current target/review/environment revisions.
- **Durable execution:** model reservations and their task bindings commit atomically. Settled checkpoints can recover after process loss; completed native output can finalize without a second model call. Uncertain external effects require reconciliation instead of blind replay. Continuation issuance and source-slot release are atomic; workspace archives persist before destruction and restore under a new identity. Local Temporal tests exercise a lost activity reply after committed handoff.
- **Acceptance and visibility:** candidate storage/submission is a durable operation. Already queued verification drains after generation stops. Task completion, proof acceptance, expert review and publication assurance remain separate. Generic agent APIs cannot expose native session archives, even for the same branch. HTTP, Python client and MCP expose bounded scientific retrieval and coordination tools.

The [design](../../docs/superpowers/specs/2026-09-23-durable-research-continuation.md), [implementation plan](../../docs/superpowers/plans/2026-09-23-durable-research-continuation.md), [audit](final-integration-audit.md) and [working ledger](LEDGER.md) retain decisions, fault windows and corrective work.

## Engineering checks

| Check | Observed result | Evidence |
|---|---|---|
| Final ordinary Python suite | 894 passed, 1 skipped, 6 deselected, 21 warnings | `full-python-delivery.log` |
| Real local Temporal | 5 passed; canonical continuation after lost activity reply | `temporal-final.log` |
| Real PostgreSQL | 3 passed; migrations and acceptance transactions | `postgresql-final.log` |
| Frontend | 36 tests passed; production build passed | `console-tests.log`, `console-build.log` |
| Lint/format | Passed; 131 files formatted | `ruff-delivery-ci.log` |
| Infra/source metadata | Passed | `metadata-final.log`, `formal-lock-final.log` |
| Terraform 1.16.2 | Locked-provider initialization and validation passed; no deployment | `terraform-init.log`, `terraform-validate.log` |
| Application image | Built; imports passed with network disabled | `container-build.log` |
| Current verifier | All 10 mechanical qualification checks satisfied | `../pilot-qualification-2026-09-23/attempt-long-horizon-03/` |

The final verifier scope is `8b06e5b17727e25d8b003e5c943b92ed2f61ecdb94e2b950db74d7cc2d5971e1`. The pinned formal image is `sha256:84deccc518a7aa5ce916d15236dac5ae416a5288449bd8620a2c8bb374c24b67`. Comparator and nanoda run inside the dedicated Linux VM. Qualification includes 24 core/library observations across both kernel modes and 16 fixed-boundary observations. The immutable mechanical packet does **not** grant production/deployment or expert scientific approval.

Earlier failures are retained: the first collector launch lacked a VM-mounted scratch directory and failed with Docker exit 125; the corrected launch and final-source rerun passed. An intermediate Python run exposed stricter native-privacy expectations, and an intermediate Temporal run exposed a continuation payload type guard. Both were corrected and independently rechecked. Historical failed logs are not erased.

## Live protocol and interpretation

Two previously reviewed finite-dimensional quantum targets use `gpt-6-sol`, high reasoning, the Responses runtime, two concurrent slots per experiment, a separate $25 envelope each, a 128,000-token active context ceiling and a 4,000,000-token cumulative ceiling. Native compaction is deliberately triggered at 8,192 tokens to exercise the implementation during short tests. This aggressive setting is not a recommended optimum or evidence that repeated compaction preserves arbitrary research performance.

A fresh private database imported only the two exact campaign/problem/review records (six records total). The first run had no prior accepted proof or model transcript. The second can retrieve newly accepted first-run artifacts under the recorded sharing policy. Existing target review is project-owner launch approval, not a newly invented independent expert review. Both targets are known results; neither establishes novelty or uncontaminated discovery.

| Attempt | Runner outcome | Accepted submissions | Native compactions | Delegated tasks | Model cost estimate |
|---|---|---:|---:|---:|---:|
| Projection `fcacc4fd-148c-4d8f-b614-0ca5ca9b76e8` | Completed autonomously | 2 | 42 | 1 | $3.419262 |
| Purity `041d11ee-e488-45f5-863f-41cc58c5a67d` | Blocked at shared token admission; no accepted proof | 0 | 77 | 2 | $7.878868 |

Projection consumed 1,674,571 cumulative input/output tokens. Three candidates were rejected before two submissions obtained independent-kernel receipts. These are two proofs of the same reviewed target, not two newly solved problems. No operator submitted a candidate for the new run. Allowed axioms in accepted receipts were exactly `propext`, `Quot.sound`, `Classical.choice`. All projection reservations settled; no uncertain operations remained.

The live loop uses locally isolated Linux acceptance tooling, not a live E2B research workspace. Workspace migration is covered by provider contract tests, not a real E2B snapshot/restore. Scientific tool use and successful formal reuse are different measurements. The second run made three knowledge queries; none returned a first-run accepted claim/artifact reference in the measured tool outputs. Formal lemma reuse is therefore not demonstrated by this pair. No fresh-session handoff occurred in either live attempt; handoff correctness has local/fake-provider and real-Temporal evidence, not yet live-model handoff evidence.

## Remaining qualification boundaries

Managed cloud deployment, live E2B recovery, killed processes during in-flight provider requests, 128/1,000-worker endurance, month-long performance and open-problem discovery remain unqualified. Provider billing is a recorded estimate, not an invoice guarantee. The finite team runner reports completion separately from the experiment lifecycle, which remains queued until an operator pauses it; receipt acceptance does not automatically stop all research. This is bounded by task/runtime/token/dollar ceilings, but an acceptance-aware stopping policy remains a future configurable optimization.

Private logs, exact native archives and reproduction exports remain under `.state/long-horizon-2026-09-23/private/`. They must not be committed or published as routine progress reports. Public evidence contains hashes, statuses, resource totals and limitations only.

## Observed performance issue

The purity run repeatedly inspected terminal blocked receipts. A mid-run audit found 46 inspections returning blocked and only one returning queued; these were not waiting on the VM. The associated rejected candidates reported unsolved Lean goals or unknown constants, with no OOM and successful container cleanup. No source changes, injected proof hints, hidden reference solutions or manual submissions were used to rescue the live attempt.

This suggests measuring compaction thresholds and repeated-read behavior before promoting a default research policy. It does not isolate a causal explanation: the run is a single stochastic sample with aggressive compaction and limited library-exploration tools. Bounded exact memory prevents loss or mislabeling of canonical evidence; it does not guarantee that a model retrieves or uses it effectively. A matched-budget comparison with a less aggressive threshold and richer library tools is still needed.

## Terminal audit and cleanup

Purity consumed 3,876,074 cumulative tokens. The next conservative reservation (128,000 input plus 16,384 output tokens) would exceed its 4,000,000-token test envelope, so it was denied before a provider generation. Two tasks completed their research reports; a third was blocked. All nine submitted candidates remained blocked by proof compilation, and no proof acceptance is claimed. Total recorded model usage across both attempts is **$11.298130**. Neither $25 dollar ceiling was reached; the cumulative token envelope is a separate configurable limit, not the active context window.

The terminal audit found a **diagnostic defect**: the local token-budget error was wrapped as `PROVIDER_FAILED`. The preserved private exception chain confirms the local budget refusal; there was no corresponding sent generation, uncertainty or VM failure. The fix maps only the expected token/cost admission errors into typed runtime errors, retaining their codes and safe messages. Tests reproduce both refusals with zero provider create calls, no leaked reservations and exact per-task/failure-artifact codes. Original live records retain their original code; they were not rewritten to make the historical run appear clean. This is a corrected reporting defect, not a new successful physics result. No additional paid retry was needed to test a deterministic local admission failure.

The two experiments were paused after their runners terminated. Both have zero active workers, reserved dollars, reserved tokens and uncertain operations. The 675 projection and 1,167 purity artifact records were independently hash-checked (28,520,046 and 51,604,645 unique content bytes respectively). Private manifest exports and a consistent SQLite backup preserve the investigation; a standalone clean-machine rebuild of the whole exported investigation was not separately exercised.

Before shutdown only the disposable PostgreSQL test container remained; every live proof-checker container had been removed. VM memory was 535 MiB used / 11,933 MiB total with 11,397 MiB available, and no live receipt reported an OOM. The disposable database container was removed, dedicated `physharness-pilot` VM stopped, Docker endpoint confirmed unavailable, database tunnel confirmed closed and `physharness-pilot-watch` monitor paused. See `shutdown.json`, `projection-integrity.json`, `purity-integrity.json` and the immutable attempt result/status files.

Final post-fix host suite: **894 passed, 1 skipped, 6 deselected**, 21 upstream warnings in 27.53 seconds. Repository CI-scoped Ruff check/format passed for 131 files; whitespace checks passed. An initial final-lint invocation named a nonexistent `scripts` directory; its error log is retained, and the corrected command used the repository CI paths (`src tests tools infra migrations`). All 61 acceptance-scoped input hashes remain unchanged after the reporting fix (`final-scope-integrity.json`), so the final verifier packet remains applicable. The last diagnostic-only patch was covered by host tests; the earlier container/Temporal/PostgreSQL checks are not claimed to have been rerun after that patch.

Observed runner duration was 354.20 seconds for projection and 873.36 seconds for purity. There were 162 accounted generations, 119 native compactions, three delegated tasks and zero fresh-session handoffs in total. `live-feature-evidence.json` distinguishes per-target tool use. These observations demonstrate execution beyond the former 96,000 cumulative-token limit; they do not demonstrate long-horizon mathematical effectiveness.

Next scientific qualification should compare less aggressive compaction and richer Lean library exploration at matched budgets, measure repeated reads/stagnation, and explicitly exercise a live fresh-agent handoff. Those are follow-up experiments, not claimed outcomes of this delivery.
