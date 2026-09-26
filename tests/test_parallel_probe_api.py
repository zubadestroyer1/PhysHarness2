import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "work/parallel-pilot-2026-09-24/probe_api.py"
SPEC = importlib.util.spec_from_file_location("parallel_probe_api", SCRIPT)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def config(tmp_path):
    private = tmp_path / "private"
    (tmp_path / "config.json").write_text(json.dumps({"private_directory": str(private)}))
    (tmp_path / "authorization.json").write_text(
        json.dumps(
            {
                "arms": 4,
                "aggregate_ceiling_usd": "100.00",
                "probe_envelope_usd": "0.20",
                "spent_probe_usd": "0",
            }
        )
    )
    return tmp_path / "config.json", private


class FakeClient:
    def __init__(self, count=1000, *, response=None, fail_create=False):
        self.calls = []
        self.count = count
        self.response = response
        self.fail_create = fail_create
        self.responses = SimpleNamespace(
            input_tokens=SimpleNamespace(count=self.count_tokens),
            create=self.create,
        )

    async def count_tokens(self, **kwargs):
        self.calls.append(("count", kwargs))
        return SimpleNamespace(input_tokens=self.count)

    async def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        if self.fail_create:
            raise RuntimeError("mock uncertain transport")
        return self.response


class FakeResponse:
    id = "resp_test"
    model = probe.MODEL
    status = "completed"
    usage = SimpleNamespace(input_tokens=1000, output_tokens=2)

    def model_dump(self, **kwargs):
        return {
            "id": self.id,
            "model": self.model,
            "status": self.status,
            "usage": {"input_tokens": 1000, "output_tokens": 2},
            "output": [],
        }


def test_probe_uses_full_schema_and_refuses_repeat(tmp_path):
    path, private = config(tmp_path)
    fake = FakeClient(response=FakeResponse())
    result = asyncio.run(probe.run_probe(path, client=fake))
    assert result["stage"] == "schema_access_accepted"
    assert result["tool_count"] == 63
    assert [name for name, _ in fake.calls] == ["count", "create"]
    create = fake.calls[1][1]
    assert create["tool_choice"] == "none"
    assert create["max_output_tokens"] == 1024
    assert create["reasoning"] == {"effort": "high"}
    assert len(create["tools"]) == 63
    names = {tool["name"] for tool in create["tools"]}
    assert {
        "return_result",
        "send_message",
        "delegate_detached",
        "wait_for_tasks",
        "peer_availability",
    } <= names
    assert {
        "read_accepted_proof_summary",
        "store_workspace_artifact",
        "submit_workspace_candidate",
        "run_lean_scratch",
        "check_lean_type",
        "lookup_library_declaration",
        "search_library_source",
        "lookup_library_source",
    } <= names
    assert (private / "probe-native.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(probe.ProbeFailure, match="PROBE_ALREADY_ATTEMPTED"):
        asyncio.run(probe.run_probe(path, client=fake))


def test_schema_context_allows_only_two_exact_registration_reads():
    actor = object()
    service = probe.SchemaOnlyService(actor)
    assert service.get_record("experiment", "schema-only", actor) == {"sharing": "ideas"}
    assert service.get_record("task", "schema-only", actor) == {
        "reply_to_parent_task_id": "schema-parent"
    }
    for kind, identifier, principal in (
        ("experiment", "another", actor),
        ("task", "another", actor),
        ("artifact", "schema-only", actor),
        ("experiment", "schema-only", object()),
    ):
        with pytest.raises(probe.ProbeFailure, match="TOOL_HANDLER_INVOKED"):
            service.get_record(kind, identifier, principal)
    with pytest.raises(probe.ProbeFailure, match="TOOL_HANDLER_INVOKED"):
        service.create_artifact({})


def test_probe_refuses_over_budget_before_create(tmp_path):
    path, private = config(tmp_path)
    fake = FakeClient(count=100_000)
    with pytest.raises(probe.ProbeFailure, match="PROBE_COST_LIMIT"):
        asyncio.run(probe.run_probe(path, client=fake))
    assert [name for name, _ in fake.calls] == ["count"]
    assert json.loads((private / "probe-state.json").read_text())["stage"] == "refused"


def test_probe_retains_unknown_request_and_disallows_retry(tmp_path):
    path, private = config(tmp_path)
    fake = FakeClient(fail_create=True)
    with pytest.raises(probe.ProbeFailure, match="PROBE_OPERATION_UNCERTAIN"):
        asyncio.run(probe.run_probe(path, client=fake))
    assert json.loads((private / "probe-state.json").read_text())["stage"] == "unknown"
    with pytest.raises(probe.ProbeFailure, match="PROBE_ALREADY_ATTEMPTED"):
        asyncio.run(probe.run_probe(path, client=fake))


def test_output_cap_incomplete_confirms_schema_access(tmp_path):
    path, private = config(tmp_path)

    class Capped(FakeResponse):
        status = "incomplete"

        def model_dump(self, **kwargs):
            return {
                **super().model_dump(**kwargs),
                "incomplete_details": {"reason": "max_output_tokens"},
            }

    result = asyncio.run(probe.run_probe(path, client=FakeClient(response=Capped())))
    assert result["stage"] == "schema_access_accepted"
    assert result["incomplete_reason"] == "max_output_tokens"
    assert (
        json.loads((private / "probe-state.json").read_text())["code"] == "SCHEMA_ACCESS_ACCEPTED"
    )
