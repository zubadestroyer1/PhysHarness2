"""Operator workflow tests use private temporary state and never call a model."""

import json
from types import SimpleNamespace

import pytest
from test_run_control import plan_input, source_files
from typer.testing import CliRunner

from physharness import cli, run_control
from physharness.domain import Principal
from physharness.errors import HarnessError


@pytest.fixture
def prepared(lab, tmp_path, monkeypatch):
    service, researcher, reviewer = lab
    source_files(tmp_path)
    data = plan_input()
    data["models"] *= 2
    plan = run_control.RunPlan.model_validate(data)
    result = run_control.prepare_run(service, researcher, plan, tmp_path)
    service.review_problem(result["problem_id"], "approved", "Synthetic CLI fixture", reviewer, "r")
    operator = Principal(id="controller", project_id="lab", role="operator")
    settings = SimpleNamespace(
        model_prices={
            "explicit-test-model": {
                "input_usd_per_million": "1",
                "output_usd_per_million": "1",
            }
        },
        worker_workspace=None,
    )
    monkeypatch.setattr(cli, "local_authority", lambda *roles: (settings, service, operator))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return service, operator, result


def test_blocked_preflight_exits_nonzero_without_queuing(prepared):
    service, actor, ids = prepared
    result = CliRunner().invoke(cli.app, ["run-team", ids["experiment_id"]])
    assert result.exit_code == 1, result.output
    assert "MODEL_CREDENTIAL_REQUIRED" in result.output
    assert service.get_record("experiment", ids["experiment_id"], actor)["status"] == "created"
    assert service.list_records("task", actor) == []


def test_run_team_preflights_requested_concurrency_before_queuing(prepared, monkeypatch):
    service, actor, ids = prepared
    seen = []

    def preflight(*args, **kwargs):
        seen.append(kwargs["requested_concurrency"])
        return {"status": "blocked", "blockers": [{"code": "WORKSPACE_CAPACITY"}]}

    monkeypatch.setattr(run_control, "run_preflight", preflight)
    result = CliRunner().invoke(cli.app, ["run-team", ids["experiment_id"], "--concurrency", "2"])
    assert result.exit_code == 1, result.output
    assert seen == [2]
    assert "WORKSPACE_CAPACITY" in result.output
    assert service.list_records("task", actor) == []


def test_check_run_previews_requested_concurrency_without_queuing(prepared, monkeypatch):
    service, actor, ids = prepared
    seen = []

    def preflight(*args, **kwargs):
        seen.append(kwargs["requested_concurrency"])
        return {"status": "blocked", "blockers": [{"code": "WORKSPACE_CAPACITY"}]}

    monkeypatch.setattr(run_control, "run_preflight", preflight)
    result = CliRunner().invoke(cli.app, ["check-run", ids["experiment_id"], "--concurrency", "2"])
    assert result.exit_code == 1, result.output
    assert seen == [2]
    assert "WORKSPACE_CAPACITY" in result.output
    assert service.list_records("task", actor) == []


def test_task_bound_is_checked_before_transition_and_seeding(prepared, monkeypatch):
    service, actor, ids = prepared
    # Isolate dispatch ordering; this fixture is not a qualified verifier.
    monkeypatch.setattr(
        run_control, "run_preflight", lambda *a, **k: {"status": "ready_for_live_attempt"}
    )
    result = CliRunner().invoke(cli.app, ["run-team", ids["experiment_id"], "--max-tasks", "1"])
    assert result.exit_code == 1, result.output
    assert "TEAM_LIMIT" in result.output
    assert service.get_record("experiment", ids["experiment_id"], actor)["status"] == "created"
    assert service.list_records("task", actor) == []


def test_review_requires_digest_of_inspected_target(prepared, tmp_path, monkeypatch):
    service, _, ids = prepared
    reviewer = Principal(id="reviewer", project_id="lab", role="reviewer")
    monkeypatch.setattr(cli, "local_authority", lambda *roles: (None, service, reviewer))
    (tmp_path / "rationale.txt").write_text("Inspected the exact target")
    result = CliRunner().invoke(
        cli.app,
        [
            "review-target",
            ids["problem_id"],
            "--target-digest",
            "0" * 64,
            "--rationale-file",
            str(tmp_path / "rationale.txt"),
            "--idempotency-key",
            "review-two",
        ],
    )
    assert result.exit_code == 1, result.output
    assert "REVIEW_TARGET_MISMATCH" in result.output
    assert len(service.list_records("review", reviewer)) == 1


def test_plan_validation_does_not_print_secret_input(lab, tmp_path, monkeypatch):
    service, actor, _ = lab
    monkeypatch.setattr(cli, "local_authority", lambda *roles: (None, service, actor))
    data = {**plan_input(), "api_key": "must-never-appear-in-output"}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(data))
    result = CliRunner().invoke(cli.app, ["prepare-run", str(path)])
    assert result.exit_code == 1, result.output
    assert "RUN_PLAN_INVALID" in result.output
    assert "must-never-appear" not in result.output
    assert service.list_records("campaign", actor) == []


def test_local_authority_cannot_invent_an_operator(monkeypatch):
    monkeypatch.setenv("PHYSHARNESS_TOKEN", "issued-researcher-token")
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: SimpleNamespace(
            auth_tokens={
                "issued-researcher-token": Principal(
                    id="researcher", project_id="lab", role="researcher"
                ),
            }
        ),
    )
    with pytest.raises(HarnessError) as error:
        cli.local_authority("operator")
    assert error.value.code == "FORBIDDEN"


def test_cli_seeds_real_ids_and_passes_limits_to_finite_supervisor(prepared, monkeypatch):
    from physharness.orchestration import research_worker

    service, actor, ids = prepared
    monkeypatch.setattr(
        run_control, "run_preflight", lambda *a, **k: {"status": "ready_for_live_attempt"}
    )
    seen = []

    async def inspect_manifest(self, manifest):
        seen.append(manifest)
        tasks = [service.get_record("task", task_id, actor) for task_id in manifest.task_ids]
        assert len(tasks) == 2
        assert all(task["experiment_id"] == ids["experiment_id"] for task in tasks)
        return {"status": "completed", "evidence_level": "cli_dispatch_fixture"}

    monkeypatch.setattr(research_worker.ResearchTeamRunner, "run", inspect_manifest)
    result = CliRunner().invoke(
        cli.app, ["run-team", ids["experiment_id"], "--concurrency", "2", "--max-tasks", "3"]
    )
    assert result.exit_code == 0, result.output
    assert len(seen) == 1
    assert seen[0].max_concurrency == 2 and seen[0].max_tasks == 3
    assert "cli_dispatch_fixture" in result.output
