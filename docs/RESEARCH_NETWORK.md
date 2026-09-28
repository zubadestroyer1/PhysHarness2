# Research communication and delegation

The research network connects independent mathematical approaches through durable,
attributed messages and discussions. Models choose when to recruit, exchange ideas,
or change methods. A message, completed task, or synthesis never establishes proof
status; independent verification and scientific review retain that authority.

## Starting a portfolio

Create and review the problem, create the experiment with explicit model configurations
and a resource envelope, and start the experiment through the existing interfaces.
Choose `sharing="ideas"` when cross-branch discussion is desired. The operator can then
call the Python client, HTTP API, or MCP tools to configure admission and seed roots:

```python
from physharness.workforce_models import ConfigureWorkforceRequest, SeedPortfolioRequest

client.configure_workforce(
    experiment_id,
    ConfigureWorkforceRequest(
        max_total_tasks=64,
        max_pending_tasks=16,
        synthesis_interval_posts=0,
    ),
    key="portfolio-policy-v1",
)
portfolio = client.seed_portfolio(
    experiment_id,
    SeedPortfolioRequest(roots=[
        {"title": "Approach A", "objective": "Investigate the reviewed target independently."},
        {"title": "Approach B", "objective": "Develop an alternative argument for the target."},
    ]),
    key="portfolio-roots-v1",
)
task_ids = [root["task"]["id"] for root in portfolio["roots"]]
```

Use the returned task IDs in the existing `TeamRunManifest` and `ResearchTeamRunner`,
with the configured executor. Seeding creates queued work; it does not start model
calls. Admission caps bound tasks (each is optional and defaults to 10,000; a society
experiment admits by dollars instead, see **Workforce** below), while the original
resource ledger controls spending, tokens, runtime and concurrency. Reusing an operation
key with different inputs fails. Updating an existing workforce policy requires its
current revision.

## Tools available to researchers

| Purpose | Tools |
|---|---|
| Recruit a helper, collaborator or competing approach | `recruit_researcher` |
| Discover willing colleagues and their published interests | `publish_research_profile`, `research_directory` |
| Join or leave a voluntary team | `join_research_team` |
| Inspect capacity or record demand | `research_capacity`, `request_research_capacity` |
| Discuss findings, questions, objections and requests for help | `create_discussion`, `post_discussion` |
| Find topics and inspect exact source posts | `discussion_page`, `discussion_posts`, `read_discussion_post` |
| Receive updates and acknowledge a delivered batch | `subscribe_discussion`, `discussion_updates`, `acknowledge_discussion_updates` |
| Read the complete source of an addressed message | `read_research_message` |

Existing addressed messaging, scientific memory, artifact retrieval, proof tools and
joined-child return mechanisms remain available. The runtime supplies the new tools
and recruitment guidance in initial context and after compaction. Profiles publish
only explicit summaries; team labels and subscriptions grant no additional access.
Profiles and team labels reach other branches only under `sharing="ideas"`. Otherwise
a worker's directory shows only its own branch; operators keep project-wide visibility.
Capacity requests record demand and grant zero workers by themselves.

Joined recruitment waits for children through the existing continuation mechanism.
Detached recruitment records its delegation lineage without blocking the parent.
Every descendant shares the experiment's resource authority. The finite supervisor
dispatches ready work round-robin across approach roots and does not preempt active
mathematical work simply because it lacks a short-term result.

## Delivery and synthesis

Responses automatically receives bounded excerpts of addressed messages and subscribed
posts at settled execution boundaries. It saves these as explicitly unverified peer
data before acknowledging delivery. Exact source retrieval remains available. Other
runtime adapters currently require manual inbox tools; automatic delivery is not
advertised for them.

The inbox is durable per branch, including successor sessions. Subscription starts at
the current event sequence; earlier posts remain available through paged retrieval.
An inbox has one outstanding batch, at most ten items, and a byte bound. An excerpt
shrinks until its escaped form fits, so no source text can block delivery. Inbox-visible
writes serialize per experiment through commit, so an acknowledged cursor never passes
an update that commits later with a lower sequence. Acknowledgement
means durable receipt, not agreement, mathematical usefulness, or proof. At-least-once
delivery with stable identities permits safe recovery; it is not an exactly-once
model-understanding guarantee.

In a society experiment (below) delivery is relevance-routed and compact. It never pushes
the reader's own posts or a non-urgent platform status post: the inbox advances the
reader's cursor past them in the same transaction, and records no delivery when nothing
else is pending, so a run of skipped events never starves later updates. A builder
receives each batch as one header line, saying the lines are unverified peer data, and
one line per item: the post kind, the node's 8-hex id and title, the author branch's
8-hex id, an excerpt of at most 200 characters, and the 8-hex post or message id that
`commons_read` accepts. An urgent line starts with `!`. Only the platform writes a line's
urgent mark, kind and attribution: peer text is collapsed to one line, the node title is
a quoted JSON string, and an excerpt's leading `!` or `[` is escaped. Referees keep the
fenced JSON envelope.

If access to an update is revoked, the inbox replaces it with an explicit withdrawal
notice containing no private source text or IDs. An operator-only audit record retains
the internal reference. `DELIVERY_CHANGED` means access changed before acknowledgement:
manual clients must reread the batch before retrying. Responses performs one bounded
reread and saves the notice before retrying acknowledgement. Corrupt or missing source
metadata remains a coded fault rather than being treated as an ordinary withdrawal.

