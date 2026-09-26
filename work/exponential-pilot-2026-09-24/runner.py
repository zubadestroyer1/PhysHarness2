"""One-attempt operator launcher for the private exponential-decay pilot.

Preparation, credentials, target review, verifier qualification, and VM lifecycle
are separate operator gates. This module never creates those authorities.
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
from collections import Counter
from contextlib import ExitStack
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from operator_handoffs import HandoffAuditError, terminal_sessions

from physharness.bootstrap import build_service
from physharness.config import Settings
from physharness.errors import HarnessError
from physharness.orchestration.research_worker import (
    ResearchTaskExecutor,
    ResearchTeamRunner,
    TeamRunManifest,
)
from physharness.orchestration.workspace_selection import configured_workspace_factory
from physharness.orchestration.workspace_tools import WorkspacePolicy
from physharness.run_control import run_preflight
from physharness.worker import Activities
from physharness.workforce_models import ConfigureWorkforceRequest


class PilotFailure(Exception):
    def __init__(self, code: str, stage: str):
        self.code, self.stage = code, stage
        super().__init__(f"{stage}: {code}")


def utc() -> str:
    return datetime.now(UTC).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    from tempfile import mkstemp

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = mkstemp(prefix=".pilot-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def amount(value) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise PilotFailure("BUDGET_SCHEDULE", "configuration") from None
    if not parsed.is_finite() or parsed < 0:
        raise PilotFailure("BUDGET_SCHEDULE", "configuration")
    return parsed


def load_manifest(path: Path) -> dict:
    value = json.loads(path.read_text())
    required = {
        "version",
        "prior_spent_usd",
        "aggregate_ceiling_usd",
        "new_reservation_ceiling_usd",
        "challenge_sha256",
        "challenge_file",
        "environment_digest",
        "worker_image_digest",
        "verifier_image_digest",
        "docker_host",
        "tmp_directory",
        "registry",
        "model_prices_file",
        "worker_qualification_file",
        "calibration_decision_file",
        "global_lock_file",
        "deployment_decision_file",
        "attempts",
    }
    attempt_fields = {
        "label",
        "phase",
        "sharing",
        "ceiling_usd",
        "experiment_id",
        "project_id",
        "target_digest",
        "private_directory",
        "database_url",
        "artifact_root",
        "status_file",
        "result_file",
    }
    if (
        not isinstance(value, dict)
        or set(value) not in (required, required | {"retired_attempts"})
        or value["version"] != 1
    ):
        raise PilotFailure("MANIFEST_SCHEMA", "configuration")
    attempts = value["attempts"]
    retired = value.setdefault("retired_attempts", [])
    if (
        not isinstance(attempts, list)
        or len(attempts) != 7
        or any(not isinstance(a, dict) or set(a) != attempt_fields for a in attempts)
        or not isinstance(retired, list)
        or any(not isinstance(a, dict) or set(a) != attempt_fields for a in retired)
    ):
        raise PilotFailure("MANIFEST_SCHEMA", "configuration")
    if (
        amount(value["prior_spent_usd"]) != Decimal("3.658018")
        or amount(value["aggregate_ceiling_usd"]) != 100
        or amount(value["new_reservation_ceiling_usd"]) != 92
        or sum((amount(a["ceiling_usd"]) for a in attempts), Decimal(0)) != 92
        or amount(value["prior_spent_usd"]) + amount(value["new_reservation_ceiling_usd"]) > 100
        or any(amount(a["ceiling_usd"]) != (12 if i < 3 else 14) for i, a in enumerate(attempts))
    ):
        raise PilotFailure("BUDGET_SCHEDULE", "configuration")
    if any(
        a["phase"] != ("calibration" if i < 3 else "comparison")
        or a["sharing"] != ("none" if i < 3 or i in (3, 6) else "ideas")
        for i, a in enumerate(attempts)
    ):
        raise PilotFailure("ARM_SCHEDULE", "configuration")
    for field in ("challenge_sha256", "environment_digest"):
        if (
            not isinstance(value[field], str)
            or len(value[field]) != 64
            or any(ch not in "0123456789abcdef" for ch in value[field])
        ):
            raise PilotFailure("TARGET_FREEZE", "configuration")
    if any(
        not isinstance(value[key], str)
        or len(value[key]) != 71
        or not value[key].startswith("sha256:")
        or any(ch not in "0123456789abcdef" for ch in value[key][7:])
        for key in ("worker_image_digest", "verifier_image_digest")
    ):
        raise PilotFailure("IMAGE_FREEZE", "configuration")
    if not isinstance(value["docker_host"], str) or not value["docker_host"].startswith("unix:///"):
        raise PilotFailure("DEDICATED_DOCKER_REQUIRED", "configuration")
    roots = []
    all_attempts = [*attempts, *retired]
    for attempt in all_attempts:
        digest = attempt["target_digest"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
        ):
            raise PilotFailure("TARGET_FREEZE", "configuration")
        private = Path(attempt["private_directory"])
        db_url = attempt["database_url"]
        if not private.is_absolute() or not db_url.startswith("sqlite:///"):
            raise PilotFailure("RUN_ISOLATION", "configuration")
        db = Path(db_url.removeprefix("sqlite:///"))
        children = [
            db,
            *(Path(attempt[key]) for key in ("artifact_root", "status_file", "result_file")),
        ]
        if not all(
            child.is_absolute() and child.resolve().is_relative_to(private.resolve())
            for child in children
        ):
            raise PilotFailure("RUN_ISOLATION", "configuration")
        roots.append(private.resolve())
    if (
        len(set(roots)) != len(all_attempts)
        or any(
            left.is_relative_to(right) or right.is_relative_to(left)
            for i, left in enumerate(roots)
            for right in roots[i + 1 :]
        )
        or any(
            len({a[key] for a in all_attempts}) != len(all_attempts)
            for key in (
                "label",
                "project_id",
                "experiment_id",
                "database_url",
                "artifact_root",
                "status_file",
                "result_file",
            )
        )
    ):
        raise PilotFailure("RUN_ISOLATION", "configuration")
    return value


def require_comparison_decision(config: dict) -> None:
    path = Path(config["calibration_decision_file"])
    try:
        decision = json.loads(path.read_text())
    except (OSError, ValueError):
        raise PilotFailure("CALIBRATION_GATE", "gate") from None
    if decision != {
        "decision": "continue",
        "challenge_sha256": config["challenge_sha256"],
        "environment_digest": config["environment_digest"],
    }:
        raise PilotFailure("CALIBRATION_GATE", "gate")


def operator_settings(config: dict, attempt: dict):
    private = Path(attempt["private_directory"])
    token = (private / "operator.token").read_text().strip()
    settings = Settings(
        _env_prefix="EXPONENTIAL_PILOT_CONFIG_ONLY_",
        mode="local",
        database_url=attempt["database_url"],
        artifact_root=Path(attempt["artifact_root"]),
        auth_file=private / "auth.json",
        auto_create_schema=False,
        verification_registry=Path(config["registry"]),
        model_prices=json.loads(Path(config["model_prices_file"]).read_text()),
        worker_workspace_provider="local_docker",
        worker_docker_host=config["docker_host"],
        worker_image_digest=config["worker_image_digest"],
        worker_max_active_workspaces=1 if attempt["phase"] == "calibration" else 2,
    )
    actor = settings.auth_tokens.get(token)
    if actor is None or actor.role != "operator" or actor.project_id != attempt["project_id"]:
        raise PilotFailure("OPERATOR_IDENTITY_REQUIRED", "authentication")
    price = settings.model_prices.get("gpt-6-sol", {})
    if (
        amount(price.get("input_usd_per_million")) < Decimal("2.50")
        or amount(price.get("output_usd_per_million")) < 10
        or not price.get("source")
    ):
        raise PilotFailure("MODEL_PRICE_INVALID", "configuration")
    return settings, actor


def validate_attempt(config: dict, attempt: dict, service, actor) -> dict:
    experiment = service.get_record("experiment", attempt["experiment_id"], actor)
    problem = service.get_record("problem", experiment["problem_id"], actor)
    count = 1 if attempt["phase"] == "calibration" else 2
    expected_model = {
        "runtime": "responses",
        "model": "gpt-6-sol",
        "parameters": {"reasoning": {"effort": "high"}},
    }
    budget = experiment["budget"]
    limits = experiment.get("runtime_limits", {})
    if (
        experiment["id"] != attempt["experiment_id"]
        or experiment["project_id"] != attempt["project_id"]
        or actor.project_id != attempt["project_id"]
        or experiment["status"] != "created"
        or experiment.get("budget_reconciliation_required")
        or experiment["problem_id"] != problem["id"]
        or experiment["target_digest"] != attempt["target_digest"]
        or problem["target_digest"] != attempt["target_digest"]
        or hashlib.sha256(problem["formal_statement"].encode()).hexdigest()
        != config["challenge_sha256"]
        or problem["environment_digest"] != config["environment_digest"]
        or experiment["execution_profile"] != "formal-research"
        or experiment["context_profile"] != "research"
        or experiment["policy"] != "independent"
        or experiment["sharing"] != attempt["sharing"]
        or amount(budget["max_cost_usd"]) != amount(attempt["ceiling_usd"])
        or budget["max_concurrency"] != count
        or budget["max_runtime_seconds"] != 2700
        or budget.get("max_tokens") is not None
        or limits.get("max_total_tokens", "missing") is not None
        or limits.get("max_context_tokens") != 256000
        or limits.get("max_output_tokens") != 64000
        or limits.get("max_turns") != 1000
        or limits.get("timeout_seconds") != 2700
        or experiment["models"] != [expected_model] * count
    ):
        raise PilotFailure("ATTEMPT_CONTRACT", "validation")
    return {"experiment": experiment, "problem": problem}


def status_snapshot(attempt: dict, service, actor, stage: str, **extra) -> dict:
    identifier = attempt["experiment_id"]
    experiment = service.get_record("experiment", identifier, actor)
    tasks = service.list_records("task", actor, identifier)
    sessions = service.list_records("session", actor, identifier)
    receipts = service.list_records("verification", actor, identifier)
    return {
        "utc": utc(),
        "stage": stage,
        "label": attempt["label"],
        "experiment_id": identifier,
        "experiment_status": experiment["status"],
        "reconciliation_required": bool(experiment.get("budget_reconciliation_required")),
        "task_status_counts": dict(Counter(item["status"] for item in tasks)),
        "session_status_counts": dict(Counter(item["status"] for item in sessions)),
        "receipts": [
            {"id": r["id"], "status": r.get("status"), "assurance": r.get("assurance")}
            for r in receipts
        ],
        "ledger": service.ledger(identifier, actor),
        **extra,
    }


def drained_sessions(service, actor, experiment_id, tasks, sessions):
    handed = any(session.get("status") == "handed_off" for session in sessions)
    links = service.list_records("continuation_link", actor, experiment_id) if handed else []
    scope = {}
    if links:
        experiment = service.get_record("experiment", experiment_id, actor)
        problem = service.get_record("problem", experiment["problem_id"], actor)
        scope = {
            "target_digest": experiment["target_digest"],
            "review_id": problem.get("review_id"),
            "environment_digest": problem["environment_digest"],
        }
    artifacts = (
        {
            artifact["id"]: artifact
            for artifact in service.list_records("artifact", actor, experiment_id)
        }
        if handed
        else {}
    )
    try:
        return terminal_sessions(
            tasks,
            sessions,
            artifacts,
            lambda artifact_id: service.artifact_content(artifact_id, actor),
            experiment_id,
            links=links,
            scope=scope,
        )
    except HandoffAuditError as exc:
        if str(exc) == "MULTIPLE_HANDOFFS_REVIEW_REQUIRED":
            raise PilotFailure(str(exc), "gate") from exc
        return False


def audit_sequence(config: dict, selected: dict, open_attempt) -> None:
    """Inspect all isolated ledgers before reserving the selected attempt's ceiling."""
    index = config["attempts"].index(selected)
    retired = config.get("retired_attempts", [])
    all_attempts = [*config["attempts"], *retired]
    if any(
        len({attempt[key] for attempt in all_attempts}) != len(all_attempts)
        for key in ("experiment_id", "database_url")
    ):
        raise PilotFailure("RUN_ISOLATION", "gate")
    spent = amount(config["prior_spent_usd"])
    reserved = Decimal(0)
    for attempt in retired:
        service, actor = open_attempt(attempt)
        identifier = attempt["experiment_id"]
        experiment = service.get_record("experiment", identifier, actor)
        ledger = service.ledger(identifier, actor)
        spent += amount(ledger["spent_cost_usd"])
        reserved += amount(ledger["reserved_cost_usd"])
        if ledger["uncertain_operations"] or experiment.get("budget_reconciliation_required"):
            raise PilotFailure("UNSETTLED_PRIOR_COST", "gate")
        if (
            experiment["status"] != "cancelled"
            or ledger["active_workers"]
            or amount(ledger["reserved_cost_usd"])
            or ledger["tokens_reserved"]
            or any(
                t["status"] not in {"completed", "failed", "cancelled"}
                for t in service.list_records("task", actor, identifier)
            )
            or not drained_sessions(
                service,
                actor,
                identifier,
                service.list_records("task", actor, identifier),
                service.list_records("session", actor, identifier),
            )
            or any(
                r["status"] in {"queued", "running", "pending"}
                for r in service.list_records("verification", actor, identifier)
            )
        ):
            raise PilotFailure("RETIRED_ATTEMPT_NOT_DRAINED", "gate")
    for position, attempt in enumerate(config["attempts"]):
        service, actor = open_attempt(attempt)
        experiment = service.get_record("experiment", attempt["experiment_id"], actor)
        ledger = service.ledger(attempt["experiment_id"], actor)
        spent += amount(ledger["spent_cost_usd"])
        reserved += amount(ledger["reserved_cost_usd"])
        if ledger["uncertain_operations"] or experiment.get("budget_reconciliation_required"):
            raise PilotFailure("UNSETTLED_PRIOR_COST", "gate")
        if position < index:
            if (
                experiment["status"] not in {"paused", "cancelled"}
                or ledger["active_workers"]
                or amount(ledger["reserved_cost_usd"])
                or ledger["tokens_reserved"]
                or any(
                    t["status"] not in {"completed", "failed", "cancelled"}
                    for t in service.list_records("task", actor, attempt["experiment_id"])
                )
                or not drained_sessions(
                    service,
                    actor,
                    attempt["experiment_id"],
                    service.list_records("task", actor, attempt["experiment_id"]),
                    service.list_records("session", actor, attempt["experiment_id"]),
                )
                or any(
                    r["status"] in {"queued", "running"}
                    for r in service.list_records("verification", actor, attempt["experiment_id"])
                )
                or not Path(attempt["result_file"]).is_file()
            ):
                raise PilotFailure("PRIOR_ATTEMPT_NOT_DRAINED", "gate")
            decision_path = Path(attempt["private_directory"]) / "advance-decision.json"
            try:
                decision = json.loads(decision_path.read_text())
            except (OSError, ValueError):
                raise PilotFailure("ADVANCE_REVIEW_REQUIRED", "gate") from None
            if decision != {"decision": "advance", "experiment_id": attempt["experiment_id"]}:
                raise PilotFailure("ADVANCE_REVIEW_REQUIRED", "gate")
        elif position > index and experiment["status"] != "created":
            raise PilotFailure("ATTEMPT_OUT_OF_ORDER", "gate")
    proposed = spent + reserved + amount(selected["ceiling_usd"])
    if proposed > amount(config["aggregate_ceiling_usd"]) or proposed - amount(
        config["prior_spent_usd"]
    ) > amount(config["new_reservation_ceiling_usd"]):
        raise PilotFailure("AGGREGATE_BUDGET", "gate")


