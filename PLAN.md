# PhysHarnessV2 — Research Society plan

Status: **design draft for review** (2026-09-24). This plan reorganizes the existing roadmap around an open-ended "research society": many agents working toward one hard physics problem the way a scientific community does. It adds a design and an execution order. It does not replace the twelve waves in `docs/IMPLEMENTATION_PLAN.md` or their exit criteria (see §8 for the mapping). Apart from the S1 progress recorded in §7, nothing described below as proposed is implemented yet.

---

## 1. Vision

A single hard root problem is given to a society of agents that behaves like a research community rather than a task pipeline:

- Agents choose their own ideas, representations, methods and collaborators.
- They explore tangents and subproblems they judge useful, share findings, disagree, delegate and recruit.
- They build on each other's work and record what failed, so nobody repeats it.
- The investigation **persists**: individual agents finish, forget, restart or change direction, while the shared state of the problem, the accumulated knowledge and the open work survive.
- Formalization is built in. Ideas move progressively from informal argument to independently checked Lean proof, and the society ends when the root theorem is independently accepted (or its budget or stop policy is reached).
- The system should scale to hundreds and eventually thousands of agents.

### Decisions made (2026-09-24)

| Question | Decision |
|---|---|
| How to pay for scale | **Mixed models.** Frontier hosted models for ideas and lead work; self-hosted open-weight models on our own GPUs (Kubernetes) for the bulk of formalization and routine work. |
| Unit of the society | **One root problem per society.** Agents may explore tangents and subproblems that plausibly help the root. |
| Human role | **Maximize autonomy.** Automated checks and built-in formalization replace human gates. A human is needed only before a result is *published*. |
| Organizing approach | **Hybrid on a shared blueprint.** A blueprint graph is the coordination medium, labs are lightweight groups on it, and priority signals replace any currency. |
| Scaffolding and tools | **Light guidance plus a rich research toolkit** (§3.6–3.7): a default research playbook, technique skills, progress check-ins and stagnation nudges, a sketch-then-fill Lean pipeline, numerical methods and computation jobs, brokered online literature access, and fast Lean checking. Every guidance piece is optional for the agent, switchable per campaign, and measured against runs without it. |

### Where this plan deliberately disagrees with "no restrictions"

1. **Three hard boundaries stay:**
   - Independent proof acceptance. Otherwise "solved" is meaningless.
   - The canonical spending ledger. Otherwise one run can exhaust any budget.
   - Sandboxing of agent-written code.

   They cost agents essentially no freedom of thought. Everything else defaults to open.
2. **Mirror science's institutions, not a group chat.**
   - All-to-all messaging costs grow with the square of the number of agents and causes herding. In our last run, both lead agents converged on one method within the first minute.
   - Human science scales through small labs, papers with abstracts, citations, referees, review articles and open-problem lists.
   - The closest precedents are Terence Tao's crowdsourced Lean projects (the PFR formalization and the Equational Theories Project). Contributors coordinated through a shared blueprint that anyone could extend and claim nodes on, with Lean checking each node.
3. **Agent count is not the lever; cost is the constraint.**
   - Our last run cost about **$40 per busy agent-hour**: $49.10 conservative accounting, 17 minutes, at most 4 concurrent workers.
   - 1,000 busy frontier agents would cost on the order of $40k per hour.
   - OpenAI's Navier–Stokes report (as summarized in our 2026-09-24 research) used about 10,000 agents, a stronger internal model and about 130B output tokens.
   - Thousands of agents is only affordable with cheaper models doing most of the work. Growth must be gated on measured value per added agent.
4. **An agent is not a VM.**
   - An agent mostly waits on model calls, so it is a cheap async process.
   - VMs are leased only while an agent compiles or computes, and proof checking is a separate autoscaled pool.
   - 1,000 agents need far fewer than 1,000 VMs.
