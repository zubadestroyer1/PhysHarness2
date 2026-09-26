# S1 audit: how the proofs were found (research-process quality)

Analyst dimension: the path to each accepted proof, dead ends and waste, variation across the
independent runs, the society, role usefulness, and what this implies for a free-forming
institution on harder problems.

## Method and definitions

- **Accepted proof.** The candidate file that each arm submitted. It is the arm's only submission, and every one was accepted. It was extracted from the arm export by `candidate_sha256`, and the 13 files are in `scripts/out/proofs/<arm>.lean`.
- **Timeline.** Each arm's tool calls were joined to the full call arguments, which gives one line per call (`scripts/out/proofpath/<arm>_timeline.txt`).
  - Times are minutes after experiment creation (t0).
  - `results.json`'s "time to proof" starts 0.2–1.7 min later, at the first root task.
- **Provenance.** Each declaration in the accepted proof was traced to:
  - its *originator*: the first non-referee session whose authored Lean text declares that name;
  - its *first successful compile*: a `lean_check` that is ok with no `sorry`, or an exit-0 `lean` run on a file that holds it;
  - its *near-final author*: the first text that is ≥95% similar to the final block.

  The sources scanned for authored Lean are `lean_check` sources, `write_file`, shell heredocs and python edits, and messages.
- **Call labels.** There is at most one tool call per turn, so a turn's tokens follow its call.
  - `path`: authored Lean, or a compile or edit of a file, whose declarations include a name in the final proof.
  - `dead-end`: authored Lean that declares only names absent from the final proof.
  - `probe`: Lean with no declarations, such as `#check` files and API tests.
  - `search`: `search_library`, `read_source`, and shell `rg`/`sed`/`ls`.
  - `coordination`: commons, messages, inbox, wait, notebook, `read_artifact`/`read_file`, recruit.
  - `review` and `submit`.

  Declarations that were renamed or re-typed at assembly count as dead ends under their old name. `dead-end` is therefore an upper bound, and `path` includes the failed compile iterations on path files.
- **Evidence ids.** `arm:session8/tTurn@minutes`.
- **Scripts** (read-only, in `scripts/`):
  - `proofpath_timeline.py`, `proofpath_analyze.py`: provenance, labels and `first_ok`;
  - `proofpath_leanfail.py`: every compile attempt and its first error class;
  - `proofpath_time.py`: worker wall-time split;
  - `proofpath_idle.py`: spend after a task's last contribution.

  Outputs are in `scripts/out/proofpath/` (`analysis.json`, `leanfail.json`, `idle.json`).

## Top findings

1. **All 11 aperiodic proofs follow one skeleton. The only real choice point was how to prove that a stationary distribution exists, and it set the critical path.** The skeleton:
   - the Frobenius coin theorem gives a strictly positive power `P^N`;
   - a one-column Doeblin minorization gives an ℓ¹ contraction on zero-mass vectors;
   - the block decay `q^⌊t/N⌋` is converted to a per-step rate;
   - total variation over a set is bounded by the ℓ¹ distance.

   Existence was proved five different ways. The existence lemma first compiled at 2.0–2.9 min with linear algebra (I-06), at 5.8–10.5 min with Banach on the ℓ¹ simplex (7 runs), and at 25.7 min with Cesàro plus compactness (S-r2). The Cesàro route also stalled the calibration run for about 4 minutes before it was abandoned.
2. **The society divided the labour; it did not diversify the method.** The 6 "Independent approach" roots split one strategy into components within 1.3 minutes. The final proof contains code that originated in all 6 roots, so reuse was real. But:
   - the roots' "avoid overlap" norm put existence on the Cesàro route;
   - integration was serial, one assembler transcribing peers' code from commons posts (15.5→29.6 min);
   - 46% of root spend ($67 of $147) came after each non-assembler root's last contribution to the accepted proof.
