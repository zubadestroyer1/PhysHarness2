"""Offline, nonsecret preparation and bounded operations for two reviewed targets.

The caller supplies the private source path, isolated destination, model, prices,
verifier, credentials and any workspace factory. Import and preparation never call
a model or VM. This module never prints model context, credentials or proof text.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

from physharness.artifacts import LocalArtifactStore
from physharness.domain import (
    BranchCreate,
    ExperimentCreate,
    ModelConfiguration,
    Principal,
    TaskCreate,
    canonical_json,
    digest_json,
)
from physharness.orchestration.research_worker import (
    ResearchTaskExecutor,
    ResearchTeamRunner,
    TeamRunManifest,
)
from physharness.run_control import run_preflight
from physharness.service import HarnessService
from physharness.storage import Database, RecordRow

TARGETS = {
    "projection": "b3817784-8d0e-4961-9903-c3c0feef1b58",
    "purity": "215b5024-4285-4aa4-baed-05cf37363291",
}
ATTEMPT = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
KIND_ORDER = {"campaign": 0, "problem": 1, "review": 2}


class PilotOpsError(ValueError):
    """Fixed diagnostic code; never include source record content in messages."""


def _fail(code: str):
    raise PilotOpsError(code)


def _regular(path: Path) -> Path:
    if not path.is_file() or path.is_symlink():
        _fail("SOURCE_UNAVAILABLE")
    return path.resolve()


def _source_row(conn, identifier: str, kind: str, project_id: str) -> dict:
    row = conn.execute(
        "SELECT id,project_id,kind,revision,payload FROM records WHERE id=?", (identifier,)
    ).fetchone()
    if row is None or row[0] != identifier or row[1] != project_id or row[2] != kind:
        _fail("SOURCE_SCOPE")
    try:
        payload = json.loads(row[4])
    except (TypeError, ValueError):
        _fail("SOURCE_RECORD_INVALID")
    if (
        not isinstance(payload, dict)
        or payload.get("id") != identifier
        or payload.get("project_id") != project_id
        or payload.get("kind") != kind
        or payload.get("revision") != row[3]
    ):
        _fail("SOURCE_RECORD_INVALID")
    return {
        "id": identifier,
        "project_id": project_id,
        "kind": kind,
        "revision": row[3],
        "payload": payload,
    }


def import_reviewed_targets(
    source_db: Path, destination_db: Path, manifest_path: Path, *, project_id: str
) -> dict:
    """Copy only allowlisted campaign/problem/review records into a new DB."""
    source_db, destination_db, manifest_path = map(Path, (source_db, destination_db, manifest_path))
    source = _regular(source_db)
    if destination_db.exists() or destination_db.is_symlink() or manifest_path.exists():
        _fail("DESTINATION_NOT_EMPTY")
    if not project_id or len(project_id) > 200:
        _fail("PROJECT_INVALID")
    rows: dict[str, dict] = {}
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        for problem_id in TARGETS.values():
            problem = _source_row(conn, problem_id, "problem", project_id)
            data = problem["payload"]
            if (
                data.get("semantic_review") != "approved"
                or not data.get("review_id")
                or not data.get("campaign_id")
                or not data.get("target_digest")
                or data.get("definition_holes") is not False
            ):
                _fail("TARGET_NOT_REVIEWED")
            review = _source_row(conn, data["review_id"], "review", project_id)
            if (
                review["payload"].get("problem_id") != problem_id
                or review["payload"].get("target_digest") != data["target_digest"]
                or review["payload"].get("decision") != "approved"
            ):
                _fail("REVIEW_MISMATCH")
            campaign = _source_row(conn, data["campaign_id"], "campaign", project_id)
            if data.get("program") not in campaign["payload"].get("programs", []):
                _fail("CAMPAIGN_MISMATCH")
            for record in (campaign, problem, review):
                existing = rows.get(record["id"])
                if existing is not None and existing != record:
                    _fail("SOURCE_CONFLICT")
                rows[record["id"]] = record
        conn.rollback()
    ordered = sorted(rows.values(), key=lambda r: (KIND_ORDER[r["kind"]], r["id"]))
    manifest = {
        "format": "physharness.two-reviewed-target-import.v1",
        "project_id": project_id,
        "targets": dict(TARGETS),
        "record_count": len(ordered),
        "records": [
            {
                "id": r["id"],
                "kind": r["kind"],
                "revision": r["revision"],
                "payload_sha256": digest_json(r["payload"]),
            }
            for r in ordered
        ],
        "excluded_kinds": [
            "experiment",
            "branch",
            "task",
            "claim",
            "artifact",
            "verification",
            "session",
        ],
    }
    manifest["manifest_sha256"] = digest_json(manifest)
    destination_db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Exclusive creation refuses a concurrent/repeated import before SQL writes.
    with destination_db.open("xb"):
        pass
    db = Database(f"sqlite:///{destination_db}")
    try:
        db.create_schema()
        with db.transaction() as session:
            if session.query(RecordRow).limit(1).first() is not None:
                _fail("DESTINATION_NOT_EMPTY")
            session.add_all(RecordRow(**record) for record in ordered)
    finally:
        db.engine.dispose()
    fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(canonical_json(manifest) + "\n")
    return {
        "manifest_sha256": manifest["manifest_sha256"],
        "record_count": len(ordered),
        "target_ids": dict(TARGETS),
    }


def isolated_service(database: Path, artifacts: Path, *, verifier=None) -> HarnessService:
    """Open an already imported isolated database; never create a missing one."""
    _regular(Path(database))
    return HarnessService(
        Database(f"sqlite:///{Path(database)}"),
        LocalArtifactStore(Path(artifacts)),
        verifier=verifier,
    )


def prepare_attempt(
    service: HarnessService,
    actor: Principal,
    *,
    target: str,
    attempt: str,
    model: ModelConfiguration | dict,
    max_concurrency: int = 2,
    compact_threshold: int = 8192,
) -> dict:
    """Idempotently seed one known-result attempt; no provider call occurs."""
    if target not in TARGETS or not ATTEMPT.fullmatch(attempt):
        _fail("ATTEMPT_INVALID")
    if actor.role not in {"operator", "admin"}:
        _fail("OPERATOR_REQUIRED")
    if type(max_concurrency) is not int or not 1 <= max_concurrency <= 8:
        _fail("CONCURRENCY_INVALID")
    if type(compact_threshold) is not int or not 1 <= compact_threshold <= 111_616:
        _fail("COMPACTION_THRESHOLD_INVALID")
    config = ModelConfiguration.model_validate(model)
    if config.runtime != "responses":
        _fail("RUNTIME_INVALID")
    problem = service.get_record("problem", TARGETS[target], actor)
    review = service.get_record("review", problem["review_id"], actor)
    if (
        problem.get("semantic_review") != "approved"
        or review.get("decision") != "approved"
        or review.get("target_digest") != problem.get("target_digest")
        or problem.get("definition_holes") is not False
    ):
        _fail("TARGET_NOT_REVIEWED")
    parameters = {
        **config.parameters,
        "context_management": [{"type": "compaction", "compact_threshold": compact_threshold}],
    }
    config = config.model_copy(update={"parameters": parameters})
    prefix = f"two-target:{target}:{attempt}"
    experiment = service.create_experiment(
        ExperimentCreate(
            campaign_id=problem["campaign_id"],
            problem_id=problem["id"],
            models=[config],
            budget={
                "max_cost_usd": "25",
                "max_concurrency": max_concurrency,
                "max_runtime_seconds": 7200,
                "max_tokens": 4_000_000,
            },
            policy="direct",
            mode="research",
            sharing="verified",
            runtime_limits={
                "max_context_tokens": 128_000,
                "max_total_tokens": 4_000_000,
                "max_turns": 128,
                "max_output_tokens": 16_384,
                "timeout_seconds": 3600,
            },
        ),
        actor,
        f"{prefix}:experiment",
    )
    branch = service.create_branch(
        experiment["id"],
        BranchCreate(
            title=f"{target} {attempt}",
            objective="Known reviewed target; independent research attempt. "
            "Prior accepted results may be reused only with exact citations.",
        ),
        actor,
        f"{prefix}:branch",
    )
    if experiment["status"] == "created":
        experiment = service.transition_experiment(
            experiment["id"], "start", experiment["revision"], actor, f"{prefix}:start"
        )
    tasks = [
        r
        for r in service.list_records("task", actor, experiment["id"])
        if r.get("branch_id") == branch["id"] and r.get("origin_actor_id") == actor.id
    ]
    if tasks:
        if len(tasks) != 1:
            _fail("ATTEMPT_STATE_AMBIGUOUS")
        task = tasks[0]
    else:
        task = service.create_task(
            TaskCreate(
                branch_id=branch["id"],
                objective="Investigate the exact reviewed target; report assumptions, "
                "failed approaches, and unresolved gaps. "
                "Use accepted prior results only with exact provenance.",
            ),
            actor,
            f"{prefix}:task",
        )
    return {
        "target": target,
        "attempt": attempt,
        "known_result": True,
        "experiment_id": experiment["id"],
        "branch_id": branch["id"],
        "task_id": task["id"],
        "status": task["status"],
        "budget_usd": "25",
        "max_concurrency": max_concurrency,
        "compact_threshold": compact_threshold,
    }


def status(service: HarnessService, actor: Principal, descriptor: dict) -> dict:
    """Allowlisted metadata only; never return artifact text or native context."""
    experiment, task = _bound_attempt(service, actor, descriptor)
    receipts = service.list_records("verification", actor, experiment["id"])
    sessions = service.list_records("session", actor, experiment["id"])
    tasks = service.list_records("task", actor, experiment["id"])
    compactions = 0
    for item in service.list_records("artifact", actor, experiment["id"]):
        if item.get("artifact_kind") != "runtime_event":
            continue
        event = json.loads(service.artifact_content(item["id"], actor))
        compactions += event.get("kind") == "compaction"
    return {
        "target": descriptor["target"],
        "known_result": True,
        "experiment_id": experiment["id"],
        "experiment_status": experiment["status"],
        "task_id": task["id"],
        "task_status": task["status"],
        "receipt_statuses": [
            {"id": r["id"], "status": r.get("status"), "assurance": r.get("assurance")}
            for r in receipts
        ],
        "compaction_count": compactions,
        "handoff_count": sum(item.get("status") == "handed_off" for item in sessions),
        "delegated_task_count": sum(bool(item.get("delegated_from_task_id")) for item in tasks),
        "ledger": service.ledger(experiment["id"], actor),
    }


def _bound_attempt(service: HarnessService, actor: Principal, descriptor: dict):
    if (
        not isinstance(descriptor, dict)
        or descriptor.get("target") not in TARGETS
        or not isinstance(descriptor.get("attempt"), str)
        or not ATTEMPT.fullmatch(descriptor["attempt"])
    ):
        _fail("ATTEMPT_INVALID")
    experiment = service.get_record("experiment", descriptor["experiment_id"], actor)
    task = service.get_record("task", descriptor["task_id"], actor)
    if (
        experiment.get("problem_id") != TARGETS[descriptor["target"]]
        or task.get("experiment_id") != experiment["id"]
        or task.get("branch_id") != descriptor.get("branch_id")
    ):
        _fail("ATTEMPT_SCOPE")
    return experiment, task


async def run_attempt(
    service: HarnessService,
    actor: Principal,
    descriptor: dict,
    *,
    prices: dict,
    environment: dict,
    workspace_factory=None,
) -> dict:
    """Launch only after explicit live preflight; second call cannot replay old native work."""
    experiment, task = _bound_attempt(service, actor, descriptor)
    experiment_id, task_id = experiment["id"], task["id"]
    if task["status"] in {"completed", "failed", "blocked"}:
        return {
            "status": "already_terminal",
            "task_status": task["status"],
            "experiment_id": experiment_id,
            "attempted_tasks": 0,
            "ledger": service.ledger(experiment_id, actor),
        }
    sessions = [
        row
        for row in service.list_records("session", actor, experiment_id)
        if row.get("task_id") == task_id
    ]
    if sessions and not task.get("ready_continuation"):
        return {
            "status": "blocked",
            "codes": ["RECOVERY_RECONCILIATION_REQUIRED"],
            "experiment_id": experiment_id,
        }
    preflight = run_preflight(service, actor, experiment_id, prices=prices, environment=environment)
    if preflight["status"] != "ready_for_live_attempt":
        return {
            "status": "blocked",
            "codes": [b["code"] for b in preflight["blockers"]],
            "experiment_id": experiment_id,
        }
    executor = ResearchTaskExecutor(service, prices=prices, workspace_factory=workspace_factory)
    result = await ResearchTeamRunner(service, executor=executor).run(
        TeamRunManifest(
            experiment_id=experiment_id,
            project_id=actor.project_id,
            mode="live",
            task_ids=[task_id],
            include_delegated=True,
            max_concurrency=experiment["budget"]["max_concurrency"],
            max_tasks=64,
            timeout_seconds=7200,
            max_verifications=64,
            run_id=f"two-target:{descriptor['target']}:{descriptor['attempt']}:run",
        )
    )
    return {
        "status": result["status"],
        "stop_reason": result["stop_reason"],
        "experiment_id": experiment_id,
        "report_artifact_id": result["artifact_id"],
        "attempted_tasks": result["attempted_tasks"],
        "ledger": result["ledger"],
    }


def export_attempt(
    service: HarnessService, actor: Principal, descriptor: dict, output: Path
) -> dict:
    """Write full private reproduction export; return only its hash and path."""
    output = Path(output)
    if output.exists() or output.is_symlink():
        _fail("EXPORT_EXISTS")
    experiment, _ = _bound_attempt(service, actor, descriptor)
    manifest = service.export_experiment(experiment["id"], actor)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(canonical_json(manifest) + "\n")
    return {
        "experiment_id": descriptor["experiment_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "output": str(output),
    }
