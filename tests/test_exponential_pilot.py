"""Guards for isolated, finite exponential-decay pilot attempts."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_core import setup_experiment

from physharness.domain import Principal
from physharness.errors import HarnessError

SCRIPT = Path(__file__).resolve().parents[1] / "work/exponential-pilot-2026-09-24/runner.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("exponential_runner", SCRIPT)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
PREP_SPEC = importlib.util.spec_from_file_location(
    "exponential_prepare", SCRIPT.with_name("prepare.py")
)
prepare = importlib.util.module_from_spec(PREP_SPEC)
PREP_SPEC.loader.exec_module(prepare)


def manifest(tmp_path):
    attempts = []
    for i in range(7):
        private = tmp_path / f"run-{i}"
        attempts.append(
            {
                "label": f"run-{i}",
                "phase": "calibration" if i < 3 else "comparison",
                "sharing": ("none" if i < 3 or i in (3, 6) else "ideas"),
                "ceiling_usd": "12" if i < 3 else "14",
                "experiment_id": f"experiment-{i}",
                "project_id": f"project-{i}",
                "target_digest": f"{i + 1:064x}",
                "private_directory": str(private),
                "database_url": f"sqlite:///{private / 'harness.db'}",
                "artifact_root": str(private / "artifacts"),
                "status_file": str(private / "status.json"),
                "result_file": str(private / "result.json"),
            }
        )
    return {
        "version": 1,
        "prior_spent_usd": "3.658018",
        "aggregate_ceiling_usd": "100",
        "new_reservation_ceiling_usd": "92",
        "challenge_sha256": "b" * 64,
        "challenge_file": str(tmp_path / "Challenge.lean"),
        "environment_digest": "c" * 64,
        "worker_image_digest": "sha256:" + "d" * 64,
        "verifier_image_digest": "sha256:" + "e" * 64,
        "docker_host": "unix:///tmp/dedicated-pilot.sock",
        "tmp_directory": str(tmp_path / "tmp"),
        "registry": str(tmp_path / "registry.json"),
        "model_prices_file": str(tmp_path / "prices.json"),
        "worker_qualification_file": str(tmp_path / "qualification.json"),
        "calibration_decision_file": str(tmp_path / "calibration-decision.json"),
        "global_lock_file": str(tmp_path / "launch.lock"),
        "deployment_decision_file": str(tmp_path / "deployment-decision.json"),
        "attempts": attempts,
    }


def write_manifest(tmp_path, value):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value))
    return path


def test_budget_schedule_and_run_roots_are_fixed(tmp_path):
    value = manifest(tmp_path)
    assert len(runner.load_manifest(write_manifest(tmp_path, value))["attempts"]) == 7
    value["attempts"][1]["artifact_root"] = value["attempts"][0]["artifact_root"]
    with pytest.raises(runner.PilotFailure, match="RUN_ISOLATION"):
        runner.load_manifest(write_manifest(tmp_path, value))
    value = manifest(tmp_path)
    value["attempts"][0]["ceiling_usd"] = "12.01"
    with pytest.raises(runner.PilotFailure, match="BUDGET_SCHEDULE"):
        runner.load_manifest(write_manifest(tmp_path, value))


def test_calibration_contract_rejects_extra_roots_and_wrong_model(tmp_path):
    config = manifest(tmp_path)
    attempt = config["attempts"][0]
    experiment = {
        "id": attempt["experiment_id"],
        "problem_id": "problem",
        "status": "created",
        "revision": 1,
        "project_id": attempt["project_id"],
        "target_digest": attempt["target_digest"],
        "execution_profile": "formal-research",
        "context_profile": "research",
        "policy": "independent",
        "sharing": "none",
        "budget": {
            "max_cost_usd": "12",
            "max_concurrency": 1,
            "max_runtime_seconds": 2700,
            "max_tokens": None,
        },
        "runtime_limits": {
            "max_total_tokens": None,
            "max_context_tokens": 256000,
            "max_output_tokens": 64000,
            "max_turns": 1000,
            "timeout_seconds": 2700,
        },
        "models": [
            {
                "runtime": "responses",
                "model": "gpt-6-sol",
                "parameters": {"reasoning": {"effort": "high"}},
            }
        ],
    }
    problem = {
        "id": "problem",
        "target_digest": attempt["target_digest"],
        "formal_statement": "exact source",
        "environment_digest": config["environment_digest"],
    }
    import hashlib

    config["challenge_sha256"] = hashlib.sha256(b"exact source").hexdigest()
    service = SimpleNamespace(
        get_record=lambda kind, identifier, actor: experiment if kind == "experiment" else problem
    )
    runner.validate_attempt(
        config, attempt, service, SimpleNamespace(project_id=attempt["project_id"])
    )
    experiment["models"][0]["model"] = "gpt-6-luna"
    with pytest.raises(runner.PilotFailure, match="ATTEMPT_CONTRACT"):
        runner.validate_attempt(
            config, attempt, service, SimpleNamespace(project_id=attempt["project_id"])
        )
    experiment["models"][0]["model"] = "gpt-6-sol"
    experiment["models"].append(experiment["models"][0])
    with pytest.raises(runner.PilotFailure, match="ATTEMPT_CONTRACT"):
        runner.validate_attempt(
            config, attempt, service, SimpleNamespace(project_id=attempt["project_id"])
        )


def test_comparison_requires_explicit_decision_for_exact_target(tmp_path):
    config = manifest(tmp_path)
    with pytest.raises(runner.PilotFailure, match="CALIBRATION_GATE"):
        runner.require_comparison_decision(config)
    Path(config["calibration_decision_file"]).write_text(
        json.dumps(
            {
                "decision": "continue",
                "challenge_sha256": "e" * 64,
                "environment_digest": config["environment_digest"],
            }
        )
    )
    with pytest.raises(runner.PilotFailure, match="CALIBRATION_GATE"):
        runner.require_comparison_decision(config)
    Path(config["calibration_decision_file"]).write_text(
        json.dumps(
            {
                "decision": "continue",
                "challenge_sha256": config["challenge_sha256"],
                "environment_digest": config["environment_digest"],
            }
        )
    )
    runner.require_comparison_decision(config)


def test_preparation_plan_preserves_matched_model_and_finite_attempt(tmp_path):
    config = manifest(tmp_path)
    spec = {
        "title": "General damped oscillator envelope",
        "informal_statement": "Positive damping implies an exponential energy envelope.",
        "assumptions": ["m>0", "k>0", "gamma>0"],
        "source": "known result",
    }
    calibration = prepare.build_plan(config["attempts"][0], spec)
    comparison = prepare.build_plan(config["attempts"][3], spec)
    assert calibration.budget.max_concurrency == 1
    assert comparison.budget.max_concurrency == 2
    assert calibration.runtime_limits["timeout_seconds"] == 2700
    assert calibration.runtime_limits["max_total_tokens"] is None
    assert calibration.models[0].parameters == {"reasoning": {"effort": "high"}}
    assert len(calibration.models) == 1 and len(comparison.models) == 2
    assert calibration.sharing == "none" and comparison.sharing == "none"


def test_distinct_verifier_and_worker_images_are_pinned(tmp_path):
    config = manifest(tmp_path)
    assert config["verifier_image_digest"] != config["worker_image_digest"]
    runner.load_manifest(write_manifest(tmp_path, config))
    config["verifier_image_digest"] = "unqualified-image"
    with pytest.raises(runner.PilotFailure, match="IMAGE_FREEZE"):
        runner.load_manifest(write_manifest(tmp_path, config))


def test_sequence_blocks_undrained_and_uncertain_prior_attempt(tmp_path):
    config = manifest(tmp_path)
    selected = config["attempts"][1]
    states = {
        a["experiment_id"]: {"status": "created", "budget_reconciliation_required": False}
        for a in config["attempts"]
    }
    ledgers = {
        a["experiment_id"]: {
            "spent_cost_usd": "0",
            "reserved_cost_usd": "0",
            "active_workers": 0,
            "tokens_reserved": 0,
            "uncertain_operations": 0,
        }
        for a in config["attempts"]
    }
    pending = []

    class Service:
        def get_record(self, kind, identifier, actor):
            return states[identifier]

        def ledger(self, identifier, actor):
            return ledgers[identifier]

        def list_records(self, kind, actor, identifier):
            return pending if kind == "verification" and identifier == "experiment-0" else []

    service = Service()

    def open_attempt(attempt):
        return service, None

    with pytest.raises(runner.PilotFailure, match="PRIOR_ATTEMPT_NOT_DRAINED"):
        runner.audit_sequence(config, selected, open_attempt)
    previous = config["attempts"][0]
    states[previous["experiment_id"]]["status"] = "paused"
    Path(previous["result_file"]).parent.mkdir()
    Path(previous["result_file"]).write_text('{"status":"completed"}')
    Path(previous["private_directory"], "advance-decision.json").write_text(
        json.dumps(
            {
                "decision": "advance",
                "experiment_id": previous["experiment_id"],
            }
        )
    )
    ledgers[previous["experiment_id"]]["uncertain_operations"] = 1
    with pytest.raises(runner.PilotFailure, match="UNSETTLED_PRIOR_COST"):
        runner.audit_sequence(config, selected, open_attempt)
    ledgers[previous["experiment_id"]]["uncertain_operations"] = 0
    runner.audit_sequence(config, selected, open_attempt)
    pending.append({"status": "queued"})
    with pytest.raises(runner.PilotFailure, match="PRIOR_ATTEMPT_NOT_DRAINED"):
        runner.audit_sequence(config, selected, open_attempt)


def test_sequence_counts_actual_spend_before_new_reservation(tmp_path):
    config = manifest(tmp_path)
    selected = config["attempts"][0]

    class Service:
        def get_record(self, kind, identifier, actor):
            return {"status": "created"}

        def ledger(self, identifier, actor):
            return {
                "spent_cost_usd": "85" if identifier == "experiment-1" else "0",
                "reserved_cost_usd": "0",
                "active_workers": 0,
                "tokens_reserved": 0,
                "uncertain_operations": 0,
            }

    with pytest.raises(runner.PilotFailure, match="AGGREGATE_BUDGET"):
        runner.audit_sequence(config, selected, lambda attempt: (Service(), None))


def test_real_service_starts_before_workforce_cap_and_seeds_only_after_cap(
    lab, tmp_path, monkeypatch
):
    service, researcher, _ = lab
    experiment, problem = setup_experiment(lab)
    operator = Principal(id="operator", project_id=researcher.project_id, role="operator")
    attempt = {
        "label": "calibration",
        "phase": "calibration",
        "experiment_id": experiment["id"],
        "status_file": str(tmp_path / "status.json"),
        "result_file": str(tmp_path / "result.json"),
    }
    qualification = tmp_path / "qualification.json"
    qualification.write_text("qualified fixture")
    config = {
        "worker_image_digest": "sha256:" + "a" * 64,
        "environment_digest": problem["environment_digest"],
        "worker_qualification_file": str(qualification),
    }
    settings = SimpleNamespace(model_prices={})
    settings.model_copy = lambda **kwargs: settings
    monkeypatch.setattr(
        runner,
        "validate_attempt",
        lambda *args: {
            "experiment": experiment,
            "problem": problem,
        },
    )
    monkeypatch.setattr(runner, "configured_workspace_factory", lambda settings: object())
    monkeypatch.setattr(
        runner,
        "run_preflight",
        lambda *args, **kwargs: {
            "status": "ready_for_live_attempt",
        },
    )

    class SeedStopped(Exception):
        pass

    class Activities:
        def __init__(self, service, executor):
            self.service = service

        def apply_experiment_command(self, item):
            policies = self.service.list_records("workforce_policy", operator, experiment["id"])
            assert len(policies) == 1 and policies[0]["max_total_tasks"] == 1
            raise SeedStopped

    with pytest.raises(SeedStopped):
        asyncio.run(
            runner.run_one(
                config,
                attempt,
                service,
                operator,
                settings,
                executor_type=lambda *args, **kwargs: object(),
                activities_type=Activities,
            )
        )
    assert service.get_record("experiment", experiment["id"], operator)["status"] == "queued"
    assert service.list_records("task", operator, experiment["id"]) == []


def test_runner_reports_domain_error_code_without_sensitive_message(tmp_path, monkeypatch, capsys):
    path = write_manifest(tmp_path, manifest(tmp_path))

    def blocked(*args):
        raise HarnessError("EXPERIMENT_NOT_ACTIVE", "private service detail")

    monkeypatch.setattr(runner, "launch_one", blocked)
    assert runner.main(["launch-one", "--manifest", str(path), "--label", "run-0"]) == 1
    output = capsys.readouterr().err
    assert "EXPERIMENT_NOT_ACTIVE" in output
    assert "private service detail" not in output
