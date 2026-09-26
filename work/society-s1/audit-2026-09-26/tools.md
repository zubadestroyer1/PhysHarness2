# S1 audit: tool friction and the agent–harness interface

Scope: all 15 arms (calibrations, pilot, S, S-r2, I-01..08, single), 123 model sessions,
3,774 turns, 3,701 tool calls. Source: the normalized dataset in `data/<arm>/` (transcripts
reassembled from native checkpoints), plus read-only look-ups in `harness.db`
(`workspace_operation` results) and the harness source to explain every error code.
Scripts: `scripts/tools_*.py` (listed at the end). Nothing here needs a network call.

**Conventions.** "$" is ledger dollars, the harness arithmetic ($2.50/M input, $10/M output,
cached tokens not discounted), which is also what the budget caps enforce. 97% of input
tokens were provider-cached, so real provider bills are lower. The ledger figure still sets
the TPM load and the budget. "Cost of a call" is the ledger cost of the turn that issued it,
plus that turn's latency and the tool's run time. The mean turn costs $0.151 (median $0.130).
"Context rent" is the tokens of a tool output multiplied by the number of turns it is re-sent:
it stays in context for every later turn of its session. Only one compaction happened in the
whole study, so that holds almost everywhere. Chars→tokens uses 2.55 chars/token, the median
of 974 measured input-token deltas after outputs of more than 2k chars. "10×/100×" projections
assume 10× or 100× as many sessions with the same per-session behaviour (linear). Items that
grow faster than linearly are marked **superlinear**.

---

## 1. Key numbers

| quantity | value | evidence |
|---|---|---|
| Study total | $568.29 ledger, 222.5M input tokens (215.8M cached), 1.20M output, 3,774 turns | `tools_misc.py` |
| Output tokens by cost | $12 of $568: the spend is almost all input (re-reading context) | `tools_misc.py` |
| Harness rejections (error envelopes) | 51 calls = 1.4% of calls; $9.21 and 6.0 agent-min direct | 13 codes, §3 |
| In-band failures (Lean errors, non-zero exit) | 416 calls (lean_check 236, shell 180), $67.80 | mostly normal proof iteration |
| **Tool-output context rent** | **125.5M token-turns = 56% of all input tokens (≈$314)** | `tools_rent.py` |
| **Library lookup rent** (search_library + read_source + shell `rg`/`sed` on Mathlib) | **≈88M token-turns = 39.5% of input (≈$220)**; 35–51% in every arm group | `tools_rent.py`, `tools_groups.py` |
| Largest outputs | 255 outputs ≥8k chars (7% of outputs) carry 53% of tool-output rent | §2 |
| **Statement check (local compile)** | **84/84 lean_check calls with a node_id returned `statement_check_unavailable`; 168/168 checker runs exited 97; no node ever reached `compiles_locally`** | §3 F1 |
| **`lake` via `bash -lc`** | **37/38 failed with exit 127 (`lake: command not found`); every session that tried it (37 sessions, 15/15 arms); direct-argv `lake` never failed that way** | §3 F3 |
| Lean name guessing | 741 `#check` probe lines in 26 sessions; 179 names did not exist; 205/438 (47%) of lean_check errors are "Unknown constant/identifier" | §4 |
| search_library | 227/451 (50%) zero hits; shell `rg` on the same sources returned hits 92% of the time | §4 |
| `automate=true` on a file with holes | 14/14 crashed the Lean REPL (cgroup OOM, 2 GiB); the default is `true` | §3 F8 |
| Verification | 13/13 submissions verified on the first try | §6 |
| Loops | stagnation detector fired 0 times; longest Lean failure streak was 7 checks, and every streak was resolved | §5 |

### Tool usage profile (all arms)

