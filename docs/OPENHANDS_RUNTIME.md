# OpenHands remote runtime

`physharness.execution.openhands.OpenHandsRuntime` implements the existing `RuntimeAdapter` lifecycle using the official **openhands-sdk 1.47.0** package. The pinned release requires Python 3.12 or later. Its `RemoteWorkspace` and `RemoteConversation` interfaces were inspected in the installed distribution and exercised in transport tests. [Official release](https://pypi.org/project/openhands-sdk/1.47.0/), [conversation API](https://docs.openhands.dev/sdk/api-reference/openhands.sdk.conversation).

The adapter never selects `LocalConversation`, starts an agent server on the host, or creates a local Docker workspace as a fallback. It connects only to an explicitly qualified remote VM. The SDK itself serializes a `LocalWorkspace` description **for the server**; this does not execute a local workspace operation in the client. [Official remote conversation implementation](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/conversation/impl/remote_conversation.py).

## Required deployment boundary

Default construction is unavailable. A caller must supply all of:

- `qualification: RemoteVMQualification`, binding an HTTPS origin, execution ID, immutable image digest, qualification record ID, expected `/server_info` digest, and expiration.
- `qualification_check`, a trusted application authority that independently validates that qualification and returns literal `True`. It is called before execution and while polling. This module does not manufacture attestations, qualify VMs, or treat a server's self-description as proof of isolation.
- Explicit `server_api_key` and `llm_api_key`; no credential environment fallback is used. Provider credentials are intentionally sent only to the qualified remote agent server. HTTP redirects and inherited proxy configuration are disabled, and requests are bound to the exact qualified origin.
- `allow_unbounded_provider_tokens=True`, acknowledging the native token/process-tree limitations described below.
- A dedicated SDK client process with `LOG_AUTO_CONFIG=false` set before its first SDK import and `LITELLM_LOCAL_MODEL_COST_MAP=True`, which avoids LiteLLM's import-time remote pricing fetch. Ambient SDK tracing/automation callbacks and pre-registered tool/agent definitions are refused.

A VM authority must verify the actual execution isolation, image, endpoint, lifetime and resource/network policy. It must also qualify a clean server configuration without unexpected hooks, skills, saved auxiliary model profiles, plugins or delegated agents. SDK 1.47.0 can automatically attach a vision-profile helper based on server-side profile configuration; the client constructor alone cannot prove such configuration is absent. A callback that simply returns `True` is a test fixture, not a production qualification authority. An HTTPS URL or a Docker container alone does not establish a qualified VM.

No live VM qualification authority or provider allocation was exercised during this implementation. Registry availability should therefore continue to distinguish adapter implementation from a qualified deployment.

## Configuration and lifecycle

```python
from physharness.execution.openhands import OpenHandsRuntime
from physharness.execution.types import ModelConfig, RuntimeLimits

# The application supplies these trusted authority/secret-store integrations.
qualification = vm_authority.current_qualification()
runtime = OpenHandsRuntime(
    store=runtime_store,
    qualification=qualification,
    qualification_check=vm_authority.verify,
    server_api_key=server_key,
    llm_api_key=provider_key,
    allow_unbounded_provider_tokens=True,
    working_dir="/workspace",
    native_tools=[],
    native_iterations_per_run=1,
)
result = await runtime.start(prompt, ModelConfig(model=exact_model), RuntimeLimits())
checkpoint = await runtime.export(result.session.id)
await runtime.resume(checkpoint)
continued = await runtime.continue_session(result.session.id, follow_up)
```

The example's authority and secret-store objects are application responsibilities, not included dummy implementations. Keep each native session under an exclusive controller lease; the `RuntimeStore` protocol has no cross-process compare-and-swap operation. The adapter additionally rejects concurrent runs within one instance.

Supported model parameters are `temperature`, `top_p`, `seed`, and `reasoning_effort`. The exact requested model string is passed to the SDK and recorded, and remote agent configuration is checked before and after a run. SDK fallback strategies are left unset and SDK retries are disabled. Native provider parameter adaptation is still controlled by LiteLLM; the deprecated `modify_params` field is not an enforceable per-model control in SDK 1.47.0. SDK-internal reconstruction currently emits deprecation/unsupported warnings about that field even when the adapter does not set it.

Native tools default to an empty requested tool list plus the SDK's `FinishTool`. Optional `TerminalTool` and `FileEditorTool` specifications may be sent to an externally qualified server where those classes are already installed/registered. They are not imported or registered as host executors. Model-controlled parameters cannot install plugins, MCP servers, client-side tools, hooks, or arbitrary tools. This adapter does not bridge the canonical research `ToolDispatcher` into native OpenHands tools.

The implementation calls the real SDK constructor, `send_message`, `run(blocking=False)`, state refresh, `interrupt`, and `close`. It performs complete HTTP history pagination with the SDK's real `Event` parser because the SDK's convenience reconciliation can swallow a request failure and return partial history. A failed history page is an error here. The HTTP client is injected into the pinned `RemoteWorkspace._client` private attribute to enforce origin, proxy and resume-request guards; this integration must be requalified when upgrading the SDK. [Official workspace client](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/workspace/remote/base.py).

## Usage, budgets and completion

Cumulative SDK-reported prompt/output counts and native statistics are preserved. Missing or malformed usage is uncertainty, never zero. Follow-up runs emit only the observed cumulative delta, preventing double counting during normal continuation. Reported usage is retained even when a run ends unsuccessfully. Raw native events preserve conversation/response/tool-call identifiers; final output comes from SDK assistant message text or `FinishAction.message`.

The startup event is `native_generation_started`, with an explicit external-envelope requirement. It is deliberately distinct from the Responses adapter's bounded `generation_started` reservation event. A controller must provision and reconcile the native run's budget separately, using provider billing/VM records when needed; SDK-reported metrics are not independent billing attestation.

`native_iterations_per_run` defaults to one. The full configured server allowance is conservatively charged to `RuntimeSession.turns` on each observed run, even if fewer iterations were used. The adapter refuses another run when that allowance would exceed the remaining `max_turns`. A one-iteration allowance may be insufficient for a multi-step native tool workflow; choose a larger allowance only within the global envelope.

`max_output_tokens` and `max_input_tokens` are passed to the SDK, but **`hard_token_limit=False`**. Native tool/context behavior, auxiliary calls, and descendant programs cannot be given a verified parent-wide token ceiling through this SDK. The adapter checks cumulative totals before a further run; a current run can already have exceeded the limit. **`controlled_spawning=False`**: removing agent tools does not prevent a terminal command in the VM from spawning processes or making further requests.

A server status of `finished`, complete parsed history, valid usage, and successful client cleanup are all required for a completed result. Completion is runtime status only; it does not establish scientific proof, semantic review, novelty, or publication acceptance.

## Native checkpoints and honest recovery

Every dispatch first writes a durable pending operation with the preallocated native conversation UUID. Checkpoints bind the SDK version, qualification, agent configuration, native event history and digest, usage, and status. Credentials are absent from checkpoint configuration and its digest; remote event contents remain sensitive research data and should use branch-private canonical storage.

`checkpoint`/`export` retrieve durable native state, including an uncertain checkpoint for inspection. `resume` verifies bindings and current remote history/usage. It can import into an empty journal for the **same qualified VM and runtime**, but never overwrite a newer durable state. Native exports are **not portable** to another runtime, model configuration, replacement VM, or recreated conversation. Use the separate portable memory module for a cross-model scientific brief.

The official SDK creates a conversation if its attach lookup returns 404. This adapter performs an existence check and also prohibits the creation request during resume, including the race where the conversation disappears between the preflight and SDK lookup. Missing native state is `NATIVE_SESSION_MISSING`, never silent reallocation or restart.

Timeout, cancellation, partial history, missing usage, remote configuration drift, unexpected status or cleanup failure leaves durable uncertainty. Such state cannot be continued or resumed blindly; a controller must reconcile it externally. An interrupt acknowledges a request, not destruction of the VM or all descendant processes. Closing the client deliberately preserves the remote conversation and VM for continuation. Allocation, hard termination, expiration and orphan cleanup belong to the VM authority. Synchronous SDK requests may outlive an async timeout until their I/O limit; the adapter does not claim a hard execution-time bound.

The configured native history bound limits captured history, but the SDK itself may buffer responses before this adapter can reject them. Server-side response and memory limits remain part of deployment qualification. Parent resource-envelope enforcement, cross-process fencing and infrastructure isolation are not inferred from transport test success.

## Validation and scope

The adapter lives in `execution/openhands.py`. Registry/public exports and the optional dependency lock are integrated separately. Temporal compatibility uses the shared runner in `orchestration/sandbox.py`, wired into the production and integration-test workers.

The official package was installed first into `/private/tmp/physharness-openhands-1.47.0`, leaving project dependencies untouched during investigation. The parent subsequently pinned the optional `openhands-sdk==1.47.0` extra. The isolated contract test command was:

```
PYTHONPATH=src LOG_AUTO_CONFIG=false OPENHANDS_SUPPRESS_BANNER=1 LITELLM_LOCAL_MODEL_COST_MAP=True \
/private/tmp/physharness-openhands-1.47.0/bin/python -m pytest -q tests/test_execution_openhands.py
```

Initial result: **22 passed**. The project environment now passes **26 OpenHands tests**, including the additional mixed-SDK compatibility and logging regressions below. Ruff passed. Tests use the real installed SDK models, remote conversation implementation, HTTP protocol and event parser with `httpx.MockTransport`; only WebSocket readiness/delivery is replaced. Regressions cover exact model/IDs, cumulative usage, actual finish actions, fresh-journal import, missing/deleted-on-attach native conversations, timeout recovery refusal, missing usage, failed history pagination, configuration mismatch, qualification revocation/pin mismatch, opaque-budget opt-in, cleanup failures, unsuccessful-run usage preservation, iteration envelopes, rejected local origins, and absence of host workspace execution.

These are **SDK protocol tests**, not live LLM calls, provider billing evidence, VM containment qualification, terminal-tool execution evidence, or completed cloud experiments. Those deployment qualifications remain outstanding.


## Temporal import compatibility

Use `physharness.orchestration.sandbox.workflow_runner()` when constructing a Temporal worker; the production worker and opt-in integration worker already do so. This returns Temporal's normal sandbox with exactly one added pass-through package, `beartype`. It does not mutate SDK defaults or disable workflow sandboxing.

OpenHands imports FastMCP, whose `key_value.aio` dependency installs a process-wide Beartype path loader. That loader consults `beartype.claw` global state even for modules outside its checked package. Temporal normally reloads modules into an isolated module registry; reloading Beartype's own state through the active loader causes a circular import before workflow code can run. Sharing this import infrastructure avoids that recursion while preserving dependency type checks and the reload/isolation of scientific workflow code. OpenHands, Rich, and `physharness` are not passed through.

Separately, the SDK's default `LOG_AUTO_CONFIG=true` can install a process-wide Rich logging handler. Logging a Temporal restriction violation can then trigger Rich imports inside the sandbox. Set **`LOG_AUTO_CONFIG=false` before any OpenHands SDK import** so logging remains application-owned. The adapter refuses missing opt-out and also checks the SDK's captured import-time setting: changing the environment after an unsafe SDK import requires restarting the client process. It does not remove handlers or change process-global import hooks at runtime.

Two fresh-process regressions exercise both SDK-first and runner-first import order, prepare all three real workflow definitions, verify workflow modules are reloaded, and verify Temporal still rejects file opening, socket creation, and `datetime.now()`. A further fresh-process test proves that a late logging opt-out cannot erase prior SDK initialization. These checks establish import compatibility only, not remote containment or live execution qualification.
