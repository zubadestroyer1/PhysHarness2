"""The private pilot helper refuses extra arms and exposes only status metadata."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "work/parallel-pilot-2026-09-24/pilot_ops.py"
SPEC = importlib.util.spec_from_file_location("parallel_pilot_ops", SCRIPT)
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


class FakeService:
    def __init__(self):
        self.experiments = {}
        self.problems = {}
        for index, (program, sharing) in enumerate(
            (
                ("quantum", "none"),
                ("quantum", "ideas"),
                ("classical", "none"),
                ("classical", "ideas"),
            )
        ):
            experiment_id = f"experiment-{index}"
            problem_id = f"problem-{program}"
            self.problems[problem_id] = {
                "id": problem_id,
                "program": program,
                "environment_digest": "a" * 64,
            }
            self.experiments[experiment_id] = {
                "id": experiment_id,
                "problem_id": problem_id,
                "status": "created",
                "revision": 1,
                "execution_profile": "formal-research",
                "context_profile": "research",
                "policy": "independent",
                "sharing": sharing,
                "budget": {
                    "max_cost_usd": "24.95",
                    "max_concurrency": 2,
                    "max_runtime_seconds": 86400,
                    "max_tokens": None,
                },
                "runtime_limits": {
                    "max_total_tokens": None,
                    "max_context_tokens": 256000,
                    "max_output_tokens": 64000,
                    "max_turns": 1000,
                    "timeout_seconds": 86400,
                },
                "models": [
                    {
                        "runtime": "responses",
                        "model": "gpt-6-sol",
                        "parameters": {"reasoning": {"effort": "high"}},
                    }
                    for _ in range(2)
                ],
            }

    def get_record(self, kind, identifier, actor):
        return (self.experiments if kind == "experiment" else self.problems)[identifier]

    def list_records(self, kind, actor, experiment_id):
        if kind == "task":
            return [{"id": "task-1", "status": "running", "objective": "SECRET PROMPT"}]
        if kind == "message":
            return [{"body": "SECRET MESSAGE"}]
        if kind == "verification":
            return [
                {
                    "id": "receipt-1",
                    "status": "verified",
                    "assurance": "qualified",
                    "proof_source": "SECRET PROOF",
                }
            ]
        return [{"status": "running", "native_checkpoint": "SECRET CHECKPOINT"}]

    def ledger(self, experiment_id, actor):
        return {"spent_cost_usd": "0", "uncertain_operations": 0}


def config(tmp_path):
    return {
        "project_id": "pilot",
        "private_directory": str(tmp_path / "private"),
        "database_url": "sqlite:///unused",
        "artifact_root": str(tmp_path / "artifacts"),
        "registry": str(tmp_path / "registry.json"),
        "model_prices_file": str(tmp_path / "prices.json"),
        "worker_qualification_file": str(tmp_path / "qualification.json"),
        "docker_host": "unix:///tmp/pilot.sock",
        "worker_image_digest": "sha256:" + "a" * 64,
        "arms": [
            {"label": label, "experiment_id": f"experiment-{i}"}
            for i, label in enumerate(
                (
                    "quantum-independent",
                    "quantum-collaborating",
                    "classical-independent",
                    "classical-collaborating",
                )
            )
        ],
        "aggregate_ceiling_usd": "100.00",
        "probe_envelope_usd": "0.20",
        "arm_ceiling_usd": "24.95",
        "status_file": str(tmp_path / "status.json"),
        "results_directory": str(tmp_path / "private/results"),
    }


def save_config(tmp_path, value):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value))
    return path


def priced_settings():
    return SimpleNamespace(
        model_prices={
            "gpt-6-sol": {
                "input_usd_per_million": "2.50",
                "output_usd_per_million": "10.00",
                "source": "Conservative upper bound",
            }
        }
    )


def test_config_refuses_extra_cost_and_duplicate_arms(tmp_path):
    value = config(tmp_path)
    value["arm_ceiling_usd"] = "25.00"
    with pytest.raises(pilot.PilotFailure) as over:
        pilot.load_config(save_config(tmp_path, value))
    assert over.value.code == "AGGREGATE_CEILING"
    value = config(tmp_path)
    value["arms"][1]["experiment_id"] = value["arms"][0]["experiment_id"]
    with pytest.raises(pilot.PilotFailure) as duplicate:
        pilot.load_config(save_config(tmp_path, value))
    assert duplicate.value.code == "FOUR_UNIQUE_ARMS_REQUIRED"


def test_price_and_arm_contract_reject_unapproved_launch_inputs(tmp_path):
    value = config(tmp_path)
    settings = priced_settings()
    settings.model_prices["gpt-6-sol"]["input_usd_per_million"] = "2.00"
    with pytest.raises(pilot.PilotFailure) as price:
        pilot.validate_prices(settings)
    assert price.value.code == "MODEL_PRICE_INVALID"
    service = FakeService()
    service.experiments["experiment-0"]["models"][0]["parameters"]["service_tier"] = "fast"
    with pytest.raises(pilot.PilotFailure) as contract:
        pilot.validate_arms(value, service, SimpleNamespace())
    assert contract.value.code == "ARM_CONTRACT_MISMATCH"


def test_explicit_settings_ignore_unrelated_pilot_environment(tmp_path, monkeypatch):
    value = config(tmp_path)
    private = Path(value["private_directory"])
    private.mkdir()
    (private / "operator.token").write_text("issued-test-token")
    (private / "auth.json").write_text(
        json.dumps(
            {"issued-test-token": {"id": "operator", "project_id": "pilot", "role": "operator"}}
        )
    )
    Path(value["model_prices_file"]).write_text(json.dumps(priced_settings().model_prices))
    monkeypatch.setenv("PHYSHARNESS_DATABASE_URL", "sqlite:///wrong.db")
    settings, actor = pilot.operator_settings(value)
    assert settings.database_url == "sqlite:///unused"
    assert actor.id == "operator"


def test_snapshot_allowlist_omits_prompts_messages_and_proofs(tmp_path):
    value = config(tmp_path)
    service = FakeService()
    arm = pilot.validate_arms(value, service, SimpleNamespace())[0]
    text = json.dumps(pilot.snapshot(value, service, SimpleNamespace(), arm, "running"))
    assert "SECRET" not in text
    assert "message_count" in text and "receipt-1" in text


def test_snapshot_counts_attached_and_detached_delegations_once(tmp_path):
    value = config(tmp_path)
    service = FakeService()
    original = service.list_records

    def records(kind, actor, experiment_id):
        if kind == "task":
            return [
                {"id": "root", "status": "completed"},
                {
                    "id": "attached",
                    "status": "completed",
                    "delegated_from_task_id": "root",
                    "reply_to_parent_task_id": "root",
                },
                {
                    "id": "detached",
                    "status": "completed",
                    "delegated_from_task_id": "root",
                    "reply_to_parent_task_id": None,
                },
            ]
        return original(kind, actor, experiment_id)

    service.list_records = records
    arm = pilot.validate_arms(value, service, SimpleNamespace())[0]
    status = pilot.snapshot(value, service, SimpleNamespace(), arm, "completed")
    assert status["delegation_count"] == 2


def test_failed_arm_stops_sequence_and_rerun_refuses_noncreated(tmp_path):
    value = config(tmp_path)
    service = FakeService()
    calls = []

    async def fail_first(config, service, actor, arm, factory):
        calls.append(arm["label"])
        service.experiments[arm["experiment"]["id"]]["status"] = "queued"
        raise pilot.PilotFailure("ARM_NOT_COMPLETED", "supervisor")

    with pytest.raises(pilot.PilotFailure) as failed:
        pilot.launch(value, service, SimpleNamespace(), priced_settings(), run_arm=fail_first)
    assert failed.value.code == "ARM_NOT_COMPLETED"
    assert calls == ["quantum-independent"]
    with pytest.raises(pilot.PilotFailure) as replay:
        pilot.launch(value, service, SimpleNamespace(), priced_settings(), run_arm=fail_first)
    assert replay.value.code == "ARM_CONTRACT_MISMATCH"
    assert calls == ["quantum-independent"]


def test_status_command_reads_file_without_service_or_token(tmp_path, monkeypatch, capsys):
    value = config(tmp_path)
    Path(value["status_file"]).write_text('{"stage":"running"}')
    path = save_config(tmp_path, value)
    monkeypatch.setattr(pilot, "operator_settings", lambda _: pytest.fail("accessed token"))
    assert pilot.main(["status", "--config", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["stage"] == "running"


def test_run_one_preflight_blocks_before_start_or_seed(tmp_path, monkeypatch):
    value = config(tmp_path)
    Path(value["worker_qualification_file"]).write_text("qualified fixture")
    service = FakeService()
    arm = pilot.validate_arms(value, service, SimpleNamespace())[0]
    seen = []

    def preflight(*args, **kwargs):
        seen.append(kwargs["requested_concurrency"])
        return {"status": "blocked"}

    monkeypatch.setattr(pilot, "run_preflight", preflight)
    monkeypatch.setattr(pilot, "configured_workspace_factory", lambda settings: object())
    service.transition_experiment = lambda *args: pytest.fail("started before preflight")
    settings = priced_settings()
    settings.model_copy = lambda **kwargs: settings
    with pytest.raises(pilot.PilotFailure) as blocked:
        asyncio.run(
            pilot.run_one(
                value,
                service,
                SimpleNamespace(),
                arm,
                {"settings": settings},
            )
        )
    assert blocked.value.code == "PREFLIGHT_BLOCKED"
    assert seen == [2]
