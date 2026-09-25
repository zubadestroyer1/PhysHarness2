"""Dry-run contracts for the harder private pilot; no model or Docker calls."""

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from test_execution_responses import message
from test_research_loop_integration import campaign, mock_executor, response

from physharness.domain import Principal
from physharness.storage import RecordRow

SCRIPTS = Path(__file__).resolve().parents[1] / "work/hardening-final-2026-09-24"
sys.path.insert(0, str(SCRIPTS))


def _module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = _module("pilot_prepare")
runner = _module("pilot_runner")
launch = _module("pilot_launch")


def _attempt(tmp_path, *, phase="calibration", ceiling="14", index=1):
    private = tmp_path / "attempts" / f"attempt-{index}"
    return {
        "label": f"attempt-{index}",
        "phase": phase,
        "sharing": "none" if phase == "calibration" else "ideas",
        "ceiling_usd": ceiling,
        "experiment_id": f"experiment-{index}",
        "project_id": f"attempt-{index}",
        "target_digest": f"{index:064x}",
        "private_directory": str(private),
        "database_url": f"sqlite:///{private / 'harness.db'}",
        "artifact_root": str(private / "artifacts"),
        "status_file": str(private / "status.json"),
        "result_file": str(private / "result.json"),
    }


def _manifest(tmp_path, *, phase="calibration", ceiling="14"):
    attempt = _attempt(tmp_path, phase=phase, ceiling=ceiling)
    return {
        "version": 2,
        "pilot": "hardening-final-2026-09-24",
        "phase": phase,
        "prior_spent_usd": "43.762893",
        "aggregate_ceiling_usd": "100",
        "new_reservation_ceiling_usd": "52",
        "challenge_sha256": "a" * 64,
        "challenge_file": str(tmp_path / "Challenge.lean"),
        "environment_digest": "b" * 64,
        "worker_image_digest": "sha256:" + "c" * 64,
        "verifier_image_digest": "sha256:" + "d" * 64,
        "docker_host": "unix:///tmp/dedicated-pilot.sock",
        "tmp_directory": str(tmp_path / "tmp"),
        "registry": str(tmp_path / f"registry-{phase}.json"),
        "model_prices_file": str(tmp_path / "prices.json"),
        "worker_qualification_file": str(tmp_path / "qualification.json"),
        "source_qualification_file": str(tmp_path / "source-qualification.json"),
        "source_scope_sha256": "e" * 64,
        "deployment_decision_file": str(tmp_path / f"deployment-decision-{phase}.json"),
        "global_lock_file": str(tmp_path / "launcher.lock"),
        "attempts": [attempt],
        "retired_attempts": [],
    }


def test_plan_has_two_root_models_but_four_cooperative_slots(tmp_path):
    spec = {
        "title": "Hard target",
        "informal_statement": "A finite nonlinear network has a conditional energy estimate.",
        "target_theorem": "physics_target",
        "provenance": (
            "Assistant-authored private known-type development target; not expert reviewed."
        ),
    }
    calibration = prepare.build_plan(_attempt(tmp_path), spec)
    cooperative = prepare.build_plan(
        _attempt(tmp_path, phase="cooperative", ceiling="38", index=2), spec
    )
    assert len(calibration.models) == 1
    assert calibration.target.source == spec["provenance"]
    assert len(cooperative.models) == 2
    assert calibration.budget.max_concurrency == 1
    assert cooperative.budget.max_concurrency == 4
    assert calibration.sharing == "none" and cooperative.sharing == "ideas"
    for plan in (calibration, cooperative):
        assert plan.budget.max_runtime_seconds == 7200
        assert plan.budget.max_tokens is None
        assert plan.runtime_limits["timeout_seconds"] == 7200
        assert plan.runtime_limits["max_context_tokens"] == 256000
        assert plan.runtime_limits["max_output_tokens"] == 64000
        assert plan.runtime_limits["max_total_tokens"] is None
        assert plan.runtime_limits["max_turns"] == 1000