| tool | calls | root / recruit / referee | rejected | failed | output chars median / p90 | share of all input (rent) | median run time |
|---|---:|---|---:|---:|---|---:|---:|
| shell | 988 | 601 / 387 / 0 | 0 | 180 | 1.5k / 6.9k | **22.1%** | 0.7 s |
| lean_check | 528 | 297 / 114 / 117 | 0 | 236 | 0.7k / 2.0k | 3.0% | 3.1 s |
| search_library | 451 | 326 / 103 / 22 | 0 | 0 | 0.2k / 10.1k | **11.8%** | 1.0 s |
| commons_node | 329 | 290 / 39 / 0 | 24 | 0 | 0.4k / 0.6k | 1.2% | 0.4 s |
| commons_read | 323 | 208 / 44 / 71 | 6 | 0 | 2.6k / 3.9k | 4.4% | 0.2 s |
| commons_post | 313 | 205 / 42 / 66 | 1 | 0 | 0.1k / 0.1k | 0.2% | 0.3 s |
| message | 219 | 92 / 127 / 0 | 3 | 0 | 0.1k / 0.1k | 0.2% | 0.3 s |
| write_file | 115 | 82 / 33 / 0 | 0 | 0 | 0.3k / 0.3k | 0.2% | 0.4 s |
| read_source | 89 | 54 / 25 / 10 | 0 | 0 | **12.1k / 22.8k** | **11.5%** | 0.4 s |
| commons_claim | 63 | 60 / 3 / 0 | 0 | 0 | 0.5k | 0.4% | 0.1 s |
| inbox | 63 | 42 / 13 / 8 | 4 | 0 | 0.1k / 0.8k (51 empty) | 0.1% | 0.3 s |
| submit_review | 63 | 0 / 0 / 63 | 0 | 0 | 1.7k | 0.0% | 0.1 s |
| read_file | 40 | 23 / 17 / 0 | 6 | 0 | 6.7k / 18.7k | 1.4% | 0.4 s |
| commons_query | 23 | 21 / 2 / 0 | 0 | 0 | 1.6k / 10.3k | 0.4% | 0.4 s |
| recruit | 17 | 17 / 0 / 0 | 0 | 0 | 0.4k | 0.1% | 0.1 s |
| notebook | 16 | 15 / 1 / 0 | **6 (38%)** | 0 | 0.8k / 36.5k | 0.4% | 0.6 s |
| verification_status | 14 | 12 / 2 / 0 | 1 | 0 | 4.4k | 0.0% | 20.7 s (waits) |
| wait / submit_for_verification / return_result / read_artifact / run_computation | 14 / 13 / 12 / 5 / 3 | | 0 | 0 | | <0.5% | |
| lean_sketch, load_skill, search_literature, fetch_source | **0** | | | | | | |

These tools were offered but never called. `lean_sketch` is the purpose-built "holes become
nodes" tool, and the playbook recommends that step. `load_skill` was listed in 45 of the 123
prompts. Their schemas are still sent with every request (see F13). `run_lean_scratch`,
`check_lean_type` and `lookup_library_declaration` are legacy tools. They were not in the
society catalog, so no arm used them.

Per session, a root averages 67.7 calls ($11.42), a recruit 48.8 ($7.61) and a referee 5.2
($0.24; median $0.21). Referees never used shell. They read the node, ran lean_check, posted
and submitted.

### By arm group

| group | sessions | calls | ledger $ | rejections /100 calls | failures /100 | lookup share of input | lake exit-127 | stmt-check unavailable | zero-hit searches | `#check` misses / lines |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| cal/pilot | 16 | 552 | 69.37 | 1.99 | 11.8 | 36.0% | 9 | 12 | 51 | 21/73 |
| S (attempt 1) | 17 | 322 | 25.00 | 0.00 | 10.9 | 51.4% | 4 | 8 | 43 | 24/110 |
| **S-r2** | 45 | 961 | 155.41 | 1.87 | 8.1 | 35.1% | 5 | 31 | 52 | 45/162 |
| **I-01..08** | 36 | 1,650 | 286.53 | 1.27 | 12.7 | 41.5% | 17 | 29 | 75 | 87/387 |
| single | 9 | 216 | 31.97 | 0.46 | 13.0 | 42.8% | 2 | 4 | 6 | 2/9 |

Every friction below appears in every design: society, independent and single. Two classes
are specific to the society. Short-id NOT_FOUNDs (5/5 in S-r2) grow with cross-agent
citation. `CROSS_LAB_MESSAGE` exists only where there are labs. Review-cap rejections are
concentrated in the I arms (11 of 14).

---

## 2. Where the tokens go: context rent

Tool outputs make up 56% of every input token sent in the study. A lookup's result is
re-sent on every later turn, so one 36.8k-char `read_source` issued at turn 50 of a 110-turn
session costs 0.87M tokens. It happened twice, in two separate arms: I-08 `83c05a6d` t49 and
I-01 `5e3f035f` t50, both reading `mathlib/Mathlib/Analysis/Normed/Lp/PiLp.lean`.

| source of rent | share of all input | ledger $ |
|---|---:|---:|
| shell: `rg` searches over Mathlib (319 calls, 263 with regex alternation, 299 piped to `head`) | 12.7% | 70.9 |
| search_library (451 calls; hits capped at 40 in directory order, one-line snippets, each hit has both `path` and `guest_path`) | 11.8% | 65.6 |
| read_source (89 whole-file reads of only **16 distinct files**; 19 reads of `Matrix/Stochastic.lean`) | 11.5% | 63.9 |
| commons_read (≈15–20% of each output is digests and actor ids) | 4.4% | 24.4 |
| shell: Lean compile output | 4.1% | 22.8 |
| shell: `sed`/`cat` views of Mathlib | 3.1% | 17.5 |
| lean_check | 3.0% | 16.9 |
| everything else | ≈5% | |

