"""Operator CLI; secrets stay in protected local files and all failures exit nonzero."""

import json
import os
import secrets
from pathlib import Path
from typing import Annotated

import typer

from .client import HarnessClient
from .config import Settings
from .domain import Principal, canonical_json, new_id
from .errors import HarnessError

app = typer.Typer(no_args_is_help=True, help="PhysHarness private research laboratory")


def output(value):
    typer.echo(json.dumps(value, indent=2, default=str))


def fail(error):
    if isinstance(error, HarnessError):
        typer.echo(canonical_json(error.envelope()), err=True)
    else:
        typer.echo(f"ERROR {type(error).__name__}: {error}", err=True)
    raise typer.Exit(1)


def client():
    token = os.environ.get("PHYSHARNESS_TOKEN")
    if not token:
        raise HarnessError("TOKEN_REQUIRED", "Set PHYSHARNESS_TOKEN to an issued identity.")
    return HarnessClient(os.environ.get("PHYSHARNESS_URL", "http://127.0.0.1:8000"), token)


def local_authority(*roles):
    """Resolve a real configured identity; operator commands cannot invent principals."""
    from .bootstrap import build_service
    from .service import require_role

    settings = Settings()
    token = os.environ.get("PHYSHARNESS_TOKEN")
    actor = settings.auth_tokens.get(token or "")
    if actor is None:
        raise HarnessError("TOKEN_REQUIRED", "Supply a configured role-scoped identity token.")
    require_role(actor, *roles)
    return settings, build_service(settings), actor


@app.command("prepare-environment")
def prepare_environment_command(
    image_metadata: Path,
    image_metadata_sha256: Annotated[str, typer.Option(help="Inspected image metadata SHA-256.")],
    project_directory: Annotated[Path, typer.Option()],
    include: Annotated[
        list[str], typer.Option(help="Repeat for each trusted relative project file.")
    ],
    output_file: Annotated[Path, typer.Option()],
):
    """Pin a built image and trusted source files without creating a target or review."""
    import hashlib

    from .verification.preparation import prepare_environment

    try:
        data = prepare_environment(
            image_metadata,
            image_metadata_sha256=image_metadata_sha256,
            project_directory=project_directory,
            project_files=include,
        )
        with output_file.open("xb") as stream:
            stream.write(data)
        output(
            {
                "environment_file": str(output_file.resolve()),
                "environment_digest": hashlib.sha256(data).hexdigest(),
                "semantic_review": "not_performed",
                "qualification": "not_performed",
            }
        )
    except Exception as error:
        fail(error)


@app.command("bundle-target")
def bundle_target_command(
    problem_id: str,
    environment_file: Annotated[Path, typer.Option()],
    project_directory: Annotated[Path, typer.Option()],
    destination: Annotated[Path, typer.Option()],
):
    """Construct an immutable bundle from the canonical target and exact pinned environment."""
    from .run_control import read_input
    from .verification.preparation import create_problem_bundle

    try:
        _, service, actor = local_authority("operator")
        problem = service.get_record("problem", problem_id, actor)
        data = read_input(environment_file.parent, environment_file.name, 500000)
        manifest_hash = create_problem_bundle(
            destination,
            problem=problem,
            environment_bytes=data,
            project_directory=project_directory,
        )
        output(
            {
                "bundle_directory": str(destination.resolve()),
                "manifest_sha256": manifest_hash,
                "problem_revision_id": problem_id,
                "target_digest": problem["target_digest"],
                "semantic_review": problem["semantic_review"],
                "qualification": "not_performed",
            }
        )
    except Exception as error:
        fail(error)


@app.command("prepare-run")
def prepare_run_command(manifest: Path):
    """Create a proposed target and inactive experiment from a versioned local plan."""
    from pydantic import ValidationError

    from .run_control import RunPlan, prepare_run, read_input

    try:
        _, service, actor = local_authority("researcher", "operator")
        try:
            plan = RunPlan.model_validate_json(read_input(manifest.parent, manifest.name, 500000))
        except ValidationError:
            raise HarnessError(
                "RUN_PLAN_INVALID", "Invalid run plan; check the documented schema. Values omitted."
            ) from None
        output(prepare_run(service, actor, plan, manifest.parent))
    except Exception as error:
        fail(error)


