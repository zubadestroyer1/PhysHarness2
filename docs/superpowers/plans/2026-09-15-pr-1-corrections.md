# PR #1 correctness and scalability corrections

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task by task. The user has explicitly approved applying the review's corrections and merging the resulting sound change.

**Goal:** Correct every actionable finding in the independent review and its documented performance/quickstart issues, with reproducible evidence and an honestly updated PR.

**Architecture:** Preserve canonical authority and existing provider boundaries. Separate reviewed target identity from trusted source identity, preserve cancellation and uncertain allocation identity, make console state follow canonical records, and bound metadata/retrieval work.

**Tech Stack:** Python 3.12, SQLAlchemy, FastAPI, Pydantic, Temporal, Responses/E2B adapters, React/TypeScript, Vitest, PostgreSQL/SQLite.

**Spec:** `work/pr-1-independent-review.md`, approved by the user's request to apply all corrections. `docs/IMPLEMENTATION_PLAN.md` remains the scientific/operational authority.

## Global Constraints

- Worker output cannot confer proof status; only independently checked, exact reviewed targets may be accepted.
- Preserve target/environment/candidate identity checks, sharing restrictions, leases, idempotency and reservations for unknown external work.
- Never fabricate human review, kernel acceptance, live provider results, or fleet qualification.
- Use actual regression failures before implementation, then focused tests. No paid model/VM or cloud experiments.
- Work on the existing `codex/foundation` PR branch. Do not alter branch protection or fabricate another reviewer identity. The user has authorized committing, pushing, updating PR #1 and merging when its requirements are met.
- Commit only the task's intended code/tests/documentation. Preserve the original review as dated evidence.
- No implementation subagents in parallel; do not spawn subagents from a dispatched task. Report concerns to the controller.
- Active wave compatibility: `codex/formal-research-loop` is being edited in `.worktrees/formal-research-loop`. Read it for interface comparison; never edit, stage, reset or commit its files. Its observed acceptance contract uses `physharness-comparator-v2`, required `challenge_sha256` computed from exact `problem.formal_statement` UTF-8 bytes, and `target_theorem` on VerificationRequest. Align these names and semantics. Preserve its future worker-effect transaction guards and run-control integration when composing patches. Perform a combined-tree test from a captured snapshot and report precisely what snapshot was tested.

### Task 1: Restore target-to-verifier integration and terminal processing faults

**Files:** `src/physharness/acceptance.py`, `src/physharness/verification/boundary.py`, `src/physharness/verification/container_driver.py`, `src/physharness/evaluation/evidence.py`, the acceptance-sharing predicates in `src/physharness/service.py`, verification/authority fixtures/tests, `docs/VERIFICATION.md`, `docs/API_CONTRACT.md`, formal qualification contract/examples as affected.

**Interfaces:** Keep `target_digest` as canonical reviewed problem metadata identity. Add a separately named `challenge_sha256` for `Challenge.lean` bytes to the trusted manifest and verified outcome/receipt evidence as needed. The operator-pinned manifest must bind canonical problem revision, canonical target digest, challenge hash and environment. Never reinterpret legacy metadata hashes as source hashes or silently accept old ambiguous manifests. Request construction remains server-owned. Prefer no new ProblemCreate field if the trusted manifest fully binds the mapping; document compatibility and any protocol/qualification repinning.

**Active-wave compatibility:** Match the existing in-progress wave contract described in Global Constraints. Source hash is the exact UTF-8 `formal_statement`, not a second user-entered field. Manifest protocol is v2 and theorem selection must equal the reviewed `target_theorem`. Canonical evidence and accepted sharing must validate the receipt against the current review, exact source hash and selected theorem; preserve these bindings in consumers and fixtures. The wave adds EngineeringRequest/EngineeringVerifier and bundle creation separately; preserve compatibility without prematurely importing those unfinished features. Execute Task 2 before Task 1 to begin in files not currently changed by the wave.

