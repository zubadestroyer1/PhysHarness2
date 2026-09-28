# PhysHarnessV2 — Research Society plan

Status: **design draft for review** (2026-09-24). This plan reorganizes the existing roadmap around an open-ended "research society": many agents working toward one hard physics problem the way a scientific community does. It adds a design and an execution order. It does not replace the twelve waves in `docs/IMPLEMENTATION_PLAN.md` or their exit criteria (see §8 for the mapping). Apart from the S1 progress and the S1 remediation recorded in §7, nothing described below as proposed is implemented yet.

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
| Organizing approach | **Hybrid on a shared blueprint.** A blueprint graph is the coordination medium, labs are lightweight groups on it, and priority signals replace any currency. (S1 remediation: labs removed; relevance routing, a message rate limit and declared routes keep the society sparse, §2.4.) |
| Scaffolding and tools | **Light guidance plus a rich research toolkit** (§3.6–3.7): a default research playbook, technique skills, progress check-ins and stagnation nudges, a sketch-then-fill Lean pipeline, numerical methods and computation jobs, brokered online literature access, and fast Lean checking. Every guidance piece is optional for the agent, switchable per campaign, and measured against runs without it. (S1 remediation: check-ins, nudges and skills removed; `lean_sketch` replaced by `lean_check(stubs=true)`.) |

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
5. **Fewer, more general tools.** Legacy agents get **63 tools**, including about 20 overlapping communication tools. Models use a small set of clear, general tools better. The society profile has 24, including the research toolkit (§3.3).
6. **Guide, don't dictate.** Light scaffolding helps: a default playbook, shared library notes, and opt-in automation around Lean. S1's technique skills, check-ins and stagnation nudges were removed after S1, which used them little or not at all (§3.7). A forced proof method would narrow exploration and can hurt strong models. So guidance is offered, never mandatory, and each piece is A/B-measured. Scaffolding never uses a benchmark's hidden reference solution.

---

## 2. The commons (blueprint and discourse)

### 2.1 Nodes

Every unit of research is a **node** in one graph rooted at the target. Nodes extend the existing canonical `claim` records, which already carry `conjecture`/`numerical`/`conditional` evidence and link to verification receipts.

- **Node types:** `goal` (the root), `lemma`, `definition`, `conjecture`, `approach`, `tangent`, `obstacle`, `counterexample`, `computation`.
- **Fields:** informal statement; optional Lean statement; assumptions; status (§2.2); authors; current claimants; attention score (§4.3); discussion thread.
- **Edges:** `depends_on`, `motivated_by`, `refutes`, `generalizes`, `specializes`, `duplicates`.
  - A `tangent` must name at least one `motivated_by` target (what it might help). It does not have to prove relevance upfront.
- **Negative results are first-class.** An `obstacle` node ("approach X fails because Y") or an abandoned node with its reason prevents the society from repeating dead ends.

### 2.2 Status