3. **Cost tracks the number of live sessions × minutes. Speed does not.** Five of the 8 independent runs gave the recruit a broad "librarian" brief, and it became a second full prover for most of the run, at 47–51% of run cost:
   - it duplicated 1–3 components;
   - its sources reached the assembler only after late discovery that branch workspaces are isolated (2.3–11.4 min in).

   Across the 9 one-root runs, corr(cost, recruit lifetime) = 0.82. The fastest and cheapest run (I-06, 11.9 min, $18.60) used a narrow recruit that returned in 3 min for $2.95.
4. **Lean friction and repeated rediscovery are about a quarter to a third of worker effort.**
   - **Compiles:** of 844 compile attempts, 327 failed (39%). 120 of the failures were unknown or renamed Mathlib names; the same wrong names recur across arms (`Matrix.dotProduct` 17×, `Matrix.vecMul_mul` 14×, `Matrix.vecMul_pow` 9×, `PiLp.toLp`/`ofLp` 9×). 34 more were `lake` not on PATH.
   - **Worker time** (the 11 aperiodic arms): 28% went to compiles (11% to failed ones) and 16% to library and API reading.
   - **Rediscovery:** every aperiodic run found the same coin theorem, searched for Perron–Frobenius and Brouwer, and failed to find them.
5. **No arm designed the proof top-down. Interfaces broke late, and review never changed the mathematics.**
   - In all 13 arms the target theorem was first written 0.1–2.6 min before submission.
   - The case where the positive power has exponent `N = 0` (a one-state chain) was discussed in 8 of the 11 aperiodic arms. Some caught it early; in I-01, I-03 and S-r2 it was fixed at or after 11.8 min.
   - Referees cost 0.4–5.6% of spend and changed no Lean artifact. The single negative verdict (1 of 34) caught an informal overclaim. In the independent runs, referee sessions mostly ran only after the proof was nearly assembled.

## 1. The mathematical route

Every aperiodic proof uses `Nat.exists_add_mul_eq_of_gcd_dvd_of_mul_pred_le` (Mathlib, `Algebra/Order/Ring/Int.lean`) for the coprime step. All 13 arms searched the library for Perron–Frobenius (`search_library` or `rg`), 12 of 13 also searched for a Brouwer or Schauder fixed point, none found either, and all took the elementary Doeblin route. That route was library-driven:

> I-04:fc42f09e/t9@0.80: "Mathlib source search: no finite Markov chain convergence/aperiodic/irreducibility/Perron–Frobenius theorem (rg on Mathlib)"

No arm used spectral theory or coupling. Across arms the variation lies only in the stationary-existence method and the rate conversion:

| arm | stationary existence | per-step rate |
|---|---|---|
| calibration-aperiodic | Cesàro route attempted (7.6–11.4 min) and abandoned; a geometric Cauchy sequence of iterates in its place (`cauchySeq_of_le_geometric`) | `rpow` root `q^(1/N)` |
| S-r2 | Cesàro averages plus compactness of `stdSimplex` (`tendsto_subseq`) | `rpow` root |
| I-01, I-02, I-03, I-04, I-07, I-08 | Banach fixed point (`ContractingWith`) on the ℓ¹ simplex as a `PiLp 1` subtype | `rpow` in I-01, I-02 and I-08; Bernoulli-type in I-03, I-04 and I-07 |
| I-05 | Banach on an affine map `x ↦ xR + ε e_c` (substochastic remainder) | Bernoulli-type |
| I-06 | linear algebra: `det(P−I)=0`, then a signed left kernel vector, then `|v|` is stationary | `rpow` |
| single | the continuous defect `∑|xQ−x|` has a minimum on the compact simplex, and contraction forces it to be 0 | `rpow` |

Two proofs are examples of good mathematics that shortened the path:

> I-06:f76088de/t29@2.10 (node statement): "Proof: P·1=1 implies det(P−I)=0; transpose shares determinant and hence admits a nonzero left kernel vector."

> single:c67ecebd/t89@9.91: "Potential simpler stationary-existence than Banach: minimize continuous displacement d(x)=∑j |(xᵥ*Q)j−x j| on compact stdSimplex"

