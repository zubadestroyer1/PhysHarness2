# S1 live-run audit: where time, tokens and money go

Scope: all 13 completed arms (calibration-doeblin-r2, calibration-aperiodic, pilot-doeblin, S-r2,
I-01..I-08, single), with S-r2 vs I-01..08 vs single as the main contrast. S (attempt 1, $25.00,
failed on 429s) and calibration-doeblin (paused, $1.46) appear only in the totals.
Everything below comes from read-only analysis of `harness.db`, runtime_event artifacts, workspace
operation records and reassembled native checkpoints. Scripts are listed at the end.
**M** marks a measured fact, **E** an estimate or model built on measurements, and **I** an
interpretation.

## 0. Summary (ranked)

1. **The org TPM limit was the main cost of the society (M).** From minute 4 to minute 28, S-r2
   ran at a flat 1.9–2.1M tokens/min, which is the 2M org limit. Model wait in excess of an
   unthrottled baseline was 4,586 agent-s, 39% of all S-r2 agent time. The prover root alone lost
   about 800 s of its 29.2 min. Without that loss it would have finished in about 16 min, the same
   as the I-arm provers. The limiter counts cached tokens: only 3% of S-r2 input was uncached
   (about 60k TPM), yet requests were throttled. So prompt caching does not raise throughput.
   An unthrottled agent of this profile wants 0.45–0.61M TPM, so 2M TPM supports about 4 agents.
   With more agents on the same limit, each agent's progress slows in proportion (E).
2. **Input is about 97% cached, but the price table charges all of it at the full $2.50/M (M).**
   At a 10% cached-input price, S-r2 would cost about $22 instead of $155, and the 13 completed arms
   about $78 instead of $542 (E; the real cached price for gpt-6-sol must be confirmed).
3. **The 210:1 input/output ratio is structural (M/E).** Each turn is one tool call. Its median
   output is 181 tokens, and the whole context is re-sent every turn. Of S-r2's 61.0M input
   tokens, 18% is the fixed prefix re-sent each turn (about 5k tokens of tool definitions plus a
   4.5k-token initial prompt). The other 82% is accumulated history. Tool results make up 78% of
   that history and model output/reasoning 22%. Context grows by about 1.2k tokens per turn. Total
   input is therefore quadratic in session length: the 6 S-r2 roots (about 125 turns each) used 95%
   of the arm's input, and the 34 referees used 5%. There was one compaction in all arms: the
   183,808-token threshold was almost never reached, and S-r2 peaked at 170k.
4. **Harness overhead per turn grows linearly with session length (M).** Each turn does about 6.5
   checkpoint saves. Each save re-serializes and hashes the whole native state, which grows about
   32 KB per turn. 69–73% of that state is provider response echoes, mostly the 21 KB tool schema
   repeated in every stored response. One save costs 15–20 ms at turn 0 and 0.2–0.33 s at turn
   100+. That is about 57 ms of CPU per MB of state, confirmed offline. Saves run synchronously on
   the runner's single event loop and block every agent. In S-r2 they used 651 s, 36% of the
   loop's wall-clock (M). No other session wrote a single event during 961 measured save windows.
5. **Every turn also pays a token-count preflight of 0.4–1.2 s (M/E).** The call is
   `responses.input_tokens.count`, and it uploads the full context before each generation. The
   "pre-generation" window costs 0.60–0.95 s per turn (8–9% of agent time): about 0.4 s at small
   context, rising to 0.85–1.2 s at about 130k tokens.
6. **The workbench is not the bottleneck (M).** Container execution is 8–12% of agent time.
   Lean checks take a flat 2.4 s each (p50) because the local_docker backend forces a fresh REPL,
   and so a fresh `import Mathlib`, for every check. Provisioning takes 0.12 s, destroy 0.08 s and
   export 0.32 s. Verification takes 25–30 s from queue to verified, and 0.05 s from promote to
   queue. 8 Lean automation checks in S-r2 hit the 2 GiB cgroup limit.

## 1. Key numbers per arm

"To verified" runs from the first generation to verification.verified. Agent-busy is the sum of
session time inside turns. Throttle excess is model wait above the unthrottled latency model (§4).
The list price is $2.50/M input and $10/M output. The last column prices cached input at 10%.

