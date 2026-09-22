"""Structural parameter validation using the installed Responses SDK contract; no API calls."""

import math

import pytest
from test_core import setup_experiment

from physharness.domain import BranchCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import ExecutionError, ModelConfig, ResponsesRuntime, RuntimeLimits
from physharness.orchestration.research_worker import ResearchTaskExecutor
from physharness.storage import LeaseRow, ReservationRow

INVALID = [
    {"temperature": "hot"},
    {"temperature": True},
    {"temperature": -0.1},
    {"temperature": 2.1},
    {"temperature": math.nan},
    {"top_p": math.inf},
    {"top_p": 1.1},
    {"instructions": []},
    {"reasoning": "high"},
    {"reasoning": {"effort": "ultra"}},
    {"reasoning": {"context": "anywhere"}},
    {"reasoning": {"summary": "always"}},
    {"reasoning": {"mode": 3}},
    {"reasoning": {"provider_request_override": "secret-value"}},
    {"text": {"verbosity": "loud"}},
    {"text": {"format": "json"}},
    {"text": {"format": {"type": "json_schema", "name": "schema", "schema": []}}},
    {"text": {"format": {"type": "json_schema", "name": "schema", "schema": {}, "strict": "yes"}}},
    {"text": {"format": {"type": "text", "extra": "secret-value"}}},
    {"service_tier": "cheap"},
    {"secret-key": "secret-value"},
]


@pytest.mark.parametrize("parameters", INVALID)
async def test_invalid_responses_parameters_fail_before_any_checkpoint(parameters):
    class UntouchedStore:
        def __init__(self):
            self.saves = 0

        async def save(self, checkpoint):
            self.saves += 1

    store = UntouchedStore()
    runtime = ResponsesRuntime(store=store)
    with pytest.raises(ExecutionError) as error:
        await runtime.start(
            "x", ModelConfig(model="exact-model", parameters=parameters), RuntimeLimits()
        )
    assert error.value.code == "INVALID_CONFIG"
    assert store.saves == 0
    assert "secret-value" not in str(error.value)
    assert "secret-key" not in str(error.value)


async def test_worker_parameter_validation_precedes_slot_lease_and_runtime(lab):
    from sqlalchemy import select

    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="B", objective="Research"), actor, "branch"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task"
    )
    operator = Principal(id="fixture-controller", project_id=actor.project_id, role="operator")

    def corrupt_config(session, operation):
        row = service._get(session, "branch", branch["id"], operator)
        return service._replace(
            session,
            row,
            {
                "model_configuration": {
                    "runtime": "responses",
                    "model": "explicit-test-model",
                    "parameters": {"reasoning": []},
                }
            },
        )

    service._execute(operator, "bad-configuration", "fixture", {}, corrupt_config)

    def never_construct(**kwargs):
        raise AssertionError("No runtime may be constructed for invalid parameters")

    executor = ResearchTaskExecutor(
        service,
        prices={
            "explicit-test-model": {"input_usd_per_million": "1", "output_usd_per_million": "1"}
        },
        runtime_factory=never_construct,
    )
    with pytest.raises((ExecutionError, HarnessError)) as error:
        await executor.execute(task["id"], actor.project_id)
    assert error.value.code == "INVALID_CONFIG"
    assert service.get_record("task", task["id"], actor)["status"] == "queued"
    with service.db.sessions() as session:
        assert session.get(LeaseRow, task["id"]) is None
        assert list(session.scalars(select(ReservationRow))) == []
    assert service.list_records("session", actor) == []


def test_valid_parameters_preserve_schema_json_and_explicit_optional_values():
    from physharness.execution.parameters import validate_responses_parameters

    schema = {
        "$defs": {"choice": {"enum": [None, True, 2, 2.5, {"nested": ["x"]}]}},
        "type": "object",
        "properties": {"answer": {"$ref": "#/$defs/choice"}},
        "additionalProperties": False,
        "x-provider-schema-extension": {"allowed": True},
    }
    parameters = {
        "instructions": "Preserve exact assumptions",
        "temperature": 2,
        "top_p": 0,
        "reasoning": {
            "context": "all_turns",
            "effort": "max",
            "summary": None,
            "generate_summary": "auto",
            "mode": "future-provider-mode",
        },
        "text": {
            "verbosity": "high",
            "format": {
                "type": "json_schema",
                "name": "Answer_1",
                "schema": schema,
                "description": "A response",
                "strict": True,
            },
        },
        "service_tier": "fast",
    }
    checked = validate_responses_parameters(parameters)
    assert checked == parameters
    checked["text"]["format"]["schema"]["properties"]["answer"]["$ref"] = "changed"
    assert (
        parameters["text"]["format"]["schema"]["properties"]["answer"]["$ref"] == "#/$defs/choice"
    )
    assert validate_responses_parameters({}) == {}
    assert validate_responses_parameters(
        {
            "instructions": None,
            "reasoning": None,
            "temperature": None,
            "top_p": None,
            "service_tier": None,
        }
    ) == {
        "instructions": None,
        "reasoning": None,
        "temperature": None,
        "top_p": None,
        "service_tier": None,
    }
    assert validate_responses_parameters({"reasoning": {}}) == {"reasoning": {}}