@app.command("review-target")
def review_target_command(
    problem_id: str,
    target_digest: Annotated[str, typer.Option(help="Exact semantic target digest inspected.")],
    rationale_file: Annotated[Path, typer.Option(help="Written review rationale, UTF-8.")],
    idempotency_key: Annotated[str, typer.Option()],
    decision: str = "approved",
):
    """Record an explicit human decision using a separately issued reviewer identity."""
    from .run_control import read_input

    try:
        _, service, actor = local_authority("reviewer")
        problem = service.get_record("problem", problem_id, actor)
        if target_digest != problem["target_digest"]:
            raise HarnessError("REVIEW_TARGET_MISMATCH", "The inspected target digest differs.")
        rationale = read_input(rationale_file.parent, rationale_file.name, 100000).decode("utf-8")
        output(service.review_problem(problem_id, decision, rationale, actor, idempotency_key))
    except Exception as error:
        fail(error)


@app.command("check-run")
def check_run_command(
    experiment_id: str,
    publication: bool = True,
    concurrency: Annotated[int, typer.Option(min=1, max=100)] = 1,
):
    """Report all missing live inputs without allocation, model calls or candidate execution."""
    from .orchestration.workspace_selection import configured_workspace_factory
    from .run_control import run_preflight

    try:
        settings, service, actor = local_authority("operator")
        report = run_preflight(
            service,
            actor,
            experiment_id,
            prices=settings.model_prices,
            environment=os.environ,
            publication=publication,
            workbench_factory=configured_workspace_factory(settings),
            requested_concurrency=concurrency,
        )
    except Exception as error:
        fail(error)
    output(report)
    if report["status"] == "blocked":
        raise typer.Exit(1)


@app.command("run-team")
def run_team_command(
    experiment_id: str,
    max_tasks: Annotated[int, typer.Option(min=1, max=1000)] = 8,
    concurrency: Annotated[int, typer.Option(min=1, max=100)] = 1,
    timeout_seconds: Annotated[float, typer.Option(min=1, max=86400)] = 300,
):
    """Launch a finite live team on durable records after explicit operator preflight."""
    import asyncio

    from .orchestration.research_worker import (
        ResearchTaskExecutor,
        ResearchTeamRunner,
        TeamRunLimits,
        TeamRunManifest,
    )
    from .orchestration.workspace_selection import configured_workspace_factory
    from .run_control import run_preflight
    from .worker import Activities

    try:
        settings, service, actor = local_authority("operator")
        factory = configured_workspace_factory(settings)
        report = run_preflight(
            service,
            actor,
            experiment_id,
            prices=settings.model_prices,
            environment=os.environ,
            workbench_factory=factory,
            requested_concurrency=concurrency,
        )
        if report["status"] == "blocked":
            output(report)
            raise typer.Exit(1)
        experiment = service.get_record("experiment", experiment_id, actor)
        if concurrency > experiment["budget"]["max_concurrency"]:
            raise HarnessError("TEAM_LIMIT", "Concurrency exceeds the experiment envelope.")
        root_count = 1 if experiment["policy"] == "direct" else len(experiment["models"])
        if max_tasks < root_count:
            raise HarnessError("TEAM_LIMIT", "Task bound is smaller than the configured root team.")
        # Validate the finite supervisor and instantiate dependencies before any queue event.
        limits = TeamRunLimits(
            max_concurrency=concurrency,
            max_tasks=max_tasks,
            timeout_seconds=timeout_seconds,
        )
        executor = ResearchTaskExecutor(
            service, prices=settings.model_prices, workspace_factory=factory
        )
        action = {"created": "start", "paused": "resume", "blocked": "resume"}.get(
            experiment["status"]
        )
        if action:
            service.transition_experiment(
                experiment_id,
                action,
                experiment["revision"],
                actor,
                f"operator-start:{experiment_id}:{experiment['revision']}",
            )
        # Reuse identical controller identities and idempotency keys as Temporal delivery.
        seeded = Activities(service, executor).apply_experiment_command(
            {
                "project_id": actor.project_id,
                "aggregate_id": experiment_id,
                "kind": "experiment.queued",
            }
        )
        result = asyncio.run(
            ResearchTeamRunner(service, executor=executor).run(
                TeamRunManifest(
                    experiment_id=experiment_id,
                    project_id=actor.project_id,
                    mode="live",
                    task_ids=seeded["task_ids"],
                    **limits.model_dump(),
                )
            )
        )
    except typer.Exit:
        raise
    except Exception as error:
        fail(error)
    output(result)
    if result.get("status") != "completed":
        raise typer.Exit(1)


