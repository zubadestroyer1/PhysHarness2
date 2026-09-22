# Claude Agent SDK adapter report

Implemented only `src/physharness/execution/claude.py`, `tests/test_execution_claude.py`,
`docs/CLAUDE_RUNTIME.md` and this report. No registry, execution exports, core/schema, or dependency
manifest edits; no subagents or commits. Parent installed the existing optional extra, yielding
`claude-agent-sdk==0.2.152`. No paid provider call, native CLI invocation or cloud VM was run.

## Actual SDK evidence

Inspected the installed SDK's exact constructor signatures for `ClaudeAgentOptions`,
`ClaudeSDKClient`, `AssistantMessage`, `ResultMessage`, plus actual `Transport`, client connection,
query initialization/control messages, and subprocess command/environment construction. Official
upstream Python source and cost documentation were also checked. These confirmed:

- Native SDK execution launches a local CLI and inherits the host environment.
- Explicit `tools`, `disallowed_tools`, `dontAsk`, `setting_sources=[]`, `skills=[]`, no plugins,
  strict empty MCP configuration, no fallback, and resume/session ids are actual supported fields.
- `allowed_tools` alone is not an exclusive tool list; the adapter also supplies `tools`.
- `max_budget_usd` is an estimate-based limit. No hard per-query output/total token cap is offered
  by the adapter; advisory task budget fields are not misrepresented as enforcement.
- One new client process per submitted query avoids confusing streaming-client cumulative costs
  with independent resumed query costs. Cache tokens are included in observed input totals.

## Interface and behavior

`ClaudeRuntime` follows `RuntimeAdapter`: async start, continue_session, interrupt, checkpoint,
resume and export. Exact native ids are generated and persisted before dispatch and checked against
SDK initialization/results. Pending operations, counts, estimated costs, query results and failures
are durable through the injected RuntimeStore. Continuation uses actual SDK native resume on the
same worker/provider-state directory. Stale rewinds and incompatible/uncertain checkpoints block.

Execution defaults to disabled. Explicit trusted worker boundary, acknowledged inherited environment,
and acknowledged unenforceable native token caps are all required. The adapter uses no provider
transport substitute in production. Current SDK version must match tested 0.2.152.

Native tools are disabled by default. Optional confined Read/Glob/Grep tools have a PreToolUse path
policy. Agent/Task/Bash and other ungoverned tools are denied; settings, skills, plugins and implicit
MCP are disabled through actual SDK fields. Exact model checks reject alias/default substitution,
unexpected assistant models, native session drift and unrequested model usage. Slash commands and
policy-overriding model parameters are rejected.

Capabilities honestly report hard_token_limit=False, controlled_spawning=False,
portable_checkpoint=False, fork=False, isolation=development_process. A trusted_vm configuration
means an external component provided that worker; this adapter does not claim to provision/attest it.
Native checkpoint JSON does not contain the SDK's opaque session files.

Wall deadlines, bounded output, observed budget checks, native result/error handling and bounded
interrupt/disconnect are implemented. Cleanup or unresolved timeout leaves uncertain state rather
than completion. Interrupt return True means request acknowledgment only. Cost events are explicitly
estimates, not settled billing. Parent/core ledger remains authoritative.

## Test-first evidence

Initial run before implementation: **13 failed**, each due to absent Claude adapter.
First real implementation: **13 passed** with installed SDK 0.2.152 and scripted wire transport.
Additional lifecycle/accounting tests passed while a new flag-like model-id regression failed;
the model grammar was tightened before rerunning. A command-builder test initially expected the
wrong spelling form for empty settings sources; inspecting the actual SDK showed the correct
`--setting-sources=` form, and the assertion was corrected without altering production behavior.

Final scoped run:

```text
.venv/bin/python -m pytest tests/test_execution_claude.py -q
21 passed in 0.30s
.venv/bin/ruff check src/physharness/execution/claude.py tests/test_execution_claude.py
All checks passed!
```

Tests instantiate the **real ClaudeSDKClient**, initialization/control routing and message parser
with a test-only `Transport`. They do not replace the production adapter with a successful mock.
The actual SDK subprocess command builder is also exercised without launching it.

Coverage: default refusal; environment/token opt-ins; tool/settings/MCP/spawning options; native
UUID preservation; continuation usage exactly once; missing/malformed usage; unexpected models and
session ids; denied native tool output; incomplete result; timeout/interrupt uncertainty; cancellation;
cleanup failure; observed budget overrun; stale/foreign-worker checkpoint refusal; read-path/symlink/
glob rejection; rejected aliases/CLI-flag model tokens; version drift; parameter override refusal;
and real SDK CLI flag generation.

## Limits and qualification

No live Claude response, credential check, paid token consumption, native read tool, CLI lifecycle,
VM isolation, kernel proof or scientific result was validated. Optional tests explicitly skip if the
SDK extra is missing; the stated run used the actual installed 0.2.152 package.

The process environment is inherited by the official SDK, not sanitized by this adapter. Default
refusal and explicit acknowledgments prevent accidental use on a secret-bearing API host; deployment
must supply a dedicated scoped worker. PreToolUse path checks are policy checks, not an OS sandbox
or proof against races. Per-native-query token overshoot and estimate/billing differences remain
inherent limits. Session histories depend on retained SDK files; exported checkpoints are not
cross-runtime portable. Durable cross-process serialization and lease/fencing remain external.
The adapter is a usable, conservative native SDK integration, not live production qualification.
