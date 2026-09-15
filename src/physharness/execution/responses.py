"""Actual OpenAI Responses tool loop with durable checkpoints and exact models."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

from jsonschema import Draft202012Validator

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
    identifier,
)

ToolHandler = Callable[[dict[str, Any], str], Awaitable[dict[str, Any]]]


class ToolDispatcher:
    """Only explicitly registered, schema-checked host functions are exposed.

    Handlers must authorize project access and reserve any budget before side effects.
    Opaque provider agent-spawning tools are never added implicitly.
    """

    def __init__(self) -> None:
        self._tools: dict[str, tuple[dict[str, Any], ToolHandler]] = {}

    def register(
        self, name: str, schema: dict[str, Any], handler: ToolHandler, description: str = ""
    ) -> None:
        if name in self._tools:
            raise ExecutionError("INVALID_CONFIG", "Duplicate tool registration")
        Draft202012Validator.check_schema(schema)
        self._tools[name] = (
            {
                "type": "function",
                "name": name,
                "parameters": schema,
                "description": description,
                "strict": True,
            },
            handler,
        )

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return [definition for definition, _ in self._tools.values()]

    async def dispatch(
        self, name: str, arguments: dict[str, Any], operation_id: str
    ) -> dict[str, Any]:
        entry = self._tools.get(name)
        if entry is None:
            raise ExecutionError(
                "TOOL_UNAVAILABLE", f"Tool {name!r} is not registered", operation_id=operation_id
            )
        definition, handler = entry
        errors = list(Draft202012Validator(definition["parameters"]).iter_errors(arguments))
        if errors:
            raise ExecutionError(
                "INVALID_TOOL_ARGUMENTS",
                "Tool arguments failed registered schema validation",
                operation_id=operation_id,
            )
        try:
            result = await handler(arguments, operation_id)
            if not isinstance(result, dict):
                raise ValueError("tool result must be a JSON object")
            json.dumps(result, allow_nan=False)
            return result
        except ExecutionError:
            raise
        except Exception as exc:
            raise ExecutionError(
                "TOOL_FAILED", f"Tool {name!r} failed", operation_id=operation_id
            ) from exc


class ResponsesRuntime:
    capabilities = Capabilities(
        available=True,
        start=True,
        continue_session=True,
        interrupt=True,
        checkpoint=True,
        resume=True,
        export=True,
        portable_checkpoint=True,
        hard_token_limit=True,
    )
    _allowed_parameters = {
        "instructions",
        "reasoning",
        "text",
        "temperature",
        "top_p",
        "service_tier",
    }

    def __init__(
        self,
        *,
        store: RuntimeStore,
        dispatcher: ToolDispatcher | None = None,
        client: Any = None,
        event_sink: EventSink | None = None,
    ):
        self.store = store
        self.dispatcher = dispatcher or ToolDispatcher()
        self.client = client
        self.event_sink = event_sink
        self._active: dict[str, asyncio.Task[Any]] = {}
        configured = bool(client or os.environ.get("OPENAI_API_KEY"))
        self.capabilities = type(self).capabilities.model_copy(
            update={
                "available": configured,
                "reason": None if configured else "OpenAI API credentials are not configured",
            }
        )

    def _get_client(self) -> Any:
        if self.client is None:
            try:
                from openai import AsyncOpenAI

                self.client = AsyncOpenAI(max_retries=0)
            except Exception as exc:
                raise ExecutionError(
                    "PROVIDER_UNAVAILABLE",
                    "OpenAI SDK or API credentials unavailable",
                    remediation="Install openai>=2.54,<3 and configure OPENAI_API_KEY",
                ) from exc
        return self.client

    async def _emit(
        self, kind: str, session: RuntimeSession, operation_id: str | None = None, **payload: Any
    ) -> None:
        if self.event_sink:
            await self.event_sink(
                RuntimeEvent(
                    kind=kind, session_id=session.id, operation_id=operation_id, payload=payload
                )
            )

    async def _save(self, session: RuntimeSession, state: dict[str, Any]) -> None:
        await self.store.save(RuntimeCheckpoint.build(session, state))

    async def start(self, prompt: str, model: ModelConfig, limits: RuntimeLimits) -> RuntimeResult:
        unknown = model.parameters.keys() - self._allowed_parameters
        if unknown:
            raise ExecutionError(
                "INVALID_CONFIG",
                f"Unsupported or reserved model parameters: {', '.join(sorted(unknown))}",
            )
        session = RuntimeSession(runtime="openai_responses", model=model, limits=limits)
        state: dict[str, Any] = {"input": [], "responses": [], "pending_operation": None}
        await self._save(session, state)
        return await self._run(session, state, prompt)

    async def continue_session(self, session_id: str, prompt: str) -> RuntimeResult:
        checkpoint = await self.checkpoint(session_id)
        if checkpoint.session.status not in {"ready", "completed"}:
            raise ExecutionError(
                "SESSION_NOT_READY", "Session requires explicit reconciliation before continuing"
            )
        return await self._run(checkpoint.session, checkpoint.native_state, prompt)

    async def _run(
        self, session: RuntimeSession, state: dict[str, Any], prompt: str
    ) -> RuntimeResult:
        if session.id in self._active:
            raise ExecutionError("OPERATION_CONFLICT", "Session is already running")
        self._active[session.id] = asyncio.current_task()
        session.status = "running"
        state["input"].append({"role": "user", "content": prompt})
        try:
            async with asyncio.timeout(session.limits.timeout_seconds):
                return await self._loop(session, state)
        except asyncio.CancelledError:
            # Cancelling an HTTP request cannot prove the remote generation stopped.
            session.status = "uncertain" if state.get("pending_operation") else "interrupted"
            await self._save(session, state)
            raise
        except TimeoutError as exc:
            session.status = "uncertain" if state.get("pending_operation") else "failed"
            await self._save(session, state)
            raise ExecutionError(
                "TIMEOUT",
                "Runtime exceeded wall-clock limit",
                operation_id=state.get("pending_operation"),
            ) from exc
        except ExecutionError:
            session.status = "uncertain" if state.get("pending_operation") else "failed"
            await self._save(session, state)
            raise
        except Exception as exc:
            session.status = "uncertain" if state.get("pending_operation") else "failed"
            await self._save(session, state)
            raise ExecutionError(
                "PROVIDER_FAILED",
                "Provider or persistence hook failed; inspect correlated internal error",
                operation_id=state.get("pending_operation"),
            ) from exc
        finally:
            self._active.pop(session.id, None)

    async def _loop(self, session: RuntimeSession, state: dict[str, Any]) -> RuntimeResult:
        client = self._get_client()
        while True:
            if session.turns >= session.limits.max_turns:
                raise ExecutionError("BUDGET_EXHAUSTED", "Session exhausted provider-turn budget")
            params = dict(session.model.parameters)
            count_params = {
                k: v for k, v in params.items() if k in {"instructions", "reasoning", "text"}
            }
            count = await client.responses.input_tokens.count(
                model=session.model.model,
                input=state["input"],
                tools=self.dispatcher.definitions,
                parallel_tool_calls=False,
                **count_params,
            )
            remaining = (
                session.limits.max_total_tokens
                - session.input_tokens
                - session.output_tokens
                - count.input_tokens
            )
            if remaining <= 0:
                raise ExecutionError(
                    "BUDGET_EXHAUSTED", "Token preflight leaves no generation budget"
                )
            operation_id = identifier()
            state["pending_operation"] = operation_id
            await self._save(session, state)
            await self._emit(
                "generation_started",
                session,
                operation_id,
                model=session.model.model,
                input_tokens_reserved=count.input_tokens,
                output_tokens_reserved=min(session.limits.max_output_tokens, remaining),
            )
            response = await client.responses.create(
                model=session.model.model,
                input=state["input"],
                tools=self.dispatcher.definitions,
                parallel_tool_calls=False,
                max_output_tokens=min(session.limits.max_output_tokens, remaining),
                store=False,
                include=["reasoning.encrypted_content"],
                **params,
            )
            native = response.model_dump(mode="json", exclude_none=True)
            state["responses"].append(native)
            session.native_session_id = response.id
            session.turns += 1
            if response.usage is None:
                # Consumption cannot be safely reconciled; preserve the native response.
                await self._save(session, state)
                raise ExecutionError(
                    "USAGE_UNAVAILABLE",
                    "Provider omitted token usage; budget reconciliation required",
                    operation_id=operation_id,
                )
            session.input_tokens += response.usage.input_tokens
            session.output_tokens += response.usage.output_tokens
            state["pending_operation"] = None
            state["input"].extend(native["output"])
            await self._save(session, state)
            await self._emit(
                "usage",
                session,
                operation_id,
                response_id=response.id,
                model=session.model.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                native_usage=response.usage.model_dump(mode="json"),
            )
            if session.input_tokens + session.output_tokens > session.limits.max_total_tokens:
                raise ExecutionError(
                    "PROVIDER_LIMIT_VIOLATION",
                    "Provider reported consumption beyond preflight token reservation",
                )
            if response.status != "completed":
                raise ExecutionError(
                    "PROVIDER_INCOMPLETE", f"Provider response status is {response.status!r}"
                )
            calls = [item for item in native["output"] if item["type"] == "function_call"]
            if not calls:
                text = response.output_text
                if not text:
                    raise ExecutionError("MODEL_OUTPUT_MISSING", "Provider returned no model text")
                session.status = "completed"
                await self._save(session, state)
                artifact = OutputArtifact(
                    content=text,
                    digest=hashlib.sha256(text.encode()).hexdigest(),
                    provenance={
                        "runtime": session.runtime,
                        "model": session.model.model,
                        "session_id": session.id,
                        "response_id": response.id,
                    },
                )
                await self._emit(
                    "completed", session, operation_id, artifact=artifact.model_dump(mode="json")
                )
                return RuntimeResult(
                    session=session,
                    output_text=text,
                    artifacts=[artifact],
                    native_items=native["output"],
                )
            for call in calls:
                tool_operation = f"{session.id}:{call['call_id']}"
                try:
                    arguments = json.loads(call["arguments"])
                    if not isinstance(arguments, dict):
                        raise ValueError("object required")
                except (ValueError, TypeError) as exc:
                    raise ExecutionError(
                        "INVALID_TOOL_ARGUMENTS", "Provider tool arguments are not a JSON object"
                    ) from exc
                state["pending_operation"] = tool_operation
                await self._save(session, state)
                result = await self.dispatcher.dispatch(call["name"], arguments, tool_operation)
                state["input"].append(
                    {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": json.dumps(result, allow_nan=False),
                    }
                )
                state["pending_operation"] = None
                await self._save(session, state)
                await self._emit("tool_completed", session, tool_operation, name=call["name"])

    async def interrupt(self, session_id: str) -> bool:
        task = self._active.get(session_id)
        if task is None:
            return False
        task.cancel()
        return True

    async def checkpoint(self, session_id: str) -> RuntimeCheckpoint:
        checkpoint = await self.store.load(session_id)
        checkpoint.verify("openai_responses")
        return checkpoint

    async def export(self, session_id: str) -> RuntimeCheckpoint:
        return await self.checkpoint(session_id)

    async def resume(self, checkpoint: RuntimeCheckpoint) -> RuntimeSession:
        checkpoint.verify("openai_responses")
        if (
            checkpoint.native_state.get("pending_operation")
            or checkpoint.session.status == "running"
        ):
            raise ExecutionError(
                "OPERATION_UNCERTAIN",
                "Checkpoint has an unresolved operation; reconcile before resuming",
            )
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
