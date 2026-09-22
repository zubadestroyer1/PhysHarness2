# Execution subsystem

The execution package is independent of API/database models. It exposes Pydantic request,
result, checkpoint, event, and capability records plus asynchronous runtime and sandbox
protocols. Import public interfaces from `physharness.execution`.

## Runtime contract

`RuntimeAdapter` provides:

```python
async def start(prompt: str, model: ModelConfig, limits: RuntimeLimits) -> RuntimeResult
async def continue_session(session_id: str, prompt: str) -> RuntimeResult
async def interrupt(session_id: str) -> bool
async def checkpoint(session_id: str) -> RuntimeCheckpoint
async def resume(checkpoint: RuntimeCheckpoint) -> RuntimeSession
async def export(session_id: str) -> RuntimeCheckpoint
```

`ModelConfig(model, parameters={})` keeps the exact requested identifier. Unknown/reserved
adapter parameters fail rather than modifying the model selection. `RuntimeLimits` sets
provider turns, output tokens per generation, cumulative input+output tokens, and wall time.
Capabilities identify which limits an adapter can enforce. They are qualification/configuration
statements, not live service health checks.

`RuntimeSession` contains its own ID, runtime, exact model configuration, limits, status,
native provider/session ID, turn count, and cumulative input/output usage.
`RuntimeResult` contains that session, output text, SHA-256-addressed output artifacts with
provider provenance, and native output items. Model output is not a verified scientific result.

`RuntimeStore.save(checkpoint)` and `.load(session_id)` are externally supplied async hooks.
`SQLiteRuntimeStore(path)` is a durable local implementation; it must be closed with `.close()`.
A production store must serialize ownership of each session across workers and retain the
checkpoint transactionally. The reference store is a single-owner development store; it does
not supply distributed leases or compare-and-swap revisions.

`RuntimeCheckpoint` includes the full session, provider state, format version and content
digest. Digest verification detects accidental corruption; it is not a signature or an
authorization boundary. Treat checkpoints as trusted project-scoped records. Resume retains
the same session identity and refuses an older/different checkpoint for an existing identity.
No adapter claims portable VM forks. An in-flight operation remains uncertain after a crash;
there is no automatic blind retry.

`ExecutionError` exposes `code`, `operation_id`, `retryable`, `remediation`, and `.as_dict()`.
Underlying provider exceptions are chained for internal diagnosis; public messages omit provider
exception bodies, which can contain credentials. Cancellation of an HTTP request does not prove
that remote billable work stopped.

## OpenAI Responses

```python
store = SQLiteRuntimeStore("runtime.db")
runtime = ResponsesRuntime(store=store, dispatcher=ToolDispatcher(), event_sink=on_event)
result = await runtime.start(
    "State an explicit conjecture and its assumptions.",
    ModelConfig(model="YOUR_EXACT_MODEL", parameters={"reasoning": {"effort": "high"}}),
    RuntimeLimits(max_turns=4, max_output_tokens=2000, max_total_tokens=12000),
)
```

This is a genuine `AsyncOpenAI.responses.create` tool loop. The real SDK's
`responses.input_tokens.count` preflights each request. The next output cap is bounded by
remaining cumulative tokens. A provider consumption discrepancy raises a limit violation and
stops further turns. No aliases or substitute models are selected by the adapter. Parameters
supported here are `instructions`, `reasoning`, `text`, `temperature`, `top_p`, and `service_tier`.
Unsupported provider parameter/model combinations fail at the provider.

The adapter uses `store=False`, requests encrypted reasoning content, and replays native output
items in subsequent inputs, preserving item IDs and function `call_id`. Native responses are
stored before usage callbacks. `ToolDispatcher.register(name, json_schema, async_handler,
description="")` exposes only registered functions; handlers receive `(arguments, operation_id)`
and must return JSON objects. JSON Schema validates every argument. Tool errors fail loudly.
Handlers are trusted control-plane code: they must authorize project access and reserve their
own budgets before starting children or external work. There is no implicit native subagent tool.

