# Scaffolding overhead audit: S1 live runs (15 arms)

Dimension: the fixed structure the harness puts on every agent, what it costs, and what could
be removed so the society can scale with minimal scaffolding. Measured facts are marked
**[M]**. Interpretation and estimates are marked **[I]**. Arms, sessions and tasks are cited by id
prefix. Money is at the harness ledger price ($2.50/M input, $10/M output, no cached discount).

## Method, in brief

- **Per-turn input composition.** For every completed turn (3,774 turns, 222.5M input tokens), I
  rebuilt the model-visible context from `data/<arm>/messages.jsonl` (the items in context at that
  turn) and the full initial prompt, decoded from each session's newest native checkpoint. I
  attributed the measured `input_tokens` to these parts: tool definitions, initial-prompt sections,
  injected harness context, agent-written arguments and text, tool outputs (work tools vs
  coordination tools), and a residual.
  - The residual is carried encrypted reasoning plus framing. It is a median 6.9% of a turn's
    input (p5 0.4%, p95 12.1%). It is never below −200 tokens, so the attribution is consistent.
  - Summed over turns, each part's tokens give its "rent": what that content cost for as long as
    it stayed in the context.
- **Tool-definition tokens are measured exactly.** For fresh sessions, turn-1 input minus the
  prompt's token count is a constant for each profile: root 3,522 (27 of 27 sessions),
  joined-recruit 3,686, and referee 1,949 ±1 (67 sessions). That constant is the provider-side cost
  of the catalog plus request framing.
  - Per-tool shares come from offline-built catalogs (test fixtures), scaled to that constant.
  - The offline catalog digests differ from the runs', so treat the per-tool split as an estimate
  and the per-profile totals as exact.
- **Text token counts use o200k_base** (tiktoken) as a proxy tokenizer. With it, the root prompt
  plus catalog reproduces turn-1 input with a constant offset, which supports the proxy.
- **Deviation from the audit constraints.** The first `tiktoken` call downloaded its public
  vocabulary file (about 3.6 MB, no data sent) to the local temp cache. That was a network fetch.
  Nothing else touched the network, and every later use read the cache.
- Scripts are in `.superpowers/live-run/audit/scripts/scaffold/`: `prompts.py`,
  `tool_catalogs.py`, `calibrate.py`, `composition.py`, `summarize.py`, `scaffold_numbers.py`,
  `tool_rent.py` and `lean_estimate.py`. Outputs are in `scaffold/out/`, and redacted sample
  prompts are in `scaffold/samples/`.
  - Run order: prompts, calibrate, composition, then scaffold_numbers, tool_rent and
    lean_estimate.
  - Environment: `PYTHONPATH=src:tests:<scaffold dir> .venv/bin/python`.

## Key numbers

