# Independent metadata audit: projection attempt 01

Captured 2026-09-23 08:26 UTC from the pilot SQLite database in read-only URI mode and the
specified private `projection-attempt-01.stdout.json`/`.stderr.log`. This audit inspected
canonical metadata and artifact references. It did not read credentials, artifact bodies,
candidate source or native checkpoint context, and it made no model, verifier or VM calls.

**Result.** Live experiment `ff884e1f-6600-40c2-a704-4072c2c163f4` ran one task,
`1dc523ad-099e-4bc4-9dd9-100cc3373f89`, which ended `blocked` with outcome code
`BUDGET_EXHAUSTED`. The team report is `blocked`, with `stop_reason: null`; the task outcome
carries the useful stop code. This is a controlled runtime limit outcome, not evidence of a
process or VM crash. The one saved Responses session is `failed`. The team report artifact is
`1276799a-765c-4a51-802f-2bf7ada74f89`, SHA-256
`b4d258a6fee6e544a7ec93e56ca6a037458ab7e440a28332be5e163a6c005596`.

| Reconciliation | Canonical result |
| --- | ---: |
| Settled model reservations | 14 (13 with usage, 1 zero-use); actual cost $0.215614 |
| Session input + output tokens | 90,502 + 3,461 = 93,963 |
| Central tokens spent / reserved | 93,963 / 0 of 96,000 maximum |
| Central cost spent / reserved | $0.215614 / $0 of $25 maximum |
| Active workers / active or uncertain reservations | 0 / 0 |
| Pending verification receipts / running verifier checks in report | 0 / 0 |
| Task lease | Row retained with expiry 0; no live lease |

The stored price calculation reconciles exactly at the configured Standard rates:
90,502 × $2/M + 3,461 × $10/M = $0.215614. The 14 historical reservation maxima total more
than 96,000 tokens because each reservation was settled before the next one; that sum is not
current use. No reservation remains unsettled or uncertain. The session was below the 24-turn
ceiling; 93,963 observed tokens left only 2,037 under `max_total_tokens: 96000`. The Responses
loop counts the next prompt before generation and returns `BUDGET_EXHAUSTED` when its input
count leaves no generation budget. The exact final preflight count was not stored in the
allowlisted metadata reviewed here, so the token-preflight path is an inference from the
13 usage-bearing reservations, token totals and code. The experiment's runtime and wall-clock envelopes
remained 1,800 seconds; no timeout code appears in the task outcome.

Three verifier receipts are `blocked`, code `comparator_failed`, assurance `none`, with no
claim ID. Each binds to problem `b3817784-8d0e-4961-9903-c3c0feef1b58`, target digest
`789a2c8a03a2028338200e44c97a8e337b0e57ed21971467f0a308db6d7946b4`, challenge
SHA-256 `b9a6382b1ebe426f4c580d11c743a6a89968fcf5ea756ccc329ba975497a2667`, environment
digest `0c46de2450bd5a9b2584d513d3ad02a963a300c3b0e3510a3a22efbc5a11341f`, and
approved review `260afe3a-b90b-4d9c-b6a8-6276028c6977`. The current problem/review records
carry those same IDs and digests. Each receipt's candidate SHA-256 equals the referenced
`lean_source` artifact's stored SHA-256. The three candidate artifact IDs are
`c779517e-2efd-4cd1-9e93-a827df132f8a`, `3fbeca83-89f7-4755-a65e-db951a29c27e`, and
`aab249a8-8f04-4777-a2f9-a93bf3f0d620`. A fourth `lean_source` artifact has no receipt.
There are zero claims for this experiment and no verified receipt; no accepted proof or
verified reusable lemma was recorded.

The experiment remained `queued` (revision 2) immediately after `run-team` returned blocked.
That is an observability and allocation-control gap in the finite runner: task completion did
not make the experiment terminal. During this audit the operator canonically paused it; the
fresh read shows `paused` (revision 3). Its pending outbox entries for the earlier queue and
pause transitions should be considered if a dispatcher is later enabled, although the central
paused state prevents new allocation. No retry should reuse this exhausted experiment.

For a fresh attempt, a larger **aggregate** token envelope is the relevant change. A bounded
proposal is `budget.max_tokens = runtime_limits.max_total_tokens = 384000`, retaining the $25
cost ceiling, 1,800-second runtime, 24 turns, 16,384 output-token cap, one worker, direct
policy and verified sharing. This is a new `ExperimentCreate` against the same reviewed
problem/campaign with a new attempt key and fresh branch/context; it does not amend this run.
The operator should preflight the new experiment and still enforce the $25 central ceiling.
This audit does not authorize or launch that attempt.

## Dated operator follow-up — 2026-09-23 08:31 UTC

After the autonomous team stopped, the operator submitted the **unchanged fourth saved
candidate** through the existing acceptance service. This was a separate verification action,
with no new model generation or native-context continuation. The candidate artifact
`dc9e7152-f052-490c-9af1-1408dbdb7b0f` retains SHA-256
`0fc36413e53a2ea0f599819310b15d6cd57d290710b3395f9b75ceaedbb2c762`, matching the
hash observed in the earlier read-only audit. The new receipt
`d3c9db0a-a9f5-42ea-9c10-61661a0f31b3` is `verified`, code `kernel_checked`, assurance
`independent_kernel`, and binds the same target, challenge, environment and review IDs recorded
above. Canonical claim `0a8a12da-b095-4f4d-9f8d-d637fb5529b8` points back to that receipt
and artifact with `proof_status: verified`. The three autonomous receipts remain blocked.
The central ledger is unchanged at 93,963 spent tokens and $0.215614, with zero reserved tokens,
zero reserved cost and zero active workers. This accepted result therefore arose from
operator-submitted verification of an existing model artifact **after** the autonomous run
reported `BUDGET_EXHAUSTED`; it does not change that run's blocked status or demonstrate that
the model completed its own task loop.

Recorded by Codex independent metadata audit, 2026-09-23 08:31 UTC. This signature records
the read-only comparison and is not a human scientific review or deployment approval.