The same few hundred lookups are repeated across agents: 69 search queries appear in more than
one session (261 calls), 11 of the 16 files read with read_source were read in several
sessions, and 109 `#check` names were probed in more than one session (439 probes). At N
agents working one problem, this work grows about linearly in N, and each copy is paid for
again on every turn.

**Counterfactual: elide stale large outputs** (`tools_elide_sim.py`). Replace an output of more
than 4k chars with a 300-char stub plus a re-fetch handle once it is 5 turns old, and charge
a pessimistic 10% re-fetch. That saves 66M tokens, 30% of all input ($165 ledger in this
study). With a 2k-char threshold it saves 36% ($200). Latency barely depends on input size:
provider latency ≈ 1.5 s + 0.003 s per 1k input + 7.1 s per 1k output tokens. So the gain is
**money and TPM**, not speed. S-r2 was throttled by the 2M TPM org limit (known: about 320k
TPM per worker). Cutting 30% of input lets the same limit run about 1.4× as many concurrent
agents. Provider caching complicates the dollar saving (eliding mid-context invalidates the
cached prefix after it), so elide in batches, for example every 20 turns.

Unicode escaping adds more. `responses.py:1064` serializes tool outputs with
`json.dumps(visible_output)` and the default `ensure_ascii=True`, so every `∑ ι ℝ ≤ ∀ ᵥ*` in
Lean output reaches the model as a 6-char `\uXXXX` escape. Upper estimate: ≤6.5M token-turns
(≈3% of input, ≤$16).

---

## 3. Friction catalogue (ranked by cost × consequence)

Classes: **HB** = harness bug; **CT** = unclear tool contract or docs; **LG** = legitimate
guard; **AM** = agent mistake.

### F1. Local-compile statement check never worked (HB). Consequence: high
- **What:** lean_check with a `node_id` compiles the file and should record a local compile,
  moving a node to `compiles_locally`. All 84 attempts that reached the check returned
  `"local_compile": {"recorded": false, "reason": "statement_check_unavailable"}`. That covers
  13 of the 15 arms; the two doeblin calibrations never called lean_check with a node_id. The
  other 19 calls with a node_id stopped earlier with "The compile was incomplete."
- **Mechanism:** the workbench container runs `--read-only` with only `/work` as a tmpfs
  (`execution/local_docker.py:572-586`). The checker is staged by
  `mkdir -p /tmp/physharness && mv …` (`orchestration/lean_session.py:988-1011`). stderr of
  every run: `mkdir: cannot create directory '/tmp/physharness': Read-only file system`. The
  run then exits 97, the harness re-uploads, retries, exits 97 again, and maps the result to a
  soft reason. The model never sees the stderr. Evidence: S-r2 workspace operation
  `a84c8f93-…:call_X9l3y3LdJUcImenXn7Fnfk7R:statement-check:check-run-0`. All 168 check-runs
  in the study exited 97.
- **Effect:** no commons node in any arm ever reached `compiles_locally`. S-r2 ended with 22
  nodes stuck at `formally_stated`. 57 agent calls in 21 sessions (10 arms) discuss it, for
  example calibration-aperiodic `11662f67` t6: *"local_compile.recorded:false reason
  statement_check_unavailable (platform glitch)"*, and S-r2 `3d151e45` t14: *"local_compile
  recorded false reason statement_check_unavailable (unexpected)"*. Two sessions then read
  the checker source with shell (`sed -n '1,220p' /work/.physharness/statement_check.py`).
  The failure was already visible in calibration-aperiodic (9 occurrences; that arm started at
  09:08 UTC, 42 min before S-r2).
- **Cost:** direct cost is small (2 investigation calls $0.20; about 1 container-minute of
  failed runs), but one rung of the evidence ladder was dead in every arm. At 10× or 100×
  agents, 840 or 8,400 silent failures, and any mechanism built on `compiles_locally` (partial
  credit, review routing) is blind.
- **Fix (XS):** give the container a `--tmpfs /tmp` (or run the checker from
  `/work/.physharness`, as the `repl_inline` daemon already does). Run a checker self-test at
  provision time. Treat `statement_check_unavailable` as an infrastructure alarm in
  `run-team.err` and the metrics, not as a per-call soft reason.