5. **Fewer, more general tools.** Agents currently get **63 tools**, including about 20 overlapping communication tools. Models use a small set of clear, general tools better. Target: about 22, including the new research toolkit (§3.3).
6. **Guide, don't dictate.** Light scaffolding helps: a default playbook, technique hints, nudges when stuck, and automation around Lean. A forced proof method would narrow exploration and can hurt strong models. So guidance is offered, never mandatory, and each piece is A/B-measured. Scaffolding never uses a benchmark's hidden reference solution.

---

## 2. The commons (blueprint and discourse)

### 2.1 Nodes

Every unit of research is a **node** in one graph rooted at the target. Nodes extend the existing canonical `claim` records, which already carry `conjecture`/`numerical`/`conditional` evidence and link to verification receipts.

- **Node types:** `goal` (the root), `lemma`, `definition`, `conjecture`, `approach`, `tangent`, `obstacle`, `counterexample`, `computation`.
- **Fields:** informal statement; optional Lean statement; assumptions; status (§2.2); authors; current claimants; attention score (§4.3); discussion thread.
- **Edges:** `depends_on`, `motivated_by`, `refutes`, `generalizes`, `specializes`, `duplicates`.
  - A `tangent` must name at least one `motivated_by` target (what it might help). It does not have to prove relevance upfront.
- **Negative results are first-class.** An `obstacle` node ("approach X fails because Y") or an abandoned node with its reason prevents the society from repeating dead ends.

### 2.2 Status ladder

`informal` → `refereed` → `formally_stated` (fidelity-checked) → `compiles_locally` → **`accepted`** (independent kernel receipt), plus the side exits `refuted` and `abandoned` (each with a reason).

- **Only platform checkers move a node up the ladder** (§5). Agents cannot set status.
- Agents may build on a node at any status.
- **Dependency status propagates.** Every node shows what it ultimately rests on (for example "uses 2 conjectures, 1 refereed lemma"). A root proof resting on anything below `accepted` is visibly conditional.

### 2.3 Claims on work

"I'm working on this node" is a **claim that expires** unless the agent renews it through activity. Stale claims free up automatically. This directly addresses what the last run showed: helpers queued for 10–12 minutes, and one started on work another agent had already finished. Several agents may claim one node. Duplication is visible, and it is allowed when intentional (independent attempts, checking).

### 2.4 Discourse protocol

- **One kind of post, attached to a node:** `question`, `finding`, `objection`, `attempt_failed`, `review`, `synthesis`, `update`.
- **Paper-style structure:** a short structured header (claim, assumptions, evidence status, what is being asked) plus a body retrieved only on demand. Agents read abstracts first and fetch full arguments deliberately.
- **Citations.** Posts and nodes cite nodes and artifacts. Citation counts are a signal for attention (§4.3), never for proof status.
- **Delivery.**
  - Agents are auto-subscribed to nodes they own, claim, cite or depend on, and can subscribe to more.
  - Updates arrive as a digest at safe pauses in the agent's work, within a size budget. Existing durable inbox semantics are kept (at-least-once, acknowledged, withdrawal notices).
  - Urgent events jump the queue: something you depend on was refuted, a dependency was accepted, someone posted an objection to your node, or a node you claimed was solved elsewhere.
- **Labs.**
  - A lab is a group of 3–8 agents working a region of the graph, with direct high-bandwidth messaging inside the lab.
  - Across labs, communication goes only through the graph and synthesis posts.
  - This sparse topology is the main defence against herding. Evidence from sparse multi-agent debate suggests it can match dense communication at lower cost; we still need to measure this for mathematical physics.

### 2.5 What it replaces

Addressed messages, discussions, the component registry, research profiles, teams and capacity requests collapse into **one commons service with about 5 tools** (§3.3). Existing records migrate or are wrapped, and old tools remain thin adapters until removed.

---

## 3. The agent

### 3.1 Reasoning and rhythm