Optional async `event_sink(RuntimeEvent)` receives `generation_started`, `generation_aborted`,
`usage`, `tool_completed`, and `completed`. The generation-start event contains the input/output
token reservation and fires before billable generation. A core ledger can veto generation by
raising. If the runtime deadline expires before the provider request, `generation_aborted` releases
that reservation with zero usage.
The usage event includes the stable operation ID and actual native usage; reconciliation should
be idempotent by operation ID. If the provider response was persisted but delivery of a usage
callback failed, reconcile from the saved native response. The adapter does not implement a
transactional outbox or monetary pricing; those belong to the controller/ledger.

The session is checkpointed before each external request and host tool. A crash or tool failure
with a pending marker prohibits automatic resume. Provider usage absent from a response also
requires reconciliation. A session's total token budget persists across `continue_session`.
`interrupt` cancels the active local coroutine; provider completion/billing may remain uncertain.

## Official Codex SDK

`CodexRuntime` uses official `openai_codex.AsyncCodex`, `CodexConfig`, `thread_start`,
`thread_resume`, `AsyncThread.turn`, and `AsyncTurnHandle.run/interrupt`, verified against
`openai-codex 0.154.0`. It retains native thread/turn IDs, items and usage. Its native checkpoint
requires the same worker directory and provider-local thread store; the exported Python snapshot
alone cannot migrate native Codex state to another host.

The SDK starts a local app-server and inherits the host environment. It must run on a trusted,
dedicated worker. This adapter requires `allow_local_execution=True` and
`allow_unbounded_provider_tokens=True`; defaults refuse to launch. The official SDK does not
expose a hard per-turn token cap. Its `hard_token_limit=False` means it cannot be used where the
controller requires hard token reservations. Observed cumulative usage stops later turns, but
one native turn can exceed the requested limit. Native provider calls inside a turn are opaque.

The adapter explicitly sets `features.multi_agent=false` and `features.multi_agent_v2=false`
in launch/thread configuration, uses `Sandbox.read_only` and `ApprovalMode.deny_all`, and exposes
`controlled_spawning=False`. Model parameters accepted are `effort`, `output_schema`,
`service_tier`, and `summary`. All other parameters fail. Optional SDK import failures include
installation guidance. No live model generation was used to qualify this adapter.

`ClaudeRuntime` and `OpenHandsRuntime` implement native continuation/checkpoint contracts against
the pinned SDKs. See [Claude](CLAUDE_RUNTIME.md) and [OpenHands](OPENHANDS_RUNTIME.md) for their
specific authority and isolation requirements. Claude requires a dedicated trusted worker;
OpenHands accepts only externally qualified remote VM endpoints. Both require explicit
acknowledgment of native token-budget uncertainty. Neither is integrated into the distributed
research executor yet. The unconfigured capability registry correctly reports them unavailable;
it does not infer live qualification from an installed SDK.

## Sandboxes

`SandboxExecutor.run(CommandRequest)` returns `CommandResult`, including operation and execution
IDs, real exit code, bounded returned stdout/stderr, and truncation flags. Nonzero command exits
are actual results rather than model success. `cancel(operation_id)` requests termination.

`LocalShellExecutor(root, allow_local_execution=False)` is **development only**. It validates
working directories, rejects traversal and symlink components beneath the configured root,
starts a new POSIX process group, kills that group on timeout/cancellation/completion, drains
stdout/stderr with byte caps, supplies a minimal environment, and prevents concurrent reuse of
an active operation ID. stdin is closed. Use absolute executable paths outside the minimal PATH.

Cwd validation is not filesystem isolation: a command can still open other host paths, create
symlinks, access the network, or detach from its process group. This is not a VM security boundary
or an executor for hostile production code. It must never be used to run model-written research
JavaScript on the control plane. The JS runner checks and rejects this executor.