def test_manifest_rejects_extra_budget_and_nonisolated_prior(tmp_path):
    config = _manifest(tmp_path)
    path = tmp_path / "manifest-calibration.json"
    path.write_text(json.dumps(config))
    assert runner.load_manifest(path)["phase"] == "calibration"
    config["attempts"][0]["ceiling_usd"] = "14.000001"
    path.write_text(json.dumps(config))
    with pytest.raises(runner.PilotFailure, match="BUDGET_SCHEDULE"):
        runner.load_manifest(path)
    config = _manifest(tmp_path, phase="cooperative", ceiling="38")
    config["attempts"].insert(0, _attempt(tmp_path, index=2))
    config["attempts"][1]["artifact_root"] = config["attempts"][0]["artifact_root"]
    path = tmp_path / "manifest-cooperative.json"
    path.write_text(json.dumps(config))
    with pytest.raises(runner.PilotFailure, match="RUN_ISOLATION"):
        runner.load_manifest(path)


def test_manifest_rejects_attempt_root_outside_its_phase_state(tmp_path):
    config = _manifest(tmp_path)
    external = tmp_path.parent / "external-attempt"
    attempt = config["attempts"][0]
    attempt.update(
        private_directory=str(external),
        database_url=f"sqlite:///{external / 'harness.db'}",
        artifact_root=str(external / "artifacts"),
        status_file=str(external / "status.json"),
        result_file=str(external / "result.json"),
    )
    path = tmp_path / "manifest-calibration.json"
    path.write_text(json.dumps(config))
    with pytest.raises(runner.PilotFailure, match="RUN_ISOLATION"):
        runner.load_manifest(path)


def test_remaining_ceiling_uses_exact_settled_prior_spend():
    assert prepare.remaining_ceiling([Decimal("7.196461")]) == Decimal("44.803539")
    assert prepare.remaining_ceiling([Decimal("7.196461"), Decimal("1.00")]) == Decimal("43.803539")
    with pytest.raises(ValueError, match="budget"):
        prepare.remaining_ceiling([Decimal("52")])


def test_root_seed_contract_uses_opt_in_profiles_without_solution_scaffold():
    calibration = runner.root_seed_request("calibration")
    cooperative = runner.root_seed_request("cooperative")
    assert len(calibration.roots) == 1
    assert len(cooperative.roots) == 2
    assert all(root.public_summary for root in cooperative.roots)
    assert all("proof" not in root.objective.lower() for root in cooperative.roots)
    assert all(root.model_index is None for root in cooperative.roots)


def test_validate_attempt_rejects_old_timeout_and_two_slot_cooperative(tmp_path):
    config = _manifest(tmp_path, phase="cooperative", ceiling="38")
    attempt = config["attempts"][0]
    source = "exact target"
    import hashlib

    config["challenge_sha256"] = hashlib.sha256(source.encode()).hexdigest()
    experiment = {
        "id": attempt["experiment_id"],
        "project_id": attempt["project_id"],
        "problem_id": "problem",
        "status": "created",
        "target_digest": attempt["target_digest"],
        "execution_profile": "formal-research",
        "context_profile": "research",
        "policy": "independent",
        "sharing": "ideas",
        "budget": {
            "max_cost_usd": "38",
            "max_concurrency": 4,
            "max_runtime_seconds": 7200,
            "max_tokens": None,
        },
        "runtime_limits": {
            "max_total_tokens": None,
            "max_context_tokens": 256000,
            "max_output_tokens": 64000,
            "max_turns": 1000,
            "timeout_seconds": 7200,
        },
        "models": [
            {
                "runtime": "responses",
                "model": "gpt-6-sol",
                "parameters": {"reasoning": {"effort": "high"}},
            }
        ]
        * 2,
    }
    problem = {
        "id": "problem",
        "target_digest": attempt["target_digest"],
        "formal_statement": source,
        "environment_digest": config["environment_digest"],
    }

    class Service:
        def get_record(self, kind, identifier, actor):
            return experiment if kind == "experiment" else problem

    actor = Principal(id="operator", project_id=attempt["project_id"], role="operator")
    runner.validate_attempt(config, attempt, Service(), actor)
    experiment["budget"]["max_concurrency"] = 2
    with pytest.raises(runner.PilotFailure, match="ATTEMPT_CONTRACT"):
        runner.validate_attempt(config, attempt, Service(), actor)
    experiment["budget"]["max_concurrency"] = 4
    experiment["runtime_limits"]["timeout_seconds"] = 2700
    with pytest.raises(runner.PilotFailure, match="ATTEMPT_CONTRACT"):
        runner.validate_attempt(config, attempt, Service(), actor)