| arm | conc | to verified (min) | turns | agent-busy s | s/turn | provider p50/p90 s | throttle excess s | saves | saves s | input M | cached | out k | in:out | list $ | $ if cached@10% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| calibration-doeblin-r2 | 2 | 6.3 | 109 | 693 | 6.36 | 3.6/8.3 | 0 | 679 | 42 | 4.08 | 95.5% | 34.8 | 117 | 10.54 | 1.78 |
| calibration-aperiodic | 2 | 17.5 | 191 | 1411 | 7.39 | 3.8/9.8 | 26 | 1205 | 110 | 13.57 | 97.3% | 69.1 | 196 | 34.61 | 4.92 |
| pilot-doeblin | 4 | 5.9 | 222 | 1429 | 6.44 | 3.2/8.8 | 0 | 1431 | 95 | 8.81 | 96.2% | 72.9 | 121 | 22.75 | 3.69 |
| **S-r2** | 8 | **29.7** | 995 | 11631 | **11.69** | **6.1/20.6** | **4586** | 6526 | 651 | 61.00 | 96.9% | 291.1 | 210 | 155.41 | 22.35 |
| I-01 | 2 | 17.4 | 231 | 2030 | 8.79 | 4.6/13.4 | 227 | 1458 | 172 | 19.44 | 96.9% | 88.5 | 220 | 49.49 | 7.10 |
| I-02 | 2 | 13.6 | 193 | 1548 | 8.02 | 4.3/11.7 | 233 | 1210 | 122 | 13.18 | 97.7% | 61.9 | 213 | 33.58 | 4.61 |
| I-03 | 2 | 14.1 | 193 | 1682 | 8.72 | 4.6/12.7 | 189 | 1216 | 120 | 13.49 | 97.8% | 81.6 | 165 | 34.53 | 4.86 |
| I-04 | 2 | 13.8 | 218 | 1637 | 7.51 | 3.5/11.0 | 173 | 1375 | 146 | 13.76 | 97.3% | 66.5 | 207 | 35.06 | 4.94 |
| I-05 | 2 | 14.5 | 223 | 1729 | 7.75 | 4.0/8.4 | 0 | 1411 | 153 | 15.19 | 97.5% | 94.3 | 161 | 38.92 | 5.59 |
| I-06 | 2 | 11.7 | 142 | 953 | 6.71 | 3.3/8.6 | 0 | 890 | 77 | 7.24 | 97.4% | 49.6 | 146 | 18.60 | 2.74 |
| I-07 | 2 | 17.0 | 235 | 1641 | 6.98 | 3.6/8.5 | 78 | 1465 | 170 | 15.49 | 98.1% | 63.6 | 243 | 39.37 | 5.16 |
| I-08 | 2 | 13.6 | 236 | 1556 | 6.59 | 3.1/9.8 | 70 | 1483 | 127 | 14.52 | 97.3% | 67.5 | 215 | 36.99 | 5.19 |
| single | 2 | 13.8 | 224 | 1465 | 6.54 | 3.5/8.0 | 0 | 1408 | 110 | 12.50 | 96.3% | 72.3 | 173 | 31.97 | 4.89 |

Totals for the 13 completed arms (M): 212.3M input tokens, of which 206.2M (97.2%) were cached
and 5.27M (2.5%) were reported as `cache_write_tokens`. Output was 1.11M tokens, including 0.31M
reasoning tokens. List cost was $541.82 (it matches the ledgers). With cached input priced at
10%/25%/50%, the cost would be $77.81/$155.15/$284.04 (E). Output is only about 2% of list cost.

Provider latency (gs→usage, raw) by class (M):

| class | turns | p50 | p90 | p99 | max |
|---|---|---|---|---|---|
| S-r2 | 995 | 6.1 s | 20.6 s | 49.3 s | 74.3 s |
| I-01..08 | 1671 | 3.9 s | 10.7 s | 23.5 s | 42.2 s |
| single | 224 | 3.5 s | 8.0 s | 16.4 s | 28.7 s |
| calibration+pilot | 522 | 3.5 s | 9.2 s | 17.9 s | 31.0 s |

## 2. Per-turn time budget (stacked)

### Method (E)

The model loop (`execution/responses.py:_loop`) runs this sequence each turn:

1. save A (pending_operation)
2. `generation_started`
3. provider call (429 resends included)
4. save B, then `usage`
5. save C
6. for each tool call: save D, dispatch, save E, `tool_completed`
7. save F (settled boundary)
8. optional delivery and turn-note saves
9. `input_tokens.count` preflight
10. save A of the next turn

Saves C (usage → next `session.saved`) and F (last `tool_completed` → next `session.saved`) are
fully observed. Their mean is the per-save cost S for that turn, and it is applied to every save
in the turn. Container time comes from `workspace.operation.pending/completed` events. Uploads,
provisions and similar ops are attributed to the tool call they fall inside. The throttle excess
comes from a latency model fitted on arms that stayed below 2M TPM (single + calibrations +
pilot):

`latency = 1.70 s + 7.0 ms × output_tokens + 0.030 ms × uncached_input + 0.010 ms × input`

The model's fitted excess is −2% to +2.5% on the arms it was fitted to.

### Seconds per turn (share of agent-busy time)