@pytest.mark.parametrize(
    "parameters",
    [
        {"reasoning": {"mode": "  "}},
        {"text": None},
        {"text": {"format": {"type": "json_schema", "name": "invalid name", "schema": {}}}},
        {"text": {"format": {"type": "json_schema", "name": "s", "schema": {"enum": [math.inf]}}}},
    ],
)
def test_shared_validator_rejects_malformed_nested_json_without_echo(parameters):
    from physharness.execution.parameters import validate_responses_parameters

    with pytest.raises(ExecutionError) as error:
        validate_responses_parameters(parameters)
    assert error.value.code == "INVALID_CONFIG"
    assert error.value.__suppress_context__ is True


async def test_malformed_legacy_checkpoint_cannot_bypass_parameter_validation(tmp_path):
    from physharness.execution import RuntimeCheckpoint, RuntimeSession, SQLiteRuntimeStore

    store = SQLiteRuntimeStore(tmp_path / "sessions.db")
    session = RuntimeSession(
        runtime="openai_responses",
        status="completed",
        model=ModelConfig(model="exact-model", parameters={"temperature": "hot"}),
        limits=RuntimeLimits(),
    )
    checkpoint = RuntimeCheckpoint.build(
        session, {"input": [], "responses": [], "pending_operation": None}
    )
    await store.save(checkpoint)
    runtime = ResponsesRuntime(store=store)
    with pytest.raises(ExecutionError) as error:
        await runtime.continue_session(session.id, "continue")
    assert error.value.code == "INVALID_CONFIG"
    assert (await store.load(session.id)).state_digest == checkpoint.state_digest


def test_team_run_limits_validate_before_task_allocation():
    from pydantic import ValidationError

    from physharness.orchestration import research_worker

    limits = research_worker.TeamRunLimits(max_concurrency=2, max_tasks=3, timeout_seconds=20)
    assert limits.model_dump() == {"max_concurrency": 2, "max_tasks": 3, "timeout_seconds": 20}
    for invalid in [
        {"timeout_seconds": math.nan},
        {"timeout_seconds": math.inf},
        {"max_tasks": 0},
        {"max_concurrency": 0},
        {"unknown": True},
    ]:
        with pytest.raises(ValidationError):
            research_worker.TeamRunLimits(**invalid)


@pytest.mark.parametrize(
    "model_name, limits",
    [("  explicit-test-model  ", {}), ("explicit-test-model", {"max_turns": 0})],
)
async def test_http_created_invalid_model_or_limits_never_allocate(tmp_path, model_name, limits):
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from physharness.api import create_app
    from physharness.config import Settings

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        artifact_root=tmp_path / "artifacts",
        auto_create_schema=True,
        auth_tokens={
            "mock-research-key": {"id": "researcher", "project_id": "lab", "role": "researcher"}
        },
    )
    with TestClient(create_app(settings)) as api:
        service = api.app.state.service
        actor = Principal(id="researcher", project_id="lab", role="researcher")
        reviewer = Principal(id="fixture-reviewer", project_id="lab", role="reviewer")
        existing, _ = setup_experiment((service, actor, reviewer))
        created = api.post(
            "/v1/experiments",
            headers={"Authorization": "Bearer mock-research-key", "Idempotency-Key": "bad-runtime"},
            json={
                "campaign_id": existing["campaign_id"],
                "problem_id": existing["problem_id"],
                "models": [{"runtime": "responses", "model": model_name}],
                "budget": existing["budget"],
                "runtime_limits": limits,
            },
        )
        assert created.status_code == 201
        experiment = created.json()
        service.transition_experiment(experiment["id"], "start", 1, actor, "start")
        branch = service.create_branch(
            experiment["id"], BranchCreate(title="B", objective="Research"), actor, "branch"
        )
        task = service.create_task(
            TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task"
        )
        executor = ResearchTaskExecutor(
            service,
            prices={model_name: {"input_usd_per_million": "1", "output_usd_per_million": "1"}},
        )
        with pytest.raises(HarnessError) as error:
            await executor.execute(task["id"], actor.project_id)
        assert error.value.code == "INVALID_CONFIG"
        assert model_name.strip() not in str(error.value)
        assert service.get_record("task", task["id"], actor)["status"] == "queued"
        with service.db.sessions() as session:
            assert session.get(LeaseRow, task["id"]) is None
            assert list(session.scalars(select(ReservationRow))) == []
        assert service.list_records("session", actor) == []
