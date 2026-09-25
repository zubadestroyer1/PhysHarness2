"""Offline operator safety checks; these tests never reach a model or VM."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

PATH = Path(__file__).resolve().parents[1] / "work/research-effectiveness-2026-09-23/pilot_ops.py"
SPEC = importlib.util.spec_from_file_location("effectiveness_pilot", PATH)
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


def test_exact_two_target_contract_and_research_threshold():
    from physharness.execution.context_policy import apply_context_profile
    from physharness.execution.types import ModelConfig, RuntimeLimits

    for problem_id in pilot.TARGETS.values():
        request = pilot._request({"id": problem_id, "campaign_id": "campaign"})
        assert request.models[0].model == "gpt-6-sol"
        assert request.models[0].parameters == {"reasoning": {"effort": "high"}}
        assert request.budget.max_cost_usd == 25
        assert request.budget.max_concurrency == 1
        assert request.budget.max_runtime_seconds == 7200
        assert request.budget.max_tokens is None
        assert request.runtime_limits["max_total_tokens"] is None
        assert request.runtime_limits["max_turns"] == 128
        assert request.execution_profile == "formal-research"
        assert request.sharing == "ideas"
        result = apply_context_profile(
            ModelConfig(model="gpt-6-sol", parameters=request.models[0].parameters),
            RuntimeLimits.model_validate(request.runtime_limits),
            request.context_profile,
        )
        assert result.parameters["context_management"][0]["compact_threshold"] == 96000


def test_factory_binds_exact_image_socket_environment_and_qualification(monkeypatch):
    seen = {}

    def select(settings):
        seen.update(settings.__dict__)
        return object()

    monkeypatch.setattr(pilot, "configured_workspace_factory", select)
    settings = SimpleNamespace(model_copy=lambda **kw: SimpleNamespace(**kw["update"]))
    pilot.workspace_factory(settings, {"environment_digest": "a" * 64}, "b" * 64)
    assert seen["worker_image_digest"] == pilot.IMAGE
    assert seen["worker_docker_host"] == pilot.DOCKER_HOST
    assert seen["worker_workspace"].environment_digest == "a" * 64
    assert seen["worker_workspace"].qualification_report_sha256 == "b" * 64
    assert seen["worker_workspace"].cost_bound_usd == 0
    assert seen["worker_workspace"].cost_source == "local_no_external_invoice"


def test_duplicate_attempt_and_other_attempt_refused_without_create(tmp_path, monkeypatch):
    descriptor = {
        "target": "projection",
        "attempt": "one",
        "project_id": "p",
        "experiment_id": "e",
        "task_id": "t",
        "branch_id": "b",
    }
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "harness.db").write_bytes(b"placeholder")
    (tmp_path / "reviewed-import.json").write_text("{}")
    (tmp_path / "projection-attempt.json").write_text(json.dumps(descriptor))
    service = Mock()
    monkeypatch.setattr(pilot, "_service", lambda private: service)
    monkeypatch.setattr(pilot, "_scope", lambda *args: (None, None, None))
    assert pilot.prepare(tmp_path, tmp_path / "source", "p", "projection", "one") == descriptor
    with pytest.raises(pilot.PilotError, match="CAMPAIGN_ALLOCATION_EXHAUSTED"):
        pilot.prepare(tmp_path, tmp_path / "source", "p", "projection", "two")
    service.create_experiment.assert_not_called()


@pytest.mark.asyncio
async def test_run_refuses_ambiguous_replay_before_preflight(monkeypatch):
    exp = {"id": "e", "status": "queued", "campaign_id": "campaign"}
    task = {"id": "t", "status": "queued"}
    monkeypatch.setattr(pilot, "_scope", lambda *args: (exp, task, {}))
    service = Mock()
    service.list_records.return_value = [{"task_id": "t"}]
    preflight = Mock()
    monkeypatch.setattr(pilot, "run_preflight", preflight)
    with pytest.raises(pilot.PilotError, match="RECOVERY_RECONCILIATION_REQUIRED"):
        await pilot.run(
            service, Mock(), {"target": "projection"}, prices={}, environment={}, factory=None
        )
    preflight.assert_not_called()


def test_status_excludes_private_content_and_separates_execution_proof(monkeypatch):
    exp = {"id": "e", "status": "running"}
    task = {"id": "t", "status": "running", "proof_status": "unverified"}
    monkeypatch.setattr(pilot, "_scope", lambda *args: (exp, task, {}))
    monkeypatch.setattr(pilot, "_exact_verified", lambda *args: set())
    monkeypatch.setattr(
        pilot,
        "_handoff_events",
        lambda *args: [{"reason": "joined_children"}, {"reason": "automatic_context_boundary"}],
    )
    service = Mock()
    service.list_records.side_effect = lambda kind, actor, eid: {
        "session": [{"status": "handed_off", "native_context": "SECRET"}],
        "task": [{"id": "t", "delegated_from_task_id": "parent", "private_notes": "SECRET"}],
        "claim": [],
        "verification": [
            {
                "id": "v",
                "status": "verified",
                "assurance": "independent_kernel",
                "diagnostics": "SECRET",
            }
        ],
        "workspace": [{"status": "stopped", "secret": "SECRET"}],
        "workspace_operation": [{"command": "run", "content": "SECRET"}],
        "artifact": [
            {"id": "a1", "artifact_kind": "runtime_event", "content": "SECRET"},
            {"id": "a2", "artifact_kind": "runtime_event", "content": "SECRET"},
            {"id": "a3", "artifact_kind": "runtime_event", "content": "SECRET"},
        ],
    }[kind]
    service.artifact_content.side_effect = [
        json.dumps(
            {
                "kind": "tool_completed",
                "payload": {"name": "run_command", "secret": "SECRET"},
            }
        ).encode(),
        json.dumps({"kind": "provider_compaction_items", "payload": {"count": 2}}).encode(),
        json.dumps({"kind": "compaction", "payload": {"secret": "SECRET"}}).encode(),
    ]
    service.ledger.return_value = {
        "spent_cost_usd": "1.000000",
        "reserved_cost_usd": "0.000000",
        "uncertain_operations": 0,
    }
    result = pilot.status(service, Mock(), {"target": "projection", "attempt": "one"})
    assert result["execution_status"] == "running"
    assert result["proof_status"] == "unverified"
    assert result["receipts"][0]["assurance"] == "independent_kernel"
    assert result["handoffs"] == 2
    assert result["joined_handoffs"] == 1
    assert result["non_join_handoffs"] == 1
    assert result["historical_continuation_mode_count_unknown"] == 2
    assert result["tool_usage"]["workspace_operations"] == 1
    assert result["tool_usage"]["runtime_by_name"] == {"run_command": 1}
    assert result["provider_compaction_items"] == 2
    assert result["pruning_boundaries"] == 1
    assert "SECRET" not in json.dumps(result)


def test_blocked_run_has_nonzero_exit():
    assert pilot.result_exit_code("run", {"status": "blocked"}) == 1
    assert pilot.result_exit_code("run", {"status": "already_terminal"}) == 0


def test_export_writes_and_validates_nonempty_artifact(tmp_path, monkeypatch):
    from physharness.domain import digest_json

    content = b"private candidate bytes"
    sha = hashlib.sha256(content).hexdigest()
    manifest = {
        "format": "physharness.reproduction.v1",
        "records": {"artifact": [{"id": "artifact", "sha256": sha}]},
    }
    manifest["manifest_sha256"] = digest_json(manifest)

    def fake_export(service, actor, descriptor, path):
        path.write_text(json.dumps(manifest))
        return {"experiment_id": "experiment", "manifest_sha256": manifest["manifest_sha256"]}

    monkeypatch.setattr(pilot, "historical", lambda: SimpleNamespace(export_attempt=fake_export))
    service = Mock()
    service.artifact_content.return_value = content
    result = pilot.export(service, Mock(), {}, tmp_path / "export")
    assert result["integrity"] == "artifact_integrity_checked"
    assert result["unique_artifacts_checked"] == 1
    assert (tmp_path / "export" / sha).read_bytes() == content


def test_zero_effect_retry_refuses_runtime_event(monkeypatch):
    exp = {"id": "e", "status": "paused"}
    task = {"id": "t", "status": "blocked"}
    monkeypatch.setattr(pilot, "_scope", lambda *args: (exp, task, {}))
    service = Mock()
    service.ledger.return_value = {
        "max_cost_usd": "25",
        "max_concurrency": 1,
        "spent_cost_usd": "0",
        "reserved_cost_usd": "0",
        "active_workers": 0,
        "uncertain_operations": 0,
        "tokens_reserved": 0,
        "tokens_spent": 0,
    }
    records = {
        "task": [task],
        "session": [{"task_id": "t", "status": "failed", "input_tokens": 0, "output_tokens": 0}],
        "claim": [],
        "verification": [],
        "workspace": [],
        "workspace_operation": [],
        "model_reservation": [],
        "artifact": [{"id": "event", "artifact_kind": "runtime_event"}],
    }
    service.list_records.side_effect = lambda kind, actor, eid: records[kind]
    with pytest.raises(pilot.PilotError, match="RETRY_EFFECTS_PRESENT"):
        pilot._zero_effect_audit(service, Mock(), {"target": "projection"})
    service.transition_experiment.assert_not_called()


def test_retry_preserves_old_descriptor_and_experiment(tmp_path, monkeypatch):
    old = {
        "target": "projection",
        "attempt": "regression-01",
        "project_id": "p",
        "experiment_id": "e",
        "branch_id": "old-branch",
        "task_id": "old-task",
    }
    pilot._write_new(tmp_path / "projection-attempt.json", old)
    original = (tmp_path / "projection-attempt.json").read_bytes()
    exp = {
        "id": "e",
        "status": "paused",
        "revision": 3,
        "campaign_id": "campaign",
        "budget": {"max_cost_usd": "25"},
    }
    service = Mock()
    service.transition_experiment.side_effect = [
        {"id": "e", "revision": 4},
        {"id": "e", "revision": 5},
    ]
    service.create_branch.return_value = {"id": "new-branch"}
    service.create_task.return_value = {"id": "new-task"}
    monkeypatch.setattr(pilot, "_service", lambda private: service)
    monkeypatch.setattr(pilot, "_scope", lambda *args: (exp, {"id": "old-task"}, {}))
    monkeypatch.setattr(pilot, "_zero_effect_audit", lambda *args: {"model_calls": 0})
    monkeypatch.setattr(
        pilot, "_campaign_allocations", lambda *args: {"projection": [exp], "purity": []}
    )
    created = pilot.retry_preflight(tmp_path, "p", "projection", "regression-01", "regression-02")
    assert created["experiment_id"] == "e"
    assert created["task_id"] == "new-task"
    assert created["previous_task_id"] == "old-task"
    assert (tmp_path / "projection-regression-01-descriptor.json").read_bytes() == original
    assert pilot._read_descriptor(tmp_path, "projection") == created
    assert service.transition_experiment.call_count == 2
    assert (
        pilot.retry_preflight(tmp_path, "p", "projection", "regression-01", "regression-02")
        == created
    )
    assert service.transition_experiment.call_count == 2


@pytest.mark.parametrize("fault_stage", ["archive", "resume", "task"])
def test_retry_recovers_after_committed_partial_step(tmp_path, monkeypatch, fault_stage):
    old = {
        "target": "projection",
        "attempt": "regression-01",
        "project_id": "p",
        "experiment_id": "e",
        "branch_id": "old-branch",
        "task_id": "old-task",
    }
    pilot._write_new(tmp_path / "projection-attempt.json", old)
    state = {
        "revision": 3,
        "status": "paused",
        "commands": {},
        "branch_creates": 0,
        "task_creates": 0,
        "faulted": False,
    }
    service = Mock()

    def scope(*args):
        exp = {
            "id": "e",
            "revision": state["revision"],
            "status": state["status"],
            "campaign_id": "campaign",
            "budget": {"max_cost_usd": "25"},
        }
        return exp, {"id": "old-task"}, {}

    def transition(eid, action, revision, actor, key):
        if key in state["commands"]:
            return state["commands"][key]
        state["revision"] += 1
        state["status"] = "queued" if action == "resume" else "paused"
        result = {"id": eid, "revision": state["revision"]}
        state["commands"][key] = result
        if fault_stage == "resume" and action == "resume" and not state["faulted"]:
            state["faulted"] = True
            raise RuntimeError("injected")
        return result

    def branch(eid, request, actor, key):
        if key not in state["commands"]:
            state["branch_creates"] += 1
            state["commands"][key] = {"id": "new-branch"}
        return state["commands"][key]

    def task(request, actor, key):
        if key not in state["commands"]:
            state["task_creates"] += 1
            state["commands"][key] = {"id": "new-task"}
            if fault_stage == "task" and not state["faulted"]:
                state["faulted"] = True
                raise RuntimeError("injected")
        return state["commands"][key]

    service.transition_experiment.side_effect = transition
    service.create_branch.side_effect = branch
    service.create_task.side_effect = task
    monkeypatch.setattr(pilot, "_service", lambda private: service)
    monkeypatch.setattr(pilot, "_scope", scope)
    monkeypatch.setattr(pilot, "_zero_effect_audit", lambda *args, **kwargs: {"model_calls": 0})
    monkeypatch.setattr(
        pilot, "_campaign_allocations", lambda *args: {"projection": [scope()[0]], "purity": []}
    )
    monkeypatch.setattr(
        pilot, "_command_result", lambda service, actor, key: state["commands"].get(key)
    )
    if fault_stage == "archive":
        actual_atomic = pilot._atomic_new_bytes

        def interrupted_archive(path, data):
            actual_atomic(path, data)
            if path.name.endswith("-descriptor.json") and not state["faulted"]:
                state["faulted"] = True
                raise RuntimeError("injected")

        monkeypatch.setattr(pilot, "_atomic_new_bytes", interrupted_archive)
    with pytest.raises(RuntimeError, match="injected"):
        pilot.retry_preflight(tmp_path, "p", "projection", "regression-01", "regression-02")
    result = pilot.retry_preflight(tmp_path, "p", "projection", "regression-01", "regression-02")
    assert result["experiment_id"] == "e"
    assert result["task_id"] == "new-task"
    assert state["branch_creates"] == state["task_creates"] == 1
    assert state["revision"] == 5
    assert (tmp_path / "projection-regression-01-descriptor.json").is_file()
    assert (
        pilot.retry_preflight(tmp_path, "p", "projection", "regression-01", "regression-02")
        == result
    )


def test_settled_restart_reuses_experiment_after_prior_retry(tmp_path, monkeypatch):
    prior = {
        "target": "projection",
        "attempt": "regression-02",
        "project_id": "p",
        "experiment_id": "e",
        "branch_id": "branch-2",
        "task_id": "task-2",
        "previous_attempt": "regression-01",
    }
    pilot._write_new(tmp_path / "projection-attempt.json", prior)
    exp = {
        "id": "e",
        "status": "paused",
        "revision": 5,
        "campaign_id": "campaign",
        "budget": {"max_cost_usd": "25"},
    }
    service = Mock()
    service.transition_experiment.side_effect = [
        {"id": "e", "revision": 6},
        {"id": "e", "revision": 7},
    ]
    service.create_branch.return_value = {"id": "branch-3"}
    service.create_task.return_value = {"id": "task-3"}
    monkeypatch.setattr(pilot, "_service", lambda private: service)
    monkeypatch.setattr(pilot, "_scope", lambda *args: (exp, {"id": "task-2"}, {}))
    settled_audit = Mock(return_value={"model_cost_spent_usd": "0.00935"})
    monkeypatch.setattr(pilot, "_settled_effect_audit", settled_audit)
    monkeypatch.setattr(
        pilot, "_campaign_allocations", lambda *args: {"projection": [exp], "purity": []}
    )
    result = pilot.retry_preflight(
        tmp_path, "p", "projection", "regression-02", "regression-03", settled=True
    )
    assert result["experiment_id"] == "e"
    assert result["task_id"] == "task-3"
    assert result["restart_mode"] == "settled"
    assert result["restart_audit"]["model_cost_spent_usd"] == "0.00935"
    settled_audit.assert_called_once()
    service.create_experiment.assert_not_called()


def test_settled_restart_refuses_reserved_budget(monkeypatch):
    from datetime import UTC, datetime

    exp = {
        "id": "e",
        "status": "paused",
        "started_at": datetime.now(UTC).isoformat(),
        "budget": {"max_runtime_seconds": 7200},
    }
    monkeypatch.setattr(pilot, "_scope", lambda *args: (exp, {"id": "t"}, {}))
    service = Mock()
    service.ledger.return_value = {
        "max_cost_usd": "25",
        "max_concurrency": 1,
        "spent_cost_usd": "0.00935",
        "reserved_cost_usd": "0.000001",
        "active_workers": 0,
        "uncertain_operations": 0,
        "tokens_reserved": 0,
    }
    with pytest.raises(pilot.PilotError, match="RESTART_LEDGER_UNSETTLED"):
        pilot._settled_effect_audit(service, Mock(), {"target": "projection"})
    service.list_records.assert_not_called()
