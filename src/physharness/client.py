"""Versioned client. Transport failures preserve uncertain mutation identity for reconciliation."""

from typing import Any

import httpx

from .errors import HarnessError


class HarnessClient:
    def __init__(self, base_url: str, token: str, *, transport=None, timeout: float = 30):
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            transport=transport,
        )

    def close(self):
        self.http.close()

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        key: str | None = None,
        params: dict | None = None,
    ) -> Any:
        if method.upper() != "GET" and not key:
            raise HarnessError(
                "IDEMPOTENCY_KEY_REQUIRED",
                "Client mutations require a stable command key.",
                status=422,
            )
        try:
            response = self.http.request(
                method,
                path,
                json=body,
                params=params,
                headers={"Idempotency-Key": key} if key else {},
            )
        except httpx.TransportError as error:
            raise HarnessError(
                "TRANSPORT_UNCERTAIN",
                "The service response could not be obtained.",
                status=503,
                operation_id=key,
                remediation=(
                    "Inspect the server and repeat the same command key and "
                    "inputs; do not invent a replacement key."
                ),
            ) from error
        try:
            result = response.json()
        except ValueError as error:
            raise HarnessError(
                "INVALID_SERVER_RESPONSE", "Service returned a non-JSON response.", status=502
            ) from error
        if response.is_error:
            failure = result.get("error", {})
            raise HarnessError(
                failure.get("code", "REMOTE_FAILURE"),
                failure.get("message", "The service rejected the request."),
                status=response.status_code,
                operation_id=failure.get("operation_id"),
                remediation=failure.get("remediation"),
                retryable=failure.get("retryable", False),
                details=failure.get("details", {}),
            )
        return result

    def status(self):
        return self.request("GET", "/v1/status")

    def list(self, collection: str, *, experiment_id=None):
        allowed = {
            "campaigns",
            "problems",
            "experiments",
            "branches",
            "tasks",
            "claims",
            "artifacts",
            "reviews",
            "sessions",
            "programs",
            "verifications",
            "messages",
        }
        if collection not in allowed:
            raise ValueError("Unknown collection")
        return self.request(
            "GET",
            f"/v1/{collection}",
            params={"experiment_id": experiment_id} if experiment_id else None,
        )
