# Native checkpoint persistence: design and consumer map

The current `CanonicalRuntimeStore` writes the complete `RuntimeCheckpoint` JSON at each durability boundary. Its artifact hash changes as `native_state.input`, `responses`, archives and tool results grow, so content addressing the whole snapshot retains repeated prefixes. The replacement keeps each save boundary and its fenced session update. It writes immutable chunks first, then publishes one small versioned checkpoint manifest through the existing fenced canonical session transaction. A crash before that transaction may leave unreachable chunks, but cannot change the current session. Readers reconstruct the complete exact `RuntimeCheckpoint` and run its existing `state_digest` verification. Historical full JSON artifacts remain readable.

The manifest contains a bounded root reference. Fixed fanout, positional pages share stable prefixes across append-only lists, and each read has depth, node, byte and cycle limits. There is no prior-checkpoint or unbounded delta-chain dependency. Every referenced chunk is a private `native_checkpoint_chunk` artifact scoped to the same task and experiment; content hashes and record scope are checked at each edge. Native state remains unavailable to agents. Export includes the complete artifact graph and offline validation checks its closure.

Consumer map:

- `CanonicalRuntimeStore.load` and `ResearchTaskExecutor` restart/recovery/handoff paths read native checkpoints.
- `continuation.py` recovery and handoff reads source checkpoints.
- `continuation_lineage.py` independently validates source and successor checkpoints, including exact state digest and settled state.
- `service.export_experiment`, CLI export and offline `reproduction.validate_export` must retain and verify the manifest's transitive chunk closure.
- `memory.py` handles portable checkpoints and artifacts; it must not receive native state. `workspaces.py` has separate workspace-native checkpoint/artifact paths and is outside this runtime format.

Implementation and regression evidence will be appended below.

## Implemented behavior

`src/physharness/execution/checkpoint_chunks.py` encodes native state into immutable JSON chunks. Lists use fixed positional pages and bounded index fanout; growing dictionaries use a hash trie so random tool-operation keys do not shift prior pages. A manifest contains the version, exact runtime `state_digest`, session identity and one root reference. No manifest references an older checkpoint. The encoder reconstructs its new graph before returning, applying the same maximum depth (32), traversed nodes (200,000), chunk bytes (5 MB) and aggregate graph bytes (256 MB) as the reader. These are finite safety bounds, not measured resource guarantees for a maximum-sized graph.

`CanonicalRuntimeStore` creates private chunks with task and session provenance, caches previously created chunk metadata for the current store instance, and creates the manifest before the existing fenced `runtime.save` transaction updates the current session. Chunk creation is idempotent by scope and content digest. A crash before publication leaves the prior session pointer; a stale fence cannot publish. Historical full JSON checkpoints still load through `HarnessService.load_native_checkpoint` with the original `RuntimeCheckpoint.verify()` hash check. The new decoder checks every artifact kind, experiment, task, session, declared SHA-256 and actual bytes. Runtime restart, recovery and handoff, continuation service and lineage validation use this decoder.

Export retains the transitive graph because chunks are private artifact records in the experiment snapshot. Both server export and offline `validate_export` reject missing, tampered or cross-task/session references and reconstruct the exact checkpoint. They only interpret the versioned runtime manifest; workspace pause snapshots that also use `native_checkpoint` remain on their existing path. Agent identities cannot read the private manifest or its chunks. Portable memory is unchanged.

## Evidence

- The new storage regressions failed before implementation: missing decoder, absent manifest/chunks and unchanged full-snapshot payload growth. The random-key dictionary workload also failed with sorted-key pages (`1,254,068` retained bytes versus `2,579,160` full-snapshot bytes); it passed after hash-trie grouping. The three-transition assertion failed before inline compactions were added (`active_input_epoch` was `[0,0,0,0]`).
- Focused verification: `.venv/bin/pytest -q tests/test_native_checkpoint_chunks.py tests/test_controller_continuation.py tests/test_research_tool_contracts.py tests/test_reproduction.py tests/test_sharing.py tests/test_session_events.py` — 88 passed. Ruff passed for the new codec, tests and persistence-owned service/lineage/reproduction changes. Coordination-owned continuation peer-wait formatting was reported separately to that owner.
- A deterministic 12-boundary append-only sample with distinct 4 KB list items retained 424,329 unique bytes versus 2,581,780 bytes of historical full snapshots. A random-key dictionary sample retained 499,789 unique bytes versus 2,585,102 bytes. These are uncompressed unique payload totals; the chunked form has more artifact records, and this sample does not measure database metadata, latency or RSS.
- Root's read-only historical sample of 96 actual retry checkpoints across six sessions restored all exact state digests. It measured 95,296,193 old full-snapshot bytes and 6,768,864 new unique chunk and manifest bytes (92.897% less). The sample invoked the encoder's `put` callback 71,735 times while producing 4,106 scoped chunk records; the in-process cache prevents repeated artifact creation commands for known content. Details: `work/swarm-hardening-2026-09-25/historical-checkpoint-benchmark.json`.

## Limits

Encoding still walks the full in-memory native state at every safety boundary, as does the existing state-digest calculation. The first save after process restart may replay idempotent chunk creation lookups for already stored chunks because the per-store cache begins empty; steady-state saves reuse the cache. Historical benchmark figures cover a bounded sample, not total experiment storage or live-provider performance. The offline validator verifies byte integrity and scope of exported checkpoint dependencies; it does not independently re-run the proof kernel or grant scientific acceptance.
