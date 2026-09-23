"""Fail-closed source provenance tests; never compile Lean on the host."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

TOOL = Path(__file__).parents[1] / "tools" / "formal_environment.py"


def module():
    assert TOOL.exists(), "formal source-audit tool must exist"
    spec = importlib.util.spec_from_file_location("formal_environment", TOOL)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def archive(tmp_path, entries):
    output = tmp_path / "source.tar.gz"
    with tarfile.open(output, "w:gz") as stream:
        for name, content, link in entries:
            info = tarfile.TarInfo(name)
            if link:
                info.type = tarfile.SYMTYPE
                info.linkname = content
                stream.addfile(info)
            else:
                data = content.encode()
                info.size = len(data)
                stream.addfile(info, io.BytesIO(data))
    return output


def test_rejects_archive_hash_mismatch_before_extracting(tmp_path):
    source = archive(tmp_path, [("root/Module.lean", "theorem safe : True := True.intro", False)])
    with pytest.raises(ValueError, match="SHA256"):
        module().extract_verified(source, "0" * 64, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "name,content,link",
    [
        ("root/../../escape", "bad", False),
        ("/absolute", "bad", False),
        ("root/link", "/etc/passwd", True),
    ],
)
def test_rejects_unsafe_archive_members(tmp_path, name, content, link):
    source = archive(tmp_path, [(name, content, link)])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="archive"):
        module().extract_verified(source, digest, tmp_path / "out")
    assert not (tmp_path / "escape").exists()


def test_extracts_only_verified_archive(tmp_path):
    source = archive(tmp_path, [("root/Module.lean", "def energy := 1", False)])
    module().extract_verified(
        source, hashlib.sha256(source.read_bytes()).hexdigest(), tmp_path / "out"
    )
    assert (tmp_path / "out" / "Module.lean").read_text() == "def energy := 1"


def test_audit_records_real_declarations_and_risks_without_trust_claim(tmp_path):
    source = tmp_path / "physlib" / "Physlib" / "Model.lean"
    source.parent.mkdir(parents=True)
    source.write_text(
        """import Mathlib.Data.Real.Basic