- **Light guidance, no imposed method.** The agent reasons natively and chooses its own method. The optional playbook, skills and nudges (§3.7) point the way without prescribing steps.
- **The society runs on a short "constitution" in the prompt:** the norms of the community, not instructions for doing mathematics. The norms are:
  - Informal work is welcome.
  - State evidence status honestly.
  - Claim before sinking effort.
  - Post failures.
  - Cite what you use.
  - Recruit when a piece can proceed independently.
  - Ask for a referee before investing heavily in formalization.
- **Episodes.** An agent works in episodes around one or a few focus nodes. At each safe pause it gets its digest and chooses what to do next:
  - continue working;
  - post a finding;
  - claim or switch to another node;
  - recruit help;
  - request a referee;
  - formalize;
  - wait, which releases its worker slot until an event arrives. This is already implemented as durable peer waits.

### 3.2 Memory (three tiers)

1. **Working context.** The model's native context, compacted when needed. Compaction is already implemented and preserves exact target, assumptions and obligations.
2. **Notebook.** The agent's portable scientific memory: research notes checkpointed with exact assumptions and evidence status (already implemented). It survives handoff to a fresh session and to a different model.
3. **The commons.** Canonical and shared. On restart, an agent rebuilds its context from its notebook plus the current state of its focus nodes and their threads, so it never relies on stale context.

### 3.3 Tools (target: about 22, down from 63)

| Group | Tools |
|---|---|
| Workspace and computation | `shell`, `file` (read/write), `run_computation` (bounded background numerical job with recorded inputs, seed, precision and environment) |
| Lean | `lean_check` (persistent Lean session; goal states, errors, `#print axioms`), `lean_sketch` (compile a proof skeleton with holes; holes become blueprint nodes, §3.7), `lean_automate` (try automation and premise suggestions on one goal) |
| Library and literature | `search_library` (pinned Mathlib/Physlib; lexical, type-directed and semantic), `read_source`, `search_literature`, `fetch_source` (brokered online access, §3.6) |
| Commons | `commons_query`, `commons_read`, `commons_post`, `commons_claim`, `inbox` |
| Society | `recruit` (brief, focus node, hat, model tier), `message` (lab/direct), `wait` |
| Evidence | `submit_for_verification` (workspace file → candidate → independent check), `verification_status` |
| Memory and skills | `notebook` (read/write checkpointed notes), `load_skill` (technique library and tool recipes, §3.7) |

Existing tools map onto these. For example, `run_command`, `run_lean_scratch`, `check_lean_type`, `search_library_source`, `submit_workspace_candidate`, and the polynomial and matrix certificate checkers become `shell`, `lean_check`, `search_library`, `submit_for_verification` and computation recipes. Old names remain adapters during migration.

### 3.4 Roles are optional "hats", not assignments

Available hats: explorer, formalizer, referee, experimenter (numerics/simulation), librarian (library and literature search, deduplication), synthesizer (review articles), maintainer (graph upkeep). Recruitment can suggest a hat, agents can change hats, and none are mandatory.

### 3.5 Model routing

| Tier | Models | Typical use |
|---|---|---|
| **F** (frontier, hosted) | e.g. GPT-6 Sol, Claude | Strategy, new ideas, root attacks, referee of major steps, synthesis |
| **O** (open-weight, self-hosted) | Strong reasoning/prover models on our GPUs | Formalization loops, lemma proving, tactic search, routine refereeing, library search |
| **S** (small, fast) | Small self-hosted models | Digest summaries, deduplication, classification, compressing tool output |

- **Escalation and delegation.** An O-tier agent stuck after a bounded effort can request escalation to F. F-tier agents delegate formalization work down to O.
- **Budgets per tier.** Each tier has its own budget inside the campaign envelope.
- **Diversity.** Mixing models also diversifies blind spots. Referees should come from a different model family than the author where possible.

### 3.6 Research toolkit

