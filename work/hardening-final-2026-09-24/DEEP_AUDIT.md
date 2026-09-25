# What the agent logs actually show

Read-only retrospective of the calibration, original cooperative attempt and fresh retry, performed after shutdown. Sources are their immutable exported manifests and SHA-addressed artifacts, canonical event records opened read-only, and relevant execution/scheduling code. Three separate mathematical, collaboration and runtime reviews were cross-checked by the root. No model experiment, VM restart or implementation change was made during this audit. Provider-private/encrypted reasoning was not decoded or reconstructed; mathematical descriptions below summarize explicit messages and formal proof artifacts.

The strongest conclusion is successful collaborative proof construction with exact independent acceptance. The strongest missed issues concern checkpoint storage, stale queued work, arbitrary within-root scheduling, and manual proof transfer. Several advertised capabilities received no meaningful exercise in these runs.

## 1. The mathematics was coherent, and both roots contributed

The clean retry assembled a 606-line, 27,321-byte proof of the finite forced nonlinear Duffing-network energy estimate. Its main construction is a modified energy: ordinary mechanical energy plus a position–velocity cross term and a damping-weighted position term. The latter makes unwanted terms cancel when differentiated. The proof compares modified and ordinary energy, bounds forcing with Young inequalities, and applies an integrating factor. It recovers the exact reviewed constants.

The surviving target proof combines:

- The submitting root's energy comparison, finite-sum dissipation estimate and full assembly.
- A derivative helper's quadratic-form, kinetic/quartic-energy and cross-term derivatives.
- The other root's `weighted_decay` integrating-factor lemma.

Both roots therefore contributed; describing the non-submitting root as wasted would be wrong. Several other helper artifacts offered alternatives or checking but were superseded in the accepted source. The principal Lean difficulties were differentiating and rearranging finite double sums under stiffness symmetry, substituting coordinate ODEs, and proving precise scalar inequalities with division and signs. The broad mathematical strategy appeared early; much of the elapsed work was formal proof construction.

The exact independent receipts remain the proof evidence. Temporary `sorry` and local axiom stubs appeared in development artifacts, especially during component assembly. Those are provisional work and must not count as solved results. Both final submitted sources closed these holes and passed the independent pipeline. The axiom lists in receipts are allowed policy upper bounds, not exact inventories of axioms used.

## 2. Strategy diversity was limited

Both identically configured GPT-6 Sol roots used the same modified-energy route within the first minute. Their productive difference was in sublemma implementation and integration, rather than sustained competing mathematical approaches. Early sharing helped assembly, but this observation does not qualify heterogeneous search or six independent attempts.

The calibration also found the main argument, then stopped after roughly 4.6 minutes with only a scalar lemma formalized, at $1.47 of its $14 ceiling. Its final report explicitly said the theorem remained unverified. This was not a token, time or spending limit. Honest partial reporting is good; a long-running campaign controller must separately decide whether a root-level partial result should trigger continued work. It should not punish a bounded helper for correctly finishing its narrower assignment.

## 3. Queued helpers became stale

Two helpers waited 9m52s and 11m43s before receiving a worker slot. The scalar-comparison assignment was effectively superseded while queued: another root supplied the required lemma at 23:54:54, the parent sent a pivot request at 23:57:56, and the queued helper only began at 00:03:11. It did adapt after reading the later information; it then did review/assembly work. This is evidence for refreshing an assignment when it starts, not evidence that every late helper was useless.

Scalar decay and symmetric-quadratic differentiation were each implemented repeatedly by different workers. Some redundancy can be intentional independent checking, but no explicit second-check objective explained all of it. A shared component registry with statement/interface, current owner, local-check status and consumers would expose such overlap without dictating the proof method.

Root independently reproduced an additional scheduling weakness. `ResearchTeamRunner._records` preserves canonical pagination, which orders tasks by UUID. `selected_tasks` preserves that order; `fair_ready_order` round-robins root lineages but preserves the supplied order within a lineage. For the two actual same-root queued tasks, UUID ordering chooses the newer `30fccdf6...` before the earlier `5a94d5ae...`, matching the observed lease order. There is no arrival or priority ordering at that point. See `deep-queue-replay.json`. This explains ordering, not the entire wait duration; occupied capacity was also necessary. Add explicit aging/priority or FIFO semantics and regression coverage before claiming queue fairness within a root.

## 4. Direct communication worked; broader network tools were scarcely exercised

The retry had 60 direct messages. Fifty-seven appeared in acknowledged delivery items, grouped into 47 delivery batches. Acknowledgment establishes delivery to the reader, not comprehension or adoption. Actual source reuse is separately established by workspace uploads and accepted-source contents. There were zero discussion topics, posts or subscriptions. The run was primarily direct-message collaboration.

In the original faulted cooperative attempt, the blocked root received 27 messages but only three were acknowledged. Twenty-four were not consumed, many sent well after it had failed. Successful send acknowledgments do not establish a working collaboration channel. Recipient status and delivery outcomes should be explicit; rerouting to another researcher must preserve sharing permissions.

One root used seven shell sleeps, totaling 160 requested seconds, interleaved with status/mailbox calls. Those sleeps happened late, after the initially queued helpers had started; they must not be blamed for the earlier queue waits. They do show a need for durable event waits that can release a scarce worker slot, rather than model-driven polling. Existing task-wait mechanisms should be used where applicable; waiting on a peer result also needs a clear supported path.

