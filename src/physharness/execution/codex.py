"""Optional official openai-codex Python SDK adapter, verified against 0.154.0.

The SDK launches a local app-server and inherits host environment. Use only on a
trusted worker, never on an API host with secrets. Token caps cannot be enforced
inside native turns. Explicit development acknowledgement is required.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

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


class CodexRuntime:
    def __init__(
        self,
        *,
        store: RuntimeStore,
        cwd: str | Path,
        allow_local_execution: bool = False,
        allow_unbounded_provider_tokens: bool = False,
        event_sink: EventSink | None = None,
    ):
        self.store, self.cwd = store, str(Path(cwd).resolve(strict=True))
        self.allow_local_execution = allow_local_execution
        self.allow_unbounded_provider_tokens = allow_unbounded_provider_tokens
        self.event_sink = event_sink
        self._codex: Any = None
        self._turns: dict[str, Any] = {}
        self._active: set[str] = set()
        self.capabilities = Capabilities(
            available=allow_local_execution and allow_unbounded_provider_tokens,
            reason=(
                "Development opt-in required: native turns have no enforceable token cap; "
                "native subagents disabled"
            ),
            start=True,
            continue_session=True,
            interrupt=True,
            checkpoint=True,
            resume=True,
            export=True,
            portable_checkpoint=False,
            controlled_spawning=False,
            hard_token_limit=False,
            isolation="development_process",
        )

    async def _client(self) -> Any:
        if not self.allow_local_execution:
            raise ExecutionError(
                "PROVIDER_UNAVAILABLE",
                "Codex SDK launches a local process; explicit development opt-in required",
            )
        if not self.allow_unbounded_provider_tokens:
            raise ExecutionError(
                "CAPABILITY_UNAVAILABLE",
                "Codex SDK cannot enforce per-turn token caps",
                remediation=(
                    "Use ResponsesRuntime for hard limits; only trusted development may "
                    "opt into unbounded native turns"
                ),
            )
        if self._codex is None:
            try:
                from openai_codex import AsyncCodex, CodexConfig
            except ImportError as exc:
                raise ExecutionError(
                    "PROVIDER_UNAVAILABLE",
                    "Official Codex Python SDK is not installed",
                    remediation="Install physharness[codex] with openai-codex>=0.154",
                ) from exc
            # Verified `codex features list` flags. Do not allow user parameters
            # to override these; external spawning goes through host budget broker.
            config = CodexConfig(
                cwd=self.cwd,
                config_overrides=(
                    "features.multi_agent=false",
                    "features.multi_agent_v2=false",
                ),
            )
            self._codex = AsyncCodex(config)
        return self._codex

    @staticmethod
    def _params(model: ModelConfig) -> dict[str, Any]:
        allowed = {"effort", "output_schema", "service_tier", "summary"}
        if model.parameters.keys() - allowed:
            raise ExecutionError(
                "INVALID_CONFIG",
                "Unsupported Codex model parameters; no silent substitution is allowed",
            )
        return dict(model.parameters)

    async def start(self, prompt: str, model: ModelConfig, limits: RuntimeLimits) -> RuntimeResult:
        self._params(model)
        client = await self._client()
        from openai_codex import ApprovalMode, Sandbox

        try:
            thread = await client.thread_start(
                model=model.model,
                cwd=self.cwd,
                sandbox=Sandbox.read_only,
                approval_mode=ApprovalMode.deny_all,
                config={"features.multi_agent": False, "features.multi_agent_v2": False},
            )
        except Exception as exc:
            raise ExecutionError(
                "PROVIDER_FAILED", "Codex thread creation failed with the exact requested model"
            ) from exc
        session = RuntimeSession(
            runtime="codex", model=model, limits=limits, native_session_id=thread.id
        )
        state = {
            "cwd": self.cwd,
            "native_turns": [],
            "pending_turn": None,
            "native_spawning_disabled": True,
        }
        await self.store.save(RuntimeCheckpoint.build(session, state))
        return await self._run(session, state, thread, prompt)

    async def continue_session(self, session_id: str, prompt: str) -> RuntimeResult:
        checkpoint = await self.checkpoint(session_id)
        await self._validate_resume(checkpoint)
        client = await self._client()
        from openai_codex import ApprovalMode, Sandbox

        thread = await client.thread_resume(
            checkpoint.session.native_session_id,
            model=checkpoint.session.model.model,
            cwd=self.cwd,
            sandbox=Sandbox.read_only,
            approval_mode=ApprovalMode.deny_all,
            config={"features.multi_agent": False, "features.multi_agent_v2": False},
        )
        if thread.id != checkpoint.session.native_session_id:
            raise ExecutionError("CHECKPOINT_MISMATCH", "Codex resumed a different native thread")
        return await self._run(checkpoint.session, checkpoint.native_state, thread, prompt)

    async def _run(
        self, session: RuntimeSession, state: dict[str, Any], thread: Any, prompt: str
    ) -> RuntimeResult:
        if session.id in self._active:
            raise ExecutionError("OPERATION_CONFLICT", "Codex session is already running")
        if (
            session.turns >= session.limits.max_turns
            or session.input_tokens + session.output_tokens >= session.limits.max_total_tokens
        ):
            raise ExecutionError(
                "BUDGET_EXHAUSTED", "Codex session exhausted its observed turn/token budget"
            )
        self._active.add(session.id)
        session.status = "running"
        state["pending_turn"] = "dispatching"
        await self.store.save(RuntimeCheckpoint.build(session, state))
        try:
            async with asyncio.timeout(session.limits.timeout_seconds):
                turn = await thread.turn(
                    prompt, model=session.model.model, **self._params(session.model)
                )
                self._turns[session.id] = turn
                state["pending_turn"] = turn.id
                await self.store.save(RuntimeCheckpoint.build(session, state))
                result = await turn.run()
            items = [item.model_dump(mode="json", by_alias=True) for item in result.items]
            native_usage = (
                result.usage.model_dump(mode="json", by_alias=True) if result.usage else None
            )
            state["native_turns"].append(
                {
                    "id": result.id,
                    "status": result.status.value,
                    "items": items,
                    "usage": native_usage,
                }
            )
            session.turns += 1
            if result.usage is None:
                raise ExecutionError(
                    "USAGE_UNAVAILABLE",
                    "Codex omitted native token usage; reconcile before continuing",
                )
            # SDK usage.total is cumulative across the native thread, including
            # all model calls within a turn. Never add cumulative totals twice.
            previous_input, previous_output = session.input_tokens, session.output_tokens
            session.input_tokens = result.usage.total.input_tokens
            session.output_tokens = result.usage.total.output_tokens
            state["pending_turn"] = None
            await self.store.save(RuntimeCheckpoint.build(session, state))
            if self.event_sink:
                await self.event_sink(
                    RuntimeEvent(
                        kind="usage",
                        session_id=session.id,
                        operation_id=result.id,
                        payload={
                            "model": session.model.model,
                            "input_tokens": session.input_tokens - previous_input,
                            "output_tokens": session.output_tokens - previous_output,
                            "native_usage": native_usage,
                        },
                    )
                )
            if result.status.value != "completed":
                raise ExecutionError("PROVIDER_INCOMPLETE", "Codex turn did not complete")
            if not result.final_response:
                raise ExecutionError("MODEL_OUTPUT_MISSING", "Codex returned no final model text")
            session.status = "completed"
            await self.store.save(RuntimeCheckpoint.build(session, state))
            text = result.final_response
            artifact = OutputArtifact(
                content=text,
                digest=hashlib.sha256(text.encode()).hexdigest(),
                provenance={
                    "runtime": "codex",
                    "model": session.model.model,
                    "native_thread_id": thread.id,
                    "native_turn_id": result.id,
                },
            )
            return RuntimeResult(
                session=session, output_text=text, artifacts=[artifact], native_items=items
            )
        except BaseException as exc:
            if session.id in self._turns:
                try:
                    await self._turns[session.id].interrupt()
                except Exception:
                    pass  # Preserve uncertainty; do not claim cancellation reached the provider.
            session.status = "uncertain" if state["pending_turn"] else "failed"
            await self.store.save(RuntimeCheckpoint.build(session, state))
            if isinstance(exc, (ExecutionError, asyncio.CancelledError)):
                raise
            if isinstance(exc, TimeoutError):
                raise ExecutionError(
                    "TIMEOUT", "Codex turn exceeded wall-clock limit; reconcile native turn"
                ) from exc
            if not isinstance(exc, Exception):
                raise
            raise ExecutionError(
                "PROVIDER_FAILED", "Codex SDK turn failed; inspect correlated internal error"
            ) from exc
        finally:
            self._turns.pop(session.id, None)
            self._active.discard(session.id)

    async def interrupt(self, session_id: str) -> bool:
        turn = self._turns.get(session_id)
        if turn is None:
            return False
        await turn.interrupt()
        return True

    async def checkpoint(self, session_id: str) -> RuntimeCheckpoint:
        checkpoint = await self.store.load(session_id)
        checkpoint.verify("codex")
        return checkpoint

    async def export(self, session_id: str) -> RuntimeCheckpoint:
        return await self.checkpoint(session_id)

    async def _validate_resume(self, checkpoint: RuntimeCheckpoint) -> None:
        checkpoint.verify("codex")
        if checkpoint.native_state.get("cwd") != self.cwd:
            raise ExecutionError(
                "CHECKPOINT_MISMATCH",
                "Codex native checkpoint is tied to the original worker directory",
            )
        if checkpoint.native_state.get("pending_turn") or checkpoint.session.status not in {
            "ready",
            "completed",
        }:
            raise ExecutionError(
                "OPERATION_UNCERTAIN", "Codex checkpoint needs native-turn reconciliation"
            )

    async def resume(self, checkpoint: RuntimeCheckpoint) -> RuntimeSession:
        await self._validate_resume(checkpoint)
        try:
            existing = await self.store.load(checkpoint.session.id)
        except ExecutionError as exc:
            if exc.code != "SESSION_NOT_FOUND":
                raise
        else:
            if existing.state_digest != checkpoint.state_digest:
                raise ExecutionError(
                    "CHECKPOINT_MISMATCH", "Resume cannot rewind an existing session identity"
                )
        await self.store.save(checkpoint)
        return checkpoint.session

    async def close(self) -> None:
        if self._codex:
            await self._codex.close()
            self._codex = None
