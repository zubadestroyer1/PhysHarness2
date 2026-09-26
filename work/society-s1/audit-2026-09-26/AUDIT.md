# S1 live-run audit: bottlenecks, friction and what worked (2026-09-26)

**Scope.** Every agent log from all 15 S1 arms:
- 123 model sessions, 3,774 provider turns and 3,701 tool calls;
- 222.5M input tokens, costing $568.29 in the ledger.

A read-only extraction rebuilt every transcript. It reconciles exactly with the budget ledger and the metrics files in all 15 arms.

Five parallel analyses produced the dimension reports this summary draws on. They are cross-checked, and the load-bearing claims were re-verified against the data:
- [time and cost](timecost.md);
- [society and coordination](society.md);
- [tool friction](tools.md);
- [proof paths](proofpath.md);
- [scaffolding](scaffolding.md).

**The question:** what stops this ecology from scaling to a free-forming scientific institution with minimal scaffolding, and what should change?

**Labels:** **[M]** marks a measured fact; **[E]** an estimate from a model or counterfactual; **[I]** an interpretation.

---

## 1. The short answer

The society idea was not what held the society back. Its costs came from **plumbing that grows faster than the number of agents**, and from **coordination rules that added work without deciding anything**. The agents themselves self-organized quickly and shared real work.

In S-r2 (6 roots, 8 workers) the society took 29.7 min and $155. The independent one-root runs took a median of 14 min and $36. That gap breaks down as follows:

| Where S-r2's time and money went | Evidence |
|---|---|
| **Provider rate limit.** 39% of all agent time was spent throttled [M]. The prover lost about 13 of its 29 min; unthrottled, it would have finished in about 16 min, like the independent runs [E]. | The org limit is 2M tokens/min and it **counts cached tokens**. One agent wants about 0.5M TPM, so only about 4 agents fit. |
| **Roots kept spending after their part was done.** $56 (36% of the arm) [M]. | No idle or yield policy; one long-pole component; one assembler. |
| **Integration by copy and paste.** 71% of the final proof was written by other roots, but it moved as pasted post text. One agent spent 14 min assembling it [M]. | No shared, importable lemma store. The dependency graph recorded only 1 cross-branch dependency. |
| **Broadcast context rent.** Coordination took 35% of root input tokens and 53% of root turn time [M]. | Every post to the goal thread is pushed to everyone (O(n²)). 20% of pushed items were the reader's own posts, and only 8% were ever opened in full. |
| **Referee machinery that gated nothing.** 34 of 40 task slots; 85% of reviewed lemmas had already compiled before the verdict [M]. | The node "compiles locally" rung never worked because of a harness bug (below), so fidelity reviews filled the gap and decided nothing. |

---

## 2. What worked well (keep)

- **Verification integrity.**
  - All 13 first proof submissions were accepted by Comparator, Lean and nanoda [M].
  - The kernel is the only arbiter. Unreviewed critical-path lemmas were accepted correctly, because only the verifier decides.
  - "Compile locally, then submit" was reliable.
- **Self-organization from a minimal seed.**
  - A 66-character objective and "Independent approach N" branch titles were enough [M].
  - The society divided the work within 72–120 s, and four roots that collided on one lemma re-assigned themselves within 15–20 s [M].
  - Real cross-agent reuse happened: the accepted proof contains code from all 6 roots.
- **Robustness after the rate-limit fix.**
  - No task failed and every arm drained cleanly.
  - Continuations restored in 1–5 s. Host RAM never fell below level 73.
- **Cheap, recoverable guards.**
  - Rejections were 1.4% of calls and 1.6% of spend. They were followed within 1–2 turns whenever the remediation text was precise.
  - There were no loops: the stagnation detector never fired, because nothing looped.
- **Cheap, honest referees.** A median of $0.23 and 46 s each. The one negative verdict was correct and came with a counterexample.
- **Cache-friendly transcripts.** Append-only context gave 97% cached input [M].
- **One general shell covered the gaps.** It handled file edits, regex search and hashing with 0 failures, which argues for fewer, more general tools.
- **Mathematical creativity.** The runs used five different existence routes; one contraction lemma was reused for existence, uniqueness and rate; and agents corrected each other's API names.

---

## 3. Bottlenecks, ranked by what they cost at scale

### A. Throughput ceiling: the provider's tokens-per-minute limit (binds first)
- S-r2 ran at a flat 1.9–2.1M TPM from minute 4 to minute 28. Throttle excess was 4.6 s per turn (39%) [M].
- The limiter counts cached input. Only about 60k TPM of it was uncached, yet requests were throttled [M].
- Demand grows linearly with agents while the cap is fixed. At 2M TPM the harness supports **about 4 agents of this profile**. Past that, every agent slows proportionally [E].
- The current wait behaviour is silent back-off sleeps. It is invisible in the logs and does not prioritise the critical path.

