# Society and coordination mechanics: overhead vs value (S1 live runs)

Analyst dimension: commons, referees, discussion and delivery, messages and waits, workforce.
Data: read-only harness databases, runtime-event artifacts and native checkpoints of every arm
(`<repo>/.state/s1/arms/<arm>/`). Scripts: `<repo>/.superpowers/live-run/audit/scripts/`
(list at the end).

Conventions
- `t` = seconds since the experiment record was created (S-r2: 2026-09-26T09:50:03Z). Roots start
  at t=20 s. S-r2's verification landed at t=1802.5 s (30.0 min on this base; the report's
  29.7 min is `time_to_root_seconds` = 1782 s from experiment start).
- Dollars come from the harness ledger (`reservations.actual`), i.e. the conservative price table
  with **no cache discount**. 98% of root input tokens were cached reads, so every input-token
  dollar figure below is an upper bound; the shares hold regardless of price.
- R1–R6 are S-r2's roots in creation order: R1 `7816b570` (task `1c00e232`, the assembler),
  R2 `30fcafbe` (`66edc340`), R3 `8d467a80` (`5e6f961b`), R4 `211ddfea` (`8983da7c`),
  R5 `404cc5c8` (`27242a2e`), R6 `df99bdc4` (`1946764c`). Each root founded its own lab.
- "Society" tools = commons_query/read/node/post/claim, inbox, message, recruit, wait,
  read_artifact. "Measured" lines are facts from the data; "Interpretation" lines are mine.

## 1. Key numbers

### S-r2 (6 roots, concurrency 8, aperiodic target)

| Quantity | Value |
|---|---|
| Wall clock to verified root | 1802.5 s (30.0 min); submission t=1775.3 s, verifier 27 s |
| Cost | $155.41: roots $146.78 (94.4%), referees $8.63 (5.6%) |
| Task slots | 40 = 6 roots + 34 referees + **0 recruits**; cap hit at t=1312 s (one rejected review request) |
| Agent time | roots 176.6 agent-min, referees 27.5 agent-min |
| Root burn rate | $0.83 per root-minute; 73.5k input tokens per turn; 786 turns |
| Society share of root turn time | **53%** (one-root arms: 16–33%) |
| Society share of root input tokens (context rent) | **35%**, of which pushed peer updates 16% (one-root arms: 10–19%, updates 3–6%) |
| Referees | 34 tasks, median 6 turns, 46 s active, $0.23; queue median 57 s, total 2,230 s |
| Verdicts | 23 faithful, 10 sound, 1 unfaithful; **no decision was gated by any verdict** |
| Reviewed lemma already Lean-complete (non-referee `lean_check` ok and complete) | 59% before the request, 85% before the verdict |
| Commons | 32 nodes (31 lemmas): 22 formally_stated, 5 abandoned, 4 informal, 1 accepted, **0 compiles_locally** |
| Local-compile recording | 31 of 31 node-bound complete `lean_check`s returned `statement_check_unavailable` |
| Final proof | 23 declarations, 23.6 KB; **71% of its characters were written by roots other than the submitter**; 16 of 31 lemma nodes appear in it by `lean_name` |
| Discussion | 197 posts (127 agent, 35 referee, 35 platform); 646 pushed items; 0 messages |
| Pushed items later read in full by the recipient | 8.2%; 20% of pushed items were the recipient's own post |
| Peer waits | 7 waits, all on R1, **7/7 ended by timeout**, 698 s total |
| Root spend after the root's last contribution to the accepted proof | **$56.46** (38% of root spend) |

### All arms (script `arm_table.py`)