def test_phase_freezes_are_distinct_and_drift_blocks_launch(tmp_path):
    calibration = tmp_path / "manifest-calibration.json"
    cooperative = tmp_path / "manifest-cooperative.json"
    assert launch.freeze_path(calibration) != launch.freeze_path(cooperative)
    baseline = {"protocol": "hardening-source-freeze-v1", "files": {"a": "hash-a"}}
    with pytest.raises(launch.FreezeError, match="drift"):
        launch.check_from_collection(
            baseline, {"protocol": baseline["protocol"], "files": {"a": "hash-b"}}
        )


def test_cooperative_freeze_rejects_shared_source_changed_since_calibration():
    earlier = {"files": {"src/physharness/a.py": "old", "prior-bundle": "x"}}
    current = {"files": {"src/physharness/a.py": "new", "new-bundle": "y"}}
    with pytest.raises(launch.FreezeError, match="cross-phase"):
        launch.check_phase_continuity(earlier, current)
    current["files"]["src/physharness/a.py"] = "old"
    launch.check_phase_continuity(earlier, current)
    current["files"]["src/physharness/new.py"] = "new"
    with pytest.raises(launch.FreezeError, match="cross-phase"):
        launch.check_phase_continuity(earlier, current)


def test_direct_runner_launch_requires_source_freeze(tmp_path):
    manifest_path = tmp_path / "manifest-calibration.json"
    manifest_path.write_text(json.dumps(_manifest(tmp_path)))
    with pytest.raises(runner.PilotFailure, match="SOURCE_FREEZE"):
        runner.require_source_freeze(manifest_path)


@pytest.mark.asyncio
async def test_prior_drain_validates_even_single_unhanded_native_checkpoint(lab, tmp_path):
    service, actor, _ = lab
    experiment, _, task = campaign(lab, concurrency=1)

    async def handler(request):
        return httpx.Response(200, json=response([message("Unresolved result")]))

    executor, client = mock_executor(service, handler)
    try:
        result = await runner.ResearchTeamRunner(service, executor=executor).run(
            runner.TeamRunManifest(
                experiment_id=experiment["id"],
                project_id=actor.project_id,
                mode="replay",
                task_ids=[task["id"]],
                max_concurrency=1,
                max_tasks=1,
                timeout_seconds=10,
            )
        )
    finally:
        await client.close()
    assert result["status"] == "completed"
    current = service.get_record("experiment", experiment["id"], actor)
    service.transition_experiment(experiment["id"], "pause", current["revision"], actor, "pause")
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(result))
    attempt = {"experiment_id": experiment["id"], "result_file": str(result_path)}
    assert runner._drained_attempt(attempt, service, actor, require_export=False) >= Decimal(0)
    session = service.list_records("session", actor, experiment["id"])[0]
    with service.db.transaction() as transaction:
        artifact = transaction.get(RecordRow, session["checkpoint_artifact_id"])
        service._replace(transaction, artifact, {"sha256": "0" * 64})
    with pytest.raises(runner.PilotFailure, match="PRIOR_ATTEMPT_NOT_DRAINED"):
        runner._drained_attempt(attempt, service, actor, require_export=False)