| Quantity | Value |
|---|---|
| Input tokens, all 15 arms | 222.5M. 97.0% of them were provider-cached. Input is $556 of the $568 ledger total. Input/output ratio is 186 **[M]** |
| Fixed context at turn 1 (tools + initial prompt) | root **8,783** (3,522 + 5,261); joined recruit **10,544** (3,686 + ~6,860); referee **10,813** (1,949 + 8,863) **[M]** |
| Part of the root prompt the task needs (target statement + objective + constitution) | about 1,300–1,600 of 5,261 tokens (about 25–30%) **[M]** |
| Fixed scaffolding share of all input tokens (rent) | **17.2%** ($95.8). The problem statement is only 2.4%, so non-problem fixed content is **14.8%** ($82) **[M]** |
| Tool-definition rent | 5.7% of input, $31.9. Four tools were never called in 3,701 calls (lean_sketch, load_skill, search_literature, fetch_source) **[M]** |
| Prompt bookkeeping (target-review record, task record ×2, indices, readable_work, capacity, contract, model list) | 8.3% of input (6.5% brief + 1.8% commons and workforce views) **[M]** |
| Referee input that is fixed scaffolding | **74%**. 62% is non-essential. The review packet itself is about 456 tokens of an 8,863-token prompt **[M]** |
| Automatic peer-update rent | 6.7% of all input ($37.4). **13.3% of S-r2** ($20.2), and 14.0% of S-r2 root input **[M]** |
| Share of peer-update tokens that are actual excerpt text | **9%**. The other 91% is IDs, metadata and a repeated per-batch notice (S-r2, o200k) **[M]** |
| Coordination-tool I/O (commons_*, inbox, message, wait, notebook, recruit, reviews) | 12.5% of input ($69.4); 17.9% of S-r2 **[M]** |
| S-r2 root turns spent on a coordination call | **55%** of turns and 60% of root turn cost ($88.5). In I-arms roots it is 34% **[M]** |
| Local compiles recorded (`compiles_locally`) | **0** in all arms. All 168 statement-check runs (84 checks × 2) exited 97 (checker missing) **[M]** |
| Fidelity referee tasks | 42 of 69 referee tasks (S-r2: 24 of 34). They only unlock `formally_stated`, which gates a compile record that never happened **[M]** |
| Check-in notes acted on within 3 turns | 49 of 250 (20%). Yet 52 of all 104 `update` posts came within 3 turns of a check-in **[M]** |
| Stagnation signals fired | **0** in 3,701 calls **[M]** |
| Peer waits (`wait for=peer`) | 14. Each one forced a portable successor: the context was reset from 52k–154k tokens to 18k–29k, with 6–186 s idle. The S-r2 successors cost $11.48 **[M]** |
| Tool rejections | 48 of 3,701 calls (1.3%); TASK_TOTAL_CAP is 14 of them **[M]** |
| Harness gap between one tool call ending and the next generation | median 0.75 s (S-r2: 1.09 s), against a median model turn latency of 4.0 s. There are 6.3 checkpoint saves per turn **[M]** |
| Per-turn budget reservation vs actual | reserved $1.28 per turn (256k in + 64k out). Actual median $0.13 (10×). The largest output of any turn was 5,966 tokens **[M]** |
| Static saving of the proposed lean configuration | **−14.5% of input** overall ($80.6); **−20.6% in S-r2** ($31.4). Per agent-turn: root −9.4k tokens, referee −7.5k (−52% of referee input) **[I]** |

Input composition by arm (share of input-token rent):

| Arm | Input M | Fixed | …of which problem | Tool defs | Bookkeeping + brief | Peer updates | Coordination I/O | Work I/O | Residual |
|---|---|---|---|---|---|---|---|---|---|
| S-r2 | 61.0 | 17.9% | 2.3% | 5.2% | 7.0% | **13.3%** | **17.9%** | 43.2% | 7.5% |
| single | 12.5 | 17.4% | 2.8% | 5.9% | 6.4% | 4.4% | 9.9% | 60.4% | 7.6% |
| I-01…I-08 (range) | 7.2–19.4 | 11.2–21.6% | 1.8–2.9% | 4.2–6.7% | 4.0–10.0% | 3.4–5.1% | 8.4–11.7% | 54.6–63.5% | 7.7–10.9% |
| pilot-doeblin | 8.8 | 22.5% | 3.1% | 8.9% | 7.8% | 6.8% | 14.4% | 48.2% | 7.8% |
| S (attempt 1) | 9.7 | 31.2% | 4.7% | 11.2% | 10.6% | 3.3% | 6.3% | 53.5% | 5.4% |
| referee tasks (all arms) | 6.0 | **74.3%** | 12.1% | 13.6% | 29.2% | 0.1% | 9.2% | 12.6% | 3.7% |

Short sessions pay the most: the fixed share goes up as session length goes down.

## Inventory of scaffolding and its cost

Token figures are per turn at turn 1 for a fresh session. "Rent" is the share of all 222.5M input
tokens.