A node is `open` until its author abandons it (`abandoned`, with a reason) or the platform accepts or refutes it (`accepted`, `refuted`). The S1 remediation removed the status ladder (audit #17): S1's agents spent much of their effort climbing a referee-driven ladder. S1's ladder values read as open.

- **The verifier is the only arbiter.** An independent kernel receipt on the exact target accepts the goal. A node imported by an independently verified proof records that proof in `in_verified_proof`; its status stays open. Imported means inlined, not necessarily used: nothing checks which constants the proof uses. Source ranks (`verified`, `complete`, `partial`) are advisory, since the VM computes them, and a rank that proves a stated node rests on a statement check that judged it (one that could not judge leaves the source `partial`); only verifier receipts are authority, and the verifier certifies the target's axioms, not each imported lemma's. A published module or node statement holds no code that would run where it is imported or checked (no `#eval`, `run_cmd`, elaborators, macros, global notation or IO), so importing a peer's lemma runs none of the peer's code in the importer's VM.
- Agents cannot set status, apart from an author abandoning its own node. Referees check plans and never move a status (§5.2).
- Agents may build on a node at any status.
- **Dependency sources propagate.** Every node shows what it ultimately rests on, by source rank (for example "rests on 2 stubs and 1 verified lemma"). A root proof resting on anything below a complete source is visibly conditional. A source counts only while every module its check inlined is still that node's source; once one is replaced it reads `stale`. Another branch cannot replace a verified source, or a complete one of an elaborated statement, at its rank, so importers are not churned stale; a definition's complete source, which nothing outranks, is locked the same way while its publisher's or author's branch is live, and any branch may replace it once both have ended (so an unrelated file can neither hold it for good nor swap out a real one).

### 2.3 Claims on work

"I'm working on this node" is a **claim that expires** unless the agent renews it through activity. Stale claims free up automatically. This directly addresses what the last run showed: helpers queued for 10–12 minutes, and one started on work another agent had already finished. Several agents may claim one node. Duplication is visible, and it is allowed when intentional (independent attempts, checking).

- **Routes and time boxes (S1 remediation).** A claim may name its **route**, the method it tries, and a **time box** of 5–240 minutes that caps every renewal: the claim lapses at the box unless the agent claims again.
- **The frontier rewards distinct routes.** A node's score drops by 1 for each live claim that names no route, or a route another live claim of the node also names. Claims on distinct routes cost nothing.
- **The compile note.** When a node first gets a complete source, the platform posts "compiled by … (route: "…"); consider stopping your route" on its thread, with the route on one line as a quoted JSON string. The note is urgent for the node's other live claimants and pushed to no one else.

### 2.4 Discourse protocol

- **One kind of post, attached to a node:** `question`, `finding`, `objection`, `attempt_failed`, `review`, `synthesis`, `update`.
- **Paper-style structure:** a short structured header (claim, assumptions, evidence status, what is being asked) plus a body retrieved only on demand. Agents read abstracts first and fetch full arguments deliberately.
- **Citations.** Posts and nodes cite nodes and artifacts. Citation counts are a signal for attention (§4.3), never for proof status.
- **Delivery.**
  - Agents are auto-subscribed to nodes they own, claim, cite or depend on, and can subscribe to more.
  - The goal takes no claims (every root works toward it, so a claim says nothing), and nobody follows its thread: the goal thread is a pull-only digest, read with `commons_read` (the ten newest posts as one line each; `before` pages older ones).
  - Updates arrive as a digest at safe pauses in the agent's work, within a size budget. Existing durable inbox semantics are kept (at-least-once, acknowledged, withdrawal notices).
  - A builder's digest is compact: one line per item with 8-hex ids that tools accept (the envelope was 91% of an update's tokens). Referees keep the fenced JSON envelope.
  - Delivery never pushes an agent's own posts, nor non-urgent platform status posts; the cursor advances past them.
  - Urgent events jump the queue: something you depend on was refuted, a dependency was accepted, someone posted an objection to your node, or a node you claimed was solved elsewhere.
- **No labs (S1 remediation).** Labs blocked the one useful hand-off in S1 and decided nothing else. Sparsity now comes from relevance routing (updates reach a node's author, claimants, citers and dependents, never a goal-thread broadcast), a per-sender message rate limit (`messages_per_minute`), and declared alternative routes at genuine choice points (§4.4).

### 2.5 What it replaces

Addressed messages, discussions, the component registry, research profiles, teams and capacity requests collapse into **one commons service with six tools** (§3.3). Existing records migrate or are wrapped, and old tools remain thin adapters until removed.

---

## 3. The agent

### 3.1 Reasoning and rhythm

- **Light guidance, no imposed method.** The agent reasons natively and chooses its own method. The optional playbook (§3.7) points the way without prescribing steps.
- **The society runs on a short "constitution" in the prompt:** the norms of the community, not instructions for doing mathematics. The norms are:
  - Informal work is welcome.
  - State evidence status honestly.
  - Claim the node you work on before sinking effort (the goal takes none; read its thread on demand). Several branches may claim one node on different routes: name yours, and optionally a time box.
  - At a genuine choice between methods, a second route is cheap insurance; stop yours when another compiles.
  - Post failures.
  - Cite what you use.
  - Recruit for one narrow deliverable (a named lemma with its signature, or a lookup); recruits end when they return.
  - Ask a referee to check a plan before a long formalization; compiled Lean needs no referee.
  - Publish Lean on its node (lean_check with node_id) and import peers' modules instead of copying their code.
  - When you have nothing useful to do, wait for events (free while waiting) or finish; the goal's long pole is where help counts most.
- **Episodes.** An agent works in episodes around one or a few focus nodes. At each safe pause it gets its digest and chooses what to do next:
  - continue working;
  - post a finding;
  - claim or switch to another node;
  - recruit help;
  - ask a referee to check a plan;
  - formalize;
  - wait, which releases its worker slot until a relevant event (a routed post or message, a watched node or branch, a long-pole change) or a timeout.

### 3.2 Memory (four tiers)

1. **Working context.** The model's native context, compacted when needed. Compaction is already implemented. The legacy anchor preserves exact target, assumptions and obligations; the society anchor is the same lean view as its prompt (exact target and assumptions, objective, frontier, the goal's long pole and claims).
2. **Notebook.** The agent's portable scientific memory: research notes checkpointed with exact assumptions and evidence status (already implemented). It survives handoff to a fresh session and to a different model.
3. **The commons.** Canonical and shared. On restart, an agent rebuilds its context from its notebook plus the current state of its focus nodes and their threads, so it never relies on stale context.
4. **Library notes.** Shared, per Mathlib pin, across a project's experiments.