`E2BSandboxProvider(api_key=..., template_id=..., timeout_seconds=300)` requires an explicit exact,
qualified template ID and key; `.create()` calls actual `e2b.AsyncSandbox.create`. It sets
`secure=True`, `allow_internet_access=False`, and supplies no environment secrets. There is no
default-template fallback. Its native sandbox ID is the execution identity. One command runs at
a time per VM; timeout/cancellation attempts bounded termination of the whole VM. Failed or
uncertain termination preserves the exact VM identity, quarantines further commands, and reports
an unresolved outcome. Native pause/resume/snapshot/fork and bounded portable file archives are
implemented and contract-tested; the canonical broker intentionally refuses native child
allocation until child budget/lifecycle integration exists. See [workspace contracts](VM_WORKSPACES.md).

E2B output is capped in returned results, but the provider SDK may internally buffer full
streams. Provider-side resource/output controls remain necessary for adversarial workloads.
VM creation/cancellation, native lifecycle operations and template isolation require live
qualification; this repository's
unit suite makes no claims that such live qualification has passed.

## Durable JavaScript research programs

`ResearchProgramRunner(journal, executor=vm, dispatcher=tools)` runs untrusted source in a
separate Node process inside the configured provider VM. It never evaluates JavaScript in the
trusted Python process, nor uses Node `vm` as a security boundary. The Node template must have no
control-plane filesystem mounts, credentials, or network egress. Model code may access its own
VM filesystem; the security boundary is the configured VM, not the JavaScript wrapper.

The exposed helper is `await host(operationId, commandName, arguments)`. Each new host operation
ends the VM subprocess, reaches a schema-checked Python broker, and records the result durably.
The next subprocess replays source with prior host results. Programs must be deterministic
between host calls and use stable operation IDs. There is a finite host-command and subprocess
wall-time limit. This mechanism is replay of orchestration, not a serialized JavaScript heap or
recovery of arbitrary filesystem/network side effects.

`CommandJournal(path)` supplies independent durable Python replay even when VM execution is
unavailable. `begin(program_id, operation_id, command, arguments)` atomically records a pending
command and returns `None` for first dispatch or the prior JSON-object result for a completed
replay. Changed command/arguments produce `COMMAND_MISMATCH`; an unresolved dispatch produces
`OPERATION_UNCERTAIN`. `complete(...)` records the JSON-object result. `.export(program_id)` returns
journal records. The runner also binds a program ID to a source digest.

A crash after a side effect but before journal commit remains uncertain. The operator/controller
must reconcile the authoritative external operation and record a result; it must not delete the
pending record and hope a retry is safe. Host handlers should themselves use the supplied stable
operation ID with providers that support idempotency. Core distributed locks and project/budget
authorization remain required for multi-worker deployment.

## Sources and qualification

- [OpenAI Codex SDK](https://developers.openai.com/codex/sdk/) documents the official Python SDK.
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
  documents native function calls and call-result correlation.
- [E2B async Python SDK](https://docs.e2b.dev/sdk-reference/python-sdk/v2.5.0/sandbox_async)
  documents VM creation, commands and lifecycle.
- Installed interfaces inspected: `openai 2.54.0`, `openai-codex 0.154.0`, `e2b 2.49.1`.

Run `.venv/bin/python -m pytest tests/test_execution*.py -q`. The suite uses actual local
subprocesses, actual Node for trusted wrapper fixtures, SQLite close/reopen replay, real OpenAI
SDK calls with mocked HTTP only, and optional real installed-SDK signature checks. It does not
spend API credits or create live E2B VMs. Passing it does not establish production VM or provider
availability.


OpenHands client processes must set `LOG_AUTO_CONFIG=false` before their first SDK import,
alongside `LITELLM_LOCAL_MODEL_COST_MAP=True`. A late logging opt-out cannot undo SDK
initialization and is refused. Temporal workers use
`physharness.orchestration.sandbox.workflow_runner()` to share only Beartype's global
import machinery; ordinary workflow module isolation and file/network/time restrictions
remain active. See [OpenHands runtime compatibility](OPENHANDS_RUNTIME.md#temporal-import-compatibility).
