"""Administrative byte-pinned bundle creation; never creates a semantic review."""

from __future__ import annotations

import json
import shutil
from pathlib import Path, PurePosixPath

from .boundary import Environment, Manifest, digest


def canonical_json(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def project_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or path.as_posix() != name
        or any(part in {".", ".."} for part in path.parts)
        or path.parts[0]
        in {
            ".lake",
            "Challenge.lean",
            "Solution.lean",
            "request.json",
            "config.json",
            "seccomp.json",
            "manifest.json",
            "environment.json",
        }
    ):
        raise ValueError(f"Unsafe or reserved project file: {name}")
    return path


def create_bundle(
    destination: Path,
    *,
    problem_revision_id: str,
    target_digest: str,
    challenge_source: str,
    theorem_names: list[str],
    image_digest: str,
    checker_versions: dict[str, str],
    binaries: dict[str, str],
    project_files: dict[str, bytes],
) -> str:
    """Write an exclusive new bundle; return the SHA-256 to pin in service configuration.

    target_digest names the complete immutable scientific revision. challenge_source is
    exactly its formal_statement, with no newline normalization. This function hashes
    supplied trusted bytes; it does not review source, execute Lean, or qualify an image.
    """
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    for name, content in project_files.items():
        project_path(name)
        if not isinstance(content, bytes) or len(content) > 16_000_000:
            raise ValueError("Project files must be bytes of at most 16 MB")
    if not {"lakefile.toml", "lakefile.lean"} & project_files.keys():
        raise ValueError("Trusted Lake configuration is required")
    if not {"lean", "lake", "comparator", "lean4export", "landrun"} <= binaries.keys():
        raise ValueError("Complete checker executable pins are required")
    if not all(checker_versions.get(name) for name in ("lean", "comparator")):
        raise ValueError("Pinned checker versions are required")
    source = challenge_source.encode("utf-8")
    if len(source) > 16_000_000:
        raise ValueError("Challenge source exceeds 16 MB")
    environment = Environment(
        image=image_digest,
        checker_versions=checker_versions,
        binaries=binaries,
        files={name: digest(data) for name, data in project_files.items()},
    )
    environment_bytes = canonical_json(environment.model_dump())
    manifest = Manifest(
        protocol="physharness-comparator-v2",
        problem_revision_id=problem_revision_id,
        target_digest=target_digest,
        challenge_sha256=digest(source),
        environment_digest=digest(environment_bytes),
        theorem_names=theorem_names,
    )
    manifest_bytes = canonical_json(manifest.model_dump())
    files = {
        **project_files,
        "Challenge.lean": source,
        "environment.json": environment_bytes,
        "manifest.json": manifest_bytes,
    }
    # mkdir is exclusive, including races with another preparation command.
    destination.mkdir(parents=True, mode=0o755)
    try:
        for name, content in files.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(content)
            path.chmod(0o444)
    except BaseException:
        shutil.rmtree(destination)
        raise
    return digest(manifest_bytes)
