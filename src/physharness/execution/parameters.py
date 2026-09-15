"""Strict Responses request structure, derived from the installed OpenAI SDK types.

This validates protocol shapes and documented numeric ranges, not compatibility
with an individual model. The provider remains authoritative for that support.
Use validate_responses_parameters at public boundaries: it never echoes unknown
keys, user values, schema contents, or raw Pydantic validation details.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from .types import ExecutionError


class _ParameterObject(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class ReasoningParameters(_ParameterObject):
    context: Literal["auto", "current_turn", "all_turns"] | None = None
    effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None
    generate_summary: Literal["auto", "concise", "detailed"] | None = None
    # The SDK declares Union[str, Literal['standard', 'pro']], deliberately open.
    mode: Annotated[str, Field(min_length=1)] = "standard"
    summary: Literal["auto", "concise", "detailed"] | None = None


class PlainTextFormat(_ParameterObject):
    type: Literal["text"]


class JSONObjectFormat(_ParameterObject):
    type: Literal["json_object"]


class JSONSchemaFormat(_ParameterObject):
    type: Literal["json_schema"]
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    schema_: dict[str, JsonValue] = Field(alias="schema")
    description: str = ""
    strict: bool | None = None


class TextParameters(_ParameterObject):
    format: Annotated[
        PlainTextFormat | JSONObjectFormat | JSONSchemaFormat, Field(discriminator="type")
    ] = Field(default_factory=lambda: PlainTextFormat(type="text"))
    verbosity: Literal["low", "medium", "high"] | None = None


class ResponsesParameters(_ParameterObject):
    instructions: str | None = None
    reasoning: ReasoningParameters | None = None
    text: TextParameters = Field(default_factory=TextParameters)
    temperature: Annotated[float, Field(ge=0, le=2, allow_inf_nan=False)] | None = None
    top_p: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    service_tier: Literal["auto", "default", "flex", "scale", "priority", "fast"] | None = None


def validate_responses_parameters(parameters: dict) -> dict:
    """Return supplied fields as independent JSON values or a safe INVALID_CONFIG error."""
    try:
        if type(parameters) is not dict:
            raise ValueError("object required")
        checked = ResponsesParameters.model_validate(parameters)
        result = checked.model_dump(mode="json", by_alias=True, exclude_unset=True)
        # General schema keywords and values remain intact. Non-JSON/NaN content
        # cannot enter checkpoint digests or a provider request through a schema.
        json.dumps(result, allow_nan=False)
        if checked.reasoning is not None and not checked.reasoning.mode.strip():
            raise ValueError("nonempty reasoning mode required")
        return result
    except (ValidationError, ValueError, TypeError, OverflowError, RecursionError):
        raise ExecutionError(
            "INVALID_CONFIG",
            "Responses parameters contain unsupported fields or invalid values.",
            remediation="Check the supported Responses parameter types, enums and numeric ranges.",
        ) from None
