# Final research-loop hardening

## Read-only diagnosis

- `issue_continuation` atomically queues a ready ticket and settles the source worker slot. `consume_continuation` replaces that ticket with the latest consumed ticket. Prior source checkpoints remain immutable, but prior source-to-successor bindings are overwritten on repeated handoff.
- `CanonicalRuntimeStore` saves the successor session before the first provider request. Existing recovery distinguishes no successor, one settled successor, and a completed successor, but no durable per-ordinal lineage record exists for operator export checks.
- OpenAI Responses handoff copies exact settled native input, response, archive references, and cumulative usage offsets when compatible. Portable handoff uses canonical working context, saved notes, and a VM archive ticket. Target/review, tool definitions, model, and environment are checked at the respective boundaries.
- A crash after native usage settlement and before compaction input pruning leaves a saved nonsettled boundary. Current recovery blocks automatically; deterministic local replay must be proven with fault injection before changing that behavior.

## Approved implementation direction

Create scoped, canonical per-ordinal continuation links at issue, update at consume, bind the first successor checkpoint before provider work, and validate the full chain at operator gates. Keep the existing one-handoff legacy path for completed pilot data. Test at least three same-task handoffs, independent agents, and fault boundaries without paid calls. A dedicated VM archive roundtrip will follow only after the root's test gate.

At the initial diagnosis checkpoint, no model, VM, live database, or credential call had been made. The later live work is recorded below.

## Implementation and local verification

- Canonical `continuation_link` rows now record each issue, consume and first successor checkpoint atomically with their respective task/session transactions. Operator export checks each ordinal's exact source, successor, checkpoint, scope, workspace artifact content, and complete session set. Protocol-tagged new tasks cannot fall back to the legacy single-handoff validator when links disappear.
- A local fault-injection test crashed after one provider response and settled usage but before compaction pruning. The saved checkpoint had no pending operation, a native compaction-only response, and 10/5 settled tokens; normal resume blocked. Running the existing pruning routine on this checkpoint produced one content-addressed archive and advanced the active context without issuing another provider request.
- Native compaction recovery now requires a saved settlement receipt binding response/operation IDs, exact usage and reservation limits. It can finish an unpruned response or a second crash after the archive write, then continue without appending a duplicate prompt. Tool/text responses, stale markers, altered input or usage, and provider overages remain blocked.
- Focused lineage, compaction, worker-tool and workspace-handoff suites: 107 passed. Ruff lint and format checks passed for the ten touched source/operator/test files. Tests include three same-task handoffs plus a separate peer branch, malformed/orphan/cyclic links, private link reads, no-link checkpoint corruption, an unmarked paid compaction crash, a second crash after local archive write, stale marker after a later tool response, and over-reservation usage. All tests use MockTransport and local stores; no paid call or live VM was used.

## Live outcome and corrective retry, 24 September

The first cooperative run produced an independently checked complete proof in 21 minutes 22 seconds. Comparator bound it to the reviewed target; Lean and Nanoda checked it. The accepted source reuses actual helper lemmas and the successful root continued through one real native compaction. This is a known-result development benchmark, not a new physics discovery. The single-agent calibration ended without a candidate after 274 seconds; different budgets preclude a controlled comparison.

The cooperative supervisor correctly remained blocked: two invalid absolute workspace paths exposed pre-dispatch error handling faults. The fixes now validate request paths before reserving external effects and return correctable errors to the model; genuine post-dispatch uncertainty still blocks. Root observed the failure before the fix, a full suite of 1,191 passing tests (14 skipped), and a real Docker regression that recovered from invalid paths and completed a valid Lean command. One pre-existing test assumed UUID ordering meant latest continuation; it now selects the explicit maximum ordinal.

All six old workers have been destroyed. The known failed read and its zero-cost slot were retired through the operator recovery API with exact archival and absence evidence. The other failed native session remains historical uncertainty, explicitly abandoned, never relabeled successful. The old proof and 2,676 unique exported artifacts remain preserved and hash-checked. Current-round conservative spending is $43.203255, leaving $8.796745 of its $52 envelope for one fresh retry. Historical spending remains $43.762893. No extra authorization is assumed.

The retry launcher is being separately audited and frozen. A root audit caught a preparation-order error before paid work: review is required for launch but cannot be required before preparation has produced the records to review. The correction has its own regression. No retry has launched at this checkpoint.

## Final result

Fresh retry completed with an independently verified full target proof at 17m03s; six tasks/sessions finished and the last task completed at 18m24s. Explicit user budget amendment raised this retry's total ceiling to $100, preserving all existing usage; final conservative cost $49.102475. Three attempts in this round total $92.305730, with earlier historical costs separately retained. Accepted source includes helper-written components; this retry needed no compaction/handoff. Eight typed input/scope refusals were audited and recovered from without data loss or provider uncertainty. Full frozen main suite: 1,194 passed, 14 skipped; standalone budget helper: 2 passed. Export checks 3,246 unique artifacts and exact native token reconciliation. All containers removed, all resource ledgers settled, experiment paused, VM stopped, monitor paused. See REPORT.md and final-reconciliation.json. No code or private output pushed.
