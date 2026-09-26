"""Operator-gated, one-attempt launcher for the harder private research pilot.

This module can inspect prepared inputs without credentials. `launch-one` is the
paid path and must be invoked only through the phase-specific source-freeze wrapper.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import importlib.util
import json
import os
import sys
import traceback
from contextlib import ExitStack
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from physharness.bootstrap import build_service
from physharness.config import Settings
from physharness.continuation_lineage import validate_terminal_lineage
from physharness.errors import HarnessError
from physharness.orchestration.research_worker import (
    ResearchTaskExecutor,
    ResearchTeamRunner,
    TeamRunManifest,
)
from physharness.orchestration.workspace_selection import configured_workspace_factory
from physharness.orchestration.workspace_tools import WorkspacePolicy
from physharness.reproduction import validate_export
from physharness.run_control import run_preflight
from physharness.workforce_models import (
    ConfigureWorkforceRequest,
    PortfolioRoot,
    SeedPortfolioRequest,
)

ROOT = Path(__file__).resolve().parents[2]
LEGACY_PATH = ROOT / "work/exponential-pilot-2026-09-24/runner.py"
sys.path.insert(0, str(LEGACY_PATH.parent))
_LEGACY_SPEC = importlib.util.spec_from_file_location("_hardening_prior_runner", LEGACY_PATH)
legacy = importlib.util.module_from_spec(_LEGACY_SPEC)
_LEGACY_SPEC.loader.exec_module(legacy)


class PilotFailure(Exception):
    def __init__(self, code: str, stage: str):
        self.code, self.stage = code, stage
        super().__init__(f"{stage}: {code}")


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
    state = path.resolve().parent
    keys = {
        "version",
        "pilot",
        "phase",
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
        "source_qualification_file",
        "source_scope_sha256",
        "deployment_decision_file",
        "global_lock_file",
        "attempts",
        "retired_attempts",
    }
    fields = {
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
        or set(value) != keys
        or value["version"] != 2
        or value["pilot"] != "hardening-final-2026-09-24"
        or value["phase"] not in {"calibration", "cooperative"}
        or path.name != f"manifest-{value['phase']}.json"
    ):
        raise PilotFailure("MANIFEST_SCHEMA", "configuration")
    attempts, retired = value["attempts"], value["retired_attempts"]
    if (
        not isinstance(attempts, list)
        or len(attempts) != (1 if value["phase"] == "calibration" else 2)
        or not isinstance(retired, list)
        or any(not isinstance(a, dict) or set(a) != fields for a in [*attempts, *retired])
        or attempts[-1]["phase"] != value["phase"]
        or attempts[-1]["sharing"] != ("none" if value["phase"] == "calibration" else "ideas")
        or (value["phase"] == "cooperative" and attempts[0]["phase"] != "calibration")
    ):
        raise PilotFailure("MANIFEST_SCHEMA", "configuration")
    if (
        amount(value["prior_spent_usd"]) != Decimal("43.762893")
        or amount(value["aggregate_ceiling_usd"]) != 100
        or amount(value["new_reservation_ceiling_usd"]) != 52
        or amount(attempts[0]["ceiling_usd"]) > 14
        or amount(attempts[-1]["ceiling_usd"]) <= 0
        or amount(attempts[-1]["ceiling_usd"]) > 52
        or amount(value["prior_spent_usd"]) + amount(value["new_reservation_ceiling_usd"]) > 100
    ):
        raise PilotFailure("BUDGET_SCHEDULE", "configuration")
    for attempt in [*attempts, *retired]:
        if attempt["phase"] not in {"calibration", "cooperative"} or attempt["sharing"] != (
            "none" if attempt["phase"] == "calibration" else "ideas"
        ):
            raise PilotFailure("ARM_SCHEDULE", "configuration")
        if amount(attempt["ceiling_usd"]) <= 0 or (
            attempt["phase"] == "calibration" and amount(attempt["ceiling_usd"]) > 14
        ):
            raise PilotFailure("BUDGET_SCHEDULE", "configuration")
    for name in ("challenge_sha256", "environment_digest", "source_scope_sha256"):
        if (
            not isinstance(value[name], str)
            or len(value[name]) != 64
            or any(ch not in "0123456789abcdef" for ch in value[name])
        ):
            raise PilotFailure("TARGET_FREEZE", "configuration")
    for name in ("worker_image_digest", "verifier_image_digest"):
        digest = value[name]
        if (
            not isinstance(digest, str)
            or not digest.startswith("sha256:")
            or len(digest) != 71
            or any(ch not in "0123456789abcdef" for ch in digest[7:])
        ):
            raise PilotFailure("IMAGE_FREEZE", "configuration")
    if not isinstance(value["docker_host"], str) or not value["docker_host"].startswith("unix:///"):
        raise PilotFailure("DEDICATED_DOCKER_REQUIRED", "configuration")
    if (
        Path(value["tmp_directory"]).resolve() != state / "tmp"
        or Path(value["registry"]).resolve() != state / f"registry-{value['phase']}.json"
        or Path(value["deployment_decision_file"]).resolve()
        != state / f"deployment-decision-{value['phase']}.json"
        or Path(value["global_lock_file"]).resolve() != state / "launcher.lock"
    ):
        raise PilotFailure("RUN_ISOLATION", "configuration")
    all_attempts = [*attempts, *retired]
    roots = []
    for attempt in all_attempts:
        private = Path(attempt["private_directory"])
        if (
            not private.is_absolute()
            or private.resolve().parent != state / "attempts"
            or private.name != attempt["label"]
            or attempt["project_id"] != attempt["label"]
            or not attempt["database_url"].startswith("sqlite:///")
        ):
            raise PilotFailure("RUN_ISOLATION", "configuration")
        children = [
            Path(attempt["database_url"].removeprefix("sqlite:///")),
            *(Path(attempt[key]) for key in ("artifact_root", "status_file", "result_file")),
        ]
        if not all(
            path.is_absolute() and path.resolve().is_relative_to(private.resolve())
            for path in children
        ):
            raise PilotFailure("RUN_ISOLATION", "configuration")
        roots.append(private.resolve())
        digest = attempt["target_digest"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
        ):
            raise PilotFailure("TARGET_FREEZE", "configuration")
    if (
        len(set(roots)) != len(roots)
        or any(
            left.is_relative_to(right) or right.is_relative_to(left)
            for i, left in enumerate(roots)
            for right in roots[i + 1 :]
        )
        or any(
            len({a[key] for a in all_attempts}) != len(all_attempts)
            for key in ("label", "project_id", "experiment_id", "database_url", "artifact_root")
        )
    ):
        raise PilotFailure("RUN_ISOLATION", "configuration")
    return value


def operator_settings(config: dict, attempt: dict):
    private = Path(attempt["private_directory"])
    token = (private / "operator.token").read_text().strip()
    settings = Settings(
        _env_prefix="HARDENING_PILOT_CONFIG_ONLY_",
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
        worker_max_active_workspaces=4 if attempt["phase"] == "cooperative" else 1,
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
    cooperative = attempt["phase"] == "cooperative"
    expected_model = {
        "runtime": "responses",
        "model": "gpt-6-sol",
        "parameters": {"reasoning": {"effort": "high"}},
    }
    budget, limits = experiment["budget"], experiment.get("runtime_limits", {})
    if (
        experiment["id"] != attempt["experiment_id"]
        or experiment["project_id"] != attempt["project_id"]
        or actor.project_id != attempt["project_id"]
        or experiment["status"] != "created"
        or experiment.get("budget_reconciliation_required")
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
        or budget["max_concurrency"] != (4 if cooperative else 1)
        or budget["max_runtime_seconds"] != 7200
        or budget.get("max_tokens") is not None
        or limits.get("max_total_tokens", "missing") is not None
        or limits.get("max_context_tokens") != 256000
        or limits.get("max_output_tokens") != 64000
        or limits.get("max_turns") != 1000
        or limits.get("timeout_seconds") != 7200
        or experiment["models"] != [expected_model] * (2 if cooperative else 1)
    ):
        raise PilotFailure("ATTEMPT_CONTRACT", "validation")
    return {"experiment": experiment, "problem": problem}


def _drained_attempt(attempt: dict, service, actor, *, require_export: bool) -> Decimal:
    identifier = attempt["experiment_id"]
    experiment = service.get_record("experiment", identifier, actor)
    ledger = service.ledger(identifier, actor)
    tasks = service.list_records("task", actor, identifier)
    sessions = service.list_records("session", actor, identifier)
    receipts = service.list_records("verification", actor, identifier)
    links = service.list_records("continuation_link", actor, identifier)
    artifacts = {
        artifact["id"]: artifact for artifact in service.list_records("artifact", actor, identifier)
    }
    problem = service.get_record("problem", experiment["problem_id"], actor)
    try:
        lineage_drained = validate_terminal_lineage(
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
        )
    except Exception as exc:
        raise PilotFailure("PRIOR_ATTEMPT_NOT_DRAINED", "gate") from exc
    if (
        experiment["status"] not in {"paused", "cancelled"}
        or experiment.get("budget_reconciliation_required")
        or ledger["uncertain_operations"]
        or ledger["active_workers"]
        or amount(ledger["reserved_cost_usd"])
        or ledger["tokens_reserved"]
        or not tasks
        or any(t["status"] not in {"completed", "failed", "cancelled"} for t in tasks)
        or any(r["status"] in {"queued", "running", "pending"} for r in receipts)
        or not lineage_drained
        or not Path(attempt["result_file"]).is_file()
    ):
        raise PilotFailure("PRIOR_ATTEMPT_NOT_DRAINED", "gate")
    if require_export:
        export = Path(attempt["private_directory"]) / "export"
        if not export.is_dir():
            raise PilotFailure("PRIOR_EXPORT_REQUIRED", "gate")
        try:
            validate_export(export)
        except Exception as exc:
            raise PilotFailure("PRIOR_EXPORT_INVALID", "gate") from exc
    return amount(ledger["spent_cost_usd"])


def settled_prior_spend(config: dict) -> Decimal:
    """Reopen every new pilot attempt; never infer a refund from a failed run."""
    spent = Decimal(0)
    for attempt in [*config["attempts"], *config["retired_attempts"]]:
        settings, actor = operator_settings(config, attempt)
        spent += _drained_attempt(attempt, build_service(settings), actor, require_export=True)
    if spent >= 52 or Decimal("43.762893") + spent > 100:
        raise PilotFailure("AGGREGATE_BUDGET", "gate")
    return spent


def root_seed_request(phase: str) -> SeedPortfolioRequest:
    if phase == "calibration":
        return SeedPortfolioRequest(
            roots=[
                PortfolioRoot(
                    title="Independent calibration",
                    objective="Investigate the reviewed target independently.",
                )
            ]
        )
    if phase != "cooperative":
        raise ValueError("unknown phase")
    return SeedPortfolioRequest(
        roots=[
            PortfolioRoot(
                title=f"Independent root {index}",
                objective=(
                    "Investigate the reviewed target; choose methods and collaborators freely."
                ),
                public_summary=f"Opted-in root researcher {index}; available for attributed ideas.",
            )
            for index in (1, 2)
        ]
    )


def audit_sequence(config: dict, selected: dict, open_attempt) -> None:
    try:
        legacy.audit_sequence(config, selected, open_attempt)
    except legacy.PilotFailure as exc:
        raise PilotFailure(exc.code, exc.stage) from exc
    if selected["phase"] == "cooperative":
        spent = sum(
            (
                _drained_attempt(item, *open_attempt(item), require_export=True)
                for item in config["attempts"][:-1]
            ),
            Decimal(0),
        )
        spent += sum(
            (
                _drained_attempt(item, *open_attempt(item), require_export=True)
                for item in config["retired_attempts"]
            ),
            Decimal(0),
        )
        if amount(selected["ceiling_usd"]) > Decimal("52") - spent:
            raise PilotFailure("AGGREGATE_BUDGET", "gate")


def utc() -> str:
    return datetime.now(UTC).isoformat()


def require_source_freeze(manifest_path: Path) -> None:
    import pilot_launch

    try:
        baseline = json.loads(pilot_launch.freeze_path(manifest_path).read_text())
        manifest = load_manifest(manifest_path)
        pilot_launch.check(
            ROOT,
            manifest_path,
            Path(manifest["source_qualification_file"]),
            baseline,
        )
    except (OSError, ValueError, KeyError, pilot_launch.FreezeError) as exc:
        raise PilotFailure("SOURCE_FREEZE", "gate") from exc


async def run_one(config: dict, attempt: dict, service, actor, settings: Settings) -> dict:
    selected = validate_attempt(config, attempt, service, actor)
    cooperative = attempt["phase"] == "cooperative"
    slots = 4 if cooperative else 1
    max_tasks = 128 if cooperative else 1
    policy = WorkspacePolicy(
        template_id=config["worker_image_digest"],
        environment_digest=config["environment_digest"],
        qualification_report_sha256=hashlib.sha256(
            Path(config["worker_qualification_file"]).read_bytes()
        ).hexdigest(),
        timeout_seconds=7200,
        cost_bound_usd="0",
        cost_source="local_no_external_invoice",
    )
    settings = settings.model_copy(update={"worker_workspace": policy})
    workspace_factory = configured_workspace_factory(settings)
    report = run_preflight(
        service,
        actor,
        attempt["experiment_id"],
        prices=settings.model_prices,
        environment=os.environ,
        workbench_factory=workspace_factory,
        requested_concurrency=slots,
    )
    if report["status"] != "ready_for_live_attempt":
        raise PilotFailure("PREFLIGHT_BLOCKED", "preflight")
    executor = ResearchTaskExecutor(
        service, prices=settings.model_prices, workspace_factory=workspace_factory
    )
    service.transition_experiment(
        attempt["experiment_id"],
        "start",
        selected["experiment"]["revision"],
        actor,
        f"hardening-start:{attempt['experiment_id']}",
    )
    service.configure_workforce(
        attempt["experiment_id"],
        ConfigureWorkforceRequest(
            max_total_tasks=max_tasks,
            max_pending_tasks=max_tasks,
            synthesis_interval_posts=0,
        ),
        actor,
        f"hardening-workforce:{attempt['experiment_id']}",
    )
    seeded = service.seed_portfolio(
        attempt["experiment_id"],
        root_seed_request(attempt["phase"]),
        actor,
        f"hardening-seed:{attempt['experiment_id']}",
    )
    roots = [item["task"]["id"] for item in seeded["roots"]]
    if len(roots) != (2 if cooperative else 1):
        raise PilotFailure("SEED_COUNT_MISMATCH", "seeding")
    status_file = Path(attempt["status_file"])
    legacy.atomic_json(status_file, legacy.status_snapshot(attempt, service, actor, "running"))

    async def heartbeat():
        while True:
            await asyncio.sleep(10)
            legacy.atomic_json(
                status_file, legacy.status_snapshot(attempt, service, actor, "running")
            )

    monitor = asyncio.create_task(heartbeat())
    try:
        result = await ResearchTeamRunner(service, executor=executor).run(
            TeamRunManifest(
                experiment_id=attempt["experiment_id"],
                project_id=actor.project_id,
                mode="live",
                task_ids=roots,
                max_concurrency=slots,
                max_tasks=max_tasks,
                max_verifications=128,
                timeout_seconds=7200,
            )
        )
    finally:
        monitor.cancel()
        try:
            await monitor
        except asyncio.CancelledError:
            pass
    legacy.atomic_json(Path(attempt["result_file"]), result)
    current = legacy.status_snapshot(
        attempt, service, actor, "completed", result_status=result.get("status")
    )
    legacy.atomic_json(status_file, current)
    if (
        result.get("status") != "completed"
        or current["ledger"]["uncertain_operations"]
        or current["reconciliation_required"]
    ):
        raise PilotFailure("ATTEMPT_NOT_COMPLETED", "supervisor")
    return result


def launch_one(config: dict, label: str, manifest_path: Path) -> None:
    selected = config["attempts"][-1]
    if selected["label"] != label:
        raise PilotFailure("UNKNOWN_ATTEMPT", "gate")
    registry_path = Path(config["registry"])
    try:
        decision = json.loads(Path(config["deployment_decision_file"]).read_text())
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
        or not tmp.resolve().is_relative_to(ROOT / ".state")
        or Path(os.environ.get("TMPDIR", "")).resolve() != tmp.resolve()
        or os.environ.get("DOCKER_HOST") != config["docker_host"]
    ):
        raise PilotFailure("RUNTIME_ENVIRONMENT", "gate")
    private = Path(selected["private_directory"])
    with ExitStack() as stack:
        global_lock_path = Path(config["global_lock_file"])
        global_lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        global_lock = stack.enter_context(global_lock_path.open("a+"))
        local_lock = stack.enter_context((private / "launcher.lock").open("a+"))
        try:
            fcntl.flock(global_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(local_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PilotFailure("LAUNCH_ALREADY_RUNNING", "gate") from None
        require_source_freeze(manifest_path)
        if config != load_manifest(manifest_path):
            raise PilotFailure("MANIFEST_CHANGED", "gate")
        if any(
            path.exists()
            for path in (
                Path(selected["status_file"]),
                Path(selected["result_file"]),
                private / "launch.claimed",
            )
        ):
            raise PilotFailure("PREVIOUS_ATTEMPT_STATE", "gate")
        settings, actor = operator_settings(config, selected)
        service = build_service(settings)
        validate_attempt(config, selected, service, actor)

        def open_attempt(item):
            if item is selected:
                return service, actor
            other_settings, other_actor = operator_settings(config, item)
            return build_service(other_settings), other_actor

        audit_sequence(config, selected, open_attempt)
        (private / "launch.claimed").open("x").close()
        legacy.atomic_json(
            Path(selected["status_file"]),
            {
                "utc": utc(),
                "stage": "claimed",
                "label": label,
                "experiment_id": selected["experiment_id"],
            },
        )
        try:
            asyncio.run(run_one(config, selected, service, actor, settings))
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
            legacy.atomic_json(
                Path(selected["status_file"]),
                {
                    "utc": utc(),
                    "stage": stage,
                    "status": "blocked",
                    "error_code": code,
                    "label": label,
                    "experiment_id": selected["experiment_id"],
                },
            )
            raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "status", "launch-one"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--label")
    args = parser.parse_args(argv)
    try:
        config = load_manifest(args.manifest)
        if args.command == "inspect":
            print(
                json.dumps(
                    {
                        "status": "valid",
                        "phase": config["phase"],
                        "current_label": config["attempts"][-1]["label"],
                        "ceiling_usd": config["attempts"][-1]["ceiling_usd"],
                    }
                )
            )
            return 0
        if args.label != config["attempts"][-1]["label"]:
            raise PilotFailure("UNKNOWN_ATTEMPT", "configuration")
        if args.command == "status":
            print(Path(config["attempts"][-1]["status_file"]).read_text())
            return 0
        require_source_freeze(args.manifest)
        launch_one(config, args.label, args.manifest)
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
