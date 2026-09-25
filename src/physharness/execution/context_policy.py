"""Explicit, bounded Responses context profiles.

The threshold controls provider compaction within one native session. It never
resets cumulative usage, experiment dollars, elapsed time, or task lineage.
"""

from __future__ import annotations

from typing import Literal

from .types import ExecutionError, ModelConfig, RuntimeLimits

CONTEXT_MARGIN = 8192
STRESS_THRESHOLD = 8192
ContextProfile = Literal["research", "stress8192"]


def maximum_safe_threshold(limits: RuntimeLimits) -> int:
    window = limits.max_context_tokens
    if window is None:
        raise ExecutionError("INVALID_CONFIG", "Context profile requires a finite context window")
    maximum = window - limits.max_output_tokens - CONTEXT_MARGIN
    if maximum < 1:
        raise ExecutionError("INVALID_CONFIG", "Context window leaves no safe compaction threshold")
    return maximum


def apply_context_profile(
    model: ModelConfig, limits: RuntimeLimits, profile: ContextProfile = "research"
) -> ModelConfig:
    """Return a model with a validated profile threshold; respect caller override."""
    if profile not in {"research", "stress8192"}:
        raise ExecutionError("INVALID_CONFIG", "Unknown context profile")
    maximum = maximum_safe_threshold(limits)
    params = dict(model.parameters)
    override = params.get("context_management")
    if override is None:
        window = limits.max_context_tokens
        assert window is not None
        threshold = min((3 * window) // 4, maximum) if profile == "research" else STRESS_THRESHOLD
        params["context_management"] = [{"type": "compaction", "compact_threshold": threshold}]
    else:
        if (
            type(override) is not list
            or len(override) != 1
            or type(override[0]) is not dict
            or override[0].get("type") != "compaction"
            or type(override[0].get("compact_threshold")) is not int
        ):
            raise ExecutionError("INVALID_CONFIG", "Invalid explicit compaction threshold")
        threshold = override[0]["compact_threshold"]
    if not 1 <= threshold <= maximum:
        raise ExecutionError("INVALID_CONFIG", "Compaction threshold exceeds safe context bounds")
    return model.model_copy(update={"parameters": params}, deep=True)