| component | S-r2 | I-01..08 | single | cal+pilot |
|---|---|---|---|---|
| model generation (unthrottled baseline) | 4.40 (37.6%) | 4.75 (62.1%) | 4.49 (68.6%) | 4.61 (68.1%) |
| throttle excess (rate limit) | **4.61 (39.4%)** | 0.58 (7.6%) | 0.00 | 0.05 (0.7%) |
| pre-generation (count preflight + update polling) | 0.95 (8.1%) | 0.67 (8.7%) | 0.60 (9.2%) | 0.61 (9.0%) |
| checkpoint saves (about 6.5 per turn) | 0.65 (5.6%) | 0.65 (8.5%) | 0.49 (7.5%) | 0.47 (7.0%) |
| Lean in container | 0.72 (6.1%) | 0.69 (9.0%) | 0.69 (10.6%) | 0.65 (9.6%) |
| search_library scan | 0.12 (1.0%) | 0.07 (0.9%) | 0.05 (0.8%) | 0.15 (2.3%) |
| shell (non-Lean) | 0.10 (0.8%) | 0.09 (1.2%) | 0.08 (1.2%) | 0.05 (0.7%) |
| uploads/read/promote | 0.08 (0.7%) | 0.02 (0.3%) | 0.01 (0.2%) | 0.02 (0.3%) |
| provision/restore | 0.02 (0.2%) | 0.01 (0.1%) | 0.01 (0.1%) | 0.01 (0.2%) |
| tool logic (commons/DB) | 0.04 (0.4%) | 0.12 (1.6%) | 0.12 (1.8%) | 0.14 (2.1%) |
| **total** | **11.69** | **7.65** | **6.54** | **6.77** |

```
S-r2       11.69 s/turn |MMMMMMMMMMMMMMMMMMMMMMTTTTTTTTTTTTTTTTTTTTTTTPPPPPSSSLLLLWW
I-01..08    7.65 s/turn |MMMMMMMMMMMMMMMMMMMMMMMMTTTPPPSSSLLLWo
single      6.54 s/turn |MMMMMMMMMMMMMMMMMMMMMMPPPSSLLLWo
cal+pilot   6.77 s/turn |MMMMMMMMMMMMMMMMMMMMMMMPPPSSLLLWo
1 char = 0.2 s; M=model (unthrottled) T=throttle excess P=pre-gen preflight+polling
S=checkpoint saves L=Lean in container W=other container ops o=tool logic
```

Agent-busy time covers 99.4% of leased time in S-r2 (11,631 of 11,697 s) and 99–100% in the I
arms, so the decomposition closes (M).

### Overhead grows with turn index (M)

Values are medians. "Pre-gen window" runs from the end of save F to the end of save A, so it
includes one save.

| turn index | full save, S-r2 / I | pre-gen window, S-r2 / I | DB-only tool call (3 saves + logic), S-r2 / I |
|---|---|---|---|
| 0–19 | 14 / 22 ms | 433 / 396 ms | 69 / 81 ms |
| 40–59 | 105 / 111 ms | 993 / 731 ms | 385 / 362 ms |
| 80–99 | 185 / 194 ms | 1,250 / 975 ms | 631 / 632 ms |
| 100–119 | 225 / 217 ms | 1,444 / 1,064 ms | 757 / 717 ms |
| 120–139 | 328 / 249 ms | 1,371 / 1,097 ms | 904 / 962 ms |

By turn 100, the non-model overhead per turn is about 2.3–2.6 s: 6.5 saves at about 0.22 s, plus
about 0.9–1.2 s of preflight. At turn 0–19 it is about 0.55 s. For the 93–140-turn prover sessions
that decide every arm, that overhead reaches about 50% of the unthrottled model time late in the
session (E).

### Slots, queues and peer waits (S-r2, M)

- The 8 slots gave 14,301 slot-s. Of that, 11,697 s was leased and 2,604 s (18.2%) was idle.
  About 700 s of the idle time was roots parked in `peer_wait` (7 requests, 712 s parked). The
  rest came after about minute 15, when only 4–6 roots stayed active.
- The 6 roots held 6 of the 8 slots for the whole run, so the 34 referee tasks queued for the other
  two. Queue wait was 2,234 s in total, with p50 33 s and max 312 s. Referee work was cheap: 209
  turns and 3.2M input tokens (5%). The review latency was scheduling latency.
- Lease → first generation took p50 0.62 s and max 2.2 s. Last runtime event → task.completed took
  p50 0.24 s (workspace export + destroy).
- `verification_status` blocked the calling turn for 20.9 s in S-r2, and averaged 17.6 s over 9
  calls in the I arms. That is the agent waiting on the verifier inside a turn.

## 3. Tokens

### Caching (M)

Cached share is 95.5–98.1% in every completed arm. Prompt caching happens automatically: the
request uses `store=False` and the full input is re-sent, and the provider matches the prefix.
The price table (`prices.json`: "cached discounts omitted") and the ledger price all input at
$2.50/M, so the reported $155.41 for S-r2 is an upper bound. If cached input costs 10% of list,
S-r2 cost $22.35 (E). The model reservation per generation is $1.28 (256k input + 64k output at
list). A median S-r2 turn costs $0.156 at list, so each reservation is about 8× the real spend.
At 100 concurrent agents, $128 would sit reserved at any moment (E).