| arm | time to proof (min) | cost $ | roots | recruits | referee tasks | referee $ (share) | society share of agent time | society share of input tokens (pushed updates) | posts | pushed items | messages | nodes | peer waits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S-r2 | 30.0 | 155.41 | 6 | 0 | 34 | 8.63 (6%) | 53% | 35% (16%) | 197 | 646 | 0 | 32 | 7 |
| pilot-doeblin | 6.5 | 22.75 | 3 | 2 | 1 | 0.09 (0%) | 31% | 24% (8%) | 21 | 83 | 12 | 5 | 0 |
| single | 14.1 | 31.97 | 1 | 2 | 6 | 1.59 (5%) | 24% | 17% (5%) | 20 | 37 | 13 | 4 | 0 |
| I-01 | 17.7 | 49.49 | 1 | 1 | 2 | 0.32 (1%) | 31% | ≥10% (3%)¹ | 13 | 47 | 35 | 6 | 1 |
| I-02 | 13.8 | 33.58 | 1 | 1 | 2 | 0.36 (1%) | 33% | 16% (5%) | 17 | 36 | 13 | 9 | 0 |
| I-03 | 14.4 | 34.53 | 1 | 1 | 2 | 0.49 (1%) | 33% | 17% (5%) | 12 | 45 | 29 | 5 | 0 |
| I-04 | 14.0 | 35.06 | 1 | 1 | 2 | 0.35 (1%) | 30% | 17% (5%) | 12 | 45 | 32 | 4 | 2 |
| I-05 | 14.8 | 38.92 | 1 | 1 | 2 | 0.76 (2%) | 26% | 17% (5%) | 13 | 48 | 27 | 5 | 1 |
| I-06 | 11.9 | 18.60 | 1 | 1 | 2 | 0.38 (2%) | 18% | 15% (5%) | 12 | 19 | 5 | 3 | 0 |
| I-07 | 17.3 | 39.37 | 1 | 1 | 2 | 1.10 (3%) | 25% | 19% (6%) | 17 | 33 | 13 | 7 | 0 |
| I-08 | 13.8 | 36.99 | 1 | 1 | 2 | 0.33 (1%) | 26% | 13% (4%) | 12 | 36 | 22 | 4 | 2 |
| calibration-aperiodic | 17.8 | 34.61 | 1 | 1 | 2 | 0.40 (1%) | 30% | 12% (3%) | 15 | 34 | 10 | 10 | 1 |
| calibration-doeblin-r2 | 8.0 | 10.54 | 1 | 1 | 0 | 0 | 16% | 11% (4%) | 3 | 14 | 10 | 1 | 0 |

¹ I-01's recruit session was compacted, so part of its context growth is unattributable.
S attempt 1 (failed, 3.5 min): its 6 roots had already spawned 10 referee tasks by t=259 s,
about 0.4 per root-minute, the same rate as S-r2.

Across all 15 arms there were 63 reviews: 37 faithful, 25 sound, 1 unfaithful, 0 gaps, 0 wrong.

## 2. Findings

### F1. Task economy: referees filled the slots but not the bill; roots' idle time is the real cost

Measured
- **Who spawned referees and why.** All 34 were `commons_node(action=request_review)` calls by
  the roots, evenly spread (R1, R4, R5, R6: 6 each; R2, R3: 5 each). There is no platform
  trigger: `request_review` is agent-initiated (`commons_review.py:603`), and the prompt tells
  every agent to do it: the norm "Ask for a referee before investing heavily in formalization"
  and playbook step 4 "Get a referee" (`orchestration/society_prompt.py:20,44`). Requests
  followed a mechanical chain: informal requests came a median 40 s after node creation, and
  fidelity requests 12 s (range 3–356 s) after `set_lean_statement`. 37 requests produced 34
  tasks; the 3 rejections were `LEAN_STATEMENT_REQUIRED` (t=106), `REVIEW_PRECONDITION`
  (t=1121) and `TASK_TOTAL_CAP` (t=1312, R6 on critical-path node `f0c40067`).
- **What they cost.** $8.63 (5.6% of the arm), 3.19M input and 66k output tokens, 209 turns,
  27.5 agent-min. Informal reviews averaged $0.215 (median 28 s active); fidelity reviews averaged $0.27
  (median 51 s). The referee queue (task created → leased) had a median of 57 s and a maximum of 312 s
  (`eee6cb03`), 2,230 s in total, because referees shared the 8 slots with 6 always-busy roots.
- **What they changed.** No action depended on a verdict. Authors kept formalizing in parallel:
  59% of reviewed lemmas already had a complete Lean check by a non-referee before the request,
  and 85% before the verdict. The ladder status was consumed once: R1's
  `commons_query(status=formally_stated, frontier=true)` at t=627, used as a discovery filter.
  11 of 34 reviews were on nodes that do not appear in the final proof. The two lemmas on the
  critical path, `f0c40067` (cesaro_stationary_residual) and `cb075c8e` (stationary_exists_cesaro),
  were **never reviewed**: the task cap blocked the request, and the kernel accepted the proof
  anyway.
