"""Operator startup configuration; no Docker or proof execution in these tests."""

import hashlib
import json

import pytest
from test_verification import configured

from physharness.bootstrap import build_service
from physharness.config import Settings
from physharness.verification import resource_policy
from physharness.verification.boundary import ResourceProfile


def setup_bundle(tmp_path, profile=None):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    verifier, request = configured(bundle)
    profile = profile or ResourceProfile()
    resources = tmp_path / "resources.json"
    resources.write_text(profile.model_dump_json())
    qualification = verifier.config.qualification.model_copy(
        update={
            "resource_profile_sha256": profile.sha256,
            "resource_profile_source_sha256": hashlib.sha256(resources.read_bytes()).hexdigest(),
            "resource_policy_sha256": resource_policy.policy_digest(),
        }
    )
    qualification_path = tmp_path / "qualification.json"
    qualification_path.write_text(qualification.model_dump_json())
    values = dict(
        auth_file=tmp_path / "absent-auth",
        database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
        artifact_root=tmp_path / "artifacts",
        verification_bundle=bundle,
        verification_manifest_sha256=verifier.config.manifest_sha256,
        verification_qualification=qualification_path,
    )
    return values, resources, request


def test_single_bundle_uses_explicit_pinned_resource_profile(tmp_path, monkeypatch):
    profile = ResourceProfile(memory_bytes=4 * 1024**3, cpus=2)
    values, resources, request = setup_bundle(tmp_path, profile)
    monkeypatch.setenv("PHYSHARNESS_VERIFICATION_RESOURCES", str(resources))
    service = build_service(Settings(**values))
    assert service.verifier.config.resources == profile
    assert service.verifier.preflight(request).code == "configured_unprobed"


def test_single_bundle_requires_explicit_resource_profile(tmp_path):
    values, _, _ = setup_bundle(tmp_path)
    with pytest.raises(ValueError, match="deployment configuration"):
        build_service(Settings(**values))


def test_whitespace_only_profile_source_change_is_rejected(tmp_path):
    values, resources, _ = setup_bundle(tmp_path)
    resources.write_bytes(resources.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="profile source"):
        build_service(Settings(**values, verification_resources=resources))


def test_policy_only_change_is_rejected_before_verifier_construction(tmp_path, monkeypatch):
    values, resources, _ = setup_bundle(tmp_path)
    monkeypatch.setattr(resource_policy, "policy_digest", lambda: "0" * 64)
    with pytest.raises(ValueError, match="resource policy"):
        build_service(Settings(**values, verification_resources=resources))


@pytest.mark.parametrize("field", ["resource_profile_source_sha256", "resource_policy_sha256"])
def test_legacy_qualification_missing_resource_pin_fails_closed(tmp_path, field):
    values, resources, _ = setup_bundle(tmp_path)
    path = values["verification_qualification"]
    qualification = json.loads(path.read_bytes())
    del qualification[field]
    path.write_text(json.dumps(qualification))
    with pytest.raises(ValueError):
        build_service(Settings(**values, verification_resources=resources))


@pytest.mark.parametrize(
    "corruption", ["missing", "symlink", "json", "duplicate", "unknown", "oversized"]
)
def test_single_bundle_bad_resource_file_fails_startup(tmp_path, corruption):
    values, resources, _ = setup_bundle(tmp_path)
    if corruption == "missing":
        resources.unlink()
    elif corruption == "symlink":
        target = tmp_path / "other.json"
        resources.rename(target)
        resources.symlink_to(target)
    elif corruption == "json":
        resources.write_text('{"private-diagnostic-canary":')
    elif corruption == "duplicate":
        resources.write_text('{"cpus":4,"cpus":2}')
    elif corruption == "unknown":
        data = json.loads(resources.read_text())
        data["private-diagnostic-canary"] = True
        resources.write_text(json.dumps(data))
    else:
        resources.write_text(" " * 16_385)
    with pytest.raises(ValueError, match="resource") as raised:
        build_service(Settings(**values, verification_resources=resources))
    assert "private-diagnostic-canary" not in str(raised.value)


@pytest.mark.parametrize("mode", ["orphan", "registry"])
def test_resource_setting_cannot_be_ignored(tmp_path, mode):
    values = dict(
        auth_file=tmp_path / "missing", verification_resources=tmp_path / "resources.json"
    )
    if mode == "registry":
        values["verification_registry"] = tmp_path / "registry.json"
    with pytest.raises(ValueError):
        Settings(**values)
