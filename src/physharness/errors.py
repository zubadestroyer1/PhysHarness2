"""Stable, actionable boundary errors; internal tracebacks stay in correlated logs."""

from typing import Any
from uuid import uuid4


class HarnessError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 409,
        remediation: str = "Inspect the operation and correct its inputs before retrying.",
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        operation_id: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.remediation = remediation
        self.retryable = retryable
        self.details = details or {}
        self.operation_id = operation_id or str(uuid4())

    def envelope(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "operation_id": self.operation_id,
                "retryable": self.retryable,
                "remediation": self.remediation,
                "details": self.details,
            }
        }