async def run_one(
    config: dict,
    attempt: dict,
    service,
    actor,
    settings: Settings,
    *,
    runner_type=ResearchTeamRunner,
    executor_type=ResearchTaskExecutor,
    activities_type=Activities,
) -> dict:
    identifier = attempt["experiment_id"]
    selected = validate_attempt(config, attempt, service, actor)
    count = 1 if attempt["phase"] == "calibration" else 2
    max_tasks = 1 if count == 1 else 128
    policy = WorkspacePolicy(
        template_id=config["worker_image_digest"],
        environment_digest=config["environment_digest"],
        qualification_report_sha256=hashlib.sha256(
            Path(config["worker_qualification_file"]).read_bytes()
        ).hexdigest(),
        timeout_seconds=2700,
        cost_bound_usd="0",
        cost_source="local_no_external_invoice",
    )
    settings = settings.model_copy(update={"worker_workspace": policy})
    workspace_factory = configured_workspace_factory(settings)
    report = run_preflight(
        service,
        actor,
        identifier,
        prices=settings.model_prices,
        environment=os.environ,
        workbench_factory=workspace_factory,
        requested_concurrency=count,
    )
    if report["status"] != "ready_for_live_attempt":
        raise PilotFailure("PREFLIGHT_BLOCKED", "preflight")
    executor = executor_type(
        service, prices=settings.model_prices, workspace_factory=workspace_factory
    )
    service.transition_experiment(
        identifier,
        "start",
        selected["experiment"]["revision"],
        actor,
        f"exponential-pilot-start:{identifier}",
    )
    service.configure_workforce(
        identifier,
        ConfigureWorkforceRequest(
            max_total_tasks=max_tasks, max_pending_tasks=max_tasks, synthesis_interval_posts=0
        ),
        actor,
        f"exponential-pilot-workforce:{identifier}",
    )
    seeded = activities_type(service, executor).apply_experiment_command(
        {
            "project_id": actor.project_id,
            "aggregate_id": identifier,
            "kind": "experiment.queued",
        }
    )
    if len(seeded.get("task_ids", [])) != count:
        raise PilotFailure("SEED_COUNT_MISMATCH", "seeding")
    status_file = Path(attempt["status_file"])
    atomic_json(status_file, status_snapshot(attempt, service, actor, "running"))

    async def heartbeat():
        while True:
            await asyncio.sleep(10)
            atomic_json(status_file, status_snapshot(attempt, service, actor, "running"))

    monitor = asyncio.create_task(heartbeat())
    try:
        result = await runner_type(service, executor=executor).run(
            TeamRunManifest(
                experiment_id=identifier,
                project_id=actor.project_id,
                mode="live",
                task_ids=seeded["task_ids"],
                max_concurrency=count,
                max_tasks=max_tasks,
                max_verifications=128,
                timeout_seconds=2700,
            )
        )
    finally:
        monitor.cancel()
        try:
            await monitor
        except asyncio.CancelledError:
            pass
    atomic_json(Path(attempt["result_file"]), result)
    current = status_snapshot(
        attempt, service, actor, "completed", result_status=result.get("status")
    )
    atomic_json(status_file, current)
    if (
        result.get("status") != "completed"
        or current["ledger"]["uncertain_operations"]
        or current["reconciliation_required"]
    ):
        raise PilotFailure("ATTEMPT_NOT_COMPLETED", "supervisor")
    return result


