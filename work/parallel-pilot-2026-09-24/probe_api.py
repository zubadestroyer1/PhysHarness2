"""One-shot, bounded Responses schema/access probe; never dispatches a tool."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from types import SimpleNamespace

from openai import AsyncOpenAI

from physharness.orchestration.research_worker import research_tools
from physharness.orchestration.workspace_tools import WorkspaceTools

MODEL = "gpt-6-sol"
OUTPUT_CAP = 1024
PROBE_CEILING = Decimal("0.20")
INPUT_RATE = Decimal("2.50")
OUTPUT_RATE = Decimal("10.00")


class ProbeFailure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class SchemaOnlyService:
    """Exact public catalog context; all effects and other reads stay unavailable."""

    def __init__(self, agent):
        self.agent = agent

    def get_record(self, kind, identifier, actor):
        if actor is self.agent and kind == "experiment" and identifier == "schema-only":
            return {"sharing": "ideas"}
        if actor is self.agent and kind == "task" and identifier == "schema-only":
            return {"reply_to_parent_task_id": "schema-parent"}
        raise ProbeFailure("TOOL_HANDLER_INVOKED")

    def __getattr__(self, name):
        raise ProbeFailure("TOOL_HANDLER_INVOKED")


def now() -> str:
    return datetime.now(UTC).isoformat()


def cost(input_tokens: int, output_tokens: int) -> Decimal:
    if type(input_tokens) is not int or input_tokens < 0:
        raise ProbeFailure("INVALID_INPUT_USAGE")
    if type(output_tokens) is not int or output_tokens < 0:
        raise ProbeFailure("INVALID_OUTPUT_USAGE")
    return ((INPUT_RATE * input_tokens + OUTPUT_RATE * output_tokens) / 1_000_000).quantize(
        Decimal("0.000001"), rounding=ROUND_CEILING
    )


def private_json(path: Path, payload: dict, *, exclusive: bool = False) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if exclusive:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".probe-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def definitions() -> list[dict]:
    # Only registration runs. The two reads describe the widest valid worker catalog.
    workspace = object.__new__(WorkspaceTools)
    workspace.policy = SimpleNamespace(timeout_seconds=86400)
    agent = SimpleNamespace(experiment_id="schema-only")
    dispatcher = research_tools(
        SchemaOnlyService(agent),
        agent,
        "schema-only",
        task_context={"task_id": "schema-only", "holder": "schema-only", "fence": 1},
        workspace_tools=workspace,
    )
    return dispatcher.definitions


def authorize(config_path: Path) -> Path:
    try:
        config = json.loads(config_path.read_text())
        if not isinstance(config, dict) or not isinstance(config.get("private_directory"), str):
            raise ProbeFailure("CONFIG_INVALID")
        authorization = json.loads((config_path.parent / "authorization.json").read_text())
        if (
            authorization.get("arms") != 4
            or Decimal(str(authorization.get("aggregate_ceiling_usd"))) != Decimal("100.00")
            or Decimal(str(authorization.get("probe_envelope_usd"))) != PROBE_CEILING
            or Decimal(str(authorization.get("spent_probe_usd"))) != 0
        ):
            raise ProbeFailure("PROBE_ENVELOPE_UNAVAILABLE")
        return Path(config["private_directory"])
    except (OSError, ValueError, TypeError, KeyError):
        raise ProbeFailure("CONFIG_INVALID") from None


def safe_state(stage: str, **fields) -> dict:
    return {"protocol": "parallel-pilot-schema-probe-v1", "utc": now(), "stage": stage, **fields}


def safe_identifier(value) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", value):
        return value
    return None


async def run_probe(config_path: Path, *, client=None) -> dict:
    private = authorize(config_path)
    state_path = private / "probe-state.json"
    native_path = private / "probe-native.json"
    tools = definitions()
    tools_json = json.dumps(tools, sort_keys=True, separators=(",", ":"), allow_nan=False)
    tool_digest = hashlib.sha256(tools_json.encode()).hexdigest()
    state = safe_state("pending", model=MODEL, tools_digest=tool_digest, tool_count=len(tools))
    try:
        private_json(state_path, state, exclusive=True)
    except FileExistsError:
        raise ProbeFailure("PROBE_ALREADY_ATTEMPTED") from None

    if not os.environ.get("OPENAI_API_KEY") and client is None:
        private_json(state_path, safe_state("refused", code="CREDENTIAL_REQUIRED"))
        raise ProbeFailure("CREDENTIAL_REQUIRED")
    owns_client = client is None
    if client is None:
        client = AsyncOpenAI(max_retries=0)
    request = {
        "model": MODEL,
        "input": "Reply ready.",
        "tools": tools,
        "parallel_tool_calls": False,
        "reasoning": {"effort": "high"},
    }
    create_sent = False
    try:
        counted = await client.responses.input_tokens.count(**request)
        input_count = counted.input_tokens
        upper = cost(input_count, OUTPUT_CAP)
        if upper > PROBE_CEILING:
            private_json(
                state_path,
                safe_state(
                    "refused",
                    code="PROBE_COST_LIMIT",
                    input_tokens_count=input_count,
                    upper_cost_usd=str(upper),
                    tools_digest=tool_digest,
                    tool_count=len(tools),
                ),
            )
            raise ProbeFailure("PROBE_COST_LIMIT")
        state = safe_state(
            "pending_create",
            model=MODEL,
            input_tokens_count=input_count,
            upper_cost_usd=str(upper),
            tools_digest=tool_digest,
            tool_count=len(tools),
        )
        private_json(state_path, state)
        # A crash after this durable state is an unknown paid operation; never rerun it.
        create_sent = True
        response = await client.responses.create(
            **request,
            context_management=[{"type": "compaction", "compact_threshold": 184000}],
            max_output_tokens=OUTPUT_CAP,
            tool_choice="none",
        )
        native = response.model_dump(mode="json", exclude_none=True)
        private_json(native_path, native)
        usage = response.usage
        actual_input = usage.input_tokens if usage else None
        actual_output = usage.output_tokens if usage else None
        actual_ceiling = (
            str(cost(actual_input, actual_output))
            if actual_input is not None and actual_output is not None
            else None
        )
        raw_reason = (
            native.get("incomplete_details", {}).get("reason")
            if isinstance(native.get("incomplete_details"), dict)
            else None
        )
        reason = "max_output_tokens" if raw_reason == "max_output_tokens" else None
        if response.model != MODEL:
            stage, code = "needs_reconciliation", "MODEL_MISMATCH"
        elif usage is None or actual_input > input_count or actual_output > OUTPUT_CAP:
            stage, code = "needs_reconciliation", "USAGE_MISMATCH"
        elif actual_ceiling is not None and Decimal(actual_ceiling) > PROBE_CEILING:
            stage, code = "needs_reconciliation", "PROBE_COST_OVERRUN"
        elif response.status == "completed" or (
            response.status == "incomplete" and reason == "max_output_tokens"
        ):
            stage, code = "schema_access_accepted", "SCHEMA_ACCESS_ACCEPTED"
        else:
            stage, code = "needs_reconciliation", "PROVIDER_INCOMPLETE"
        result = safe_state(
            stage,
            code=code,
            model=MODEL if response.model == MODEL else "mismatch",
            response_id=safe_identifier(response.id),
            response_status=response.status
            if response.status in {"completed", "incomplete"}
            else "other",
            incomplete_reason=reason,
            input_tokens=actual_input,
            output_tokens=actual_output,
            upper_cost_usd=actual_ceiling,
            preflight_upper_cost_usd=str(upper),
            tools_digest=tool_digest,
            tool_count=len(tools),
        )
        private_json(state_path, result)
        return result
    except ProbeFailure:
        raise
    except BaseException:
        private_json(
            state_path,
            safe_state(
                "unknown" if create_sent else "count_unknown",
                code="PROBE_OPERATION_UNCERTAIN",
                tools_digest=tool_digest,
                tool_count=len(tools),
            ),
        )
        raise ProbeFailure("PROBE_OPERATION_UNCERTAIN") from None
    finally:
        if owns_client:
            await client.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(run_probe(args.config))
        print(json.dumps(result, sort_keys=True))
        return 0 if result["stage"] == "schema_access_accepted" else 1
    except ProbeFailure as error:
        print(json.dumps({"stage": "blocked", "code": error.code}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
