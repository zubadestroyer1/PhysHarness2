# Runtime/execution implementation report

Owned files only: `src/physharness/execution/`, `tests/test_execution*.py`,
`docs/EXECUTION.md`, `examples/research_programs/`, and this report. No commits made.

## Public imports ready for core integration

All are exported by `physharness.execution`:

- `ExecutionError(code, message, operation_id=None, retryable=False, remediation=None)`:
  attributes plus `.as_dict()` produce the contract's public error fields. Exceptions preserve
  provider causes internally without putting their raw bodies in public messages.
- Pydantic `ModelConfig(model: str, parameters: dict={})`: exact, nonblank identifier.
- `RuntimeLimits(max_turns=8, max_output_tokens=4096, max_total_tokens=32768,
  timeout_seconds=300)`: positive validated values; native adapters advertise actual enforcement.
- `Capabilities`: available, reason, start, continue_session, interrupt, checkpoint, resume,
  export, fork, portable_checkpoint, controlled_spawning, hard_token_limit, isolation.
- `RuntimeSession(id, runtime, model, limits, status, native_session_id, turns,
  input_tokens, output_tokens)`. IDs default to UUID strings.
- `RuntimeCheckpoint(session, native_state, state_digest, version=1)`;
  `.build(session, native_state)` computes digest, `.verify(runtime=None)` checks it.
- `RuntimeResult(session, output_text, artifacts, native_items)`.
- `OutputArtifact(kind='model_output', content, media_type='text/plain', digest, provenance)`.
- `RuntimeEvent(kind, session_id, operation_id=None, payload={})` and `EventSink` async callback.
- `RuntimeStore` async protocol `.save(checkpoint)` / `.load(session_id)`.
- `RuntimeAdapter` async protocol:
  `start(prompt, model, limits) -> RuntimeResult`,
  `continue_session(session_id, prompt) -> RuntimeResult`,
  `interrupt(session_id) -> bool`,
  `checkpoint(session_id) -> RuntimeCheckpoint`,
  `resume(checkpoint) -> RuntimeSession`, `export(session_id) -> RuntimeCheckpoint`.
- `SQLiteRuntimeStore(path)` implements durable hooks; `.close()` releases it.
- `ToolDispatcher()`, `.register(name, schema, async_handler, description='')`,
  `.definitions`, `await .dispatch(name, arguments, operation_id) -> dict`.
  Handler signature: `async def handler(arguments: dict, operation_id: str) -> dict`.
- `ResponsesRuntime(store=..., dispatcher=None, client=None, event_sink=None)`.
  Supports all RuntimeAdapter methods. Inject a real `AsyncOpenAI` client to control HTTP
  transport/credentials. Otherwise it lazily loads the SDK/key. No missing-output success fallback.
- `CodexRuntime(store=..., cwd=..., allow_local_execution=False,
  allow_unbounded_provider_tokens=False, event_sink=None)` plus async `.close()`.
  Supports all RuntimeAdapter methods; `hard_token_limit=False`, portable checkpoint false.
- `CommandRequest(operation_id=UUID, argv: list[str], cwd='.', timeout_seconds=60,
  max_output_bytes=65536, env={})` and `CommandResult(operation_id, execution_id,
  exit_code, stdout, stderr, stdout_truncated, stderr_truncated)`.
- `SandboxExecutor` async `.run(request)` / `.cancel(operation_id)` protocol.
- `LocalShellExecutor(root, allow_local_execution=False)`: actual POSIX processes,
  `.active_operations`, `.confined_path(path)`, runtime-specific execution UUID.
- `E2BSandboxProvider(api_key=None, template_id=None, timeout_seconds=300)`:
  `await .create()` before `.run`, `.cancel`, `.close`; `.execution_id` is native VM ID.
  `.fork()` explicitly raises CAPABILITY_UNAVAILABLE.
- `CommandJournal(path)` context manager; `.begin(program_id, operation_id, command,
  arguments) -> None | dict` (None means newly reserved; dict means completed replay),
  `.complete(program_id, operation_id, result: dict)`, `.export(program_id) -> list[dict]`.
- `ResearchProgramRunner(journal, executor=None, dispatcher=None, max_commands=100,
  timeout_seconds=30)`: `await .command(program_id, operation_id, name, arguments)` uses
  the journal/broker independently; `await .run(program_id, source)` requires a provider VM.
- `provider_capabilities()` returns an explicitly unconfigured/unqualified registry; callers
  should publish real configured adapter capabilities separately, never infer health from import.

## Integration details that matter

Responses `generation_started` event is emitted after a pending checkpoint is stored and
before `responses.create`. Payload: exact `model`, `input_tokens_reserved`,
`output_tokens_reserved`. The event sink can reserve/veto monetary budget here.
`usage` payload: `model`, `input_tokens`, `output_tokens`, `native_usage`, and for Responses
`response_id`. Operation ID is stable; reconcile idempotently. Native response+usage is persisted
before usage callback, so failed callback delivery can be repaired from the checkpoint. There is
no transactional outbox in this subsystem. Core owns monetary pricing, ledger locking, distributed
worker leases, project access, and external tool/child reservations.

Other Responses event kinds: `tool_completed`, `completed`. Tool operation IDs are
`<session_uuid>:<native_call_id>` so they are stable strings, not necessarily UUIDs. Host handlers
must authorize and budget all side effects. Native opaque spawning is not supplied as a tool.

