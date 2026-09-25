# S1 live run plan: research society vs single agent vs independent attempts

**Status: plan only, 2026-09-25.** Nothing in this document has run. No model call, VM,
Colima, E2B sandbox or image build has been started for it, and no live evidence exists
for the society profile. The S1 code is covered by deterministic tests only:
`tests/test_society_simulation.py` drives three agents and platform referees through the
society tools with no model. Every item marked **USER DECISION REQUIRED** or listed in
[Prerequisites and approvals](#8-prerequisites-and-approvals) needs the user before
anything is spent.

Files:
- `work/society-s1/run-plan.example.json`: the society-arm manifest skeleton for
  `phys prepare-run`. Its placeholders are labelled `USER DECISION REQUIRED`. A plan
  that still contains one fails validation, so the skeleton cannot be prepared by
  accident.
- `tools/society_metrics.py`: the metrics below, computed from one experiment export.

## 1. Question and exit evidence

PLAN §7 sets the S1 exit evidence: deterministic tests (done), then a live **8–16 agent**
run on a hard known target, compared with a single agent and with independent attempts
at matched cost. The metrics are an accepted root, less duplicated work than the last
run, and observed lemma reuse.

The question: at the same dollar ceiling, does a society sharing a commons (claims,
node threads, referees, labs) reach an independently accepted root more often, sooner or
more cheaply than one agent or than agents working alone? A single repetition per arm
gives descriptive evidence only. It does not support a causal claim.

## 2. Arms at matched budget

Every arm gets the same dollar ceiling **B** (see [the budget table](#5-budget)), the same
frozen target, masked reference, source freeze, workbench image, verifier bundle and
price table. Each arm uses a fresh project and database, so no arm can retrieve another
arm's work. The model families are the same: family A and family B.

| Arm | Experiment shape | Agents | Concurrency | Wall-clock ceiling |
|---|---|---|---|---|
| **S. Society** | One society experiment (`sharing="ideas"`, society policy as in the example). Policy `independent` with 8 model entries (4 per family) seeds 8 roots. Each root founds a lab, and recruits join labs (`lab_size_max` 6). Referees are platform-created, cross-model and isolated (ruling R18). | 8 seeded roots, up to 16 research agents, plus referee tasks | 12 (8 roots and 4 slots for referees and recruits) | W |
| **I. Independent attempts** | 8 roots (4 per family) that share nothing | 8 | 8 | B / (8 × $40) hours |
| **1. Single agent** | One root, family A | 1 | 1 | B / $40 hours, or earlier when it finishes |

Concurrency 12 in arm S leaves room for referees. With 8 busy roots at concurrency 8, a
referee would queue until a root yields, which repeats the helper queueing of the last
run.

### Design choice: tool matching (USER DECISION REQUIRED)

The S1 toolkit exists only in the society profile. That includes the persistent Lean
session with automation, `lean_sketch`, `run_computation`, brokered literature and
skills. A society policy requires `sharing="ideas"`, so there are two ways to build the
single and independent arms:

- **Design A: legacy baseline.** Arm 1 is a legacy experiment (policy `direct`,
  `sharing="none"`, one model). Arm I is one legacy experiment with policy
  `independent`, `sharing="none"` and 8 model entries. This matches the earlier pilots
  and the arm names literally, but it confounds collaboration with tools: the legacy
  63-tool profile has no Lean session, sketching, computation runner, literature or
  skills. Legacy agents can still delegate, so set `max_total_tasks` to the number of
  roots to keep each arm free of helpers.
- **Design B: tool matched (recommended).** Every arm uses the society profile. Arm 1
  is one society experiment with one root (policy `direct`, models `[A, B]`, so that
  referees can be cross-model). Arm I is **8 separate one-root society experiments**,
  4 with a family A root and 4 with family B, each with ceiling B/8. Separate experiments
  share nothing: each has its own commons. Only arm S shares a commons.

Design B has two limits:
- S1 has no switch that removes `recruit` from the society profile. In arms 1 and I, set
  the workforce admission cap (`max_total_tasks` = 1 + referee allowance) and report any
  recruit as a protocol deviation.
- `prepare-run` creates one campaign, problem and experiment per plan. Eight independent
  experiments therefore need either eight plans (eight target reviews and eight verifier
  registry entries of identical content) or an operator script that creates eight
  experiments on one reviewed problem.

In both designs, referee tasks are built-in platform checks, not collaborators. They are
paid from the arm's ceiling B.

### Operator configuration of arm S

- Prepare it from `run-plan.example.json` once every placeholder is filled.
- Before starting, call `configure_workforce(max_total_tasks=40, max_pending_tasks=20,
  synthesis_interval_posts=0)`. That allows 16 research agents plus up to 24 referee
  tasks.
- S1 cannot cap research agents separately from referee tasks. Both count toward
  `max_total_tasks`, so report the split from the export (`branches.agents`,
  `branches.referees`).
- Launch with `phys run-team <experiment> --max-tasks 40 --concurrency 12
  --timeout-seconds <W>`. `run-team` runs the preflight first. The preflight now also
  blocks benchmark mode without a readable `masked_reference` artifact
  (`MASKED_REFERENCE_REQUIRED`).
- `ResearchTeamRunner` runs:
  - the referee tasks requested by its own lineages (ruling R20);
  - the synthesis tasks it schedules (R21);
  - in society runs, any queued parentless synthesis that an earlier run left behind
    (R23).

  No live run has exercised these paths.

## 3. Target selection (USER DECISION REQUIRED)

Criteria:
1. **A known result with a masked reference.** A complete private reference proof must
   pass Comparator, Lean and Nanoda before any paid work. Its text becomes the
   `masked_reference` artifact, and its sources go on the benchmark blocklist.
2. **Harder than the Duffing-network target.** That target was accepted after 17m03s by
   2 roots plus 4 helpers. The development calibration (a single agent, see the budget)
   should not reach an accepted proof within its first hour.
3. **Natural decomposition.** The proof should split into several lemmas that different
   agents can own, so that claims, citations and reuse have room to appear.
4. **Faithful, short statement.** It has no definition holes and can be stated with
   pinned Mathlib/Physlib. It passes target review and semantic negative controls: an
   altered statement must be rejected through the same pipeline.
5. **No shortcut in the pinned libraries.** Search Mathlib `db584cd6` and Physlib
   `40584817` for the theorem or a near-exact form before freezing. Hiding useful
   library results to add difficulty is not allowed.
6. **Clean provenance.** Agents can read the problem record, so `target.source`, the
   title and the informal statement must not name or paraphrase the known-solution
   source. Keep the provenance in the operator's private notes.
7. **Skill overlap recorded.** The technique skills were written before any target was
   chosen, so none is derived from a reference. If a skill spells out the reference
   route, record it: `energy-lyapunov` already describes the xᵀPx Lyapunov-equation
   method, and `sos-certificates` describes sum-of-squares decompositions.

**Candidate targets (proposals only).** None has been elaborated, checked against the
pinned libraries or given a reference proof.

| # | Candidate | Program | Rationale (one line) |
|---|---|---|---|
| 1 | **Tsirelson's bound**: for Hermitian involutions A₀, A₁ on ℂᵐ and B₀, B₁ on ℂⁿ, every state satisfies ⟨A₀⊗(B₀+B₁) + A₁⊗(B₀−B₁)⟩ ≤ 2√2 | quantum | A known finite-dimensional operator inequality (Mathlib `Matrix`, Kronecker products, `PosSemidef`) whose proof needs a sum-of-squares operator identity and noncommutative algebra, a harder kind of step than the Duffing energy estimate. |
| 2 | **Kepler orbit equation**: for r̈ = −μ r/‖r‖³ with specific angular momentum h = r × ṙ ≠ 0, ‖r‖(1 + e cos θ) = ‖h‖²/μ, where e and θ come from the Laplace–Runge–Lenz vector | classical | Several conserved quantities and cross-product identities in ℝ³ (`HasDerivAt`, Mathlib `crossProduct`), which split naturally into lemmas: L conserved, A conserved, A·r identity. |
| 3 | **Explicit exponential stability of x′ = Ax from a Lyapunov pair**: with P ≻ 0, Q ≻ 0 and AᵀP + PA = −Q, ‖x(t)‖² ≤ (λmax(P)/λmin(P)) e^{−(λmin(Q)/λmax(P)) t} ‖x(0)‖² | classical | It extends the Duffing energy method to matrices and needs spectral bounds for positive definite matrices, but the `energy-lyapunov` skill names the route, so it is likely the easiest of the five. |
| 4 | **Exponential convergence of a finite Markov chain under Doeblin's condition** (P(i,j) ≥ δ for all i, j): ‖μPᵗ − π‖_TV ≤ (1 − nδ)ᵗ, with a unique stationary π | classical (statistical physics) | Finite sums, a total-variation contraction lemma and existence and uniqueness of π; a nonlinear-ODE-free target that tests whether the society generalizes beyond energy estimates. |
| 5 | **Gibbs variational principle (finite system)**: Σᵢ pᵢEᵢ + T Σᵢ pᵢ log pᵢ ≥ −T log Z for every distribution p, with equality exactly at the Gibbs distribution | classical (statistical physics) | Convexity (Gibbs or log-sum inequality) plus the equality case; possibly too easy if Mathlib's KL-divergence results apply directly, so it is a fallback or development rung. |

## 4. Literature mode

- **Benchmark mode (arm S, and every arm in Design B).**
  - `blocked_sources` lists the chosen target's known-solution sources: arXiv ids, DOIs,
    domains and identifiable title fragments.
  - `masked_reference_artifact_id` names a private `masked_reference` artifact holding
    the reference text. The operator uploads it before `prepare-run`, and agents cannot
    read it.
  - The broker screens search results and fetched text for overlap with the reference
    (`overlap_threshold` 0.02) and withholds flagged text. Agents see only a reason code.
    The measurements stay in a private `literature_screen` artifact.
  - A flag means text was withheld, not leaked. An arm is **contaminated** only if a
    post-run audit finds reference text in released sources, posts or the accepted
    proof. A contaminated arm is reported but excluded from the benchmark comparison.
- **Literature-assisted arm (optional, USER DECISION REQUIRED).** It is a separately
  labelled arm S with `mode="open"`: all fetches are logged and nothing is blocked. It
  measures literature help, not reasoning from scratch, and never counts as a benchmark
  result.
- In Design A, the legacy arms have no literature tools at all. That asymmetry is one
  more reason to prefer Design B.
- There is no general web search: it needs a paid search API key. S1 offers arXiv,
  OpenAlex and allowlisted fetch.

## 5. Budget

The planning figure is **$40 per busy agent-hour**, from PLAN §1. The Duffing retry cost
$49.10 for 17 minutes with at most 4 concurrent workers, about $43 per busy agent-hour at
full occupancy. Busy agent-hours include referee tasks. Arm I spends ceiling B over
B / (8 × $40) hours; arm 1 over B / $40 hours, and it usually stops earlier.

| Option | Arm S shape | Busy agent-hours per arm | Ceiling B per arm | Three arms | Development calibration | Total, one repetition | Total, two repetitions |
|---|---|---|---|---|---|---|---|
| Minimum | 8 concurrent × 1 h | 8 | $320 | $960 | $80 (2 agent-hours) | **$1,040** | $2,000 |
| Recommended | 12 concurrent × 1.5 h | 18 | $720 | $2,160 | $160 (4 agent-hours) | **$2,320** | $4,480 |
| Upper (16 agents) | 16 concurrent × 2 h | 32 | $1,280 | $3,840 | $160 | **$4,000** | $7,840 |

- The optional literature-assisted arm adds one more B.
- These are model-cost planning figures. E2B sandbox time, if chosen, and verification
  compute are extra.
- The ceilings are hard: ledger reservation happens before each call, and a ceiling may
  be raised mid-run only with the user's explicit approval, recorded as a budget
  amendment.
- Repetitions double the arm cost. Two per arm is the smallest design that shows any
  variance.

## 6. Stop rules (predeclared)

1. **Root accepted.** An independent-kernel receipt on the exact target stops the run
   (`stop_on_verified_target`). The runner drains already queued verifications for at
   most 600 seconds.
2. **Ceiling reached.** When the ledger reaches B, no new reservations are made.
3. **Wall clock.** The experiment's `max_runtime_seconds` and the `run-team --timeout-seconds`
   limit apply.
4. **Stagnation (operator rule).** S1 has no automated stagnation stop; CampaignRuntime
   in S2 adds one. So the operator exports every 15 minutes and runs
   `tools/society_metrics.py`. The operator stops the arm when no node has moved up the
   ladder (`nodes_by_status`) and no receipt has been accepted in the last 25% of B or
   45 minutes, whichever comes first.
5. **Fault.** On `BUDGET_RECONCILIATION_REQUIRED`, an uncertain external operation or a
   quarantined workspace, pause the experiment, audit, and ask the user before resuming.
   Earlier pilots did the same.
6. **Contamination.** On a confirmed leak (section 4), the arm keeps running only if the
   user agrees, and it is labelled contaminated.
7. **Operator stop** at the user's request.

Every stop produces an honest report of the frontier, obstacles and partial results
(PLAN §4.7).

## 7. Metrics (PLAN §9) and `tools/society_metrics.py`

Run the tool on each arm's export: `phys export <experiment> <dir>` and then
`python tools/society_metrics.py <dir> [--as-of <epoch>]`. Export directories contain
proof and transcript bytes, so keep them private.

| PLAN §9 metric | Tool output | Notes |
|---|---|---|
| Accepted root | `accepted_root`, `accepted_root_receipt_id` | Mirrors the acceptance predicate: a verified independent-kernel receipt bound to the reviewed target. It also works for legacy arms. |
| Accepted nodes | `accepted_nodes` | In S1 only the goal can be accepted. Non-root acceptance is deferred. |
| Time to root | `time_to_root_seconds` | From experiment start to the commit of the verified claim. |
| Cost per accepted node | `cost_per_accepted_result_usd`, `spent_cost_usd`, `tokens_spent` | Canonical ledger. |
| Duplicated-work fraction | `duplicate_claim_fraction`, `claimed_nodes`, `duplicate_claimed_nodes` | An upper bound: a claim record keeps only its first claim and last expiry. There is no claim-based baseline for the last run, so compare against the audited overlap in the arm reports. |
| Idle and waiting fraction; post-acceptance spend | Not computed | Needs event timelines, which the export does not contain. Use the database event log, as the earlier pilot evaluators did. |
| Coordination versus mathematics | `tool_call_mix` (`commons_society`, `math_lean_computation`, `other`, `by_tool`) | Counts calls, not tokens. It needs the runtime-event artifact bytes in the export directory; otherwise `available` is false. |
| Citation and reuse rate | `citations`, `cross_branch_citations`, `cross_branch_dependencies` | Confirm lemma reuse in the accepted proof by manual audit, as in the Duffing report. |
| Retrieval hit rate | Not computed | S1 has no accepted non-root nodes to retrieve. |
| Live approach families | `branches.labs`, `nodes_by_type` | Proxies. The count over time needs periodic exports. |
| Referee catch rate; fidelity failure rate | `referee_negative_share`, `fidelity_failure_share`, `reviews_by_verdict`, `cross_model_share`, `stale_reviews` | These are negative-verdict shares. A true catch rate needs ground truth. |
| Stale-claim rate | `stale_claim_count`, `live_claim_count`, `claims_as_of` | Unreleased claims past expiry at `--as-of`. |
| Lean iterations per accepted node | `lean_checks_per_accepted_result` | Needs runtime events. |
| Automation hit rate | Not computed | `lean_check` results are not persisted as records. |
| Skill and literature usage; contamination flags | `tool_call_mix.by_tool` (`load_skill`, `search_literature`, `fetch_source`), `literature_fetches`, `literature_by_status`, `contamination_flags` | Whether cited sources contributed is a manual audit. |
| Honest separation of evidence | `evidence.model_sessions`, `evidence.runtime_event_artifacts` | The operator labels each export as simulated, mocked-provider or live. |

**Predeclared reading of S1:**
- **Success signal:** arm S has an accepted root; its `duplicate_claim_fraction` is at
  most 0.5 (a heuristic threshold chosen before the run, not an estimate); and its
  accepted proof reuses at least one lemma from another branch.
- Arms 1 and I give the matched baseline: accepted or not, time to root and cost.
- With one repetition, none of this establishes a causal benefit.

## 8. Prerequisites and approvals

Each item needs the user. None has been started.

1. **Budget.** Choose an option from [section 5](#5-budget) and the number of
   repetitions, and approve each arm's ceiling B. This includes the development
   calibration. Paid runs need an explicit budget each time (PLAN §7).
2. **Target choice.** Pick one candidate from [section 3](#3-target-selection-user-decision-required),
   or another that meets the criteria. Then:
   - construct the reference proof and pass it through Comparator, Lean and Nanoda;
   - write the negative controls;
   - write the masked reference text and the blocklist;
   - have the target reviewed: assistant-led review under delegation, or human expert
     review, which is required before any publication.
3. **Tool-matching design.** Choose Design A or B ([section 2](#design-choice-tool-matching-user-decision-required)),
   and decide on the literature-assisted arm.
4. **Models.** Name the exact model ids for families A and B, and their recorded
   prices (`settings.model_prices`). The preflight accepts only `runtime="responses"`
   (`RUNTIME_NOT_INTEGRATED` otherwise) and checks only `OPENAI_API_KEY`. So family B
   must also be served through the Responses API, unless qualifying another runtime is
   approved. That would be work outside S1.
5. **Workbench v2 image rebuild and qualification.** This uses the dedicated
   Colima/Linux builder and needs approval (docs/FORMAL_ENVIRONMENT.md, "Workbench v2").
   - Resolve every `TODO(pin-at-rebuild)`: `LEAN_REPL_REVISION` and `LEAN_REPL_SHA256`
     in `formal/workbench-v2.Dockerfile` (the upstream `v4.33.0` tag commit, whose
     toolchain must be exactly `leanprover/lean4:v4.33.0`), and the versions plus
     aarch64 and x86_64 wheel SHA-256 values for python-flint, cvxpy, clarabel, scs and
     osqp in `formal/workbench-requirements.lock`.
   - Build, record the image digest, and requalify the workbench, including the REPL
     path `/opt/lean-repl/.lake/build/bin/repl`.
   - Without v2, `lean_check` falls back to one-shot Lean, which re-imports Mathlib on
     every check (slower and more expensive), and `run_computation` reports the new
     packages as `null`. The user decides whether S1 may run on v1.
6. **Verifier bundle registration for the chosen target.**
   - Run `phys bundle-target`, and add a `PHYSHARNESS_VERIFICATION_REGISTRY` entry per
     problem revision (docs/VERIFICATION.md).
   - Verifier qualification must be current for the frozen source.
   - Design B with eight plans needs eight entries.
7. **Workspace provider: E2B or local_docker.**
   - `local_docker` is qualified for up to 4 concurrent workbenches on the dedicated
     16 GiB, 8 CPU VM. Arm S at concurrency 12 needs a larger VM and
     `worker_max_active_workspaces` ≥ 12, plus requalification of that capacity.
   - The E2B adapter is implemented but has never run live. It needs `E2B_API_KEY`,
     a qualified template, and its own live qualification. It adds sandbox cost.
   - E2B's portable workspace archive is bounded at 64 KiB in total, 32 KiB per file
     and 64 files (`execution/e2b.py`). A harder target's proof and an agent's scratch
     files can exceed that, and checkpoint or handoff then fails with `WORKSPACE_LIMIT`.
     `local_docker` has a 256 MiB workspace quota.
   - This plan therefore recommends `local_docker` on a larger dedicated VM for S1.
8. **Operator setup (after approval).**
   - Upload the `masked_reference` artifact and fill the example plan.
   - Run `prepare-run`, review the target, register the verifier bundle,
     `configure_workforce`, and `check-run`.
   - Start the VM or E2B, and start the monitor.
   - Each of these needs the approvals above. No VM or paid call is started without them.

## 9. Known limitations going in

- No live evidence exists for any society path: tools, referees, labs, literature, the
  Lean session or sketching. Earlier live pilots used the legacy profile only.
- **Unreachable statuses.** Non-root `accepted` is deferred to S2/S4, and `refuted` has
  no platform path in S1. A `wrong` verdict leaves an objection but does not refute the
  node.
- **Agents see their own posts.** An agent's own node-thread posts are delivered back to
  its inbox, as in the legacy discussion delivery. That spends digest budget, and the
  simulation shows it.
- **Goal hole names.** Hole nodes sketched from the goal are named `node_hole_<i>`,
  because the goal node has no Lean name.
- **Standard axioms only.** `lean_check` records a local compile only when the proof
  uses nothing beyond `propext`, `Classical.choice` and `Quot.sound` (R23).
- **E2B file cap.** On E2B, `write_file` is capped at 32,768 bytes per file (R23), and the
  workspace archive at 64 KiB (section 8, item 7).