### What drives 210:1 (M/E)

- The output per turn is one function call: p50 181, p90 623, p99 1,680, max 3,234 tokens in S-r2.
  Reasoning tokens are 27% of output. `parallel_tool_calls=False` forces one action per model
  round-trip.
- Each turn's input is the whole context, so input/output ≈ mean context / mean output = 61.3k/293.
- The first turn's input is p50 11.3k in S-r2 and 10.0k in I. It consists of tool definitions
  (24 tools, 21 KB JSON, about 5k tokens; `commons_node` alone is 3.6 KB) and the initial user
  prompt (18.6 KB, about 4.5k tokens). This fixed prefix, re-sent every turn, is **18.1%** of S-r2
  input (15.1% in I).
- Context grows 1.22k tokens per turn in S-r2 and 1.32k in I. Previous output (including
  reasoning items) is 25% of that growth, and tool results plus injected deliveries are 75%.
- Weighting each addition by how many later turns re-read it gives the history-token share by
  source:

| source | S-r2 | I-01..08 | single |
|---|---|---|---|
| model outputs/reasoning carried | 21.7% | 22.5% | 21.1% |
| search_library | 18.2% | 10.2% | 4.5% |
| shell | 13.8% | 34.3% | 53.0% |
| read_source | 12.4% | 13.1% | 5.8% |
| commons_read | 10.2% | 3.8% | 5.3% |
| lean_check | 8.3% | 4.9% | 1.2% |
| commons_post / commons_node | 6.0% / 4.6% | 1.6% / 1.7% | 1.5% / 2.0% |
| all society tools (commons_*, notebook, inbox, message, reviews, wait) | 24.4% | 9.2% | 10.1% |

- Per-call additions are largest for read_artifact (16.4k tokens mean, I), notebook (10k),
  read_source (5.4–7.8k) and read_file (4–6k). search_library and shell average about 1.1–1.5k,
  with p90 values of 2.5–3.7k.
- Total input ≈ n·base + g·n²/2. For a 125-turn root: 1.25M + 9.4M ≈ 10.6M, matching the observed
  10.3–11.0M. The quadratic history term is 88% of it (E).
- **Compaction:** there was one provider compaction in all arms (I-01, one session). No S-r2 session
  reached the 183,808 threshold (max input 170,052 tokens).

### Counterfactual context budgets (E)

These keep each trajectory fixed and change only what is re-sent. Compaction resets to base + a
6k-token summary and charges one full-context request plus 3k output tokens per compaction.
"Elide>K" replaces tool results older than K turns with a 40-token stub, evicting in blocks every
K turns so the cache survives.

| scenario | S-r2 input | tokens/turn | throughput at fixed TPM | S-r2 list $ | S-r2 $ cached@10% | all 13 arms input |
|---|---|---|---|---|---|---|
| observed | 61.0M | 61.6k | ×1.00 | 155.41 | 22.35 | 212.3M |
| compact at 128k | 51.5M (84%) | 52.1k | ×1.18 | 131.80 | 19.47 | 91% |
| compact at 96k | 42.3M (69%) | 42.8k | ×1.44 | 108.73 | 16.56 | 75% |
| compact at 64k | 34.0M (56%) | 34.6k | ×1.79 | 88.47 | 14.21 | 60% |
| compact at 48k | 28.3M (46%) | 28.8k | ×2.16 | 74.28 | 12.66 | 50% |
| elide tool results > 20 turns | 40.9M (67%) | 41.4k | ×1.49 | 105.15 | 15.94 | 71% |
| elide tool results > 10 turns | 33.4M (55%) | 33.8k | ×1.83 | 86.28 | 13.54 | 57% |

Quality effects are not modelled (I). These cuts need an A/B test on prover success, not only on
tokens.

## 4. Rate-limit throttling in S-r2

### Tokens per minute (M)

The table shows input+output tokens per minute, counted at usage time. Excess is mean latency
above the unthrottled model per request.

| minute | req | total TPM | mean latency | mean excess | avg in-flight |
|---|---|---|---|---|---|
| 0 | 97 | 1.78M | 2.3 s | 0.2 s | 4.0 |
| 1–3 | 58–70 | 2.30–2.84M | 3.9–4.7 s | ≈0 | 4.4–5.3 |
| 4–9 | 38–47 | 1.95–2.10M | 7.5–11.4 s | 2.2–6.8 s | 6.0–6.7 |
| 10–20 | 16–33 | 1.90–2.10M | 11.4–19.1 s | 6.5–12.5 s | 4.0–6.5 |
| 21–26 | 17–24 | 1.88–2.09M | 10.4–13.2 s | 5.0–7.7 s | 3.4–5.0 |
| 27–29 | 17–23 | 1.66–2.05M | 6.5–8.2 s | 1.9–2.6 s | 1.7–3.0 |

