"""Multiple reviewed revisions share environments without sharing acceptance authority."""

import json

import pytest
from test_verification import configured, fake_result, sha

from physharness import verification as v
from physharness.bootstrap import build_service
from physharness.config import Settings
from physharness.verification import resource_policy
from physharness.verification.registry import RegistryDocument


def registry_file(tmp_path):
    entries, requests, configs = [], [], []
    profile = tmp_path / "verifier-resources.json"
    profile.write_bytes(resource_policy.profile_bytes(resource_policy.DEFAULT_PROFILE))
    for index in range(2):
        root = tmp_path / f"bundle{index}"
        root.mkdir()
        verifier, request = configured(root)
        revision = f"revision-{index}"
        manifest = json.loads((root / "manifest.json").read_bytes())
        manifest.update(problem_revision_id=revision, target_digest=str(index + 1) * 64)
        raw = json.dumps(manifest).encode()
        (root / "manifest.json").write_bytes(raw)
        config = verifier.config.model_copy(update={"manifest_sha256": sha(raw)})
        request = request.model_copy(
            update={"problem_revision_id": revision, "target_digest": manifest["target_digest"]}
        )
        entries.append(
            {
                "problem_revision_id": revision,
                "resource_profile": str(profile),
                "config": config.model_dump(mode="json"),
            }
        )
        requests.append(request)
        configs.append(config)
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps({"protocol": "physharness-verifier-registry-v1", "entries": entries})
    )
    return path, requests, configs


def test_registry_routes_exact_revisions_with_shared_environment(tmp_path, monkeypatch):
    assert hasattr(v, "VerifierRegistry"), "multi-revision verifier routing missing"
    path, requests, _ = registry_file(tmp_path)
    registry = v.VerifierRegistry.from_file(path)
    monkeypatch.setattr(
        v.ComparatorVerifier, "_run_container", lambda self, req, *args: fake_result(req)
    )
    assert requests[0].environment_digest == requests[1].environment_digest
    assert requests[0].target_digest != requests[1].target_digest
    for req in requests:
        result = registry.verify(req)
        assert result.status == "verified"
        assert result.target_digest == req.target_digest
    unknown = registry.verify(requests[0].model_copy(update={"problem_revision_id": "unknown"}))
    assert (unknown.status, unknown.code) == ("blocked", "verifier_revision_unconfigured")
    assert registry.preflight(requests[0]).code == "configured_unprobed"


@pytest.mark.parametrize("corruption", ["duplicate", "manifest_pin", "revision", "engineering"])
def test_registry_rejects_ambiguous_or_unpinned_routes(tmp_path, corruption):
    assert hasattr(v, "VerifierRegistry"), "multi-revision verifier routing missing"
    path, _, _ = registry_file(tmp_path)
    doc = json.loads(path.read_bytes())
    if corruption == "duplicate":
        doc["entries"].append(doc["entries"][0])
    elif corruption == "manifest_pin":
        doc["entries"][0]["config"]["manifest_sha256"] = "f" * 64
    elif corruption == "revision":
        doc["entries"][0]["problem_revision_id"] = "different-revision"
    else:
        config = doc["entries"][0]["config"]
        config["execution"] = config.pop("qualification")
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        v.VerifierRegistry.from_file(path)


def test_registry_checks_actual_profile_bytes_in_both_construction_paths(tmp_path):
    path, requests, _ = registry_file(tmp_path)
    document = RegistryDocument.model_validate_json(path.read_bytes())
    assert v.VerifierRegistry(document).preflight(requests[0]).code == "configured_unprobed"
    assert v.VerifierRegistry.from_file(path).preflight(requests[0]).code == "configured_unprobed"
    profile = tmp_path / "verifier-resources.json"
    profile.write_bytes(profile.read_bytes() + b" ")
    constructors = (
        lambda: v.VerifierRegistry(document),
        lambda: v.VerifierRegistry.from_file(path),
    )
    for construct in constructors:
        with pytest.raises(ValueError, match="resource profile source"):
            construct()


def test_registry_rejects_changed_values_even_with_updated_source_hash(tmp_path):
    path, _, _ = registry_file(tmp_path)
    profile = tmp_path / "verifier-resources.json"
    data = json.loads(profile.read_bytes())
    data["cpus"] = 2
    profile.write_text(json.dumps(data))
    document = json.loads(path.read_bytes())
    source_hash = sha(profile.read_bytes())
    config = document["entries"][0]["config"]
    config["resource_profile_source_sha256"] = source_hash
    config["qualification"]["resource_profile_source_sha256"] = source_hash
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="resource profile source"):
        v.VerifierRegistry.from_file(path)


@pytest.mark.parametrize(
    "corruption",
    ["legacy_path", "relative_path", "value", "symlink", "missing", "oversized", "duplicate"],
)
def test_registry_rejects_invalid_profile_source_before_routes_exist(tmp_path, corruption):
    path, _, _ = registry_file(tmp_path)
    document = json.loads(path.read_bytes())
    profile = tmp_path / "verifier-resources.json"
    if corruption == "legacy_path":
        del document["entries"][0]["resource_profile"]
    elif corruption == "relative_path":
        document["entries"][0]["resource_profile"] = "verifier-resources.json"
    elif corruption == "value":
        data = json.loads(profile.read_bytes())
        data["cpus"] = 2
        profile.write_text(json.dumps(data))
    elif corruption == "symlink":
        target = tmp_path / "other-resources.json"
        profile.rename(target)
        profile.symlink_to(target)
    elif corruption == "missing":
        profile.unlink()
    elif corruption == "oversized":
        profile.write_bytes(b" " * 16_385)
    else:
        profile.write_text('{"cpus":4,"cpus":2}')
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        v.VerifierRegistry.from_file(path)


