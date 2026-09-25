"""Offline content integrity, deliberately separate from acceptance/publication authority."""

import hashlib
import json
import os
import re
from pathlib import Path

from .domain import digest_json
from .errors import HarnessError


def _read_file(path: Path, max_bytes: int):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            import stat

            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("not a regular file")
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("file exceeds export limit")
        return data
    except (OSError, ValueError) as error:
        raise HarnessError(
            "EXPORT_FILE_INVALID",
            "Export contains a missing, linked or oversized file.",
            details={"file": path.name},
        ) from error


def validate_export(directory: Path) -> dict:
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise HarnessError("EXPORT_DIRECTORY_INVALID", "Supply a real export directory.")
    try:
        manifest = json.loads(_read_file(directory / "manifest.json", 200_000_000))
        unsigned = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        if (
            manifest["format"] != "physharness.reproduction.v1"
            or digest_json(unsigned) != manifest["manifest_sha256"]
        ):
            raise ValueError("manifest hash or format")
        hashes = set()
        for artifact in manifest["records"]["artifact"]:
            sha = artifact["sha256"]
            if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
                raise ValueError("invalid artifact identity")
            data = _read_file(directory / sha, 20_000_000)
            if hashlib.sha256(data).hexdigest() != sha:
                raise ValueError("artifact hash mismatch")
            hashes.add(sha)
        from .execution.checkpoint_chunks import decode, is_manifest

        artifacts = {row["id"]: row for row in manifest["records"]["artifact"]}
        if len(artifacts) != len(manifest["records"]["artifact"]):
            raise ValueError("duplicate artifact identity")
        for artifact in artifacts.values():
            if artifact.get("artifact_kind") != "native_checkpoint":
                continue
            raw = _read_file(directory / artifact["sha256"], 20_000_000)
            try:
                parsed = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
            if not is_manifest(parsed):
                continue
            owner = (artifact.get("provenance") or {}).get("task_id")
            if not owner:
                raise ValueError("checkpoint owner is missing")

            def read(ref, *, artifact=artifact, owner=owner):
                chunk = artifacts.get(ref["artifact_id"])
                if (
                    chunk is None
                    or chunk.get("artifact_kind") != "native_checkpoint_chunk"
                    or chunk.get("experiment_id") != artifact.get("experiment_id")
                    or (chunk.get("provenance") or {}).get("task_id") != owner
                    or (chunk.get("provenance") or {}).get("session_id")
                    != (artifact.get("provenance") or {}).get("session_id")
                    or chunk.get("sha256") != ref["sha256"]
                ):
                    raise ValueError("checkpoint chunk scope mismatch")
                return _read_file(directory / chunk["sha256"], 20_000_000)

            restored = decode(raw, read)
            if restored.session.id != (artifact.get("provenance") or {}).get("session_id"):
                raise ValueError("checkpoint session mismatch")
        return {
            "status": "artifact_integrity_checked",
            "manifest_sha256": manifest["manifest_sha256"],
            "unique_artifacts_checked": len(hashes),
            "kernel_replay": "not_performed",
            "publication_approved": False,
            "limitations": [
                "Hashes establish content integrity, not the authenticity of supplied receipts.",
                "Independent kernel replay, complete trusted dependencies "
                "and expert publication review remain required.",
            ],
        }
    except HarnessError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise HarnessError(
            "EXPORT_INTEGRITY_ERROR", "Export manifest or artifact integrity failed."
        ) from error
