import json

import pytest
from test_core import setup_experiment

from physharness.domain import ArtifactCreate, digest_json
from physharness.errors import HarnessError
from physharness.reproduction import validate_export


def export_fixture(lab, directory):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    artifact = service.create_artifact(
        ArtifactCreate(experiment_id=experiment["id"], kind="finding", content="Unresolved"),
        actor,
        "result",
    )
    manifest = service.export_experiment(experiment["id"], actor)
    directory.mkdir()
    (directory / artifact["sha256"]).write_bytes(b"Unresolved")
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return manifest, artifact


def test_export_has_review_and_consistent_snapshot_identity(lab, tmp_path):
    manifest, _ = export_fixture(lab, tmp_path / "export")
    assert manifest["records"]["review"][0]["id"] == manifest["problem"]["review_id"]
    assert manifest["snapshot"]["isolation"] in {"sqlite_immediate", "postgresql_repeatable_read"}
    assert manifest["snapshot"]["last_project_event_sequence"] > 0
    result = validate_export(tmp_path / "export")
    assert result["status"] == "artifact_integrity_checked"
    assert result["kernel_replay"] == "not_performed"
    assert result["publication_approved"] is False


@pytest.mark.parametrize("tamper", ["manifest", "artifact", "symlink", "missing"])
def test_export_validation_rejects_tampering_and_missing_bytes(lab, tmp_path, tamper):
    directory = tmp_path / "export"
    manifest, artifact = export_fixture(lab, directory)
    if tamper == "manifest":
        manifest["qualification"]["live_fleet"] = "qualified"
        (directory / "manifest.json").write_text(json.dumps(manifest))
    else:
        target = directory / artifact["sha256"]
        target.unlink()
        if tamper == "artifact":
            target.write_bytes(b"forged")
        elif tamper == "symlink":
            other = tmp_path / "other"
            other.write_bytes(b"Unresolved")
            target.symlink_to(other)
    with pytest.raises(HarnessError):
        validate_export(directory)


def test_hash_checked_export_does_not_trust_claimed_qualification(lab, tmp_path):
    directory = tmp_path / "export"
    manifest, _ = export_fixture(lab, directory)
    manifest["qualification"] = {"scientific_novelty": "approved", "live_fleet": "qualified"}
    manifest["manifest_sha256"] = digest_json(
        {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    )
    (directory / "manifest.json").write_text(json.dumps(manifest))
    result = validate_export(directory)
    assert result["publication_approved"] is False
    assert result["kernel_replay"] == "not_performed"


def test_worker_can_export_current_target_review_without_browsing_other_reviews(lab):
    from test_sharing import approaches

    service, _, exp, _, (alpha, _) = approaches(lab, "none")
    manifest = service.export_experiment(exp["id"], alpha)
    assert manifest["records"]["review"][0]["id"] == manifest["problem"]["review_id"]
    assert len(service.list_records("review", alpha)) == 1


def test_fifo_manifest_is_rejected_without_blocking(tmp_path):
    import os
    from concurrent.futures import ThreadPoolExecutor

    os.mkfifo(tmp_path / "manifest.json")
    with ThreadPoolExecutor(max_workers=1) as pool:
        attempt = pool.submit(validate_export, tmp_path)
        with pytest.raises(HarnessError):
            attempt.result(timeout=1)


def test_cli_export_is_private_independently_of_umask(lab, tmp_path, monkeypatch):
    import os
    import stat

    from physharness import cli

    source = tmp_path / "source"
    manifest, _ = export_fixture(lab, source)

    class TestTransport:
        def request(self, method, path):
            if path.endswith("/export"):
                return manifest
            return {"content": "Unresolved"}

        def close(self):
            pass

    monkeypatch.setattr(cli, "client", lambda: TestTransport())
    target = tmp_path / "private-export"
    previous = os.umask(0o022)
    try:
        cli.export(manifest["experiment"]["id"], target)
    finally:
        os.umask(previous)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in target.iterdir())