def test_single_bundle_and_registry_settings_are_mutually_exclusive(tmp_path):
    with pytest.raises(ValueError):
        Settings(
            auth_file=tmp_path / "missing",
            verification_registry=tmp_path / "registry.json",
            verification_bundle=tmp_path / "bundle",
        )


def test_registry_setting_builds_router_in_all_service_processes(tmp_path):
    assert hasattr(v, "VerifierRegistry"), "multi-revision verifier routing missing"
    path, requests, _ = registry_file(tmp_path)
    service = build_service(
        Settings(
            auth_file=tmp_path / "missing",
            verification_registry=path,
            database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
            artifact_root=tmp_path / "artifacts",
        )
    )
    assert isinstance(service.verifier, v.VerifierRegistry)
    assert service.verifier.preflight(requests[1]).code == "configured_unprobed"


def test_environment_preparation_and_bundle_do_not_create_review(lab, tmp_path):
    assert hasattr(v, "prepare_environment"), "pinned environment preparation missing"
    assert hasattr(v, "create_problem_bundle"), "canonical bundle preparation missing"
    from test_verification import configured

    from physharness.domain import CampaignCreate, ProblemCreate

    service, actor, _ = lab
    template = tmp_path / "template"
    template.mkdir()
    _, _ = configured(template)
    raw_environment = json.loads((template / "environment.json").read_bytes())
    metadata = {key: raw_environment[key] for key in ("image", "binaries", "checker_versions")}
    metadata_file = tmp_path / "image.json"
    metadata_file.write_text(json.dumps(metadata))
    environment = v.prepare_environment(
        metadata_file,
        image_metadata_sha256=sha(metadata_file.read_bytes()),
        project_directory=template,
        project_files=["lakefile.toml"],
    )
    campaign = service.create_campaign(
        CampaignCreate(title="Prepared", objective="Fixed target", programs=["classical"]),
        actor,
        "campaign",
    )
    problem = service.create_problem(
        ProblemCreate(
            campaign_id=campaign["id"],
            title="Prepared",
            program="classical",
            informal_statement="Identity",
            formal_statement="theorem identity (n : Nat) : n = n := by rfl\n",
            target_theorem="identity",
            environment_digest=sha(environment),
        ),
        actor,
        "problem",
    )
    root = tmp_path / "prepared"
    manifest_sha = v.create_problem_bundle(
        root, problem=problem, environment_bytes=environment, project_directory=template
    )
    assert sha((root / "manifest.json").read_bytes()) == manifest_sha
    assert (root / "environment.json").read_bytes() == environment
    assert (root / "Challenge.lean").read_text() == problem["formal_statement"]
    assert service.get_record("problem", problem["id"], actor)["semantic_review"] == "pending"
    assert service.list_records("review", actor) == []
    assert service.list_records("claim", actor) == []
    with pytest.raises(ValueError, match="environment"):
        v.create_problem_bundle(
            tmp_path / "wrong",
            problem=problem,
            environment_bytes=environment + b" ",
            project_directory=template,
        )
    with pytest.raises(ValueError, match="digest"):
        v.prepare_environment(
            metadata_file,
            image_metadata_sha256="f" * 64,
            project_directory=template,
            project_files=["lakefile.toml"],
        )


def test_bundle_preparation_detects_post_write_source_corruption(tmp_path, monkeypatch):
    from physharness.domain import ProblemCreate, digest_json
    from physharness.verification import preparation
    from physharness.verification.bundles import canonical_json

    template = tmp_path / "template"
    template.mkdir()
    configured(template)
    environment = canonical_json(json.loads((template / "environment.json").read_bytes()))
    fields = ProblemCreate(
        campaign_id="test-campaign",
        title="Target",
        program="classical",
        informal_statement="Test only",
        formal_statement="theorem target : True := by trivial",
        environment_digest=sha(environment),
    ).model_dump(mode="json")
    problem = {**fields, "id": "revision", "target_digest": digest_json(fields)}
    create = preparation.create_bundle

    def corrupt_after_write(destination, **kwargs):
        result = create(destination, **kwargs)
        path = destination / "Challenge.lean"
        path.chmod(0o644)
        path.write_text("theorem changed : False := by sorry")
        return result

    monkeypatch.setattr(preparation, "create_bundle", corrupt_after_write)
    destination = tmp_path / "bundle"
    with pytest.raises(ValueError, match="pins"):
        v.create_problem_bundle(
            destination, problem=problem, environment_bytes=environment, project_directory=template
        )
    assert not destination.exists()


def test_environment_preparation_rejects_symlink_project_root(tmp_path):
    from physharness.verification import preparation

    project = tmp_path / "project"
    project.mkdir()
    configured(project)
    metadata = tmp_path / "metadata.json"
    metadata.write_bytes((project / "environment.json").read_bytes())
    symlink = tmp_path / "linked-project"
    symlink.symlink_to(project, target_is_directory=True)
    with pytest.raises(ValueError, match="directory"):
        preparation.prepare_environment(
            metadata,
            image_metadata_sha256=sha(metadata.read_bytes()),
            project_directory=symlink,
            project_files=["lakefile.toml"],
        )