### B. Context rent: input tokens grow quadratically with session length
- Every turn is one tool call. Median output is 181 tokens, and the whole context is re-sent each time. The input/output ratio is about 186–210:1 [M].
- Context grows about 1.2k tokens per turn, so input ∝ turns². The 6 S-r2 roots made 95% of the arm's input [M].
- Composition of all input [M]:
  - tool outputs: **56%** (library look-ups alone 39.5%, and 255 outputs of at least 8k chars carry 53% of the re-sent tool context);
  - fixed scaffolding: **17%** (the problem statement is only 2.4% of all input);
  - pushed peer updates: 6.7% overall and 13.3% in S-r2, of which **91% is IDs and envelope**, not excerpt text.
- Compaction happened once in the whole study: the threshold is 184k and S-r2 peaked at 170k.
- Because the TPM limit counts these tokens, **context rent is also the throughput limit**.

### C. Idle and long-lived sessions
- Cost tracks how long sessions stay alive, not how fast the work goes (r = 0.82 across the one-root runs) [M].
- In S-r2, roots spent $56 after their last contribution [M]. Peer waits never woke (7 of 7 timed out) because they wake only on a direct message, and cross-lab messages are blocked [M].
- In five one-root runs, a broad "librarian" recruit became a second full prover. It took 47–51% of run cost and bought no speed. The fastest and cheapest run used a narrow recruit that returned in 3 min for $2.95 [M].

### D. Integration by transcription
- There is no shared file or import path between workspaces, and nothing tells agents their workspace is private. They find out by trial, 2.3–11.4 min in [M].
- Code crossed as about 120 Lean-bearing posts. Assembly was serial: one agent spent 14 min [M].
- Short 8-hex ids in posts led to NOT_FOUND errors and made-up UUIDs [M].
- This cost grows at least as O(N) serial assembly per integration.

### E. Coordination rules that decide nothing (scaffolding debt)
- **The node status ladder never worked.**
  - **Bug [M, verified in code]:** the workbench runs `--read-only` with a tmpfs only at `/work`. The statement checker stages itself with `mkdir /tmp/physharness`, which fails, so 168 of 168 checker runs exited 97. No node in any arm reached `compiles_locally`.
  - Yet the ladder drove 42 of 69 referee tasks, 91 failed local-compile attempts and about $22 of S-r2 root turns. 57 agent calls blamed a "platform glitch" or similar.
- **Referees** changed no Lean artifact [M].
- **Task-count caps** starved reviews: 41% of I-arm review requests hit TASK_TOTAL_CAP [M]. Caps are reported as input errors.
- **The lab rule** blocked the one direct hand-off message, which then went out as a broadcast [M].
- **Unused machinery:**
  - check-ins were acted on 20% of the time, yet caused half of all update posts;
  - 4 tools were never called;
  - stagnation nudges never fired [M].
- **Prompt bookkeeping:**
  - about 70% of a root's 5.3k-token prompt is platform bookkeeping (review rationale, task record twice, empty indices, a stale capacity snapshot);
  - referee prompts are 74% fixed context, 8.9k tokens for a 0.5k-token review packet [M].

### F. Lean and library friction (paid again by every agent)
- 39% of 844 compile attempts failed [M]:
  - 47% of lean_check errors were unknown identifiers, the same wrong names in every arm (`Matrix.dotProduct` 17×);
  - 179 of 741 `#check` probes named declarations that don't exist.
- `search_library` returned nothing 50% of the time, while shell `rg` found hits 92% of the time [M]. Whole-file `read_source` of 16 distinct files flooded the context.
- `lake` is not on the PATH in login shells: `bash -lc 'lake …'` failed 37 of 38 times with exit 127, once in every session that tried it, across all 15 arms [M]. That cost 55–114 calls and $8–17.
- `automate=true` is the default and ran out of memory in the 2 GiB container 14 of 14 times [M, verified].
- Each Lean check takes a flat 2.4 s because the local_docker backend starts a fresh REPL, and so a fresh Mathlib import, for every check (by design) [M].

### G. Harness overhead per turn (caps agents per process)
- **Checkpoint saves:** about 6.5 per turn. Each re-serializes and re-hashes the whole state, 70% of which is the repeated tool schema. A save costs 15 ms at turn 0 and up to 330 ms by turn 120. Saves block the single event loop that runs every agent: 36% of it in S-r2 [M].
  - This limits one runner process to about 12 active agents [E].