In S-r2, 08bdcfc9 got uniqueness from the convergence bound itself (`uniqueness_of_geometric_bound`, compiled at 5.3 min). This removes a separate uniqueness argument.

## 2. Per-arm path

Component columns give the minute of the first successful compile, and who compiled it: `R` is a root, `r` a recruit, and an apostrophe marks a successor session. "Written by" is the share of the final proof's characters that each session originated.

| arm | verified (min) / cost | final proof written by | primitive power | Doeblin contraction | existence (route) | rate | target first written → submitted | path / dead-end, % turns (% cost) |
|---|---|---|---|---|---|---|---|---|
| calib-doeblin-r2 | 7.98 / $10.54 | root 54%, recruit 46% | n/a | 4.11 r | 4.16 R (Cauchy) | 5.70 R | 7.3 → 7.58 | 38 (41) / 4 (5) |
| calib-aperiodic | 17.85 / $34.61 | root lineage 88%, recruit 12% | 2.45 r | 3.79 R | Cesàro abandoned at 11.41; 14.44 R' (Cauchy) | 10.21 R | 16.6 → 17.43 | 13 (18) / 6 (7) |
| pilot-doeblin | 6.46 / $22.75 | root1 63%, recruit 26%, root3 10%, root2 0% | n/a | 1.85 r | 3.33 root3, cross-lab | 2.11 R1 | 5.48 → 6.05 | 22 (29) / 10 (8) |
| **S-r2** | 30.04 / $155.41 | originated by all 6 roots: 29/27/17/11/11/6% | 7.04 a84c | 2.56 2ce4 | 25.70 08bd (Cesàro); approximate fixed point by 5f72 at 5.16 | 3.03 f128 (uniform version 13.17) | 27.2 → 29.59 (assembly from 15.5) | 9 (12) / 5 (6) |
| I-01 | 17.68 / $49.49 | recruit 77% (assembler), root 23% | 2.33 R; N>0 fix 13.03 | 4.23 r (root duplicate 4.87) | 10.53 r (Banach) | 8.91 R | 17.17 → 17.26 | 25 (31) / 6 (6) |
| I-02 | 13.84 / $33.58 | root 63%, recruit 22%, 14% via shell | 2.12 r | 3.16 R | ≈8.96 R (Banach) | 5.69 r | 11.8 → 13.39 | 21 (27) / 5 (7) |
| I-03 | 14.40 / $34.53 | root 63%, recruit 37% | 2.51 r; N>0 fix 12.8 | 3.2 R | 6.61 R (Banach) | 10.57 R | 13.8 → 13.94 | 26 (35) / 5 (5) |
| I-04 | 14.03 / $35.06 | recruit 88% (assembler), root 12% | 2.58 r (root duplicate 2.44) | 3.58 r | 6.77 r (Banach) | 8.93 R, re-typed by r at 12.35 | 13.37 → 13.56 | 20 (26) / 4 (4) |
| I-05 | 14.78 / $38.92 | root 66%, recruit 34% | 2.12 / 4.54 R | 2.38 r | 5.79–7.23 r (affine Banach) | 8.32 R | 13.9 → 14.33 | 35 (45) / 4 (4) |
| **I-06** | **11.92 / $18.60** | root 88%, recruit 12% | 1.82 r | 4.22 R | **2.02–2.93 R (linear algebra)** | 7.69 R | 11.2 → 11.42 | 25 (37) / 3 (2) |
| I-07 | 17.27 / $39.37 | root 81%, recruit 15% | 1.69 R | 4.61 r | 8.20 R (Banach) | 10.54 R | 14.95 → 16.83 | 32 (44) / 0 (0) |
| I-08 | 13.80 / $36.99 | root 79%, recruit session 1 17% | 1.55 r | 3.25 R | ≈8.0 R (Banach) | ≈10.2 R | 11.5 → 13.36 | 21 (29) / 12 (13) |
| single | 14.14 / $31.97 | root 84%, recruit 2 14% | 3.51 R (N>0 at 6.78) | 5.36 R | 10.77 R (minimizer); recruit's Banach version 10.25 was a duplicate | 9.57 R | 11.1 → 13.73 | 19 (28) / 7 (11) |