@app.command("init")
def initialize(project: str = "local-lab", directory: Path = Path(".state")):
    """Create a development database and separate identity files, refusing overwrite."""
    from .storage import Database

    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (directory / "auth.json").exists():
            raise HarnessError(
                "ALREADY_INITIALIZED",
                "Identity store already exists; use the existing credentials.",
            )
        identities = {}
        for role in ["researcher", "reviewer", "operator", "publisher"]:
            token = secrets.token_urlsafe(48)
            principal = Principal(id=f"local-{role}", project_id=project, role=role)
            identities[token] = principal.model_dump(mode="json")
            with (directory / f"{role}.token").open("x") as stream:
                os.chmod(stream.name, 0o600)
                stream.write(token + "\n")
        with (directory / "auth.json").open("x") as stream:
            os.chmod(stream.name, 0o600)
            json.dump(identities, stream)
        Database(f"sqlite:///{directory / 'harness.db'}").create_schema()
        output(
            {
                "status": "development_initialized",
                "directory": str(directory.resolve()),
                "identity_files": [
                    f"{role}.token" for role in ["researcher", "reviewer", "operator", "publisher"]
                ],
                "verification": "unconfigured",
                "cloud": "unqualified",
            }
        )
    except Exception as error:
        fail(error)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000):
    """Run the authenticated API. Production uses managed TLS termination."""
    import uvicorn

    uvicorn.run("physharness.api:create_app", factory=True, host=host, port=port)


@app.command()
def status():
    try:
        connection = client()
        try:
            output(connection.status())
        finally:
            connection.close()
    except Exception as error:
        fail(error)


@app.command()
def doctor():
    """Probe installed capabilities, failing loudly when essential configuration is absent."""
    import shutil

    from sqlalchemy import text

    from .bootstrap import build_service
    from .execution import provider_capabilities

    checks = []
    try:
        settings = Settings()
        service = build_service(settings)
        with service.db.sessions() as session:
            session.execute(text("SELECT 1 FROM records LIMIT 1"))
        checks.append({"name": "database", "status": "accessible"})
        checks.append(
            {
                "name": "identity_store",
                "status": "configured" if settings.auth_tokens else "missing",
            }
        )
        checks.append(
            {
                "name": "verifier",
                "status": "configured_unqualified" if service.verifier else "missing",
            }
        )
        checks.append(
            {
                "name": "temporal",
                "status": "configured_unprobed" if settings.temporal_address else "missing",
            }
        )
        output(
            {
                "checks": checks,
                "tools": {
                    name: shutil.which(name) for name in ["docker", "lean", "lake", "terraform"]
                },
                "runtime_capabilities": provider_capabilities(),
                "fleet": "unqualified",
            }
        )
        if any(check["status"] == "missing" for check in checks):
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as error:
        fail(error)


@app.command("request")
def request(
    path: str,
    file: Annotated[Path | None, typer.Option()] = None,
    key: Annotated[str | None, typer.Option()] = None,
):
    """GET an API path, or POST the exact JSON file using a visible idempotency key."""
    try:
        connection = client()
        try:
            if file:
                command_key = key or new_id()
                typer.echo(f"Command key: {command_key}", err=True)
                output(
                    connection.request("POST", path, json.loads(file.read_text()), key=command_key)
                )
            else:
                output(connection.request("GET", path))
        finally:
            connection.close()
    except Exception as error:
        fail(error)


@app.command("export")
def export(experiment_id: str, directory: Path):
    """Download a hash-checked reproduction manifest and its source artifacts."""
    import hashlib

    try:
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        os.chmod(directory, 0o700)
        connection = client()
        try:
            manifest = connection.request("GET", f"/v1/experiments/{experiment_id}/export")
            written = set()

            def private_write(path, data):
                descriptor = os.open(
                    path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
                )
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(data)

            for artifact in manifest["records"]["artifact"]:
                if artifact["sha256"] in written:
                    continue
                content = connection.request("GET", f"/v1/artifacts/{artifact['id']}/content")[
                    "content"
                ].encode()
                if hashlib.sha256(content).hexdigest() != artifact["sha256"]:
                    raise HarnessError(
                        "ARTIFACT_INTEGRITY_ERROR", "Exported artifact failed its content hash."
                    )
                private_write(directory / artifact["sha256"], content)
                written.add(artifact["sha256"])
            private_write(directory / "manifest.json", json.dumps(manifest, indent=2).encode())
            from .reproduction import validate_export

            validation = validate_export(directory)
            output(
                {
                    "status": "exported",
                    "path": str(directory.resolve()),
                    "scientific_novelty": "unreviewed",
                    "validation": validation,
                }
            )
        finally:
            connection.close()
    except Exception as error:
        fail(error)


@app.command("validate-export")
def validate_export_command(directory: Path):
    """Check exported bytes without claiming proof replay or publication approval."""
    from .reproduction import validate_export

    try:
        output(validate_export(directory))
    except Exception as error:
        fail(error)


if __name__ == "__main__":
    app()