| Component | Size per turn | Rent (share, $) | Used as intended? |
|---|---|---|---|
| Tool catalog: root/detached 24 tools, joined recruit 25, referee 18 | 3,522 / 3,686 / 1,949 | 5.7%, $31.9 | Partly. commons_node alone is ~620 tokens/turn. Zero calls: lean_sketch, load_skill, search_literature, fetch_source. Under 25 calls: run_computation 3, read_artifact 5, wait 14, notebook 16, recruit 17, commons_query 23 |
| Constitution (norms, boundaries, playbook, skill list) | 301 (referee 210) | 0.4% | The norms are partly followed (see below). The playbook's sketch, literature and skills steps were never used |
| Target record (`research_brief.target`) | 1,278, of which ~275 is IDs and digests | 2.4% (problem) | Needed. Strip the record metadata |
| Target-review rationale (`brief.review`) | 1,212 | in 6.5% | The operator's audit text. No agent ever needs it |
| Current-task record, ×2 (`current_task` + `readable_work.open_obligations[0].record`) | 391–1,037 each. A referee packet appears 3 times | in 6.5% | Duplicated. It holds holder, fence, slot and workspace-policy digests |
| Memory indices (`brief.indices`) | ~505 | in 6.5% | Almost always empty lists with retrieval metadata |
| Capacity snapshot + guidance + task contract + model list + retrieval notes | ~350–520 | 1.8% (with commons views) | Stale after turn 1. S-r2 lists 6 identical model entries (141 tokens) |
| Commons frontier in the referee prompt | 2,366 | 0.4% of all (16.6% of referee input) | Not needed to review one node |
| Automatic peer-update batches | ~294 tokens/item (excerpt ≈ 26) | 6.7%, $37.4 (S-r2 $20.2) | Read and acted on. 323 commons_read calls were needed to see full posts. 81% of S-r2 items came from the shared goal-node thread |
| Check-in note every 12 turns | ~80 tokens each | 0.4% | 20% compliance. It drove the first post in most sessions (turn 13) |
| Stagnation detector and nudges | 0 | 0 | Never fired |
| Node status ladder (informal → refereed → formally_stated → compiles_locally) | its tools and descriptions (lean_check's is 931 chars) | S-r2: 135 root turns on node operations, $22 turn cost | Broken end-to-end: `compiles_locally` was never reached |
| Referee tasks (platform-created on request_review) | 10.8k fixed per turn, ~6 turns each | $15.0 (2.6% of cost). S-r2: 1,688 slot-seconds | Compliance is good. The fixed cost dominates, and in I-arms verdicts arrived 11–15 min after the request |
| Labs, lab_size_max, cross-lab DM ban | prompt `lab` field + recruit/message schema | small | Inert in S-r2 (6 labs of 1 member). It blocked the one useful direct hand-off message |
| Workforce caps (max_total_tasks / max_pending_tasks) | 0 tokens | 16 rejections | Referees used up the task cap: 34 of 40 in S-r2. 11 referee requests were rejected in I-arms (cap 4) |
| Peer wait / continuation | successor prompt 25.7–29.0k | S-r2 successors $11.48 | Every peer wait lost the full transcript (portable mode) |
| Budget reservation per turn | $1.28 held | 0 tokens | Safe but 10× oversized |
| Checkpoint durability | 6.3 saves per turn | 0 tokens | Part of the 0.75–1.09 s gap between turns |
| Verification (submit_for_verification, verification_status) | ~170 tokens of definitions | $1.5 of rent | Lean and correct: 13 submissions, 13 accepted |

## Findings

**F1. About 70% of every root's initial prompt is bookkeeping that is re-billed on every turn.** [M]
- The root prompt is a canonical-JSON dump of platform records
  (`research_worker.py:1801`, `memory.working_context`).
  - The objective ("Investigate the complete target using a method of your choosing.") is
    13 tokens, and the target statement about 1,000.
  - Around them sit the target-review rationale (1,212 tokens: "Target review: assistant-led,
    under the user's delegation…") and the current task record twice (with lease holder, fence,
    worker_slot_id and workspace qualification digests).
  - Also included: memory indices with empty `items` plus retrieval metadata, a capacity snapshot
    that goes stale after turn 1, and six identical model entries.
- Removing it (C1–C4 in `lean_estimate.py`) saves **5.5% + 1.2% + 0.4% + 0.5% ≈ 7.5% of all input
  tokens** [I]. That is about 3.3k tokens per root turn and 5.8k per referee turn.
- It creates no integrity risk: the records stay in the database for audit.

**F2. Referees are mostly scaffolding.** [M]
- A referee's turn-1 context is 10.8k tokens. The part it needs is about 0.5k (the fenced
  review packet) plus about 1k (the target).