**Computation and numerical methods** (inside the offline sandbox):
- **Already present:** Python with numpy, scipy, sympy and mpmath; exact polynomial and matrix-factorization checkers.
- **To add** through a reviewed image rebuild:
  - rigorous interval arithmetic (python-flint/Arb);
  - convex and semidefinite optimization (cvxpy with an SDP solver) for sum-of-squares and other certificates;
  - an SMT solver (z3);
  - graph tools (networkx);
  - plotting (matplotlib; plots returned as images to models that accept images).
- **Growth:** heavier packages (for example PDE solvers or SageMath) are added only on demonstrated need.
- **`run_computation`** runs longer jobs in the background within resource and time bounds. Results become `computation` nodes with reproducibility metadata (inputs, seed, precision, package versions, image digest), and they count as evidence, never proof (§5.3). Large sweeps later move to Ray (§6.1).

**Lean checking** (fast feedback is the biggest lever on formalization cost):
- **A persistent Lean session per workspace** with the pinned Mathlib/Physlib imports already loaded, instead of re-importing on every check.
- **Rich feedback on every check:** goal states, errors, and an axiom report.
- **On failure,** the check automatically runs automation (`simp`, `aesop`, `linarith`/`nlinarith`, `polyrith`, `positivity`, `norm_num`, `exact?`/`apply?`) and premise suggestions from library search on the failing goal, and returns what worked or came close.
- **Local compile success is never acceptance;** only the independent checker (§5.2) accepts.

**Literature and online sources** (brokered from the trusted plane, never from the sandbox, which stays offline):
- **Sources:**
  - `search_literature` covers arXiv, OpenAlex/Semantic Scholar, Mathlib/Physlib documentation, Lean community archives and general web search.
  - `fetch_source` retrieves a PDF or HTML page, converts it to text with source spans, and stores it as a source artifact with URL, time, hash and licence note.
- **Status of what's retrieved:**
  - Retrieved lemmas and proofs are **informal inputs**. They can be cited and autoformalized into nodes, which then climb the normal ladder with fidelity checks.
  - A paper saying something is true never gives a node proof status.
- **Access policy per campaign:**
  - `open` (open problems): full brokered access, all fetches logged.
  - `benchmark` (known results): the target's known-solution sources (papers, repositories, identifiable titles) are blocked, fetched text is screened for overlap with the masked reference, and any detected leak flags the run as contaminated.
  - A separate, clearly labelled "literature-assisted" benchmark arm may allow everything.
- **Fetched web content is untrusted data.** It is never treated as instructions; the sandbox has no credentials or egress, and the broker strips active content.

### 3.7 Light scaffolding (guidance, not a method)

- **Default research playbook** in the constitution, which agents may skip or reorder:
  1. Orient: restate the goal, and note known techniques and relevant library results.
  2. Explore: special cases, numerical experiments, literature.
  3. Conjecture and argue informally.
  4. Get a referee.
  5. Sketch the Lean proof with holes.
  6. Fill the holes.
  7. Submit.
- **Technique skills** (`load_skill`): short, curated notes on methods common in mathematical physics, each with when it applies, typical pitfalls, and pointers into Mathlib/Physlib. Examples: energy and Lyapunov methods, Grönwall and comparison arguments, variational methods, spectral and perturbation arguments, fixed-point and compactness arguments, convexity and operator inequalities for quantum information, symmetry arguments. Tool recipes (interval arithmetic, SOS certificates, the Lean sketch workflow) are skills too.
- **Progress check-ins.** Every so often (configurable by turns or spend), the runtime asks for a short structured self-assessment: current subgoal, confidence, blocker, next step. It is posted as an `update` on the agent's node, so it doubles as a status report for the society.
- **Stagnation nudges.** When the existing stagnation detector sees no progress, the agent receives *suggestions*:
  - try a special case or a numerical experiment;
  - search the literature;
  - request a referee;
  - recruit a collaborator;
  - switch approach;
  - hand over to fresh eyes.
  Repeated stagnation informs the allocator (§4.3).
