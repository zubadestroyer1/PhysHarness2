import importlib.util
import io
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]


def migration_config(url, output=None):
    config = Config(str(ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_migration_creates_real_schema_and_can_revert(tmp_path, monkeypatch):
    monkeypatch.delenv("PHYSHARNESS_DATABASE_URL", raising=False)
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = migration_config(url)
    command.upgrade(config, "head")
    engine = sa.create_engine(url)
    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()) == {
        "alembic_version",
        "records",
        "commands",
        "events",
        "outbox",
        "budgets",
        "reservations",
        "leases",
        "dependencies",
    }
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO budgets (experiment_id,max_cost,max_concurrency) VALUES ('exp',100,2)"
            )
        )
        row = connection.execute(
            sa.text(
                "SELECT reserved,spent,active_workers,tokens_reserved,tokens_spent FROM budgets"
            )
        ).one()
        assert tuple(row) == (0, 0, 0, 0, 0)
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO budgets (experiment_id,max_cost,max_concurrency) "
                "VALUES ('invalid',-1,2)"
            )
        )
    engine.dispose()
    command.downgrade(config, "base")
    assert sa.inspect(sa.create_engine(url)).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")


def test_frozen_migration_matches_current_column_and_index_contract(tmp_path, monkeypatch):
    from physharness.storage import Base

    monkeypatch.delenv("PHYSHARNESS_DATABASE_URL", raising=False)
    url = f"sqlite:///{tmp_path / 'schema.db'}"
    command.upgrade(migration_config(url), "head")
    engine = sa.create_engine(url)
    inspector = sa.inspect(engine)
    for table in Base.metadata.sorted_tables:
        expected = {(c.name, c.nullable) for c in table.columns}
        actual = {(c["name"], c["nullable"]) for c in inspector.get_columns(table.name)}
        assert actual == expected, table.name
        # SQLite's generic reflection skips expression indexes. Compare its actual
        # index DDL with ORM DDL instead, including the literal JSON scope path.
        with engine.connect() as connection:
            actual_indexes = dict(
                connection.execute(
                    sa.text(
                        "SELECT name, sql FROM sqlite_master WHERE type='index' "
                        "AND tbl_name=:table AND sql IS NOT NULL"
                    ),
                    {"table": table.name},
                ).all()
            )
        expected_indexes = {
            index.name: str(sa.schema.CreateIndex(index).compile(dialect=engine.dialect))
            for index in table.indexes
        }
        assert actual_indexes == expected_indexes
    engine.dispose()
    for migration in (ROOT / "migrations/versions").glob("*.py"):
        assert "physharness.storage" not in migration.read_text()


def test_postgresql_offline_migration_generates_real_sql(monkeypatch):
    monkeypatch.delenv("PHYSHARNESS_DATABASE_URL", raising=False)
    output = io.StringIO()
    command.upgrade(
        migration_config("postgresql+psycopg://unused:unused@localhost/unused", output),
        "head",
        sql=True,
    )
    sql = output.getvalue()
    assert "CREATE TABLE records" in sql
    assert "CREATE TABLE reservations" in sql
    assert "SERIAL" in sql
    assert "COMMIT" in sql
    assert "CREATE INDEX records_project_kind_keyset ON records (project_id, kind, id)" in sql
    assert "CREATE INDEX records_project_kind_experiment_keyset" in sql
    assert "CAST(payload ->> 'experiment_id' AS VARCHAR)" in sql


