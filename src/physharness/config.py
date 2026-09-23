"""Explicit environment configuration; missing production authority fails startup."""

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, SettingsError

from .domain import Principal
from .orchestration.workspace_tools import WorkspacePolicy


class ConfigurationError(ValueError):
    """Safe startup diagnostic: neither values nor secret dictionary keys are retained."""


def _authentication(value):
    try:
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            raise TypeError
        return {
            token: Principal.model_validate(
                principal.model_dump() if isinstance(principal, Principal) else principal
            )
            for token, principal in value.items()
        }
    except (ValueError, TypeError):
        raise ValueError("Invalid authentication configuration; check principal fields.") from None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PHYSHARNESS_", extra="ignore", hide_input_in_errors=True
    )
    mode: Literal["local", "production"] = "local"
    database_url: str = Field(default="sqlite:///.state/harness.db", repr=False)
    artifact_root: Path = Path(".state/artifacts")
    artifact_bucket: str | None = None
    auth_file: Path = Path(".state/auth.json")
    auth_tokens: dict[str, Principal] = Field(default_factory=dict, repr=False)
    auto_create_schema: bool = False
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    temporal_address: str | None = None
    temporal_namespace: str = "default"
    temporal_tls: bool = False
    temporal_api_key: SecretStr | None = None
    model_prices: dict[str, dict] = Field(default_factory=dict)
    e2b_template_id: str | None = None
    worker_workspace: WorkspacePolicy | None = Field(default=None, repr=False)
    temporal_task_queue: str = "physharness-research-v1"
    verification_registry: Path | None = None
    verification_bundle: Path | None = None
    verification_manifest_sha256: str | None = None
    verification_qualification: Path | None = None
    verification_resources: Path | None = None

    def __init__(self, **values):
        try:
            super().__init__(**values)
        except ValidationError as error:
            fields = sorted(
                {
                    str(item["loc"][0])
                    for item in error.errors(include_input=False, include_context=False)
                    if item["loc"] and item["loc"][0] in type(self).model_fields
                }
            )
            # Never forward a nested location, value, or arbitrary upstream message. Tokens
            # are dictionary keys and hide_input_in_errors does not redact those locations.
            label = "authentication" if "auth_tokens" in fields else "deployment"
            raise ConfigurationError(
                f"Invalid {label} configuration; check "
                + (", ".join(fields) if fields else "authentication and deployment requirements")
                + ". Secret values were omitted."
            ) from None
        except (SettingsError, ValueError, TypeError, OSError):
            raise ConfigurationError(
                "Unable to load authentication or deployment configuration; "
                "check JSON syntax and file permissions. Secret values were omitted."
            ) from None

    @field_validator("auth_tokens", mode="before")
    @classmethod
    def validate_authentication(cls, value):
        return _authentication(value)

    @model_validator(mode="after")
    def validate_deployment(self):
        if self.verification_registry and any(
            (
                self.verification_bundle,
                self.verification_manifest_sha256,
                self.verification_qualification,
                self.verification_resources,
            )
        ):
            raise ValueError("Configure either a verifier registry or a single bundle, not both.")
        if self.verification_resources and not all(
            (
                self.verification_bundle,
                self.verification_manifest_sha256,
                self.verification_qualification,
            )
        ):
            raise ValueError("A resource override requires a complete single-bundle verifier.")
        if (
            all(
                (
                    self.verification_bundle,
                    self.verification_manifest_sha256,
                    self.verification_qualification,
                )
            )
            and not self.verification_resources
        ):
            raise ValueError("A single-bundle verifier requires an explicit resource profile.")
        if not self.auth_tokens and self.auth_file.is_file():
            self.auth_tokens = _authentication(json.loads(self.auth_file.read_text()))
        if self.mode == "production":
            if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise ValueError(
                    "Production requires PostgreSQL; SQLite is only a local development backend."
                )
            if not self.artifact_bucket:
                raise ValueError("Production requires configured durable S3 artifact storage.")
            if not self.auth_tokens or any(len(key) < 32 for key in self.auth_tokens):
                raise ValueError(
                    "Production requires configured role-scoped tokens of at least 32 characters."
                )
            if self.auto_create_schema:
                raise ValueError("Production schema changes must run through Alembic migrations.")
        return self
