"""Official OpenHands SDK 1.47.0, exclusively over qualified remote VM endpoints.

The operator supplies an external qualification verifier; this module does not
invent a VM attestation or provide a local execution fallback. Native token and
process-tree budgets remain opaque and require explicit acceptance.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import ipaddress
import math
import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from .types import (
    Capabilities,
    EventSink,
    ExecutionError,
    ModelConfig,
    RuntimeCheckpoint,
    RuntimeEvent,
    RuntimeLimits,
    RuntimeResult,
    RuntimeSession,
    RuntimeStore,
    digest,
)

SUPPORTED_SDK_VERSION = "1.47.0"
NATIVE_TOOLS = frozenset({"TerminalTool", "FileEditorTool"})
TELEMETRY_ENV = (
    "LMNR_PROJECT_API_KEY",
    "OTEL_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "AUTOMATION_CALLBACK_URL",
)


@dataclass(frozen=True)
class RemoteVMQualification:
    """References for a trusted external qualification authority, never self-issued proof."""

    endpoint: str
    execution_id: str
    image_digest: str
    qualification_id: str
    server_info_sha256: str
    expires_at: float

    def validate(self):
        url = urlsplit(self.endpoint)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
            or url.hostname.lower() in {"localhost", "localhost.localdomain"}
        ):
            raise ExecutionError("VM_UNQUALIFIED", "Use an authenticated HTTPS remote VM origin")
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError:
            address = None
        if address and (address.is_loopback or address.is_unspecified or address.is_link_local):
            raise ExecutionError("VM_UNQUALIFIED", "A host-local endpoint is not a qualified VM")
        if (
            not self.execution_id
            or not self.qualification_id
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", self.image_digest)
            or not re.fullmatch(r"[a-f0-9]{64}", self.server_info_sha256)
            or not math.isfinite(self.expires_at)
            or self.expires_at <= time.time()
        ):
            raise ExecutionError("VM_UNQUALIFIED", "VM qualification is incomplete or expired")


def _agent_digest(payload):
    """Compare SDK configurations without persisting or hashing credential values."""

    def redact(value):
        if isinstance(value, dict):
            return {
                key: "<credential>"
                if key
                in {"api_key", "aws_access_key_id", "aws_secret_access_key", "aws_session_token"}
                else redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    return digest(redact(payload))


class OpenHandsRuntime:
    def __init__(
        self,
        *,
        store: RuntimeStore,
        qualification: RemoteVMQualification | None = None,
        qualification_check: Callable[[RemoteVMQualification], bool] | None = None,
        server_api_key: str | None = None,
        llm_api_key: str | None = None,
        llm_base_url: str | None = None,
        working_dir="/workspace",
        allow_unbounded_provider_tokens=False,
        native_tools=None,
        native_iterations_per_run=1,
        max_native_output_bytes=2_000_000,
        event_sink: EventSink | None = None,
        http_transport: httpx.BaseTransport | None = None,
    ):
        self.store, self.qualification = store, qualification
        self.qualification_check = qualification_check
        self.server_api_key, self.llm_api_key = server_api_key, llm_api_key
        self.llm_base_url, self.working_dir = llm_base_url, working_dir
        self.allow_unbounded_provider_tokens = allow_unbounded_provider_tokens
        self.native_tools = sorted(set(native_tools or []))
        self.native_iterations_per_run = native_iterations_per_run
        self.max_native_output_bytes = max_native_output_bytes
        self.event_sink, self.http_transport = event_sink, http_transport
        self._active: set[str] = set()
        self._connections: dict[str, Any] = {}
        if (
            set(self.native_tools) - NATIVE_TOOLS
            or type(native_iterations_per_run) is not int
            or not 1 <= native_iterations_per_run <= 1000
            or not 1024 <= max_native_output_bytes <= 16_000_000
            or not isinstance(working_dir, str)
            or not working_dir.startswith("/")
            or any(part == ".." for part in working_dir.split("/"))
        ):
            raise ExecutionError(
                "INVALID_CONFIG", "Unsupported remote tool, iteration, or workspace configuration"
            )
        try:
            installed = importlib.metadata.version("openhands-sdk") == SUPPORTED_SDK_VERSION
        except importlib.metadata.PackageNotFoundError:
            installed = False
        self.capabilities = Capabilities(
            available=installed
            and qualification is not None
            and qualification_check is not None
            and bool(server_api_key and llm_api_key)
            and allow_unbounded_provider_tokens,
            reason="External VM qualification required; native token/process budgets are opaque",
            start=True,
            continue_session=True,
            interrupt=True,
            checkpoint=True,
            resume=True,
            export=True,
            fork=False,
            portable_checkpoint=False,
            controlled_spawning=False,
            hard_token_limit=False,
            isolation="provider_vm" if qualification else "none",
        )

    def _gate(self):
        if self.qualification is None or self.qualification_check is None:
            raise ExecutionError(
                "VM_UNQUALIFIED", "An external VM qualification authority is required"
            )
        self.qualification.validate()
        if self.qualification_check(self.qualification) is not True:
            raise ExecutionError("VM_UNQUALIFIED", "The external authority did not qualify this VM")
        if not self.allow_unbounded_provider_tokens:
            raise ExecutionError(
                "CAPABILITY_UNAVAILABLE",
                "OpenHands cannot enforce the parent token/process-tree envelope",
            )
        if not self.server_api_key or not self.llm_api_key:
            raise ExecutionError(
                "PROVIDER_UNAVAILABLE", "Explicit server and provider credentials are required"
            )
        if any(os.environ.get(key) for key in TELEMETRY_ENV):
            raise ExecutionError(
                "SDK_ENVIRONMENT_UNQUALIFIED",
                "Run in a dedicated worker without inherited SDK telemetry or callbacks",
            )
        if os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP", "").lower() != "true":
            raise ExecutionError(
                "SDK_ENVIRONMENT_UNQUALIFIED",
                "Set LITELLM_LOCAL_MODEL_COST_MAP=True to disable remote pricing fetches",
            )
        if os.environ.get("LOG_AUTO_CONFIG", "").lower() != "false":
            raise ExecutionError(
                "SDK_ENVIRONMENT_UNQUALIFIED",
                "Set LOG_AUTO_CONFIG=false before SDK import; worker logging is application-owned",
            )
        try:
            if importlib.metadata.version("openhands-sdk") != SUPPORTED_SDK_VERSION:
                raise ExecutionError(
                    "SDK_UNQUALIFIED", "OpenHands SDK differs from the tested version"
                )
            import openhands.sdk as sdk
        except ImportError as exc:
            raise ExecutionError(
                "PROVIDER_UNAVAILABLE", "Install the pinned official OpenHands SDK"
            ) from exc
        from openhands.sdk.logger.logger import ENV_AUTO_CONFIG
        from openhands.sdk.observability.laminar import should_enable_observability
        from openhands.sdk.subagent.registry import get_registered_agent_definitions
        from openhands.sdk.tool.registry import get_tool_module_qualnames

        if ENV_AUTO_CONFIG:
            raise ExecutionError(
                "SDK_ENVIRONMENT_UNQUALIFIED",
                "SDK was already imported with logging autoconfiguration; restart the worker",
            )
        if (
            should_enable_observability()
            or get_registered_agent_definitions()
            or get_tool_module_qualnames()
        ):
            raise ExecutionError(
                "SDK_ENVIRONMENT_UNQUALIFIED",
                "Use a clean SDK process without ambient tracing or tool/agent registrations",
            )
        return sdk

    def _agent(self, session):
        sdk = self._gate()
        model = session.model
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@-]*", model.model)
            or model.model.lower() in {"default", "latest", "auto"}
            or model.parameters.keys() - {"temperature", "top_p", "seed", "reasoning_effort"}
        ):
            raise ExecutionError(
                "INVALID_CONFIG", "Supply an exact model and supported LLM parameters"
            )
        llm = sdk.LLM(
            model=model.model,
            api_key=self.llm_api_key,
            base_url=self.llm_base_url,
            max_output_tokens=session.limits.max_output_tokens,
            max_input_tokens=session.limits.max_total_tokens,
            num_retries=0,
            timeout=max(1, math.ceil(session.limits.timeout_seconds)),
            fallback_strategy=None,
            drop_params=False,
            log_completions=False,
            extended_thinking_budget=None,
            **{"reasoning_effort": None, **model.parameters},
        )
        from openhands.sdk.tool.spec import Tool

        return sdk.Agent(
            llm=llm,
            tools=[Tool(name=name) for name in self.native_tools],
            include_default_tools=["FinishTool"],
            mcp_config={},
            condenser=None,
            critic=None,
            tool_concurrency_limit=1,
        )

    def _connect(self, session, state, *, create):
        sdk = self._gate()
        agent = self._agent(session)
        if _agent_digest(agent.model_dump(mode="json")) != state["agent_digest"]:
            raise ExecutionError(
                "CHECKPOINT_MISMATCH", "Model or native execution configuration changed"
            )
        qualification = self.qualification
        assert qualification is not None

        def guard(request):
            # The SDK otherwise silently creates a missing conversation on reattach.
            if (
                not create
                and request.method == "POST"
                and request.url.path.rstrip("/") == "/api/conversations"
            ):
                raise ExecutionError(
                    "NATIVE_SESSION_MISSING", "Native resume must never create a replacement"
                )
            expected_origin = httpx.URL(qualification.endpoint)
            if (request.url.scheme, request.url.host, request.url.port) != (
                expected_origin.scheme,
                expected_origin.host,
                expected_origin.port,
            ):
                raise ExecutionError(
                    "REMOTE_IDENTITY_MISMATCH", "SDK request changed the qualified origin"
                )

        client = httpx.Client(
            base_url=qualification.endpoint,
            transport=self.http_transport,
            headers={"X-Session-API-Key": self.server_api_key},
            timeout=httpx.Timeout(min(10, session.limits.timeout_seconds)),
            trust_env=False,
            follow_redirects=False,
            event_hooks={"request": [guard]},
        )
        from openhands.sdk.workspace import RemoteWorkspace

        workspace = RemoteWorkspace(
            host=qualification.endpoint,
            working_dir=self.working_dir,
            api_key=self.server_api_key,
            read_timeout=10,
        )
        # Pinned SDK's documented RemoteWorkspace client is backed by this PrivateAttr.
        # Inject an actual httpx client to enforce origin, proxy and resume-request policy.
        workspace._client = client
        try:
            if digest(workspace.get_server_info()) != qualification.server_info_sha256:
                raise ExecutionError(
                    "REMOTE_IDENTITY_MISMATCH", "Remote server metadata differs from qualification"
                )
            if not create:
                response = client.get(f"/api/conversations/{session.native_session_id}")
                if response.status_code == 404:
                    raise ExecutionError(
                        "NATIVE_SESSION_MISSING", "The native conversation no longer exists"
                    )
                response.raise_for_status()
                self._check_info(response.json(), session, state)
            conversation = sdk.RemoteConversation(
                agent=agent,
                workspace=workspace,
                conversation_id=UUID(session.native_session_id),
                max_iteration_per_run=self.native_iterations_per_run,
                plugins=[],
                callbacks=[],
                hook_config=None,
                visualizer=None,
                secrets=None,
                client_tools=[],
                delete_on_close=False,
            )
            if str(conversation.id) != session.native_session_id:
                raise ExecutionError(
                    "REMOTE_IDENTITY_MISMATCH", "Server replaced the requested conversation ID"
                )
            return conversation, client
        except BaseException:
            client.close()
            raise

    def _check_info(self, info, session, state):
        if (
            info.get("id") != session.native_session_id
            or not isinstance(info.get("agent"), dict)
            or _agent_digest(info["agent"]) != state["agent_digest"]
            or info.get("max_iterations") != self.native_iterations_per_run
            or info.get("client_tools")
            or info.get("hook_config")
            or info.get("workspace", {}).get("working_dir") != self.working_dir
        ):
            raise ExecutionError(
                "REMOTE_CONFIG_MISMATCH",
                "Remote conversation identity, model or execution policy differs",
            )

    def _snapshot(self, connection, session, state, *, require_usage):
        self._gate()
        conversation, client = connection
        info = conversation.state.refresh_from_server()
        self._check_info(info, session, state)
        from openhands.sdk.event import Event

        events, page_id, seen_pages = [], None, set()
        for _ in range(1000):
            response = client.get(
                f"/api/conversations/{session.native_session_id}/events/search",
                params={"limit": 100, **({"page_id": page_id} if page_id else {})},
            )
            response.raise_for_status()
            page = response.json()
            events.extend(
                Event.model_validate(item).model_dump(mode="json") for item in page["items"]
            )
            if len(str(events).encode()) > self.max_native_output_bytes:
                raise ExecutionError(
                    "NATIVE_OUTPUT_LIMIT", "Native history exceeds the configured checkpoint bound"
                )
            page_id = page.get("next_page_id")
            if not page_id:
                break
            if page_id in seen_pages:
                raise ExecutionError("NATIVE_HISTORY_INVALID", "Remote history pagination repeated")
            seen_pages.add(page_id)
        else:
            raise ExecutionError(
                "NATIVE_HISTORY_INVALID", "Remote history exceeds pagination bound"
            )
        usage = None
        if require_usage:
            raw = info.get("stats", {}).get("usage_to_metrics")
            if not isinstance(raw, dict) or not raw:
                raise ExecutionError("USAGE_UNAVAILABLE", "Remote state omitted reported usage")
            inp = out = 0
            for metrics in raw.values():
                tokens = metrics.get("accumulated_token_usage")
                if not isinstance(tokens, dict) or any(
                    type(tokens.get(k)) is not int or tokens[k] < 0
                    for k in ("prompt_tokens", "completion_tokens")
                ):
                    raise ExecutionError(
                        "USAGE_UNAVAILABLE", "Native usage is incomplete; do not assume zero"
                    )
                inp += tokens["prompt_tokens"]
                out += tokens["completion_tokens"]
            from openhands.sdk.conversation.conversation_stats import ConversationStats

            parsed = ConversationStats.model_validate(info["stats"])
            usage = {
                "input_tokens": inp,
                "output_tokens": out,
                "native_stats": parsed.model_dump(mode="json"),
            }
        return info["execution_status"], events, usage

    async def _save(self, session, state):
        await self.store.save(RuntimeCheckpoint.build(session, state))

    async def _close(self, session_id):
        connection = self._connections.pop(session_id, None)
        if connection is None:
            return
        conversation, client = connection
        websocket = getattr(conversation, "_ws_client", None)
        thread = getattr(websocket, "_thread", None)
        try:
            await asyncio.to_thread(conversation.close)
            if thread is not None and thread.is_alive():
                raise ExecutionError("CLEANUP_UNCERTAIN", "SDK websocket thread did not stop")
        finally:
            await asyncio.to_thread(client.close)

    async def start(self, prompt: str, model: ModelConfig, limits: RuntimeLimits):
        self._gate()
        session = RuntimeSession(
            runtime="openhands", model=model, limits=limits, native_session_id=str(uuid4())
        )
        state = {
            "format": "physharness.openhands-native.v1",
            "sdk_version": SUPPORTED_SDK_VERSION,
            "qualification": asdict(self.qualification),
            "agent_digest": _agent_digest(self._agent(session).model_dump(mode="json")),
            "events": [],
            "events_digest": digest([]),
            "usage": None,
            "pending": None,
            "portable": False,
            "turn_accounting": "conservative_server_iteration_allowances",
        }
        await self._save(session, state)
        return await self._run(session, state, prompt, create=True)

    async def _load(self, session_id):
        return self._validate_checkpoint(await self.store.load(session_id))

    def _validate_checkpoint(self, checkpoint):
        checkpoint.verify("openhands")
        state = checkpoint.native_state
        self._gate()
        if (
            state.get("format") != "physharness.openhands-native.v1"
            or state.get("sdk_version") != SUPPORTED_SDK_VERSION
            or state.get("qualification") != asdict(self.qualification)
            or state.get("events_digest") != digest(state.get("events"))
        ):
            raise ExecutionError("CHECKPOINT_MISMATCH", "Native checkpoint binding differs")
        if state.get("pending") or checkpoint.session.status in {"uncertain", "running"}:
            raise ExecutionError(
                "RECOVERY_RECONCILIATION_REQUIRED",
                "An uncertain native call requires external reconciliation, never blind replay",
            )
        return checkpoint.session, state

    async def continue_session(self, session_id, prompt):
        session, state = await self._load(session_id)
        return await self._run(session, state, prompt, create=False)

    async def _run(self, session, state, prompt, *, create):
        self._gate()
        if session.id in self._active:
            raise ExecutionError("SESSION_BUSY", "This native session is already running")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ExecutionError("INVALID_CONFIG", "A nonempty prompt is required")
        if (
            session.turns + self.native_iterations_per_run > session.limits.max_turns
            or session.input_tokens + session.output_tokens >= session.limits.max_total_tokens
        ):
            raise ExecutionError(
                "BUDGET_EXCEEDED", "Remaining envelope cannot fund another native run"
            )
        self._active.add(session.id)
        operation_id = str(uuid4())
        state["pending"] = {"operation_id": operation_id, "prompt_digest": digest(prompt)}
        session.status = "running"
        try:
            # Durable intent precedes every possible remote side effect.
            await self._save(session, state)
            async with asyncio.timeout(session.limits.timeout_seconds):
                connection = await asyncio.to_thread(self._connect, session, state, create=create)
                self._connections[session.id] = connection
                status, prior, _ = await asyncio.to_thread(
                    self._snapshot, connection, session, state, require_usage=False
                )
                if (
                    status not in {"idle", "finished", "paused"}
                    or digest(prior) != state["events_digest"]
                ):
                    raise ExecutionError(
                        "RECOVERY_RECONCILIATION_REQUIRED",
                        "Native server state differs from the checkpoint",
                    )
                if self.event_sink:
                    await self.event_sink(
                        RuntimeEvent(
                            kind="native_generation_started",
                            session_id=session.id,
                            operation_id=operation_id,
                            payload={
                                "runtime": "openhands",
                                "reservation": "external_native_envelope_required",
                            },
                        )
                    )
                await asyncio.to_thread(connection[0].send_message, prompt)
                await asyncio.to_thread(connection[0].run, blocking=False)
                while True:
                    status, events, usage = await asyncio.to_thread(
                        self._snapshot, connection, session, state, require_usage=False
                    )
                    if status != "running":
                        break
                    await asyncio.sleep(0.02)
                status, events, usage = await asyncio.to_thread(
                    self._snapshot, connection, session, state, require_usage=True
                )
                assert usage is not None
                if (
                    usage["input_tokens"] < session.input_tokens
                    or usage["output_tokens"] < session.output_tokens
                ):
                    raise ExecutionError("USAGE_MISMATCH", "Native cumulative usage went backwards")
                new_events = events[len(prior) :]
                if events[: len(prior)] != prior:
                    raise ExecutionError(
                        "NATIVE_HISTORY_INVALID", "Native history changed instead of appending"
                    )
                delta = {
                    "input_tokens": usage["input_tokens"] - session.input_tokens,
                    "output_tokens": usage["output_tokens"] - session.output_tokens,
                }
                state.update(events=events, events_digest=digest(events), usage=usage)
                session.input_tokens, session.output_tokens = (
                    usage["input_tokens"],
                    usage["output_tokens"],
                )
                session.turns += self.native_iterations_per_run
                if self.event_sink:
                    await self.event_sink(
                        RuntimeEvent(
                            kind="usage",
                            session_id=session.id,
                            operation_id=operation_id,
                            payload={**delta, "source": "openhands_cumulative_stats"},
                        )
                    )
                state["last_remote_status"] = status
                if status != "finished":
                    raise ExecutionError(
                        "REMOTE_EXECUTION_FAILED", "Native run did not finish successfully"
                    )
                output = []
                for event in new_events:
                    if event.get("source") == "agent" and event.get("kind") == "MessageEvent":
                        output.extend(
                            item["text"]
                            for item in event["llm_message"]["content"]
                            if item.get("type") == "text"
                        )
                    action = event.get("action") or {}
                    if action.get("kind") == "FinishAction":
                        output.append(action["message"])
                await self._close(session.id)
                state["pending"] = None
                session.status = "completed"
                await self._save(session, state)
                return RuntimeResult(
                    session=session, output_text="\n".join(output), native_items=new_events
                )
        except BaseException as exc:
            session.status = "uncertain"
            state["last_error"] = {
                "type": type(exc).__name__,
                "code": getattr(exc, "code", "REMOTE_EXECUTION_UNCERTAIN"),
            }
            await self._save(session, state)
            try:
                try:
                    await self.interrupt(session.id)
                finally:
                    await self._close(session.id)
            except Exception as cleanup:
                state["cleanup_error"] = {
                    "type": type(cleanup).__name__,
                    "code": getattr(cleanup, "code", "CLEANUP_UNCERTAIN"),
                }
                await self._save(session, state)
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, ExecutionError):
                raise
            raise ExecutionError(
                "REMOTE_EXECUTION_UNCERTAIN",
                "Native call failed or timed out; inspect its durable checkpoint before recovery",
            ) from exc
        finally:
            self._active.discard(session.id)

    async def interrupt(self, session_id):
        self._gate()
        connection = self._connections.get(session_id)
        if connection is None:
            return False
        await asyncio.to_thread(connection[0].interrupt)
        # Request acknowledgement is not a VM/process-tree termination guarantee.
        return True

    async def checkpoint(self, session_id):
        checkpoint = await self.store.load(session_id)
        checkpoint.verify("openhands")
        return checkpoint

    async def export(self, session_id):
        return await self.checkpoint(session_id)

    async def resume(self, checkpoint):
        checkpoint.verify("openhands")
        # First validate supplied state using the same binding checks without overwriting
        # an existing durable record (which may contain a newer uncertain operation).
        try:
            current = await self.store.load(checkpoint.session.id)
        except ExecutionError as exc:
            if exc.code != "SESSION_NOT_FOUND":
                raise
            current = None
        if current is not None and current.state_digest != checkpoint.state_digest:
            raise ExecutionError("CHECKPOINT_MISMATCH", "The durable checkpoint has advanced")
        session, state = self._validate_checkpoint(checkpoint)
        connection = await asyncio.to_thread(self._connect, session, state, create=False)
        self._connections[session.id] = connection
        try:
            status, events, usage = await asyncio.to_thread(
                self._snapshot, connection, session, state, require_usage=True
            )
            if (
                status not in {"idle", "finished", "paused"}
                or digest(events) != state["events_digest"]
                or usage != state["usage"]
            ):
                raise ExecutionError(
                    "RECOVERY_RECONCILIATION_REQUIRED",
                    "Remote history or usage differs from the native checkpoint",
                )
        finally:
            await self._close(session.id)
        if current is None:
            await self._save(session, state)
        return session
