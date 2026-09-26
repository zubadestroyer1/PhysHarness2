"""Private two-target regression operator. Preparation and status make no provider calls."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import traceback
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from physharness.domain import BranchCreate, ExperimentCreate, Principal, TaskCreate, digest_json
from physharness.errors import HarnessError
from physharness.execution.types import RuntimeCheckpoint
from physharness.orchestration.pricing import ModelPrice
from physharness.orchestration.research_worker import (
    ResearchTaskExecutor,
    ResearchTeamRunner,
    TeamRunManifest,
)
from physharness.orchestration.workspace_selection import configured_workspace_factory
from physharness.orchestration.workspace_tools import WorkspacePolicy
from physharness.reproduction import validate_export
from physharness.run_control import run_preflight, validate_runtime_inputs
from physharness.storage import CommandRow, EventRow, RecordRow, ReservationRow

HERE = Path(__file__).resolve().parent
PRIVATE = HERE.parent.parent / ".state/research-effectiveness-2026-09-23/private"
SOURCE = HERE.parent.parent / ".state/runs/first-pilot/private/harness.db"
HISTORICAL = HERE.parent / "long-horizon-2026-09-23/pilot_ops.py"
IMAGE = "sha256:48e4f60a07c289baf846c0ff6fa2624870c59547c2a00971db0510e767161be0"
DOCKER_HOST = "unix://" + os.path.expanduser("~/.colima/physharness-pilot/docker.sock")
TARGETS = {
    "projection": "b3817784-8d0e-4961-9903-c3c0feef1b58",
    "purity": "215b5024-4285-4aa4-baed-05cf37363291",
}
ATTEMPT = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
TERMINAL = {"completed", "failed", "blocked", "cancelled"}
SAFE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")


class PilotError(ValueError):
    """Fixed safe code only; never attach record or exception contents."""


def _safe_label(value):
    return value if isinstance(value, str) and SAFE_CODE.fullmatch(value) else None


def historical():
    spec = importlib.util.spec_from_file_location("historical_pilot_ops", HISTORICAL)
    if spec is None or spec.loader is None:
        raise PilotError("HISTORICAL_HELPER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _descriptor_path(private: Path, target: str) -> Path:
    return private / f"{target}-attempt.json"


@contextmanager
def _lock(private: Path, *, blocking: bool = True):
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(private, 0o700)
    fd = os.open(private / ".operator.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            raise PilotError("ATTEMPT_ACTIVE") from None
        yield
    finally:
        os.close(fd)


def _write_new(path: Path, value: dict):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _atomic_new_bytes(path: Path, data: bytes):
    temporary = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
    finally:
        temporary.unlink(missing_ok=True)


def _command_result(service, actor, key: str) -> dict | None:
    command_id = digest_json([actor.project_id, actor.id, key])
    with service.db.sessions() as session:
        row = session.get(CommandRow, command_id)
        return row.result if row is not None and row.project_id == actor.project_id else None


@contextmanager
def _mounted_tmp():
    """Keep verifier scratch beneath the worktree mounted into dedicated Colima."""
    path = HERE.parent.parent / ".state/research-effectiveness-2026-09-23/tmp"
    if path.is_symlink():
        raise PilotError("VERIFIER_TMP_UNAVAILABLE")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    if not path.is_dir() or not os.access(path, os.W_OK | os.X_OK):
        raise PilotError("VERIFIER_TMP_UNAVAILABLE")
    previous_env, previous_cache = os.environ.get("TMPDIR"), tempfile.tempdir
    os.environ["TMPDIR"] = str(path)
    tempfile.tempdir = str(path)
    try:
        yield
    finally:
        tempfile.tempdir = previous_cache
        if previous_env is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = previous_env


def _read_descriptor(private: Path, target: str) -> dict:
    if target not in TARGETS:
        raise PilotError("TARGET_INVALID")
    path = _descriptor_path(private, target)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 4096:
        raise PilotError("ATTEMPT_NOT_PREPARED")
    value = json.loads(path.read_text())
    if value.get("target") != target or not ATTEMPT.fullmatch(value.get("attempt", "")):
        raise PilotError("ATTEMPT_DESCRIPTOR_INVALID")
    return value


def _service(private: Path, *, verifier=None):
    return historical().isolated_service(
        private / "harness.db", private / "artifacts", verifier=verifier
    )


def _actor(project_id: str) -> Principal:
    return Principal(id="research-effectiveness-operator", project_id=project_id, role="operator")


def _scope(service, actor, descriptor):
    target = descriptor["target"]
    experiment = service.get_record("experiment", descriptor["experiment_id"], actor)
    task = service.get_record("task", descriptor["task_id"], actor)
    problem = service.get_record("problem", TARGETS[target], actor)
    review = service.get_record("review", problem["review_id"], actor)
    if (
        experiment["problem_id"] != TARGETS[target]
        or experiment["campaign_id"] != problem["campaign_id"]
        or experiment["target_digest"] != problem["target_digest"]
        or task["experiment_id"] != experiment["id"]
        or task["branch_id"] != descriptor["branch_id"]
        or problem["semantic_review"] != "approved"
        or review["decision"] != "approved"
        or review["target_digest"] != problem["target_digest"]
    ):
        raise PilotError("ATTEMPT_SCOPE")
    return experiment, task, problem


def _request(problem: dict) -> ExperimentCreate:
    request = ExperimentCreate.model_validate(
        {
            "campaign_id": problem["campaign_id"],
            "problem_id": problem["id"],
            "models": [
                {
                    "runtime": "responses",
                    "model": "gpt-6-sol",
                    "parameters": {"reasoning": {"effort": "high"}},
                }
            ],
            "budget": {
                "max_cost_usd": "25",
                "max_concurrency": 1,
                "max_runtime_seconds": 7200,
                "max_tokens": None,
            },
            "policy": "direct",
            "mode": "research",
            "sharing": "ideas",
            "execution_profile": "formal-research",
            "context_profile": "research",
            "runtime_limits": {
                "max_context_tokens": 128000,
                "max_output_tokens": 16384,
                "max_total_tokens": None,
                "max_turns": 128,
                "timeout_seconds": 3600,
            },
        }
    )
    validate_runtime_inputs(request.models, request.runtime_limits)
    return request


def _campaign_allocations(service, actor, campaign_id: str) -> dict[str, list[dict]]:
    allocations = {name: [] for name in TARGETS}
    for experiment in service.list_records("experiment", actor):
        if experiment.get("campaign_id") != campaign_id:
            continue
        if experiment.get("problem_id") not in TARGETS.values():
            raise PilotError("CAMPAIGN_ALLOCATION_EXHAUSTED")
        for name, problem_id in TARGETS.items():
            if experiment.get("problem_id") == problem_id:
                allocations[name].append(experiment)
    return allocations


def _handoff_events(service, actor, task_ids: set[str]) -> list[dict]:
    """Read canonical issue events, including tickets already consumed."""
    with service.db.sessions() as session:
        rows = session.scalars(
            select(EventRow).where(
                EventRow.project_id == actor.project_id,
                EventRow.kind == "task.queued",
                EventRow.aggregate_id.in_(task_ids),
            )
        )
        return [
            row.payload["continuation"]
            for row in rows
            if isinstance(row.payload.get("continuation"), dict)
        ]


def _exact_verified(service, actor, experiment: dict, receipts: list[dict]) -> set[str]:
    """Use the canonical acceptance predicate; receipt labels alone are insufficient."""
    accepted = set()
    with service.db.sessions() as session:
        exp_row = session.get(RecordRow, experiment["id"])
        for receipt in receipts:
            row = session.get(RecordRow, receipt["id"])
            if row is not None and service._accepted_evidence(
                session, row, exp_row, {"independent_kernel"}
            ):
                accepted.add(receipt["id"])
    return accepted


def prepare(private: Path, source: Path, project_id: str, target: str, attempt: str) -> dict:
    """Import exactly reviewed records and reserve one of two lifetime campaign slots."""
    if target not in TARGETS or not ATTEMPT.fullmatch(attempt):
        raise PilotError("ATTEMPT_INVALID")
    with _lock(private):
        database = private / "harness.db"
        manifest = private / "reviewed-import.json"
        if not database.exists():
            historical().import_reviewed_targets(source, database, manifest, project_id=project_id)
        elif not manifest.is_file() or manifest.is_symlink():
            raise PilotError("IMPORT_MANIFEST_MISSING")
        service, actor = _service(private), _actor(project_id)
        path = _descriptor_path(private, target)
        if path.exists() or path.is_symlink():
            descriptor = _read_descriptor(private, target)
            if descriptor["attempt"] != attempt:
                raise PilotError("CAMPAIGN_ALLOCATION_EXHAUSTED")
            _scope(service, actor, descriptor)
            return descriptor
        problem = service.get_record("problem", TARGETS[target], actor)
        allocations = _campaign_allocations(service, actor, problem["campaign_id"])
        if allocations[target] or sum(len(rows) for rows in allocations.values()) >= 2:
            raise PilotError("CAMPAIGN_ALLOCATION_EXHAUSTED")
        review = service.get_record("review", problem["review_id"], actor)
        if (
            problem.get("semantic_review") != "approved"
            or review.get("decision") != "approved"
            or review.get("target_digest") != problem.get("target_digest")
            or problem.get("definition_holes") is not False
        ):
            raise PilotError("TARGET_NOT_REVIEWED")
        prefix = f"research-effectiveness:{target}:{attempt}"
        experiment = service.create_experiment(_request(problem), actor, prefix + ":experiment")
        branch = service.create_branch(
            experiment["id"],
            BranchCreate(
                title=f"{target} research effectiveness",
                relation="competing",
                objective=(
                    "Investigate the exact independently reviewed target and submit a proof "
                    "with evidence. Choose methods freely."
                ),
            ),
            actor,
            prefix + ":branch",
        )
        # Task allocation requires an active experiment. No worker is attached to
        # this isolated offline service; pause immediately after task creation.
        experiment = service.transition_experiment(
            experiment["id"], "start", experiment["revision"], actor, prefix + ":prepare-start"
        )
        task = service.create_task(
            TaskCreate(
                branch_id=branch["id"],
                objective=(
                    "Investigate the exact reviewed target; submit any proposed proof for "
                    "independent verification and report unresolved obligations."
                ),
            ),
            actor,
            prefix + ":task",
        )
        service.transition_experiment(
            experiment["id"], "pause", experiment["revision"], actor, prefix + ":prepare-pause"
        )
        descriptor = {
            "target": target,
            "attempt": attempt,
            "project_id": project_id,
            "experiment_id": experiment["id"],
            "branch_id": branch["id"],
            "task_id": task["id"],
            "max_cost_usd": "25",
            "model_calls": 0,
        }
        _write_new(path, descriptor)
        return descriptor


def _zero_effect_audit(
    service, actor, descriptor: dict, *, new_task_id=None, recovering: bool = False
) -> dict:
    """Prove the first task never passed its non-generative startup boundary."""
    experiment, task, _ = _scope(service, actor, descriptor)
    eid = experiment["id"]
    allowed_experiment_states = (
        {"paused", "blocked", "queued"} if recovering else {"paused", "blocked"}
    )
    if task["status"] != "blocked" or experiment["status"] not in allowed_experiment_states:
        raise PilotError("RETRY_STATE_NOT_TERMINAL")
    if task.get("ready_continuation") or task.get("consumed_continuation"):
        raise PilotError("RETRY_CONTINUATION_EXISTS")
    ledger = service.ledger(eid, actor)
    if (
        ledger.get("max_cost_usd") not in {"25", "25.000000"}
        or ledger.get("max_concurrency") != 1
        or any(ledger.get(key) != "0" for key in ("spent_cost_usd", "reserved_cost_usd"))
        or any(
            ledger.get(key) != 0
            for key in ("active_workers", "uncertain_operations", "tokens_reserved", "tokens_spent")
        )
    ):
        raise PilotError("RETRY_LEDGER_NOT_ZERO")
    rows = {
        kind: service.list_records(kind, actor, eid)
        for kind in (
            "task",
            "session",
            "claim",
            "verification",
            "workspace",
            "workspace_operation",
            "model_reservation",
            "artifact",
        )
    }
    expected_task_ids = {task["id"]} | ({new_task_id} if new_task_id else set())
    if {row["id"] for row in rows["task"]} != expected_task_ids:
        raise PilotError("RETRY_TASK_SCOPE")
    if new_task_id and any(
        row["id"] == new_task_id and row.get("status") != "queued" for row in rows["task"]
    ):
        raise PilotError("RETRY_TASK_SCOPE")
    if any(
        rows[kind]
        for kind in (
            "claim",
            "verification",
            "workspace",
            "workspace_operation",
            "model_reservation",
        )
    ):
        raise PilotError("RETRY_EFFECTS_PRESENT")
    if not rows["session"] or any(
        row.get("task_id") != task["id"]
        or row.get("status") not in {"failed", "blocked"}
        or row.get("input_tokens") != 0
        or row.get("output_tokens") != 0
        or row.get("turns", 0) != 0
        for row in rows["session"]
    ):
        raise PilotError("RETRY_SESSION_NOT_ZERO")
    allowed_artifacts = {
        "native_checkpoint",
        "execution_failure",
        "team_run_manifest",
        "team_run_report",
    }
    checkpoint_count = 0
    for artifact in rows["artifact"]:
        kind = artifact.get("artifact_kind")
        if kind not in allowed_artifacts:
            raise PilotError("RETRY_EFFECTS_PRESENT")
        if kind == "native_checkpoint":
            body = service.artifact_content(artifact["id"], actor)
            if len(body) > 5_000_000:
                raise PilotError("RETRY_CHECKPOINT_INVALID")
            checkpoint = RuntimeCheckpoint.model_validate_json(body)
            checkpoint.verify()
            native = checkpoint.native_state
            if (
                checkpoint.session.turns != 0
                or checkpoint.session.input_tokens != 0
                or checkpoint.session.output_tokens != 0
                or native.get("pending_operation")
                or native.get("terminal_response_pending")
                or native.get("responses")
                or native.get("tool_results")
                or native.get("archives")
                or native.get("archive_refs")
                or native.get("provider_compaction_count", 0) != 0
            ):
                raise PilotError("RETRY_CHECKPOINT_NOT_ZERO")
            checkpoint_count += 1
    if checkpoint_count == 0:
        raise PilotError("RETRY_CHECKPOINT_MISSING")
    with service.db.sessions() as session:
        reservations = list(
            session.scalars(select(ReservationRow).where(ReservationRow.experiment_id == eid))
        )
        if any(
            row.workers != 1
            or row.state != "settled"
            or row.reserved != 0
            or row.actual != 0
            or row.tokens_reserved != 0
            or row.tokens_actual != 0
            for row in reservations
        ):
            raise PilotError("RETRY_RESERVATION_NOT_ZERO")
    return {
        "sessions_checked": len(rows["session"]),
        "checkpoints_checked": checkpoint_count,
        "settled_zero_worker_slots": len(reservations),
        "model_calls": 0,
    }


def _settled_effect_audit(
    service, actor, descriptor: dict, *, new_task_id=None, recovering: bool = False
) -> dict:
    """Require settled billing and a known pre-provision tool failure before fresh work."""
    experiment, source_task, _ = _scope(service, actor, descriptor)
    eid = experiment["id"]
    states = {"paused", "blocked", "queued"} if recovering else {"paused", "blocked"}
    if experiment["status"] not in states:
        raise PilotError("RESTART_EXPERIMENT_ACTIVE")
    started = datetime.fromisoformat(experiment["started_at"])
    deadline = started + timedelta(seconds=experiment["budget"]["max_runtime_seconds"])
    if started.tzinfo is None or datetime.now(UTC) >= deadline:
        raise PilotError("RESTART_DEADLINE_EXPIRED")
    ledger = service.ledger(eid, actor)
    spent = Decimal(str(ledger.get("spent_cost_usd")))
    if (
        Decimal(str(ledger.get("max_cost_usd"))) != 25
        or ledger.get("max_concurrency") != 1
        or Decimal(str(ledger.get("reserved_cost_usd"))) != 0
        or not 0 < spent < 25
        or any(
            ledger.get(k) != 0
            for k in ("active_workers", "uncertain_operations", "tokens_reserved")
        )
    ):
        raise PilotError("RESTART_LEDGER_UNSETTLED")
    rows = {
        kind: service.list_records(kind, actor, eid)
        for kind in (
            "task",
            "session",
            "claim",
            "model_reservation",
            "verification",
            "workspace",
            "workspace_operation",
            "artifact",
        )
    }
    old_tasks = [row for row in rows["task"] if row["id"] != new_task_id]
    if (
        not old_tasks
        or source_task["id"] not in {row["id"] for row in old_tasks}
        or any(
            row.get("status") not in TERMINAL or row.get("ready_continuation") for row in old_tasks
        )
        or (new_task_id is None and len(old_tasks) != len(rows["task"]))
        or (
            new_task_id is not None
            and [row.get("status") for row in rows["task"] if row["id"] == new_task_id]
            != ["queued"]
        )
    ):
        raise PilotError("RESTART_TASK_SCOPE")
    if rows["verification"] or rows["claim"]:
        raise PilotError("RESTART_VERIFICATION_EFFECT")
    if any(
        row.get("status") != "destroyed" or row.get("billing_status") != "reconciled"
        for row in rows["workspace"]
    ):
        raise PilotError("RESTART_WORKSPACE_UNSETTLED")
    if any(
        row.get("status") not in {"completed", "rejected"} for row in rows["workspace_operation"]
    ):
        raise PilotError("RESTART_WORKSPACE_UNSETTLED")
    failures = []
    for artifact in rows["artifact"]:
        if artifact.get("artifact_kind") == "execution_failure":
            body = service.artifact_content(artifact["id"], actor)
            if len(body) > 1_000_000:
                raise PilotError("RESTART_FAILURE_INVALID")
            failures.append((artifact.get("created_at", ""), json.loads(body)))
    if not failures:
        raise PilotError("RESTART_FAILURE_SCOPE")
    failure = max(failures, key=lambda pair: pair[0])[1]
    if failure.get("code") != "EXPERIMENT_DEADLINE" or failure.get("task_id") != source_task["id"]:
        raise PilotError("RESTART_FAILURE_SCOPE")
    with service.db.sessions() as session:
        reservations = list(
            session.scalars(select(ReservationRow).where(ReservationRow.experiment_id == eid))
        )
    if any(
        row.state != "settled"
        or row.actual is None
        or row.tokens_actual is None
        or row.reserved < 0
        or row.actual < 0
        or row.tokens_actual < 0
        for row in reservations
    ):
        raise PilotError("RESTART_RESERVATION_UNSETTLED")
    model_bindings = {row["reservation_id"]: row for row in rows["model_reservation"]}
    if (
        len(model_bindings) != len(rows["model_reservation"])
        or any(row.get("status") != "settled" for row in model_bindings.values())
        or {row.id for row in reservations if row.workers == 0} != set(model_bindings)
        or sum(row.actual for row in reservations) != int(spent * 1_000_000)
        or sum(row.tokens_actual for row in reservations) != ledger.get("tokens_spent")
    ):
        raise PilotError("RESTART_RESERVATION_UNSETTLED")
    artifacts = {row["id"]: row for row in rows["artifact"]}
    pending_count = 0
    if not rows["session"]:
        raise PilotError("RESTART_SESSION_UNSETTLED")
    for row in rows["session"]:
        if row.get("task_id") not in {task["id"] for task in old_tasks} or row.get(
            "status"
        ) not in {"failed", "completed", "blocked", "uncertain"}:
            raise PilotError("RESTART_SESSION_UNSETTLED")
        artifact = artifacts.get(row.get("checkpoint_artifact_id"))
        if artifact is None or artifact.get("artifact_kind") != "native_checkpoint":
            raise PilotError("RESTART_CHECKPOINT_INVALID")
        body = service.artifact_content(artifact["id"], actor)
        if len(body) > 5_000_000:
            raise PilotError("RESTART_CHECKPOINT_INVALID")
        checkpoint = RuntimeCheckpoint.model_validate_json(body)
        checkpoint.verify()
        if (
            checkpoint.session.status != row["status"]
            or checkpoint.session.input_tokens != row.get("input_tokens")
            or checkpoint.session.output_tokens != row.get("output_tokens")
        ):
            raise PilotError("RESTART_CHECKPOINT_INVALID")
        pending = checkpoint.native_state.get("pending_operation")
        if row["status"] == "uncertain":
            last = checkpoint.native_state.get("input", [])[-1:]
            if (
                row["task_id"] != source_task["id"]
                or not pending
                or len(last) != 1
                or not isinstance(last[0], dict)
                or last[0].get("type") != "function_call"
                or last[0].get("name") != "search_library_source"
                or pending != f"{checkpoint.session.id}:{last[0].get('call_id')}"
                or failure.get("operation_id") != pending
                or checkpoint.native_state.get("tool_results", {}).get(pending)
                or any(
                    item.get("type") == "function_call_output"
                    and item.get("call_id") == last[0].get("call_id")
                    for item in checkpoint.native_state.get("input", [])
                    if isinstance(item, dict)
                )
                or rows["workspace"]
                or rows["workspace_operation"]
            ):
                raise PilotError("RESTART_NATIVE_UNCERTAIN")
            pending_count += 1
        elif pending:
            raise PilotError("RESTART_NATIVE_UNCERTAIN")
    if pending_count != 1:
        raise PilotError("RESTART_NATIVE_UNCERTAIN")
    return {
        "model_cost_spent_usd": ledger["spent_cost_usd"],
        "tokens_spent": ledger["tokens_spent"],
        "sessions_checked": len(rows["session"]),
        "settled_reservations": len(reservations),
        "pending_workspace_tool_not_replayed": pending_count,
        "deadline": deadline.isoformat(),
    }


def retry_preflight(
    private: Path,
    project_id: str,
    target: str,
    from_attempt: str,
    attempt: str,
    *,
    settled: bool = False,
) -> dict:
    """Explicit audited restart within the same experiment and original deadline."""
    if (
        target not in TARGETS
        or not ATTEMPT.fullmatch(from_attempt)
        or not ATTEMPT.fullmatch(attempt)
        or from_attempt == attempt
    ):
        raise PilotError("ATTEMPT_INVALID")
    mode = "settled" if settled else "zero"
    audit_fn = _settled_effect_audit if settled else _zero_effect_audit
    with _lock(private, blocking=False):
        descriptor = _read_descriptor(private, target)
        if descriptor["project_id"] != project_id:
            raise PilotError("PROJECT_SCOPE")
        archive = private / f"{target}-{from_attempt}-descriptor.json"
        intent_path = private / f"{target}-{from_attempt}-to-{attempt}-retry-intent.json"
        service, actor = _service(private), _actor(project_id)
        if descriptor["attempt"] == attempt:
            if not intent_path.is_file() or archive.is_symlink() or not archive.is_file():
                raise PilotError("RETRY_INTENT_MISMATCH")
            if hashlib.sha256(archive.read_bytes()).hexdigest() != descriptor.get(
                "previous_descriptor_sha256"
            ):
                raise PilotError("RETRY_INTENT_MISMATCH")
            _scope(service, actor, descriptor)
            return descriptor
        if descriptor["attempt"] != from_attempt or (
            descriptor.get("previous_attempt") and not settled
        ):
            raise PilotError("RETRY_ALREADY_USED")
        path = _descriptor_path(private, target)
        prior_bytes = path.read_bytes()
        prior_sha = hashlib.sha256(prior_bytes).hexdigest()
        experiment, _, _ = _scope(service, actor, descriptor)
        prefix = f"research-effectiveness:{target}:{attempt}"
        if intent_path.exists() or intent_path.is_symlink():
            if (
                not intent_path.is_file()
                or intent_path.is_symlink()
                or intent_path.stat().st_size > 4096
            ):
                raise PilotError("RETRY_INTENT_MISMATCH")
            intent = json.loads(intent_path.read_text())
            if (
                set(intent)
                != {
                    "from_attempt",
                    "attempt",
                    "old_descriptor_sha256",
                    "experiment_id",
                    "experiment_revision",
                    "mode",
                }
                or intent["from_attempt"] != from_attempt
                or intent["attempt"] != attempt
                or intent["old_descriptor_sha256"] != prior_sha
                or intent["experiment_id"] != experiment["id"]
                or intent["mode"] != mode
                or type(intent["experiment_revision"]) is not int
                or not 1 <= intent["experiment_revision"] <= experiment["revision"]
            ):
                raise PilotError("RETRY_INTENT_MISMATCH")
            task_result = _command_result(service, actor, prefix + ":task")
            new_task_id = task_result.get("id") if isinstance(task_result, dict) else None
            audit = audit_fn(service, actor, descriptor, new_task_id=new_task_id, recovering=True)
        else:
            if archive.exists() or archive.is_symlink():
                raise PilotError("RETRY_ALREADY_USED")
            audit = audit_fn(service, actor, descriptor)
            intent = {
                "from_attempt": from_attempt,
                "attempt": attempt,
                "old_descriptor_sha256": prior_sha,
                "experiment_id": experiment["id"],
                "experiment_revision": experiment["revision"],
                "mode": mode,
            }
        allocations = _campaign_allocations(service, actor, experiment["campaign_id"])
        if (
            len(allocations[target]) != 1
            or allocations[target][0]["id"] != experiment["id"]
            or any(len(rows) > 1 for rows in allocations.values())
            or sum(
                Decimal(str(row["budget"]["max_cost_usd"]))
                for rows in allocations.values()
                for row in rows
            )
            > 50
        ):
            raise PilotError("CAMPAIGN_ALLOCATION_EXHAUSTED")
        if not intent_path.exists():
            _atomic_new_bytes(intent_path, (json.dumps(intent, sort_keys=True) + "\n").encode())
        if archive.exists() or archive.is_symlink():
            if archive.is_symlink() or not archive.is_file() or archive.read_bytes() != prior_bytes:
                raise PilotError("RETRY_INTENT_MISMATCH")
        else:
            _atomic_new_bytes(archive, prior_bytes)
        resumed = service.transition_experiment(
            experiment["id"],
            "resume",
            intent["experiment_revision"],
            actor,
            prefix + ":retry-resume",
        )
        branch = service.create_branch(
            experiment["id"],
            BranchCreate(
                title=f"{target} research effectiveness retry",
                relation="competing",
                objective=(
                    "Investigate the exact independently reviewed target and submit a proof "
                    "with evidence. Choose methods freely."
                ),
            ),
            actor,
            prefix + ":branch",
        )
        task = service.create_task(
            TaskCreate(
                branch_id=branch["id"],
                objective=(
                    "Investigate the exact reviewed target; submit any proposed proof for "
                    "independent verification and report unresolved obligations."
                ),
            ),
            actor,
            prefix + ":task",
        )
        service.transition_experiment(
            experiment["id"], "pause", resumed["revision"], actor, prefix + ":retry-pause"
        )
        updated = {
            "target": target,
            "attempt": attempt,
            "project_id": project_id,
            "experiment_id": experiment["id"],
            "branch_id": branch["id"],
            "task_id": task["id"],
            "max_cost_usd": "25",
            "model_calls": 0,
            "previous_attempt": from_attempt,
            "previous_task_id": descriptor["task_id"],
            "previous_descriptor_sha256": prior_sha,
            "restart_mode": mode,
            "restart_audit": audit,
        }
        temporary = private / f".{target}-{attempt}-{uuid4().hex}.tmp"
        _write_new(temporary, updated)
        os.replace(temporary, path)
        return updated


def workspace_factory(settings, problem: dict, qualification_sha256: str):
    """Bind the public provider selector to exact target and observed report digest."""
    policy = WorkspacePolicy(
        template_id=IMAGE,
        environment_digest=problem["environment_digest"],
        qualification_report_sha256=qualification_sha256,
        timeout_seconds=7200,
        cost_bound_usd="0",
        cost_source="local_no_external_invoice",
    )
    configured = settings.model_copy(
        update={
            "worker_workspace": policy,
            "worker_workspace_provider": "local_docker",
            "worker_docker_host": DOCKER_HOST,
            "worker_image_digest": IMAGE,
            "worker_workspace_quota_bytes": 256 * 1024 * 1024,
        }
    )
    return configured_workspace_factory(configured)


def status(service, actor, descriptor: dict) -> dict:
    """Allowlisted metadata only. Content and native checkpoints never leave private storage."""
    experiment, task, _ = _scope(service, actor, descriptor)
    eid = experiment["id"]
    records = {
        kind: service.list_records(kind, actor, eid)
        for kind in (
            "session",
            "task",
            "claim",
            "verification",
            "workspace",
            "workspace_operation",
            "artifact",
        )
    }
    counts = {kind: len(rows) for kind, rows in records.items()}
    ledger = service.ledger(eid, actor)
    accepted = _exact_verified(service, actor, experiment, records["verification"])
    receipts = [
        {
            "id": r["id"],
            "status": _safe_label(r.get("status")),
            "assurance": _safe_label(r.get("assurance")),
            "code": _safe_label(r.get("code")),
            "artifact_id": r.get("artifact_id"),
            "exact_target_accepted": r["id"] in accepted,
        }
        for r in records["verification"]
    ]
    event_counts = {}
    tool_counts = {}
    handoff_reasons = {}
    for artifact in records["artifact"]:
        if artifact.get("artifact_kind") != "runtime_event":
            continue
        raw = service.artifact_content(artifact["id"], actor)
        if len(raw) > 1_000_000:
            raise PilotError("EVENT_TOO_LARGE")
        event = json.loads(raw)
        kind = event.get("kind")
        if kind == "tool_completed":
            name = event.get("payload", {}).get("name")
            if isinstance(name, str) and SAFE_CODE.fullmatch(name):
                tool_counts[name] = tool_counts.get(name, 0) + 1
        if kind in {
            "generation_started",
            "usage",
            "provider_compaction_items",
            "compaction",
            "stagnation_warning",
            "recovery_requested",
            "recovery_exhausted",
        }:
            event_counts[kind] = event_counts.get(kind, 0) + 1
            if kind == "provider_compaction_items":
                event_counts["provider_compaction_item_count"] = event_counts.get(
                    "provider_compaction_item_count", 0
                ) + max(0, int(event.get("payload", {}).get("count", 0)))
    handoffs = _handoff_events(service, actor, {row["id"] for row in records["task"]})
    for handoff in handoffs:
        reason = handoff.get("reason")
        if reason not in {"joined_children", "stagnation_recovery", "automatic_context_boundary"}:
            reason = "other"
        handoff_reasons[reason] = handoff_reasons.get(reason, 0) + 1
    operation_kinds = ("provision", "run", "upload", "read_range", "export", "restore", "destroy")
    current_modes = {"native": 0, "portable": 0}
    for row in records["task"]:
        mode = (row.get("consumed_continuation") or {}).get("continuation_mode")
        if mode in current_modes:
            current_modes[mode] += 1
    return {
        "target": descriptor["target"],
        "attempt": descriptor["attempt"],
        "experiment_id": eid,
        "execution_status": _safe_label(experiment["status"]),
        "task_status": _safe_label(task["status"]),
        "proof_status": "verified_exact_target" if accepted else "unverified",
        "submitted_claim_count": len(records["claim"]),
        "exact_verified_receipt_count": len(accepted),
        "receipts": receipts,
        "ledger": ledger,
        "model_cost": {
            "source": "recorded_operator_prices_estimate",
            "spent_usd": ledger.get("spent_cost_usd"),
            "reserved_usd": ledger.get("reserved_cost_usd"),
            "uncertain_operations": ledger.get("uncertain_operations"),
        },
        "counts": counts,
        "handoffs": len(handoffs),
        "handoff_reasons": handoff_reasons,
        "joined_handoffs": handoff_reasons.get("joined_children", 0),
        "non_join_handoffs": len(handoffs) - handoff_reasons.get("joined_children", 0),
        "latest_consumed_continuation_modes": current_modes,
        "historical_continuation_mode_count_unknown": max(
            0, len(handoffs) - sum(current_modes.values())
        ),
        "delegated_tasks": sum(bool(t.get("delegated_from_task_id")) for t in records["task"]),
        "workspace_statuses": [_safe_label(w.get("status")) for w in records["workspace"]],
        "tool_usage": {
            "runtime_tool_calls": sum(tool_counts.values()),
            "runtime_by_name": tool_counts,
            "workspace_operations": len(records["workspace_operation"]),
            "by_kind": {
                k: sum(o.get("command") == k for o in records["workspace_operation"])
                for k in operation_kinds
            },
        },
        "generations": event_counts.get("generation_started", 0),
        "provider_compaction_items": event_counts.get("provider_compaction_item_count", 0),
        "pruning_boundaries": event_counts.get("compaction", 0),
        "terminal_read_stagnation_warnings": event_counts.get("stagnation_warning", 0),
        "recovery_requests": event_counts.get("recovery_requested", 0),
        "recovery_exhausted": event_counts.get("recovery_exhausted", 0),
    }


async def run(
    service, actor, descriptor: dict, *, prices: dict, environment: dict, factory
) -> dict:
    experiment, task, _ = _scope(service, actor, descriptor)
    eid = experiment["id"]
    if task["status"] in TERMINAL or experiment["status"] in TERMINAL:
        return {"status": "already_terminal", "experiment_id": eid, "task_status": task["status"]}
    if task["status"] == "running" and not task.get("ready_continuation"):
        raise PilotError("ATTEMPT_ACTIVE")
    if any(s.get("task_id") == task["id"] for s in service.list_records("session", actor, eid)):
        if not task.get("ready_continuation"):
            raise PilotError("RECOVERY_RECONCILIATION_REQUIRED")
    if service.ledger(eid, actor).get("uncertain_operations"):
        raise PilotError("UNCERTAIN_OPERATION_RECONCILIATION_REQUIRED")
    allocations = _campaign_allocations(service, actor, experiment["campaign_id"])
    if (
        any(len(rows) > 1 for rows in allocations.values())
        or sum(len(rows) for rows in allocations.values()) > 2
        or sum(
            Decimal(str(row["budget"]["max_cost_usd"]))
            for rows in allocations.values()
            for row in rows
        )
        > 50
    ):
        raise PilotError("CAMPAIGN_ALLOCATION_EXHAUSTED")
    preflight = run_preflight(
        service, actor, eid, prices=prices, environment=environment, workbench_factory=factory
    )
    if preflight["status"] != "ready_for_live_attempt":
        return {
            "status": "blocked",
            "codes": [b["code"] for b in preflight["blockers"]],
            "experiment_id": eid,
        }
    if experiment["status"] == "created":
        experiment = service.transition_experiment(
            eid,
            "start",
            experiment["revision"],
            actor,
            f"research-effectiveness:{descriptor['target']}:{descriptor['attempt']}:start",
        )
    elif experiment["status"] in {"paused", "blocked"}:
        experiment = service.transition_experiment(
            eid,
            "resume",
            experiment["revision"],
            actor,
            f"research-effectiveness:{descriptor['target']}:{descriptor['attempt']}:resume",
        )
    result = await ResearchTeamRunner(
        service, executor=ResearchTaskExecutor(service, prices=prices, workspace_factory=factory)
    ).run(
        TeamRunManifest(
            experiment_id=eid,
            project_id=actor.project_id,
            mode="live",
            task_ids=[task["id"]],
            include_delegated=True,
            max_concurrency=1,
            max_tasks=128,
            timeout_seconds=7200,
            max_verifications=128,
            run_id=f"research-effectiveness:{descriptor['target']}:{descriptor['attempt']}:run",
        )
    )
    return {
        "status": result["status"],
        "stop_reason": result.get("stop_reason"),
        "experiment_id": eid,
        "report_artifact_id": result.get("artifact_id"),
        "attempted_tasks": result.get("attempted_tasks"),
        "ledger": result.get("ledger"),
    }


def export(service, actor, descriptor: dict, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise PilotError("EXPORT_EXISTS")
    output.mkdir(parents=True, mode=0o700)
    os.chmod(output, 0o700)
    result = historical().export_attempt(service, actor, descriptor, output / "manifest.json")
    manifest = json.loads((output / "manifest.json").read_text())
    for artifact in manifest["records"]["artifact"]:
        path = output / artifact["sha256"]
        if path.exists():
            continue
        content = service.artifact_content(artifact["id"], actor)
        if isinstance(content, str):
            content = content.encode()
        if hashlib.sha256(content).hexdigest() != artifact["sha256"]:
            raise PilotError("ARTIFACT_HASH_MISMATCH")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
    validation = validate_export(output)
    return {
        "experiment_id": result["experiment_id"],
        "manifest_sha256": result["manifest_sha256"],
        "integrity": validation["status"],
        "unique_artifacts_checked": validation["unique_artifacts_checked"],
    }


def result_exit_code(command: str, result: dict) -> int:
    return 1 if command == "run" and result.get("status") == "blocked" else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("dry-prepare", "retry-preflight", "retry-settled", "status", "run", "export"),
    )
    parser.add_argument("target", choices=TARGETS)
    parser.add_argument("--attempt", required=False)
    parser.add_argument("--from-attempt", required=False)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--private", type=Path, default=PRIVATE)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--qualification-report", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "dry-prepare":
            if not args.attempt:
                raise PilotError("ATTEMPT_REQUIRED")
            result = prepare(args.private, args.source, args.project_id, args.target, args.attempt)
        elif args.command in {"retry-preflight", "retry-settled"}:
            if not args.attempt or not args.from_attempt:
                raise PilotError("ATTEMPT_REQUIRED")
            result = retry_preflight(
                args.private,
                args.project_id,
                args.target,
                args.from_attempt,
                args.attempt,
                settled=args.command == "retry-settled",
            )
        else:
            descriptor = _read_descriptor(args.private, args.target)
            if descriptor["project_id"] != args.project_id:
                raise PilotError("PROJECT_SCOPE")
            if args.command == "run":
                from physharness.bootstrap import build_service
                from physharness.config import Settings

                settings = Settings(
                    database_url=f"sqlite:///{args.private / 'harness.db'}",
                    artifact_root=args.private / "artifacts",
                    auto_create_schema=False,
                )
                token = os.environ.get("PHYSHARNESS_TOKEN")
                actor = settings.auth_tokens.get(token or "")
                if (
                    actor is None
                    or actor.role not in {"operator", "admin"}
                    or actor.project_id != args.project_id
                ):
                    raise PilotError("OPERATOR_AUTH_REQUIRED")
                service = build_service(settings)
                _, _, problem = _scope(service, actor, descriptor)
                if (
                    not args.qualification_report
                    or not args.qualification_report.is_file()
                    or args.qualification_report.is_symlink()
                ):
                    raise PilotError("QUALIFICATION_REPORT_REQUIRED")
                qualification_sha256 = hashlib.sha256(
                    args.qualification_report.read_bytes()
                ).hexdigest()
                factory = workspace_factory(settings, problem, qualification_sha256)
                prices = {
                    "gpt-6-sol": ModelPrice.model_validate(
                        settings.model_prices["gpt-6-sol"]
                    ).model_dump(mode="json")
                }
                with _lock(args.private, blocking=False), _mounted_tmp():
                    result = asyncio.run(
                        run(
                            service,
                            actor,
                            descriptor,
                            prices=prices,
                            environment={"OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY"))},
                            factory=factory,
                        )
                    )
            else:
                service, actor = _service(args.private), _actor(args.project_id)
                if args.command == "status":
                    result = status(service, actor, descriptor)
                else:
                    if not args.output:
                        raise PilotError("OUTPUT_REQUIRED")
                    with _lock(args.private):
                        result = export(service, actor, descriptor, args.output)
        print(json.dumps(result, sort_keys=True, default=str))
        return result_exit_code(args.command, result)
    except Exception as error:
        raw = (
            str(error)
            if isinstance(error, PilotError)
            else error.code
            if isinstance(error, HarnessError)
            else None
        )
        code = raw if isinstance(raw, str) and SAFE_CODE.fullmatch(raw) else "UNEXPECTED_ERROR"
        diagnostic = {
            "status": "error",
            "phase": args.command.upper(),
            "code": code,
            "type": type(error).__name__,
        }
        if args.private.is_dir() and not args.private.is_symlink():
            path = args.private / f"operator-error-{uuid4().hex}.log"
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(diagnostic, sort_keys=True) + "\n")
                stream.writelines(traceback.format_tb(error.__traceback__, limit=30))
            diagnostic["private_log"] = str(path)
        print(json.dumps(diagnostic), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