def load_validator():
    spec = importlib.util.spec_from_file_location(
        "infrastructure_validator", ROOT / "infra/validate_metadata.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_metadata_validator_rejects_mutable_images_and_unpinned_actions():
    validator = load_validator()
    assert validator.validate_image("example/app@sha256:" + "a" * 64) is None
    for image in ["example/app:latest", "example/app", "example/app:dev", "example/app@sha256:bad"]:
        assert validator.validate_image(image)
    assert validator.validate_action("actions/checkout@" + "a" * 40) is None
    assert validator.validate_action("actions/checkout@v4")


def test_repository_infrastructure_metadata_validates():
    assert load_validator().validate_repository(ROOT) == []


def test_postgresql_live_migration_uses_isolated_schema(monkeypatch):
    import os
    from uuid import uuid4

    url = os.environ.get("PHYSHARNESS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("No dedicated PostgreSQL test endpoint configured")
    monkeypatch.delenv("PHYSHARNESS_DATABASE_URL", raising=False)
    schema = f"harness_ci_{uuid4().hex}"
    engine = sa.create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            config = migration_config(url)
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            row = connection.execute(
                sa.text(
                    "INSERT INTO events "
                    "(project_id,kind,aggregate_id,operation_id,payload,created_at) "
                    "VALUES ('p','test','a','o','{}','2026-09-14T00:00:00Z') RETURNING sequence"
                )
            ).scalar_one()
            assert row == 1
            assert sa.inspect(connection).has_table("budgets", schema=schema)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def test_local_preparation_generates_private_nonoverwritten_credentials(tmp_path):
    import json
    import stat

    spec = importlib.util.spec_from_file_location("prepare_local", ROOT / "infra/prepare_local.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    destination = tmp_path / ".env"
    module.prepare(destination, ROOT / "infra/images.lock.json")
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    values = dict(
        line.split("=", 1) for line in destination.read_text().splitlines() if "=" in line
    )
    tokens = json.loads(values["PHYSHARNESS_AUTH_TOKENS"].strip("'"))
    assert len(tokens) == 3 and all(len(token) >= 32 for token in tokens)
    assert {principal["role"] for principal in tokens.values()} == {
        "researcher",
        "reviewer",
        "operator",
    }
    assert "OPENAI_API_KEY" not in values
    with pytest.raises(FileExistsError):
        module.prepare(destination, ROOT / "infra/images.lock.json")


def test_qualified_lean_input_digest_cannot_be_forged(tmp_path):
    import hashlib

    spec = importlib.util.spec_from_file_location(
        "qualified_ci", ROOT / "infra/run_qualified_lean.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "evidence.json"
    source.write_bytes(b'{"operator":"reviewed"}')
    assert (
        module.pinned_bytes(source, hashlib.sha256(source.read_bytes()).hexdigest())
        == source.read_bytes()
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        module.pinned_bytes(source, "0" * 64)
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="real file"):
        module.pinned_bytes(link, hashlib.sha256(source.read_bytes()).hexdigest())


def test_migrations_use_supplied_transaction_connection(tmp_path, monkeypatch):
    monkeypatch.delenv("PHYSHARNESS_DATABASE_URL", raising=False)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        config = migration_config(f"sqlite:///{tmp_path / 'should-not-exist.db'}")
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        assert sa.inspect(connection).has_table("records")
    assert not (tmp_path / "should-not-exist.db").exists()


def test_recorded_rds_trust_store_matches_public_bundle_digest():
    import hashlib
    import json

    metadata = json.loads((ROOT / "infra/certs/rds-global-bundle.json").read_text())
    bundle = (ROOT / "infra/certs/rds-global-bundle.pem").read_bytes()
    assert metadata["source"] == "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
    assert hashlib.sha256(bundle).hexdigest() == metadata["sha256"]
    assert b"PRIVATE KEY" not in bundle
    assert b"BEGIN CERTIFICATE" in bundle


def test_real_compose_parser_accepts_all_profiles(tmp_path):
    import shutil
    import subprocess
    import sys

    executable = shutil.which("docker-compose")
    if executable is None:
        pytest.skip("Standalone Compose parser is not installed")
    private_env = tmp_path / ".env"
    subprocess.run(
        [sys.executable, str(ROOT / "infra/prepare_local.py"), "--output", str(private_env)],
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        [
            executable,
            "--env-file",
            str(private_env),
            "-f",
            str(ROOT / "compose.yaml"),
            "--profile",
            "app",
            "--profile",
            "worker",
            "config",
            "--quiet",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_failed_qualification_run_replaces_stale_pass_with_current_blocked(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "qualified_failure", ROOT / "infra/run_qualified_lean.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "qualification.json"
    output.write_text('{"status":"passed","run_id":"old"}')
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    with pytest.raises(RuntimeError, match="Linux"):
        module.run_from_environment(output)
    current = json.loads(output.read_text())
    assert current["status"] == "blocked"
    assert current["run_id"] != "old"
    assert current["results"] == []


def test_failed_qualification_retains_current_partial_results(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "qualified_partial", ROOT / "infra/run_qualified_lean.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def fail_after_result(output, report):
        report["results"].append({"id": "partial", "outcome": "blocked"})
        raise RuntimeError("qualification fault")

    monkeypatch.setattr(module, "_run_cases", fail_after_result)
    output = tmp_path / "qualification.json"
    with pytest.raises(RuntimeError, match="fault"):
        module.run_from_environment(output)
    current = json.loads(output.read_text())
    assert current["status"] == "blocked"
    assert current["results"] == [{"id": "partial", "outcome": "blocked"}]