- **Token-count preflight:** `input_tokens.count` before every generation re-uploads the whole context. It costs 0.4–1.2 s per turn, 8–9% of agent time [M].
- **Pricing and reservations:**
  - cached input is charged at the full rate [M]. If cached input is billed at 10% (the gpt-6-sol rate is unconfirmed), the 13 completed arms would have cost about $78 instead of $542, and S-r2 about $22 [E];
  - each turn reserves $1.28 against an actual median of $0.13. At 100 agents that ties up about 10× the budget needed [M].

---

## 4. What breaks at 10× and 100× agents

| Mechanism | Growth | Breaks at | Fix category |
|---|---|---|---|
| Provider TPM (counts cached tokens) | linear demand, fixed cap | about 4 agents per 2M TPM | capacity, plus context budget |
| Goal-thread broadcast of peer updates | **O(n²)** | fills a 184k context in about 45 turns at 100 agents [E] | relevance routing, compact lines |
| Single-event-loop checkpoint saves | linear per agent, super-linear per turn | about 12 agents per process [E] | lighter, fewer, off-loop saves |
| Integration by transcription | O(N) serial on one assembler | any wide proof graph | shared importable lemma store |
| Referee load (per claim) | O(claims) | task caps starve work | review only where it adds information |
| Per-turn reservations (10× actual) | linear | budgets locked up | size from last usage |
| Every agent re-learns Mathlib names and the toolchain | linear, all waste | already large | shared institutional memory |

---

## 5. Recommended changes (a roadmap)

These are ordered by payoff for scaling and by effort. Tiers 0–1 are plumbing. Tier 2 replaces rules with substrate. Tier 3 removes scaffolding. Tier 4 is research process.

**Tier 0: bugs and one-line fixes (XS, do first)**
1. **Make the statement checker work.** Give the workbench a writable `/tmp` tmpfs, or stage the checker under `/work`. Add a checker self-test at provision, and alarm on `statement_check_unavailable`. *(Restores a machine-checked "compiles" signal, which can replace fidelity referees.)*
2. **Put `lake`/`lean` on the PATH in login shells**, or run the shell tool with `bash -c`.
3. **Change the `lean_check` default to `automate=false`**, or bound automation to cheap tactics under its own memory limit.
4. **Price cached input correctly** in `prices.json`, the ledger and reservations. Size each reservation from the last usage instead of 256k + 64k.
5. **Clearer errors:**
   - caps as "budget, not input: limit N, used N";
   - pass through the provider reason for workspace transfers;
   - name the offending kind for `CONTEXT_EVIDENCE_KIND`;
   - accept unique 8-hex id prefixes everywhere;
   - `ensure_ascii=False` in tool outputs.
6. **Log every 429 wait** (count and seconds) as a runtime event.

**Tier 1: throughput and context (the biggest scale lever)**

7. **Context budget.** Elide tool outputs over 4k chars once they are about 5 turns old, leaving a stub and a re-fetch handle, in blocks so the cache survives. Also cap whole-file reads and/or compact earlier (64–96k). **Expected: −30% to −45% input, and 1.4–1.8× more agents per TPM [E].** Needs a quality A/B test.
8. **TPM governor and capacity.**
   - A client-side scheduler that admits turns by tokens and gives the critical path priority.
   - Raise the org limit or spread load across orgs or models.
   - Budget about 0.55M TPM per agent.
9. **Drop the per-turn `input_tokens.count` preflight.** Use the last usage plus a local estimate, and count exactly only near the limit. *(−8% agent time.)*
10. **Lighter, fewer, off-loop checkpoints.**
    - Store response summaries, not echoed tool schemas.
    - Coalesce saves from 6.5 to about 3 per turn and write them off the event loop.
    - Switch SQLite to WAL.
    *(About −90% of save cost; removes the ~12-agents-per-process ceiling.)*
11. **Allow parallel or batched tool calls.** Each saved round-trip removes one full-context re-send.

**Tier 2: substrate instead of rules (the society)**

12. **A shared, importable lemma store.** A complete `lean_check` publishes the source to the node, and `commons_fetch` or `import Commons.X` brings it into another workspace. Assembly becomes continuous and by reference, and the reuse metric is computed by provenance. Tell agents that workspaces are private.
13. **Relevance-routed updates.**
    - Push a post only if it touches a node the reader created, claimed, cited or was messaged about.
    - Never echo the reader's own posts, and deliver compact one-line updates.
    - The goal thread becomes a pull-only digest.
    *(Removes the O(n²) term; −11% of S-r2 input from compact lines alone.)*
14. **Event-based waits and zero-cost idling.**
    - `wait` wakes on a peer's post, claim or node-status event, or on a change in the frontier.
    - An agent with no open work sleeps instead of polling.
    - Show the long pole ("last open dependency of the goal") so idle agents can choose to attack it with an alternative route.