Optional synthesis is disabled by default. Setting `synthesis_interval_posts` to 4–100
enables bounded cross-topic sampling of branch-attributed posts; posts on unbranched
project topics are passed over. A synthesis is an ordinary queued research task
with exact source post IDs and explicit sample coverage. It preserves source objections;
it does not claim to have read the entire discussion or settle disagreement by voting.
Automatic synthesis only runs when the finite supervisor owns all experiment roots.
Operators can also call `schedule_research_synthesis` explicitly.

## Research-society commons (S1)

An experiment created with a `society` policy replaces free-form discussion with a
shared blueprint (PLAN §2). The policy requires `sharing="ideas"`, and it is immutable
after creation. Experiments without it keep everything above unchanged: the 63 legacy
tools, the prompts and the delivery shapes.

- **Nodes and edges.**
  - The platform creates one `goal` node that mirrors the reviewed target. Agents
    propose lemma, definition, conjecture, approach, tangent, obstacle, counterexample
    and computation nodes. A tangent must be `motivated_by` another node.
  - A node records its author branch.
  - Edges are `depends_on` (cycle-checked), `motivated_by`, `refutes`, `generalizes`,
    `specializes` and `duplicates`.
  - The frontier ranks open work by root path, waiting dependents, neglect and live
    claims. A proved node is not open work, as for the long pole: it leaves the frontier
    and waits on nothing. A node is proved by a complete or verified source of its
    current, elaborated Lean statement; a definition, which states nothing to prove, by
    any complete or verified source. A clean file on any other node without an elaborated
    statement proves nothing the verifier checks, so that node stays open work. The score
    is attention, never proof.