**Milestones.**

- **First plan.** In every arm the first root plan post appeared at 0.9–1.5 min (calibration-doeblin-r2 at 2.95 min), after a library search. It named the primitive-power-then-Doeblin route. Example: I-06:f76088de/t13@0.89, "Current subgoal: derive stationary distribution and geometric convergence from a strictly positive matrix power."
- **No early skeleton.** No arm compiled a `sorry` skeleton of the target early. I-07 and I-08 used `sorry` stubs only inside the final assembly file, at 11.5–15.9 min.
- **Every first submission was accepted (13/13).** Before submitting, agents checked `#print axioms` and the absence of `sorry` locally, for example `ProofAxioms.lean` in I-06 and `FullAxioms.lean` in I-07.

## 3. Where the turns went

Shares of turns, with cost in parentheses, in the 8 independent runs combined (1,650 turns):

| label | share of turns (cost) |
|---|---|
| on path | 26% (34%) |
| dead end | 5% (5%) |
| probes | 7% (7%) |
| library and API search | 25% (17%) |
| coordination | 32% (32%) |
| submit and review | 2% (2%) |

In S-r2 the on-path share was 9% of turns (12% of cost) and coordination was 51% (59%):

- commons posts: 16.9% of turns;
- commons reads: 16.5%;
- node bookkeeping (create, set_lean_statement, request_review, link): 11.6%.

**Worker wall time** (model latency plus tool time, root and recruit sessions) splits as follows:

- **Lean compiles:** 28%, of which failed compiles are 11%. By arm: I-06 42% (23% failed), I-05 40%, I-03 37%.
- **Search and reading:** 16%. The single arm reached 24%.

## 4. Dead ends, waste, rediscovery, fighting Lean

