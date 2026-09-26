"""Isolated retry preparation and admission for the reviewed hardening target.

This operator module never changes the original manifests or source freezes. Its
preparation commands have no model credential. Launch is explicit, one-shot, and
requires fresh source amendment, retirement, ledger, and target checks.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import sys
import traceback
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from physharness.bootstrap import build_service
from physharness.config import Settings
from physharness.continuation_lineage import validate_terminal_lineage
from physharness.domain import digest_json
from physharness.execution.types import ExecutionError, RuntimeCheckpoint
from physharness.execution.workspace_archive import checked_path
from physharness.reproduction import validate_export
from physharness.verification.boundary import Environment, safe_read
from physharness.verification.preparation import prepare_environment
from physharness.verification.qualification import DeploymentScope, capture_scope

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
import pilot_launch  # noqa: E402
import pilot_prepare  # noqa: E402
import pilot_runner  # noqa: E402

HISTORICAL_SPEND = Decimal("43.762893")
NEW_CEILING = Decimal("52")
RETRY_STATE = ROOT / ".state/hardening-final-2026-09-24-retry-1"
OLD_STATE = ROOT / ".state/hardening-final-2026-09-24"
OLD_MANIFEST = OLD_STATE / "manifest-cooperative.json"
OLD_FREEZE = OLD_STATE / "source-freeze-cooperative.json"
RETRY_MANIFEST = RETRY_STATE / "manifest-retry.json"
SOURCE_FREEZE = RETRY_STATE / "source-freeze-retry.json"
LAUNCH_FREEZE = RETRY_STATE / "launch-freeze-retry.json"
AMENDMENT = RETRY_STATE / "source-amendment.json"
AMENDMENT_DECISION = RETRY_STATE / "source-amendment-decision.json"
RETIREMENT_REVIEW = RETRY_STATE / "retirement-review.json"
RETIREMENT_DECISION = RETRY_STATE / "retirement-decision.json"
RETRY_MODULE = "work/hardening-final-2026-09-24/pilot_retry.py"
RETRY_TEST = "tests/test_hardening_retry.py"
SCIENTIFIC_FIELDS = (
    "title",
    "program",
    "informal_statement",
    "formal_statement",
    "assumptions",
    "definitions",
    "source",
    "environment_digest",
    "target_theorem",
    "definition_holes",
)


class RetryError(ValueError):
    pass


def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RetryError("SOURCE_MISSING")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def amount(value) -> Decimal:
    try:
        number = Decimal(value)
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise RetryError("AGGREGATE_BUDGET") from exc
    if not number.is_finite() or number < 0:
        raise RetryError("AGGREGATE_BUDGET")
    return number


def remaining_ceiling(spends: list[Decimal]) -> Decimal:
    settled = sum((amount(value) for value in spends), Decimal(0))
    remaining = NEW_CEILING - settled
    if remaining <= 0 or HISTORICAL_SPEND + settled + remaining > Decimal("100"):
        raise RetryError("AGGREGATE_BUDGET")
    return remaining


def scientific_payload(problem: dict) -> dict:
    """ProblemCreate fields unaffected by fresh campaign/revision identity."""
    return {field: problem[field] for field in SCIENTIFIC_FIELDS}


def _old_problem(original: dict) -> dict:
    prior = original["attempts"][-1]
    settings, actor = pilot_runner.operator_settings(original, prior)
    service = build_service(settings)
    experiment = service.get_record("experiment", prior["experiment_id"], actor)
    return service.get_record("problem", experiment["problem_id"], actor)


def _new_problem(attempt: dict, problem_id: str) -> dict:
    private = Path(attempt["private_directory"])
    settings = Settings(
        _env_prefix="HARDENING_RETRY_PREP_CONFIG_ONLY_",
        mode="local",
        database_url=attempt["database_url"],
        artifact_root=Path(attempt["artifact_root"]),
        auth_file=private / "auth.json",
        auto_create_schema=False,
    )
    token = (private / "researcher.token").read_text().strip()
    actor = settings.auth_tokens[token]
    return build_service(settings).get_record("problem", problem_id, actor)


def source_map(old_files: dict[str, str]) -> dict[str, str]:
    """Re-hash every old frozen input and discover new source in its source domains."""
    names = set(old_files)
    names.update(str(path.relative_to(ROOT)) for path in (ROOT / "src").rglob("*.py"))
    names.update(str(path.relative_to(ROOT)) for path in (ROOT / "infra").glob("*.py"))
    names.update((RETRY_MODULE, RETRY_TEST))
    output = {}
    for name in sorted(names):
        path = ROOT / name
        if path.exists() or path.is_symlink():
            output[name] = digest(path)
    return output


def source_delta(old: dict[str, str], current: dict[str, str]) -> dict:
    return {
        "changed": {
            path: {"before": old[path], "after": current[path]}
            for path in sorted(old.keys() & current.keys())
            if old[path] != current[path]
        },
        "added": {path: current[path] for path in sorted(current.keys() - old.keys())},
        "deleted": {path: old[path] for path in sorted(old.keys() - current.keys())},
    }


def check_source_amendment(
    old: dict[str, str], current: dict[str, str], amendment: dict, old_freeze_sha: str
) -> None:
    expected = {
        "protocol": "hardening-retry-amendment-v1",
        "old_freeze_sha256": old_freeze_sha,
        **source_delta(old, current),
    }
    if amendment != expected:
        raise RetryError("SOURCE_AMENDMENT")


def checked_source() -> dict:
    original = json.loads(OLD_FREEZE.read_text())
    if original.get("protocol") != "hardening-source-freeze-v1":
        raise RetryError("OLD_FREEZE")
    current = source_map(original["files"])
    amendment = json.loads(AMENDMENT.read_text())
    check_source_amendment(original["files"], current, amendment, digest(OLD_FREEZE))
    decision = json.loads(AMENDMENT_DECISION.read_text())
    if decision != {
        "decision": "approve_exact_retry_source_amendment",
        "amendment_sha256": digest(AMENDMENT),
    }:
        raise RetryError("SOURCE_AMENDMENT_REVIEW")
    return {
        "protocol": "hardening-retry-source-freeze-v1",
        "old_freeze_sha256": digest(OLD_FREEZE),
        "amendment_sha256": digest(AMENDMENT),
        "files": current,
    }


def check_predispatch_call(source: dict) -> None:
    """Prove only the local argument validator would reject an undispatched run."""
    if (
        source.get("tool_name") != "run_command"
        or source.get("pending_operation") != f"{source.get('session_id')}:{source.get('call_id')}"
        or not isinstance(source.get("arguments"), dict)
    ):
        raise RetryError("ABANDONED_CALL")
    cwd = source["arguments"].get("cwd")
    if cwd in {".", "/opt/sources/physlib", "/opt/sources/mathlib"}:
        raise RetryError("ABANDONED_CALL")
    try:
        checked_path(cwd)
    except ExecutionError as exc:
        if exc.code == "UNSAFE_PATH":
            return
    raise RetryError("ABANDONED_CALL")


def _canonical_records(service, actor, experiment_id: str) -> dict:
    return {
        kind: service.list_records(kind, actor, experiment_id)
        for kind in (
            "task",
            "session",
            "continuation_link",
            "artifact",
            "verification",
            "workspace",
            "workspace_operation",
        )
    }


def _check_abandoned_run(item: dict, records: dict, service, actor, experiment_id: str) -> None:
    task = next((x for x in records["task"] if x["id"] == item.get("task_id")), None)
    session = next((x for x in records["session"] if x["id"] == item.get("session_id")), None)
    workspace = next((x for x in records["workspace"] if x["id"] == item.get("workspace_id")), None)
    if (
        task is None
        or task["status"] != "blocked"
        or session is None
        or session["task_id"] != task["id"]
        or session["status"] != "uncertain"
        or workspace is None
        or workspace["task_id"] != task["id"]
        or workspace["status"] != "destroyed"
        or workspace.get("destruction_confirmed") is not True
        or session.get("checkpoint_artifact_id") != item.get("checkpoint_artifact_id")
        or any(x["task_id"] == task["id"] for x in records["continuation_link"])
        or len([x for x in records["session"] if x["task_id"] == task["id"]]) != 1
    ):
        raise RetryError("ABANDONED_CALL")
    artifact = service.get_record("artifact", item["checkpoint_artifact_id"], actor)
    raw = service.artifact_content(item["checkpoint_artifact_id"], actor)
    if (
        artifact.get("artifact_kind") != "native_checkpoint"
        or artifact.get("experiment_id") != experiment_id
        or (artifact.get("provenance") or {}).get("task_id") != task["id"]
        or (artifact.get("provenance") or {}).get("session_id") != session.get("native_record_id")
        or artifact.get("sha256") != hashlib.sha256(raw).hexdigest()
        or artifact.get("sha256") != item.get("checkpoint_sha256")
    ):
        raise RetryError("ABANDONED_CALL")
    checkpoint = RuntimeCheckpoint.model_validate_json(raw)
    checkpoint.verify()
    state = checkpoint.native_state
    calls = [
        call
        for response in state.get("responses", [])[-1:]
        for call in response.get("output", [])
        if call.get("type") == "function_call"
    ]
    if len(calls) != 1:
        raise RetryError("ABANDONED_CALL")
    call = calls[0]
    arguments = json.loads(call["arguments"])
    observed = {
        "session_id": checkpoint.session.id,
        "pending_operation": state.get("pending_operation"),
        "call_id": call.get("call_id"),
        "tool_name": call.get("name"),
        "arguments": arguments,
    }
    if (
        checkpoint.session.id != session.get("native_record_id")
        or checkpoint.session.status != session.get("status")
        or state.get("settled_boundary") is not False
        or state.get("terminal_response_pending")
        or observed != item.get("call")
        or any(
            op.get("workspace_id") == workspace["id"]
            and op.get("status") == "reconciliation_required"
            for op in records["workspace_operation"]
        )
    ):
        raise RetryError("ABANDONED_CALL")
    check_predispatch_call(observed)


def _check_abandoned_read(item: dict, records: dict, service, actor, experiment_id: str) -> None:
    task = next((x for x in records["task"] if x["id"] == item.get("task_id")), None)
    session = next((x for x in records["session"] if x["id"] == item.get("session_id")), None)
    workspace = next((x for x in records["workspace"] if x["id"] == item.get("workspace_id")), None)
    operation = next(
        (x for x in records["workspace_operation"] if x["id"] == item.get("operation_id")), None
    )
    if (
        task is None
        or task["status"] != "failed"
        or task.get("error_code") != "WORKSPACE_RECOVERY_ABORTED"
        or session is None
        or session["task_id"] != task["id"]
        or session["status"] != "completed"
        or workspace is None
        or workspace["task_id"] != task["id"]
        or workspace["status"] != "destroyed"
        or workspace.get("destruction_confirmed") is not True
        or operation is None
        or operation.get("workspace_id") != workspace["id"]
        or operation.get("task_id") != task["id"]
        or operation.get("command") != "read_range"
        or operation.get("status") != "failed"
        or operation.get("inputs") != item.get("operation_inputs")
        or (operation.get("result") or {}).get("code") != "WORKSPACE_OPERATOR_RETIRED"
        or (operation.get("result") or {}).get("evidence_artifact_id")
        != workspace.get("destruction_evidence_artifact_id")
        or session.get("checkpoint_artifact_id") != item.get("checkpoint_artifact_id")
        or any(x["task_id"] == task["id"] for x in records["continuation_link"])
        or len([x for x in records["session"] if x["task_id"] == task["id"]]) != 1
    ):
        raise RetryError("ABANDONED_READ")
    artifact = service.get_record("artifact", item["checkpoint_artifact_id"], actor)
    raw = service.artifact_content(item["checkpoint_artifact_id"], actor)
    if (
        artifact.get("artifact_kind") != "native_checkpoint"
        or artifact.get("experiment_id") != experiment_id
        or (artifact.get("provenance") or {}).get("task_id") != task["id"]
        or (artifact.get("provenance") or {}).get("session_id") != session.get("native_record_id")
        or artifact.get("sha256") != hashlib.sha256(raw).hexdigest()
        or artifact.get("sha256") != item.get("checkpoint_sha256")
    ):
        raise RetryError("ABANDONED_READ")
    checkpoint = RuntimeCheckpoint.model_validate_json(raw)
    checkpoint.verify()
    if (
        checkpoint.session.id != session.get("native_record_id")
        or checkpoint.session.status != session.get("status")
        or checkpoint.native_state.get("pending_operation") is not None
        or checkpoint.native_state.get("settled_boundary") is not True
    ):
        raise RetryError("ABANDONED_READ")
    call_source = item.get("call") or {}
    responses = checkpoint.native_state.get("responses", [])
    index = call_source.get("response_index")
    if type(index) is not int or not 0 <= index < len(responses):
        raise RetryError("ABANDONED_READ")
    response = responses[index]
    calls = [
        entry
        for entry in response.get("output", [])
        if entry.get("type") == "function_call"
        and entry.get("call_id") == call_source.get("call_id")
    ]
    if len(calls) != 1 or response.get("id") != call_source.get("response_id"):
        raise RetryError("ABANDONED_READ")
    call = calls[0]
    arguments = json.loads(call["arguments"])
    tool_operation = f"{checkpoint.session.id}:{call['call_id']}"
    broker_id = str(
        uuid5(
            NAMESPACE_URL,
            digest_json([actor.project_id, task["id"], workspace["id"], tool_operation]),
        )
    )
    tool_result = checkpoint.native_state.get("tool_results", {}).get(tool_operation, {})
    if (
        call.get("name") != "read_workspace_file"
        or arguments != {key: operation["inputs"][key] for key in ("path", "offset", "length")}
        or broker_id != operation["id"]
        or (tool_result.get("result") or {}).get("error", {}).get("code")
        != "WORKSPACE_RECONCILIATION_REQUIRED"
    ):
        raise RetryError("ABANDONED_READ")
    try:
        checked_path(operation["inputs"]["path"])
    except ExecutionError as exc:
        if exc.code == "UNSAFE_PATH":
            return
    raise RetryError("ABANDONED_READ")


def _check_vm_absence(observation: dict, original: dict, records: dict) -> None:
    if (
        observation.get("protocol") != "hardening-container-absence-v1"
        or observation.get("docker_host") != original["docker_host"]
        or observation.get("all_containers_absent") is not True
        or not isinstance(observation.get("observed_at"), str)
        or not isinstance(observation.get("workspaces"), list)
    ):
        raise RetryError("VM_ABSENCE_EVIDENCE")
    try:
        when = datetime.fromisoformat(observation["observed_at"])
    except ValueError as exc:
        raise RetryError("VM_ABSENCE_EVIDENCE") from exc
    if when.tzinfo is None:
        raise RetryError("VM_ABSENCE_EVIDENCE")
    expected = sorted(
        (
            {
                "workspace_id": workspace["id"],
                "execution_id": workspace["execution_id"],
                "container_absent": True,
            }
            for workspace in records["workspace"]
        ),
        key=lambda item: item["workspace_id"],
    )
    actual = sorted(observation["workspaces"], key=lambda item: item.get("workspace_id", ""))
    if actual != expected:
        raise RetryError("VM_ABSENCE_EVIDENCE")


def _prior_attempt_spend(
    original: dict, attempt: dict, review: dict | None, observation: dict | None = None
) -> Decimal:
    settings, actor = pilot_runner.operator_settings(original, attempt)
    service = build_service(settings)
    identifier = attempt["experiment_id"]
    experiment = service.get_record("experiment", identifier, actor)
    ledger = service.ledger(identifier, actor)
    records = _canonical_records(service, actor, identifier)
    problem = service.get_record("problem", experiment["problem_id"], actor)
    if (
        experiment["status"] not in {"paused", "cancelled"}
        or experiment.get("budget_reconciliation_required")
        or ledger["uncertain_operations"]
        or ledger["active_workers"]
        or amount(ledger["reserved_cost_usd"])
        or ledger["tokens_reserved"]
        or any(x["status"] in {"queued", "running", "pending"} for x in records["verification"])
        or any(
            x["status"] != "destroyed"
            or x.get("destruction_confirmed") is not True
            or x.get("active_operation_id") is not None
            or x.get("billing_status") != "reconciled"
            for x in records["workspace"]
        )
        or any(
            x["status"] in {"queued", "running", "reconciliation_required"}
            for x in records["workspace_operation"]
        )
    ):
        raise RetryError("PRIOR_NOT_DRAINED")
    if review is None:
        return pilot_runner._drained_attempt(attempt, service, actor, require_export=True)
    if observation is None:
        raise RetryError("VM_ABSENCE_EVIDENCE")
    _check_vm_absence(observation, original, records)
    if review.get("experiment_id") != identifier or experiment["status"] != "cancelled":
        raise RetryError("RETIREMENT_REVIEW")
    abandoned = review.get("abandoned", [])
    if (
        not isinstance(abandoned, list)
        or len(abandoned) != 2
        or {x.get("kind") for x in abandoned} != {"predispatch_run", "predispatch_read_range"}
        or len({x.get("task_id") for x in abandoned}) != 2
    ):
        raise RetryError("RETIREMENT_REVIEW")
    for item in abandoned:
        if item["kind"] == "predispatch_run":
            _check_abandoned_run(item, records, service, actor, identifier)
        else:
            _check_abandoned_read(item, records, service, actor, identifier)
    excluded = {x["task_id"] for x in abandoned}
    uncertain_run_id = next(x["task_id"] for x in abandoned if x["kind"] == "predispatch_run")
    if {x["id"] for x in records["task"] if x["status"] == "blocked"} != {uncertain_run_id}:
        raise RetryError("RETIREMENT_REVIEW")
    tasks = [x for x in records["task"] if x["id"] not in excluded]
    sessions = [x for x in records["session"] if x["task_id"] not in excluded]
    links = [x for x in records["continuation_link"] if x["task_id"] not in excluded]
    artifacts = {x["id"]: x for x in records["artifact"]}
    if any(
        x["status"] not in {"completed", "failed", "cancelled"} for x in tasks
    ) or not validate_terminal_lineage(
        tasks,
        sessions,
        links,
        artifacts,
        lambda artifact_id: service.artifact_content(artifact_id, actor),
        identifier,
        {
            "target_digest": experiment["target_digest"],
            "review_id": problem.get("review_id"),
            "environment_digest": problem["environment_digest"],
        },
    ):
        raise RetryError("PRIOR_NOT_DRAINED")
    export = Path(attempt["private_directory"]) / "export"
    if not export.is_dir():
        raise RetryError("PRIOR_EXPORT_REQUIRED")
    try:
        validate_export(export)
    except Exception as exc:
        raise RetryError("PRIOR_EXPORT_INVALID") from exc
    return amount(ledger["spent_cost_usd"])


def audit_prior() -> tuple[dict, Decimal]:
    original = pilot_runner.load_manifest(OLD_MANIFEST)
    review = json.loads(RETIREMENT_REVIEW.read_text())
    decision = json.loads(RETIREMENT_DECISION.read_text())
    observation = Path(review.get("operator_observation_file", ""))
    if (
        review.get("protocol") != "hardening-retry-retirement-v1"
        or review.get("original_manifest_sha256") != digest(OLD_MANIFEST)
        or review.get("original_freeze_sha256") != digest(OLD_FREEZE)
        or review.get("experiment_id") != original["attempts"][-1]["experiment_id"]
        or decision
        != {
            "decision": "approve_exact_failed_attempt_retirement_for_retry",
            "retirement_review_sha256": digest(RETIREMENT_REVIEW),
        }
        or not observation.is_absolute()
        or not observation.resolve().is_relative_to(ROOT)
        or review.get("operator_observation_sha256") != digest(observation)
    ):
        raise RetryError("RETIREMENT_REVIEW")
    attempts = [*original["attempts"], *original["retired_attempts"]]
    observation_data = json.loads(observation.read_text())
    observed = observation_data.get("workspaces", [])
    if not isinstance(observed, list) or len(
        {entry.get("workspace_id") for entry in observed}
    ) != len(observed):
        raise RetryError("VM_ABSENCE_EVIDENCE")
    spends = [
        _prior_attempt_spend(
            original,
            attempt,
            review if attempt["experiment_id"] == review["experiment_id"] else None,
            observation_data,
        )
        for attempt in attempts
    ]
    return original, remaining_ceiling(spends)


def _exact_target(spec: dict, original: dict) -> tuple[bytes, bytes]:
    for key in (
        "challenge_sha256",
        "worker_image_digest",
        "verifier_image_digest",
        "docker_host",
    ):
        if spec.get(key) != original[key]:
            raise RetryError("TARGET_DRIFT")
    challenge_path = Path(spec["challenge_file"])
    if challenge_path.resolve() != Path(original["challenge_file"]).resolve():
        raise RetryError("TARGET_DRIFT")
    challenge = safe_read(challenge_path.parent, challenge_path.name)
    if hashlib.sha256(challenge).hexdigest() != original["challenge_sha256"]:
        raise RetryError("TARGET_DRIFT")
    environment = prepare_environment(
        Path(spec["image_metadata_path"]),
        image_metadata_sha256=spec["image_metadata_sha256"],
        project_directory=Path(spec["project_directory"]),
        project_files=spec["project_files"],
    )
    parsed = Environment.model_validate_json(environment)
    if (
        hashlib.sha256(environment).hexdigest() != original["environment_digest"]
        or parsed.image != original["verifier_image_digest"]
    ):
        raise RetryError("TARGET_DRIFT")
    return challenge, environment


def _source_qualification(path: Path, scope_sha: str, image: str) -> None:
    qualification = json.loads(path.read_text())
    scope = json.loads((path.parent / "scope.json").read_text())
    reviewed = DeploymentScope.model_validate(scope)
    if (
        qualification.get("mechanical_status") != "satisfied"
        or qualification.get("production_qualified") is not False
        or qualification.get("scope_sha256") != scope_sha
        or qualification.get("scope") != scope
        or reviewed.sha256 != scope_sha
        or reviewed.image_digest != image
    ):
        raise RetryError("SOURCE_QUALIFICATION")
    try:
        current = capture_scope(
            ROOT,
            image_metadata=reviewed.image_metadata,
            runtime_identity=reviewed.runtime_identity,
            resource_profile=reviewed.resource_profile_file,
        )
    except Exception as exc:
        raise RetryError("SOURCE_QUALIFICATION") from exc
    if current.model_dump(mode="json") != reviewed.model_dump(mode="json"):
        raise RetryError("SOURCE_QUALIFICATION")


def load_retry_manifest() -> dict:
    value = json.loads(RETRY_MANIFEST.read_text())
    original = pilot_runner.load_manifest(OLD_MANIFEST)
    if (
        value.get("protocol") != "hardening-retry-manifest-v1"
        or value.get("phase") != "cooperative"
        or value.get("old_manifest_sha256") != digest(OLD_MANIFEST)
        or value.get("old_freeze_sha256") != digest(OLD_FREEZE)
        or value.get("retirement_review_sha256") != digest(RETIREMENT_REVIEW)
        or value.get("retirement_decision_sha256") != digest(RETIREMENT_DECISION)
        or value.get("amendment_sha256") != digest(AMENDMENT)
        or value.get("prior_spent_usd") != "43.762893"
        or value.get("new_reservation_ceiling_usd") != "52"
        or value.get("aggregate_ceiling_usd") != "100"
    ):
        raise RetryError("RETRY_MANIFEST")
    for key in (
        "challenge_sha256",
        "challenge_file",
        "environment_digest",
        "worker_image_digest",
        "verifier_image_digest",
        "docker_host",
        "model_prices_file",
        "worker_qualification_file",
    ):
        if value.get(key) != original[key]:
            raise RetryError("TARGET_DRIFT")
    attempt = value.get("attempt")
    if not isinstance(attempt, dict) or set(attempt) != set(original["attempts"][-1]):
        raise RetryError("RETRY_MANIFEST")
    private = RETRY_STATE / "attempts" / "hardening-cooperative-retry-1"
    if (
        attempt["label"] != private.name
        or attempt["phase"] != "cooperative"
        or attempt["sharing"] != "ideas"
        or attempt["project_id"] != private.name
        or Path(attempt["private_directory"]).resolve() != private
        or attempt["database_url"] != f"sqlite:///{private / 'harness.db'}"
        or Path(attempt["artifact_root"]).resolve() != private / "artifacts"
        or Path(attempt["status_file"]).resolve() != private / "status.json"
        or Path(attempt["result_file"]).resolve() != private / "result.json"
        or any(
            attempt[key] in {x[key] for x in [*original["attempts"], *original["retired_attempts"]]}
            for key in ("label", "project_id", "experiment_id", "database_url", "artifact_root")
        )
        or amount(attempt["ceiling_usd"]) <= 0
        or amount(attempt["ceiling_usd"]) > NEW_CEILING
        or Path(value["tmp_directory"]).resolve() != RETRY_STATE / "tmp"
        or Path(value["registry"]).resolve() != RETRY_STATE / "registry-retry.json"
        or Path(value["deployment_decision_file"]).resolve()
        != RETRY_STATE / "deployment-decision-retry.json"
        or Path(value["global_lock_file"]).resolve() != Path(original["global_lock_file"]).resolve()
    ):
        raise RetryError("RUN_ISOLATION")
    _source_qualification(
        Path(value["source_qualification_file"]),
        value["source_scope_sha256"],
        value["verifier_image_digest"],
    )
    record = json.loads((RETRY_STATE / "prepared-retry.json").read_text())
    new_problem = _new_problem(attempt, record["problem_revision_id"])
    if (
        scientific_payload(new_problem) != scientific_payload(_old_problem(original))
        or new_problem["target_digest"] != attempt["target_digest"]
        or new_problem["target_digest"] != record["target_digest"]
        or new_problem.get("semantic_review") != "approved"
        or not new_problem.get("review_id")
    ):
        raise RetryError("TARGET_DRIFT")
    return value


def prepare(spec_path: Path, qualification_path: Path) -> dict:
    checked_source()
    original, ceiling = audit_prior()
    if RETRY_MANIFEST.exists():
        raise RetryError("RETRY_ALREADY_PREPARED")
    spec = json.loads(spec_path.read_text())
    challenge, environment = _exact_target(spec, original)
    qualification = json.loads(qualification_path.read_text())
    scope_sha = qualification["scope_sha256"]
    _source_qualification(qualification_path, scope_sha, original["verifier_image_digest"])
    state = RETRY_STATE
    private = state / "attempts" / "hardening-cooperative-retry-1"
    attempt = {
        "label": private.name,
        "phase": "cooperative",
        "sharing": "ideas",
        "ceiling_usd": format(ceiling, "f"),
        "experiment_id": "pending",
        "project_id": private.name,
        "target_digest": "pending",
        "private_directory": str(private),
        "database_url": f"sqlite:///{private / 'harness.db'}",
        "artifact_root": str(private / "artifacts"),
        "status_file": str(private / "status.json"),
        "result_file": str(private / "result.json"),
    }
    record = pilot_prepare._prepare_attempt(
        attempt, spec["target"], environment, challenge, Path(spec["project_directory"])
    )
    new_problem = _new_problem(attempt, record["problem_revision_id"])
    if (
        scientific_payload(new_problem) != scientific_payload(_old_problem(original))
        or record["target_digest"] != new_problem["target_digest"]
        or record["challenge_sha256"] != original["challenge_sha256"]
        or record["environment_digest"] != original["environment_digest"]
        or record["model_calls"] != 0
    ):
        raise RetryError("TARGET_DRIFT")
    attempt["experiment_id"] = record["experiment_id"]
    attempt["target_digest"] = record["target_digest"]
    (state / "tmp").mkdir(exist_ok=True, mode=0o700)
    manifest = {
        "protocol": "hardening-retry-manifest-v1",
        "phase": "cooperative",
        "old_manifest_sha256": digest(OLD_MANIFEST),
        "old_freeze_sha256": digest(OLD_FREEZE),
        "retirement_review_sha256": digest(RETIREMENT_REVIEW),
        "retirement_decision_sha256": digest(RETIREMENT_DECISION),
        "amendment_sha256": digest(AMENDMENT),
        "spec_sha256": digest(spec_path),
        "prior_spent_usd": "43.762893",
        "new_reservation_ceiling_usd": "52",
        "aggregate_ceiling_usd": "100",
        "challenge_sha256": original["challenge_sha256"],
        "challenge_file": original["challenge_file"],
        "environment_digest": original["environment_digest"],
        "worker_image_digest": original["worker_image_digest"],
        "verifier_image_digest": original["verifier_image_digest"],
        "docker_host": original["docker_host"],
        "tmp_directory": str(state / "tmp"),
        "registry": str(state / "registry-retry.json"),
        "model_prices_file": original["model_prices_file"],
        "worker_qualification_file": original["worker_qualification_file"],
        "source_qualification_file": str(qualification_path),
        "source_scope_sha256": scope_sha,
        "deployment_decision_file": str(state / "deployment-decision-retry.json"),
        "global_lock_file": original["global_lock_file"],
        "attempt": attempt,
    }
    pilot_prepare.write_private(RETRY_MANIFEST, json.dumps(manifest, separators=(",", ":")))
    pilot_prepare.write_private(
        state / "prepared-retry.json", json.dumps(record, separators=(",", ":"))
    )
    return {"status": "prepared_pending_review", "ceiling_usd": attempt["ceiling_usd"]}


def assemble_registry(qualification_path: Path, resource_profile: Path) -> dict:
    manifest = load_retry_manifest()
    record = json.loads((RETRY_STATE / "prepared-retry.json").read_text())
    return pilot_prepare.assemble_registry(
        {**manifest, "attempts": [manifest["attempt"]]},
        record,
        qualification_file=qualification_path,
        resource_profile=resource_profile,
    )


def _launch_file_map(manifest: dict) -> dict[str, str]:
    record = json.loads((RETRY_STATE / "prepared-retry.json").read_text())
    files = [
        RETRY_MANIFEST,
        RETIREMENT_REVIEW,
        RETIREMENT_DECISION,
        Path(json.loads(RETIREMENT_REVIEW.read_text())["operator_observation_file"]),
        AMENDMENT,
        AMENDMENT_DECISION,
        OLD_MANIFEST,
        OLD_FREEZE,
        RETRY_STATE / "prepared-retry.json",
        Path(manifest["registry"]),
        Path(manifest["deployment_decision_file"]),
        Path(manifest["challenge_file"]),
        Path(manifest["source_qualification_file"]),
        Path(manifest["worker_qualification_file"]),
        Path(manifest["model_prices_file"]),
    ]
    files.extend(path for path in Path(record["bundle_directory"]).rglob("*") if path.is_file())
    files.extend(
        path
        for path in Path(manifest["source_qualification_file"]).parent.rglob("*")
        if path.is_file()
    )
    return {str(path.resolve().relative_to(ROOT)): digest(path) for path in sorted(set(files))}


def check_freeze() -> dict:
    manifest = load_retry_manifest()
    source = checked_source()
    if json.loads(SOURCE_FREEZE.read_text()) != source:
        raise RetryError("SOURCE_FREEZE")
    launch = json.loads(LAUNCH_FREEZE.read_text())
    if launch != {
        "protocol": "hardening-retry-launch-freeze-v1",
        "source_freeze_sha256": digest(SOURCE_FREEZE),
        "files": _launch_file_map(manifest),
    }:
        raise RetryError("LAUNCH_FREEZE")
    return manifest


def freeze() -> dict:
    manifest = load_retry_manifest()
    source = checked_source()
    decision = json.loads(Path(manifest["deployment_decision_file"]).read_text())
    if (
        decision.get("decision") != "activate_for_authorized_private_pilot_only"
        or decision.get("registry_sha256") != digest(Path(manifest["registry"]))
        or decision.get("mechanical_status") != "satisfied"
        or decision.get("production_qualified") is not False
    ):
        raise RetryError("DEPLOYMENT_GATE")
    pilot_prepare.write_private(
        SOURCE_FREEZE, json.dumps(source, sort_keys=True, separators=(",", ":"))
    )
    launch = {
        "protocol": "hardening-retry-launch-freeze-v1",
        "source_freeze_sha256": digest(SOURCE_FREEZE),
        "files": _launch_file_map(manifest),
    }
    pilot_prepare.write_private(
        LAUNCH_FREEZE, json.dumps(launch, sort_keys=True, separators=(",", ":"))
    )
    return {
        "status": "frozen",
        "source_files": len(source["files"]),
        "launch_files": len(launch["files"]),
    }


def _runner_config(manifest: dict) -> dict:
    return {**manifest, "attempts": [manifest["attempt"]], "retired_attempts": []}


def _locked_admission(expected_manifest: dict) -> dict:
    """Repeat every mutable admission read after obtaining the global launch lock."""
    actual = check_freeze()
    if actual != expected_manifest:
        raise RetryError("MANIFEST_CHANGED")
    _, remaining = audit_prior()
    if amount(actual["attempt"]["ceiling_usd"]) != remaining:
        raise RetryError("AGGREGATE_BUDGET")
    return actual


def launch() -> None:
    manifest = check_freeze()
    _, remaining = audit_prior()
    attempt = manifest["attempt"]
    if amount(attempt["ceiling_usd"]) != remaining:
        raise RetryError("AGGREGATE_BUDGET")
    registry = Path(manifest["registry"])
    decision = json.loads(Path(manifest["deployment_decision_file"]).read_text())
    if decision.get("decision") != "activate_for_authorized_private_pilot_only" or decision.get(
        "registry_sha256"
    ) != digest(registry):
        raise RetryError("DEPLOYMENT_GATE")
    if os.environ.get("DOCKER_HOST") != manifest["docker_host"]:
        raise RetryError("DEDICATED_DOCKER_REQUIRED")
    if Path(os.environ.get("TMPDIR", "")).resolve() != Path(manifest["tmp_directory"]).resolve():
        raise RetryError("RUNTIME_ENVIRONMENT")
    private = Path(attempt["private_directory"])
    with ExitStack() as stack:
        global_lock = stack.enter_context(Path(manifest["global_lock_file"]).open("a+"))
        local_lock = stack.enter_context((private / "launcher.lock").open("a+"))
        try:
            fcntl.flock(global_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(local_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RetryError("LAUNCH_ALREADY_RUNNING") from exc
        manifest = _locked_admission(manifest)
        attempt = manifest["attempt"]
        if any(
            path.exists()
            for path in (
                private / "launch.claimed",
                Path(attempt["status_file"]),
                Path(attempt["result_file"]),
            )
        ):
            raise RetryError("PREVIOUS_ATTEMPT_STATE")
        settings, actor = pilot_runner.operator_settings(_runner_config(manifest), attempt)
        service = build_service(settings)
        pilot_runner.validate_attempt(_runner_config(manifest), attempt, service, actor)
        # Read the credential only after all source, lineage, budget and attempt gates.
        key = pilot_launch.KEY_FILE.read_text().strip()
        if not key:
            raise RetryError("OPERATOR_MODEL_CREDENTIAL")
        (private / "launch.claimed").open("x").close()
        pilot_runner.legacy.atomic_json(
            Path(attempt["status_file"]),
            {
                "stage": "claimed",
                "label": attempt["label"],
                "experiment_id": attempt["experiment_id"],
            },
        )
        os.environ["OPENAI_API_KEY"] = key
        try:
            log_fd = os.open(private / "launch.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(log_fd, "w") as log, redirect_stdout(log), redirect_stderr(log):
                asyncio.run(
                    pilot_runner.run_one(
                        _runner_config(manifest), attempt, service, actor, settings
                    )
                )
        except Exception as exc:
            with (private / "launcher-error.log").open("a") as stream:
                os.chmod(private / "launcher-error.log", 0o600)
                traceback.print_exception(exc, file=stream)
            pilot_runner.legacy.atomic_json(
                Path(attempt["status_file"]),
                {
                    "stage": "runner",
                    "status": "blocked",
                    "error_code": getattr(exc, "code", "UNEXPECTED_FAILURE"),
                },
            )
            raise RetryError(getattr(exc, "code", "UNEXPECTED_FAILURE")) from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("draft-amendment", "prepare", "assemble-registry", "freeze", "check", "launch"),
    )
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--qualification", type=Path)
    parser.add_argument("--resources", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "draft-amendment":
            old = json.loads(OLD_FREEZE.read_text())
            print(
                json.dumps(
                    {
                        "protocol": "hardening-retry-amendment-v1",
                        "old_freeze_sha256": digest(OLD_FREEZE),
                        **source_delta(old["files"], source_map(old["files"])),
                    },
                    sort_keys=True,
                )
            )
        elif args.command == "prepare":
            if args.spec is None or args.qualification is None:
                parser.error("prepare requires --spec and --qualification")
            print(json.dumps(prepare(args.spec, args.qualification), sort_keys=True))
        elif args.command == "assemble-registry":
            if args.qualification is None or args.resources is None:
                parser.error("assemble-registry requires --qualification and --resources")
            print(json.dumps(assemble_registry(args.qualification, args.resources), sort_keys=True))
        elif args.command == "freeze":
            print(json.dumps(freeze(), sort_keys=True))
        elif args.command == "check":
            manifest = check_freeze()
            _, remaining = audit_prior()
            if amount(manifest["attempt"]["ceiling_usd"]) != remaining:
                raise RetryError("AGGREGATE_BUDGET")
            print(json.dumps({"status": "matching", "ceiling_usd": str(remaining)}))
        else:
            launch()
        return 0
    except (RetryError, OSError, ValueError, KeyError) as exc:
        code = str(exc) if isinstance(exc, RetryError) else type(exc).__name__
        print(json.dumps({"status": "blocked", "code": code}), file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({"status": "blocked", "code": "UNEXPECTED_FAILURE"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