## 5. Submission needlessly re-emitted a completed proof

The successful root reported local full-source compilation at 00:05:18. It then had to supply the full source text to `submit_candidate` rather than promote the already checked workspace file by reference.

Root traced response `resp_00e0c709d06b6368016ab5bad27c5487d0b605272d9775cdc0`: generation started at 00:05:37.748981 and usage settled at 00:07:35.748937, a 118-second interval. It produced 12,342 output tokens, only 78 labeled reasoning tokens. The function argument's actual source is 25,532 Unicode characters / 27,321 UTF-8 bytes and hashes exactly to the accepted candidate (`d54ff7f2...`). The provider response's `created_at` is near request start, not the later tool-execution time.

Most of that local-success-to-submission interval was therefore a large source-emission step, not verifier execution. The logs do not isolate every second of provider/network overhead, but the avoidable workflow is clear. Add a workspace-file-to-candidate operation that snapshots exact bytes under the lease, hashes them, stores an immutable artifact, and runs the same independent verifier. This must not trust a model's claim that a file passed locally.

## 6. Checkpoint storage is the largest missed scale concern

The retry's export contains 2,504,754,798 bytes of unique artifact payloads. Native checkpoints alone account for 2,504,180,069 bytes: over 99.97%. There are 2,087 distinct native checkpoints for 338 provider responses (6.17 per response), with the largest snapshot about 3.21 MB. The original cooperative export likewise contains about 2.08 GB. These are stored uncompressed payload byte totals, not measured RSS, disk-physical allocation, network traffic or IO latency.

The runtime saves complete growing input/response/tool-result structures at several necessary durability boundaries. Each new state changes the whole JSON hash, so content addressing whole snapshots does not deduplicate their largely shared prefixes. Changing to immutable chunks or deltas plus small atomic state manifests could preserve the same crash guarantees without repeatedly storing the full prefix. Removing safety checkpoints is not the proposed fix. No million-worker extrapolation or storage-performance claim is supported by this small run.

## 7. Context, tools and evidence were handled more honestly than raw success counts suggest

Retry cumulative input was 19,019,962 tokens, of which approximately 96.06% were reported cached. Its largest single-response input was 172,072 tokens, below the 183,808 compaction threshold. It therefore correctly did not compact. The original successful root did compact once, reducing 333 active items to five, continued and produced an accepted proof; that root completed, while another root's fault blocked the overall supervisor. No live handoff occurred in any of these three attempts. The observation demonstrates one successful continuation, not general resistance to repeated context loss.

The eight retry tool refusals were recoverable: a scientific checkpoint requested 1,500 estimated tokens for a mandatory 1,537-token core and succeeded after retrying at 2,500; private checkpoint sharing and checkpoint-as-candidate were refused; malformed IDs and a stale cursor were corrected. Two peer receipt lookups remained inaccessible under record scope, even though the accepted dependency and candidate could be read through permitted tools. A compact, permission-checked shared verification summary would reduce this confusion without exposing private session checkpoints.

The four `lake: command not found` shell failures were login-shell PATH friction, not absence of Lean or VM failure. Normal Lean compilation failures during proof development were also expected. They need distinct categories in dashboards. No recorded OOM event or response-cap hit explains the outcomes.

## 8. The knowledge bank and several research capabilities remain unqualified

All three knowledge-bank searches across these runs returned no items. Library-source searches did supply useful Lean declarations; peer artifacts supplied most new components. Empty searches do not establish a broken index: coverage, query choice and intentionally isolated benchmark stores may all matter. They establish that this success does not validate the accumulated lemma-bank mechanism. A targeted known-premise retrieval and reuse test is still needed.

Similarly, this was a supplied, reviewed Lean target. It does not demonstrate paper ingestion, faithful conversion of a new informal physics claim, discovery of an open result, numerical/certificate-assisted reasoning, competing model families, or sustained recursive delegation. The six tasks formed a shallow root/helper structure; no live continuation links were used. Further testing should explicitly exercise these capabilities rather than assuming a successful proof covers them.

## 9. Work continued after acceptance

Twenty-one model responses settled after first verification, accounting for $6.284783 conservatively. Eighteen requests actually began after verification, accounting for $5.410400, about 11% of the full retry's $49.102475. The distinction matters: already in-flight work cannot be counted as avoidable new spending. The later work included notifications, evidence retrieval, final reports and checkpointing; it is not all waste.

Define a verified-target completion policy: notify every live participant, allow bounded useful wrap-up, then stop further unrelated proof search and settle all external operations. Measure request start time, not just settlement time. Conservative ledger totals and the earlier cache-price estimate are not provider invoice evidence.

## Recommendations before increasing scale

1. Make scheduling age/priority-aware; refresh queued objectives and expose ownership of reusable components.
2. Add immutable file-to-candidate and file-to-artifact transfer, retaining exact independent verification.
3. Replace repeated whole-state persistence with a crash-tested chunked/delta representation.
4. Make peer availability, shared verification status and durable event waits explicit; add a bounded completion policy.
5. Test lemma retrieval, sustained handoff/compaction, strategy diversity and root-level persistence deliberately. Keep these as separate outcomes from verified proof success.

These are proposed changes, not changes implemented by this audit. The VM and monitor remain off. Detailed supporting reports: `deep-mathematical-audit.md`, `deep-collaboration-audit.md`, `deep-runtime-audit.md`, `deep-accounting-audit.json`, and `deep-queue-replay.json`.
