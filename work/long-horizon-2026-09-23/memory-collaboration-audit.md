# Long-horizon memory and collaboration audit (2026-09-23)

Read-only audit of `memory.py`, `research.py`, `service.py`, `collaboration.py`, `orchestration/research_worker.py`, `execution/responses.py`, and relevant tests. No live provider, VM, or credential use.

## Existing foundation worth preserving

- The experiment has one transactional cost, token, concurrency, and runtime envelope. `ResearchTaskExecutor.execute` reserves a worker slot and model tokens through `service.reserve_resources`; the team runner limits task attempts and schedules eligible descendants. Child branches inherit the experiment and its model configuration. (`service.py:636-650, 737-920, 924-987`; `research_worker.py:379-445, 715-723, 746-864`)
- Tasks, dependencies, branch ancestry, messages, events, verification receipts, and artifact hashes are canonical records. Task completion is fenced and requires artifact evidence. `delegated_from_task_id` is captured for worker-created tasks and lets the finite runner select descendants without sweeping unrelated root-branch tasks. (`collaboration.py:19-72, 168-214, 216-282`; `research_worker.py:755-785`; `test_research_loop_integration.py:563-612`)
- Portable checkpoints bind the exact target, review, branch, mandatory open obligations, failed verification references, chosen evidence hashes, and lineage. Summaries are marked unverified; restore checks freshness. There is a paginated `PortableMemory.history_page` service method, and native/private artifacts are excluded from portable evidence. (`memory.py:65-211, 366-576`; `test_memory.py:26-100, 144-190, 293-305`)
- Native Responses checkpoints preserve complete input, provider outputs, tool results, and pending-operation identity. Uncertain external effects block automatic replay. (`research_worker.py:43-139, 338-360`; `responses.py:154-197, 278-385, 394-420`)
- Accepted reusable claims require exact target/environment/assumption/receipt bindings. This provides a sound source for a research graph's proved edges without choosing a proof method. (`research.py:66-240`)

## Critical gaps

1. **The working context is not bounded.** `PortableMemory._core` includes every open task, every unverified claim, and every blocked/rejected verification for the branch. Once those exceed the caller's envelope, `checkpoint` raises `SCIENTIFIC_CORE_TOO_LARGE`; it has no bounded current-task view. `restart_brief` eagerly returns all visible claims, receipts, tasks, artifacts, and messages, and is inserted into every new task's initial prompt. `ResponsesRuntime` appends all prior input/output/tool results to `state['input']` at each turn. `max_total_tokens` is cumulative for one session; current portable checkpoints do not compact native input. (`memory.py:147-191, 433-452`; `collaboration.py:284-304`; `research_worker.py:537-550`; `responses.py:160-183, 200-243, 285-382`)
2. **History retrieval is not exposed to the model.** `history_page` exists, but `research_tools` registers only `checkpoint_context`, `restore_context`, and `restart_brief` in this area. The user cannot rely on an agent selectively fetching exact older records when the initial brief is made bounded. (`memory.py:193-211`; `research_worker.py:180-213`)
3. **Delegation cannot complete a parent-child research loop.** A parent can fork and enqueue, but under `sharing='none'` it can see its immediate child branch only for scheduling; it cannot read the child's task result or research artifact. A message requires `sharing='ideas'`, and no worker tool pages a mailbox or child status. The existing child test proves independent execution after parent loss, not parent integration of a returned result. (`service.py:202-247`; `collaboration.py:216-282`; `research_worker.py:288-324`; `test_sharing.py:176-205`; `test_research_loop_integration.py:190-292`)
4. **Waiting can deadlock at concurrency one.** The parent holds the experiment's only worker reservation throughout a live Responses session. A tool that waits for a child while the parent retains that slot prevents the child from starting. Existing `wait_for_verification` polls an independent verifier; it is not a safe pattern for child tasks. The runner starts descendants only after capacity is free. (`research_worker.py:379-386, 851-864`)
5. **No durable scientific graph query.** Records and `EdgeRow` already encode task dependencies and branch relations, but there is no bounded, typed graph view joining task outcomes, claims, attempts, receipts, source spans, and counterexamples. `search_knowledge` addresses accepted reusable lemmas only. A single task/claim list is a poor long-horizon map. (`collaboration.py:19-72`; `service.py:976-985`; `research.py:186-240`)

## Minimal useful implementation, in dependency order

### 1. Bounded exact working context and retrieval

Keep `physharness.portable-context.v1` and its tests intact. Add `WorkingContext.v1` as a new presentation over canonical records rather than weakening the existing scientific core. For example:

```python
PortableMemory.working_context(branch_id, actor, *, task_id, limits: WorkingContextLimits,
                               selected_ids: list[str] = []) -> dict
# limits: max_bytes, max_estimated_tokens, max_references, max_summary_chars
# result: target + review identity/digests, current task (full objective/dependencies/status),
# budget snapshot, selected exact references, bounded open/failure counts by kind,
# history cursors/query hints, attributed unverified working notes, truncation manifest.
```