- **The one unfaithful verdict** (review `161c3a50`, task `7a0a590b`, t=771, $0.26, node
  `13ca1d8a` by R6) was correct but inconsequential. The Lean statement was faithful; the
  informal text overclaimed a bounded-defect corollary for arbitrary P, with the counterexample
  P=(2). R6 then spent 5 turns on the rework, between t=836 and t=922: an acknowledgement post,
  abandoning the node (t=877), recreating it as `fbb6624c` with the **byte-identical Lean
  statement** (t=890), `set_lean_statement` (t=903) and a new fidelity request (t=922; task
  `358d79a9`, $0.23, faithful at t=971). R6 was on the critical path at the time. The final proof
  uses this Lean statement (`cesaro_telescope`) unchanged.
- **One-root arms.** Referees queued 89–910 s (I-01 910 s, I-02 664 s, I-03 715 s) because the
  root and its recruit held both slots. A complete Lean proof of the lemma existed before 17 of
  18 I-arm and calibration verdicts. The pilot's only referee (`af9507e6`) queued 297 s and
  produced no verdict before the target was verified, and its librarian recruit `a1be7eed` was
  never leased.
- **Where the money went.** Roots cost $0.83 per minute whether or not their work was still
  needed. Measured from each root's last post whose code entered the accepted proof (R2 t=587,
  R3 t=1143, R4 t=435, R5 t=967, R6 t=1635, R1 at submission), the roots then spent R2 $14.16,
  R4 $15.63, R5 $15.32, R3 $7.32, R6 $3.62 and R1 $0.40: **$56.46 in total**. That spend went on
  status updates, assembly-status questions, peer waits and backup re-proofs (R4 re-proved R1's
  `stationary_pos_irred` at t=1623, 22 min after R1 posted it; R2 did "parallel backup"
  stationary glue at t=1405–1538).
- **Referee load under the current rule** assumes per-agent behaviour stays as measured: 0.36
  requests per root-minute, 1.19 requests per node, 46 s active and $0.23 each.

  | Roots | Referee tasks per 30 min | Referee cost | Mean concurrent referee slots |
  |---|---|---|---|
  | 6 (uncapped) | ~64 | $15 | 1.6 |
  | 60 (10×) | ~640 | ~$150 | ~16 |
  | 600 (100×) | ~6,400 | ~$1,500 | ~160 |

  The dollar share stays near 6–10%. The damage is structural:
  - Referees and research agents share one `max_total_tasks` counter
    (`workforce.py:285–310`), so any fixed cap is consumed by referees (S-r2: 85% of the cap),
    which crowds out recruits.
  - Referees share one slot pool, so verdict latency grows with occupancy (I arms: 11–15 min).
  - Referees read node threads, so their input grows with thread length.

Interpretation: in S1 the referee layer is ceremony. The kernel is the only arbiter of
acceptance, non-root acceptance is deferred, and 85% of reviewed lemmas were already
machine-checked. "34 of 40 slots" overstates the dollar cost. The large, avoidable cost was roots
running at full burn after their contribution was finished.

### F2. Commons dynamics: real reuse happened, but through post bodies, not the graph

Measured
- **Lifecycle.** 31 lemma nodes were created between t=63 and t=1587, at 0.17 per root-minute:
  R6 11, R2 5, R1 4, R3 4, R5 4, R4 3. 22 reached formally_stated (median ~140 s after
  creation), 5 were abandoned, 4 stayed informal, and **none reached `compiles_locally`**.
  - The reason is a harness defect. Every node-bound complete `lean_check` (31 in S-r2; also
    single 4/4, pilot 3/3, I-03 4/4, I-05 2/2) returned
    `local_compile: {recorded: false, reason: statement_check_unavailable}`.
  - The statement-check run exits 97 with stderr
    `mkdir: cannot create directory '/tmp/physharness': Read-only file system`: the
    local_docker workbench root filesystem is read-only, and `DAEMON_RUNTIME_DIR` is `/tmp/...`
    (`orchestration/lean_session.py:~985–1011`).
  - Evidence: workspace_operation for `.physharness/check-35495958…` (R2, node
    `2fd27a87` / `coprime_eventually_nonneg_combination`).
