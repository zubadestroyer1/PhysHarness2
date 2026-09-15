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
