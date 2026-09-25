# One-shot schema/access probe

Implementation: `probe_api.py` loads only the existing pilot config and `authorization.json` ($100 aggregate, four arms, $0.20 probe allocation, zero prior probe spend). It builds the exact 54 worker tool definitions from `research_tools(..., task_context=..., workspace_tools=...)` using schema-only dummy objects; no canonical service or workspace handlers are invoked. It stores a SHA256 digest of the canonical tool JSON and its count.

It exclusively creates `private/probe-state.json` mode 0600 before any endpoint call; a second invocation is refused even after a crash. It calls `responses.input_tokens.count` with the exact model `gpt-6-sol`, safe input `Reply ready.`, high reasoning, all tool definitions and `parallel_tool_calls=False`. It computes a conservative request upper cost `count * $2.50/M + 1024 * $10/M`; if above $0.20, it refuses before generation. Otherwise it durably writes `pending_create`, then calls `responses.create` with `max_retries=0`, `max_output_tokens=1024`, `tool_choice="none"`, and `context_management=[{"type":"compaction","compact_threshold":184000}]`. The API key comes only from the environment. Full native response is written mode 0600 under `private/probe-native.json`; the state and console output contain only bounded allowlisted identifiers, status, usage, upper-cost estimate, tool count/digest, and a safe code. A model mismatch, missing/overrun usage, other incomplete result or uncertain request requires reconciliation. `incomplete_details.reason=max_output_tokens` counts as schema/access acceptance, not scientific work.

Invocation for the root operator, once, with the key supplied outside this command:

```sh
PYTHONPATH=src .venv/bin/python work/parallel-pilot-2026-09-24/probe_api.py --config .state/parallel-pilot-2026-09-24/config.json
```

Do not rerun if `private/probe-state.json` exists, even after a transport error. Inspect and reconcile the private native/state records first. The helper does not update the authorization file or experiment ledger; the root must record actual or uncertain probe spending against the $0.20 allocation before starting four arms.

Verification with no paid API calls: `PYTHONPATH=src .venv/bin/pytest -q tests/test_parallel_probe_api.py` passed 4 tests (full schema, cost refusal before create, uncertain no retry, and output-cap incomplete acceptance). Ruff check and formatting pass. No VM or model call was made.