### Reading the table

- **M:** Average throughput was 2.06M TPM over 29.8 min. The first 3 minutes burst above 2M,
  consistent with a token bucket. From minute 4 onwards throughput held a flat plateau of
  1.88–2.10M TPM while mean latency tripled. The plateau is in *total* tokens, cached included:
  uncached input ran at only about 60k TPM, so the limiter counts cached tokens.
- **M:** The limiter does *not* appear to count the 64k `max_output_tokens` reservation. Input
  plus 64k per request would have been 3–8M "TPM", far above the plateau.
- **E:** The excess model wait was 4,586 agent-s, 51% of S-r2's model wait. Resends are silent:
  `_rate_limit_wait` sleeps and logs nothing, so there is no direct 429 count. This excess is the
  best available proxy. The I pairs that shared the org (I-01+02, I-03+04, I-07+08) also sat at
  2.0–2.9M in several minutes and show +7% to +21% excess. I-05+06 stayed at or below 1.96M and
  shows none.
- **Unthrottled per-agent demand (M):** 530k TPM on average in I-arm sessions (0.45–0.61M across
  classes), at 7.8 requests/min and 67.6k tokens/request. So 2M TPM supports about 3.8 such
  agents. S-r2 put 8 on it and got 316k TPM per agent.
- **Impact on the result (E):** The verified root (task 1c00e232) took 127 turns in 29.2 min
  (4.3 turns/min), with 1,403 s of model wait of which about 800 s was excess. The I-arm provers
  needed 93–140 turns at 6.6–8.8 turns/min. The society did not reduce the turns a proof needs.
  The 2× longer time-to-verified is explained by the TPM ceiling plus heavier per-turn overhead.
  S-r2's aggregate rate was 33.4 turns/min, about what two concurrent I arms achieved together
  (28–30).

## 5. Harness and persistence overhead

### Native checkpoints (M)

- S-r2 made 6,526 saves: 6.56 per turn and 6.3 per turn in the other arms. Across the arm that is
  about 3.6 saves/s, one every 1.8 s per active session.
- The chunk graph makes bytes cheap. Each save writes about 5.9 new chunks and 9.2 KB, for a total
  of 38,698 chunks (61.6 MB) plus 6,526 manifests (2.1 MB) in S-r2.
- CPU is not cheap. Each save runs:
  - `RuntimeCheckpoint.build`: a deepcopy plus a full canonical-JSON sha256
  - `verify()`: runs twice, once in `CanonicalRuntimeStore` and once in `encode`
  - an encode-time size check: one more full canonical-JSON dump
  - a walk that re-serializes and hashes every node, including unchanged ones
- Offline timing on reassembled final states gives **CPU per save ≈ 57 ms per MB of state**, with
  n=37 sessions of 1 MB or more. A 4.0 MB S-r2 root costs 38 ms build + 12 ms verify + 175 ms
  encode = 225 ms, which matches the 0.2–0.33 s saves measured in the run.
- The final state of a 125-turn session is about 4 MB. Stored `responses` are **69–73%** of all
  state bytes. Each stored response echoes the 21 KB `tools` array, so about 2.65 MB of a 4.0 MB
  root is repeated tool schemas. `tool_results` duplicates the function outputs already in
  `input` and is another 11–13%.
- Saves are synchronous inside `async def save` and run on the **single event loop** of
  `run-team`. In 961 measured F-save windows (98 s in total), **zero events from other sessions**
  were written. In S-r2, saves used 651 s of the 1,788 s wall-clock, **36% of the loop** (E, lower
  bound). The I arms used 11–18%, with 2 sessions per process.
- Per 995 turns, SQLite write amplification in S-r2 is about 170 rows per turn (M):
  - 48,439 artifact records
  - 60,419 events
  - 59,983 `commands` idempotency rows: the largest table at 60 MB of pages, holding 40.6 MB of
    stored results

  A save is about 8 separate transactions (one per chunk artifact, plus the manifest and the
  session update). Each artifact write also fsyncs its file and its directory. `harness.db` runs
  with `journal_mode=delete`, not WAL. The measured cost is about 1.5–2 ms per artifact write, and
  the database reached 171 MB for 995 turns.

### Pre-generation window (M/E)

- Between save F and save A the loop runs `_receive_updates`, `_receive_turn_note`,
  `client.responses.input_tokens.count` and the context check. With saves removed, this costs about
  0.37–0.42 s per turn at small context and 0.85–1.2 s at about 130k tokens.
- The count call re-uploads the full input, so the payload grows with context. It runs once per
  generation: 995 extra full-context API calls in S-r2.