- **Sketch-then-fill formalization** (the draft–sketch–prove pattern):
  1. From an informal proof, `lean_sketch` compiles a Lean skeleton with `sorry` holes to confirm the structure type-checks.
  2. Each hole's goal is extracted as a statement and becomes a `lemma` node linked to its parent.
  3. Holes are filled by automation first, then O-tier provers, then F-tier models.
  4. Filled pieces recompose, and the whole proof goes to independent checking.

  The blueprint and the proof structure stay in sync automatically.
- **Honesty rule.** No scaffold, hint or nudge is derived from a benchmark's hidden reference solution.

---

## 4. The society runtime

### 4.1 Persistent campaign

- **Replace the finite `ResearchTeamRunner`** with a **CampaignRuntime**: one durable Temporal workflow per society, using Continue-As-New.
- **What it owns:** the agent population, slot allocation, spawning and retiring agents, labs, synthesis cadence and stopping.
- **Event-driven:** it reacts to node status changes, idle agents, budget changes, expired claims and timers.
- **Persistence.** It can pause and resume across days. Agents retire and are reincarnated through handoffs.
- **Keeps existing guarantees:** leases and fencing, idempotency, uncertain-operation handling and checkpoint recovery.

### 4.2 Launch

1. The root target passes the automated fidelity ensemble (§5.1).
2. An opening round of several F-tier agents independently writes distinct framings or approaches to the root. Each distinct approach seeds a lab.
3. Every lab has one of its agents make a whole-root attempt from the start. Decomposition is never forced.

### 4.3 Attention allocation (priority signal, no currency)

- **Score per open node**, computed from:
  - whether it is on a path to the root;
  - how many dependents are waiting on it;
  - recent progress;
  - neglect (time since last attention);
  - how under-explored its approach family is;
  - referee confidence;
  - spend so far (diminishing returns);
  - bounded "this matters" votes from agents.
- **Push and pull.** Agents **pull** work from a frontier view sorted by score. The allocator **pushes** only when spawning agents or assigning them to neglected high-score nodes.
- **Reserved capacity** (initial defaults, tunable):
  - at least 20% for whole-root and deep attempts;
  - at least 10% for tangents and new approaches;
  - a minimum tenure, so quiet long attempts are not preempted for lacking short-term output.
- **Signals are never proof.** Citations, votes and message volume affect attention only.
- **Start simple.** Scoring begins as transparent heuristics. Learned allocation policies (Waves 6 and 10) replace it only after matched-budget evidence.

### 4.4 Diversity and anti-herding

- The allocator keeps a minimum number of distinct approach families alive.
- Periodic **fresh-eyes reseeding**: new agents get the root plus *accepted* results only, without the discussion, so they can escape a shared blind spot.
- Referees come from a different model family where possible.
- Synthesis must preserve dissent and cite sources. A popular conjecture never becomes fact through repetition.

### 4.5 Society maintenance agents

- **Synthesizers** periodically write review articles per region of the graph: what is known, what is open, contradictions, and the objections that remain. Digests reference these.
- **Maintainers** merge duplicate nodes (keeping both histories), flag stale claims and orphaned tangents, and repair edges.

### 4.6 Hierarchical budgets

- The campaign budget is split into lab sub-budgets, which are split into agent reservations.
- The allocator rebalances lab budgets periodically.
- This gives labs autonomy and removes the single experiment/budget row lock that would otherwise throttle concurrency at hundreds of agents.
- Reserve-before-call accounting is unchanged.

### 4.7 Stopping

- **Root accepted:** an independent kernel receipt on the exact root statement triggers a bounded wrap-up (final synthesis, proof outline, write-up), then stop. This is already implemented as exact-target stop and bounded drain.
- **Other stops:** budget exhausted, operator stop, or a stagnation policy (no status-ladder progress within a configured spend). Each produces an honest report of the frontier, obstacles and partial results.