- The referee objective (1,494 chars) appears three times: `objective`,
  `research_brief.current_task.objective` and `readable_work.open_obligations[0].record.objective`.
- The prompt also carries a fenced 10-node commons frontier (2,366 tokens).
- Referee sessions are short (419 turns across 69 tasks), so 74% of all referee input is fixed
  scaffolding.
- A lean referee prompt (packet + target + constitution, 18→9 tools) saves about 7.5k tokens per
  referee turn, about 52% of referee cost [I].

**F3. Peer-update push is the scaling bottleneck, and 91% of it is metadata.** [M]
- Each delivered item carries 7 UUIDs (attributed_to, branch_id, id, node_id, retrieval_id,
  retrieval_post_id — the same value as id — and topic_id), plus sequence, flags and a
  ~160-character excerpt. Each batch also repeats a 130-character notice.
- In S-r2: 601 items, 176.6k tokens (294 tokens per item). Excerpts are 15.6k of those tokens (9%).
- Roots claimed the goal node and posted their updates there, so 81% of items came from one
  thread that every root subscribes to. Delivery is effectively all-to-all.
- Items delivered per root-turn grow with the number of peers:
  - I-arm roots: 0.21 (one recruit plus two referees).
  - pilot: 0.34 (five research agents).
  - S-r2: 0.76 (six roots). That is about 0.12–0.13 items per turn per posting peer.
- Peer updates are 14.0% of S-r2 root input, against 5.3% for I-arm roots.
- **At 100 agents on a shared thread** [I]: about 12 items per turn, which hits the 10-item batch
  cap.
  - That is about 2.9k metadata-heavy tokens added per turn, against about 1.1k per turn of the
    agent's own context growth.
  - The 184k compaction threshold would be reached in about 45 turns, and about 70% of every
    turn's input would be peer metadata.
- With a compact line format (excerpt plus about 20 tokens of attribution), items cost about
  46 tokens (−84%). The saving is 5.7% of all input and **11.1% of S-r2 input** [I].
- Scoping subscriptions to nodes an agent created, claimed or cited, rather than the goal thread,
  removes the N² term.

**F4. The node-status ladder produced 42 referee tasks and about 90 lean_check calls toward a
status that could never be reached.** [M]
- How the ladder works:
  - `formally_stated` requires a faithful fidelity review (`commons_review.py:825`).
  - `compiles_locally` requires `formally_stated` plus a platform statement check run from
    lean_check with a `node_id`.
- The statement checker was missing in every workbench. All 168 check runs exited 97, and 91 of
  119 lean_check calls that carried a node_id returned `local_compile: {"recorded": false,
  "reason": "statement_check_unavailable"}`. No node ever reached `compiles_locally`.
- The fidelity reviews (24 of 34 in S-r2) served only this ladder. The verifier checks the
  final proof and every lemma in it regardless.
- S-r2 roots spent 135 turns on node operations: create 32, set_lean_statement 29,
  request_review 37, link 13, abandon 5 and claim 19 (about $22 of turn cost), plus $8.6 of
  referee tasks.