- With `context_management` on, its result is used only for the context-limit check: the input
  reservation is `max_context_tokens` regardless.
- Update polling cannot be separated from these logs. S-r2's window is 25–50% longer than the I
  arms' at the same turn index, which suggests loop contention or society delivery polling (I).

### Other harness costs (M)

Resource reservation and settlement plus event emission take about 4 ms per turn (the tail from
save A to `generation_started`).

## 6. Workbench and infrastructure

### Container operations (M)

Durations are p50/p90. n is the number of operations.

| op class | S-r2 n, sum | S-r2 p50/p90 | I-01..08 n, sum | I p50/p90 |
|---|---|---|---|---|
| Lean REPL check (inline, fresh process) | 198, 628 s | 2.67/4.14 s | 259, 648 s | 2.38/2.59 s |
| `lake env lean` via shell | 18, 45 s | 2.92/3.84 s | 211, 489 s | 2.41/2.91 s |
| statement verify (checker) | 62, 17 s | 0.18/0.45 s | 58, 12 s | 0.18/0.25 s |
| REPL backend probe | 35, 22 s | 0.26/1.81 s | 23, 6 s | 0.18/0.45 s |
| search_library (os.walk over physlib+Mathlib) | 106, 119 s | 0.93/1.55 s | 145, 120 s | 0.84/0.92 s |
| shell (other) | 102, 96 s | 0.32/1.62 s | 399, 151 s | 0.19/0.49 s |
| upload | 390, 79 s | 0.05/0.46 s | 492, 35 s | 0.05/0.06 s |
| export | 46, 25 s | 0.32/1.50 s | 34, 14 s | 0.35/0.77 s |
| provision | 39, 13 s | 0.12/0.84 s | 29, 4 s | 0.11/0.12 s |
| restore | 5, 3.6 s | 0.76/0.84 s | 4, 2.9 s | 0.60/1.15 s |
| destroy | 39, 4.6 s | 0.08/0.10 s | 29, 2.1 s | 0.08/0.09 s |

### Lean checks (M)

- On local_docker, `lean_check` uses the `repl_inline` backend: the provider requires a quiescent
  guest after each command, so every check starts a REPL and imports Mathlib.
- That floor is about 2.3 s per check. Cold and warm are almost the same: the first check in a
  workspace takes 2.94 s against 2.60 s later in S-r2, and 2.40 s against 2.37 s in I.
- The olean page cache stayed hot all day: pre-warm read 2.65 GB in 1–2 s before every arm.
- Contention: in S-r2 a check took 2.36 s p50 with no overlapping container command, and 2.8–3.0 s
  with 2 or more.
- Memory: Lean check peak RSS was 840 MiB p50. 8 S-r2 checks, and 5 in I/single, reached the
  2 GiB cgroup limit (`cgroup_oom_observed`, 22 OOM events in S-r2; all were heavy automation
  requests).

### Uploads and exports (M)

S-r2's 390 uploads were:

- 198 REPL request files (argv cannot carry stdin)
- 111 harness bootstrap copies: 35 `lean_session.py`, 38 `statement_check.py` and 38
  `statement_check.lean`, one set per workspace
- 62 verify-statement Source/Reference pairs
- 19 agent `write_file` calls

The 46 exports were 39 final workspace checkpoints (one per task workspace; 39 workspaces for 40
tasks, since every referee got its own) and 7 handoff exports. Workspace checkpoint artifacts
totalled only 1.6 MB.

### Verification (M)

Promote → `verification.queued` took 0.05–0.13 s, and queued → verified took 24.8–30.4 s in every
arm (S-r2 27.2 s). That covers the Comparator builds (1.8 s + 2.6 s), lean4export, nanoda and the
Lean kernel replay, in an 8 GiB, 4-CPU container with 1 checker slot. It runs through
`asyncio.to_thread`, so it does not block the loop.

## 7. Timelines

| step | S-r2 | I-01..08 | single |
|---|---|---|---|
| experiment.created → task.queued (operator check-run/preflight/pre-warm/launch) | 20.3 s | 13.7–16.7 s | 14.4 s |
| task.queued → leased | 0.08 s | 0.06–0.1 s | 0.06 s |
| leased → first `generation_started` | 1.29 s | 0.6–1.35 s | 3.24 s |
| first generation → first response | 1.9 s | 2.0–2.6 s | 1.9 s |
| first generation → first workspace provision (lazy, at the first workbench tool) | 3.6 s | 7.4–10.7 s | 13.5 s |
| proof promote → verification.queued | 0.06 s | 0.05–0.13 s | 0.06 s |
| verification queued → verified | 27.2 s | 25.5–30.4 s | 24.8 s |
| first generation → verified | 29.7 min | 11.7–17.4 min | 13.8 min |

Startup is not a cost: launch to the first model call takes 1–3 s. The 14–20 s before launch is
operator scripting.

