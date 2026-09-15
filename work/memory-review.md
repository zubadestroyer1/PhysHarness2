# Independent portable-memory review

Scope: read-only review of `src/physharness/memory.py`, context API routes/models, and `research_tools`/worker context-tool binding. Reviewed target assumptions/status preservation, branch visibility, lineage, native-state exclusions, and concurrency. This report is the only repository file written for the review. I did not use my own workspace broker/provider implementation as independent review evidence. All reproduction fixtures used temporary local SQLite/artifact stores; no model or paid provider calls.

## Finding reproduced and fixed during review

**P2: a task-associated checkpoint could be issued after its lease expired during artifact storage.**

The original implementation checked `_fenced` at `memory.py:428`, built the scientific payload, and called `artifacts.put` at line 502, then inserted the checkpoint without checking the lease again. An S3 upload or other slow content store can outlast a live lease. The reproduction created a real task/lease through `HarnessService`, set its valid expiration to current time plus 50 ms, and wrapped the real artifact store's `put` with a 100 ms delay. `checkpoint(...task_id,holder,fence)` returned a checkpoint successfully. Immediately checking the same lease returned `STALE_LEASE`; restoring the newly issued checkpoint still succeeded. This did not grant proof status or complete the task, but violated task-associated checkpoint fencing.

The implementation owner added a second `_fenced` check after artifact storage and before the artifact record is inserted (`memory.py:503–504`). I independently reran the same temporary-service reproduction after that change. Observed output:

```text
INDEPENDENT_RECHECK STALE_LEASE
ISSUED_CHECKPOINTS 0
```

The uploaded content-addressed bytes may remain unreferenced when the transaction aborts, but no canonical task checkpoint is issued. The reproduced finding is closed on the reviewed final code. A regression test was added by the implementation owner, not by this reviewer.

## Verified behavior and evidence

- Existing memory/API/sharing tests: **37 passed** before the fix and **38 passed in 1.06 s** afterward. Two existing TestClient dependency deprecation warnings appeared; no failures.
- Independent concurrent identical-command reproduction: eight requests through a four-thread pool produced **one unique checkpoint ID**. No duplicate canonical checkpoint was observed.
- Independent operator-compaction privacy reproduction: a project operator attempted to include another branch's private evidence in the selected branch's checkpoint under `sharing=none`. The derived branch reader rejected the evidence with `NOT_FOUND`.
- Independent actual tool-dispatch reproduction exercised `checkpoint_context` and `restore_context` with the worker's real task/holder/fence tuple. Restored target identity matched the experiment and `native_continuation` was `not_included`. A sibling branch's `restore_context` call under `sharing=ideas` returned a `NOT_FOUND` tool error envelope.
- Exact target/review/environment/assumption/definition snapshots, mandatory open tasks/unproved claims/failed verification attempts, current selected-evidence status/digests, and annotation attribution are covered by the existing real-service tests and corresponding code paths. I found no demonstrated summary-to-proof promotion path.
- Native/private checkpoint artifact kinds are rejected as selected history. Issuance markers, artifact hashes, branch bindings and lineage generations/hashes prevent an ordinary uploaded artifact from impersonating an issued portable checkpoint. Sibling lineage adoption is rejected even when ideas can be shared.
- API context request models reject extra caller-controlled status fields. Worker tool schemas do not allow callers to override the controller-bound task/holder/fence tuple.

## Limits, not additional confirmed defects

The format deliberately distinguishes mandatory canonical science from caller annotations and explicitly selected history. A new checkpoint can replace caller-supplied `unresolved_obligations` with an empty list without providing resolution evidence; its prior annotation remains in the immutable predecessor. I reproduced that behavior. It is consistent with the documented treatment of these fields as unverified annotations, so I have not presented it as an authority bypass. Any product promise that **all** previously mentioned informal obligations survive compaction would need a stronger carry-forward/resolution contract.

Completed dependencies and accepted results are not automatically included in the mandatory core. They remain canonical and can be explicitly selected/retrieved; open task dependencies retain their IDs. This is a limitation to remember when describing full dependency preservation across compaction. The memory API does not automatically replace a runtime's active context or guarantee a provider token budget; the estimator is explicitly bytes divided by four. Those boundaries are accurately stated in `docs/MEMORY.md`.

No further concrete cross-branch, lineage, native-state portability, or status-laundering defect was demonstrated in this review. No live model continuation, production PostgreSQL concurrency, or cloud artifact-store behavior was qualified. Export/review publication integration remained with the separate auditor; this review did not duplicate that audit or claim its results.