- Agents misread the failure as a gate that referees or the task cap control:
  - I-02 d0793ffb, turn 28: "`local_compile.recorded:false, statement_check_unavailable` likely
    due task capacity prevented fidelity review (request_review returned TA…"
  - I-01 5e3f035f, turn 36: "Formal-status recording pending informal referee."
  - One agent, I-08 a8b9911d at turn 30, diagnosed it correctly: "Blocker: node statement-check
    unavailable prevents automatic `compiles_locally` promotion; the independent verifier only
    accepts the final target."
- Across all arms, agents mentioned `statement_check_unavailable` 47 times.

**F5. Coordination crowds out work as the society grows.** [M]
- Turns whose single call went to a coordination tool:
  - single root: 33%.
  - I-arm roots: 34%.
  - S-r2 roots: **55%** (60% of root turn cost and 54% of root turn-time).
- commons_read was the most frequent S-r2 root action: 124 turns, 15.8%. Truncated peer excerpts
  push agents to fetch full posts.
- Posts took another 127 turns (finding 70, update 44, question 13).
- Coordination-tool I/O is 17.9% of S-r2 input, against about 10% in I-arms [M].
- At 10–100× agents [I], the share of turns spent reading the commons will keep rising unless
  delivery becomes a digest and reading is targeted.

**F6. Peer waits silently cost the agent its transcript.** [M]
- Only a `joined_children` handoff can resume natively (`research_worker.py:1683-1690`). A
  `wait(for="peer")` hands off to a *portable* successor: a fresh session with a 25.7k–29.0k-token
  prompt instead of the 52k–154k-token transcript it had.
- Idle gaps were 6–186 s. All 7 S-r2 peer waits targeted the same assembler branch (7816b570).
- The 5 S-r2 successors cost $11.48 and re-oriented from scratch.
- `wait(for="tasks")`, the documented use in the capacity note, was never called.

**F7. The lab boundary blocked the most useful direct message and turned it into a broadcast.**
[M]
- In S-r2 every root is its own one-member lab and there are no recruits, so labs do nothing
  except forbid direct messages.
- 3d151e45, turn 14, to the assembler: "Minorization proof done, full copy-ready Lean source
  node d6b557bb…" was rejected with CROSS_LAB_MESSAGE.
- The same session then posted on node d6b557bb's thread (turn 16). Session 415493d7 posted its
  question on the goal thread, which every root subscribes to.
- So a one-to-one message became a one-to-many post. At scale this rule increases broadcast load
  (F3).

**F8. Task-count caps make referees compete with research.** [M]
- max_total_tasks counts referee tasks. S-r2 used 34 of its 40 slots on referees and recruited
  nobody.
- Every I-arm (cap 4 = root + recruit + 2 referees) rejected a later referee request: 11
  TASK_TOTAL_CAP in I-arms, 14 in all.
- The rejected referee requests left lemma nodes without a referee verdict. Agents recorded this
  as a blocker: 08bdcfc9, turn 121, "Task cap blocked independent referee for new stationary
  lemma, so no platform acceptance."
- In I-arms the concurrency of 2 made referees queue for 11–15 min (I-01 median 821 s, I-05 660 s).
  In runs of 12–17 min, the verdicts arrived after the work had moved on.

**F9. Several instructions changed nothing, or changed timing but not substance.** [M]
- Zero use of lean_sketch, search_literature, fetch_source and load_skill, despite the playbook
  ("Explore: …literature", "Sketch the Lean proof with holes") and the skill list.
- Stagnation nudges: 0 fired.
- Check-in note: 80% ignored. It still set the time of the first post: the first commons_post
  came at turn 13, the turn right after the first check-in, in 13 of 27 fresh root sessions.
  Half of all `update` posts followed a check-in, and each is then broadcast (F3).
- "Post failures": 172 failed non-referee lean_checks, but 1 `attempt_failed` post.
- "Claim before sinking effort": all 27 fresh roots claimed by turn 3 (26 of them at turn 1–2).
  But 28 of 63 claims were on the shared goal node, where a claim carries no information.

**F10. Tool catalogs are strict and wide.** [M]
- Every commons_node call must fill 15 properties, most of them null. A request_review call's
  median argument is 293 characters for what is logically `{node_id, scope}`.
- lean_check's 931-character description is mostly about the broken local-compile protocol (F4).
- Removing the 4 zero-call tools plus notebook (16 calls, 6 of them rejected
  CONTEXT_EVIDENCE_KIND) saves about 590 tokens per root turn (1% of input) [I].
- Splitting commons_node into small actions would also cut argument padding.

**F11. Per-turn harness overhead grows with concurrency.** [M]
- Tool-end to next-generation gap: median 0.75 s in the 1–4-agent arms, 1.09 s in S-r2 with 8
  workers. That is +45%, and about 20% of the median 4.0 s model latency.
- This gap includes update delivery, the turn note, an `input_tokens.count` preflight request, the
  budget reservation, and about 6.3 durable checkpoint saves per turn.
- Budget reservations hold $1.28 per turn against a median actual $0.13:
  - Input is reserved at `max_context_tokens` because compaction is enabled
    (`responses.py:777`).
  - Output is reserved at 64k, against a largest observed output of 5,966.
- At 1,000 concurrent agents that is about $1,280 held in flight [I]. Admission would serialize
  well before the budget is actually spent.

**F12. The fixed context is mostly cache hits, which masks the problem but does not remove it.**
[M]
- 97% of input tokens were cached. Everything the harness adds is append-only, so the fixed
  prefix is cache-friendly. Any change must keep that property.
- Rent still scales with context length × turns × agents. Under a real cached discount the
  dollar figures shrink, but the shares above do not: time, TPM rate limits (the known 2M TPM
  throttle) and the compaction threshold all count cached tokens.

## Instructions vs behaviour

| Instruction (source) | Behaviour | Evidence |
|---|---|---|
| "Claim before sinking effort." (constitution) | Followed mechanically | 27 of 27 fresh roots claim by turn 3 (26 at turn 1–2); 28 of 63 claims are on the goal node |
| "Recruit when a piece can proceed independently." | Diverges by setting | 14 roots recruited, 13 of them at turn 2–4, before exploring (the S root at turn 10). Hats: librarian 8, formalizer 7, explorer 2. S-r2: 0 recruits among 6 roots |
| "Ask for a referee before investing heavily in formalization." / playbook "Get a referee." | Followed, and misattributed | 89 request_review attempts (69 accepted, 20 rejected). Agents treated the referee as a precondition for acceptance (F4 quotes) |
| "Only the independent verifier accepts proofs." (boundaries) | Followed | "this is local compile, not acceptance" (I-01 5e3f035f, turn 85); every arm submitted once and was verified once |
| "Post failures." | Ignored | 1 attempt_failed post against 172 failed Lean checks |
| "Cite what you use." | Partial | 153 of 391 posts carry cites or artifact_ids |
| Playbook "Sketch the Lean proof with holes" / literature / skills | Ignored | lean_sketch 0, search_literature 0, fetch_source 0, load_skill 0 |
| Check-in: "post a short self-assessment as an update on your focus node" | 20% compliance, and it shapes post timing | first post at turn 13 in 13 of 27 fresh root sessions; e.g. I-01, turn 13: "Subgoal: reduce coprime return times + irreducibility to a uniformly positive power; confidence high…" |
| Capacity note: "optionally call wait with for='tasks'…" | Never used as written | 0 `wait(for=tasks)`; 14 `wait(for=peer)` |
| Referee: "Call submit_review exactly once" | Followed | 63 of 63 completed referee tasks submitted exactly one verdict |
| Referee: "Post questions, findings or objections on the assigned node's thread" | Followed | 65 referee finding posts, 1 objection. The objection caught a real flaw: 08bdcfc9, turn 79, "Referee objection valid: my informal corollary asserted boundedness without stochasticity" |
| lean_check description (local compile when statement found) | Tried, always failed | 119 calls with node_id, 0 recordings |

Instructions that caused wasted work [M]:
- The referee-first playbook combined with the node ladder: 42 fidelity reviews and about 90
  lean_check calls toward a status that could not be reached (F4).
- The check-in notes induced update posts (52 of 104), which were then broadcast in the
  metadata-heavy format (F3).
- `wait(for=peer)`: 7 transcript resets in S-r2 (F6).

## Guards and policy

| Rule (code) | Count | Blocked legitimate work? | Prevented real harm? | Recommendation |
|---|---|---|---|---|
| TASK_TOTAL_CAP (workforce.py:310) | 14 | Yes: referee requests in every I-arm | Budget only (so does the $ ledger) | Replace with $ admission; give referees their own small pool |
| TASK_PENDING_CAP | 2 (pilot) | Yes: referee requests | No | Remove; concurrency and $ already bound the queue |
| CROSS_LAB_MESSAGE (collaboration.py:914) | 3 | Yes: direct hand-off to the assembler | No: posts are public anyway | Remove labs; per-agent message budget instead |
| REVIEW_PRECONDITION / LEAN_STATEMENT_REQUIRED | 2 / 2 | Friction from the ladder | No | Goes with the ladder |
| CONTEXT_EVIDENCE_KIND (notebook) | 6 of 16 notebook calls | Friction: the tool semantics are confusing | No | Remove notebook, or accept free notes |
| DELIVERY_MISMATCH (inbox ack) | 4 | Friction: two delivery channels (push + inbox) | No | Keep one channel |
| NOT_FOUND / INVALID_ARGUMENTS | 6 / 2 | Agent ID mistakes; recoverable | Correct behaviour | Keep |
| WORKSPACE_TRANSFER_REJECTED (read_file requests of 6k–30k bytes) | 6 | Yes: legitimate file reads | Size bound; the VM is fine | Raise the limit or return a truncated read instead of refusing |
| GOAL_NODE_RESERVED | 2 | No: agents tried to restate the goal | Protects the target mirror | Keep |
| DEPENDENCY_CYCLE / NODE_CLOSED | 1 / 1 | No | Graph hygiene | Keep; harmless |
| Referee tool profile, fenced author data | none | No | Isolation and prompt-injection defence | Keep |
| Verified-target guard (pre_generation_guard) | 4 blocked (TARGET_ALREADY_VERIFIED), 4 superseded | No | Stops spend after acceptance | Keep |

Overall, only 1.3% of calls were rejected and every rejection was a recoverable envelope. The
cost of the guards is not the rejections themselves. It is the behaviour they shape: referee
dependence, broadcasting instead of messaging, and caps absorbed by referees.

## What worked well

- **The verification path is minimal and correct.** Each arm made 1 submission, about 1 status
  check and 1 acceptance (13 of 13). It is cheap in context (about 170 tokens of definitions per
  turn). It is the integrity core; keep it unchanged.
- **Referee isolation and discipline.** The profile is smaller (18 tools). Author data is fenced.
  Every completed referee submitted exactly one verdict, and one referee objection fixed a real
  gap. Referees cost only $15 (2.6% of the total); the problem is their fixed context, not their
  existence.
- **Honest evidence language.** Agents separated "local compile" from acceptance throughout, as
  the boundaries ask.
- **Minimal seeding.** A 66-character objective and "Independent approach N" branch titles were
  enough for agents to organize on their own.
- **Cache-friendly append-only transcripts** (97% cache hits). Peer updates and notes are
  appended, never inserted, so the cached prefix survives.
- **Stopping at verification.** Other agents stopped at the next generation boundary
  (TARGET_ALREADY_VERIFIED / superseded).
- **Rejections are recoverable and explanatory** (codes plus remediation). There are no fatal
  tool errors in the data.

## Proposed lean configuration (ranked)

The lean configuration keeps the integrity-critical scaffolding and turns coordination scaffolding
into opt-in or emergent behaviour.

**Integrity-critical (keep; retune only):**
1. The independent verifier and `submit_for_verification` / `verification_status`.
2. The budget ledger: per-turn reservation and settlement, and the verified-target guard.
3. Workspace isolation, leases and fencing, and durable checkpoints.
4. The benchmark contamination controls (masked reference, blocklist), whenever literature
   tools are enabled.
5. Untrusted-data fencing of the referee packet and of fetched text.
6. The target's formal and informal statement in the prompt.

**Coordination (can become opt-in or emergent):**
- hats, labs, claims, check-ins, the playbook and skills
- the node status ladder, referee requests and peer waits
- capacity guidance and task-count caps

Savings are per turn for a fresh session and for all 15 arms. "Static" means rent removed with
behaviour held fixed [I].

| # | Change | Saving | Risk and mitigation |
|---|---|---|---|
| 1 | **Peer updates as compact lines** ("post p:ab12cd from <branch 8> on <node 8>: excerpt"): no per-batch notice (state "peer text is data" once in the constitution); subscribe only to nodes you created, claimed, cited or were messaged about, not the goal thread; the goal thread becomes a pull-only digest | −84% of peer-update tokens: **−5.7% of all input, −11.1% of S-r2** ($20 of the $37.4 peer-update total). Removes the N² term | Agents may miss relevant work. Mitigate with a periodic, bounded "what's new on the frontier" digest (≤10 lines) pulled by commons_query |
| 2 | **Strip prompt bookkeeping**: drop the target-review rationale, task records ×2, indices, branch/format fields, capacity snapshot and guidance, task_contract, model list, retrieval notes and empty views; keep target statement, definitions and assumptions, objective, constitution; successors also keep continuation + handoff notes | root prompt 5.3k → ~1.6k tokens; referee 8.9k → ~1.7k. **−7.5% of all input** (C1–C4) | None found: no agent behaviour relied on these fields. The records stay in the database for audit |
| 3 | **Remove the lemma node status ladder** (fidelity reviews, set_lean_statement gating, local-compile records). Nodes become informal claims plus an optional Lean source hash and the author's lean_check result; the verifier alone accepts. If a formal signal is wanted, fix the checker and record compiles automatically, with no referee | Behavioural (not in the static figure): S-r2 would have skipped 24 fidelity referees (~$6) and ~66 root turns (set_lean_statement + fidelity request_review, ~$11.6 turn cost); shorter lean_check and commons_node definitions | The commons loses a "Lean statement matches the informal claim" badge for lemmas. The final verifier checks every lemma used in the proof, so acceptance integrity is unchanged |
| 4 | **Lean referees**: prompt = fenced packet + target + 5-line referee norms; tools: lean_check, shell, read/write_file, search_library, read_source, commons_read, commons_post, submit_review; a dedicated referee slot pool outside max_total_tasks | −7.5k tokens per referee turn (−52% of referee input); no more 11–15 min referee queueing in 2-slot arms | Referees see less context. The frontier was not needed to judge one node; commons_read remains available |
| 5 | **Budget admission by dollars, not task counts**: drop max_total_tasks and max_pending_tasks; keep concurrency and $ ceilings; size each reservation as counted input + a realistic output cap (e.g. 16k) | Removes 16 rejections and the cap starvation (34 of 40 in S-r2); **4.4× more concurrent turns per reserved dollar** ($1.28 → ~$0.29) | Budget safety is integrity-critical. Settlement stays exact. A turn that needs more output than the cap must fail closed, or re-reserve before sending |
| 6 | **Remove labs and the cross-lab DM ban**; allow direct messages to any branch under a per-agent message budget | Stops one-to-one hand-offs turning into broadcasts (F7); removes the lab field and recruit/message parameters | Message spam at scale. Mitigate with a rate limit, and deliver messages as compact lines (#1) |
| 7 | **Native continuation for peer waits, or remove `wait(for=peer)`** (agents can keep working and read their inbox) | S-r2: 5 transcript resets, $11.5 of successors, 1–3 min of idle per wait | A native resume keeps the whole context. Compaction already bounds it |
| 8 | **Prune the tool catalog**: drop lean_sketch, load_skill, notebook, and (in benchmark mode) search_literature and fetch_source; shorten the lean_check and commons_node descriptions; split commons_node | −590 tokens per root turn (**−1% of input**), and more if descriptions shrink; less argument padding | Losing capabilities no one used. Offer a `load_skill`-style on-demand catalog if a tool is ever needed |
| 9 | **Remove check-in notes and the stagnation nudges**, or make check-ins 30-turn and posted to the agent's own node only | −0.35% of input directly; removes about half of `update` posts and their fan-out | Less status visibility. Mitigate with a platform-computed activity digest (from tool logs, no model turn) |
| 10 | **Claims**: auto-claim on create or focus; forbid claiming the goal node | about 1 turn per agent; removes 28 claims that carried no information | none |

Totals [I]:
- Static (1, 2, 8, 9): **−14.5% of all input, $80.6 of $568**. S-r2: −20.6%, $31.4 of $155.
- Per agent-turn: root −9.4k tokens (4.7k of them peer updates), recruit −6.2k to −7.2k,
  referee −7.5k.
- Behavioural savings, which overlap with the static figure: in S-r2, dropping the node ladder,
  lean referees and native waits would avoid about $6 + $12 + $11.5 more. That puts S-r2 at
  roughly −35 to −40% of cost at equal work.
- At 1,000 agents × 150 turns:
  - The fixed tax falls from about 8.8k–10.8k tokens per agent-turn (1.3B–1.6B tokens, about
    $3.3k–$4.0k per run at ledger price) to about 3k–3.5k per agent-turn (about $1.1k–$1.3k).
  - Peer-update growth becomes roughly linear in the number of agents instead of quadratic.

Recommended validation [I]: run one A/B pair (current vs lean) on the same target at S-r2 scale
before scaling up. Measure verified or not, time to verification, input per agent-turn, coordination
turn share, and peer-update rent.
