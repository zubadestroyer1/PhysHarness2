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
| **1. Single agent** | One root, family A | 1 | 1 | B / $40 hours (at most 24 h), or earlier when it finishes |

**W** is arm S's wall-clock ceiling. It is the arm's busy agent-hours divided by arm S's
concurrency: 1 h, 1.5 h and 1.5 h in the three budget options of
[section 5](#5-budget). The operator sets it as `run-team --timeout-seconds` and as the
plan's `budget.max_runtime_seconds`.
- Every arm's wall clock must fit one `run-team` invocation, which allows at most
  86,400 s.
- A timeout (`TEAM_TIMEOUT`) cancels active tasks and does not drain queued
  verifications. The runner's 600-second verification drain applies only when generation
  stops for another reason, such as an exhausted budget.
- Allow room within W for a late candidate's verification.

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
| 1 | **Tsirelson's bound**: for Hermitian involutions A₀, A₁ (m × m) and B₀, B₁ (n × n), with C = A₀⊗(B₀+B₁) + A₁⊗(B₀−B₁) as a Kronecker product, every unit vector ψ ∈ ℂᵐⁿ satisfies Re⟨ψ, Cψ⟩ ≤ 2√2 | quantum | A known finite-dimensional operator inequality (Mathlib `Matrix`, Kronecker products, `PosSemidef`) whose proof needs a sum-of-squares operator identity and noncommutative algebra, a harder kind of step than the Duffing energy estimate. |
| 2 | **Kepler orbit equation from conserved vectors**: let r : ℝ → ℝ³ satisfy r̈ = −μ r/‖r‖³ with μ > 0 and r(t) ≠ 0 for all t. Fix a time t₀ and set h₀ = r(t₀) × ṙ(t₀) and A₀ = ṙ(t₀) × h₀ − μ r(t₀)/‖r(t₀)‖. Then μ‖r(t)‖ + A₀·r(t) = ‖h₀‖² for every t, which is the orbit ‖r‖(1 + e cos θ) = ‖h₀‖²/μ with e = ‖A₀‖/μ | classical | Because h₀ and A₀ are fixed at t₀, the claim at other times needs both conservation lemmas (angular momentum, then the Laplace–Runge–Lenz vector) in ℝ³ (`HasDerivAt`, Mathlib `crossProduct`) before the dot-product identity, so it splits naturally into lemmas. |
| 3 | **Explicit exponential stability of x′ = Ax from a Lyapunov pair**: for real n × n matrices with P, Q symmetric positive definite and AᵀP + PA = −Q, every solution satisfies ‖x(t)‖² ≤ (λmax(P)/λmin(P)) e^{−(λmin(Q)/λmax(P)) t} ‖x(0)‖² for all **t ≥ 0** (for t < 0 it fails in general) | classical | It extends the Duffing energy method to matrices and needs spectral bounds for positive definite matrices, but the `energy-lyapunov` skill names the route, so it is likely the easiest of the five. |
| 4 | **Exponential convergence of a finite Markov chain under Doeblin's condition**: for a row-stochastic P on n states with P(i,j) ≥ δ > 0 for all i, j, there is a unique stationary distribution π, and every distribution μ satisfies d_TV(μPᵗ, π) ≤ (1 − nδ)ᵗ for all t ∈ ℕ, where d_TV(μ, ν) = sup over sets S of \|μ(S) − ν(S)\| = ½ Σⱼ \|μⱼ − νⱼ\| | classical (statistical physics) | Finite sums, the one-step total-variation contraction by 1 − nδ, and existence and uniqueness of π (which needs δ > 0); with the ℓ¹ norm instead of d_TV the constant would be 2(1 − nδ)ᵗ. A target free of nonlinear ODEs, which tests whether the society generalizes beyond energy estimates. |
| 5 | **Gibbs variational principle (finite system)**: on a finite nonempty state set with energies Eᵢ and temperature T > 0, let Z = Σᵢ e^{−Eᵢ/T}. Every probability vector p satisfies Σᵢ pᵢEᵢ + T Σᵢ pᵢ log pᵢ ≥ −T log Z (with 0 log 0 = 0), with equality exactly when pᵢ = e^{−Eᵢ/T}/Z | classical (statistical physics) | Convexity (Gibbs or log-sum inequality) plus the equality case; possibly too easy if Mathlib's KL-divergence results apply directly, so it is a fallback or development rung. |

## 4. Literature mode

- **Benchmark mode (arm S, and every arm in Design B).**
  - `blocked_sources` lists, for **each** known-solution source of the chosen target,
    its arXiv id **and** its journal DOI, plus a distinctive title fragment of two or
    more words. Other accepted entries are OpenAlex ids (`W…` or its URL), single page
    URLs and bare domains.
  - Identifiers may be written in any common form: `arXiv: 2101.00001v2 [math-ph]`,
    `math.AP/0601001`, abs, pdf or html URLs with or without a scheme,
    `10.48550/arXiv.<id>` (read as the arXiv id), and bare, `doi:`, `DOI:` or doi.org
    DOIs in any case. An entry that is none of these is rejected when the plan is
    validated, by preflight (`LITERATURE_BLOCKLIST_INVALID`) and by the broker; it is
    never accepted silently.
  - Identifiers are matched against every identity of a search result (its DOI, all
    OpenAlex locations and `ids`, arXiv's own DOI and links). They also refuse fetches
    of the named arXiv, doi.org and OpenAlex pages, and withhold fetched text that
    cites them. Title fragments are normalized (case, accents, LaTeX markup and math
    delimiters, quotes, dashes, spacing) and screen titles, abstracts, journal
    references and fetched text, as whole words. They are never compared with a URL an
    agent chose, so a fetch cannot probe them.
  - **List both forms.** The broker makes no extra network calls to map an arXiv id to
    its journal DOI or back. It links the two only when a provider record carries both
    (an arXiv entry with its journal DOI, or an OpenAlex work with an arXiv location),
    and then refuses both for the rest of that execution. Until then a DOI-only entry
    does not stop a fetch of `arxiv.org/html/<id>`, and an arXiv-only entry does not
    stop a journal record that lists no arXiv copy. Preflight notes
    `LITERATURE_BLOCKLIST_ONE_FORM` when a benchmark blocklist uses only one form.
  - `masked_reference_artifact_id` names a private `masked_reference` artifact holding
    the reference text. The operator uploads it before `prepare-run`, and agents cannot
    read it. In the example it is the short placeholder
    `USER DECISION REQUIRED: ref id`, because the field holds at most 36 characters.
    Preflight applies the broker's own check: the text needs at least 20 distinct
    eight-word sequences (about 27 words), or the overlap screen could never fire and
    preflight reports `MASKED_REFERENCE_REQUIRED`.
  - The broker screens search results and fetched text for overlap with the reference
    (`overlap_threshold` 0.02) and withholds flagged text. Agents see one reason code,
    `withheld_contamination_risk`, whether the text overlapped the reference or cited a
    blocked source. The measurements stay in a private `literature_screen` artifact.
    Searches return only the released items: how many were withheld is logged on the
    worker, never returned to the agent.
  - The withholding is an inherent 1-bit oracle: an agent learns that a source it chose
    was close to the reference or named a blocked source, and repeated fetches can probe
    that. It never sees the text, the measurements or which screen fired. The post-run
    audit below covers what an agent could infer.
  - Fetches of search and listing pages on allowlisted hosts are refused
    (`LITERATURE_SOURCE_BLOCKED`), after percent-decoding and dot-segment removal:
    arXiv `/search`, `/list`, `/a/`, `/catchup`, `/year`, `/find`, `/archive` and
    `/multi`; Wikipedia `api.php`, `rest.php`, `/api/`, every `Special:` page (by path
    or `title=`) and any `search=` or `fulltext=` query; the MathOverflow and Math
    StackExchange home page, `/questions` listing, `/questions/tagged`, `/search`,
    `/tags`, `/unanswered`, `/feeds` and `/users`; and nLab search, `all_pages`, `list`,
    `recently_revised`, feeds and exports. Those pages list other works outside
    `search_literature`'s per-item screen.
  - Only verbatim reuse is detected: eight-word overlap with the reference, cited
    identifiers and normalized title fragments. Paraphrase, translation or a proof
    restated in other notation passes the screen; the post-run audit is the check.
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
- **Politeness.** Every broker in a worker process shares one per-host limiter. arXiv
  (arxiv.org and the https export API together) gets one request at a time, three
  seconds apart, as its API terms ask; OpenAlex 0.2 s; other hosts one second. A 429 or
  503 holds the host back for everyone for its `Retry-After` (or an exponential
  backoff), with up to three attempts when the wait is at most 30 s. A request that
  would queue longer than 60 s fails with the retryable `LITERATURE_RATE_LIMITED`. Set
  `PHYSHARNESS_LITERATURE_CONTACT` to an operator email to send it as OpenAlex's
  `mailto` and in the User-Agent; unset, none is sent. The limiter does not span
  processes, so run literature-enabled workers in one process.

## 5. Budget

The planning figure is **$40 per busy agent-hour**, from PLAN §1. The Duffing retry cost
$49.10 for 17 minutes with at most 4 concurrent workers, about $43 per busy agent-hour at
full occupancy. Busy agent-hours include referee tasks and assume every slot stays busy
for the whole ceiling, so they are an upper bound on spend. Arm I spends ceiling B over
B / (8 × $40) hours; arm 1 over B / $40 hours, and it usually stops earlier.

| Option | Arm S shape (concurrency × W) | Busy agent-hours per arm | Ceiling B per arm | Arm I wall clock | Arm 1 wall clock | Three arms | Development calibration | Total, one repetition | Total, two repetitions |
|---|---|---|---|---|---|---|---|---|---|
| Minimum | 12 × 1 h | 12 | $480 | 1.5 h | 12 h | $1,440 | $80 (2 agent-hours) | **$1,520** | $2,960 |
| Recommended | 12 × 1.5 h | 18 | $720 | 2.25 h | 18 h | $2,160 | $160 (4 agent-hours) | **$2,320** | $4,480 |
| Upper (16 concurrent) | 16 × 1.5 h | 24 | $960 | 3 h | 24 h | $2,880 | $160 | **$3,040** | $5,920 |

- **The Upper row is capped by arm 1.** Arm 1 has one agent, so its wall clock is B / $40.
  A ceiling of $960 already needs 24 h, the most one `run-team --timeout-seconds` allows.
  A larger B would need arm 1 to continue in a second `run-team` invocation after a
  timeout. That would re-seed its root idempotently and resume the task through its
  continuation, but no such resumption has been qualified, so this plan does not use
  it.
- The Upper row also needs `budget.max_concurrency` 16 in the plan (the example has 12)
  and 16 concurrent workbenches.
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
   (`stop_on_verified_target`, `TARGET_VERIFIED`). The runner retires queued tasks, starts
   no new work and lets running tasks finish their bounded wrap-up.
2. **Ceiling reached.** When the ledger reaches B, no new reservations are made.
3. **Wall clock.** Arm S stops at W, arm I at B / (8 × $40) and arm 1 at B / $40, each at
   most 24 h: the `run-team --timeout-seconds` value and the plan's `max_runtime_seconds`.
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
| Coordination versus mathematics | `tool_call_mix` (`commons_society`, `math_lean_computation`, `other`, `unclassified`, `by_tool`) | Counts calls, not tokens. It needs the runtime-event artifact bytes in the export directory; otherwise `available` is false. The buckets are listed below the table. |
| Citation and reuse rate | `citations`, `cross_branch_citations`, `cross_branch_dependencies` | Confirm lemma reuse in the accepted proof by manual audit, as in the Duffing report. |
| Retrieval hit rate | Not computed | S1 has no accepted non-root nodes to retrieve. |
| Live approach families | `branches.labs`, `nodes_by_type` | Proxies. The count over time needs periodic exports. |
| Referee catch rate; fidelity failure rate | `referee_negative_share`, `fidelity_failure_share`, `reviews_by_verdict`, `cross_model_share`, `stale_reviews` | These are negative-verdict shares. A true catch rate needs ground truth. |
| Stale-claim rate | `stale_claim_count`, `live_claim_count`, `claims_as_of`, `claims_as_of_source` | Unreleased claims past expiry at `--as-of`. Without `--as-of`, claims are judged at the run's end (the latest activity in the export), so claims that merely outlived the run are not counted. Stale counts are meaningful only for in-run exports (the 15-minute checks) or with an explicit `--as-of`. A post-run count misses a lapse that the same branch later re-claimed, because the claim record is overwritten. |
| Lean iterations per accepted node | `lean_checks_per_accepted_result` | Needs runtime events. |
| Automation hit rate | Not computed | `lean_check` results are not persisted as records. |
| Skill and literature usage; contamination flags | `tool_call_mix.by_tool` (`load_skill`, `search_literature`, `fetch_source`), `literature_fetches`, `literature_by_status`, `contamination_flags` | Whether cited sources contributed is a manual audit. |
| Honest separation of evidence | `evidence.model_sessions`, `evidence.runtime_event_artifacts` | The operator labels each export as simulated, mocked-provider or live. |

**Tool buckets.** Every tool of the society profile and of the 63-tool legacy profile is in
exactly one bucket; `tests/test_society_metrics.py` enforces this. A tool in no bucket
(one added later) counts as `unclassified`.
- `commons_society`: commons, inbox, messaging, recruitment, waiting, delegation,
  discussion, return and review tools.
- `math_lean_computation`: shell, file, Lean, library, computation, candidate and
  verification tools.
- `other` (memory, knowledge, literature and skills): society `search_literature`,
  `fetch_source`, `notebook`, `load_skill`, `read_artifact`; legacy `checkpoint_context`,
  `checkpoint_research_notes`, `history_page`, `index_page`, `read_artifact`,
  `read_artifact_chunk`, `read_dependency_bundle`, `read_scientific_record`,
  `research_graph_page`, `restart_brief`, `restore_context`, `search_knowledge`,
  `store_artifact`, `working_context`.

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
   - Pin the transitive dependencies the lock flags (recalled offline and not yet
     verified). cvxpy needs osqp, clarabel and scs. osqp 0.6.x needs `qdldl`, a binary
     wheel with its own pin. osqp 1.x instead needs `jinja2`, `joblib` and `setuptools`.
     Prefer the Debian packages (`python3-jinja2`, `python3-joblib`,
     `python3-setuptools`, and `python3-cffi` if any wheel needs cffi) when the snapshot
     satisfies them. Otherwise give each its own hashed lock line.
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
- **Local compiles rest on the statement check.** `lean_check` records a local compile
  only when the platform's statement check passes (docs/RESEARCH_NETWORK.md). The kernel
  re-checks every declaration of the compiled file. The theorem's elaborated type must
  equal the node statement's under `lean_header` alone. The axioms the check collects
  itself must be within `propext`, `Classical.choice` and `Quot.sound` (R23).
  - Cost: each recorded compile runs three more Lean processes in the VM (the file, the
    reference statement, the checker), each importing the header.
  - It needs `python3` and `lake` in the VM, as the REPL daemon and the one-shot
    fallback already do, and runs the same way on v1 and v2.
  - `compiles_locally` stays VM-attested: it resists forged Lean source, not a tampered
    VM.
- **E2B file cap.** On E2B, `write_file` is capped at 32,768 bytes per file (R23), and the
  workspace archive at 64 KiB (section 8, item 7).