- [x] Add service-to-Comparator regression based on `/tmp/physharness-acceptance-repro.py`: create and review a real canonical problem, build its trusted manifest, submit candidate; assert bundle validation reaches the controlled checker rather than `trusted_bundle_invalid`. Declare the checker transport synthetic. Tamper canonical target, source hash, source bytes and environment independently and assert fail closed.
- [x] Add limit and processing-fault tests: exactly 2,000,000 candidate characters is supported; 2,000,001 is rejected before queueing; a persisted legacy oversized receipt and an artifact-read failure during processing get explicit blocked receipts instead of remaining queued. Expected invariant: `result['status'] == 'blocked'` and diagnostic code/remediation are present for processing faults.
- [x] Run new tests and record expected failures. Implement distinct hashes, complete trusted-driver checks and diagnostic persistence. Keep all verifier identity/assurance checks intact; align one named candidate-size constant across queue and verifier contracts.
- [x] Run verification/authority/API/reproduction/infrastructure tests covering changed contracts plus Ruff. Update docs with exact new contract and honest compatibility requirements. Commit and write task report with red/green commands/output and any remaining concern.

### Task 2: Preserve cancellation and newly allocated VM identities

**Files:** `src/physharness/orchestration/workspaces.py`, `src/physharness/execution/e2b.py`, workspace/runtime/E2B tests, `docs/VM_WORKSPACES.md`.

**Interfaces:** `CancelledError` must propagate unchanged after uncertainty is recorded. Every known fork/restore child ID must survive post-allocation validation, cleanup errors and cancellation, including in durable journal evidence across process restart. Unknown work retains reservations. Replaying an uncertain operation cannot silently allocate a replacement or treat a quarantined child as ready.

- [x] Turn `/tmp/physharness_execution_review_repro.py` into integrated regressions for runtime timeout and explicit interrupt, including provisioning and a later VM operation. Assert no subsequent generation starts, cancellation/timeout is explicit, and unresolved VM reservations remain held.
- [x] Turn `/tmp/physharness_child_identity_repro.py` into fork and restore regressions for metadata validation plus kill failure, and cancellation after allocation. Assert returned child ID is retained in observations and durable journal; reopen journal to verify recovery evidence; assert replay does not allocate another child.
- [x] Run tests red. Record observations before re-raising cancellation. Retain/quarantine child identities immediately before post-allocation awaits; bound cleanup and preserve explicit uncertainty if cleanup fails. Do not record an uncertain allocation as completed/usable.
- [x] Run focused workspace/Responses/E2B suites and Ruff; document recovery and cancellation semantics. Commit and report red/green evidence.

### Task 3: Make console controls, evidence and errors follow canonical state

**Files:** `console/src/App.tsx`, `console/src/components.tsx`, `console/src/api.ts`, `console/src/types.ts`, a small shared transition module if useful, `console/tests/*`, `docs/CONSOLE.md`, `README.md`.

**Interfaces:** Shared supported transitions: created → start/cancel; queued and running → pause/cancel; paused and blocked → resume/cancel; terminal → none. Selection uses refreshed canonical records while immutable loaded artifact content remains bound to its artifact ID. Mutation errors persist independently of polling errors. Polling avoids overlapping full-project reloads and refreshes the selected ledger, with request/session guards preventing stale responses after disconnect or reselection.

**Supported local runtime:** `/Users/kieranpi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node` is Node 24.19.0. Prepend its bin directory to PATH for npm/Vitest/build so validation runs on a supported version; system Node 25.9.0 is outside the declared range.