The target statement and assumptions, review identity, current task, and exact acceptance status must never be dropped. Other history is represented by counts and cursors, not a claim of completeness. If those mandatory fields alone exceed the envelope, return a typed overflow error. Fetch selected records through existing authorization and `_reference` validation; disclose neither sibling-private data nor native checkpoints. Add worker tools `history_page(kind, limit, after)`, `read_record(kind, id)` for portable allowed kinds, and `working_context(task_id, ...)`; `read_artifact` already covers authorized bytes. Put `WorkingContext.v1`, not `restart_brief`, in a new task's initial prompt. The existing checkpoint can still preserve an explicit lineage and selected evidence. Use an exact record ID/hash in every graph or context reference and mark model-written notes unverified.

### 2. Durable child handoff and result read

Expose a scoped child query without broadening general sharing. Proposed service interface:

```python
CollaborationMixin.child_result(parent_task_id, child_task_id, actor) -> dict
# parent must be the actor's current fenced task; child.delegated_from_task_id == parent_task_id;
# child branch must be the assigned branch or an authorized direct child;
# result: child task status, objective, evidence IDs, bounded artifact descriptors,
# attribution, proof/verification status, no raw private native session.
```

Read artifact bytes separately with a narrowly authorized handoff capability, or publish a bounded `research_handoff` artifact into the parent's branch on child completion. Prefer the latter if keeping `_in_scope` unchanged: the controller validates child task ancestry, hashes the child output, copies an attributed summary/reference to the parent, and records a `derived_from` edge. This is a result handoff, never proof acceptance. Add `child_status`/`child_result` tools with keyset paging over a parent's delegated tasks; no arbitrary task ID reads. A child may additionally `send_message` if ideas sharing is enabled, but mailboxes are not the only return path.

### 3. Yield rather than hold the only slot

Provide a durable `yield_for_children(child_task_ids, checkpoint_id)` control action. Validate that each child was delegated by the current fenced task and checkpoint is current/assigned. Atomically record the parent wait and a continuation task whose dependencies are the child task IDs; release the parent lease and worker reservation before scheduling children. On completion, the runner executes the continuation with a fresh bounded working context plus exact child handoff references. The continuation is a new task/session, so it avoids replay of a potentially billed or uncertain native session. An explicit completed parent can instead delegate a continuation task with the same dependency relationship; the key requirement is that waiting consumes no worker slot. Do not introduce a blocking `wait_for_child` tool inside `ResponsesRuntime`.

### 4. Native compaction as a separate, explicit boundary

The native Responses input grows because it is replayed in full. After a settled tool/response boundary, allow an explicit compact-to-new-session transition: persist the old native checkpoint and a portable WorkingContext/handoff artifact; start a new Responses session using those records plus selected exact references. Charge the new session to the same experiment ledger. Never rewrite an uncertain checkpoint or trim `state['input']` in place, because that would obscure replay and accounting. The old session remains exact audit history. This transition can initially be implemented as a continuation task, avoiding a generic in-session compaction framework.

### 5. Graph view using current tables

Add a read-only `research_graph_page(experiment_id, actor, *, anchor_id=None, edge_kinds=None, limit=50, after=None)` over `RecordRow` and `EdgeRow` rather than a new graph database. Include typed edges for branch parentage, task delegation/dependencies, task outputs, claim evidence and verification, source provenance, and explicit refutation/counterexample links where records actually establish them. Return IDs, revision/hash, status, and cursor. Do not infer proof or a fixed proof strategy from an edge. Backfill only deterministic links from existing fields; create new edges transactionally with their source command going forward.

## Tests that prove the seams

- One-worker replay: parent delegates a child and yields; child runs; parent continuation reads the exact child output and finishes; ledger `active_workers` returns to zero. A parent retaining the slot must not be able to call a blocking child wait.
- Private-result boundary: unrelated branch and sibling cannot read the child result; authorized delegating parent receives only an attributed handoff, with proof status unchanged. A forged child task ID or artifact fails.
- Long history: hundreds of failed receipts/open claims/artifacts still produce a bounded WorkingContext with accurate counts/cursors; selected record fetch returns exact hash/status; mandatory target overflow fails explicitly. Existing portable-context.v1 tests keep passing.
- Restart: child completes after parent process loss; a fresh finite runner selects only the delegated child/continuation, reads durable handoff, and does not duplicate billed provider work.
- Graph page: typed edges and keyset paging retain exact provenance under status changes; hidden branch/native checkpoints do not appear. Acceptance is taken only from canonical receipts.

The existing tests cover bounded explicit checkpoint input, privacy, runner restart, child independence, and ledger reservation, but not these end-to-end joins. The proposed order makes context and result retrieval useful first, then adds automatic suspension and graph navigation without redesigning the authority model.
