# Durable Research Continuation Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Root owns planning, instructions, integration audit and live operations; GPT-6 Sol agents own implementation. Existing worktree is retained.

**Goal:** Deliver robust context continuation, scientific memory, delegation and recovery through existing canonical services, then qualify and run two reviewed physics targets.

**Architecture:** Extend existing Responses runtime, canonical scientific services, task leases/outbox, Temporal activities and finite team runner. Keep provider-native state separate from exact scientific records and model-authored summaries. Every descendant and continuation shares the experiment ledger.

**Tech Stack:** Existing Python 3.12, Pydantic/SQLAlchemy, OpenAI SDK 2.54, Temporal, PostgreSQL/SQLite, Lean/Comparator/nanoda Linux image, TypeScript console.

**Spec:** ../specs/2026-09-23-durable-research-continuation.md

## Global constraints

- No acceptance weakening, invented expert approvals, hidden benchmark solutions, model substitution, or ledger reset.
- No credentials/native model context in public logs or agent messages. Agents do not read private credentials or launch paid calls. Root operates credentials privately.
- Preserve existing dirty user/pilot work. No destructive migration, cloud deployment, merge or remote publication in this task.
- Source edits by GPT-6 Sol agents; root writes design/evidence documents and audits changes.
- Existing PortableMemory v1 remains valid; new bounded working views are explicitly partial and do not confer proof status.
- No automatic replay of pending/uncertain paid effects. All modifications use canonical authorization, idempotency, shared resources and task fencing.
- Paid tests: $25 per attempt; all child, compaction and continuation usage included. VM stopped and monitor paused afterward.

## Review focus

1. A compaction item alongside function calls cannot drop either side of a call/result pair or erase accounting.
2. A process dies between reservation, provider response, usage settlement, checkpoint and continuation issuance: retain uncertainty and reject stale ownership.
3. Thousands of failed/open records cannot inflate working context without bound or vanish from the obligation index.
4. One-slot parent waits must release capacity, and failed child work must become inspectable rather than deadlock.
5. New sessions, model changes or shared results must not bypass experiment scope, reviewed definitions or budget ceilings.

## Task 1 — Runtime compaction and continuation boundary

Owner: native runtime agent. Files: execution/parameters.py, types.py, responses.py; optional new execution/context.py; tests/test_execution_parameters.py and new tests/test_execution_context.py. No controller/memory edits.

Consumes existing RuntimeStore, ToolDispatcher and EventSink. Produces typed context-management parameters; RuntimeLimits.max_context_tokens; RuntimeResult.continuation; an optional async boundary hook receiving the current RuntimeCheckpoint. Exact hook signature coordinated with Task 3 before edits. Default behavior remains backward-compatible when disabled.

- [x] Write fake-provider tests for two compactions, preservation of encrypted items, exact usage, tool pairing, malformed output and boundary persistence failures.
- [x] Implement typed inline compaction and active context preflight, using SDK-supported shapes. Provider tokens/cost never reset.
- [x] Prune only on a safe completed boundary; retain complete durable history. Emit auditable compaction counts/size metadata without opaque content.
- [x] Implement a separate yielded continuation result; no fake successful final response and no automatic uncertain replay.
- [x] Run focused runtime/parameter/provider tests and lint; provide diff/report for root review.

## Task 2 — Bounded scientific context and retrieval

Owner: scientific memory agent. Files: new working_context.py or bounded additions to memory.py; research.py/knowledge/index.py if necessary; dedicated tests. Do not edit research_worker.py or shared API files until integration owner coordinates.

Consumes existing canonical services and visibility/acceptance methods. Produces a bounded working-context builder with exact target/review/current task, explicit paginated record references and original evidence access; scoped retrieval/read methods for controller tool registration. Existing checkpoint v1 behavior is preserved.

- [x] Test large failed/open histories, exact retained assumptions, false verified labels, stale revisions, cross-branch privacy, private native exclusions and size overflow.
- [x] Implement working-context reconstruction from authoritative records with truthful completeness indicators and cursors.
- [x] Implement bounded record/history/artifact retrieval and scoped accepted dependency discovery; retain provenance and assumptions.
- [x] Test linked failure evidence and applicable lemma retrieval with real service fixtures, not only mocked dictionaries.
- [x] Run memory/research/knowledge/sharing tests and report public interfaces to Task 3.

## Task 3 — Durable handoff, waiting and collaboration integration

Owner: continuation/controller agent. Files: new continuation.py; collaboration.py, service.py wiring, orchestration/research_worker.py, worker.py/workflows.py/temporal_delivery.py as needed; API/client/MCP additive endpoints; dedicated integration tests. Native runtime files belong to Task 1, memory internals to Task 2.

