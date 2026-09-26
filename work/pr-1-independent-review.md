# Independent review of PR #1

Reviewed 2026-09-15. **Decision: request changes; do not merge this revision.**

This is the preserved review of the original head. Subsequent corrections and their validation are recorded in [PR correction evidence](pr-1-fix-validation.md).

- PR: [Build the PhysHarness development platform and project workflow](https://github.com/zubadestroyer1/PhysHarness2/pull/1)
- Base: `f0639cd901ca01c6013007d98430f7b7fcb7fe4e`
- Reviewed head: `3cc5185e9ab19672538eacd0400f3aae6e2e6a43`
- Scope: 207 changed files; application authority/storage/API/client/MCP, acceptance, scientific/evaluation/learning components, memory, execution providers, orchestration, console, infrastructure, migrations, tests, PR description and project documentation.

The review used fresh-context reviewers for acceptance/science, execution/orchestration, and infrastructure/console. The primary reviewer inspected application authority and integration paths, ran the aggregate checks, and independently reran the reported reproductions. Existing audit reports were treated as historical claims, not as review conclusions. This is model-assisted independent code review, not a human scientific or code-owner approval.

## Findings requiring correction

### 1. P1 — Canonical targets cannot pass the verifier's source-hash check

Locations: [service.py:515](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/service.py#L515), [acceptance.py:81](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/acceptance.py#L81), [boundary.py:308](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/verification/boundary.py#L308).

Problem creation computes `target_digest` from the complete serialized problem metadata. Acceptance forwards that digest unchanged. Comparator requires the same digest to equal SHA-256 of the `Challenge.lean` file bytes. These represent different data. A manifest pinned to the canonical digest fails the file check; a manifest pinned to the Lean-source digest fails the manifest/request check.

A problem created and reviewed through the real service, with a matching environment and controlled pinned bundle, returned `blocked / trusted_bundle_invalid`, with `target or environment digest mismatch`. This happens before Docker or a proof kernel runs, so supplying the missing qualified environment does not resolve it.

**Required correction:** distinguish the immutable reviewed problem identity from the challenge-source hash, bind both in the trusted manifest and receipt contract, and exercise the real service-to-Comparator request path. Do not remove the integrity checks.

### 2. P1 — VM tool cancellation can allow model work after the runtime timeout

Locations: [workspaces.py:430](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/orchestration/workspaces.py#L430), [workspaces.py:669](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/orchestration/workspaces.py#L669), [research_worker.py:122](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/orchestration/research_worker.py#L122).

The workspace broker catches `BaseException`, including `asyncio.CancelledError`, and converts it to `HarnessError`. The research tool wrapper handles that as an ordinary model-visible tool rejection. This consumes the cancellation used by the Responses runtime timeout, allowing its generation loop to continue.

With the actual Responses SDK using a scripted HTTP transport, the real broker and a sleeping fake VM, a 0.25-second timeout produced a `completed` session at approximately 0.26 seconds and two model-create requests, with the second issued after cancellation. The workspace correctly became `reconciliation_required`, but execution did not stop. No paid calls occurred in this reproduction.

**Required correction:** preserve uncertainty observations and reservations, then propagate cancellation through the tool boundary. Check both provisioning and subsequent VM operations. A regression must assert that no new generation begins after cancellation and that unknown VM work remains reserved.

### 3. P1 — Starting an experiment removes its console stop controls

Locations: [App.tsx:198](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/console/src/App.tsx#L198), [components.tsx:142](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/console/src/components.tsx#L142), [service.py:605](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/service.py#L605).

The API returns `queued` after start/resume and permits pause/cancel while queued. Both console action selectors omit that state. Workers can perform paid work while the experiment remains queued; no writer advancing the experiment itself to `running` was found. The designated console therefore removes Pause and Cancel immediately after a normal start. It also omits the API-supported resume/cancel actions for `blocked` experiments.

An isolated React test with a queued experiment confirmed that the selected panel has no Cancel button. Existing tests use a running fixture and miss the normal start result.

**Required correction:** represent every supported API transition consistently in the list and detail controls, ideally from one shared mapping. Verify the real created → queued response sequence.

### 4. P2 — Valid uploads can leave verification permanently queued

Locations: [acceptance.py:80](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/acceptance.py#L80), [domain.py:122](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/domain.py#L122), [boundary.py:35](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/verification/boundary.py#L35).

Artifact creation permits 5,000,000 characters; the verifier request permits 2,000,000. Submission checks artifact kind and integrity without checking the verifier limit. Processing constructs `VerificationRequest` before its exception handler.

A 2,000,001-character Lean artifact uploaded and queued successfully, then processing raised `ValidationError`; its canonical receipt remained `queued`. Retrying the same input cannot repair this deterministic failure. Artifact-read failures during request construction likewise escape the persisted outcome path.

**Required correction:** validate candidate constraints before queuing and persist an explicit processing fault if request construction or artifact loading fails. Test the boundary sizes and fault state.

### 5. P2 — Selected evidence and resource accounting do not refresh

Locations: [App.tsx:37](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/console/src/App.tsx#L37), [App.tsx:54](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/console/src/App.tsx#L54).

Five-second polling replaces collection data but leaves `selection.item` as an old object. The ledger effect depends only on the API client and selection, so it does not poll either. A selected experiment can indefinitely show obsolete status, revision, spend and active workers while collection polling succeeds. Detail-panel transitions also retain the obsolete revision.

Reproduction: the next poll returned paused/revision 2 and the ledger endpoint was ready to report $3 spent. The panel still showed running/revision 1/$0; the ledger endpoint had been called once.

**Required correction:** resolve selection against refreshed records and refresh the selected experiment's ledger with explicit loading/fault state. Verify changes from another operator and worker settlements while the panel stays open.

### 6. P2 — Successful read polling hides failed mutations

Location: [App.tsx:40](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/console/src/App.tsx#L40).

Reads and mutations share one `error` value. Every successful background refresh calls `setError(null)`, clearing a failed cancellation/review's error code, operation ID and remediation even though that operation still failed. A failed Cancel returning HTTP 409 was visible immediately and disappeared after the next successful poll.

This contradicts the console guide's claim that revision conflicts remain visible operator decisions.

**Required correction:** separate mutation failures from read-refresh state and preserve them until acknowledged or resolved. A regression must cross a polling interval after the failed mutation.

### 7. P2 — A bounded artifact page performs unbounded hidden-row work

Location: [service.py:262](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/service.py#L262).

Pagination applies visibility in Python and scans until it finds enough visible rows or exhausts the experiment. There is no scan bound. `_in_scope` also performs record lookups while scanning. A small requested page therefore does not bound database work for isolated branches.

Measured with real SQLAlchemy/SQLite and 1,000 metadata artifacts belonging to another branch under `sharing=none`: requesting `limit=1` returned zero items and no cursor after **1,014 SQL statements**. This was 0.07 seconds locally; it is a query-count measurement, not a PostgreSQL latency benchmark. The number of database round trips grows with other workers' retained history and is multiplied across callers.

**Required correction:** use indexed SQL visibility predicates/batched authorization, or a bounded scanned-page cursor contract, while retaining privacy. Add a query-count or bounded-work regression with predominantly invisible records. Do not merely cap returned items and claim bounded work.

### 8. P2 — Native E2B child identity can be lost after allocation

Locations: [e2b.py:847](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/execution/e2b.py#L847), [e2b.py:902](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/execution/e2b.py#L902), [e2b.py:913](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/execution/e2b.py#L913).

Fork/restore receives a newly allocated sandbox before post-allocation network/identity verification. The child is only added to retained observations by the later `_commit_child`. If verification fails and cleanup `kill()` also fails, the cleanup exception escapes and the known billable child ID is absent from both the journal result and reconciliation observations. Cancellation during this window has a related retention gap.

A fake provider returned `known-billable-child`; metadata lookup and kill then failed. Observed result: raw `OSError`, empty child observations, no retained children, pending journal with `result=null`, despite the known returned child identity.

This affects the explicitly enabled standalone native path; it is not evidence of a live cloud incident.

**Required correction:** retain/quarantine the child identity immediately after allocation, before further awaits, and use bounded cleanup that preserves the identity and explicit uncertainty even if metadata validation, destruction or cancellation fails.

## Descriptions and project alignment

- The PR's five successful CI jobs at the reviewed head were confirmed through GitHub. Local aggregate counts match the stated 368 Python tests and 10 console tests.
- README, roadmap and implementation ledger clearly describe a development platform with all twelve waves unqualified. They do not claim live models, a live VM fleet, accepted Lean results, production scale or new physics. Those disclosed qualification gaps alone are not grounds for rejecting a development PR.
- The implementation has useful authority separation, immutable artifact hashes, idempotency fingerprints, retained uncertain reservations, pinned CI inputs, independent-kernel publication requirements and explicit evidence categories. These strengths do not resolve the integration failures above.
- Console documentation overstates live refresh and persistent mutation-error behavior, as findings 5–6 demonstrate.
- README's local quickstart omits entering the API URL or setting `VITE_API_URL`; the blank default targets Vite's origin and there is no development proxy. The dedicated console guide gives the needed `http://127.0.0.1:8000` configuration. This is a lower-priority documentation correction.
- Historical `work/` and `outputs/` reports are not a current certification. External scientific source material and benchmark meaning still require the explicitly outstanding expert review.

## Further scaling work

Beyond finding 7, knowledge search loads the complete eligible claim inventory, performs several metadata reads and reads candidate artifact bytes before ranking and applying the result limit ([research.py:84](https://github.com/zubadestroyer1/PhysHarness2/blob/3cc5185e9ab19672538eacd0400f3aae6e2e6a43/src/physharness/research.py#L84)). In S3 deployments a query returning one hit can read every eligible proof. The console also reloads all project collections every five seconds. These deserve indexed candidate selection, batched reads, scoped queries and incremental updates before fleet qualification. No 128- or 1,000-worker performance claim is justified by the current evidence.

## Validation and limits

| Check | Observed result |
|---|---|
| Fresh full Python suite | 368 passed, 2 explicit infrastructure skips, 21 upstream warnings |
| Ruff lint and format | Passed; 93 files already formatted |
| Deployment metadata and PR whitespace | Passed |
| Existing console tests | 10 passed |
| TypeScript and Vite build | Passed |
| Additional isolated console regressions | 3 failed, reproducing findings 3, 5 and 6 |
| Acceptance reproductions | Hash mismatch blocked; oversized candidate raised and stayed queued |
| Runtime cancellation reproduction | Completed after timeout; additional scripted model request |
| Native child recovery reproduction | Known child ID absent after metadata and kill failures |
| Artifact pagination probe | 1,014 SQL statements for an empty page with limit 1 and 1,000 hidden records |
| GitHub CI at reviewed head | Python, live PostgreSQL, console, Terraform and actual application-container build/import all successful |

Local frontend checks used Node 25.9.0, outside the declared supported versions; they are diagnostic evidence, not support qualification. The verified GitHub console job used the configured supported Node 24.15.0. PostgreSQL and Temporal were skipped by the local aggregate suite; PostgreSQL's current CI pass was independently inspected, while the previously reported local Temporal run was not repeated in this review. No paid model/VM call, live Lean execution, cloud deployment or endurance workload was run.

Temporary reproduction sources, retained locally at review time:

- `/tmp/physharness-acceptance-repro.py`
- `/tmp/physharness_execution_review_repro.py`
- `/tmp/physharness_child_identity_repro.py`
- `$TMPDIR/physharness-console-review-scrwrhcu/tests/review.test.tsx`

Run the Python scripts with the repository's `.venv/bin/python` from the repository root. Run the isolated UI test from its temporary console directory with `./node_modules/.bin/vitest run tests/review.test.tsx`. The UI tests assert corrected behavior and intentionally fail on the reviewed code. Source files, index and PR branch were not modified by these reproductions.

## Merge status

The technical findings already make the user's merge condition false. No merge was attempted. GitHub also reports the PR as a draft with `REVIEW_REQUIRED`: main requires one approving code-owner review, all five checks, current base and resolved conversations, with administrator enforcement. The sole current code owner is also the PR author. An eligible independent approval still needs to be arranged; model-assisted review cannot provide a separate human/code-owner identity.

Correct the findings, add the missing integration regressions, reconcile affected contracts/documentation, and review the resulting new head before reconsidering merge. Existing branch protection should remain in force.
