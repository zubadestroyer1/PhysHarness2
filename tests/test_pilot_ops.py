"""Offline operations helper tests; never load a private pilot database."""

import importlib.util
import json
from pathlib import Path

import pytest
from test_core import setup_experiment

from physharness.domain import ArtifactCreate, Principal, ProblemCreate
from physharness.errors import HarnessError
from physharness.storage import RecordRow

HELPER = Path(__file__).parents[1] / "work/long-horizon-2026-09-23/pilot_ops.py"
spec = importlib.util.spec_from_file_location("two_target_pilot_ops", HELPER)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


@pytest.fixture
def source(lab, tmp_path, monkeypatch):
    service, actor, reviewer = lab
    first_experiment, first = setup_experiment(lab)
    second = service.create_problem(
        ProblemCreate(
            campaign_id=first["campaign_id"],
            title="Second target",
            program="quantum",
            informal_statement="Second synthetic target",
            formal_statement="theorem target2 : True := by trivial",
            assumptions=["Finite fixture"],
            environment_digest="a" * 64,
        ),
        actor,
        "second-problem",
    )
    service.review_problem(
        second["id"], "approved", "Reviewed synthetic fixture", reviewer, "second-review"
    )
    # Deliberately add old work. Import must leave it behind.
    service.create_artifact(
        ArtifactCreate(
            experiment_id=first_experiment["id"],
            kind="reference_proof",
            content="private prior proof",
        ),
        actor,
        "prior-artifact",
    )
    monkeypatch.setattr(ops, "TARGETS", {"projection": first["id"], "purity": second["id"]})
    database = Path(service.db.engine.url.database)
    destination = tmp_path / "isolated" / "harness.db"
    manifest = tmp_path / "isolated" / "source-manifest.json"
    return service, actor, database, destination, manifest


