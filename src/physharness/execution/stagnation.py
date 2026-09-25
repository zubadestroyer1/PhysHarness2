"""Bounded durable signals for repeated terminal reads without new work."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

READ_TOOLS = frozenset(
    {
        "read_scientific_record",
        "history_page",
        "index_page",
        "research_graph_page",
        "read_artifact",
        "read_artifact_chunk",
        "restart_brief",
        "working_context",
        "mailbox_page",
        "read_dependency_bundle",
        "search_knowledge",
        "child_task_status",
        "inspect_verification",
        "wait_for_verification",
        "read_workspace_file",
        "search_library_source",
        "lookup_library_source",
        "lookup_library_declaration",
        # Elaborating a query returns diagnostics; it does not revise source.
        "check_lean_type",
        "joined_children",
        "discussion_page",
        "discussion_posts",
        "read_discussion_post",
        "read_research_message",
        "discussion_updates",
        "research_directory",
        "research_capacity",
    }
)
TERMINAL_READS = frozenset({"tail", "cat", "head", "sed", "rg", "grep", "awk"})
WORK_COMMANDS = frozenset({"lean", "lake", "python", "python3", "pytest", "cargo", "make", "cmake"})
NON_PROGRESS_TOOLS = READ_TOOLS | frozenset(
    {
        "checkpoint_context",
        "checkpoint_research_notes",
        "restore_context",
        "wait_for_tasks",
        "request_handoff",
        "checkpoint_workspace",
        "subscribe_discussion",
        "acknowledge_discussion_updates",
        "publish_research_profile",
        "join_research_team",
        "request_research_capacity",
    }
)
STATE_KEYS = frozenset(
    {
        "progress_epoch",
        "read_counts",
        "seen_work",
        "warned",
        "recovery_requested",
        "recovery_attempted",
        "exhausted",
    }
)
MAX_FINGERPRINTS = 64
VOLATILE_FIELDS = frozenset(
    {
        "operation_id",
        "execution_id",
        "request_id",
        "created_at",
        "updated_at",
        "id",
        "receipt_id",
        "record_id",
        "artifact_id",
    }
)


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _scientific(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _scientific(part) for key, part in value.items() if key not in VOLATILE_FIELDS}
    if isinstance(value, list):
        return [_scientific(part) for part in value]
    return value


def _read_target(arguments: dict[str, Any]) -> dict[str, Any]:
    # Receipt/artifact IDs and terminal paths identify stable read targets.
    return {
        key: value
        for key, value in arguments.items()
        if key not in {"operation_id", "execution_id", "request_id"}
    }


def _work_identity(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> str:
    if name == "write_workspace_file":
        return _hash({"name": name, "content": arguments.get("content")})
    if name == "store_artifact":
        return _hash({"name": name, "content": arguments.get("content")})
    if name == "submit_candidate":
        return _hash({"name": name, "source": arguments.get("source")})
    if name == "verify_candidate":
        return _hash({"name": name, "artifact_id": arguments.get("artifact_id")})
    return _hash({"name": name, "arguments": arguments, "result": _scientific(result)})


def validate_state(state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict) or set(state) - STATE_KEYS:
        raise ValueError("invalid stagnation state")
    epoch = state.get("progress_epoch", 0)
    if type(epoch) is not int or not 0 <= epoch <= 1_000_000:
        raise ValueError("invalid progress epoch")
    counts = state.get("read_counts", {})
    seen = state.get("seen_work", [])
    if (
        not isinstance(counts, dict)
        or len(counts) > MAX_FINGERPRINTS
        or not isinstance(seen, list)
        or len(seen) > MAX_FINGERPRINTS
        or len(set(seen)) != len(seen)
    ):
        raise ValueError("invalid stagnation history")
    if any(
        re.fullmatch(r"[0-9a-f]{64}", key) is None
        or type(value) is not int
        or not 1 <= value <= 1_000_000
        for key, value in counts.items()
    ) or any(
        not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in seen
    ):
        raise ValueError("invalid stagnation fingerprint")
    for field in ("warned", "recovery_requested", "recovery_attempted", "exhausted"):
        if type(state.get(field, False)) is not bool:
            raise ValueError("invalid stagnation flag")
    return dict(state)


def _terminal_read(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> bool:
    if name == "discussion_updates":
        return bool(result.get("items")) and "error" not in result
    if name in {"inspect_verification", "wait_for_verification"}:
        return result.get("status") in {"blocked", "rejected", "verified", "completed", "failed"}
    if name == "joined_children":
        children = result.get("children")
        return (
            isinstance(children, list)
            and bool(children)
            and result.get("pending_ids") == []
            and "error" not in result
        )
    if name == "child_task_status":
        return (
            result.get("all_terminal") is True
            and bool(result.get("children"))
            and "error" not in result
        )
    if name == "run_command":
        return _command_name(arguments) in TERMINAL_READS and result.get("exit_code") == 0
    return name in READ_TOOLS and "error" not in result


def _command_name(arguments: dict[str, Any]) -> str:
    argv = arguments.get("argv")
    if not isinstance(argv, list) or not argv or not isinstance(argv[0], str):
        return ""
    command = argv[0].rsplit("/", 1)[-1]
    if command in {"sh", "bash", "zsh"} and len(argv) >= 3 and argv[1] in {"-c", "-lc"}:
        parts = argv[2].strip().split(maxsplit=1)
        command = parts[0].rsplit("/", 1)[-1] if parts else ""
    return command


def observe(
    state: dict[str, Any], name: str, arguments: dict[str, Any], result: dict[str, Any]
) -> str | None:
    """Update in place and return a signal; lifecycle authority stays external."""
    if not _terminal_read(name, arguments, result):
        if (
            name not in NON_PROGRESS_TOOLS
            and "error" not in result
            and (name != "run_command" or _command_name(arguments) in WORK_COMMANDS)
        ):
            work = _work_identity(name, arguments, result)
            seen = state.setdefault("seen_work", [])
            if work not in seen:
                seen.append(work)
                del seen[:-MAX_FINGERPRINTS]
                state.update(
                    progress_epoch=state.get("progress_epoch", 0) + 1,
                    read_counts={},
                    warned=False,
                    recovery_requested=False,
                    recovery_attempted=False,
                    exhausted=False,
                )
        return None
    # A/B alternation remains visible because counts are per exact terminal
    # observation, not only the immediately previous read.
    fingerprint = _hash(
        {
            "name": name,
            "target": _read_target(arguments),
            "result": _scientific(result),
        }
    )
    counts = state.setdefault("read_counts", {})
    if fingerprint not in counts and len(counts) == MAX_FINGERPRINTS:
        counts.pop(next(iter(counts)))
    counts[fingerprint] = counts.get(fingerprint, 0) + 1
    repeats = counts[fingerprint]
    if state.get("recovery_attempted") and repeats >= 8:
        if not state.get("exhausted"):
            state["exhausted"] = True
            return "recovery_exhausted"
        return None
    if repeats >= 8 and not state.get("recovery_requested") and not state.get("recovery_attempted"):
        state["recovery_requested"] = True
        return "recovery_requested"
    if repeats >= 4 and not state.get("warned"):
        state["warned"] = True
        return "stagnation_warning"
    return None


def successor_state(state: dict[str, Any]) -> dict[str, Any]:
    """Consume the single recovery request when a new native session starts."""
    result = validate_state(state)
    if result.get("recovery_requested"):
        result["recovery_requested"] = False
        result["recovery_attempted"] = True
        result["read_counts"] = {}
        result["warned"] = False
    return result


WARNING_MESSAGE = (
    "Repeated unchanged terminal results; perform substantive new work or revise the approach."
)
RECOVERY_MESSAGE = "Bounded recovery is required before more repeated reads."


def signal_message(signal: str, suggestions: list[str] | None = None) -> str:
    """Agent-visible text for a signal; optional suggestions are listed as options only."""
    text = WARNING_MESSAGE if signal == "stagnation_warning" else RECOVERY_MESSAGE
    if not suggestions:
        return text
    return text + " Options: " + "; ".join(suggestions)