---

## 5. Built-in checks and formalization

The principle is **informal first, progressive formalization, and strict verification at the point of claiming.** All checks are automated platform services, not optional agent behaviour.

### 5.1 Root target fidelity (before launch)

1. *k* independent formalizations of the root statement are produced by different models.
2. Pairwise equivalence is attempted in Lean, and disagreements are surfaced.
3. Each formalization is translated back to English and compared with the source by a judge ensemble.
4. Vacuity and sanity probes:
   - Are the hypotheses satisfiable? Construct an instance.
   - Is the statement trivially true or false? Run automation and look for counterexamples.
   - Can `False` be derived from the hypotheses?
5. The outcome is labelled **auto-reviewed**, never "human reviewed". Human review is optional for launch and required before a result is published as solved.

The final root proof is always checked against this fixed statement. Agent-invented intermediate definitions therefore cannot fake the root.

### 5.2 Node-level checks (these move nodes up the ladder)

1. **Referee.** An informal argument gets independent referee reviews, cross-model where possible. Objections stay attached to the node.
2. **Statement fidelity.** Adding a Lean statement triggers back-translation and judging, vacuity probes, and numerical or example testing where applicable.
3. **Local compile** in the agent's workspace.
4. **Independent acceptance**, using the existing Comparator + Lean + nanoda pipeline: axiom audit, no `sorry`, exact statement binding.
5. **Composition.** When dependencies are accepted, the consuming proof is rebuilt and re-checked against the consistent dependency closure (existing integration rule).

### 5.3 Formalization economy

- Formalization dominated the effort in the last run: the final proof was 606 lines.
- O-tier models run the Lean feedback loops. F-tier models handle statements, strategy and hard steps.
- Sketch-then-fill (§3.7) turns an informal proof into a Lean skeleton whose holes become nodes. The persistent Lean session and automation-on-failure (§3.6) cut the cost of each iteration.
- Accepted nodes are immediately reusable library entries within the campaign. Retrieval is tested to actually return them; in the last run, lemma-bank searches returned nothing.
- Agents may introduce definitions in a campaign-local namespace. Definitions are nodes with fidelity checks.
- Numerical and computational evidence stays evidence (computation nodes carry reproducibility metadata). It counts as proof only with a certificate checked in Lean (Wave 7).

---

## 6. Scale substrate

### 6.1 Separate planes (sized independently)

| Plane | Contents | Deployment |
|---|---|---|
| Control | API, canonical service, PostgreSQL, Temporal, S3 artifacts | Managed services |
| Agent | Async agent runtimes, each hosting many agent loops (target 50–200 per pod, to be measured) | Kubernetes Deployments, autoscaled by KEDA on active-agent demand, drain-aware |
| Inference | **Model router** (one API for all tiers; accounting, rate/token governance, prompt/prefix caching); hosted API gateway; **self-hosted open-weight models on a GPU node pool** via vLLM or SGLang | Kubernetes GPU pool, autoscaled on queue depth |
| Workspace | Sandboxes leased on demand; pre-baked images with Mathlib/Physlib build outputs as a shared read-only layer and a per-agent writable overlay; paused when idle | E2B first; Kubernetes Agent Sandbox + Kata (VM isolation) when E2B cost or quotas bind |
| Verification | Qualified Linux isolation; priority queue that favours root and critical-path candidates | Separate autoscaled pool; requalified on any runtime change |
| Compute (optional) | Numerics and large searches | Ray/KubeRay when there is a demonstrated need |

This **updates the 2026-09-22 scaling recommendation**, which said ECS first and Kubernetes only when self-hosting. Choosing self-hosted open-weight inference makes Kubernetes with GPU pools core infrastructure, so the agent and inference planes go to managed Kubernetes (EKS or GKE) directly. Workspaces stay on E2B until measured cost or quotas justify self-hosted sandboxes.

