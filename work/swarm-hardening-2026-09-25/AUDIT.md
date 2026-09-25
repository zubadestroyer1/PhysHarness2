# Root audit ledger

Scope: changes against the source/test snapshot in `baseline/manifest.json`, not against the already-dirty Git HEAD. Pre-change suite: 1,196 passed, 14 skipped, 21 warnings (baseline-suite.log). No paid provider experiment is authorized by this change request.

## Findings under implementation review

- C1: Parent amendment originally required full child-task read permission before checking parent authority. Reproduce under sharing=none; permit exact queued assignment changes while retaining child result privacy. Implementer reports fixed; root integration check pending.
- C2: Message cursor advancement can include withdrawal notices. Delivery status must use exact delivered item membership; cursor advancement alone cannot assert receipt of message content. Implementer notified.
- C3: Component directory initially failed after 200 global entries with no page API, including hidden rows. Require actual visibility-filtered pagination and missing-reference handling. Implementer notified.
- P1: Whole growing dict pages sorted by random tool IDs would repeatedly rewrite prefixes. Hash-partitioned mapping encoding and random-key growth regression added by implementer; root benchmark pending.
- P2: Chunk graph must retain private scope and export closure, support historical full snapshots and workspace-native artifacts, and fail on missing/tampered/foreign chunks. Focused tests reported, root integration pending.
- P3: Avoid one database transaction per old chunk on every save; cache immutable references within scoped store, keep publication fencing and validate read/write limits symmetrically. Implementation in progress.
- K1: Knowledge corpus diagnostics originally counted hidden claims before checking visibility. Require output noninterference and batched metadata filtering; implementation in progress.
- K2: Capture refusals must remain recoverable only for the specifically confirmed read-only operation. Wrong hash retries must not quarantine a healthy VM; actual post-dispatch uncertainty remains blocked. Implementation in progress.

## Remaining verification

Root review and regression replay for each fixed finding; complete current-source Python suite; lint/schema checks; actual VM bounded-file capture if supported by the completed tests; checkpoint encode/decode audit against a bounded sample of prior real native checkpoints. Simulated queue scale, mocked provider transitions, actual VM checks and live scientific outcomes must be reported separately.