15. **Remove labs and the cross-lab message ban.** Replace them with rate-limited messages addressed to a node or a branch.
16. **Admit work by dollars, not task counts**, and give referees their own small slot pool. *(Removes cap starvation and 2,230 s of referee queueing.)*

**Tier 3: remove scaffolding (minimal institution)**

17. **Drop the node status ladder and fidelity reviews.**
    - Nodes become claims plus an optional Lean source hash and the author's `lean_check` result.
    - Compiles are recorded automatically once fix 1 lands.
    - The verifier alone accepts. Referees review plans and the final statement, not compiled lemmas.
18. **Strip prompt bookkeeping.** The root prompt goes from 5.3k to about 1.6k tokens and the referee prompt from 8.9k to about 1.7k. Keep the target, objective and constitution.
19. **Prune and merge tools.**
    - Remove `inbox` (51 of 63 calls were empty; the push already delivers), `notebook`, `lean_sketch` and `load_skill`.
    - Merge `search_library` and `read_source` into one ranked declaration search (`Name : type — file:line`, with did-you-mean), or rely on `rg` plus output elision.
20. **Remove check-ins and stagnation nudges.** A platform activity digest built from the tool logs costs no model turns.

The scaffolding analysis estimates a static −14.5% of all input (−20.6% in S-r2) for items 13, 18, 19 and 20. With the behavioural effects of items 16 and 17 and native waits, S-r2 would be about −35% to −40% cheaper at equal work [E].

**Tier 4: research process**

21. **Agree on the architecture before splitting.** A shared target file with `sorry`-stubbed lemma signatures that always compiles; claims attach to stubs.
    - *Evidence:* late `N > 0` mismatches in 8 of 11 aperiodic arms, and the target theorem was written only 0.1–2.6 min before submission in every arm.
22. **Diversity at genuine choice points, with time boxes and kill rules.**
    - Here the only real choice was how to prove a stationary distribution exists.
    - Its routes compiled at 2.9 min (linear algebra), 5.8–10.5 min (Banach) and 25.7 min (Cesàro, which set S-r2's critical path).
    - Independent runs sampled that diversity for free; the society gave it to one owner.
23. **Narrow, returning delegation.** Scope a recruit to one named lemma with its signature, and let it end.
24. **Institutional memory.** A per-Mathlib-pin cheat sheet (renamed APIs, known absences such as Perron–Frobenius, the coin and fixed-point APIs), shared by every agent. *Evidence:* every run re-learned the same names.
25. **A harder target** that separates the arms: 10 or more substantial lemmas, a costly choice point, and infrastructure missing from Mathlib. Candidates:
    - Perron–Frobenius for irreducible nonnegative matrices;
    - irreducible chains with general period `d` and Cesàro convergence;
    - spectral-gap mixing bounds for reversible chains.

    Calibrate to a 20–50% single-agent success rate within budget, and record lemma-graph progress so a failed run still gives a signal.

**Validation before scaling.** Run one A/B pair at S-r2 scale on the harder target: the current configuration against Tier 0–3. Measure:
- solved or not, and time to proof;
- input per agent-turn;
- coordination share of turns;
- peer-update rent;
- tokens per minute against the limit.

---

## 6. When a society should pay off [I]

- **Here:** components took one agent 1.5–8 min, and each handoff cost 1–4 min plus 3–15 min of integration. The proof graph was shallow (about 5 components with one bottleneck), which caps any parallel speed-up at about 2×. Routing and integration consumed that 2×.
- **Where collaboration should win:** where components take tens of minutes, the graph is wide (10 or more components), integration is by reference (Tier 2), idle agents cost nothing, and context rent does not grow with the number of agents (Tiers 1–3).

The substrate changes in Tiers 1–2 are prerequisites for testing the society idea fairly. They are not optimisations to apply later.

---

## 7. Method and limits

- **Data:** extraction by `extract.py`, read-only and deterministic. Tokens and cost reconcile exactly with each arm's ledger.
- **Known gaps:**
  - there is no per-request HTTP log, so 429 waits are inferred from timing (±1 s);
  - reservation waits cannot be separated out;
  - reasoning content is encrypted, so only its size is known.
- **Scope of the results:** single model family (`gpt-6-sol`), one society run, two easy targets. The throttle-excess model was fitted on the unthrottled arms, with an error of −2% to +2.5% on those arms.
- **Constraint deviation:** one analyst downloaded a public tokenizer vocabulary file (tiktoken, about 3.6 MB). No data was sent.
- **Privacy:** every analysis stayed read-only on the run data and never read credentials. The OpenAI org id that appears in one error log was not copied.
