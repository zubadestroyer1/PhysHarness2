# Task C — runtime, public interfaces, scheduling

Implemented in the isolated `formal-research-loop` worktree without a commit, push, paid model call, VM start, or credential read.

## Delivered

- Responses reads the bounded unified discussion/addressed-message delivery at each settled pre-generation boundary. It writes the attributed, explicitly unverified excerpts and delivery ID into the canonical native checkpoint before acknowledging. Recovery after a failed acknowledgement reuses the saved context without duplicating it. No hook runs during an uncertain paid provider call or terminal recovery. Delivery history is bounded to 128 IDs per native session; the canonical server acknowledgement cursor remains authoritative.
- Agent tools expose discussion creation, posts, exact source retrieval, subscriptions, directory, recruitment, team membership, capacity inspection/demand, and inbox reads/acks through service methods. Operator-only workforce configuration and portfolio seeding are exposed through HTTP, Python client, and MCP. Mutations require idempotency keys; HTTP bodies use the strict A/B Pydantic request models. Other runtimes are described as manual delivery only.
- Initial and compacted research context includes bounded directory, topic, capacity, mailbox and exact source retrieval guidance. Assigned synthesis post IDs and bounded sample scope are present explicitly. Instructions encourage independent mathematical approaches, useful recruitment, critical discussion and artifact references without mandatory decomposition or peer authority.
- The finite team runner dispatches ready tasks round-robin across root lineages while respecting dependencies, existing leases and the manifest concurrency limit. It scans tasks once per tick and caches branch ancestry, refreshing it for new branches. Automatic synthesis ticks only for an opted-in experiment when the run owns every active root lineage. Existing queued synthesis tasks in the run lineage are selected by their canonical marker. No budget or concurrency ceiling was raised.
- Stagnation classification treats directory, inbox and source reads as reads; empty inbox polls and membership/capacity bookkeeping do not count as scientific progress.

## Verification

- Full Python suite: **1022 passed, 10 skipped** (`PYTHONPATH=src .venv/bin/pytest -q`), after integration of A/B and the synthesis-context test. The 10 skips are existing environment-dependent checks.
- Ruff check and format check pass on every Task C source/test file.
- New tests cover checkpoint-before-ack ordering, provider-visible delivery, acknowledgement-failure recovery without duplicate context, unified post and addressed-message delivery through a real service/provider mock, exact source retrieval, strict HTTP request rejection and Python client idempotency, actual agent tool dispatch, sampled synthesis context in both initial prompt and compaction anchor, and fair root ordering. Existing joined delegation, execution context, provider strict-schema and discussion/workforce suites pass.

## Qualification limits

Provider behavior was mocked; no paid model or live fleet run was performed. Fairness and delivery tests establish protocol behavior, not mathematical effectiveness. Automatic inbox delivery is implemented for Responses; other runtimes retain manual tools. This workstream did not claim 128 active workers or enlarge the `max_concurrency <= 100` supervisor ceiling.