Consumes Task 1 safe-boundary hook and Task 2 working-context builder. Produces canonical request/issue/consume continuation lifecycle, runtime handoff/wait tools, fenced new execution ownership, actual worker start/resume selection, scoped mailbox/history/status tools and durable readiness in both controllers.

- [x] Test fresh successor with same experiment budget, model allowlist, stale-fence rejection, duplicate continuation consumption and uncertain-request blocking.
- [x] Implement request_handoff and wait_for_tasks with issued canonical state, no arbitrary worker-granted continuation authority.
- [x] Release parent lease and slot on yield; resume fresh or exact compatible native state only after dependencies are terminal and pending effects are reconciled.
- [x] Integrate helpers/collaborators/competing branches, child terminal-status inspection and selective mailbox retrieval. Enforce none/verified/ideas; do not leak private transcripts.
- [x] Add safe process-recovery adoption at known settled checkpoints; retain loud operator-required state for ambiguous effects.
- [x] Test multiple cycles, one-slot parent/child scheduling, orphan recovery, cancellation and equivalent Temporal routing.
- [x] Run coordination/authority/worker/CLI/integration tests and produce root review package.

## Task 4 — Safe finishing, observability and exposure

Owner: controller agent after Task 3 integration, with independent audit. Files: research_worker.py, research service candidate operation, CLI/API/client/MCP and tests as appropriate.

- [x] Add explicit candidate store-and-submit operation with idempotent durable verification request; drafts never auto-promote.
- [x] Keep already queued verifications draining after generation stop within checker deadline; record outstanding checks rather than false completion.
- [x] Report exact budget stop dimensions, continuation counts, worker/pending states and resource usage without secret context.
- [x] Validate public surfaces and update docs to distinguish implemented/local/live/fleet qualification.

## Task 5 — Independent integrated audit and qualification

Root directs fresh reviewers and fixes by implementers. No paid experiments before audit blockers are resolved.

- [x] Inspect integrated diff against every spec layer, including dependencies and shared-file interactions. Record findings and fixes in work/long-horizon-2026-09-23/LEDGER.md.
- [x] Run `.venv/bin/pytest -q -m 'not integration and not lean'`, repository CI-scoped Ruff check/format, relevant frontend tests/build and infrastructure validation.
- [x] Run real local Temporal engine and PostgreSQL integration regressions; distinguish genuine unavailable integrations.
- [x] Start dedicated physharness-pilot VM, verify exact image/runtime identities and resources, run fresh verifier collector in new exclusive evidence directory when scope changed.
- [x] Exercise restart/retention and cleanup; preserve hash-verifiable artifacts and no stray worker containers.

## Task 6 — Two live problems, monitoring and delivery

Root operates private credentials. A GPT-6 Sol operations agent implements reviewed nonsecret orchestration helpers and tests. Retain original pilot records.

- [x] Prepare fresh reviewed projection and purity experiments (known-result regression/reuse), generous cumulative limits and active context threshold under configured pricing tier; $25 each.
- [x] Revalidate target/bundle/review and provider configuration, then launch first run. Keep independent acceptance and proof provenance visible.
- [x] Launch second run with explicit permitted access to accepted first-result artifacts; measure actual lemma retrieval/use separately.
- [x] Create scheduled monitor plus active supervision; log progress, CPU/RAM/container failures, exact cost and proof status. Diagnose crashes before audited fixes/fresh retry.
- [x] Export clean result/evidence reports, preserve raw private logs, stop VM, pause monitor, and report outstanding scientific/production limitations.

## Execution decisions

User explicitly requested planning followed by autonomous implementation and tests; no additional planning approval pause is introduced. Existing isolated worktree contains qualified image and retained pilot state, so it is reused rather than copying/deleting state. Live target selection uses already reviewed targets to avoid manufacturing new scientific approval. This is a regression/reuse suite and not an open-discovery benchmark. Implementation policies remain configurable; initial paid trials do not qualify the ultimate fleet scale.

## Delivery evidence

Implementation/audit and both live tests completed on 2026-09-23. See `work/long-horizon-2026-09-23/DELIVERY.md` for the exact scope and limits: 894 final host tests passed; real local Temporal/PostgreSQL and scoped kernel qualification passed; projection accepted, purity unproved after shared token admission stopped a descendant. Both runs exercised native compaction and delegation, but neither exercised live fresh-session handoff or demonstrated cross-target lemma reuse. Completion of these implementation/test tasks does not qualify every production or scientific wave. Dedicated VM stopped; monitor paused.
