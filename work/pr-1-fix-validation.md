# PR #1 correction and compatibility evidence

Recorded 2026-09-15. Original reviewed base: `3cc5185e9ab19672538eacd0400f3aae6e2e6a43`.
Final correction source: `207e0133a707acd49d35a43bae399dc41cba88b4`.

The user authorized fixing every finding in the [independent review](pr-1-independent-review.md),
merging the sound result, and preserving compatibility with concurrent wave work. The dated
original findings remain intact. Every actionable scoped review finding below was reproduced,
corrected and independently re-reviewed. Model-assisted review does not supply GitHub's required
independent human approval. Final review, current CI and merge status are reported on
[PR #1](https://github.com/zubadestroyer1/PhysHarness2/pull/1).

## Corrected findings

| Original finding | Correction and regression evidence |
|---|---|
| 1. Canonical target digest confused with source hash | Comparator v2 separates canonical metadata identity from exact UTF-8 challenge bytes; real service-to-Comparator tests reach the scripted checker and independently reject tampered identities. Acceptance binds the current approved review and selected theorem. |
| 2. VM cancellation swallowed | The broker records uncertainty then propagates the original cancellation. Runtime timeout/interrupt tests verify no later generation starts and unresolved reservations remain held. |
| 3. Queued/blocked console controls missing | Shared transitions expose start/cancel, pause/cancel and resume/cancel for the corresponding canonical states, in list and detail views. |
| 4. Verifier faults leave receipts queued | One named 2,000,000-character limit applies before queueing and in requests. Oversized legacy receipts and construction/read failures persist explicit blocked diagnostics. Boundary and Unicode cases are tested. |
| 5. Selected evidence and ledger stale | Selection follows canonical record IDs/revisions; polling refreshes the selected ledger. Resource responses are guarded against disconnect and reselection. |
| 6. Polling erases mutation errors | Mutation and read errors have separate lifetimes. Successful background reads do not clear a failed operator command. |
| 7. Hidden-record query growth | Pages bound examined metadata, use ordered indexes and preserve empty-page continuation. Authorization and complete internal readers remain intact. Measurements appear below. |
| 8. Native child identity lost after allocation | Known child IDs are quarantined and journaled before later validation/cleanup awaits. Cleanup is bounded; pending observations survive reopen and cannot replay as a successful or replacement allocation. |

The console quickstart now specifies its API URL. Polling uses one event page per cycle and
refreshes affected canonical collections; unchanged cursors avoid whole-project reloads.
Knowledge search ranks metadata before fetching proof bytes and reads dependency source once.

Additional review findings were also fixed:

- A custom verifier's reserved diagnostic code could suppress the final current-review check.
  A locally computed compatibility flag now governs legacy handling; every verified outcome
  rechecks the locked current target/review before atomic receipt/claim persistence.
- Engineering-driver requests remain compatible with the active wave's separate schema.
  Scientific requests require theorem/review fields; common manifest pins remain unconditional.
- Activity retains the newest 1,000 observed events with that limit visible. Session saves emit
  fenced, idempotent events in the same transaction; the metric honestly labels recorded sessions.
- Same-review queued/failed receipts still caused a growing database scan after the initial
  pagination fix. Adding status and assurance to the receipt index closes that demonstrated gap.

Implementation commits: `10dc3b5`, `c18dcdd`, `dc15ca3`, `e90c040`, `ed437bd`, `aa01a07`, `207e013`.
The targeted fixes and follow-ups each passed separate implementation-independent review.

## Measured retrieval costs

| Reproduction | Before | After |
|---|---:|---:|
| One-item page, 1,000 invisible artifacts | 1,016 SQL statements | 6 |
| One-item page, 2,000 invisible artifacts | 2,026 SQL statements | 6 |
| One-result search, 1,000 irrelevant synthetic verified claims | 1,002 proof reads | 1 proof read, 13 SQL statements |
| One accepted artifact, 1,000 stale-review receipts | 1,001 receipt objects materialized | 1 |
| Lookup among 10,000 same-review queued/failed receipts | 60,236 SQLite instructions | 254 |
| Lookup among 10,000 same-review insufficient-assurance receipts | 90,236 SQLite instructions | 254 |

Page measurements cover `none`, `verified` and `ideas` sharing. Tests capture actual emitted SQL
and its bound parameters, then inspect SQLite EXPLAIN. Ordered keyset indexes avoid the original
temporary sort. Receipt-state regressions count database instructions, rather than just returned
rows, and prove that a valid receipt remains reachable after the 10,000-row inventory.

The immutable `0002_record_keyset_indexes` migration adds scope and receipt indexes. Revision
0001 is unchanged. Real SQLite upgrade/downgrade/re-upgrade and ORM/index-DDL parity pass;
PostgreSQL offline generation checks the actual JSON-expression index SQL. The required CI job
provides live PostgreSQL migration validation after publication.

These are bounded-work improvements, not constant-latency or fleet-capacity claims. A page
examines at most `max(100, limit)` scoped records plus lookahead, with further indexed acceptance
checks. Already verified independent-kernel receipts sharing artifact/review but differing in
other bindings can still add index work. Search matches O(N) metadata and sorts M matches in
O(M log M) time/O(M) memory; invalid high-ranked candidates add validation and sometimes proof
reads. Eligible corrupt/missing source is explicitly excluded, with an authorized diagnostic;
private or acceptance-invalid candidates expose no source or rejection details.

## Final local validation

At correction source `207e013`:

- `.venv/bin/pytest -q`: **482 passed, 2 skipped, 21 upstream warnings**.
- Ruff lint/format: **96 files clean**. Deployment metadata and whitespace checks passed.
- Supported Node **24.19.0**: **36 console tests passed**, TypeScript and Vite production build passed.

Local skips are the unconfigured PostgreSQL endpoint and opt-in Temporal integration test.
Warnings are existing Starlette/httpx, AnyIO and OpenHands SDK deprecations; they were not hidden
or fixed by unrelated dependency changes. No paid model, VM, cloud or proof-kernel call occurred.
Scripted checker success demonstrates acceptance contracts, not a scientific proof.

A live browser smoke used the built console and actual API against disposable SQLite state,
with no dispatcher/provider. It verified connect, created→queued retaining Pause/Cancel,
selected-record refresh after an external pause, refreshed synthetic $0.25 accounting, terminal
cancellation and disconnect. Browser errors were empty; the local server/tab were closed.
An attempted direct-HTTP stale-conflict setup was blocked by the shell sandbox; that scenario
is covered by controlled UI tests, not claimed as part of the live smoke.

## Active wave integration

[PR #20](https://github.com/zubadestroyer1/PhysHarness2/pull/20) is stacked on `codex/foundation`.
Its checkout was never edited, staged, reset or committed by this task. Its published, clean
head `60e8254c02e8cbfce08201bac1ff2b7ce2224a1c` was captured at
**2026-09-15T08:51:35.535682+00:00**: 288 files, manifest SHA-256
`4170c8ef3ececf9c9f5b107e294d92feec139fbd958143267bb6e4cd651acf48`.

A normal integration merge was prepared in a disposable clone, with parents that wave head and
correction `207e013`. Integration commit: `9d374152ec136ada2c5ce7015b03d331606ba459`.
It contains committed wave work, the foundation fixes and explicit overlap resolutions.

Full Python validation explicitly imported that integration tree's `src`: **639 passed,
4 skipped, 21 upstream warnings**. The skips are two opt-in Temporal cases and two unconfigured
PostgreSQL cases. Ruff lint/format passed for **112 files**. Deployment metadata passed on the
preceding composition with identical deployment inputs. Console source exactly matches the
separately tested foundation console. The new configured-preflight regression forwards a
non-default reviewed theorem through the wave API using synthetic transport.

The overlap resolutions preserve:

- Separate scientific and engineering request/verifier APIs, exact canonical/source/theorem pins,
  and the wave's actual upstream checker invocation and diagnostics.
- Both transaction-local worker-effect checks; session events within that same transaction;
  cancellation checkpoint retention under a current lease.
- The wave's independent-kernel requirement for knowledge reuse alongside metadata ranking,
  invalid-candidate continuation and current review/source/theorem visibility checks.
- Complete cursor traversal, including empty visible pages, by console and internal consumers.
- Historical engineering evidence, while marking changed current launcher/driver source as
  requiring rebuild, rerun and repinning. No earlier run is relabeled as testing changed bytes.

Final publication must use forward-only updates and recheck the wave head before advancing its
remote branch. Future wave edits are outside this identified integration test. Comparator v2
requires explicit fresh manifests/receipts and qualification pins; legacy ambiguous evidence is
not silently reinterpreted. All twelve scientific/operational waves remain unqualified.

## Review process limitation

The collaboration tool exhausted its agent-thread limit. Separate task-independent reviewers
were reused; no implementer approved its own fix. Those reviewers may retain earlier scoped
context, so this is disclosed as a limitation of review independence rather than hidden.