## 8. Scaling projection (10× / 100× agents)

Assumption: per-agent work equals S-r2's. "Linear" means linear in agent-turns.

| cost driver | growth | measured at 8 agents (S-r2) | at 80 agents | at 800 agents |
|---|---|---|---|---|
| model tokens / $ | linear in agents; **quadratic in session length** | 61M tokens, $155 list (about $22 at cached 10%) | about 610M, $1.55k (about $220) | about 6.1B, $15.5k (about $2.2k) |
| org TPM (2M) | fixed ceiling; demand linear (0.53M/agent) | 4.2M demand vs 2M: 39% of agent time waiting | 42M demand, 21× oversubscribed: each agent gets 1/21 of its unthrottled turn rate | 420M demand, 210× |
| aggregate turn rate under 2M TPM | pinned at about 2M / tokens-per-turn | 33 turns/min | 33 turns/min, so each agent is about 10× slower | same, about 100× slower |
| checkpoint CPU on one event loop | linear in turn rate × state size (state ∝ turns) | 0.65 s of loop time per turn, 36% busy at 33 turns/min | saturates near 90 turns/min (about 12 unthrottled agents) if TPM is raised | multi-process required |
| SQLite commits (rollback journal, fsync per artifact) | linear in turns: about 52 commits/turn | about 29/s, 171 MB DB | about 290/s at 10× TPM | about 2,900/s, beyond a single SQLite file |
| workbench RAM | linear in concurrently active Lean checks | ≤5 overlapping, 0.84 GiB p50 each, cap 2 GiB | about 40 GiB if TPM allowed about 50 overlapping checks | about 400 GiB, needs many hosts or a shared Lean server |
| referee queue | linear in claims; slot budget fixed | p50 33 s, max 312 s | grows with roots × about 5.7 referee tasks per root | — |
| verification | linear in submissions | 27 s, 1 slot, about 130/h capacity | fine | fine unless submissions exceed about 100/h |
| exports / artifact store | linear in saves | 47.5k files, 255 MB export (the `phys export` HTTP timeout) | about 2.5 GB | about 25 GB |

What breaks first (E):

- Under the current 2M TPM, extra agents add almost nothing. The society's turn rate is already
  pinned, so wall-clock per unit of work grows about linearly with N beyond about 4 agents.
- Raise TPM about 10× and the next wall is the runner's single event loop plus SQLite write
  amplification, at about 12–15 agents of this profile per process.
- Lean RAM becomes the limit only after both are fixed.

## 9. Ranked bottlenecks (evidence)

1. **TPM ceiling, counting cached tokens.** Measured at 4,586 agent-s (39%) in S-r2, plus a
   13-minute prover delay (§4). It scales super-linearly in effect: every added agent slows all
   others.
2. **Context re-send per turn.** 61.6k tokens per turn to produce 293 output tokens. History is
   quadratic in session length, and roots used 95% of tokens (§3). This one number sets TPM
   pressure, cost and provider latency.
3. **Price accounting ignores caching.** Reported costs are about 7× the likely bill, and
   reservations are about 8× the real per-turn spend (§3).
4. **Persistence on the hot path.** About 6.5 full-state saves per turn at about 57 ms/MB, 70% of
   the state being echoed tool schemas. That is 5.6–8.5% of agent time and 36% of the S-r2 event
   loop, grows linearly within a session, and blocks every agent (§5).
5. **Per-turn token-count preflight.** 0.6–0.95 s per turn (8–9%), growing with context, with an
   extra full-context upload per turn (§5).
6. **Slot allocation.** Roots held 6 of 8 slots, so referees queued 2,234 s in total (max 312 s)
   while 18% of slot time sat idle late in the run (§2).
7. **Lean re-import per check.** 2.4 s floor, 6–10% of agent time; occasional 2 GiB OOMs (§6).
8. **Minor items:** search_library full scan (0.9 s, about 1%), 111 bootstrap uploads and 198
   request-file uploads (0.7%), and `verification_status` blocking a turn for 17–21 s.

## 10. Recommended changes and estimated impact