### F2. Library look-ups flood the context and names are guessed (CT). ≈40% of input
- **What:** agents search Mathlib by guessing identifier names. 367 of 451 search_library
  queries are identifier-shaped. search_library is a literal, case-folded substring scan
  (`workspace_tools.py:254-315`). It returns the first 40 hits in directory order, with no
  ranking and no regex, so it found nothing for half the queries. 160 of 223 zero-hit
  searches were followed by another search_library call (streaks of up to 5). Agents moved to
  shell `rg` with regex alternation (319 calls, 92% non-empty) and to `#check` batches in
  lean_check: 100 pure probe calls, 75% failed because at least one guessed name was
  missing.
- **Repeated misses:** `Matrix.vecMul_mul` 0/11 found across 8 sessions, `Matrix.vecMul_pow`
  0/7, `Matrix.vecMul_assoc` 0/4, `Matrix.dotProduct` 0/4 (renamed in the pinned Mathlib).
  Unknown identifiers are 47% of all lean_check errors (205/438).
- **Cost:** zero-hit searches: 227 calls, $18.81, 15.7 agent-min. `#check` probes: 100 calls,
  $19.60, 17.6 min. Lookup rent: ≈$220 (39.5% of input). 10×: ≈$2.2k; 100×: ≈$22k. The waste
  is duplicated across agents (§2).
- **Fix (M):** replace search_library and read_source with **one** library tool that answers
  in declarations, not raw lines. It would take a name fragment, regex or type pattern
  (Loogle/`#find`-style, against the pinned environment) and return compact
  `Name : type — file:line` rows ranked by declaration match, plus "did you mean" suggestions
  for unknown names. Its read mode would return one declaration or a line range, never a whole
  file. Together with elision (§2), this goes after most of the ≈40% lookup share. The
  cheaper alternative is to delete both tools and rely on shell `rg`, which agents already
  preferred, together with elision.

### F3. `lake` is missing from PATH in login shells, although the tool description names it (HB/CT)
- **What:** the shell tool description says *"Run a command in the offline workspace VM
  (python3, lake, lean, ...). For Lean use cwd='/opt/sources/physlib'"*. `bash -lc 'lake env
  lean …'` failed 37 of 38 times with `bash: line 1: lake: command not found` (exit 127). The
  same command as direct argv `["lake","env","lean",…]` never hit this (66 ok, 48 Lean
  errors). The login shell resets PATH, so `/opt/lean/bin` is dropped. It happened once in
  every session that tried it: 37 sessions in all 15 arms.
- **Recovery:** 10 sessions switched to `/opt/lean/bin/lake`, 11 to direct argv and 12 to
  lean_check, some after `find / -maxdepth 5 -name lake` probes (33 env-probe calls in total).
- **Cost:** 55 calls, $7.75, 4.5 min lower bound (the failed call, env probes and repeats);
  114 calls, $16.85, 10.4 min upper bound (everything until the next successful compile).
  10×: $78–169; 100×: $775–1,685. Pure waste.
- **Fix (XS):** add `/etc/profile.d/lean.sh` or symlinks in `/usr/local/bin` to the image, or
  run the shell tool with `bash -c` instead of a login shell.