def test_import_only_reviewed_allowlist_with_exact_hashes(source, tmp_path):
    _, actor, database, destination, manifest_path = source
    result = ops.import_reviewed_targets(
        database, destination, manifest_path, project_id=actor.project_id
    )
    manifest = json.loads(manifest_path.read_text())
    assert result["manifest_sha256"] == ops.digest_json(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    assert result["record_count"] in {5, 6}  # Shared or distinct campaigns.
    isolated = ops.isolated_service(destination, tmp_path / "isolated" / "artifacts")
    with isolated.db.sessions() as session:
        rows = list(session.query(RecordRow))
    assert {row.kind for row in rows} == {"campaign", "problem", "review"}
    assert {row.id for row in rows if row.kind == "problem"} == set(ops.TARGETS.values())
    assert {entry["payload_sha256"] for entry in manifest["records"]} == {
        ops.digest_json(row.payload) for row in rows
    }
    with pytest.raises(ops.PilotOpsError, match="DESTINATION_NOT_EMPTY"):
        ops.import_reviewed_targets(
            database, destination, manifest_path, project_id=actor.project_id
        )


def test_import_rejects_review_tampering_and_foreign_project(source):
    service, actor, database, destination, manifest_path = source
    with pytest.raises(ops.PilotOpsError, match="SOURCE_SCOPE"):
        ops.import_reviewed_targets(database, destination, manifest_path, project_id="other")
    problem = service.get_record("problem", ops.TARGETS["purity"], actor)
    with service.db.transaction() as session:
        service._replace(
            session, session.get(RecordRow, problem["review_id"]), {"decision": "rejected"}
        )
    with pytest.raises(ops.PilotOpsError, match="REVIEW_MISMATCH"):
        ops.import_reviewed_targets(
            database, destination, manifest_path, project_id=actor.project_id
        )
    assert not destination.exists()


def test_prepare_idempotent_budget_and_redacted_status(source, tmp_path):
    _, actor, database, destination, manifest_path = source
    actor = Principal(id="pilot-operator", project_id=actor.project_id, role="operator")
    ops.import_reviewed_targets(database, destination, manifest_path, project_id=actor.project_id)
    isolated = ops.isolated_service(destination, tmp_path / "isolated" / "artifacts")
    model = {
        "runtime": "responses",
        "model": "operator-chosen-model",
        "parameters": {"reasoning": {"effort": "high"}},
    }
    first = ops.prepare_attempt(
        isolated, actor, target="projection", attempt="a1", model=model, max_concurrency=2
    )
    assert (
        ops.prepare_attempt(
            isolated, actor, target="projection", attempt="a1", model=model, max_concurrency=2
        )
        == first
    )
    experiment = isolated.get_record("experiment", first["experiment_id"], actor)
    assert experiment["budget"] == {
        "max_cost_usd": "25",
        "max_concurrency": 2,
        "max_runtime_seconds": 7200,
        "max_tokens": 4_000_000,
    }
    assert experiment["runtime_limits"] == {
        "max_context_tokens": 128_000,
        "max_total_tokens": 4_000_000,
        "max_turns": 128,
        "max_output_tokens": 16_384,
        "timeout_seconds": 3600,
    }
    assert experiment["models"][0]["parameters"]["context_management"] == [
        {"type": "compaction", "compact_threshold": 8192}
    ]
    assert experiment["sharing"] == "verified"
    snapshot = ops.status(isolated, actor, first)
    assert "private prior proof" not in json.dumps(snapshot)
    assert snapshot["ledger"]["max_cost_usd"] == "25"
    assert snapshot["compaction_count"] == 0
    assert snapshot["handoff_count"] == 0
    assert snapshot["delegated_task_count"] == 0
    assert len(isolated.list_records("experiment", actor)) == 1
    with pytest.raises(HarnessError) as conflict:
        ops.prepare_attempt(
            isolated,
            actor,
            target="projection",
            attempt="a1",
            model={**model, "model": "changed-model"},
            max_concurrency=2,
        )
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(ops.PilotOpsError, match="COMPACTION_THRESHOLD_INVALID"):
        ops.prepare_attempt(
            isolated,
            actor,
            target="purity",
            attempt="bad-threshold",
            model=model,
            compact_threshold=128_000,
        )
    second = ops.prepare_attempt(
        isolated, actor, target="purity", attempt="a2", model=model, compact_threshold=32_768
    )
    assert second["compact_threshold"] == 32_768
    assert (
        isolated.get_record("experiment", second["experiment_id"], actor)["models"][0][
            "parameters"
        ]["context_management"][0]["compact_threshold"]
        == 32_768
    )
    export_path = tmp_path / "isolated" / "exports" / "projection.json"
    exported = ops.export_attempt(isolated, actor, first, export_path)
    assert exported["manifest_sha256"] == json.loads(export_path.read_text())["manifest_sha256"]
    assert export_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ops.PilotOpsError, match="EXPORT_EXISTS"):
        ops.export_attempt(isolated, actor, first, export_path)


@pytest.mark.asyncio
async def test_run_is_preflight_blocked_without_credentials_or_price(source, tmp_path):
    _, actor, database, destination, manifest_path = source
    actor = Principal(id="pilot-operator", project_id=actor.project_id, role="operator")
    ops.import_reviewed_targets(database, destination, manifest_path, project_id=actor.project_id)
    isolated = ops.isolated_service(destination, tmp_path / "isolated" / "artifacts")
    descriptor = ops.prepare_attempt(
        isolated,
        actor,
        target="purity",
        attempt="dry",
        model={"runtime": "responses", "model": "operator-chosen-model"},
    )
    result = await ops.run_attempt(isolated, actor, descriptor, prices={}, environment={})
    assert result["status"] == "blocked"
    assert "MODEL_CREDENTIAL_REQUIRED" in result["codes"]
    assert isolated.list_records("session", actor) == []
    with pytest.raises(ops.PilotOpsError, match="ATTEMPT_SCOPE"):
        ops.status(isolated, actor, {**descriptor, "target": "projection"})
