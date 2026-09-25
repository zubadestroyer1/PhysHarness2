"""Public execution contracts, independent of API/database models."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def identifier() -> str:
    return str(uuid4())


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class ExecutionError(Exception):
    """Safe public error; provider exception details remain in the exception chain."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        operation_id: str | None = None,
        retryable: bool = False,
        remediation: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.operation_id = operation_id
        self.retryable = retryable
        self.remediation = remediation

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "operation_id": self.operation_id,
            "retryable": self.retryable,
            "remediation": self.remediation,
            "details": {},
        }


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelConfig(Record):
    model: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("model")
    @classmethod
    def exact_nonempty(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("model must be an exact nonempty identifier without whitespace")
        return value


class RuntimeLimits(Record):
    max_turns: int = Field(default=8, ge=1, le=1000)
    max_output_tokens: int = Field(default=4096, ge=1)
    # None delegates the cumulative ceiling to the shared dollar/time budget.
    # A numeric guard remains cumulative across compaction and continuation.
    max_total_tokens: int | None = Field(default=32768, ge=1)
    max_context_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: float = Field(default=300, gt=0, le=86400)


class Capabilities(Record):
    available: bool
    reason: str | None = None
    start: bool = False
    continue_session: bool = False
    interrupt: bool = False
    checkpoint: bool = False
    resume: bool = False
    export: bool = False
    fork: bool = False
    portable_checkpoint: bool = False
    controlled_spawning: bool = False
    hard_token_limit: bool = False
    isolation: Literal["none", "development_process", "provider_vm"] = "none"


class RuntimeSession(Record):
    id: str = Field(default_factory=identifier)
    runtime: str
    model: ModelConfig
    limits: RuntimeLimits
    status: Literal[
        "ready", "running", "completed", "interrupted", "failed", "uncertain", "handed_off"
    ] = "ready"
    native_session_id: str | None = None
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class RuntimeCheckpoint(Record):
    session: RuntimeSession
    native_state: dict[str, Any]
    state_digest: str
    version: Literal[1] = 1

    @classmethod
    def build(cls, session: RuntimeSession, native_state: dict[str, Any]) -> RuntimeCheckpoint:
        data = {"session": session.model_dump(mode="json"), "native_state": native_state}
        return cls(
            session=session.model_copy(deep=True),
            native_state=deepcopy(native_state),
            state_digest=digest(data),
        )

    def verify(self, runtime: str | None = None) -> None:
        expected = digest(
            {"session": self.session.model_dump(mode="json"), "native_state": self.native_state}
        )
        if expected != self.state_digest or (runtime and self.session.runtime != runtime):
            raise ExecutionError(
                "CHECKPOINT_MISMATCH", "Checkpoint integrity or runtime identity mismatch"
            )


class OutputArtifact(Record):
    kind: str = "model_output"
    content: str
    media_type: str = "text/plain"
    digest: str
    provenance: dict[str, Any] = Field(default_factory=dict)


class RuntimeResult(Record):
    session: RuntimeSession
    output_text: str
    artifacts: list[OutputArtifact] = Field(default_factory=list)
    native_items: list[dict[str, Any]] = Field(default_factory=list)
    continuation: dict[str, Any] | None = None
    completion_reason: str | None = None


class RuntimeEvent(Record):
    kind: str
    session_id: str
    operation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


EventSink = Callable[[RuntimeEvent], Awaitable[None]]


class RuntimeStore(Protocol):
    async def save(self, checkpoint: RuntimeCheckpoint) -> None: ...
    async def load(self, session_id: str) -> RuntimeCheckpoint: ...
    async def archive(self, session_id: str, content: dict[str, Any]) -> str: ...
    async def load_archive(self, session_id: str, archive_id: str) -> dict[str, Any]: ...


class RuntimeAdapter(Protocol):
    capabilities: Capabilities

    async def start(
        self, prompt: str, model: ModelConfig, limits: RuntimeLimits
    ) -> RuntimeResult: ...
    async def continue_session(self, session_id: str, prompt: str) -> RuntimeResult: ...
    async def interrupt(self, session_id: str) -> bool: ...
    async def checkpoint(self, session_id: str) -> RuntimeCheckpoint: ...
    async def resume(self, checkpoint: RuntimeCheckpoint) -> RuntimeSession: ...
    async def export(self, session_id: str) -> RuntimeCheckpoint: ...


class CommandRequest(Record):
    operation_id: str = Field(default_factory=identifier)
    argv: list[str] = Field(min_length=1)
    cwd: str = "."
    timeout_seconds: float = Field(default=60, gt=0, le=86400)
    max_output_bytes: int = Field(default=65536, ge=1, le=16_777_216)
    env: dict[str, str] = Field(default_factory=dict)


class CommandResult(Record):
    operation_id: str
    execution_id: str
    exit_code: int
    stdout: str
    stderr: str
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class SandboxExecutor(Protocol):
    capabilities: Capabilities

    async def run(self, request: CommandRequest) -> CommandResult: ...
    async def cancel(self, operation_id: str) -> bool: ...