def launch_one(config: dict, label: str) -> None:
    matches = [item for item in config["attempts"] if item["label"] == label]
    if len(matches) != 1:
        raise PilotFailure("UNKNOWN_ATTEMPT", "gate")
    attempt = matches[0]
    registry_path = Path(config["registry"])
    decision_path = Path(config["deployment_decision_file"])
    try:
        decision = json.loads(decision_path.read_text())
    except (OSError, ValueError):
        raise PilotFailure("DEPLOYMENT_GATE", "gate") from None
    if (
        not registry_path.is_file()
        or decision.get("decision") != "activate_for_authorized_private_pilot_only"
        or decision.get("registry_sha256") != hashlib.sha256(registry_path.read_bytes()).hexdigest()
        or decision.get("mechanical_status") != "satisfied"
        or decision.get("production_qualified") is not False
    ):
        raise PilotFailure("DEPLOYMENT_GATE", "gate")
    challenge = Path(config["challenge_file"])
    if (
        not challenge.is_file()
        or challenge.is_symlink()
        or hashlib.sha256(challenge.read_bytes()).hexdigest() != config["challenge_sha256"]
    ):
        raise PilotFailure("CHALLENGE_SOURCE_DRIFT", "gate")
    tmp = Path(config["tmp_directory"])
    if (
        not tmp.is_absolute()
        or not tmp.is_dir()
        or not tmp.resolve().is_relative_to(Path(__file__).resolve().parents[2] / ".state")
        or Path(os.environ.get("TMPDIR", "")).resolve() != tmp.resolve()
        or os.environ.get("DOCKER_HOST") != config["docker_host"]
    ):
        raise PilotFailure("RUNTIME_ENVIRONMENT", "gate")
    if attempt["phase"] == "comparison":
        require_comparison_decision(config)
    private = Path(attempt["private_directory"])
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    global_lock_path = Path(config["global_lock_file"])
    global_lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with ExitStack() as stack:
        global_lock = stack.enter_context(global_lock_path.open("a+"))
        lock = stack.enter_context((private / "launcher.lock").open("a+"))
        try:
            fcntl.flock(global_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PilotFailure("LAUNCH_ALREADY_RUNNING", "gate") from None
        if (
            Path(attempt["result_file"]).exists()
            or Path(attempt["status_file"]).exists()
            or (private / "launch.claimed").exists()
        ):
            raise PilotFailure("PREVIOUS_ATTEMPT_STATE", "gate")
        settings, actor = operator_settings(config, attempt)
        service = build_service(settings)
        validate_attempt(config, attempt, service, actor)

        def open_attempt(item):
            if item is attempt:
                return service, actor
            other_settings, other_actor = operator_settings(config, item)
            return build_service(other_settings), other_actor

        audit_sequence(config, attempt, open_attempt)
        (private / "launch.claimed").open("x").close()
        atomic_json(
            Path(attempt["status_file"]),
            {
                "utc": utc(),
                "stage": "claimed",
                "label": label,
                "experiment_id": attempt["experiment_id"],
            },
        )
        try:
            asyncio.run(run_one(config, attempt, service, actor, settings))
        except Exception as error:
            code = (
                error.code
                if isinstance(error, (PilotFailure, HarnessError))
                else "UNEXPECTED_FAILURE"
            )
            stage = error.stage if isinstance(error, PilotFailure) else "runner"
            with (private / "launcher-error.log").open("a") as stream:
                os.chmod(private / "launcher-error.log", 0o600)
                stream.write(f"{utc()} {stage} {code}\n")
                traceback.print_exception(error, file=stream)
            atomic_json(
                Path(attempt["status_file"]),
                {
                    "utc": utc(),
                    "stage": stage,
                    "status": "blocked",
                    "error_code": code,
                    "label": attempt["label"],
                    "experiment_id": attempt["experiment_id"],
                },
            )
            raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "status", "launch-one"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--label")
    args = parser.parse_args(argv)
    attempt = None
    try:
        config = load_manifest(args.manifest)
        if args.command == "inspect":
            print(
                json.dumps(
                    {
                        "status": "valid",
                        "attempts": [
                            {
                                "label": a["label"],
                                "phase": a["phase"],
                                "sharing": a["sharing"],
                                "ceiling_usd": a["ceiling_usd"],
                            }
                            for a in config["attempts"]
                        ],
                    }
                )
            )
            return 0
        matches = [a for a in config["attempts"] if a["label"] == args.label]
        if len(matches) != 1:
            raise PilotFailure("UNKNOWN_ATTEMPT", "configuration")
        attempt = matches[0]
        if args.command == "status":
            print(Path(attempt["status_file"]).read_text())
            return 0
        launch_one(config, args.label)
        return 0
    except Exception as error:
        code = (
            error.code if isinstance(error, (PilotFailure, HarnessError)) else "UNEXPECTED_FAILURE"
        )
        stage = error.stage if isinstance(error, PilotFailure) else "runner"
        print(
            json.dumps({"status": "blocked", "stage": stage, "error_code": code}), file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