### F4. Workspaces are per-agent, but nothing says so, and files can't be shared (CT, missing capability). Superlinear
- **What:** each agent has its own VM. 6/6 `WORKSPACE_TRANSFER_REJECTED` rejections were an
  agent reading a peer's path (`read_file scratch/Primitive.lean`, …). The provider's specific
  reason (*"Guest refused a missing, linked, non-regular or unsafe workspace path"*,
  `local_docker.py:447`) is replaced by *"Workspace helper refused the operation; VM is
  available."* with the generic remediation *"Inspect the operation and correct its inputs"*.
  Agents inferred the isolation themselves (I-05 `a6f7ac26` t75: *"I cannot access your
  `scratch/PositiveMixing.lean` (workspace per-branch isolated…). please send full source via
  message chunks ≤20k"*).
- **Effect:** code moves between agents as chat text. About 120 posts and messages carry Lean
  source (≈210k chars). 72 of S-r2's 162 posts mention copy-ready or full source or isolation
  (for example *"Cross-workspace copy-ready sources now available with FULL UUIDs"*). At
  least 40k chars of peer Lean were re-typed by the receiver into write_file, lean_check or
  shell. That figure is a lower bound because transcript text is cut at 4k chars. The S-r2
  root assembly depended on this relay.
- **Cost:** direct cost is small ($1.04 for the rejections, ≈$0.16 of re-typed output), but
  the coordination turns (asking for source, waiting, re-assembling) grow with the number of
  agents whose work must be integrated. **Superlinear.**
- **Fix (M):** add a content-addressed share. `publish(path)` returns an artifact id, and
  `write_file` or `read_file` accept `artifact_id`, or a read-only `/shared` mount of
  published files. State "your workspace is private to you" in the shell/read_file
  descriptions, and pass the provider's reason through.

### F5. Short ids in posts lead to NOT_FOUND and fabricated UUIDs (AM, induced by the contract). Superlinear
- **What:** 86 of 532 posts and messages cite bare 8-hex ids (186 ids). All 5 commons_read
  NOT_FOUNDs (all S-r2) trace back to them. Two looked up a bare prefix (`post_id:"b2e26ba8"`,
  `"2943c42e"`). Three sent a **made-up completion** of a prefix, for example
  `e827d78b-3164-4fc9-…` and `e827d78b-1785-414c-…` for the real `e827d78b-ccc8-…`, and
  `dfdd892e-c78c-…` for `dfdd892e-5723-…`. One agent then posted *"post b2e26ba8 is an
  abbreviated ID, not retrievable by commons_read; please share full post UUID"*.
- **Cost:** $1.26 direct plus the correction posts. The frequency grows with cross-citation
  density, so it is a society-scale problem.
- **Fix (S):** accept any unique id prefix of 8 or more hex characters in every id argument
  (git-style). On ambiguity, return the candidates. This also shortens every citation.

### F6. Budget caps are reported as input errors, and they contradict the norms (LG with a bad error)
- **What:** `request_review` creates a referee task, so it competes for the experiment's
  `max_total_tasks`. There were 14 `TASK_TOTAL_CAP` and 2 `TASK_PENDING_CAP` rejections. In
  the I arms, 11 of 27 review requests (41%) were refused. The envelope says *"Experiment task
  total cap reached."* and then *"Inspect the operation and correct its inputs before
  retrying"*. One agent retried the identical request on the same node 31 turns later
  (calibration-aperiodic `95c806f9` t34, t65). Others recorded the consequence, for example
  I-03 `3f701001` t32: *"reviewers currently capped, so node still informal."* The
  constitution tells agents to "Get a referee" and "Ask for a referee before investing heavily
  in formalization". Neither the tool description nor the norms mention that a review spends
  a task slot.
- **Cost:** $2.78 direct. The larger cost is nodes that stayed informal.
- **Fix (XS/S):** give each code its own remediation: "budget, not input: limit N, used N; do
  not retry". Expose the remaining budget in the tool description or result. Consider a
  separate review pool.

### F7. notebook rejects commons ids as "evidence" with a misleading message (CT)
- **What:** 6/16 notebook calls were rejected (38%, the highest rate of any tool) with
  `CONTEXT_EVIDENCE_KIND: "Native/private checkpoints are not portable evidence."`. The agents
  had passed commons node and post ids. `memory.py:24,108-116` accepts only
  artifact/claim/task/verification/source/program records. The error names neither the
  offending id nor the accepted kinds. In 5/5 sessions the agent dropped `evidence_ids`
  entirely (one after a second identical-kind try), so the notes lost their citations.
- **Cost:** $1.87, 1.2 min.
- **Fix (XS):** accept commons node and post ids (they are the society's evidence), or name
  the id and the accepted kinds. Better still, fold notebook into commons posts or remove it.

### F8. `automate=true` (the default) crashes the Lean REPL on files with holes (bad default)
- **What:** 14 of 14 lean_check calls with `automate=true` on a file with `sorry` holes came
  back with `reason_code: lean_repl_crashed`, and each coincides with a `cgroup_oom_observed`
  workspace operation. Running `aesop`, `exact?` and the other automation in a 2 GiB container
  exhausts memory. These calls took ≈10 s instead of ≈3 s. No call with holes and automation
  succeeded. 13 of the 14 crashes were referee sessions, mostly at turns 2–3 (8 in S-r2). Agents learned to pass
  `automate=false` (481 calls).
- **Cost:** 14 calls, $0.65, about 2.5 min. Small, but the feature delivered no value in this
  study.
- **Fix (XS):** default to `automate=false`, or run automation under its own memory and time
  bound with only cheap tactics.

### F9. `inbox` duplicates the push channel (redundant tool)
- **What:** peer updates arrive automatically (871 `research_network_updates` batches), so 51
  of 63 inbox calls were empty and 23 were identical repeats (polling). All 4
  `DELIVERY_MISMATCH` rejections were acknowledgements of a delivery that had also been
  pushed. In 8 cases the push re-injected the batch that inbox had just returned.
- **Cost:** inbox calls $11.99 and 6.9 min; mismatches $1.02.
- **Fix (XS):** remove inbox (the push already delivers and implicitly acknowledges), or make
  the acknowledgement idempotent.

### F10. Unicode escaping in tool outputs (HB, inefficiency)
See §2. ≤6.5M token-turns (≤$16). Fix (XS): `json.dumps(..., ensure_ascii=False)` in
`execution/responses.py:1064`.

### F11. Hidden side effects and log lines without codes (observability)
- lean_check with a `node_id` also renews the agent's claim. The renewal silently failed 62 of
  103 times (`claim_renewed: false`, CLAIM_NOT_HELD). Each failure writes a bare
  `command_rejected` line to `run-team.err`. The service logs `operation` and `error_code` as
  `extra`, and the formatter drops them (`service.py:805-812`).
- The known list gives `command_rejected` as a rejection code, but it is not a code. It is the
  generic service log line: 125 across all arms. The model-visible rejections match
  `Research tool rejected: <CODE>` one-for-one (51 = 51). Most of the remaining lines are these
  hidden renewals. Exact attribution is impossible because the lines carry no code.
- **Fix (XS):** include the error code and operation in the log format. Report side effects
  explicitly, or split them out of lean_check.

### F12. Small guards, mostly well handled (LG/AM)

| code | n | what the agent tried | harness reason (source) | next action | class |
|---|---:|---|---|---|---|
| CROSS_LAB_MESSAGE | 3 | message a branch in another lab | `cross_lab_direct_messages: false`; remediation "Post on the relevant commons node" | 2/3 posted on the commons on the next turn or the one after; 1 carried on with library search | LG, good error |
| REVIEW_PRECONDITION | 2 | informal review of a `formally_stated` node | "A informal review does not apply…" (typo) | moved on or posted instead | LG |
| LEAN_STATEMENT_REQUIRED | 2 | fidelity review before a Lean statement | remediation names `set_lean_statement` | 1/2 called set_lean_statement next | LG, good error |
| GOAL_NODE_RESERVED | 2 | `set_lean_statement` on the goal node at turn 4 (I-05, single) | rejected **after** 2.8 s of Lean elaboration | moved on | LG; check the reservation first; the description doesn't mention it |
| NOT_FOUND (verification) | 1 | successor session reading a peer's receipt (I-04 `6c4f0368` t1) | receipts are branch-scoped; hidden and missing look the same | messaged the peer | LG |
| NODE_CLOSED | 1 | referee posts a `finding` on a node closed meanwhile | closed nodes take only synthesis or update, which referees can't post | re-read the node, then submit_review | CT gap |
| DEPENDENCY_CYCLE | 1 | link in the wrong direction | clear remediation | moved on | LG |
| INVALID_ARGUMENTS | 2 | lean_name without lean_statement; two ids in commons_read | precise message | fixed on the next turn (2/2) | AM |

### F13. Schema and catalog overhead (CT, minor)
- The strict schemas mark every property required, so each commons_node call spells out all
  15 fields. That is 48k chars of `null` and `[]` across 329 calls: ≈19k output tokens and
  ≈2.3 min of generation at 7.1 ms per token.
- Turn-1 input is 8.5–8.9k tokens for a 16.5–17.2k-char root prompt, which suggests about
  3–4.5k tokens of fixed per-request overhead (tool schemas plus system text). That overhead
  is re-sent on all 3,774 turns (≈5–7% of input; rough estimate). Tools that were never
  called (lean_sketch, load_skill, search_literature, fetch_source) and redundant ones (inbox,
  notebook) are part of it.
- submit_for_verification requires the file's sha256, so agents ran `sha256sum` in the shell
  30 times first. That is a deliberate exact-capture guard, so keep it, but the tool could
  also return the digest it captured.

---

## 4. Lean workflow

- **Options in the catalog:** lean_check (persistent REPL, `repl_inline` backend for 527/528
  calls), or shell `lake env lean <file>` after write_file. There was no run_lean_scratch.
  The split was 528 lean_check calls and 402 shell compiles. Agents used lean_check for small
  lemmas and `#check` probes (median source 670 chars, max 4k) and the shell for whole files.
  The S-r2 split was 169/22 (53 of its lean_checks were referees'). The I arms split 224/260,
  and single 14/44.
- **Speed is not the bottleneck:** lean_check takes 3.0 s median warm (p90 4.3 s) and 3.4 s
  cold, the first call in a session. A shell compile takes 2.8 s. One edit→check cycle takes
  ≈8.4 s: 5.5 s of model turn plus 2.9 s of tool. No timeouts were observed (the only
  non-zero exit codes were 1, 2, 97 and 127).
- **Loops per session:** 96 sessions ran Lean checks: median 3.5 per session, p90 26, max 47
  (930 in total), and 43% of checks failed. In lean_check, 151 of the 162 theorems it was
  used on compiled; the median was 1 check to reach ok (p90 2, max 5). Iteration mostly
  happened in shell compiles.
- **Error types:** lean_check (438 errors): unknown identifier or constant 47%, tactic failed
  13%, unsolved goals 11%, type mismatch 10%, rewrite failed 6%, parse 4%. Shell compiles
  (163 errors, lower bound): type mismatch 38%, rewrite failed 16%, tactic failed 12%,
  unsolved goals 12%, module path 2%. Naming, not proving, dominates the fast-feedback tool
  (F2).
- **Lookup hit rates:** search_library 50% zero hits; read_source always "succeeded" but
  returned whole files (median 12k chars; 89 reads of 16 files); shell `rg` 92% non-empty.
  `#check` lines: 741 probes, 24% missing, and 92 re-checks of a name already checked in the
  same session.

## 5. Shell use, wasted calls and loops

Shell calls by purpose (`tools_shell.py`; the regex classifier is heuristic):

| purpose | calls | failed | rent share of input | better tool? |
|---|---:|---:|---:|---|
| Lean compile (`lake env lean`, `/opt/lean/bin/lake`) | 402 | 160 (37 PATH, the rest Lean errors) | 4.1% | fine; fix PATH (F3) |
| Library search (`rg` over `/opt/sources`) | 330 | 6 | 13.1% | a declaration-level library tool (F2) |
| File edits (python `.replace`/append, `sed -i`, `cat >>`) | 69 | 0 | 0.2% | works; an `edit_file` would only standardize it |
| Library views (`sed -n`/`cat` of Mathlib) | 49 | 0 | 3.1% | declaration read (F2) |
| Workspace inspect/view (`ls`, `sha256sum`, `sed` of own files) | 91 | 5 | 0.7% | fine |
| Environment probes (`command -v lean`, `find / -name lake`) | 33 | 6 | 0.7% | none needed once F3 is fixed |
| Other (`sleep 15`/`sleep 20` in S-r2, `date`, python) | 14 | 3 | <0.1% | `wait` |

- **Loops:** the stagnation detector (`execution/stagnation.py`) raised 0 signals. Identical
  repeated calls: 138, of which only 1 was consecutive. Shell accounts for 72, mostly the same
  compile command after an edit (legitimate). inbox polling accounts for 23. There were 20
  commons_read re-reads and 17 identical lean_check re-runs. Lean failure streaks (checks
  until the next ok check): 151×1, 58×2, 19×3, 8×4, 7 streaks of 5–7, all resolved. Streaks
  of 5 or more cost $4.88 and 5 min. There was no pathological looping. Repeated failures
  were short and ended in success.
- **Wasted shell calls:** 37 PATH failures, 33 env probes, 2 harness-internals
  investigations (F1) and 2 `sleep` polls.

## 6. What worked well

- **Verification path:** 13/13 `submit_for_verification` calls verified on the first attempt
  (every verified arm), each followed by a `verification_status` wait (median ≈21 s). The
  "compile locally in the shell, sha256sum, submit" pattern was reliable.
- **Rejections are rare, cheap and recoverable:** 51 rejections (1.4% of calls, 1.6% of
  spend). There were no `TOOL_UNAVAILABLE` calls and only 2 `INVALID_ARGUMENTS`, both fixed on
  the next turn. Where the remediation was precise (CROSS_LAB_MESSAGE, LEAN_STATEMENT_REQUIRED,
  INVALID_ARGUMENTS), agents usually followed it within 1–2 turns.
- **Fast Lean feedback:** a 3 s REPL check with structured messages. Most proof iteration
  converged within 1–3 checks.
- **One general shell covered the gaps:** file editing through python replace (0 failures),
  regex search, hashing and environment discovery, with no dedicated tool for any of them.
  That supports fewer, more general tools.
- **Referee loop is lean:** median 5 calls, 6 turns and $0.21 per referee session (read,
  check, post, submit).
- **No looping:** there was no loop for the detector to flag, and failure streaks were short.

## 7. Ranked fixes (impact ÷ effort; fewer tools, less scaffolding)

| # | change | removes | effort | study saving | at 100× agents |
|---|---|---|---|---|---|
| 1 | Writable `/tmp` (tmpfs) or run the checker from `/work`; checker self-test at provision; alarm on `statement_check_unavailable` | F1 (the dead `compiles_locally` rung, 57 confused calls) | XS | restores a ladder rung; $0.2 direct | prevents 8,400 silent failures |
| 2 | `lake`/`lean` on PATH for login shells, or `bash -c` | F3 | XS | 55–114 calls, $7.75–16.85, 4.5–10 min | $0.8–1.7k, 7–17 agent-hours |
| 3 | Elide or clear stale tool outputs over 4k chars after about 5 turns (stub plus re-fetch handle; batched to keep the cache) | 30% of all input tokens | M | ≈$165 ledger; about 1.4× the agents per TPM | ≈$16k; the TPM limit is what binds at scale |
| 4 | One declaration-level library tool (name, regex or type search, ranked `Name : type — file:line`, did-you-mean) replacing search_library and read_source, or delete both in favor of `rg` plus #3 | F2: 227 zero-hit searches, 100 `#check` probes, whole-file reads | M | $38 of direct calls plus a large part of the $220 lookup rent | ≈$4k direct plus a large part of $22k rent |
| 5 | Accept unique id prefixes (≥8 hex) everywhere | F5 (all commons_read NOT_FOUNDs, made-up UUIDs) | S | $1.3 plus corrections | superlinear in cross-citation |
| 6 | Specific error remediations: caps ("budget, not input: limit N, used N"), pass the provider reason through for WORKSPACE_TRANSFER_REJECTED, name the offending kind for CONTEXT_EVIDENCE_KIND; codes in log lines | F6, F7, F11, part of F4 | XS | ≈$6 plus the repeated cap request | linear |
| 7 | Shared, content-addressed files (`publish` → artifact id; write_file/read_file from artifact id); say "your workspace is private" | F4 (code relayed as chat, re-typing) | M | ≥40k chars re-typed plus the relay turns | superlinear with integration |
| 8 | `automate=false` by default, or bounded automation | F8 (14/14 OOM) | XS | 14 calls, about 2.5 min | linear |
| 9 | Remove `inbox` (the push delivers); fold `notebook` into commons posts; drop never-used `lean_sketch` and `load_skill` from the catalog | F9, F7, part of F13 | XS–S | $13 plus schema tokens on every turn | linear (on every turn) |
| 10 | `ensure_ascii=False` for tool outputs | F10 | XS | ≤$16 | ≤$1.6k |
| 11 | Check the goal-node reservation before elaborating; let referees post a finding on a closed node or point them to submit_review; accept omitted optional fields | F12, F13 | XS | seconds and about 19k output tokens | linear |

Fixes 1, 2, 6, 8 and 10 are configuration or one-line changes that remove pure waste. Fixes
3 and 4 matter most as the number of agents grows. They go after the ≈56% of input tokens
that is re-sent tool output, and input tokens are what the TPM limit counts. Fixes 5 and 7
address the only costs here that grow faster than the number of agents.

## 8. Method and reproducibility

Run from `<repo>/.superpowers/live-run/audit/scripts/` with plain `python3` (standard library
only; everything is read from `../data`):

- `tools_lib.py`: loaders, turn and session indexes, `cost_of`
- `tools_misc.py`: totals, tool profile, rejection costs, statement check, lake detour,
  automation versus OOM, search and inbox, verification
- `tools_rejections.py`: every rejection with arguments, output and the next 5 calls
  (`tools_out/rejections_dump.txt`)
- `tools_shell.py`: shell purpose classifier (`tools_out/shell_rows.json`)
- `tools_rent.py` and `tools_elide_sim.py`: context rent by tool, unicode escapes,
  counterfactual elision
- `tools_lean_names.py`: `#check` probes and repeated names (`tools_out/check_probes.json`)
- `tools_lean_errors.py`: Lean error taxonomy
- `tools_loops.py`: identical calls, failure streaks, checks until ok
- `tools_ids.py`: made-up or short ids
- `tools_relay.py`: peer Lean re-typed into own workspace
- `tools_groups.py`: per-group rates

`tools_out/search_rows.json` was produced by an inline pass whose logic is summarized in
`tools_misc.py:search()`: parsed search_library outputs with (arm, session, turn, query, hit
count, reason, output chars).

The workspace-operation stderr in F1 comes from a read-only query (`mode=ro`) of the S-r2
`harness.db` `workspace_operation` records. `run-team.err` was only counted with grep for
rejection strings. No line of it was copied.

**Caveats:** transcript text is cut at 4,000 chars, so re-typing counts, shell error
taxonomies and escape counts beyond the cut are lower bounds or extrapolations. The shell
purpose classifier is regex-based. The dollar figures are ledger dollars. The elision saving
ignores cache effects and assumes a 10% re-fetch rate.