| # | change | expected impact (E) |
|---|---|---|
| 1 | **Raise TPM or spread load across models/orgs.** Budget about 0.55M TPM per unthrottled agent. Add a client-side TPM governor that admits turns by tokens and prioritises the prover path. Log every 429 wait (count and seconds) as a runtime event. | Removes the 39% throttle share in S-r2 (about 4.6 s/turn). The prover path returns to about 16 min. The governor turns silent 30 s back-off sleeps into explicit scheduling. |
| 2 | **Context budget.** Lower the compaction threshold toward 64–96k, or elide tool results older than 10–20 turns in blocks. Cap read_source/read_artifact/notebook outputs (4–16k tokens each). Shrink the fixed prefix (tool schemas about 5k tokens; `commons_node` alone 3.6 KB). | −31% to −45% input tokens, so ×1.4–1.8 throughput at a fixed TPM and −31% to −45% list cost (§3 table). Halving the prefix alone saves about −9%. Needs a quality A/B test. |
| 3 | **Allow parallel tool calls or batched tool actions** (for example read+search, or several lean_checks). | Each saved round-trip removes one full-context re-send. A mean of 1.5 calls per turn cuts turns about 33% and input by more (the quadratic term). |
| 4 | **Price cached input** in `prices.json`, the ledger and reservations, using the cached rate and `cache_write_tokens`. Size the reservation from the last usage instead of 256k+64k. | Reported cost about −86% if cached is priced at 10% (S-r2 $155 → about $22; all arms $542 → about $78). Reservations drop about 8×, which keeps 100-agent budgets from being tied up. |
| 5 | **Lighter checkpoints.** Store only `id`, `status`, `usage`, `output`, `model` and `created_at` per response (drop the echoed `tools`, `text` and settings). Stop duplicating `tool_results` for completed calls. Compute the state digest from the chunk-tree root instead of 3 extra full canonical dumps. | State −80%, so save CPU per save −80%. The per-turn overhead no longer grows about 20× over a session. S-r2 would save about 520 of its 651 save-seconds and free about 30% of the event loop. |
| 6 | **Fewer, off-loop saves.** Coalesce C+D and E+F (6.5 → about 3 saves per turn). Run `_save_checkpoint` via `asyncio.to_thread` or a writer process. Write one transaction per save. Switch `harness.db` to WAL with `synchronous=NORMAL`. Skip `commands` rows for content-addressed chunk puts. | Combined with #5, persistence goes from 0.65 s to about 0.05–0.08 s per turn (−7% agent time). Commits drop about 5×. The runner's loop no longer serialises agents, which is needed before scaling past about 12 agents per process. |
| 7 | **Remove the per-turn `input_tokens.count` preflight.** Use the previous usage.input_tokens plus a local estimate of appended items, and let server-side compaction handle overflow. Keep an exact count only near the limit. | −0.4 to −1.2 s per turn (about −8% agent time; up to about 950 s in S-r2), and 50% fewer full-context uploads. |
| 8 | **Separate the referee concurrency pool** (for example 2–4 slots reserved), or run referees in a lightweight pool. | Referee queue waits of 2,234 s (p50 33 s) drop to near 0. Faster review feedback to roots. |
| 9 | **Persistent Lean.** Add a warm REPL per workspace with the import cached (allow one background process on local_docker), or a shared per-host Lean service. | Per check 2.4 s → an estimated 0.3–0.5 s. That saves about 430 s in S-r2 and about 940 s across I (3–7% of agent time), and cuts about 0.84 GiB of import RSS per check. A shared service avoids N copies of Mathlib in RAM. |
| 10 | **Small infrastructure fixes.** Bake `lean_session.py` and `statement_check.*` into the image (−111 uploads). Pipe REPL requests over stdin (−198 uploads). Prebuild a search index in the image: search_library 0.9 s → about 0.05 s. Make `verification_status` non-blocking or event-driven. | About −1.5% of agent time, about −50% container ops per Lean check, and 17–21 s of turn-blocking removed per verification poll. |

Priority for a 10–100× society: #1 and #2 first, because they set throughput. #4 matters for
correct budgets. #5–#7 are needed before one runner process can host more than about 12 active
agents. #8–#10 are local wins.

## 11. Caveats

- The throttle excess is inferred: the harness does not log 429 resends. The baseline was fitted on
  arms at or below 1.33M TPM (R² is moderate). Part of the S-r2 excess may be provider-side slowness
  under load (I).
- The per-save cost of saves A, B, D and E is inferred from the fully observed C and F saves of the
  same turn. The overhead growth table is measured directly.
- Offline CPU timings were taken on the same host after the run, without DB writes or container
  load. They agree with the in-run save windows.
- Cached-input pricing for gpt-6-sol is unknown here. The 10/25/50% scenarios are illustrative.
- Counterfactual token savings assume unchanged trajectories.

## 12. Reproduce

All scripts are read-only on run data and write under
`<repo>/.superpowers/live-run/audit/scripts/out/`. Run them from `<repo>` with `PYTHONPATH=src`
and `.venv/bin/python`.

1. `scripts/timecost_extract.py`: per-arm tables into `out/extract_<arm>.json`.
2. `scripts/timecost_checkpoints.py`: reassembles the final native checkpoint of every session,
   measures composition, and times offline save CPU. Output: `out/checkpoints.json`.
3. `scripts/timecost_analyze.py`: turn reconstruction, save-cost attribution, latency model and
   stacked components. Output: `out/analysis.json`.
4. `scripts/timecost_simulate.py`: context-budget counterfactuals. Output: `out/simulate.json`.

`scripts/timecost_lib.py` holds the shared turn reconstruction.
