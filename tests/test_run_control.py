import hashlib
import json

import pytest
from pydantic import ValidationError

from physharness.domain import Principal
from physharness.errors import HarnessError


def plan_input():
    return {
        "version": 1,
        "run_id": "morning-run",
        "project_id": "lab",
        "campaign": {
            "title": "Review queue",
            "objective": "Known results",
            "programs": ["quantum"],
        },
        "target": {
            "title": "Involution",
            "program": "quantum",
            "informal_statement": "Review me",
            "formal_source_file": "Challenge.lean",
            "environment_file": "environment.json",
            "assumptions": ["Finite dimensional"],
            "target_theorem": "target",
        },
        "models": [{"runtime": "responses", "model": "explicit-test-model"}],
        "budget": {
            "max_cost_usd": "1",
            "max_concurrency": 2,
            "max_runtime_seconds": 60,
            "max_tokens": 1000,
        },
    }


def source_files(tmp_path):
    (tmp_path / "Challenge.lean").write_text("theorem target : True := by trivial\n")
    (tmp_path / "environment.json").write_text(
        json.dumps(
            {
                "image": "sha256:" + "a" * 64,
                "checker_versions": {"lean": "test-only"},
                "binaries": {},
                "files": {},
            }
        )
    )


def test_prepare_is_idempotent_and_cannot_create_review_or_start_work(lab, tmp_path):
    from physharness.run_control import RunPlan, prepare_run

    service, actor, _ = lab
    source_files(tmp_path)
    plan = RunPlan.model_validate(plan_input())
    first = prepare_run(service, actor, plan, tmp_path)
    assert prepare_run(service, actor, plan, tmp_path) == first
    problem = service.get_record("problem", first["problem_id"], actor)
    assert problem["semantic_review"] == "pending"
    assert service.get_record("experiment", first["experiment_id"], actor)["status"] == "created"
    assert service.list_records("task", actor) == []
    assert service.list_records("review", actor) == []


def test_changed_source_cannot_reuse_run_identity(lab, tmp_path):
    from physharness.run_control import RunPlan, prepare_run

    service, actor, _ = lab
    source_files(tmp_path)
    plan = RunPlan.model_validate(plan_input())
    prepare_run(service, actor, plan, tmp_path)
    (tmp_path / "Challenge.lean").write_text("theorem target : False := by sorry\n")
    with pytest.raises(HarnessError) as error:
        prepare_run(service, actor, plan, tmp_path)
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    assert len(service.list_records("problem", actor)) == 1


@pytest.mark.parametrize("source", ["../secret", "/etc/passwd", "link.lean"])
def test_plan_rejects_source_escape_before_creating_records(lab, tmp_path, source):
    from physharness.run_control import RunPlan, prepare_run

    service, actor, _ = lab
    source_files(tmp_path)
    (tmp_path / "link.lean").symlink_to(tmp_path / "Challenge.lean")
    data = plan_input()
    data["target"]["formal_source_file"] = source
    with pytest.raises((HarnessError, ValidationError)):
        prepare_run(service, actor, RunPlan.model_validate(data), tmp_path)
    assert service.list_records("campaign", actor) == []


def test_run_plan_forbids_credentials_review_flags_and_unknown_execution_mode():
    from physharness.run_control import RunPlan

    for field, value in [("api_key", "secret"), ("approved", True), ("execution", "magic")]:
        with pytest.raises(ValidationError):
            RunPlan.model_validate({**plan_input(), field: value})


def test_preflight_reports_all_missing_inputs_without_allocating(lab, tmp_path):
    from physharness.run_control import RunPlan, prepare_run, run_preflight

    service, actor, _ = lab
    source_files(tmp_path)
    prepared = prepare_run(service, actor, RunPlan.model_validate(plan_input()), tmp_path)
    operator = Principal(id="controller", project_id="lab", role="operator")
    report = run_preflight(service, operator, prepared["experiment_id"], prices={}, environment={})
    assert report["status"] == "blocked"
    assert {x["code"] for x in report["blockers"]} >= {
        "TARGET_REVIEW_REQUIRED",
        "MODEL_CREDENTIAL_REQUIRED",
        "MODEL_PRICE_REQUIRED",
        "VERIFIER_REQUIRED",
    }
    assert report["model_calls"] == 0
    assert service.list_records("task", operator) == []


def test_preflight_cannot_be_run_as_an_agent(lab):
    from physharness.run_control import run_preflight

    service, _, _ = lab
    worker = Principal(id="worker", project_id="lab", role="agent", experiment_id="some-run")
    with pytest.raises(HarnessError) as error:
        run_preflight(service, worker, "some-run", prices={}, environment={})
    assert error.value.code == "FORBIDDEN"


def test_empty_source_is_rejected_before_any_record_is_created(lab, tmp_path):
    from physharness.run_control import RunPlan, prepare_run

    service, actor, _ = lab
    source_files(tmp_path)
    (tmp_path / "Challenge.lean").write_text("")
    with pytest.raises(HarnessError) as error:
        prepare_run(service, actor, RunPlan.model_validate(plan_input()), tmp_path)
    assert error.value.code == "RUN_INPUT_INVALID"
    assert service.list_records("campaign", actor) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("runtime_limits", {"max_turns": 0}),
        ("runtime_limits", {"api_key": "credential-never-recorded"}),
        ("models", [{"runtime": "responses", "model": " spaced "}]),
        (
            "models",
            [{"runtime": "responses", "model": "test", "parameters": {"api_key": "secret"}}],
        ),
        (
            "models",
            [
                {
                    "runtime": "responses",
                    "model": "test",
                    "parameters": {"reasoning": {"api_key": "secret"}},
                }
            ],
        ),
    ],
)
def test_invalid_runtime_configuration_never_becomes_a_run_plan(field, value):
    from physharness.run_control import RunPlan

    with pytest.raises(ValidationError):
        RunPlan.model_validate({**plan_input(), field: value})


def test_configured_preflight_forwards_nondefault_reviewed_theorem(lab, tmp_path):
    from physharness.run_control import RunPlan, prepare_run, run_preflight
    from physharness.verification.boundary import outcome

    service, actor, reviewer = lab
    source_files(tmp_path)
    source = "theorem distinct_selector : True := by trivial\n"
    (tmp_path / "Challenge.lean").write_text(source)
    data = plan_input()
    data["target"]["target_theorem"] = "distinct_selector"
    prepared = prepare_run(service, actor, RunPlan.model_validate(data), tmp_path)
    service.review_problem(
        prepared["problem_id"], "approved", "Synthetic fixture review", reviewer, "review"
    )
    calls = []

    class ControlledPreflight:
        def preflight(self, request):
            calls.append(request)
            return outcome(
                request, "blocked", "configured_unprobed", "Synthetic preflight", "No kernel run"
            )

    service.verifier = ControlledPreflight()
    operator = Principal(id="controller", project_id="lab", role="operator")
    report = run_preflight(service, operator, prepared["experiment_id"], prices={}, environment={})
    assert len(calls) == 1
    assert calls[0].target_theorem == "distinct_selector"
    assert calls[0].semantic_reviewed is True
    assert calls[0].challenge_sha256 == hashlib.sha256(source.encode()).hexdigest()
    assert report["model_calls"] == 0
    assert service.list_records("task", operator) == []
