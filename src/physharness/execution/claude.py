"""Official Claude Agent SDK adapter, contract-tested against 0.2.152.

The SDK launches a local CLI and inherits the worker environment. It provides no hard
per-query token cap. Both facts require explicit operator opt-in on a dedicated trusted
worker. Default tools are empty; only confined read tools may be enabled. No tool capable
of spawning an opaque child process is exposed by this adapter.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from .types import (
    Capabilities,
    EventSink,
    ExecutionError,
    ModelConfig,
    OutputArtifact,
    RuntimeCheckpoint,
    RuntimeEvent,
    RuntimeLimits,
    RuntimeResult,
    RuntimeSession,
    RuntimeStore,
)

SUPPORTED_SDK_VERSION = "0.2.152"
READ_TOOLS = frozenset({"Read", "Glob", "Grep"})
DENIED_TOOLS = ["Agent", "Task", "Bash", "Write", "Edit", "NotebookEdit", "Skill", "ToolSearch"]


class ClaudeRuntime:
    def __init__(
        self,
        *,
        store: RuntimeStore,
        cwd: str | Path,
        execution_boundary: Literal["disabled", "trusted_development", "trusted_vm"] = "disabled",
        allow_inherited_environment: bool = False,
        allow_unbounded_provider_tokens: bool = False,
        native_tools: list[str] | None = None,
        max_estimated_cost_usd: float = 1.0,
        max_native_output_bytes: int = 2_000_000,
        worker_id: str | None = None,
        event_sink: EventSink | None = None,
    ):
        self.store, self.cwd = store, str(Path(cwd).resolve(strict=True))
        if not Path(self.cwd).is_dir():
            raise ExecutionError("INVALID_CONFIG", "Claude worker cwd must be a directory")
        if execution_boundary not in {"disabled", "trusted_development", "trusted_vm"}:
            raise ExecutionError("INVALID_CONFIG", "Unknown Claude worker execution boundary")
        self.execution_boundary = execution_boundary
        self.allow_inherited_environment = allow_inherited_environment
        self.allow_unbounded_provider_tokens = allow_unbounded_provider_tokens
        self.native_tools = sorted(set(native_tools or []))
        if set(self.native_tools) - READ_TOOLS:
            raise ExecutionError("CAPABILITY_UNAVAILABLE", "Only confined read tools are supported")
        if not math.isfinite(max_estimated_cost_usd) or max_estimated_cost_usd <= 0:
            raise ExecutionError(
                "INVALID_CONFIG", "A positive estimated session budget is required"
            )
        if not 1024 <= max_native_output_bytes <= 16_000_000:
            raise ExecutionError(
                "INVALID_CONFIG", "Native output bound is outside supported limits"
            )
        self.max_estimated_cost_usd = max_estimated_cost_usd
        self.max_native_output_bytes = max_native_output_bytes
        self.worker_id = worker_id or platform.node()
        self.provider_state_root = str(
            Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).resolve()
        )
        self.event_sink = event_sink
        self._clients: dict[str, Any] = {}
        self._active: set[str] = set()
        installed = importlib.util.find_spec("claude_agent_sdk") is not None
        self.capabilities = Capabilities(
            available=installed
            and execution_boundary != "disabled"
            and allow_inherited_environment
            and allow_unbounded_provider_tokens,
            reason="Trusted-worker, inherited-environment and native-token opt-ins required",
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
            isolation="development_process",
        )

    def _sdk(self):
        if self.execution_boundary == "disabled":
            raise ExecutionError(
                "PROVIDER_UNAVAILABLE", "Claude SDK needs an explicit trusted worker boundary"
            )
        if not self.allow_inherited_environment:
            raise ExecutionError(
                "CAPABILITY_UNAVAILABLE",
                "Claude SDK inherits worker environment and credentials",
                remediation="Use a dedicated worker with intended provider credentials only.",
            )
        if not self.allow_unbounded_provider_tokens:
            raise ExecutionError(
                "CAPABILITY_UNAVAILABLE",
                "Claude SDK cannot enforce hard per-query token limits",
                remediation="Use a bounded API adapter or accept native token-budget uncertainty.",
            )
        try:
            import claude_agent_sdk
        except ImportError as exc:
            raise ExecutionError(
                "PROVIDER_UNAVAILABLE",
                "Official Claude Agent SDK is not installed",
                remediation="Install the existing physharness[claude] optional extra.",
            ) from exc
        if claude_agent_sdk.__version__ != SUPPORTED_SDK_VERSION:
            raise ExecutionError(
                "SDK_UNQUALIFIED",
                "Claude SDK version differs from tested contract",
                remediation=f"Use SDK {SUPPORTED_SDK_VERSION} or requalify this adapter.",
            )
        return claude_agent_sdk

    @staticmethod
    def _params(model):
        if model.model in {"sonnet", "opus", "haiku", "default", "inherit"} or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:/@-]*", model.model
        ):
            raise ExecutionError("INVALID_CONFIG", "Use an exact Claude model identifier")
        if model.parameters.keys() - {"effort", "system_prompt"}:
            raise ExecutionError(
                "INVALID_CONFIG", "Unsupported Claude parameters cannot override execution policy"
            )
        if model.parameters.get("effort") not in {None, "low", "medium", "high", "xhigh", "max"}:
            raise ExecutionError("INVALID_CONFIG", "Unsupported Claude effort")
        if "system_prompt" in model.parameters and not isinstance(
            model.parameters["system_prompt"], str
        ):
            raise ExecutionError("INVALID_CONFIG", "Claude system prompt must be plain text")
        return dict(model.parameters)

    def _options(self, session, state, *, resume):
        sdk = self._sdk()
        return sdk.ClaudeAgentOptions(
            cwd=self.cwd,
            model=session.model.model,
            fallback_model=None,
            session_id=None if resume else session.native_session_id,
            resume=session.native_session_id if resume else None,
            fork_session=False,
            tools=self.native_tools,
            allowed_tools=self.native_tools,
            disallowed_tools=DENIED_TOOLS,
            permission_mode="dontAsk",
            strict_mcp_config=True,
            mcp_servers={},
            setting_sources=[],
            skills=[],
            plugins=[],
            agents={},
            hooks={"PreToolUse": [sdk.HookMatcher(hooks=[self._tool_gate])]},
            max_turns=session.limits.max_turns - session.turns,
            max_budget_usd=self.max_estimated_cost_usd - state["estimated_cost_usd"],
            max_buffer_size=min(self.max_native_output_bytes, 1_000_000),
            stderr=lambda _line: None,
            include_partial_messages=False,
            forward_subagent_text=False,
            **self._params(session.model),
        )

    def _make_client(self, options):
        return self._sdk().ClaudeSDKClient(options=options)

    async def _tool_gate(self, data, _tool_id, _context):
        reason = None
        name = data.get("tool_name")
        if name not in self.native_tools or data.get("agent_id"):
            reason = "Opaque spawning and unconfigured native tools are disabled"
        else:
            inputs = data.get("tool_input", {})
            path_value = inputs.get("file_path") if name == "Read" else inputs.get("path", ".")
            if not isinstance(path_value, str):
                reason = "Tool path is missing or invalid"
            else:
                try:
                    path = (Path(self.cwd) / path_value).resolve()
                    if not path.is_relative_to(self.cwd):
                        reason = "Tool path escapes the trusted worker directory"
                except (OSError, RuntimeError, ValueError):
                    reason = "Tool path could not be resolved"
            for key in ("glob", "pattern" if name == "Glob" else "glob"):
                pattern = inputs.get(key)
                if isinstance(pattern, str) and (
                    pattern.startswith("/") or ".." in Path(pattern).parts
                ):
                    reason = "Glob pattern escapes the trusted worker directory"
        if reason:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        return {}

    async def start(self, prompt: str, model: ModelConfig, limits: RuntimeLimits) -> RuntimeResult:
        sdk = self._sdk()
        self._params(model)
        session = RuntimeSession(runtime="claude", model=model, limits=limits)
        session.native_session_id = session.id
        state = {
            "cwd": self.cwd,
            "worker_id": self.worker_id,
            "provider_state_root": self.provider_state_root,
            "sdk_version": sdk.__version__,
            "native_tools": self.native_tools,
            "estimated_cost_usd": 0.0,
            "native_results": [],
            "pending_operation": None,
        }
        await self.store.save(RuntimeCheckpoint.build(session, state))
        return await self._run(session, state, prompt, resume=False)

    async def continue_session(self, session_id: str, prompt: str) -> RuntimeResult:
        checkpoint = await self.checkpoint(session_id)
        self._validate_resume(checkpoint)
        return await self._run(checkpoint.session, checkpoint.native_state, prompt, resume=True)

    @staticmethod
    def _integer(value):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ExecutionError(
                "USAGE_UNAVAILABLE", "Claude reported missing or invalid token/turn usage"
            )
        return value

    async def _run(self, session, state, prompt, *, resume):
        if not prompt.strip() or prompt.lstrip().startswith("/"):
            raise ExecutionError(
                "INVALID_PROMPT", "Use a nonempty message; native slash commands are disabled"
            )
        if session.id in self._active:
            raise ExecutionError("OPERATION_CONFLICT", "Claude session is already running")
        if (
            session.turns >= session.limits.max_turns
            or session.input_tokens + session.output_tokens >= session.limits.max_total_tokens
            or state["estimated_cost_usd"] >= self.max_estimated_cost_usd
        ):
            raise ExecutionError("BUDGET_EXHAUSTED", "Claude session exhausted its observed budget")
        options = self._options(session, state, resume=resume)
        client = self._make_client(options)
        self._active.add(session.id)
        self._clients[session.id] = client
        operation_id = str(uuid4())
        state["pending_operation"] = operation_id
        session.status = "running"
        messages, final, failure = [], None, None
        try:
            await self.store.save(RuntimeCheckpoint.build(session, state))
            sdk = self._sdk()
            total_bytes = 0
            async with asyncio.timeout(session.limits.timeout_seconds):
                await client.connect()
                await client.query(prompt, session_id=session.native_session_id)
                async for message in client.receive_response():
                    raw = asdict(message)
                    total_bytes += len(json.dumps(raw, default=str).encode())
                    if total_bytes > self.max_native_output_bytes:
                        raise ExecutionError(
                            "OUTPUT_LIMIT",
                            "Claude native output exceeded the configured byte limit",
                        )
                    if isinstance(message, sdk.SystemMessage):
                        if message.subtype == "init":
                            if message.data.get("session_id") != session.native_session_id:
                                raise ExecutionError(
                                    "CHECKPOINT_MISMATCH",
                                    "Claude initialized another native session",
                                )
                            if message.data.get("model") != session.model.model:
                                raise ExecutionError(
                                    "MODEL_MISMATCH", "Claude initialized a different model"
                                )
                            if set(message.data.get("tools", [])) - set(self.native_tools):
                                raise ExecutionError(
                                    "UNCONTROLLED_TOOL",
                                    "Claude initialized unexpected native tools",
                                )
                        raw = {
                            "subtype": message.subtype,
                            "data": {
                                key: message.data[key]
                                for key in ("session_id", "model", "tools", "claude_code_version")
                                if key in message.data
                            },
                        }
                    if isinstance(message, sdk.AssistantMessage):
                        if message.model != session.model.model:
                            raise ExecutionError(
                                "MODEL_MISMATCH", "Claude returned another model's output"
                            )
                        if message.parent_tool_use_id:
                            raise ExecutionError(
                                "UNCONTROLLED_TOOL", "Unexpected opaque subagent output"
                            )
                        for block in message.content:
                            if (
                                isinstance(block, sdk.ToolUseBlock)
                                and block.name not in self.native_tools
                            ):
                                raise ExecutionError(
                                    "UNCONTROLLED_TOOL", "Claude attempted an unconfigured tool"
                                )
                        if message.error:
                            raise ExecutionError(
                                "PROVIDER_FAILED", "Claude assistant reported an API error"
                            )
                    messages.append(raw)
                    if isinstance(message, sdk.ResultMessage):
                        final = message
            if final is None:
                raise ExecutionError("PROVIDER_INCOMPLETE", "Claude ended without a result message")
            if final.session_id != session.native_session_id:
                raise ExecutionError(
                    "CHECKPOINT_MISMATCH", "Claude returned a different native session"
                )
            if final.origin and final.origin.get("kind") != "human":
                raise ExecutionError(
                    "UNCONTROLLED_TOOL", "Claude result originated from an unsolicited native turn"
                )
            usage = final.usage or {}
            inputs = sum(
                self._integer(usage.get(name, 0 if name.startswith("cache_") else None))
                for name in (
                    "input_tokens",
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                )
            )
            outputs = self._integer(usage.get("output_tokens"))
            turns = self._integer(final.num_turns)
            if turns == 0:
                raise ExecutionError(
                    "USAGE_UNAVAILABLE", "Claude did not report a completed native turn"
                )
            if (
                final.total_cost_usd is None
                or not math.isfinite(final.total_cost_usd)
                or final.total_cost_usd < 0
            ):
                raise ExecutionError(
                    "USAGE_UNAVAILABLE", "Claude omitted a valid estimated query cost"
                )
            if final.model_usage and set(final.model_usage) - {session.model.model}:
                raise ExecutionError("MODEL_MISMATCH", "Claude usage includes an unrequested model")
            session.input_tokens += inputs
            session.output_tokens += outputs
            session.turns += turns
            state["estimated_cost_usd"] += final.total_cost_usd
            state["native_results"].append({"operation_id": operation_id, "result": asdict(final)})
            state["pending_operation"] = None
            await self.store.save(RuntimeCheckpoint.build(session, state))
            if self.event_sink:
                await self.event_sink(
                    RuntimeEvent(
                        kind="usage",
                        session_id=session.id,
                        operation_id=operation_id,
                        payload={
                            "model": session.model.model,
                            "input_tokens": inputs,
                            "output_tokens": outputs,
                            "estimated_cost_usd": final.total_cost_usd,
                            "cost_is_estimate": True,
                            "native_session_id": session.native_session_id,
                            "native_usage": usage,
                        },
                    )
                )
            if (
                final.is_error
                or final.subtype != "success"
                or final.terminal_reason in {"aborted_streaming", "aborted_tools"}
            ):
                raise ExecutionError(
                    "PROVIDER_INCOMPLETE", "Claude query failed or was interrupted"
                )
            if not final.result:
                raise ExecutionError("MODEL_OUTPUT_MISSING", "Claude returned no final model text")
            if (
                session.turns > session.limits.max_turns
                or session.input_tokens + session.output_tokens > session.limits.max_total_tokens
                or outputs > session.limits.max_output_tokens
                or state["estimated_cost_usd"] > self.max_estimated_cost_usd
            ):
                raise ExecutionError(
                    "BUDGET_OVERRUN",
                    "Claude exceeded observed limits; native token caps are not enforceable",
                )
            session.status = "completed"
        except BaseException as exc:
            failure = exc
            state["last_error"] = {
                "type": type(exc).__name__,
                "code": getattr(exc, "code", None),
                "operation_id": operation_id,
            }
            try:
                async with asyncio.timeout(5):
                    await client.interrupt()
                state["interrupt_requested"] = True
            except Exception as interrupt_error:
                state["interrupt_error"] = type(interrupt_error).__name__
            session.status = "uncertain" if state["pending_operation"] else "failed"
        finally:
            try:
                async with asyncio.timeout(5):
                    await client.disconnect()
            except Exception as cleanup_error:
                state["cleanup_error"] = type(cleanup_error).__name__
                session.status = "uncertain"
                if failure is None:
                    failure = ExecutionError(
                        "CLEANUP_UNCERTAIN", "Claude CLI cleanup failed; reconcile worker state"
                    )
            self._clients.pop(session.id, None)
            self._active.discard(session.id)
            await self.store.save(RuntimeCheckpoint.build(session, state))
        if failure:
            if isinstance(failure, (ExecutionError, asyncio.CancelledError)):
                raise failure
            if isinstance(failure, TimeoutError):
                raise ExecutionError(
                    "TIMEOUT",
                    "Claude exceeded wall-clock limit; native state needs reconciliation",
                    operation_id=operation_id,
                ) from failure
            if not isinstance(failure, Exception):
                raise failure
            raise ExecutionError(
                "PROVIDER_FAILED",
                "Claude SDK failed; inspect correlated internal error",
                operation_id=operation_id,
            ) from failure
        text = final.result
        artifact = OutputArtifact(
            content=text,
            digest=hashlib.sha256(text.encode()).hexdigest(),
            provenance={
                "runtime": "claude",
                "model": session.model.model,
                "native_session_id": session.native_session_id,
                "operation_id": operation_id,
                "sdk_version": state["sdk_version"],
                "cost_is_estimate": True,
            },
        )
        return RuntimeResult(
            session=session, output_text=text, artifacts=[artifact], native_items=messages
        )

    async def interrupt(self, session_id: str) -> bool:
        client = self._clients.get(session_id)
        if client is None:
            return False
        async with asyncio.timeout(5):
            await client.interrupt()
        return True

    async def checkpoint(self, session_id: str) -> RuntimeCheckpoint:
        checkpoint = await self.store.load(session_id)
        checkpoint.verify("claude")
        return checkpoint

    async def export(self, session_id: str) -> RuntimeCheckpoint:
        return await self.checkpoint(session_id)

    def _validate_resume(self, checkpoint):
        checkpoint.verify("claude")
        state = checkpoint.native_state
        if (
            state.get("cwd") != self.cwd
            or state.get("worker_id") != self.worker_id
            or state.get("provider_state_root") != self.provider_state_root
        ):
            raise ExecutionError(
                "CHECKPOINT_MISMATCH",
                "Claude native checkpoint belongs to another worker or directory",
            )
        if (
            state.get("sdk_version") != SUPPORTED_SDK_VERSION
            or state.get("native_tools") != self.native_tools
        ):
            raise ExecutionError("CHECKPOINT_MISMATCH", "Claude checkpoint SDK/tool policy differs")
        if state.get("pending_operation") or checkpoint.session.status not in {
            "ready",
            "completed",
        }:
            raise ExecutionError(
                "OPERATION_UNCERTAIN", "Claude checkpoint needs native-operation reconciliation"
            )
        if not checkpoint.session.native_session_id:
            raise ExecutionError("CHECKPOINT_MISMATCH", "Claude native session identity is missing")

    async def resume(self, checkpoint: RuntimeCheckpoint) -> RuntimeSession:
        self._validate_resume(checkpoint)
        try:
            current = await self.store.load(checkpoint.session.id)
        except ExecutionError as exc:
            if exc.code != "SESSION_NOT_FOUND":
                raise
        else:
            if current.state_digest != checkpoint.state_digest:
                raise ExecutionError(
                    "CHECKPOINT_MISMATCH", "Resume cannot rewind existing Claude session state"
                )
        await self.store.save(checkpoint)
        return checkpoint.session