Responses checkpoints retain full native response items/IDs, function call IDs, usage and
explicit in-flight operation marker. Tool/provider failure, missing usage or request cancellation
can leave `uncertain` status. Do not automatically retry/rewind; reconcile the underlying operation.
A completed snapshot can be resumed with the same session ID. An existing different snapshot
for that ID is rejected; resume is not fork. Export may contain sensitive tool/context data and
must remain project-scoped. The digest is integrity checking, not cryptographic authentication.

SQLite store is persistent but single-owner and synchronous internally. Core can implement the
same async RuntimeStore protocol with its own transactional session table. Core must prevent two
workers from owning the same runtime session. The SQL journal provides atomic reservation of each
program/operation key; a crash after side effect but before completion remains uncertain.

## Genuine SDK interfaces verified

Checked local Codex CLI: `/Applications/ChatGPT.app/Contents/Resources/codex`, version
`0.154.0-alpha.6.2`. `codex features list` shows `multi_agent` and `multi_agent_v2`.
Installed optional packages in the project `.venv` to inspect their actual Python code/signatures:
`openai-codex==0.154.0`, `e2b==2.49.1` (the CLI dependency was installed by the official SDK).
Base environment has `openai==2.54.0`.

Codex uses `AsyncCodex(CodexConfig(...))`, `thread_start`, `thread_resume`,
`AsyncThread.turn`, `AsyncTurnHandle.run`, `AsyncTurnHandle.interrupt`, and `close`.
`TurnResult.usage.total` is native cumulative thread usage; it is not added repeatedly.
`features.multi_agent=false` and `features.multi_agent_v2=false` are set at launch and thread
configuration. Sandbox is `Sandbox.read_only`; approvals are `ApprovalMode.deny_all`.
The installed SDK inherits host environment when spawning app-server. This adapter is restricted
to explicit trusted-worker development use and has no hard native-turn token guarantee.

E2B uses `AsyncSandbox.create(template=exact_id, api_key=..., timeout=...,
allow_internet_access=False, secure=True, envs={})`, native `.sandbox_id`,
`.commands.run(cmd, cwd=..., envs=..., timeout=...)`, `.kill()`, and actual
`CommandExitException` / `TimeoutException` classes. Missing template/key or SDK is unavailable.
One active command per VM permits VM-wide cancellation. Returned output is bounded, although SDK
internal stream buffers are not proven bounded. No fork or portability support is invented.

Official references fetched:
- https://developers.openai.com/codex/sdk/ (redirects to official Learn SDK page)
- https://developers.openai.com/api/docs/guides/function-calling
- https://docs.e2b.dev/sdk-reference/python-sdk/v2.5.0/sandbox_async

Dependency requests sent to parent: `jsonschema>=4,<5`, `openai>=2.54,<3`, and explicit
`e2b>=2.49,<3` in e2b extra. The existing official `openai-codex` optional extra is appropriate.
No project dependency files were edited by this agent.

## Research program execution boundaries

The runner only accepts an available executor declaring provider_vm isolation and network-disabled
operation. LocalShellExecutor is rejected even when opted in. It invokes separate Node subprocesses
inside that VM; the Python API process never evaluates JavaScript. The VM template must be trusted,
credentialless, without control-plane mounts, and without egress. Node `vm` is not used or claimed
as a boundary. The JS wrapper itself is not a security sandbox: it mediates cooperative program
coordination while the Python dispatcher authorizes every untrusted broker request.

`await host(opId, command, args)` yields the next command to Python. A subsequent VM subprocess
replays source with completed host results. Changed source digest under the same program ID and
changed operation identity reject. Replays do not recreate a heap or promise arbitrary recovery;
programs must be deterministic between stable host calls. Arbitrary VM filesystem side effects
are not journaled. Python CommandJournal/ResearchProgramRunner.command is fully usable without VM.

## Verification

Final targeted check commands:

```
.venv/bin/python -m ruff check src/physharness/execution tests/test_execution*.py
.venv/bin/python -m pytest tests/test_execution*.py -q
```

The suite has 27 tests covering:
- Local opt-in, minimal environment, real process output bounds (including invalid UTF-8).
- Traversal/symlink rejection, real timeout, process-group cancellation with spawned-child
  termination checked, concurrent duplicate operation rejection.
- Journal restart/replay without duplicated side effects, command mismatch, unresolved operations,
  invalid results and local-runtime refusal for JavaScript.
- Real Node execution of trusted broker-wrapper fixtures: first command, completed replay,
  mismatched identity, robust serialization of source and prior data.
- Actual OpenAI SDK with HTTP-only fake external responses: native tool IDs/items, usage events,
  artifacts, checkpoint persistence/integrity, token preflight, tool failures, reserved parameter
  rejection, unconfigured status, recovery uncertainty and no missing-output fallback.
- E2B missing config/fork unavailable, Codex hard-cap refusal, unavailable Claude/OpenHands,
  and signature assertions against actual optional installed SDKs.

No live paid model calls or E2B VM creation were performed. Full provider timeout/cancellation,
native Codex restore, VM isolation/egress/template qualification and complete VM-driven program
execution are not certified by these unit tests. No assertion of production readiness is made.
