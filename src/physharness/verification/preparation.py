"""Administrative preparation from exact canonical inputs, without review or execution."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..domain import ProblemCreate, digest_json
from .boundary import Environment, Manifest, digest, safe_read
from .bundles import canonical_json, create_bundle, project_path


def _project_bytes(project_directory: Path, names: list[str]) -> dict[str, bytes]:
    if project_directory.is_symlink() or not project_directory.is_dir():
        raise ValueError("Trusted project directory must be a real directory")
    if not names or len(names) > 1000 or len(set(names)) != len(names):
        raise ValueError("Supply 1-1000 unique trusted project file names")
    result, total = {}, 0
    for name in names:
        project_path(name)
        data = safe_read(project_directory, name)
        total += len(data)
        if total > 64_000_000:
            raise ValueError("Trusted project files exceed the 64 MB preparation limit")
        result[name] = data
    if not {"lakefile.toml", "lakefile.lean"} & result.keys():
        raise ValueError("Trusted Lake configuration is required")
    return result


def prepare_environment(
    image_metadata_path: Path,
    *,
    image_metadata_sha256: str,
    project_directory: Path,
    project_files: list[str],
) -> bytes:
    """Return canonical Environment bytes; no network, Lean execution or review occurs."""
    image_metadata_path = Path(image_metadata_path)
    raw = safe_read(image_metadata_path.parent, image_metadata_path.name)
    if len(raw) > 2_000_000 or digest(raw) != image_metadata_sha256:
        raise ValueError("Image metadata digest mismatch or metadata exceeds 2 MB")
    metadata = json.loads(raw)
    if (
        not isinstance(metadata, dict)
        or not {"image", "checker_versions", "binaries"} <= metadata.keys()
    ):
        raise ValueError("Image metadata lacks fixed image/checker executable identities")
    files = _project_bytes(Path(project_directory), project_files)
    environment = Environment(
        image=metadata["image"],
        checker_versions=metadata["checker_versions"],
        binaries=metadata["binaries"],
        files={name: digest(data) for name, data in files.items()},
    )
    if not {"lean", "lake", "comparator", "lean4export", "landrun"} <= environment.binaries.keys():
        raise ValueError("Image metadata lacks required executable pins")
    if not all(environment.checker_versions.get(name) for name in ("lean", "comparator")):
        raise ValueError("Image metadata lacks required checker versions")
    return canonical_json(environment.model_dump())


def create_problem_bundle(
    destination: Path, *, problem: dict, environment_bytes: bytes, project_directory: Path
) -> str:
    """Create a bundle for a stored revision and return its manifest SHA-256.

    Pending revisions may be prepared for review. This validates the canonical problem
    metadata and exact environment/project bytes; it does not change any service record.
    """
    required = {"id", "target_digest", "formal_statement", "environment_digest", "target_theorem"}
    if not isinstance(problem, dict) or not required <= problem.keys():
        raise ValueError("A complete canonical problem revision is required")
    fields = {name: problem[name] for name in ProblemCreate.model_fields if name in problem}
    parsed = ProblemCreate.model_validate(fields)
    if digest_json(parsed.model_dump(mode="json")) != problem["target_digest"]:
        raise ValueError("Canonical problem metadata digest mismatch")
    if not isinstance(environment_bytes, bytes) or len(environment_bytes) > 2_000_000:
        raise ValueError("Environment must be at most 2 MB of exact bytes")
    if digest(environment_bytes) != problem["environment_digest"]:
        raise ValueError("Canonical problem environment digest mismatch")
    environment = Environment.model_validate_json(environment_bytes)
    if canonical_json(environment.model_dump()) != environment_bytes:
        raise ValueError("Environment bytes are not canonical; prepare and review a new revision")
    files = _project_bytes(Path(project_directory), list(environment.files))
    if any(digest(data) != environment.files[name] for name, data in files.items()):
        raise ValueError("Trusted project file digest mismatch")
    destination = Path(destination)
    manifest_sha = create_bundle(
        destination,
        problem_revision_id=problem["id"],
        target_digest=problem["target_digest"],
        challenge_source=problem["formal_statement"],
        theorem_names=[problem["target_theorem"]],
        image_digest=environment.image,
        checker_versions=environment.checker_versions,
        binaries=environment.binaries,
        project_files=files,
    )
    try:
        manifest_raw = safe_read(destination, "manifest.json")
        manifest = Manifest.model_validate_json(manifest_raw)
        if any(
            (
                digest(manifest_raw) != manifest_sha,
                manifest.target_digest != problem["target_digest"],
                manifest.problem_revision_id != problem["id"],
                manifest.challenge_sha256 != digest(problem["formal_statement"].encode("utf-8")),
                manifest.environment_digest != problem["environment_digest"],
                safe_read(destination, "environment.json") != environment_bytes,
                digest(safe_read(destination, "Challenge.lean")) != manifest.challenge_sha256,
                manifest.theorem_names != [problem["target_theorem"]],
                any(
                    digest(safe_read(destination, name)) != expected
                    for name, expected in environment.files.items()
                ),
            )
        ):
            raise ValueError("Prepared bundle does not match canonical input pins")
    except BaseException:
        shutil.rmtree(destination)
        raise
    return manifest_sha
