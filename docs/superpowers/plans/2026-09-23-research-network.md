# Research Network Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development; user explicitly selected GPT-6 Sol coding with root audit.

**Goal:** Implement the six approved collaboration proposals as usable, scoped, durable research capabilities.
**Architecture:** Discussion and workforce service mixins persist existing canonical records/events. Runtime adapters expose those services and deliver bounded updates at settled boundaries. Existing verifier and resource ledger remain authoritative.
**Tech Stack:** Python, Pydantic, SQLAlchemy, FastAPI, Responses runtime, existing Temporal integration.
**Spec:** docs/superpowers/specs/2026-09-23-research-network.md

## Global constraints
Preserve all prior dirty work. No commits, pushes, model calls, credential reads or VM starts by subagents. New source owned by one agent per file. Use existing isolated worktree. No forced proof decomposition, hierarchy, binary branching, majority-vote proof status or silent model substitutions. All branches share existing money/time ledger. Security and exact target semantics remain fail closed. No fleet qualification claim from mock workers.

## Review focus
Cross-branch privacy through generic record APIs; crash between delivery and checkpoint/ack; alternate task creation bypassing admission; duplicate concurrent portfolio/recruit commands; stale targets and historical cursor reuse. Test each in owning workstream.

### Task A — Research board and durable subscriptions (proposals 4/5)
Owner: discussion.py, discussion_models.py, service.py composition/scope integration, tests/test_research_discussion.py.
Interfaces: create_discussion(experiment_id, request, actor, key), post_discussion(topic_id, request, actor, key), discussion_page(experiment_id, actor, *, after=None, limit=20), discussion_posts(topic_id, actor, *, after=None, limit=20), subscribe_discussion(topic_id, subscribed, actor, key), discussion_updates(experiment_id, actor, *, after=None, limit=10), acknowledge_discussion_updates(experiment_id, delivery_id, actor, key). Typed request models in discussion_models; coordinate exact return shapes with C before code.
- [x] Add tests for sharing none/verified_only/ideas, forged origin/verified status, artifact privacy, replies across topics, experiment/target binding and generic API reads.
- [x] Implement append-only posts with sequence identity and bounded queries, explicit participant subscriptions, bounded durable delivery batches and idempotent acknowledgement. Claim/definition/evidence link types are validated, no acceptance changes.
- [x] Test out-of-order/forged acknowledgements, restart redelivery, gaps caused by filtering, full pages with exact next cursors, unsubscribe and isolation.
- [x] Expose explicit synthesis references preserving objections; synthesized text remains attributed. Freeze focused tests and report.

### Task B — Portfolio, recruitment, team directory and allocation (proposals 1/2/3/6)
Owner: workforce.py, workforce_models.py, collaboration.py create_task admission integration, tests/test_research_workforce.py. A owns service.py and integrates mixin/scope on request.
Interfaces: configure_workforce(experiment_id, request, actor, key), seed_portfolio(experiment_id, request, actor, key), recruit_researcher(experiment_id, request, actor, key), publish_research_profile(experiment_id, request, actor, key), research_directory(experiment_id, actor, *, after=None, limit=20), join_research_team(experiment_id, request, actor, key), research_capacity(experiment_id, actor), request_research_capacity(experiment_id, request, actor, key). Send exact models to C.
- [x] Test atomic idempotent seed and recruit (same key changed semantics rejected), rollback and cross-target/branch authority. Implement single transaction branches+tasks using existing invariants rather than nested service commits.
- [x] Bound total/pending tasks, include old create_task path in admission, report QUEUED versus RUNNING honestly. Atomic concurrency guard serializes experiment scheduling admission. Operator policy cannot enlarge original money/time/concurrency envelope.
- [x] Implement opt-in bounded directory and voluntary team membership, no implicit private permissions. Capacity demand is observable and does not create capacity or grant funds. Test protected experiments and private artifact exclusion.
- [x] Support synthesis recruitment as ordinary objective with bounded discussion references; no hardcoded scientific methods. Freeze focused tests and report.

### Task C — Model tools, safe delivery, public interfaces and fair scheduling
Owner: orchestration/research_worker.py, execution/responses.py, new orchestration/research_network.py, api.py, client.py, mcp_server.py, execution/stagnation.py where needed; tests/test_network_runtime.py and tests/test_network_api.py. Do not edit A/B service modules.
- [x] Register strict schemas for A/B interfaces after exact contract handshake, expose all through HTTP/client/MCP. Add agent instructions encouraging useful recruitment, independent exploration, criticism, concise updates and artifact use without mandatory mathematical roles.
- [x] Add optional safe-boundary update hook to Responses: inject bounded tool/peer-data context into persisted state before next generation, preserve visible delivery IDs, acknowledge only after context is durable; retries cannot silently omit batch. No model calls for inbox polling, no new uncertain effect replay. Other runtimes truthfully advertise unsupported automatic delivery.
- [x] Include scoped discovery/capacity/inbox in initial and compacted context; bound repeated data and treat peer messages as untrusted ideas rather than system authority. Ensure terminal response recovery stays non-paid.
- [x] Implement deterministic fair ready-task ordering across root lineages/branches preserving dependencies and renewal of active work. Keep max concurrency qualification ceiling; do not merely raise 100 to claim scale.
- [x] Test two concurrent fake agents exchange actionable evidence and child returns; restart before/after durable injection; single-slot join remains safe; mailbox backlog/dedup, schema recursion, errors visible. Freeze focused tests/report.

### Task D — Integration and measured coordination experiments
After A/B/C freeze, assign Sol implementation of tests/network evaluation runner; root audits. Add replay-only scenarios comparing independent roots, addressed messages, and subscribed discussions with identical resource manifests; record actual deliveries, use/reuse acknowledgements, coordination overhead, duplicates, waiting, fairness, outcomes and limits. Metrics do not establish mathematical effectiveness or inferred message usefulness. Use baseline plus deterministic fault injection and bounded load (e.g. 128 logical queued branches, few active mock workers) with explicit simulated label. No live model budget silently reused.
- [x] Run all focused contracts and full Python/Ruff/format checks.
- [x] Audit whole integrated diff for authorization, scoped delivery, double allocation, bypass paths and evidence claims; assign author fixes and retest.
- [x] Run affected PostgreSQL/Temporal integration where available; record skipped dependencies loudly.
- [x] Update status/docs/research-network report mapping all six proposals to shipped APIs/tests and remaining qualifications. Stop test VM if started.

## Execution ruling
The user explicitly asked to plan and then implement autonomously with GPT-6 Sol. Proceed without an additional approval turn. Workstreams A/B/C may run concurrently with disjoint ownership; shared interfaces must be agreed before integration. Preserve local evidence and do not commit the mixed existing worktree.

## Completion evidence
Implemented and independently audited. See `work/research-network-2026-09-23/DELIVERY.md` for fresh aggregate, PostgreSQL/Temporal, real VM and kernel checks. Mock replay does not establish scientific effectiveness or live fleet qualification. No paid model calls, commits or pushes; the dedicated VM was stopped after testing.
