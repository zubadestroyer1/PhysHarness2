# Claude Agent SDK runtime

`physharness.execution.claude.ClaudeRuntime` implements the existing runtime adapter contract
using the official `claude-agent-sdk` **0.2.152**, whose installed Python source was inspected.
The SDK's real client, control protocol, message parser and command builder are exercised by
scripted-transport tests. No paid Claude query, native CLI run, cloud worker qualification or
scientific result was produced during implementation.

## Explicit execution contract

The default constructor refuses execution. Starting a session requires all three operator choices:

```python
from physharness.execution.claude import ClaudeRuntime

runtime = ClaudeRuntime(
    store=runtime_store,
    cwd=trusted_worker_directory,
    execution_boundary="trusted_development",  # or explicitly provisioned trusted_vm
    allow_inherited_environment=True,
    allow_unbounded_provider_tokens=True,
    max_estimated_cost_usd=1.0,
)
```

These are deployment configuration, not worker-provided model parameters. They do not authorize
spending by themselves. The campaign/ledger layer must authorize the actual call and reservation.
Use only a dedicated worker with intended provider credentials and research files. The official
SDK merges the parent process environment into its CLI environment; this adapter cannot honestly
claim environment isolation. It neither scrapes credentials nor copies them into checkpoints.
The operator must scope credentials, filesystem, network and process access outside the adapter.
Never run it on an API host containing receipt authority or unrelated cloud/application secrets.

The `trusted_vm` label acknowledges a VM provisioned by another component; it does not create or
attest one. Capabilities therefore report `isolation="development_process"`. SDK version drift
blocks startup until the new contract is qualified. Installing the existing `physharness[claude]`
extra is the dependency path; no base dependency, registry or runtime factory was changed here.

## Models and native tools

`start(prompt, ModelConfig(...), RuntimeLimits(...))` passes an exact model id without fallback.
Aliases such as `sonnet`, flag-like values and unsupported model parameters are rejected. Native
initialization, assistant messages and model-usage identities must agree with the request.
The supported model parameters are plain-text `system_prompt` and an SDK-supported `effort` value.
They cannot override permissions, tools, environment, MCP, session identity or budget options.

Native tools default to an empty list. Optional `native_tools=["Read", "Glob", "Grep"]` enables
only these read tools. A `PreToolUse` hook checks resolved paths and rejects escaping symlinks,
parent-directory globs, unconfigured tools and subagent-attributed calls. This is a policy gate
for trusted workers, not an operating-system sandbox or proof of race-free filesystem isolation.

The SDK receives explicit tool selection, `dontAsk`, an immutable deny list including `Agent`,
`Task` and `Bash`, no fallback, no skills/plugins/agents, empty settings sources, and strict empty
MCP configuration. Generated shell execution, editing and opaque spawning are unsupported here.
Those operations must use the separate governed execution/broker layer. Unexpected native tool
or subagent output fails loudly. `controlled_spawning=False` advertises that this adapter does
not offer governed native descendants; it is not a claim that arbitrary SDK behavior is audited.
Native slash commands are rejected so reset/resume commands cannot silently alter session identity
or accounting within a prompt.

## Budgets and accounting

The SDK receives remaining native turn and estimated-dollar allowances. It does not expose a
reliable hard per-query output/total token cap. The adapter reports `hard_token_limit=False` and
requires explicit acceptance of this limitation before any process starts. Token overruns are
detected after the result, persisted and block continuation; they cannot undo incurred usage.

Each adapter turn creates one SDK client process, submits one query and disconnects. Continuation
opens a new client with the exact native `resume` id. Result usage is added once per query, including
cache-read and cache-creation input tokens. Assistant-message fragments are not counted again.
SDK `total_cost_usd` is recorded as an **estimate**, not authoritative billing; usage events carry
`cost_is_estimate=True`. A session's estimated budget is reduced by preceding query estimates.
Actual cost settlement remains the resource ledger's job.

Native output is bounded per message by the SDK buffer option and in aggregate by the adapter
(default 2 MB). A wall deadline covers connection, query and result consumption. Failure triggers
a bounded interrupt request and disconnect. Cleanup errors persist as uncertain state rather than
successful completion. Timeout without a terminal result also stays uncertain; no automatic rerun
is allowed. Interrupted, failed and over-budget records require explicit reconciliation.

## Checkpoints and continuation

The adapter persists its generated runtime/native UUID and a pending operation before dispatch.
Checkpoints retain worker id, cwd, provider state directory, SDK/tool policy, observed counters,
query results and pending/error metadata. The stored native id must match initialization and every
result. Cross-runtime identity, another worker/directory, a different SDK/tool policy, uncertain
operations and attempts to rewind existing state are rejected.

`checkpoint` and `export` return the canonical runtime checkpoint. `resume` validates and restores
that pointer/state; the next continuation asks the actual SDK to resume the native transcript.
The SDK's session files in its configuration directory must still exist on the same worker.
Exported JSON does not recreate opaque native memory or include a portable transcript store.
Accordingly `portable_checkpoint=False` and `fork=False`. Restoring worker files is a separate
sandbox/checkpoint responsibility. There is no silent cross-runtime conversion.

`interrupt(session_id)` returns whether an active SDK client acknowledged an interrupt request.
It does not mean all native work has conclusively stopped. A terminal result or successful cleanup
is still needed to settle state. Session concurrency is guarded within this adapter instance;
the durable orchestration layer must serialize identities across processes using its leases.

## Verification evidence and remaining qualification

The tests use real SDK dataclasses/client/control parsing with a test-only `Transport` delivering
scripted wire messages. The production implementation has no fake provider and no selectable
success simulator. Tests cover conservative defaults, capability opt-ins, exact models and native
ids, real option/CLI-flag mapping, usage across resumed clients, rejected tools, deadlines,
interrupt/cancellation, cleanup uncertainty, budget overruns, stale checkpoints and path gates.
They establish protocol behavior, not provider availability, credential validity, actual billing,
native tool containment, VM isolation, successful physics research or live load qualification.

Inspected sources: installed `claude_agent_sdk` 0.2.152 `types.py`, `client.py`, internal query and
subprocess transport, plus official [SDK source](https://github.com/anthropics/claude-agent-sdk-python)
and [cost/usage documentation](https://code.claude.com/docs/en/agent-sdk/cost-tracking).
