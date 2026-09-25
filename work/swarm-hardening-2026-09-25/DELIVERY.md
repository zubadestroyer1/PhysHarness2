# Persistent swarm hardening: delivery

Scope: the four fix groups in `docs/superpowers/plans/2026-09-25-persistent-swarm-hardening.md`. Work began under Codex (GPT-6 Sol implementers, root audit in `AUDIT.md`) and was completed under Claude Code after Codex usage ran out mid-implementation. Nothing was committed or published. No paid model run was made. The only VM use was Codex's earlier bounded file-capture check (`real-vm-checks.log`, `real-vm-retry.log`). This delivery makes no wave or fleet qualification claim.

## Verification

- Pre-change baseline: 1,196 passed, 14 skipped (`baseline-suite.log`).
- Handover state (Codex stopped): 1 failed, 1,231 passed, 16 skipped. The failure was `test_ranked_knowledge_rechecks_acceptance_and_skips_invalid_candidates[missing_origin]`: the in-progress K1 diagnostics change raised NOT_FOUND on a claim whose origin experiment no longer exists.
- Final: **1,258 passed, 16 skipped**. `ruff check src tests` passes; there were 28 errors at handover.
- The 16 skips are opt-in provider/Docker/E2B checks that the environment did not enable.

## Unit 1: coordination and research resilience

| Item | Result | Evidence |
|---|---|---|
| FIFO within round-robin | Ordered by `created_at` within each root; UUID page order no longer matters | `test_ready_dispatch_uses_creation_age_inside_each_lineage_not_pagination_order` |
| Queued objective amendment | Checks revision; uses the same lock as lease admission; refused once leased. History is capped at the last 8 entries plus a count and hash chain of dropped ones | `test_queued_objective_amendment_is_revision_fenced_and_closes_on_lease`, cap test in `test_swarm_coordination_gaps.py` |
| Fresh context at lease | **Bug fixed:** after an amendment, the old objective still reached the model through `superseded_objectives` in the working context. The prompt now carries only `superseded_objective_count` (`memory._prompt_view`); the canonical record and its digest are unchanged | executor regression in `test_swarm_coordination_gaps.py` (red before fix) |
| C1: parent pivot | The parent can amend a queued private child's objective without reading its results, including under `sharing="none"` | `test_parent_worker_can_pivot_queued_private_child_without_result_access`, `test_parent_worker_pivots_queued_child_without_result_access_under_none_sharing` |
| Component registry (C3) | Visibility filter applied before paging; always "unverified"; shows `owner_strategy` | `test_component_directory_pages_past_200_and_private_rows_do_not_block` |
| Delivery honesty (C2) | Matches exact delivered items; a withdrawal takes precedence. New `recipient_unavailable` state: the message was never presented and the recipient branch has no queued or running work | `test_withdrawn_message_is_never_reported_as_acknowledged`, `test_message_to_branch_with_only_blocked_tasks_is_recipient_unavailable` |
| Peer availability | New `peer_availability` service method and tool, registered only when sharing is "ideas". Paged at 1–20; reports scheduling state only | `test_peer_availability_*` |
| Durable peer waits | Waiting frees the worker slot. Wakes on a message, a terminal recipient, timeout, `cancelled`, or `scope_withdrawn` (sharing or recipient withdrawn). Previously, withdrawing sharing raised inside the team supervisor | `test_waiting_peer_releases_capacity_and_resumes_on_reply`, `test_supervisor_resumes_waiter_when_sharing_withdrawn`, `test_peer_wait_*_wake` |
| Exact-target stop / bounded drain | Only independent-kernel evidence for the exact current target closes the target. Queued work is retired; generation stops at the next boundary. The check is pre-filtered in SQL, so unrelated receipts are never loaded | positive retire, two-worker stop and helper-final-response-stays-unproved tests; `test_verified_target_check_ignores_unrelated_receipts_without_loading_them` |
| Root replanning | Finite `configure_root_replans` policy (0–8); off by default | `test_partial_root_uses_finite_native_replans_and_remains_unproved` |
| Strategy descriptions | Optional `strategy` of at most 500 characters on task creation and delegation tools. It is carried into the helper prompt, task listings and the component directory, and its content is not judged | strategy tests in `test_swarm_coordination_gaps.py` |

## Unit 2: durable execution knowledge

- Chunked native checkpoints (details and benchmark in `persistence.md`): 96 real retry checkpoints restored exactly, with 92.9% less unique payload.
- P3: loading now makes one record query per graph level, batched 500 at a time, instead of one per chunk. On the regression, a load dropped from 44 to 8 SQL statements; saves stay within a fixed cost per new chunk (`test_save_and_load_sql_cost_scales_with_new_chunks_not_history`).
- **Not done (P3a):** creating all of one save's chunks in a single transaction. Chunk ids are assigned when a record is inserted and embedded in the parent chunk before it is stored, so batching needs deterministic ids or a two-phase encoder. Save cost is already a fixed amount per new chunk.

## Unit 3: artifact transfer and knowledge

- Workspace file promotion, accepted-result summaries and search diagnostics: see `knowledge.md`.
- K1: the diagnostics fix is completed. Dangling origins are skipped, and the independent audit's leak repro is now a regression test (`test_ineligible_cross_experiment_claim_does_not_change_search_diagnostics`, `test_claim_with_dangling_origin_experiment_is_skipped`; both red against baseline).
- K2: E2B definite-refusal handling is narrowed to read-only `download` and `export`. Helper refusals on `upload` and `restore` may have changed files, so they stay uncertain (`test_e2b_upload_helper_refusal_is_not_treated_as_definite`, red then green). A capture transport failure stays uncertain (`test_capture_transport_failure_is_uncertain_not_refusal`).

## Unit 4: integrated resilience

- Three consecutive compactions and handoffs keep the exact target and assumptions (`test_three_handoffs_record_exact_per_ordinal_successors`).
- One verified and one rejected lemma receipt keep their ids and status unchanged in every later checkpoint's working context. That verified receipt has kernel assurance, not independent-kernel, so it correctly does not close the target (`test_lemma_receipt_status_survives_three_handoffs_unchanged`; this pins existing behaviour, so there was no red run).

## Evidence classes

All of the Unit 1–4 evidence above is deterministic local tests with fake providers and SQLite. Codex's earlier real-VM run exercised only file capture and a Lean source-reuse compile; that compile's queued candidate had no independent receipt. None of this measures live swarm effectiveness, provider latency, or fleet-scale behaviour.

## Known limits / follow-ups

- Scheduling has no priority or aging. A requeued continuation keeps its original `created_at` and so runs before newer tasks.
- The first checkpoint save after a process restart replays one idempotent create per existing chunk, because the cache starts empty. A load holds all chunk bytes in memory.
- There is no database index for the verified-target query; SQLite still scans that experiment's verification rows.
- Next evidence step, per the retrospective: a live run with 8–16 workers, deliberate interruptions and handoffs, a lemma-reuse probe, and matched-cost comparisons.