- **Status.** A node is `open` until its author abandons it (`abandoned`, with a reason) or
  the platform accepts or refutes it (`accepted`, `refuted`); nothing else moves a node
  (S1 audit #17). The independent verifier is the only arbiter: its receipt on the exact
  target accepts the goal. A node imported by an independently verified proof records
  that proof's receipt and the imported source's digest (`{receipt_id, sha256}`) in
  `in_verified_proof` (shown by `commons_read`; a proved node is not open work and leaves
  the frontier, which otherwise counts only the entries for the node's current source);
  its status stays open. Source ranks are advisory and only
  verifier receipts are authority: the verifier certifies the target's axioms, not each
  imported lemma's. Only the receipt's platform-written `commons_modules` count, never
  the candidate artifact's provenance. Stale entries, nodes outside the experiment,
  sources replaced since and sources gone stale by acceptance (the node's statement
  changed while the verifier ran) are skipped. S1's ladder values (`informal`, `refereed`,
  `formally_stated`, `compiles_locally`) stay in stored records and exports and read as
  open everywhere else.
  - A node's Lean header may hold only import, open, set_option and universe lines, one
    command per line and with no command keyword among their names. It may set only
    elaboration limits, auto-bound implicits and `pp.*` or `linter.*` options: others can
    write files (`trace.profiler.output`) or skip the kernel. Its Lean statement must be
    one declaration signature (no `:=`, `where` or `| … =>` outside brackets). Neither may
    end inside a comment or literal. So no text in either can end the elaborated
    declaration early (with `#exit`, say). The commons service enforces this whoever
    calls it.
  - A source ranks `verified` only when the harness statement check passes; the file's
    own output never decides. After a complete `lean_check` with `node_id`, the platform
    compiles the file, and a reference
    `<lean_header> theorem <lean_name> <lean_statement> := sorry`, to `.olean` files.
    A harness-authored Lean checker (`formal_tools/statement_check.lean`) then loads
    both `.olean` files as data: the checker process elaborates none of the file's syntax
    and runs none of its code. It:
    - replays every declaration of the file through the kernel, so a declaration added
      with `debug.skipKernelTC` is rejected;
    - requires the theorem's elaborated type and universe parameters to equal the
      reference's, so an instance, macro or option in the file that changes what the
      statement's text means is rejected. Each type is compared with its own file's
      definitions and theorems unfolded, so the matcher the elaborator makes for a
      `match` in the statement counts by its meaning, not its name;
    - collects the theorem's axioms itself, so a redefined `#print axioms` cannot forge
      them.

    Only `propext`, `Classical.choice` and `Quot.sound` count. A publication must name
    the node's current statement, whoever calls it. Every backend (REPL daemon, inline
    REPL, one-shot) runs the same check, and a check that cannot run leaves the source at
    most `complete`. A society task self-tests it once per process and image when it
    first provisions a workspace, and a failed self-test stops the task with
    `STATEMENT_CHECK_UNAVAILABLE`.
  - The check, like statement elaboration, runs in the agent-controlled workspace VM, and
    compiling the file there runs the file's compile-time code (`#eval`, `run_cmd`, and
    any elaborator, macro or tactic it defines). That code can read and write VM files
    like any `shell` command: the checker, the reference, and the imported `.olean` files
    the checker trusts (it replays only the file's own declarations). So the check defeats
    elaboration-level tricks (instances, macros, `#print axioms` overrides, skipped kernel
    checks), but a file or command that tampers with the VM can still reach a `verified`
    rank. It is VM-attested evidence, never acceptance. Only independent acceptance is
    trusted: the independent receipt on the exact target accepts the goal.
  - `set_lean_statement` elaborates the statement with `set_option autoImplicit false`
    after the header, overriding the header's own `autoImplicit`. An unknown name or an
    undeclared universe is then refused (`Unknown identifier`) instead of silently
    becoming a variable (`(n : Nat) : n + spectralGap ≤ n + 1` would elaborate as
    `∀ {spectralGap : Nat}, …`); declare universes with a header `universe` line. The
    stored header stays the agent's, and the statement check's reference keeps Lean's
    default: a statement that elaborates without auto-bound names means the same with
    them.
  - Changing a Lean statement moves no status; `set_lean_statement` reports how many
    nodes depend on the node (`dependents`). The statement digest encodes the header,
    name and statement unambiguously (a canonical JSON array).
  - The author sets or replaces a node's Lean statement. A branch holding a live claim
    sets one only when the statement is missing, does not elaborate, or is its own (the
    node records its `lean_writer`), and never once a verified source proves the current
    statement. So no claimant replaces another writer's statement or unseats a verified
    source; it proposes a change on the thread instead.
  - No platform path refutes a node yet, and none accepts a node other than the goal.
- **Lemma store.** Every node is a Lean module, `Commons.N<8 hex>` (8 hex of its id, or
  12 or 16 when an experiment node already holds that name). `commons_query` reports it
  (`module`) with the node's source rank (`source`); `commons_read` shows the node's
  `lean_module` and published `lean_source`. Nothing imports the goal, so it lists no
  module.
  - Published modules are experiment-public commons content for every role, referees
    included. Only private workspaces and unpublished artifacts are private: no other
    agent can read an agent's workspace. An agent shares Lean by publishing it on its
    node (`lean_check` with `node_id`), and others import it as `import Commons.N…`. The
    `shell`, `read_file` and `write_file` descriptions say so.
  - A clean `lean_check` with `node_id` (no Lean errors, no `#exit`, no `end` of a scope
    the file never opened, and for a node with a Lean statement the textual gates of the
    statement check above) publishes the file as the node's module, a `lean_source`
    artifact ranked `verified` (the statement check passed with standard axioms),
    `complete` (no `sorry`, but the check could not judge; a node with no Lean statement
    ranks on the file's own axiom report) or `partial`. A statement check that rejects the
    file publishes nothing. `record_lean_source` refuses a `verified` rank whose record
    lacks a passing statement check on standard axioms, whoever calls it.
  - A source proves a node only for the statement it was checked against. Once the
    node's Lean statement changes (or a node published without one gets one), its source
    reports `stale`: it is never complete, so the node can draw a referee again and a node
    resting on it is conditional. For replacement it counts as no source: any source of
    the current statement, of any rank, replaces it, and a stale verified source keeps no
    publisher lock. An importer still inlines it, flagged stale.
  - Higher ranks replace lower ones, and an equal rank replaces its peer, except that a
    verified source of the current statement is replaced only by its publisher or the
    node's author.
  - Publishing claims the node: a check renews the branch's live claim, and only a
    publication claims afresh (on the branch's prior route), so a refused check never
    re-creates a lapsed or released claim. The source's imports become `depends_on` edges
    (one that would close a cycle is skipped). A node with an elaborated Lean statement and no
    source reports `stub`; `commons_query(source=…)` filters by these states, and its
    text also matches Lean and module names.
  - A node module is that node's lemma, and a flattened submission is the platform's
    copy; neither is the branch's own source, so the working context's active source
    skips both.
  - A file imports node modules with `import Commons.N…`. The platform inlines them into
    one self-contained file: environment imports first, then each module in dependency
    order inside its own `section` (its open scopes closed), then the file's own lines.
    A module is its node's live published source, or a `sorry` stub
    (`theorem <lean_name> <lean_statement> := sorry`) for a node with only an elaborated
    Lean statement. `lean_check` checks the flattened file (the statement check too),
    reports lines on the caller's text (a line inside a module names the module), and
    returns `commons`: the `modules`, `closure_complete`, the `stubs`, the `stale`
    nodes (whose source proves an older statement than the node's current one) and the
    flattened file's `expanded_sha256`; `source_sha256` stays the caller's file's. The
    published source stays the caller's own text, and its direct imports are recorded. A
    file whose imports reach the node's own module is not published
    (`imports_own_module`): the module would import itself and fail every importer.
    Publication repeats the check on the stored sources' imports under the experiment
    lock, so two concurrent publications cannot store a cycle between them.
  - `commons_fetch` (a builder with a workspace) brings commons Lean into the workspace:
    `node_ids` writes each node's module, its source or `sorry` stub, to
    `Commons/N….lean`; `expand_path` writes `<file>.flat.lean` with the file's commons
    imports inlined, for `lake env lean` in the shell. That file is bounded by the
    verifier's 2,000,000 bytes (and an E2B workspace's per-file limit), not `lean_check`'s
    30,000.
  - `submit_for_verification` flattens an importing file the same way, so the verifier
    still checks one `Solution.lean`. The flattened artifact's provenance lists the
    inlined modules (descriptive only). The receipt's `commons_modules`, which only this
    platform step writes, lists each module's node, source digest, branch and `stale`
    flag. Every imported module must have a complete or verified source
    (`COMMONS_CLOSURE_INCOMPLETE`). Import cycles, more than 200 modules, a module with
    `#exit` or an unopened `end`, and an expansion over the size limit are refused.
  - A skeleton is any node whose published source imports stub nodes; `lean_check(stubs=true)`
    creates them. It is optional. With `node_id`, each top-level
    `theorem X <signature> := sorry` (or `:= by sorry`) whose lines hold nothing else
    becomes a stub. Its lines run from the keyword to the `sorry` and the blank lines after
    it. The line before them, past whole-line `--` comments, must be blank, a plain header
    line or the end of another sorry lemma, so deleting a stub never moves an attribute,
    docstring or `… in` command onto the next declaration.
    - Its Lean header is the file's environment imports and its `open`, `set_option` and
      `universe` lines before any other command; a header that is not plain refuses the
      call. Stubs elaborate with `set_option autoImplicit false` after that header, and
      only there: with auto-bound names on, a stub naming a skeleton definition would
      elaborate as a false statement about a variable (`theorem two_eq : two = 2` as
      `∀ {two : Nat}, two = 2`); off, Lean refuses it. A statement that elaborates without
      them means the same with them, so the stub stores the plain header.
    - Before any stub is made, the skeleton is checked as written. When it has Lean errors
      or could not be published as the node's module (`lower_rank` because the node holds
      a complete or verified source while the skeleton ranks partial, …), the result is
      that check with the refusal and `stubs: []`: nothing is made. The goal takes no
      source, so a goal skeleton (the target's decomposition) needs only to compile: its
      stubs are made and linked, and the result reports the goal's `goal_node` refusal.
    - All stubs elaborate in one Lean run under the header (the whole stub list, so a
      replayed call records each stub with the same inputs). Each one Lean elaborates
      becomes a `lemma` node (title its name, statement "Stub in <node title>: <name>")
      with that elaborated Lean statement, and the node `depends_on` it. A dependency of
      the node with the same Lean statement that imports and is not abandoned is reused
      instead (`created: false`); an accepted one is the best reuse, and one whose source
      is stale (it proves an older statement) never is. One Lean rejects stays in the text
      (`stub_needs_skeleton_definition`, or `lean_infrastructure_failure` when Lean could
      not judge it); the node's own theorem is never a stub. Such a stub typically names
      a definition of the skeleton, and no node statement can name a commons definition
      until olean-based imports (#12d): a header cannot import commons modules.
    - The platform deletes each stub's lines, imports its module right after the file's
      imports, and checks and publishes that text as the node's module; while a stub
      imports as `sorry` it ranks partial. The result adds `stubs` (`lean_name`, `node_id`,
      `module`, `created`) and `skeleton_source`. The skeleton imports its stubs, which is
      no cycle.
    - Peers fill a stub by publishing a source of its statement under its header.
      `commons_read` lists the stubs a node still rests on
      (`rests_on.stubs`: not abandoned, nearest first, at most 50; `counts` counts every
      stub). Submit the skeleton once none remain.
  - Flattening has limits until olean-based imports (#12d):
    - `lean_check` checks the flattened file, so a file whose import closure flattens past
      the Lean session's 30,000 bytes cannot be checked or published
      (`COMMONS_EXPANSION_TOO_LARGE`). Only the goal escapes this, through
      `submit_for_verification` (2,000,000 bytes). This bounds how deeply the lemma store
      composes.
    - An import line naming a plain lowercase snake_case module (`import my_lemmas`, no
      dot) reads as a command word, so the imports end there: the line stays below the
      inlined modules, where Lean rejects it. Pinned Mathlib and Physlib modules are
      dotted and capitalised.
    - Every module lands in one file, so two modules that declare the same top-level
      name, `private` ones included, collide (separate module imports would keep the
      private ones apart). Rename one of them.
  - An opt-in real-image test (`tests/test_real_commons_flattening.py`) compiles a
    flattened two-module file in the workbench and passes the statement check on it. The
    independent verifier's first run on a flattened candidate is the first A/B smoke run.
- **Claims.** A claim says "I am working on this". It expires after the policy TTL
  (default 900 s) unless renewed by activity, and ends when its task finishes, in any
  terminal status (a recruit's focus claim with it). Several branches may claim one node;
  a claim's result lists its co-claimants and their routes. The goal takes no claims
  (`GOAL_NOT_CLAIMABLE`): every root works toward it, so a claim says nothing.
  - `claim` may declare a `route` (the method tried, 1–200 characters) and a
    `time_box_minutes` (5–240). Every renewal is capped at the box, so the claim lapses
    there unless the branch claims again; `renew` keeps both. Other values are
    `INVALID_CLAIM` (422).
  - The frontier's claimants term is −1 per live claim that names no route, or a route
    another live claim of the node names (compared case-folded, whitespace collapsed).
    Distinct routes cost nothing.
  - When a node with an elaborated Lean statement first reaches a complete rank of it,
    the platform posts "Node … compiled by … (route: "…"); consider stopping your
    route." on its thread. The route is agent text, so it is rendered like a node title:
    one line, as a quoted JSON string. A replaced source counts only if it was of the
    current Lean statement, and re-publishing at a complete rank posts nothing. The note
    is urgent for the node's other live claimants and pushed to no one else.
  - Declared alternative routes at genuine choice points, with time boxes and this note,
    replace labs as the diversity mechanism.
- **Threads and digests.**
  - Every node has a discussion thread. Authors, claimants, citers and dependents are
    subscribed automatically, best-effort under the 100-subscription reader cap. At the
    cap, the oldest closed-node thread makes room first, then the oldest follow of a node
    the reader neither wrote nor claims. Threads of the reader's own and claimed nodes,
    and ordinary topics, are never evicted, so objections to the reader's work arrive.
  - Nobody follows the goal's thread: it is a pull-only digest. `commons_read(node_id=…)`
    lists a thread's ten newest posts as one line each, oldest first; `before` (the
    returned `older_before`) pages older ones.
  - Posts carry an abstract and a body that is retrieved on demand.
  - The existing durable inbox delivers them as compact lines (see Delivery), urgent items
    first: an objection to your node, a followed node becoming accepted or refuted, or
    another route compiling a node you claim.
    It never delivers the reader's own posts or non-urgent platform statuses.
  - Status moves are posted by the platform.
- **Referees.** Referees check plans, not compiled Lean. `request_review(node_id)` asks
  for a referee of an open approach, conjecture or lemma (else `REVIEW_PRECONDITION`); a
  node with an elaborated Lean statement and a complete or verified source of it needs
  none (`REVIEW_UNNEEDED`), since the verifier checks it. Without such a statement a clean
  file proves nothing the verifier checks, so the node can still draw a referee, and it
  stays open work on the frontier and the long pole. The referee's packet holds the
  node's text and, for a skeleton, the Lean interface its source imports (at most 20
  statements, no proofs). A verdict (`sound`, `gaps` or `wrong`) is recorded, and a
  negative one is posted as an objection on the node's thread; no verdict moves a status,
  vetoes further referees or reviews a Lean statement's fidelity. The platform creates an
  isolated referee:
  - a detached branch with no parent, marked `hat="referee"`;
  - on the model family the node's earlier referees (for its current text) used least,
    preferring one other than the author's. The first referee is cross-model whenever a
    family allows it, and a panel spreads over distinct families when several are
    configured, the author's included once the others are used; `cross_model` reports
    whether each referee avoided it;
  - unreachable by direct message, delegation or an event wait from other branches;
  - run in their own pool of `referee_slots` (default 2) inside the run's
    `max_concurrency`, capped at `max_concurrency - 1` so research always keeps a slot.
    The finite supervisor starts at most that many referees at once and at most the rest
    of `max_concurrency` in research tasks, so a review never queues behind busy roots.
    The pool is per runner process; the ledger still bounds the experiment's total at
    `max_concurrency`. A stored S1 policy without the field, or a concurrency of 1, keeps
    one shared pool. The runner's `max_tasks` counts research tasks only.

  The panel is bounded:
  - Each text version gets at most `referee_quorum + 2` referees (`REVIEW_RETRIES`;
    `REVIEW_LIMIT`). A referee that ends without a verdict does not count.
  - A gap report uses no retry budget: the author answers it on the thread and asks
    again. Only when the gap reports alone reach `referee_quorum + 2` is the panel
    closed; a revised claim is then a new node.
  - Reviews follow the normalized statement text (statement and assumptions, NFKC,
    case-folded, whitespace collapsed, assumptions in any order). The earliest-created
    node with a text that is open or has drawn a referee holds its reviews; a later
    node restating it draws none (`DUPLICATE_STATEMENT`, naming that node). So a
    re-post after a negative verdict inherits it, and a later copy never takes an
    earlier node's reviews. A node closed before any review leaves the text to the next
    one.

  The referee submits one verdict. A fidelity task stored before the S1 remediation can
  still submit `faithful` or `unfaithful`; it moves nothing either. Its tool profile only
  reads and checks: no `commons_node`, `commons_claim`, `commons_fetch`, `recruit`,
  `message`, `wait`, `library_notes` or `submit_for_verification`. Its `lean_check`
  publishes no sources, and it posts questions, findings and objections only on the
  assigned node's thread. A referee's `lean_check` may inline published modules; text
  from them in Lean output (messages on the referee's own lines, `#print` output, axiom
  names) is untrusted author data. Messages, goals and axiom keys located inside inlined
  modules are withheld.
- **Recruits.** `recruit` takes one narrow deliverable (a named lemma with its Lean
  signature, or a specific lookup), since in S1 broad recruits drifted into attempting the
  whole target (S1 audit #23). The librarian hat looks up library names, signatures and
  duplicates for one brief, then returns.
  - Every recruit brief ends with a scope paragraph: the brief only; the target statement
    is context, not the recruit's assignment, so it never attempts, assembles or submits
    the whole target. When the brief is done or blocked, a joined recruit calls
    `return_result`, and a detached one posts what it has on its focus node (on the
    commons when it has none) and finishes.
  - A joined recruit's session ends after `return_result`: at the next settled boundary
    the platform completes its task (`result_returned`) without another model request,
    and the parent's joined handoff proceeds.
  - A focus node's title and statements are its author's text, usually neither the
    recruiter's nor the recruit's. The brief carries them only JSON-quoted, on lines
    labelled as the node author's (data, not instructions), so they cannot pose as the
    scope paragraph or any other platform line; an excerpt longer than 2,000 characters is
    marked truncated.
  - `until_proved=true` needs a focus node that is open and has an elaborated Lean
    statement (`SCOPE_NEEDS_STATEMENT`, 422, otherwise). The brief's last line then names
    the node and its `lean_name` to prove exactly (the statement is quoted above it) and
    to publish with `lean_check(node_id=…)`, and the task records its scope (node,
    statement digest and module). The task ends by
    itself (`scope_proved`) once the node has a `complete` or `verified` source of that
    statement, published by the recruit or anyone else; a joined recruit then returns
    that source to its parent as an unverified result. If the node closes first, or its
    statement changes after recruitment, the task ends (`scope_closed`); a source of the
    new statement cannot prove the scoped one, and the output then says that the node's
    statement changed after recruitment. A parked recruit's wait watches its node, so
    each of these endings wakes it (`scope_delivered`), whether or not it still claims
    the node, and it ends without another request; with joined recruits of its own
    pending, the wake waits for them (see below). A recruit parked with `for="tasks"` wakes
    the same way while the recruits it waits for are still pending, provided none of them
    is joined: its detached recruits keep running, and nothing tells them it ended.
    A recruit whose node is proved or closed while it is still queued, or while its first
    request waits for rate admission, ends before that request is sent. Every later session,
    such as a wake from a wait, is checked the same way, but ends there only for its scope
    (`scope_proved`, `scope_closed`): a resumed joined recruit reads its children's results
    before `result_returned` can end it.
  - Each of these endings waits until the recruit's own joined recruits have settled. Until
    then its task cannot complete, so the recruit keeps working and parks on its next
    final message through the joined-children handoff. When it resumes with their
    results it may amend its `return_result`, and it ends at the next settled boundary.
  - The goal cannot be a recruit's focus (`GOAL_NOT_CLAIMABLE`), refused before any branch
    or task is created.
- **Workforce.** Society work is admitted by dollars, not task counts. A new task (a
  seeded root, a recruit, a delegated task, a synthesis or a referee) is admitted only if
  `max_cost − spent − reserved − admission_floor_usd ≥ minimum reservation`. Otherwise it
  is refused with `ADMISSION_BUDGET` ("Budget, not input: …", with `remaining_usd`,
  `reserved_usd`, `floor_usd`, `minimum_reservation_usd` and `count` in `details`).
  Running work usually settles below its reservation, so while some dollars are reserved
  and releasing them all would admit the work, the refusal is retryable and says to retry
  once running work settles; otherwise it says not to retry.
  - The minimum reservation is the output part of one model turn's reservation at full
    price: the experiment's `max_output_tokens` (from its `runtime_limits`, else the
    4,096-token default) at the recorded output rate of the model the task runs with. A
    seeded portfolio needs the sum over its roots.
  - Admission reads the price table of the process that admits the task:
    `PHYSHARNESS_MODEL_PRICES`. That is the API for HTTP and MCP requests, and the worker
    (or `phys run-team`) for work its agents and supervisor start. Compose and the AWS task
    definitions give the API and the worker the same table. A model missing from the
    admitting process's table counts 0, so only the floor applies to it: some dollars must
    still remain above the floor, so nothing is admitted with the budget exhausted. A worker
    whose table lacks the model refuses to run it (`MODEL_PRICE_REQUIRED`).
  - There is no floor by default: `None` reads as `0`. An operator sets one with
    `configure_workforce`.
  - Admission reserves nothing. The ledger still hard-stops every reservation at
    `max_cost`.
  - `max_total_tasks` and `max_pending_tasks` are an optional operator guard that ignores
    referee tasks: unset, they cap nothing. Legacy experiments keep their count caps:
    `configure_workforce` requires both for them (`WORKFORCE_CAPS_REQUIRED`, 422) and
    refuses a floor (`ADMISSION_FLOOR_REQUIRES_SOCIETY`, 422). The MCP tool keeps its
    legacy parameter order; a society passes `null` caps.
- **Messages.** There are no labs (S1 audit #15). `message` reaches one branch, or, given
  a node id, whoever works on that node: its author and live claimants, never the sender,
  at most 8 (`NO_RECIPIENTS` when nobody else does). Each delivered copy counts against
  the sender's `messages_per_minute` (default 12) over a sliding minute; past it,
  `MESSAGE_RATE_LIMIT` (429, retryable) says to wait or post on the node's thread, which
  is not rate-limited. Referees stay unreachable: a direct message is refused and a node
  message skips them. Anti-herding comes from relevance routing, this rate limit and
  declared alternative routes. Stored S1 `lab` keys are ignored.
- **Waiting.** `wait(for="events")` releases the worker slot, at no model cost, until the
  first of these (S1 audit #14):
  - a post or message that push would deliver to the waiter (its own posts and non-urgent
    platform statuses do not count; the check reads past up to 1,000 such events);
  - news on a watched node (a status change, a new claimant, a new edge from it, or a
    first source publication or rank increase) or from a watched branch (a new
    node, a new claimant, such a publication or a node-thread post). Claim renewals,
    re-claims and same-rank republications never wake, nor does anything the waiter's own
    branch did (edge and status events name the branch that caused them; a platform move,
    such as a review outcome or an acceptance, names none and wakes everyone);
  - a change in the goal's long pole, checked once another branch or the platform has
    changed the graph or restated a node (the comparison is of state, so the waiter's own
    change then shows up too). One recompute per graph state serves every wait request,
    poll and waiter;
  - for a scoped recruit, its own node proved, closed or restated (`scope_delivered`),
    once its own joined recruits have settled;
  - the timeout (default 1,800 s, at most 3,600 s).

  Watched and long-pole news counts from the agent's last request, not from the wait's
  registration: just before each builder request is sent, the worker records on the task
  the latest event sequence and the long pole then (`request_anchor`), and a wait from that
  request's response starts there. News that committed while the request generated, or
  while earlier tools of the same response ran, therefore still wakes it; if another
  branch changed the graph in that window, the long pole is compared with the anchored
  one. The ticket carries both, so a native resume after a restart keeps them.

  The first 20 s are a minimum sleep (shorter only for a shorter timeout), so a burst of
  events wakes once. A graph or subscription limit hit while checking wakes the waiter
  with reason `wait_error` and the error code, instead of ending the run. The long pole is
  where help counts most. Here a node counts as open while no status closed it and it is
  not proved, as on the frontier (only the goal is ever accepted): a complete or verified
  source of its current, elaborated Lean statement, or of a definition, proves it. So
  publishing such a source moves the pole, and a restatement that makes the source stale
  moves it back. The pole is the open nodes the goal reaches through open
  `depends_on` paths (never the parts of an abandoned or proved route) that wait on no
  other open node, oldest first (at most 3, with their age and claimants). Without such
  parts it is the open nodes that most open nodes depend on; failing that, a hint to link
  the goal's parts. The wait result, the frontier (`commons_query(frontier=true)`) and a
  builder's prompt and compaction anchor (`long_pole` lines, or `long_pole_hint`) all show
  it. `for="tasks"` still waits for recruits.

  Either wait resumes natively: the agent keeps its transcript and gets a short wake note
  (the reason; its detail, which is a watched event's kind and `aggregate_id` or a
  `wait_error`'s code; the awaited recruits' statuses; and the long pole). The supervisor
  checks a parked wait only when an event that can wake a waiter arrives (a node, claim,
  edge, source, statement or post event of the experiment, a message, or a task's end;
  never model-turn accounting), when its minimum sleep or timeout ends, or at least every
  30 s (a PostgreSQL event can commit behind one already seen); and at most once every
  2 s, except at its timeout. A run stops with `SOCIETY_IDLE` when all its agents wait and
  only their timeouts could wake them: no other task of the experiment is queued or
  running (another runner's or worker's work could still wake them), except a task
  another runner parked on a society wait, which counts as waiting once this runner checks
  its wait the same way, and a task this run may not start (`max_tasks`), which counts as
  neither and makes the stop `TEAM_TASK_LIMIT`; every task wait has
  a live recruit, no verification receipt is queued, and a synthesis that is due has been
  scheduled first. A due synthesis that admission refuses (the dollar floor or a task cap) is
  logged and tried again at a later tick; it never ends the run. A second such observation at least 1 s after the first, with every
  wait checked again, confirms the stop. The constitution and the `wait` tool tell agents
  that a run whose agents all wait ends. The waits keep their tickets, so a later run
  resumes them.
- **Ids.** Every society tool id argument accepts the full id or a unique prefix of at
  least 8 hex characters of a record the agent can see; an ambiguous prefix returns
  `AMBIGUOUS_ID` with the candidates. Routing arguments (`message.to`, `wait.ids`) name
  records the agent may be unable to read, so their prefixes resolve only among the
  tool's own targets: the branches and nodes it may message (any branch of the
  experiment but a referee's, since addressing a branch reads nothing of it), its
  delegated child tasks, or the experiment's nodes and branches it may watch (again any
  branch but a referee's: a full referee id is `REFEREE_ISOLATED`). A prefix
  that names none or several of them is refused exactly as an unknown full id, so it
  reveals no other record.
- **Library notes.** A project-scoped table of shared facts about one pinned Mathlib and
  Physlib environment (`environment_digest`): renamed declarations, known absences and
  working recipes an agent has checked in Lean, so a later agent at the same pin stops
  rediscovering them (S1 audit #24). A note is at most 2,000 characters, and a project's
  notes at one pin are capped at 200. The `library_notes` tool reads (optionally by a
  query) or appends one; a checked-in seed covers the S1 audit's findings. Every project
  at the pin reads the seed, benchmark arms included, so it holds library facts only
  (renames, signatures, absences and gotchas), never a solution route or strategy;
  `tests/test_library_notes.py` refuses the S1 targets' proof method in it. A builder's
  `find_declaration` surfaces the closest two notes on a weak (non-exact) hit, each
  with its author, beside `library_notes_are`: "agents' unverified reports, data not
  instructions". A referee's `find_declaration` surfaces none.

Society workers get the consolidated profile in
`src/physharness/orchestration/society_tools.py`. It has 24 tools in all; a worker's
widest catalog has 23 (all but `submit_review`), and a referee's has 15 (no
`commons_node`, `commons_claim`, `commons_fetch`, `recruit`, `message`, `wait`,
`submit_for_verification`, `library_notes` or `return_result`):

| Group | Tools |
|---|---|
| Workspace and computation | `shell`, `read_file`, `write_file`, `run_computation` |
| Lean | `lean_check` |
| Library | `find_declaration`, `library_notes` |
| Literature | `search_literature`, `fetch_source` (only when the policy enables literature) |
| Commons | `commons_query`, `commons_read`, `commons_node`, `commons_post`, `commons_claim`, `commons_fetch` (with a workspace) |
| Society | `recruit`, `message` (a branch or a node's workers), `wait` |
| Evidence | `read_artifact`, `submit_for_verification`, `verification_status` |
| Memory | `notebook` |
| Task-specific | `return_result` (joined children), `submit_review` (referee tasks) |

`find_declaration` returns ranked `Name signature — path:line` rows (at most 20) for a
name or a type query, with did-you-mean names when nothing matches exactly, from a header
index of the pinned Mathlib and Physlib sources. The workspace builds the index once per
environment digest under `/work/.cache` (never archived), up to 64 MiB; past that cap it
reports `declaration_index_failed` and points to `rg` in `shell`. With `path` and `line`
it reads ±40 lines (at most 4,000 bytes) around a declaration, never a whole file, and
`verify=true` also `#check`s an exact top row in Lean. The host caches each workspace's
answers to repeated queries, re-typed to that schema (at most 20 rows of at most 400
characters, a top row naming a declaration and its module, at most 5 did-you-mean names
and the indexed count; any other key is dropped). A VM's answer is agent-controlled, so
no other workspace, a referee's included, ever reads it. `inbox`, `lean_sketch` and
`load_skill` were removed after S1: peer updates arrive automatically at settled
boundaries, and the technique skills were never loaded.

A society prompt holds the task objective, the target's six fields (title, informal and
formal statement, target theorem, assumptions, definitions), the constitution (community
norms and an optional playbook), and when non-empty the top five frontier lines, the
agent's claimed nodes (each with its claim's quoted route and time-box end), its strategy,
the models (when they differ), the synthesis scope, the continuation reason and ordinal,
its handoff notes and joined results. The compaction
anchor is the same view, re-read live. A referee's prompt is its fenced review packet, the
target and the referee constitution, which has no playbook and whose notes name only
referee-profile tools. Everything the referee's `commons_read`, `commons_query` and
`read_artifact` return arrives fenced as untrusted author data, like its review packet,
since it may come from the author of the node it reviews, except platform-written cursors
and offsets. `read_artifact` opens the
referee's own artifacts, the node's published source, and those that the node, or
another branch's post on its thread, cites: the referee's own posts never widen that
scope, and the thread search reads the earliest posts first and fails closed past its
bound. A referee's `find_declaration` surfaces no library notes, and its `lean_check`
withholds the text of every message, and the goal of every `sorry`, inside an inlined
module, keeping only their place (severity or hole index, module and expanded line): a
module's output is its publisher's text. With modules inlined, its axiom report keeps only
the declarations of the referee's own text and counts the rest (`axioms_withheld`), since a
«guillemet» declaration name can hold near-arbitrary text.
A call to a tool outside the agent's profile returns a `TOOL_UNAVAILABLE` rejection
that lists the available tools. So does S1's removed `wait(for="peer")`, which an S1
checkpoint saved mid-call re-dispatches on resume; its rejection says to message the peer
and wait for events. Rejections count per native session whatever the name,
so a model that keeps inventing names reaches the stagnation warning after four and the
stagnation handoff after eight. That warning is separate from the repeated-read warning,
so neither silences the other. The finite supervisor runs the referee tasks its own
lineages request, and synthesis tasks that have no parent branch. A platform-rooted
task it runs (a referee, or a parentless synthesis) adds its lineage to the run's own,
so a review that such a task requests runs in the same run. Every society run adopts a queued
parentless synthesis, so two concurrent runs may pick the same one; the run that finds
it already leased skips it without recording an outcome. A lease conflict on a synthesis
the run scheduled itself is still recorded as its outcome.

Operators prepare a society arm from a run plan with a `society` block. See
`work/society-s1/run-plan.example.json` and the
[S1 live-run plan](../work/society-s1/RUN_PLAN.md).
- A benchmark-mode plan needs a private `masked_reference` artifact.
- The preflight blocks a benchmark run without it.
- Society exports add `commons_node`, `commons_claim`, `commons_review` and
  `literature_fetch` records and an `edges` list.
- `python tools/society_metrics.py <export>` reports the PLAN §9 metrics from an export.

The S1 live comparison (2026-09-26) ran the S1 society profile
([results](../work/society-s1/results-2026-09-26/REPORT.md)); no live run has used the
remediated profile yet. Its evidence is deterministic and mocked-provider tests,
including a no-model end-to-end simulation (`tests/test_society_simulation.py`).

## Qualification boundary

Protocol tests and mocked-provider replays test delivery, recovery, admission and
execution wiring. They cannot establish improved physics solving, SOTA performance,
or live fleet capacity. The finite supervisor retains its existing concurrency ceiling.
Large logical queues are not evidence of that many active models or VMs. Promotion of
communication policies needs matched-budget live research comparisons under the same
proof-acceptance policy.

Apply database migrations `0003_discussion_indexes` and `0004_library_notes` before
deployment. The new partial record indexes keep discussion lookups separate from
unrelated receipt-query plans, and 0004 adds the library notes table.
See the [implementation plan](superpowers/plans/2026-09-23-research-network.md) for
ownership, tests and integration gates.