### 3.3 Tools (24 in the society profile, down from 63)

| Group | Tools |
|---|---|
| Workspace and computation | `shell`, `read_file`, `write_file`, `run_computation` (bounded background numerical job with recorded inputs, seed, precision and environment) |
| Lean | `lean_check` (persistent Lean session; goal states, errors, `#print axioms`; with `node_id` it publishes the node's module, and with `stubs=true` it turns a skeleton's sorry lemmas into stub nodes) |
| Library | `find_declaration` (pinned Mathlib/Physlib declarations as ranked `Name signature — path:line` rows, by name or by type, with did-you-mean names; reads at most ±40 lines around one), `library_notes` (shared facts about the Mathlib pin, §3.2) |
| Literature | `search_literature`, `fetch_source` (brokered online access, §3.6) |
| Commons | `commons_query`, `commons_read`, `commons_node`, `commons_post`, `commons_claim`, `commons_fetch` (commons Lean into the workspace) |
| Society | `recruit` (brief, focus node, hat, model tier), `message` (a branch or a node's workers), `wait` (for events or recruits) |
| Evidence | `read_artifact`, `submit_for_verification` (workspace file → candidate → independent check), `verification_status` |
| Memory | `notebook` (read/write checkpointed notes) |
| Task-specific | `return_result` (joined recruits), `submit_review` (referees) |

A worker's widest catalog has 23 (all but `submit_review`); a referee's has 15, since a referee neither builds, claims nor recruits.

Existing tools map onto these. For example, `run_command`, `run_lean_scratch`, `check_lean_type`, `search_library_source`, `submit_workspace_candidate`, and the polynomial and matrix certificate checkers become `shell`, `lean_check`, `find_declaration`, `submit_for_verification` and computation recipes. Old names remain adapters during migration.

### 3.4 Roles are optional "hats", not assignments

Available hats: explorer, formalizer, referee, experimenter (numerics/simulation), librarian (library names, signatures and duplicates for one brief, then return), synthesizer (review articles), maintainer (graph upkeep). Recruitment can suggest a hat, agents can change hats, and none are mandatory.

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
- **On failure,** the check can run automation (`simp`, `aesop`, `linarith`/`nlinarith`, `polyrith`, `positivity`, `norm_num`, `exact?`/`apply?`) and premise suggestions from library search on the failing goal, and returns what worked or came close (`automate=true`; off by default since S1, where it exhausted the 2 GiB workbench 14 of 14 times).
- **A published source rank, even `verified`, is never acceptance;** only the independent checker (§5.2) accepts.

**Literature and online sources** (brokered from the trusted plane, never from the sandbox, which stays offline):
- **Sources:**
  - `search_literature` covers arXiv, OpenAlex/Semantic Scholar, Mathlib/Physlib documentation, Lean community archives and general web search.
  - `fetch_source` retrieves a PDF or HTML page, converts it to text with source spans, and stores it as a source artifact with URL, time, hash and licence note.
- **Status of what's retrieved:**
  - Retrieved lemmas and proofs are **informal inputs**. They can be cited and autoformalized into nodes, which then earn source ranks from the statement check like any other node (§5.2).
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
  4. Optionally publish a Lean skeleton whose sorry lemmas become stub nodes (lean_check with stubs=true).
  5. Fill stubs by publishing their sources; submit the skeleton once none remain.
  6. Submit.
- **Library notes** (§3.2): one constitution line points to the shared facts about the Mathlib pin; they are agents' unverified reports, never instructions.
- The stagnation detector remains the loop guard. S1's technique skills (never loaded), check-ins (acted on 20% of the time) and stagnation nudges (never fired) were removed after S1.
- **Sketch-then-fill formalization** (the draft–sketch–prove pattern; optional, not a phase; S1 audit #21). A skeleton is any node whose published source imports stub nodes; `lean_check(stubs=true)` creates them, replacing S1's `lean_sketch` holes:
  1. An agent writes the proof with top-level `theorem X … := sorry` lemmas and checks it with `lean_check(node_id=…, stubs=true)`.
  2. If the skeleton checks as written and could be published as the node's module (a goal skeleton, the target's decomposition, needs only to compile), each sorry lemma that elaborates under the file's header, with auto-bound names off, becomes a `lemma` stub node the skeleton's node depends on (a dependency with the same Lean statement that is not abandoned is reused); one that needs the skeleton's own definitions stays in its text.
  3. The platform replaces each stub's lines with `import Commons.N…` and publishes that text as the node's module. Peers fill the stubs in parallel by publishing their sources.
  4. Once none remain (`rests_on.stubs`), the skeleton goes to independent checking.

  The blueprint follows the proof structure: each stub the skeleton imports is a `depends_on` edge of its node (an abandoned stub stays linked but is never left to fill).
- **Honesty rule.** No scaffold or hint is derived from a benchmark's hidden reference solution.

---

## 4. The society runtime

### 4.1 Persistent campaign

- **Replace the finite `ResearchTeamRunner`** with a **CampaignRuntime**: one durable Temporal workflow per society, using Continue-As-New.
- **What it owns:** the agent population, slot allocation, spawning and retiring agents, synthesis cadence and stopping.
- **Event-driven:** it reacts to node status changes, idle agents, budget changes, expired claims and timers.
- **Persistence.** It can pause and resume across days. Agents retire and are reincarnated through handoffs.
- **Keeps existing guarantees:** leases and fencing, idempotency, uncertain-operation handling and checkpoint recovery.

### 4.2 Launch

1. The root target passes the automated fidelity ensemble (§5.1).
2. An opening round of several F-tier agents independently writes distinct framings or approaches to the root. Each distinct approach becomes an approach node.
3. Every approach has one agent make a whole-root attempt from the start. Decomposition is never forced.

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

- Declared alternative routes at genuine choice points, with time boxes and the compile note, replace labs as the diversity mechanism (§2.3).
- The allocator keeps a minimum number of distinct approach families alive.
- Periodic **fresh-eyes reseeding**: new agents get the root plus *accepted* results only, without the discussion, so they can escape a shared blind spot.
- Referees come from a different model family where possible.
- Synthesis must preserve dissent and cite sources. A popular conjecture never becomes fact through repetition.

### 4.5 Society maintenance agents

- **Synthesizers** periodically write review articles per region of the graph: what is known, what is open, contradictions, and the objections that remain. Digests reference these.
- **Maintainers** merge duplicate nodes (keeping both histories), flag stale claims and orphaned tangents, and repair edges.

### 4.6 Hierarchical budgets

- The campaign budget is split into agent reservations; sub-budgets by graph region remain future work.
- Reserve-before-call accounting is unchanged.

### 4.7 Stopping

- **Root accepted:** an independent kernel receipt on the exact root statement triggers a bounded wrap-up (final synthesis, proof outline, write-up), then stop. This is already implemented as exact-target stop and bounded drain.
- **Other stops:** budget exhausted, operator stop, or a stagnation policy (no new complete or verified source and no new receipt within a configured spend). Each produces an honest report of the frontier, obstacles and partial results.
- **Idle stop (S1 remediation).** When every agent waits, nothing is admissible and no new event has arrived, the finite runner stops (`SOCIETY_IDLE`) instead of sleeping out the waits; the waits keep their tickets for a later run.

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

### 5.2 Node-level checks

The independent verifier is the only arbiter; referees check plans (S1 audit #17).

1. **Referee.** A plan or informal argument (an open approach, conjecture or lemma) gets independent referee reviews, cross-model where possible, with the Lean interface a skeleton imports. Verdicts are recorded and objections stay attached to the node; no verdict moves a status. A compiled node needs no referee (`REVIEW_UNNEEDED`). Fidelity reviews were removed after S1.
2. **Statement check.** A source published from the agent's workspace (`lean_check` with `node_id`) ranks `verified` only when the harness statement check passes: the kernel replays the file, the theorem's elaborated type equals the node statement's, and only standard axioms appear. Ranks are VM-attested and advisory.
3. **Independent acceptance**, using the existing Comparator + Lean + nanoda pipeline: axiom audit, no `sorry`, exact statement binding. A receipt on the target accepts the goal; the nodes its proof imported record the receipt (`in_verified_proof`) and stay open, since the verifier certifies the target's axioms, not each imported lemma's.
4. **Composition.** When dependencies are accepted, the consuming proof is rebuilt and re-checked against the consistent dependency closure (existing integration rule).

### 5.3 Formalization economy

- Formalization dominated the effort in the last run: the final proof was 606 lines.
- O-tier models run the Lean feedback loops. F-tier models handle statements, strategy and hard steps.
- Sketch-then-fill (§3.7), which is optional, turns an informal proof into a Lean skeleton whose sorry lemmas become stub nodes (`lean_check(stubs=true)`, replacing `lean_sketch` holes): a skeleton is any node whose published source imports stub nodes. The persistent Lean session (§3.6) cuts the cost of each iteration. Automation on a failing goal is opt-in (`automate=true`) since S1, where it exhausted the workbench's memory.
- Accepted nodes are immediately reusable library entries within the campaign. Retrieval is tested to actually return them; in the last run, lemma-bank searches returned nothing.
- Agents may introduce definitions in a campaign-local namespace. Definitions are nodes, checked by Lean elaboration like any other.
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
- Checkpoint saves are slim (a stored response keeps its billing and recovery fields plus a digest of the request echo), coalesced (4 per single-call turn and 3 + k for k calls, down from about 6.5 per turn) and one transaction each, and SQLite runs in WAL mode. Encoding checkpoints off the event loop is future work.
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

Hosted rate limits are held today by a per-process client-side TPM governor (`PHYSHARNESS_PROVIDER_TOKENS_PER_MINUTE`), set to about 90% of the org limit divided by the processes that share it; cross-process governance belongs to the model router (§6.1). S1's unthrottled agents needed about 0.55M TPM each.

---

## 7. Execution order (milestones)

Each milestone has exit evidence, and no milestone counts as wave qualification by itself. Paid runs need an explicit budget each time.

| # | Milestone | Main work | Exit evidence |
|---|---|---|---|
| **S0** | Land current work | Commit and PR the 2026-09-25 swarm hardening; merge `main` (the branch is 11 commits behind); refresh `IMPLEMENTATION_STATUS.md` | CI green; status docs current |
| **S1** | Commons v1, toolkit v1, tool consolidation | Nodes and edges on claims, status ladder, expiring claims, node threads, digests with urgent events, labs; referee and fidelity services. **Toolkit:** persistent Lean session with automation-on-failure, `lean_sketch` holes → nodes, `run_computation`, expanded numerics image, brokered literature access with per-campaign contamination policy, technique skills, check-ins and stagnation nudges. 63 → about 22 tools with adapters | Deterministic tests; then a live **8–16 agent** run on a hard known target versus a single agent and independent attempts at matched cost. Metrics: accepted root, less duplicated work than the last run, observed lemma reuse |
| **S1 remediation (2026-09-26)** | Audit remediation | Tier 0 fixes plus the society substrate (lemma store, relevance routing, event waits, library notes) replaced labs, the ladder, fidelity reviews, check-ins and count caps; 24 society tools | Evidence is deterministic tests; the paid A/B against the S1 society run (S-r2) needs a budget |
| **S2** | CampaignRuntime | Persistent society workflow, attention allocator with reserves, fresh-eyes reseeding, synthesizer and maintainer agents, hierarchical budgets, stagnation stop | A multi-session society (days, with pause/resume) that survives deliberate crashes and handoffs and continues without operator reassignment; **32 agents** |
| **S3** | Mixed-model routing | Model router; one self-hosted open-weight model on a Kubernetes GPU pool; tier budgets; escalation | Measured cost per accepted node by tier; at least 50% of agent-hours on self-hosted models with no drop in accepted-node rate at matched budget |
| **S4** | Kubernetes substrate at 128 | Agent, inference and verification planes on managed Kubernetes; workspace pool (E2B, with an Agent Sandbox + Kata trial); instrumentation | **Wave 8:** 72 hours at 128 active agents with injected failures, reconciled accounting, no lost accepted results |
| **S5** | Hundreds to 1,000 | Sharded commons, fair admission, provider-rate governance, verifier backpressure | **Wave 9:** 1,000 agents doing useful work, **only if S1–S4 show positive marginal value per added agent** |
| **S6** | Open-problem societies | Expert- or auto-reviewed open roots; publication review | **Wave 11:** can begin after S2 with small societies; sustained campaigns follow S4 |

**S1 progress (2026-09-25):** implemented; the final whole-branch review's findings are fixed. The commons, the toolkit and the 26-tool society profile ([S1 plan](docs/superpowers/plans/2026-09-25-s1-research-society.md), Tasks 1–10) sit behind an opt-in society policy. Evidence so far is deterministic tests only, including a no-model end-to-end simulation. The live 8–16 agent comparison has **not** run: it needs the approvals in [the S1 run plan](work/society-s1/RUN_PLAN.md). Those are the budget, the target, the models, the workbench v2 rebuild, the verifier bundle and the workspace provider. Deferred by design: node-level acceptance, the root fidelity ensemble, background jobs, general web search, the allocator and maintenance agents, and hierarchical budgets.

**S1 live comparison (2026-09-26):** every completed arm proved its target, but both targets were within one agent's reach. On the aperiodic target the society arm (S-r2, 6 roots, concurrency 8) took 29.7 min and $155.41, against 13.9 min and $31.97 for a single agent ([results](work/society-s1/results-2026-09-26/REPORT.md)). Its [audit](work/society-s1/audit-2026-09-26/AUDIT.md) set the S1 remediation's agenda (the row above).

The **first society target** should be a known result that is hard enough that a single agent does not finish it quickly (harder than the Duffing-network target), with its reference solution masked. That gives collaboration real work and gives us a correct answer to check against.

---

## 8. Mapping to the existing waves

| Society component | Waves it advances |
|---|---|
| Commons, blueprint, discourse | 4 (collaboration and memory), 5 (knowledge) |
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
- **Society health:** number of live approach families over time (herding), referee catch rate, stale-claim rate, and reuse by provenance (cross-branch imports of published modules, and their share of the accepted proof). The accepted proof's modules are those it inlined, used or not, so the share is an upper bound on reuse; confirm use by audit before claiming it. The fidelity-check failure rate applies to S1 arms only.
- **Matched-budget comparisons:** single agent vs independent attempts vs society. Policies are promoted only on reproducible gains.
- **Scaffolding and tools:** scaffolding on vs off at matched budget; Lean iterations per accepted node; automation hit rate; library-note and literature usage (skill usage in S1 arms) and whether cited sources contributed; contamination flags in benchmark runs.
- **Honest separation of evidence:** simulated vs mocked-provider vs live runs.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Graph clutter and duplication at scale | Maintainer agents, `duplicates` edges, claim expiry, digest budgets |
| Herding onto one approach | Relevance routing, message rate limit, declared alternative routes, fresh-eyes reseeding, cross-model referees |
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
