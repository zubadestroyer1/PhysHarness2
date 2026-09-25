import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from physharness.domain import Principal, digest_json
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


# Society arm plans ---------------------------------------------------------------------------

# Recorded from the pre-change RunPlan (before the optional society field existed): the
# digest of the plan as prepare_run stores it in the run_preparation artifact.
LEGACY_PLAN_DIGEST = "1d4067e906d7b5a06d8ad907c384976bef596cedd95e0e9e7eaa4b90266c4ba5"


def test_legacy_plan_prepares_exactly_as_before(lab, tmp_path):
    from physharness.run_control import RunPlan, prepare_run

    service, actor, _ = lab
    source_files(tmp_path)
    prepared = prepare_run(service, actor, RunPlan.model_validate(plan_input()), tmp_path)
    experiment = service.get_record("experiment", prepared["experiment_id"], actor)
    assert "society" not in experiment
    content = service.artifact_content(prepared["preparation_artifact_id"], actor)
    assert digest_json(json.loads(content)["plan"]) == LEGACY_PLAN_DIGEST


SOCIETY = {
    "claim_ttl_seconds": 900,
    "lab_size_max": 6,
    "referee_quorum": 1,
    "literature": {"mode": "open"},
}


def society_plan(**update):
    return {
        **plan_input(),
        "models": [
            {"runtime": "responses", "model": "family-a-test-model"},
            {"runtime": "responses", "model": "family-b-test-model"},
        ],
        "sharing": "ideas",
        "society": SOCIETY,
        **update,
    }


def test_society_plan_prepares_a_society_experiment(lab, tmp_path):
    from physharness.domain import SocietyPolicy
    from physharness.run_control import RunPlan, prepare_run

    service, actor, _ = lab
    source_files(tmp_path)
    prepared = prepare_run(service, actor, RunPlan.model_validate(society_plan()), tmp_path)
    experiment = service.get_record("experiment", prepared["experiment_id"], actor)
    assert experiment["society"] == SocietyPolicy(**SOCIETY).model_dump(mode="json")
    assert experiment["sharing"] == "ideas" and len(experiment["models"]) == 2
    content = json.loads(service.artifact_content(prepared["preparation_artifact_id"], actor))
    assert content["plan"]["society"] == experiment["society"]
    assert prepared["model_calls"] == 0 and experiment["status"] == "created"


@pytest.mark.parametrize(
    ("update", "fragment"),
    [
        ({"sharing": "verified"}, "requires ideas sharing"),
        ({"society": {**SOCIETY, "literature": {"mode": "benchmark"}}}, "masked_reference"),
        ({"society": {**SOCIETY, "unknown": True}}, "society.unknown"),
    ],
)
def test_society_plan_is_checked_before_any_record(lab, update, fragment):
    from physharness.run_control import RunPlan

    service, actor, _ = lab
    with pytest.raises(ValidationError, match=fragment):
        RunPlan.model_validate(society_plan(**update))
    assert service.list_records("campaign", actor) == []


def test_run_plan_rejects_unfilled_user_decisions():
    from physharness.run_control import RunPlan

    data = plan_input()
    data["target"]["title"] = "USER DECISION REQUIRED: choose the target"
    with pytest.raises(ValidationError, match="USER DECISION REQUIRED"):
        RunPlan.model_validate(data)


EXAMPLE = Path(__file__).resolve().parents[1] / "work/society-s1/run-plan.example.json"
PLACEHOLDER = "USER DECISION REQUIRED"


def fill(value, choices, path=""):
    """Replace every placeholder with the test value chosen for its JSON path."""
    if isinstance(value, dict):
        return {key: fill(item, choices, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, list):
        return [fill(item, choices, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, str) and PLACEHOLDER in value:
        return choices.pop(path)
    return value


def placeholders(value, path=""):
    if isinstance(value, dict):
        return [p for key, item in value.items() for p in placeholders(item, f"{path}.{key}")]
    if isinstance(value, list):
        return [p for i, item in enumerate(value) for p in placeholders(item, f"{path}[{i}]")]
    return [path] if isinstance(value, str) and PLACEHOLDER in value else []


EXAMPLE_CHOICES = {
    ".target.title": "Test target",
    ".target.program": "classical",
    ".target.informal_statement": "A statement chosen for the test.",
    ".target.formal_source_file": "Challenge.lean",
    ".target.environment_file": "environment.json",
    ".target.target_theorem": "target",
    # Eight seeded roots, four per model family.
    **{f".models[{i}].model": f"family-{'ab'[i // 4]}-test-model" for i in range(8)},
    ".budget.max_cost_usd": "480",
    ".budget.max_runtime_seconds": 14400,
    ".budget.max_tokens": 40000000,
    ".society.literature.blocked_sources[0]": "arXiv:2101.00001",
    ".society.literature.masked_reference_artifact_id": "masked-reference-test-id",
}


def test_society_example_plan_validates_once_user_decisions_are_filled(lab, tmp_path):
    from physharness.run_control import RunPlan, prepare_run

    example = json.loads(EXAMPLE.read_text())
    assert sorted(placeholders(example)) == sorted(EXAMPLE_CHOICES)
    # As shipped, the skeleton cannot be prepared.
    with pytest.raises(ValidationError):
        RunPlan.model_validate(example)
    plan = RunPlan.model_validate(fill(example, dict(EXAMPLE_CHOICES)))
    assert plan.society is not None and plan.sharing == "ideas"
    assert plan.society.literature.mode == "benchmark"
    assert [model.model for model in plan.models] == ["family-a-test-model"] * 4 + [
        "family-b-test-model"
    ] * 4
    assert plan.budget.max_concurrency == 12
    service, actor, _ = lab
    source_files(tmp_path)
    prepared = prepare_run(service, actor, plan.model_copy(update={"project_id": "lab"}), tmp_path)
    experiment = service.get_record("experiment", prepared["experiment_id"], actor)
    assert experiment["society"]["literature"]["mode"] == "benchmark"


@pytest.mark.parametrize("kind", [None, "note", "masked_reference"])
def test_preflight_requires_the_benchmark_masked_reference(lab, tmp_path, kind):
    """Without its reference the broker fails closed, so literature would silently be off."""
    from physharness.domain import ArtifactCreate
    from physharness.run_control import RunPlan, prepare_run, run_preflight

    service, actor, _ = lab
    source_files(tmp_path)
    reference = "missing-reference"
    if kind is not None:
        reference = service.create_artifact(
            ArtifactCreate(kind=kind, content="Masked reference text."), actor, "reference"
        )["id"]
    literature = {"mode": "benchmark", "masked_reference_artifact_id": reference}
    plan = society_plan(society={**SOCIETY, "literature": literature})
    prepared = prepare_run(service, actor, RunPlan.model_validate(plan), tmp_path)
    operator = Principal(id="controller", project_id="lab", role="operator")
    report = run_preflight(service, operator, prepared["experiment_id"], prices={}, environment={})
    codes = {blocker["code"] for blocker in report["blockers"]}
    assert ("MASKED_REFERENCE_REQUIRED" in codes) is (kind != "masked_reference")
    assert report["model_calls"] == 0