- [x] Import the three isolated regression scenarios at `/private/var/folders/4x/gtrwnl511qvbkvtpksqmvyc80000gn/T/physharness-console-review-scrwrhcu/tests/review.test.tsx` into normal tests with valid canonical fixtures. Verify created → queued retains Pause/Cancel in list/detail, blocked supports resume/cancel, polling updates selected revision/status/ledger, and failed cancellation remains visible after a successful read poll.
- [x] Add meaningful tests for stale in-flight responses and polling: unchanged event cursor must avoid reloading all record collections; changed canonical events refresh relevant scoped state; no overlapping poll cycle. Do not silently truncate inventories or misrepresent a partial page as complete. Use an initial collection snapshot plus event-driven refresh and campaign/experiment scoping where appropriate. Capture the initial event watermark before loading collections so concurrent writes cannot fall between the snapshot and cursor. Preserve the server event page cursor/has_more semantics, including pages with no visible events; advance only after associated refresh succeeds. Guard ledger, artifact, export and mutation completions against disconnect or reselection.
- [x] Run tests red; implement shared actions, canonical selection refresh, ledger polling, independent error state and bounded/incremental refresh. Keep all server errors explicit; no automatic mutation retries with new idempotency keys.
- [x] Correct local quickstart to explicitly use `VITE_API_URL=http://127.0.0.1:8000` (or enter that API URL). Update console documentation to exactly match behavior. Run console tests and TypeScript/Vite build, commit and report evidence. Supported Node validation can rely on current CI if no supported local binary exists; state local version honestly.

### Task 4: Bound record visibility and knowledge retrieval work

**Files:** `src/physharness/service.py`, `src/physharness/research.py`, `src/physharness/storage.py`, a new immutable Alembic revision if indexes are needed, sharing/knowledge/infrastructure/memory tests, `docs/API_CONTRACT.md`, `docs/SCIENCE.md`.

**Interfaces:** Preserve the current sharing truth table for own branch, delegated topology, trusted inputs, private native artifacts, accepted cross-branch evidence, orchestrators and legacy experiment-only agents. A page request must have bounded scanned work, with a continuation cursor when invisible rows consume its scan budget, or use indexed SQL visibility plus batched checks. Never return unauthorized data. Internal full readers continue all pages, including empty pages with a cursor.

- [x] Add a real SQL query-count regression for at least 1,000 invisible artifacts and `limit=1`; prove bounded SQL work independent of invisible inventory growth. Assert later authorized records are still reachable through returned cursors and test all sharing modes/private record kinds. Inspect the database query plan as well as statement counts: a SQL LIMIT must not conceal an avoidable full metadata sort/scan. Add PostgreSQL-compatible immutable index migration checks where needed for project/kind/keyset (and experiment scope), keeping existing migration history unchanged.
- [x] Add knowledge-search tests with many irrelevant verified claims and an artifact-store read counter. `limit=1` must not fetch every proof from storage. Candidate selection/ranking should occur before expensive acceptance/artifact validation; continue past invalid candidates until the requested number of eligible results is collected. Preserve discovery/holdout, environment, assumption, reviewed-target and source integrity restrictions.
- [x] Run tests red, implement query predicates/batched authorization or explicit bounded scans, and indexed/batched candidate loading. Do not simply hide the original O(N) artifact reads behind a new helper or claim production-scale qualification. Keep invalid/corrupt selected evidence explicit and return correct relevant results.
- [x] Run sharing/authority/memory/knowledge/research/infrastructure tests and Ruff. Document exact page semantics and remaining metadata ranking costs. Commit and report measured before/after query/store-read counts.

### Task 5: Integrate evidence, review and submit the corrected PR

**Files:** `work/pr-1-fix-validation.md`, `docs/IMPLEMENTATION_STATUS.md`, `CHANGELOG.md`, PR #1 description; modify other affected descriptions only if needed for accuracy.

- [ ] Review each task's code against its brief and reproduced failures; resolve substantive findings before continuing.
- [ ] Run fresh aggregate Python tests, Ruff lint/format, deployment metadata, whitespace, console tests/build and available required infrastructure checks. Verify exact GitHub head/CI after pushing.
- [ ] Record all corrected issues, actual counts, skips, compatibility changes and remaining qualification requirements. Keep `work/pr-1-independent-review.md` as a dated pre-fix review, adding a link to the fix evidence if useful.
- [ ] Obtain an independent final code review of the complete correction range, resolve findings, commit/push evidence, update PR #1 title/body to final behavior, and mark ready when appropriate.
- [ ] Merge using GitHub's required protections when available; if an independent code-owner approval is the remaining external blocker, leave the reviewed fixes pushed and report that exact prerequisite without bypassing it or claiming a merge occurred.