namespace Model
/- theorem fake : True := sorry /- nested -/ -/
def label := "axiom false : False"
noncomputable def energy : Nat := 1
theorem conserved : energy = 1 := by rfl
axiom empirical : True
theorem unfinished : True := by sorry
end Model
"""
    )
    selection = {
        "modules": [
            {
                "package": "physlib",
                "path": "Physlib/Model.lean",
                "declarations": ["energy", "conserved", "empirical", "unfinished"],
            }
        ]
    }
    result = module().audit_declarations(tmp_path, selection)
    entry = result["modules"][0]
    assert [d["name"] for d in entry["declarations"]] == [
        "energy",
        "conserved",
        "empirical",
        "unfinished",
    ]
    assert entry["imports"] == ["Mathlib.Data.Real.Basic"]
    assert entry["risk_tokens"] == {"axiom": [7], "sorry": [8]}
    assert entry["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["semantic_review"] == "not_reviewed"
    assert result["kernel_check"] == "not_run"
    assert result["sandbox_qualification"] == "not_run"


def test_audit_fails_for_missing_requested_declaration(tmp_path):
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "X.lean").write_text("-- theorem invented : True := by trivial\n")
    with pytest.raises(ValueError, match="declaration.*invented"):
        module().audit_declarations(
            tmp_path,
            {"modules": [{"package": "p", "path": "X.lean", "declarations": ["invented"]}]},
        )


@pytest.mark.parametrize("path", ["../outside.lean", "/etc/passwd", "X.lean"])
def test_audit_rejects_paths_outside_verified_package(tmp_path, path):
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "X.lean").symlink_to("/etc/passwd")
    with pytest.raises(ValueError, match="path|symlink"):
        module().audit_declarations(
            tmp_path, {"modules": [{"package": "p", "path": path, "declarations": ["x"]}]}
        )


def test_committed_lock_has_real_immutable_inputs_and_shared_toolchain():
    lock = json.loads((TOOL.parents[1] / "formal" / "environment.lock.json").read_text())
    module().validate_lock(lock)
    assert lock["lean"]["version"] == "v4.33.0"
    assert (
        lock["sources"]["comparator"]["lean_toolchain"]
        == lock["sources"]["physlib"]["lean_toolchain"]
    )
    assert lock["sources"]["mathlib"]["revision"] == "db584cd6d46c92f209a44c0f1c829460d327499d"
    assert lock["libraries"]["QuantumInfo"]["source"] == "physlib"
    assert all(lib["semantic_review"] == "not_reviewed" for lib in lock["libraries"].values())


def test_lock_rejects_mutable_revision_and_missing_archive_hash():
    lock = json.loads((TOOL.parents[1] / "formal" / "environment.lock.json").read_text())
    tool = module()
    lock["sources"]["comparator"]["revision"] = "master"
    with pytest.raises(ValueError, match="revision"):
        tool.validate_lock(lock)
    lock["sources"]["comparator"]["revision"] = "a" * 40
    lock["sources"]["comparator"]["archive_sha256"] = None
    with pytest.raises(ValueError, match="SHA256"):
        tool.validate_lock(lock)


def test_download_rejects_wrong_bytes_without_publishing_cache(tmp_path):
    source = tmp_path / "response"
    source.write_bytes(b"bad gateway, not a source archive")
    output = tmp_path / "cache" / "source.tar.gz"
    with pytest.raises(ValueError, match="SHA256"):
        module().download_verified(source.as_uri(), "0" * 64, output)
    assert not output.exists()
    assert not output.with_suffix(".gz.partial").exists()


def test_download_existing_corrupt_cache_is_not_silently_reused(tmp_path):
    output = tmp_path / "source.tar.gz"
    output.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="SHA256"):
        module().download_verified("https://example.invalid/source", "0" * 64, output)


def test_preserves_safe_internal_upstream_documentation_symlink(tmp_path):
    source = archive(
        tmp_path,
        [("root/README.md", "source", False), ("root/docs/README.md", "../README.md", True)],
    )
    module().extract_verified(
        source, hashlib.sha256(source.read_bytes()).hexdigest(), tmp_path / "out"
    )
    assert (tmp_path / "out" / "docs" / "README.md").read_text() == "source"


def test_audit_allows_os_directory_alias_but_not_package_symlinks(tmp_path):
    real = tmp_path / "real"
    source = real / "p" / "M.lean"
    source.parent.mkdir(parents=True)
    source.write_text("def x := 1\n")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    result = module().audit_declarations(
        alias, {"modules": [{"package": "p", "path": "M.lean", "declarations": ["x"]}]}
    )
    assert result["modules"][0]["declarations"][0]["name"] == "x"


def test_lake_preparation_preserves_revision_evidence_and_is_idempotent(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "prepare_lake", TOOL.parents[1] / "formal" / "prepare_lake.py"
    )
    helper = importlib.util.module_from_spec(spec)
    # Import must not mutate the real /opt filesystem.
    source = tmp_path / "sources"
    package = source / "comparator"
    package.mkdir(parents=True)
    upstream = {
        "packages": [
            {
                "name": "lean4export",
                "rev": "a" * 40,
                "type": "git",
                "configFile": "lakefile.toml",
                "inherited": False,
            }
        ]
    }
    (package / "lake-manifest.json").write_text(json.dumps(upstream))
    physics = source / "physlib"
    physics.mkdir()
    physics_config = 'name = "Physlib"\nenableArtifactCache = true\nrestoreAllArtifacts = true\n'
    (physics / "lakefile.toml").write_text(physics_config)
    (physics / "Model.lean").write_bytes(b"def model := 1\n")
    spec.loader.exec_module(helper)
    lock = {"sources": {"lean4export": {"revision": "a" * 40}}}
    helper.prepare(source, lock)
    helper.prepare(source, lock)
    assert json.loads((package / "lake-manifest.upstream.json").read_text()) == upstream
    assert json.loads((package / "lake-manifest.json").read_text())["packages"][0]["dir"] == str(
        source / "lean4export"
    )
    assert (physics / "lakefile.upstream.toml").read_text() == physics_config
    assert (physics / "lakefile.toml").read_text() == physics_config.replace(
        "enableArtifactCache = true", "enableArtifactCache = false"
    )
    assert (physics / "Model.lean").read_bytes() == b"def model := 1\n"
    prepared_bytes = (physics / "lakefile.toml").read_bytes()
    (physics / "lakefile.upstream.toml").write_text('name = "Unexpected"\n')
    with pytest.raises(ValueError, match="Unexpected Physlib"):
        helper.prepare(source, lock)
    assert (physics / "lakefile.toml").read_bytes() == prepared_bytes


def test_download_does_not_delete_an_existing_partial_file(tmp_path):
    source = tmp_path / "upstream"
    source.write_bytes(b"verified")
    output = tmp_path / "archive.tar.gz"
    partial = output.with_suffix(".gz.partial")
    partial.write_bytes(b"another download in progress")
    module().download_verified(source.as_uri(), hashlib.sha256(b"verified").hexdigest(), output)
    assert output.read_bytes() == b"verified"
    assert partial.read_bytes() == b"another download in progress"


def test_lock_rejects_missing_required_checker_and_architecture():
    lock = json.loads((TOOL.parents[1] / "formal" / "environment.lock.json").read_text())
    tool = module()
    removed = lock["sources"].pop("landrun")
    with pytest.raises(ValueError, match="required source"):
        tool.validate_lock(lock)
    lock["sources"]["landrun"] = removed
    lock["lean"]["archives"].pop("arm64")
    with pytest.raises(ValueError, match="architecture"):
        tool.validate_lock(lock)


def test_dockerfile_and_source_lock_agree_on_builder_inputs():
    lock = json.loads((TOOL.parents[1] / "formal" / "environment.lock.json").read_text())
    dockerfile = (TOOL.parents[1] / "formal" / "Dockerfile").read_text()
    for image in lock["builder_images"].values():
        assert "FROM " + image + " AS " in dockerfile
    assert lock["debian_snapshot"] in dockerfile
    assert "QUALIFIED_TOOLCHAIN_IMAGE" not in dockerfile


def test_build_context_excludes_caches_and_unrelated_formal_files(tmp_path):
    required = [
        "formal/Dockerfile",
        "formal/environment.lock.json",
        "formal/prepare_lake.py",
        "formal/record_build.py",
        "formal/DeclarationAudit.lean",
        "tools/formal_environment.py",
        "src/physharness/verification/container_driver.py",
        "src/physharness/verification/resource_policy.py",
    ]
    included = [
        *required,
        "formal/smoke/classical/Challenge.lean",
        "formal/adversarial/Attack.lean",
    ]
    excluded = [
        "formal/.lake/build/Candidate.lean",
        "formal/.elan/toolchains/private",
        "formal/smoke/.lake/Untrusted.lean",
        "formal/private-credentials.json",
        ".state/provider-key",
        "formal/__pycache__/record_build.pyc",
    ]
    for name in [*included, *excluded]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic source" if name in included else "never send this")
    output = io.BytesIO()
    module().write_build_context(tmp_path, output)
    # Buildx peeks only 1024 bytes: a leading PAX header plus its payload leaves
    # no actual member header to recognize, and stdin is mistaken for a Dockerfile.
    assert output.getvalue()[156:157] == tarfile.REGTYPE
    with tarfile.open(fileobj=io.BytesIO(output.getvalue())) as context:
        names = set(context.getnames())
        assert names == set(included)
        assert all(b"never send this" not in context.extractfile(name).read() for name in names)
