"""Small JSON logs usable locally and by OpenTelemetry collectors."""

import json
import logging
import os
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def __init__(self, *, redacted_values=()):
        super().__init__()
        self.redacted_values = sorted(
            {value for value in redacted_values if isinstance(value, str) and value},
            key=len,
            reverse=True,
        )

    def redact(self, value):
        for secret in self.redacted_values:
            value = value.replace(secret, "[REDACTED]")
        return value

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("operation_id", "operation", "error_code", "experiment_id", "task_id"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        # Redact before JSON escaping, including multiline native exception messages.
        return json.dumps(
            {
                key: self.redact(value) if isinstance(value, str) else value
                for key, value in payload.items()
            },
            ensure_ascii=False,
        )


def configure_logging(level: str = "INFO", *, settings=None) -> None:
    secrets = [
        os.environ[name]
        for name in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "E2B_API_KEY",
            "PHYSHARNESS_TOKEN",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
        )
        if os.environ.get(name)
    ]
    if settings is not None:
        secrets.extend(settings.auth_tokens)
        secrets.append(settings.database_url)
        if settings.temporal_api_key:
            secrets.append(settings.temporal_api_key.get_secret_value())
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(redacted_values=secrets))
    logger = logging.getLogger("physharness")
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