- **Compiled but unused lemmas.**

  | arm | compiled but unused | declarations in final proof |
  |---|---|---|
  | S-r2 | 22 | 23 |
  | pilot | 14 | 17 |
  | I-08 | 11 | 21 |
  | I-01 | 8 | 22 |
  | I-03 | 7 | 23 |
  | I-05 | 6 | 24 |
  | I-02 | 4 | 11 |
  | I-06 | 4 | 15 |
  | I-04 | 3 | 27 |
  | I-07 | 0 | 18 |

  Some of these are re-typed versions of lemmas the final proof uses (for example I-06's recruit `pos_*`), so the counts are an upper bound.
- **The Cesàro trap** (seen twice).
  - **calibration-aperiodic.** At 7.56 the root committed to a "finite-simplex Cesàro stationary law", and gave up at 11.41 (95c806f9/t93): "No formal proof completed for finite-state stationary distribution existence; exact Cesàro strategy and available compactness lemma identified." Its native successor switched to a geometric Cauchy sequence and compiled existence at 14.44 (a8e20048/t15). The detour cost about 4–7 min on the critical path.
  - **S-r2.** The approach was chosen explicitly to avoid overlap:

    > S-r2:5f72e177/t15@1.31: "Avoid overlap with Doeblin branch: isolate formal stationary existence by Cesàro averages and compactness."

    > S-r2:5f72e177/t59@7.65 (body): "Limit of Cesàro averages is a possible existence route independent of Doeblin Banach contraction."

    At the bottleneck (the Cesàro residual limit), three roots worked concurrently: 08bdcfc9 compiled it at 20.99, 2ce4dce9's `inv_mul_bounded_tendsto_zero` ran from 14.0 to 21.8 and went unused, and 5f72e177's denominator limit at 20.2 went unused. The whole existence theorem compiled at 25.70:

    > S-r2:08bdcfc9/t113@25.93: "MAJOR: full `stationary_exists_cesaro` theorem locally Lean compiles with all dependencies explicitly proved, zero sorry, not conditional!"

    By contrast, a Banach existence lemma compiled at 5.8–10.5 min in the I-runs.
- **Duplicated components within a lab.**
  - I-01 duplicated the Doeblin contraction, the primitive power and the global minorant. I-01:5e3f035f/t45@4.42: "I was separately tackling equivalent column-minorization (node f15f8a09...) but will defer to your completed stronger statement." At 15.12 the recruit wrote: "I independently Lean-compiled global minorant via even simpler ε = (global minimum m of Q entries)/2".
  - I-04 duplicated the primitive power and stationary positivity.
  - I-03 duplicated the fixed point, positivity and nonexpansiveness.
  - single duplicated existence, with Banach in the recruit and the minimizer in the root.
- **Requested help that went unused.** In I-08 the recruit kept working after returning its result. I-08:a8b9911d/t10@4.73: "I received your request after returning delegated task; my slot is still active, so will develop scalar block-to-geometric lemma". Its two later sessions ($12.27) produced 11 compiled helpers, and none reached the final proof. The root proved them itself before the answers arrived.
- **Successors redid their own lineage's work.** In S-r2, portable successor 3d151e45 re-proved `positive_column_minorization` (first compiled by its predecessor at 3.55) and `stationary_pos_irred` (compiled by d4d8b371 at 2.47) at 24.9–27.0 min.
- **Interface mismatch: the `N = 0` case.** The case was discussed in 8 of 11 aperiodic arms. It was fixed late in I-01 (11.9→13.0), I-03 (11.8→12.8) and S-r2 (21.8–22.2).

  > I-03:3f701001/t86@11.83: "Critical issue: your `aux_eventual_positive` returns N possibly 0 (one-state chain with a=0,b=1, all d=0). Numeric bound assumes N>0."
- **Repeated library rediscovery.** Every aperiodic run and every S-r2 root re-derived the same library map:
  - Matrix: `rowStochastic` submonoid, `IsIrreducible`/`IsPrimitive` definitions only.
  - Fixed points and limits: `ContractingWith`, `stdSimplex` closed and compact, `PiLp 1` distance = sum of absolute values.
  - Number theory: the coin theorem.
  - Absent: Perron–Frobenius, Brouwer.

  Across all 13 arms, 19–34% of turns carry the search label; in the I-runs it is 25% of turns and 17% of cost.
- **Fighting Lean.** The failure classes and recurring names are in finding 4. Probe files show the pattern: I-07's root wrote 9 `Check*.lean` probe files. Environment rediscovery repeated too: 34 `lake` PATH failures, and every lab found `/opt/lean/bin` again.

## 5. Why the independent runs vary (11.9–17.7 min; $18.60–$49.49)

- **Cost is live sessions × time × context.**
  - corr(cost, time-to-proof) = 0.88.
  - corr(cost, recruit lifetime) = 0.82.
  - In five runs the recruit had a broad library brief and lived 11.4–17.3 min at 47–51% of cost (I-01 to I-05). This bought no speed: those five runs took 13.6–17.4 min, against 11.7 (I-06), 17.0 (I-07) and 13.9 (single) with short-lived recruits.
- **Fastest and cheapest, I-06** (verified 11.92, $18.60). Four things set it apart:
  - **Narrow recruit brief.** I-06:f76088de/t3: "Do not attempt full target, prioritize reusable proof or precise blocker." The recruit compiled the primitive lemma at 1.82 and returned at 3.23 for $2.95.
  - **Shortest existence route.** The root found it early (linear algebra, 2.0–2.9 min), the earliest of any run.
  - **Small context.** The root worked alone, with the smallest median input (45k tokens per turn, against 51–84k elsewhere).
  - **Little integration.** One artifact read. The root re-typed the recruit's lemma at 10.4 rather than waiting for a transfer.

  It was not cleaner Lean: 47% of its compiles failed, 10 of them on unknown names.
- **Slowest, I-01** (17.68, $49.49). Two full-length sessions (110 and 111 turns, about 9.5M input tokens each) worked in parallel and duplicated three components. The root only found out that workspaces were not shared at 11.35:

  > I-01:5e3f035f/t84@11.35: "Workspaces not shared: /work/scratch/Banach.lean absent here. Please send ENTIRE Banach.lean source via message (20k cap)"

  The `N>0` fix came at 13.0. Assembly then moved to the recruit at 15.3–15.6 (I-01:4118b2a5/t99: "YES: I will assemble and submit target independently from my branch"), and the sources had to be re-sent.
- **Second slowest, I-07** (17.27). The recruit left at 7.95. The root then did the rate proof, four glue lemmas and assembly in sequence. Its last component was ready at 10.54 but it submitted only at 16.83: the glue had to be written during assembly, and assembly took 12 `lake` iterations.
- **Transfer latency.** Isolation was found by trial, 2.3–11.4 min into each run. The agents built transfer workarounds: messages with code (up to 11 per run), multi-part commons posts, a `run_computation` whose stdout carried the file into an artifact (I-01, I-04), and gzip plus base64 (I-04):

  > I-04:fc42f09e/t82@11.00: "Cross-VM SOURCE TRANSFER via artifact: `read_artifact(...)` … yields full JSON computation record, whose `stdout` field contains exactly complete 14,908-byte … banach"

## 6. The society (S-r2) and the pilot (pilot-doeblin)

- **Diversity was not exercised.** In the first 1.2 min, four of the six roots started on the same primitive lemma (nodes at 1.04–1.16). By 1.31 they had deconflicted by posts into components:

  > S-r2:2ce4dce9/t14@1.20: "Switching to the complementary Doeblin contraction since another branch is studying coprime→primitivity."

  The components were primitive (a84c), Doeblin and minorization (2ce4), existence (5f72, then 08bd), positivity, ℓ¹ and assembly (d4d8), scalar rate (f128), and uniqueness and the Cesàro telescope (08bd). No root tried another overall strategy. The target and the Mathlib library left one route, and the society spent its diversity on *which component each root owns*.
- **Building on each other's work was real.** The accepted proof contains code that originated in all six roots: d4d8 29%, 08bd 27%, f128 17%, a84c 11%, 2ce4 11%, 5f72 6%. The ideas that shortened the path were the exact coin theorem, the monotonicity-plus-block uniform geometric lemma and uniqueness from the geometric bound.
- **Parallel production worked.** Under the roughly 1.5× per-turn throttle (median turn latency 6.1 s, against 3.1–4.6 s in the I-runs), five of the six components were compiled by 7.04 min. That is as fast as or faster than any root-plus-recruit pair.
- **What lost the time.**
  1. The existence route. Everything except existence was done by 14.04 min; existence compiled at 25.70.
  2. Serial, transcription-based integration. The assembler (d4d8) started at 15.5. Over 42 turns it did 17 commons reads of "copy-ready" posts and re-typed about 15 KB of peers' Lean into `*FromPeer.lean` files. It hit ID friction on the way:

     > S-r2:d4d8b371/t72@11.58: "Primitive source post b2e26ba8 is an abbreviated ID, not retrievable by commons_read; please share full post UUID (or post on root)."

     It integrated existence 3.7 min after that became available, and submitted at 29.59.
- **Idle cost.** Non-assembler roots spent $67.37, 46% of root spend, after their last contribution to the accepted proof: 2ce4 $18.91 after 3.5 min, a84c $16.23 after 7.0, 5f72 $15.59 after 15.7, f128 $11.48 after 15.1. The time went to re-posting "copy-ready" code, offering help, polling (`wait`, `inbox`, `sleep 15`) and re-proving. The final proof depended on other branches, but every branch held a single piece of one serial pipeline.
- **The pilot shows the same division of labour** (3 roots, Doeblin target):
  - root 3 proved stationary existence (compiled 3.33), which root 1 used across labs;
  - the recruit proved the contraction (1.85);
  - root 2 duplicated the contraction and uniqueness, contributed 0% and cost $4.61.

  pilot-doeblin > 7adaf7cd/t30@4.14: "Cross-lab stationary worker 8031ae5a just posted COMPLETE standalone Lean proof stationary_exists_of_geometric_steps in commons post"

  Against calibration-doeblin-r2 (1 root plus recruit), the working time was about the same (5.5 against 5.9 min from session start) at 2.2× the cost.

## 7. Role usefulness

- **Recruits.**
  - **Narrow formalizer or explorer briefs** (I-06, I-08 session 1, calibration-aperiodic, calibration-doeblin-r2) delivered a single needed lemma in 1.5–5 min for $2.4–5.1. That lemma was 12–46% of the final proof.
  - **Broad librarian briefs** (I-01 to I-05, I-07, the single arm's first recruit) finished their stated library work in 1–2.5 min. None found a ready-made convergence theorem. They then either:
    - became a second prover and sometimes the assembler (I-04 recruit 88%, I-01 77%); or
    - returned with 0% contribution (single's first recruit, $2.79).

    Their library findings were the same in every run.
- **Referees.**
  - **Cost:** 0.4–5.6% of spend.
  - **Verdicts:** 33 of 34 in S-r2 were sound or faithful. Their added mathematical content was non-vacuity witnesses (`Fin 1` models, `aesop` does not derive `False`) and informal re-proofs.
  - **The one negative verdict** caught a real overclaim in an informal corollary:

    > S-r2 review (unfaithful): "the informal statement also claims this produces a bounded-defect approximate fixed point after division by n, which is false under the universal arbitrary-matrix quantifier"

    The author accepted it (08bdcfc9/t79@13.94). The Lean identity was unaffected.
  - **Timing:** in I-01 to I-05 the referees ran at 11.8–16.1 min, after the proof was nearly assembled. They were queued behind the concurrency-2 slots.
  - **Effect:** no referee changed a Lean artifact or the path to the proof.

## 8. What worked well

- **Correct and self-checked.** 13 of 13 first submissions were accepted, after local axiom and `sorry` checks.
- **Library search found the key tool fast.** The exact coin theorem was found in about 1 min in every arm, so the combinatorial step was never a bottleneck.
- **Fast deconfliction.** Four S-r2 roots that started on the same lemma had re-assigned themselves within about 15–20 s using posts.
- **Useful mathematical creativity.** Linear-algebra existence (I-06), the compact-minimizer route (single), uniqueness from convergence (S-r2), and reusing a single contraction lemma for existence, uniqueness and rate (the Banach runs).
- **Agents helped each other with API names.** For example, I-02:d0793ffb at 8.66 corrected `PiLp.ofLp` to `WithLp.ofLp`.
- **Agents invented workarounds** for missing file sharing: artifact exports and multi-part posts.

## 9. Implications for a free-forming institution on harder problems (ranked)

1. **Shared compiled lemma store, with import by name, replacing transcription.**
   - Integration by re-typing was the serial bottleneck of the society (14 min, one assembler).
   - In the pairs it caused 2–4 minute transfer delays and hacks.
   - At 10–100 agents, a single assembler re-typing N contributors' code grows O(N) in turns and context.

   Minimal scaffolding: branch-published Lean modules that others can `import`, and a verifier that checks the assembled closure. Keep workspaces isolated if needed, but make reading a published file first-class.
2. **Agree on a proof architecture before splitting.** Evidence:
   - late `N>0` mismatches in 8 of 11 aperiodic arms;
   - duplicates in every pair run except I-06 and I-07;
   - S-r2 split the work by the target's conjuncts, which lost the synergy of a single contraction lemma that yields existence, uniqueness and rate.

   Minimal scaffolding: a shared target file with `sorry`-stubbed lemma signatures that always compiles. Claims attach to stubs, and assembly is continuous rather than a final step.
3. **Put diversity at genuine choice points, with time boxes and kill rules.**
   - Here the only choice point was existence. Its five methods compiled at anywhere from 2.9 to 25.7 min. Independent runs sampled that diversity for free; the society assigned it to one owner.
   - For hard problems, run two or three competing routes on the bottleneck component only, and abandon one when a rival route compiles. In calibration-aperiodic, abandoning Cesàro and switching to the Cauchy route took 3 minutes.
4. **Narrow, returning delegation.** Scope a recruit to one named lemma with its Lean signature and let it end. Idle agents should cost nothing, and polling agents should be put to sleep: S-r2 spent 46% of root spend after the roots' last contributions, and cost followed live-session minutes (r = 0.82).
5. **Persistent institutional memory for the library and the toolchain.** Remedies:
   - a per-Mathlib-pin cheat sheet: renamed APIs such as `dotProduct` and `WithLp.ofLp`, and known absences such as Perron–Frobenius and Brouwer;
   - the PATH fixed;
   - the known coin, fixed-point and simplex APIs documented.

   These would remove most of the 120 unknown-name failures, the 34 PATH failures, and much of the 16% of worker time spent searching. Every run and every S-r2 root paid this cost again.
6. **Referees on plans, not on compiled lemmas.** Once `lean_check` has passed, fidelity review of an auxiliary lemma adds little. Review is worth more on informal routes before formalization, where the Cesàro trap would have been caught, and on the final statement.

**When collaboration pays off.**

- **What the evidence shows.** Components here took one agent 1.5–8 min, and each handoff cost 1–4 min plus 3–15 min of integration. The proof graph was shallow, with about 5 components and one bottleneck, which caps any parallel speed-up at about 2×. The society's parallel component production was real, but routing and integration consumed it.
- **Expectation for harder problems (interpretation).** Collaboration should pay once components take tens of minutes, the graph is wide (10 or more components), and integration is by reference rather than transcription.

## 10. A target hard enough to separate the arms

Effort in these runs went to analytic infrastructure: simplex completeness in `PiLp 1`, `Tendsto` and limits, `rpow` for the per-step rate, and existence. It did not go to the combinatorics, which was a library hit, or to the overall idea, which the statement dictates. A separating target should need:

- a long critical path with 10 or more substantial lemmas;
- at least one costly choice point with several plausible routes;
- infrastructure absent from the pinned Mathlib;
- an exact frozen Lean statement.

Suggestions (interpretation):

- **Irreducible chains with general period `d`.** Stated with the gcd of return times rather than two coprime lengths, and asking for the cyclic-class decomposition and Cesàro convergence. Here the Cesàro limit machinery, the trap in these runs, becomes unavoidable, and the number theory needs more than the two-generator coin theorem.
- **Perron–Frobenius for irreducible nonnegative matrices.** The spectral radius is a simple positive eigenvalue with a positive eigenvector, and `P^t / ρ^t` converges to a rank-one projection in the primitive case. All 13 arms searched for Perron–Frobenius and found nothing. It needs eigenvalue and Collatz–Wielandt theory and has real route choices.
- **Spectral-gap mixing bounds for reversible chains.** For example, the ℓ² or total-variation bound through the spectral gap in the π-weighted inner product, or the Cheeger inequality. These need the spectral theorem and Rayleigh quotients, and have many components suited to parallel work.

Calibrate first with 2–3 independent runs. Aim for a success rate of 20–50% within budget, and record lemma-graph progress so that a failed arm still yields a signal.

## Caveats

- **Sample size.** There is one society run, and it was throttled about 1.5× per turn.
- **Provenance is name-based,** with a 95%-similarity check. Renamed or re-typed lemmas split credit: I-06's primitive lemma originated in the recruit and was re-typed by the root.
- **`path` includes failed iterations on path files. `dead-end` is an upper bound.**
- **Cost per label follows the context size at each turn,** so later turns weigh more.
- **Component times are the first successful compile anywhere.** The assembler may have received a component later.