### 6.2 Data scaling

- The commons lives in PostgreSQL, partitioned per campaign. The event stream (the existing outbox) feeds subscriptions, and digests are computed incrementally.
- Hierarchical budgets (§4.6) remove hot-row locks.
- Chunked checkpoints keep storage bounded: 93% smaller on real checkpoints, already implemented.
- Indexed task, session and workspace queries replace in-Python filtering where measurements show cost.
- Lease-renewal and command volume at 1,000 agents is about 100 renewals/s. This needs profiling (see the 2026-09-22 research).

### 6.3 Capacity sizing

Useful concurrency is bounded by the smallest of:

- model throughput (hosted rate limits, plus self-hosted tokens/s per GPU times the number of GPUs);
- budget;
- workspace capacity;
- control-plane throughput;
- verifier throughput.

Size each plane from measured per-agent demand in the 8–32 agent runs. VM count alone is not a capacity measure.

---

## 7. Execution order (milestones)

Each milestone has exit evidence, and no milestone counts as wave qualification by itself. Paid runs need an explicit budget each time.

| # | Milestone | Main work | Exit evidence |
|---|---|---|---|
| **S0** | Land current work | Commit and PR the 2026-09-25 swarm hardening; merge `main` (the branch is 11 commits behind); refresh `IMPLEMENTATION_STATUS.md` | CI green; status docs current |
| **S1** | Commons v1, toolkit v1, tool consolidation | Nodes and edges on claims, status ladder, expiring claims, node threads, digests with urgent events, labs; referee and fidelity services. **Toolkit:** persistent Lean session with automation-on-failure, `lean_sketch` holes → nodes, `run_computation`, expanded numerics image, brokered literature access with per-campaign contamination policy, technique skills, check-ins and stagnation nudges. 63 → about 22 tools with adapters | Deterministic tests; then a live **8–16 agent** run on a hard known target versus a single agent and independent attempts at matched cost. Metrics: accepted root, less duplicated work than the last run, observed lemma reuse |
| **S2** | CampaignRuntime | Persistent society workflow, attention allocator with reserves, fresh-eyes reseeding, synthesizer and maintainer agents, hierarchical budgets, stagnation stop | A multi-session society (days, with pause/resume) that survives deliberate crashes and handoffs and continues without operator reassignment; **32 agents** |
| **S3** | Mixed-model routing | Model router; one self-hosted open-weight model on a Kubernetes GPU pool; tier budgets; escalation | Measured cost per accepted node by tier; at least 50% of agent-hours on self-hosted models with no drop in accepted-node rate at matched budget |
| **S4** | Kubernetes substrate at 128 | Agent, inference and verification planes on managed Kubernetes; workspace pool (E2B, with an Agent Sandbox + Kata trial); instrumentation | **Wave 8:** 72 hours at 128 active agents with injected failures, reconciled accounting, no lost accepted results |
| **S5** | Hundreds to 1,000 | Sharded commons, fair admission, provider-rate governance, verifier backpressure | **Wave 9:** 1,000 agents doing useful work, **only if S1–S4 show positive marginal value per added agent** |
| **S6** | Open-problem societies | Expert- or auto-reviewed open roots; publication review | **Wave 11:** can begin after S2 with small societies; sustained campaigns follow S4 |

**S1 progress (2026-09-25):** implemented, pending the final review. The commons, the toolkit and the 25-tool society profile ([S1 plan](docs/superpowers/plans/2026-09-25-s1-research-society.md), Tasks 1–10) sit behind an opt-in society policy. Evidence so far is deterministic tests only, including a no-model end-to-end simulation. The live 8–16 agent comparison has **not** run: it needs the approvals in [the S1 run plan](work/society-s1/RUN_PLAN.md). Those are the budget, the target, the models, the workbench v2 rebuild, the verifier bundle and the workspace provider. Deferred by design: node-level acceptance, the root fidelity ensemble, background jobs, general web search, the allocator and maintenance agents, and hierarchical budgets.

