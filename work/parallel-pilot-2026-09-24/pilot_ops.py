"""One-shot, operator-gated four-arm pilot launcher and read-only status viewer."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import traceback
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from physharness.bootstrap import build_service
from physharness.config import Settings
from physharness.domain import Principal
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
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".status-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, separators=(",", ":"), sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text())
    required = {
        "project_id",
        "private_directory",
        "database_url",
        "artifact_root",
        "registry",
        "model_prices_file",
        "worker_qualification_file",
        "docker_host",
        "worker_image_digest",
        "arms",
        "aggregate_ceiling_usd",
        "probe_envelope_usd",
        "arm_ceiling_usd",
        "status_file",
        "results_directory",
    }
    if not isinstance(config, dict) or set(config) != required:
        raise PilotFailure("CONFIG_SCHEMA", "configuration")
    arms = config["arms"]
    if (
        not isinstance(arms, list)
        or len(arms) != 4
        or any(not isinstance(a, dict) or set(a) != {"label", "experiment_id"} for a in arms)
        or len({a["experiment_id"] for a in arms}) != 4
        or len({a["label"] for a in arms}) != 4
    ):
        raise PilotFailure("FOUR_UNIQUE_ARMS_REQUIRED", "configuration")
    try:
        ceiling = Decimal(config["aggregate_ceiling_usd"])
        arm = Decimal(config["arm_ceiling_usd"])
        probe = Decimal(config["probe_envelope_usd"])
    except (ValueError, TypeError, InvalidOperation):
        raise PilotFailure("BUDGET_CONFIG_INVALID", "configuration") from None
    if (
        not all(value.is_finite() for value in (ceiling, arm, probe))
        or ceiling != 100
        or arm != Decimal("24.95")
        or probe != Decimal("0.20")
        or arm * 4 + probe > ceiling
    ):
        raise PilotFailure("AGGREGATE_CEILING", "configuration")
    return config


def validate_prices(settings: Settings) -> None:
    price = settings.model_prices.get("gpt-6-sol")
    try:
        input_rate = Decimal(price["input_usd_per_million"])
        output_rate = Decimal(price["output_usd_per_million"])
        source = price["source"]
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise PilotFailure("MODEL_PRICE_INVALID", "validation") from None
    if (
        not input_rate.is_finite()
        or input_rate < Decimal("2.50")
        or not output_rate.is_finite()
        or output_rate < Decimal("10")
        or not isinstance(source, str)
        or not source.strip()
    ):
        raise PilotFailure("MODEL_PRICE_INVALID", "validation")


def operator_settings(config: dict) -> tuple[Settings, Principal]:
    private = Path(config["private_directory"])
    token = (private / "operator.token").read_text().strip()
    settings = Settings(
        _env_prefix="PARALLEL_PILOT_CONFIG_ONLY_",
        mode="local",
        database_url=config["database_url"],
        artifact_root=Path(config["artifact_root"]),
        auth_file=private / "auth.json",
        auto_create_schema=False,
        verification_registry=Path(config["registry"]),
        model_prices=json.loads(Path(config["model_prices_file"]).read_text()),
        worker_workspace_provider="local_docker",
        worker_docker_host=config["docker_host"],
        worker_image_digest=config["worker_image_digest"],
        worker_max_active_workspaces=2,
    )
    actor = settings.auth_tokens.get(token)
    if actor is None or actor.role != "operator" or actor.project_id != config["project_id"]:
        raise PilotFailure("OPERATOR_IDENTITY_REQUIRED", "authentication")
    return settings, actor


def validate_arms(config: dict, service, actor: Principal) -> list[dict]:
    experiments = []
    pairs: dict[str, list[tuple[str, str]]] = {}
    for arm in config["arms"]:
        experiment = service.get_record("experiment", arm["experiment_id"], actor)
        problem = service.get_record("problem", experiment["problem_id"], actor)
        budget = experiment["budget"]
        limits = experiment.get("runtime_limits", {})
        models = experiment["models"]
        if (
            experiment["status"] != "created"
            or experiment.get("budget_reconciliation_required")
            or experiment.get("execution_profile") != "formal-research"
            or experiment.get("context_profile") != "research"
            or experiment["policy"] != "independent"
            or experiment["sharing"] not in {"none", "ideas"}
            or Decimal(budget["max_cost_usd"]) != Decimal("24.95")
            or budget["max_concurrency"] != 2
            or budget["max_runtime_seconds"] != 86400
            or budget.get("max_tokens") is not None
            or len(models) != 2
            or any(
                m["runtime"] != "responses"
                or m["model"] != "gpt-6-sol"
                or m["parameters"] != {"reasoning": {"effort": "high"}}
                for m in models
            )
            or limits.get("max_total_tokens", "missing") is not None
            or limits.get("max_context_tokens") != 256000
            or limits.get("max_output_tokens") != 64000
            or limits.get("max_turns") != 1000
            or limits.get("timeout_seconds") != 86400
        ):
            raise PilotFailure("ARM_CONTRACT_MISMATCH", "validation")
        pairs.setdefault(problem["program"], []).append(
            (experiment["problem_id"], experiment["sharing"])
        )
        expected_label = problem["program"] + (
            "-independent" if experiment["sharing"] == "none" else "-collaborating"
        )
        if arm["label"] != expected_label:
            raise PilotFailure("ARM_LABEL_MISMATCH", "validation")
        experiments.append({"label": arm["label"], "experiment": experiment, "problem": problem})
    if len(pairs) != 2 or any(
        len(items) != 2
        or len({p for p, _ in items}) != 1
        or {s for _, s in items} != {"none", "ideas"}
        for items in pairs.values()
    ):
        raise PilotFailure("ARM_PAIR_MISMATCH", "validation")
    return experiments


def snapshot(config: dict, service, actor: Principal, arm: dict, stage: str, **extra) -> dict:
    experiment_id = arm["experiment"]["id"]
    experiment = service.get_record("experiment", experiment_id, actor)
    tasks = service.list_records("task", actor, experiment_id)
    sessions = service.list_records("session", actor, experiment_id)
    receipts = service.list_records("verification", actor, experiment_id)
    messages = service.list_records("message", actor, experiment_id)
    return {
        "utc": utc(),
        "stage": stage,
        "current_arm": arm["label"],
        "experiment_id": experiment_id,
        "experiment_status": experiment["status"],
        "reconciliation_required": bool(experiment.get("budget_reconciliation_required")),
        "task_status_counts": {
            status: sum(t["status"] == status for t in tasks)
            for status in ("queued", "running", "completed", "blocked", "failed")
        },
        "session_status_counts": {
            status: sum(s["status"] == status for s in sessions)
            for status in ("created", "running", "completed", "failed")
        },
        "ledger": service.ledger(experiment_id, actor),
        "receipts": [
            {"id": r["id"], "status": r.get("status"), "assurance": r.get("assurance")}
            for r in receipts
        ],
        "message_count": len(messages),
        "delegation_count": sum(
            bool(t.get("delegated_from_task_id") or t.get("reply_to_parent_task_id"))
            for t in tasks
        ),
        **extra,
    }


async def run_one(
    config: dict,
    service,
    actor: Principal,
    arm: dict,
    factory,
    runner_type=ResearchTeamRunner,
    executor_type=ResearchTaskExecutor,
    activities_type=Activities,
) -> dict:
    path = Path(config["status_file"])
    experiment = arm["experiment"]
    experiment_id = experiment["id"]
    policy = WorkspacePolicy(
        template_id=config["worker_image_digest"],
        environment_digest=arm["problem"]["environment_digest"],
        qualification_report_sha256=hashlib.sha256(
            Path(config["worker_qualification_file"]).read_bytes()
        ).hexdigest(),
        timeout_seconds=86400,
        cost_bound_usd="0",
        cost_source="local_no_external_invoice",
    )
    settings = factory["settings"].model_copy(update={"worker_workspace": policy})
    workspace_factory = configured_workspace_factory(settings)
    report = run_preflight(
        service,
        actor,
        experiment_id,
        prices=settings.model_prices,
        environment=os.environ,
        workbench_factory=workspace_factory,
        requested_concurrency=2,
    )
    if report["status"] != "ready_for_live_attempt":
        raise PilotFailure("PREFLIGHT_BLOCKED", "preflight")
    executor = executor_type(
        service, prices=settings.model_prices, workspace_factory=workspace_factory
    )
    service.transition_experiment(
        experiment_id,
        "start",
        experiment["revision"],
        actor,
        f"parallel-pilot-start:{experiment_id}",
    )
    service.configure_workforce(
        experiment_id,
        ConfigureWorkforceRequest(
            max_total_tasks=128, max_pending_tasks=128, synthesis_interval_posts=0
        ),
        actor,
        f"parallel-pilot-workforce:{experiment_id}",
    )
    seeded = activities_type(service, executor).apply_experiment_command(
        {
            "project_id": actor.project_id,
            "aggregate_id": experiment_id,
            "kind": "experiment.queued",
        }
    )
    if not seeded.get("task_ids"):
        raise PilotFailure("SEED_FAILED", "seeding")
    atomic_json(path, snapshot(config, service, actor, arm, "running"))

    async def heartbeat():
        while True:
            await asyncio.sleep(10)
            atomic_json(path, snapshot(config, service, actor, arm, "running"))

    monitor = asyncio.create_task(heartbeat())
    try:
        result = await runner_type(service, executor=executor).run(
            TeamRunManifest(
                experiment_id=experiment_id,
                project_id=actor.project_id,
                mode="live",
                task_ids=seeded["task_ids"],
                max_concurrency=2,
                max_tasks=128,
                max_verifications=128,
                timeout_seconds=86400,
            )
        )
    finally:
        monitor.cancel()
        try:
            await monitor
        except asyncio.CancelledError:
            pass
    atomic_json(Path(config["results_directory"]) / f"{arm['label']}.json", result)
    current = snapshot(config, service, actor, arm, "completed", result_status=result.get("status"))
    atomic_json(path, current)
    if result.get("status") != "completed" or current["ledger"]["uncertain_operations"]:
        raise PilotFailure("ARM_NOT_COMPLETED", "supervisor")
    return result


def launch(config: dict, service, actor: Principal, settings: Settings, *, run_arm=run_one) -> None:
    private = Path(config["private_directory"])
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (private / "launcher.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PilotFailure("LAUNCH_ALREADY_RUNNING", "gate") from None
        arms = validate_arms(config, service, actor)
        validate_prices(settings)
        if any((Path(config["results_directory"]) / f"{a['label']}.json").exists() for a in arms):
            raise PilotFailure("PREVIOUS_RESULT_EXISTS", "gate")
        for arm in arms:
            asyncio.run(run_arm(config, service, actor, arm, {"settings": settings}))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("launch", "status"))
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    config = None
    try:
        config = load_config(args.config)
        if args.command == "status":
            print(Path(config["status_file"]).read_text())
            return 0
        settings, actor = operator_settings(config)
        launch(config, build_service(settings), actor, settings)
        return 0
    except Exception as error:
        code = (
            error.code if isinstance(error, (PilotFailure, HarnessError)) else "UNEXPECTED_FAILURE"
        )
        stage = error.stage if isinstance(error, PilotFailure) else "launch"
        if config is not None and args.command == "launch":
            atomic_json(
                Path(config["status_file"]),
                {
                    "utc": utc(),
                    "stage": stage,
                    "status": "blocked",
                    "error_code": code,
                },
            )
            private = Path(config["private_directory"])
            private.mkdir(parents=True, exist_ok=True, mode=0o700)
            with (private / "launcher-error.log").open("a") as stream:
                os.chmod(private / "launcher-error.log", 0o600)
                stream.write(f"{utc()} {stage} {code}\n")
                traceback.print_exception(error, file=stream)
        print(
            json.dumps({"status": "blocked", "stage": stage, "error_code": code}), file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