- **Claims.** 158 claim events: 19 explicit claims and 139 automatic renewals, 89 of them on the
  goal node. All 6 roots claimed the goal at t=24–26 s, which carries no information. Lemma
  claims were almost only authors'. The one duplicate claim (`83686e07`: R1 at t=106, R4 at
  t=1574) did not stop R4's redundant re-proof.
- **Edges and citations.** 46 edges: 23 depends_on, 18 motivated_by, 2 duplicates,
  2 generalizes, 1 specializes. Only **1 cross-branch depends_on** exists: `cb075c8e` (R6) on
  `2636e90b` (R5). 29 of 154 citations were cross-branch.
- **Actual reuse.** I matched each declaration of the accepted proof (artifact `b7e1e51b`,
  receipt `3431b5b6`) to its earliest near-identical posted version (similarity ≥0.7; most are
  1.00). 16 of 22 lemma declarations came from other roots. By characters, the proof is R6 29%,
  R3 17%, R2 11%, R4 11% and R5 4% (other roots, 71% in all), and R1 29% (its own lemmas 14%,
  plus 15% unposted glue: `geometric_given_stationary` and `physics_target`). The society's
  metric `cross_branch_dependencies = 1` undercounts this by an order of magnitude.
- **Transfer channel.** The Lean code crossed branches only as text pasted into post bodies:
  - 36 posts contained complete Lean proofs, and 56 posts totalling 51k characters were
    "copy-ready" or cross-workspace transfers.
  - R1 asked for this at t=593 (post `fc328033`: "full root assembly requires cross-workspace
    lemma code; could peers post copy-ready Lean source").
  - Then followed ID hunting: 11 posts (for example `4d4d6d44` at t=695, "abbreviated ID, not
    retrievable"; `10f4f403` at t=940), and 5 `commons_read` NOT_FOUND on truncated or garbled
    UUIDs (for example `post_id: "b2e26ba8"` at t=641).
  - `commons_query` does not index `lean_name`: R1's search for `uniqueness_of_geometric_bound`
    at t=1350 returned 0 items although node `6b90e5b5` has exactly that `lean_name`, so R1
    posted a question instead (`bed07ed0`, t=1367).
- **Discovery latency.** 15 of 31 lemma nodes were read (node or thread post) by another root,
  a median of 488 s after creation. 11 were cited cross-branch (median 342 s), and 14 were
  never read or cited by another root. Posts carrying Lean proofs: 18 of 31 were read by
  another root, a median of 337 s after posting.
- **Duplicate and parallel work** was low early and rose late:
  - Coprime → eventual positivity: R5 `0818191c` (abandoned), R6 `daefc216` (left informal) and
    R2's chain `2fd27a87`/`0f07a1e7`/`7d88fb96`/`e827d78b`, which won.
  - Stationary positivity: R1 `83686e07` and R6 `95e066fe`, linked `duplicates` at t=515.
  - Power-stationarity: R5 `afa8b20c` and R6 `527523e5`, abandoned as a duplicate.
  - Late backups: R4 `stationary_pos_irred` at t=1623; R2 stationary glue at t=1405–1538; three
    Cesàro residual-limit versions from R5 (t=1210), R4 (t=1239) and R6 (t=1280).

### F3. Communication: broadcast by default, pulled when it matters

Measured
- **No private channel.** Each root was its own lab and `cross_lab_direct_messages` was false,
  so S-r2 had **0 messages** (2 `CROSS_LAB_MESSAGE` rejections) and **0 recruits**. Every
  one-root arm recruited 1–2 helpers (usually a librarian or formalizer at t=20–26 s) and
  exchanged 5–35 intra-lab messages.
- **Posts.** 197 in total:
  - agents 127: 70 findings, 44 updates, 13 questions;
  - referees 35: 33 findings, 2 objections;
  - platform 35 status "update" posts.
  - 46% were on the goal thread. 44 updates (35% of agent posts) follow the harness check-in
    note ("post a short self-assessment as an update", `society_prompt.py:106`); 6 of them were
    ever read in full by another root.
- **Pushed deliveries** (automatic at turn boundaries, ≤10 items and ≤16 KB each,
  `execution/responses.py:250–316`): 644 items went to roots, about 105 per root and 3.6 per
  root-minute, 669 bytes each. By source:

  | Pushed items | Share |
  |---|---|
  | via the goal thread (everyone subscribed) | 85% |
  | the recipient's own post, echoed back | 20% |
  | peer check-in updates | 27% |
  | platform status and referee notices | 10% |
  | peer findings | 33% |

  Only 8.2% of pushed items were later opened in full (`commons_read post_id`) by the
  recipient, a median of 55 s after delivery. 22% of all posts were ever read in full by a
  non-author; 34 of those 43 were findings. The `inbox` tool (21 calls, 2 `DELIVERY_MISMATCH`)
  is largely redundant with push.
- **Context rent** (`context_rent2.py`): each turn's measured input-token growth is split
  across what was appended at that boundary, then multiplied by the turns remaining in the
  session.
  - Pushed updates were 15.9% of S-r2 root input: 9.2M tokens, about $23 at list price.
  - Society tool I/O was another 19%: 11M tokens, about $27, much of it the useful code
    transfer.
  - One-root arms: pushed updates 3–6%, society total 10–19%.
- **Peer waits.** 7 waits, all on R1, by R2 ×3, R3 ×2 and R4 ×2, with timeouts of 30–180 s.
  All 7 ended by timeout: 120, 60, 181, 121 and 120 s, plus 86 s and 9 s cut short by the
  verification.
  - The wait can only wake on a direct message from the peer (`continuation.py:1068–1143`),
    which cross-lab policy made impossible, so the mechanism could never fire. In I-01 the same
    tool worked: the root waited 98 s on its own recruit's message.
  - Side effect: each resume started a new session from a ~26k-token brief (the pre-wait
    context was 121–144k), an accidental compaction.
- **Turn time.** Society actions took 53% of root turn time in S-r2, against 16–33% in the
  one-root arms. For R6 on the critical path (t=518–1635) the share was 47%: 8.7 of 18.6 min.

### F4. Critical path of S-r2

The chain that finished last was **stationary existence**; every other component had slack.

| t (s) | Event | Evidence |
|---|---|---|
| 0 → 20 | experiment created → 6 roots leased (harness setup) | task.leased |
| 24–26 | all 6 roots claim the goal | commons.node_claim |
| 65–136 | **emergent division of labour**: R2 primitivity, R4 switches to Doeblin "since another branch is studying coprime→primitivity" (t=72), R5 takes stationary existence by Cesàro/compactness to "avoid overlap" (t=79), R3 takes block→geometric (t=95), R1 takes positivity/ℓ¹, R6 takes propagation/TV/uniqueness | posts `5779e013`, `9c892f7a`, `038c818c` |
| 136 | R5 reports Mathlib's `ContractingWith.exists_fixedPoint'` and stdSimplex compactness, then chooses compactness | goal thread |
| 160–460 | 11 sub-lemmas Lean-checked across 6 roots (Doeblin 160, positivity 172, coprime 194, block→geometric 237, minorization 249, ℓ¹ 274, uniqueness 329, simplex approx fixed point 367, block recurrence 389, primitive 432) | lean_check ok/complete |
| 518 → 1635 | **long pole**: R6's Cesàro chain (`13ca1d8a` → unfaithful at 771 → `fbb6624c` 889 → `483d2e59` 1014 → residual bridge 1280 → `f0c40067` 1290 → `cesaro_stationary_residual` post 1374 → `stationary_exists_cesaro` 1556, copy-ready `aa0079e1` 1635), building on R5's `compact_simplex_approx_fixedpoint` (posted 620) | posts, nodes |
| 593 → 990 | copy-ready source requests and UUID hunting | `fc328033`, `4d4d6d44`, `10f4f403` |
| 931 → 1484 | R1 assembles everything except existence (`geometric_given_stationary`, 13.6 KB, no sorry) | post `f5430dbc` |
| 1484 → 1635 | R1 waits on stationary existence; R2, R3 and R4 peer-wait on R1 | peer_wait events |
| 1683 → 1747 | R1 reads `aa0079e1` and `d3a4c180`, compiles `StationaryFromPeer.lean` at 1733, concatenates | R1 session `d4d8b371` |
| 1775.3 | `submit_for_verification` | receipt `3431b5b6` |
| 1802.5 | verified (kernel_checked); other roots superseded or completed at 1803–1810 | verification.verified |

- Critical-chain work: R5 79→620, R6 518→1635, R1 1635→1776, then the verifier. That is about
  30 agent-min of the 204 agent-min spent (15%). Everything else was parallel work: lemmas that
  fed the proof were finished by t=1143, and R1's geometric assembly by 1484.
- Of that parallel work, $56.46 of root spend came after each root's last contribution (F1).
- Within the long pole, R6 spent 47% of its turn time on society actions. The unfaithful rework
  took 5 of its turns (about 100 s). Model latency was throttled: median 6.5 s per turn in S-r2
  against 3.0–4.9 s in the other arms, p90 24.5 s against 8.1–15.1 s. That throttling is a
  known issue.
- **Route lock-in (interpretation, with evidence).**
  - 7 of 8 independent runs (I-01…I-05, I-07, I-08) proved existence with Mathlib's Banach
    fixed point (`ContractingWith`/`efixedPoint` in their final sources). No one-root run used
    Cesàro averages.
  - The society found the Banach tool at t=136, then allocated existence to a Cesàro/compactness
    route and kept it for 1,500 s. R5 at t=459: "a possible existence route independent of
    Doeblin Banach contraction"; R6 at t=1648: "Assembler can skip proving abstract Banach
    contraction fixedpoint altogether".
  - Early partition into independent pieces seems to have discouraged the cross-piece route
    (Doeblin contraction ⇒ existence) that lone agents take naturally. From about t=1000
    onward, 4 roots had nothing left to do, and none tried an alternative route on the one open
    piece.
- **Pilot contrast** (3 roots, Doeblin target). R1 submitted at t=363 using R3's
  `stationary_exists_of_geometric_steps` (post at t=233) and its own recruit's lemmas (sent by
  message). The time to proof was 6.5 min at $22.75, against 8.0 min at $10.54 for one root
  (calibration-doeblin-r2): little speedup at 2.2× the cost.

### F5. Society vs one-root runs

- **What the society did that one-root runs did not:**
  - decomposition without a planner in about 2 minutes;
  - 6-way parallel lemma proving (11 lemmas compiled by t=460);
  - an accepted proof assembled from all 6 roots.
- **What one-root runs did that the society did not:** each recruited a helper (librarian or
  formalizer) in its own lab, coordinated by direct messages, and picked the shortest global
  route. Root plus recruit reached a proof in 11.9–17.7 min for $18.60–49.49.
- **What the society cost:**
  - $155 (4.3× the I median);
  - 2× the wall time;
  - 53% of root time and 35% of root input tokens on coordination;
  - 34 referee tasks, 646 pushed items, 11 ID-hunting posts and 7 dead peer waits.
- **Where coordination helped:**
  - the goal-thread broadcast in the first 2 minutes (division of labour);
  - finding posts that carried full Lean code (the reuse channel);
  - the formally_stated filter, used once by the assembler.
- **Where it was pure overhead:**
  - referee reviews (no gating, mostly of compiled lemmas);
  - check-in update posts (44; 6 read);
  - own-post echoes (20% of pushed items);
  - platform status posts;
  - goal-claim renewals;
  - peer waits that could not wake;
  - UUID hunting;
  - roots idling at full burn.

### F6. Scaling

Per-agent rates measured in S-r2 are held constant for a 30-minute run. These are estimates,
not measurements.

| Mechanism | Order | n = 6 (measured) | n = 60 | n = 600 |
|---|---|---|---|---|
| Goal-thread push: items per agent per minute | O(n) per agent, O(n²) total | 3.6 | ~36, at the ~44/min delivery ceiling (10 items × ~4.4 boundaries/min) | ~360: backlog grows without bound |
| Pushed-update context rent | O(n²) | 9.2M tokens ($23) | ~920M ($2,300 at list price); updates are ~60% of a 184k context by the end | infeasible |
| Own-post echo | O(n) waste | 20% of pushed items | same share | same share |
| Platform status posts to subscribers | O(nodes × subscribers) | 34 items | ~O(100×) | — |
| Referee tasks (agent-requested per node and scope) | O(n) tasks, shares the task cap and slot pool | 34 (cap) / ~64 uncapped | ~640; ~16 concurrent slots; cap and queue starvation | ~6,400; ~160 slots |
| Claim renewals | O(n × activity) writes | 139 | ~1,400 | ~14,000 |
| Peer wait across labs | O(1) each, 100% wasted | 7/7 timeouts | all timeouts | all timeouts |
| Single assembler | O(lemmas), serial, one context | 16 lemmas, 14 min of assembler time, final file 23.6 KB | lemma count × size exceeds `lean_check`'s 30,000-byte source bound (`MAX_SOURCE`) | — |
| Pull reads (`commons_read`) | O(n) per agent if everyone reads everyone | 0.7 per root-minute | grows with frontier size | — |

## 3. What worked well

1. **Division of labour emerged in 72–120 s** with no scaffolding beyond the shared goal thread
   (posts `5779e013`, `9c892f7a`, `038c818c`). Duplication stayed low until late in the run.
2. **Real cross-agent lemma reuse.** The accepted proof is a verbatim assembly from all 6 roots
   (71% of its characters written by others). This meets the S1 success signal ("accepted proof
   reuses at least one lemma from another branch") many times over, but the harness metric
   (`cross_branch_dependencies = 1`) missed it.
3. **The kernel as sole arbiter holds.** Unreviewed critical-path lemmas (`f0c40067`,
   `cb075c8e`) were accepted, because only the independent verifier decides.
4. **Referees are cheap and honest.** A median of $0.23 and 46 s, and the one negative verdict
   was correct, with a concrete counterexample.
5. **Robust execution.** No S-r2 task failed after the 429 fix. Continuation handoffs restored
   in 1–5 s and reset context from 121–144k to ~26k tokens.

## 4. Bottlenecks ranked by estimated cost (S-r2)

1. **Roots at full burn after their contribution: $56.46** (36% of the arm). Causes: the long
   pole, a single assembler, and no idle or yield policy.
2. **Society context rent: 35% of root input**, 20.2M tokens, about $51 at list price. About
   $26 of that is excess over the one-root norm. Pushed updates alone are $23, of which 85% came
   through the goal thread, 20% were own echoes and 27% were check-in updates.
3. **Long-pole route lock-in** (existence via Cesàro and compactness, t=79–1635): about 5–10
   wall-minutes. At 6 roots × $0.83/min that is $25–50 (interpretation).
4. **Cross-workspace transfer by copy and paste, and ID hunting:** 56 transfer posts, 11
   ID-hunting posts, 5 NOT_FOUND, and 14 min of assembler time (t=931–1776), 2.4 min of it on
   the critical path.
5. **Referees:** $8.63, 27.5 agent-min, 34 of 40 task slots, 2,230 s of queueing, 70 posts
   (referee and platform), and 5 turns of critical-path rework for an informal-text nit.
6. **Throttled turns** (known): median model latency 1.7× the one-root arms.
7. **Dead peer waits:** 698 s idle across 7 waits (cheap in dollars, zero value).
8. **Broken local-compile recording** (`/tmp` read-only): the machine signal that could replace
   informal review never appeared.

## 5. Recommended changes (ranked by impact / effort)

| # | Change | Removes | Impact | Effort |
|---|---|---|---|---|
| 1 | **Fix the statement-check runtime directory**: `DAEMON_RUNTIME_DIR=/tmp/physharness` fails on the read-only local_docker rootfs. Use a workspace-local directory or a writable tmpfs, and add a regression test that runs the statement check in the real image. | 31/31 unrecorded compiles; the ladder never shows "compiles_locally" | High: enables item 2 and a trustworthy frontier | S |
| 2 | **Stop suggesting referees, and trigger review only where it adds information.** Drop "Get a referee" and the referee norm from `society_prompt.py`. Platform-trigger a review only for a node that (a) is used by another branch and (b) has no recorded local compile. Put referee tasks outside `max_total_tasks` and in their own small slot pool, or at lower reasoning effort. | 34 tasks, $8.6, 70 posts, 2,230 s queued, critical-path rework; the O(n) referee load becomes O(consumed-but-uncompiled nodes) | High | S |
| 3 | **Shared, importable lemma store.** On a node-bound complete `lean_check`, attach the source as the node's artifact. Add `commons_fetch(node_id)`, which writes it into the workspace as `Commons/<lean_name>.lean` (or builds a topologically ordered bundle), so assembly is an `import`, not a transcription. Accept unique 8-hex ID prefixes everywhere, and index `lean_name` in `commons_query`. | 56 copy-ready posts, 11 ID-hunting posts, NOT_FOUND errors, most of the 14-min manual assembly; the 30 KB single-file ceiling | High | M |
| 4 | **Relevance-routed push instead of goal-thread broadcast.** Never echo a reader's own posts. Do not push check-in updates or platform status posts (keep them queryable). Push a post only if it cites or relates to a node the reader authored, claims or depends on, or is a finding with attached compiled code. Replace the check-in note with a private notebook write. | 16% of root input tokens (~$23); the O(n²) term | High at scale | S–M |
| 5 | **Event-based waits.** `wait(for=peer)` wakes on the peer's next post, claim or node-status event, and `wait(for=node, status=…)` wakes on a frontier change. A root with no open claimed work waits on the frontier at zero token cost instead of polling or posting status. | 7/7 dead waits; much of the $56 of idle burn | High | S |
| 6 | **Long-pole visibility.** The frontier ranks "last open dependency of the goal" with its claimant count. Idle roots see it and may start an alternative-route attempt; this is data, not an instruction. | route lock-in; idle roots | Medium | S |
| 7 | **Node-addressed messages across labs**: a message to a node's author or claimant, rate-limited per sender. Targeted requests replace broadcast questions ("please post source for X"). | broadcast Q&A on the goal thread | Medium | S |
| 8 | **Reuse metric by provenance.** Match accepted-proof declarations to posted or stored sources (`society_metrics.py`). S-r2: 16 of 22 declarations and 71% of characters were cross-branch, against the reported `cross_branch_dependencies = 1`. | an under-reported success signal | Medium (evaluation correctness) | S |
| 9 | **Drop automatic goal-claim renewals**, and let a claim on the goal carry no meaning. | 89 of 139 renewal writes | Low | S |

Minimal-scaffolding reading: items 2, 4 and 9 remove scaffolding (prompt nudges, default
broadcasts, ceremonial claims). Items 1, 3, 5 and 7 add substrate (correct compile recording,
shared imports, event wakeups, addressable messages) rather than rules. That trade matches the
long-term aim.

## 6. Scripts and evidence

The scripts are read-only and live under `<repo>/.superpowers/live-run/audit/scripts/`.

| Script | Purpose |
|---|---|
| `society_common.py` | DB, export and checkpoint loaders |
| `extract_calls.py` | every function call, with arguments and output, from native checkpoints; private cache in `cache/<arm>-calls.json` |
| `task_economy.py` | per-task role, time, tokens and cost; `--rows` prints per-task rows |
| `commons_nodes.py` | node lifecycle, claims, edges, citations, reads and reviews |
| `referee_value.py` | whether a reviewed lemma was already compiled; queue and latency |
| `discussion.py` | posts, deliveries, reads and signal share |
| `context_rent2.py` | input-token rent by category (`context_rent.py` is the earlier tool-only version) |
| `turn_latency.py`, `turn_time_split.py` | per-turn latency; society vs math share of time |
| `arm_table.py` | the cross-arm table |

Key ids:

| Item | Id |
|---|---|
| Final proof artifact | `b7e1e51b-6231-4767-a6e0-bb9f77c3f672` |
| Receipt | `3431b5b6-c470-4e35-a380-85695015514c` |
| Assembler session | `d4d8b371-4030-4ee4-a7f8-bbb6d4d5391a` |
| Stationary-existence post | `aa0079e1-4a8c-41b0-93a8-30dfbc428354` |
| Unfaithful review | `161c3a50-57e6-43be-a74d-d0683fa8328a` |
| Task-cap rejection | R6, node `f0c40067`, t=1312 |