The **first society target** should be a known result that is hard enough that a single agent does not finish it quickly (harder than the Duffing-network target), with its reference solution masked. That gives collaboration real work and gives us a correct answer to check against.

---

## 8. Mapping to the existing waves

| Society component | Waves it advances |
|---|---|
| Commons, blueprint, discourse, labs | 4 (collaboration and memory), 5 (knowledge) |
| Built-in checks, fidelity ensemble, formalization economy | 1 (acceptance), 5 (autoformalization), 7 (certificates) |
| Research toolkit and light scaffolding | 2 (single-agent loop, optional research skills), 5 (literature ingestion and retrieval), 7 (numerics and certificates) |
| CampaignRuntime, allocator, diversity reserves | 6 (search and scaling policies), 9 (fair scheduling) |
| Model router, self-hosted inference | 9 (scale), 10 (learning from society data) |
| Kubernetes planes, workspaces, verifier pool | 3 (durable execution), 8 (128 workers), 9 (1,000 workers) |
| Open-problem societies | 11 |

Wave 0 (expert review of the 40 benchmark targets) remains open. The auto-review ensemble can pre-screen them, but it does not replace the human review that the wave's exit criteria require.

---

## 9. Evaluation (tracked in every live run)

- **Outcomes:** accepted root, accepted nodes, time to root, cost per accepted node.
- **Efficiency:** duplicated-work fraction, idle and waiting fraction, post-acceptance spend, tokens spent on coordination versus mathematics.
- **Knowledge:** citation and reuse rate, retrieval hit rate for applicable accepted nodes.
- **Society health:** number of live approach families over time (herding), referee catch rate, fidelity-check failure rate, stale-claim rate.
- **Matched-budget comparisons:** single agent vs independent attempts vs society. Policies are promoted only on reproducible gains.
- **Scaffolding and tools:** scaffolding on vs off at matched budget; Lean iterations per accepted node; automation hit rate; skill and literature usage and whether cited sources contributed; contamination flags in benchmark runs.
- **Honest separation of evidence:** simulated vs mocked-provider vs live runs.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Graph clutter and duplication at scale | Maintainer agents, `duplicates` edges, claim expiry, digest budgets |
| Herding onto one approach | Labs, sparse cross-lab channel, diversity reserves, fresh-eyes reseeding, cross-model referees |
| Gaming the attention signals | Signals affect attention only; bounded votes; only platform checkers move status |
| Referee blind spots | Cross-model referees, preserved objections, independent kernel as final arbiter |
| Runaway spawning or spend | Hierarchical budgets, reserve-before-call accounting, descendant caps |
| Context flooding | Abstract-first posts, byte-bounded digests, urgent-only push |
| Open-weight quality gap | Escalation to F tier; tier choice measured per role before shifting volume |
| Cost of scale | Growth gated on measured marginal value; self-hosted inference for bulk work |
| Benchmark contamination via online access | Per-campaign access policy, blocked known-solution sources, overlap screening against the masked reference, fetch logs, separate literature-assisted arm |
| Prompt injection from web content | Fetched content treated as untrusted data; offline sandbox with no credentials; broker strips active content |
| Over-scaffolding narrows exploration | Guidance is optional and switchable per campaign; A/B measured; no mandatory steps |

## 11. Open questions (to settle during S1–S3)

- Which open-weight models serve the O and S tiers, and on what GPUs? Choose by measured Lean formalization success per dollar.
- Which hard known target to use as the first society benchmark? It needs a masked reference.
- Referee quorum and when to require cross-model review, to be tuned from the S1 runs.
- Whether cross-campaign libraries are wanted later (currently out of scope: one society, one root).
