"""Portable regular-file checkpoint with versioned content-addressed manifests.

The wire format is PHW2, an eight-byte manifest length, canonical JSON manifest,
then unique content chunks in manifest order. The old E2B v1 envelope is readable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from .e2b import WorkspaceArchive as LegacyArchive
from .types import ExecutionError

DEFAULT_QUOTA = 256 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024
_MAGIC = b"PHW2"
_V3_FORMAT = "physharness.workspace.v3"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_EXCLUDED = {".git", ".ssh", ".aws", ".config", "__pycache__", ".cache", "node_modules"}


def checked_path(path: str) -> str:
    if not isinstance(path, str) or not path or len(path.encode("utf-8")) > 1024:
        raise ExecutionError("UNSAFE_PATH", "Workspace path must be a bounded relative path")
    parts = path.split("/")
    # Guest file systems reject longer names (NAME_MAX); refuse them before dispatch.
    if any(
        not part
        or part in {".", ".."}
        or "\\" in part
        or "\x00" in part
        or len(part.encode("utf-8")) > 255
        for part in parts
    ):
        raise ExecutionError("UNSAFE_PATH", "Workspace path is not canonical")
    if any(part in _EXCLUDED or part.startswith(".env") or part.endswith(".pyc") for part in parts):
        raise ExecutionError(
            "WORKSPACE_EXCLUDED", "Secrets and generated caches cannot be archived"
        )
    return path


def _json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


@dataclass(frozen=True)
class WorkspaceArchive:
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def to_bytes(self) -> bytes:
        return self.data

    @classmethod
    def build(
        cls,
        files: dict[str, bytes],
        *,
        quota_bytes: int = DEFAULT_QUOTA,
        excluded_paths: list[str] | None = None,
    ) -> WorkspaceArchive:
        if type(quota_bytes) is not int or not 1 <= quota_bytes <= DEFAULT_QUOTA:
            raise ExecutionError("WORKSPACE_LIMIT", "Invalid workspace byte quota")
        entries, chunks = [], {}
        total = 0
        for path, content in sorted(files.items()):
            checked_path(path)
            if not isinstance(content, bytes):
                raise ExecutionError("WORKSPACE_LIMIT", "Workspace files must be bytes")
            total += len(content)
            if total > quota_bytes or len(files) > 10_000:
                raise ExecutionError("WORKSPACE_LIMIT", "Workspace checkpoint exceeds quota")
            refs = []
            for offset in range(0, len(content), CHUNK_SIZE):
                part = content[offset : offset + CHUNK_SIZE]
                digest = hashlib.sha256(part).hexdigest()
                chunks[digest] = part
                refs.append(digest)
            entries.append({"path": path, "size": len(content), "chunks": refs})
        paths = {entry["path"] for entry in entries}
        if any(
            "/".join(path.split("/")[:i]) in paths
            for path in paths
            for i in range(1, len(path.split("/")))
        ):
            raise ExecutionError("UNSAFE_PATH", "File shadows workspace directory")
        exclusions = sorted(set(excluded_paths or []))
        if len(exclusions) > 10_000 or any(
            not isinstance(path, str) or len(path.encode()) > 1024 for path in exclusions
        ):
            raise ExecutionError("WORKSPACE_LIMIT", "Invalid exclusion manifest")
        manifest = _json(
            {
                "format": "physharness.workspace.v2",
                "files": entries,
                "chunks": [
                    {"sha256": key, "size": len(value)} for key, value in sorted(chunks.items())
                ],
                "excluded_paths": exclusions,
            }
        )
        if len(manifest) > 4_000_000:
            raise ExecutionError("WORKSPACE_LIMIT", "Workspace manifest exceeds quota")
        return cls(
            _MAGIC
            + len(manifest).to_bytes(8, "big")
            + manifest
            + b"".join(chunks[k] for k in sorted(chunks))
        )

    @classmethod
    def from_bytes(
        cls, data: bytes, *, sha256: str, quota_bytes: int = DEFAULT_QUOTA
    ) -> WorkspaceArchive:
        if (
            not isinstance(data, bytes)
            or not _DIGEST.fullmatch(sha256)
            or hashlib.sha256(data).hexdigest() != sha256
        ):
            raise ExecutionError("CHECKPOINT_MISMATCH", "Workspace archive checksum mismatch")
        if data.startswith(_MAGIC):
            archive = cls(data)
            archive._v2_files(quota_bytes)
            return archive
        legacy = LegacyArchive.from_bytes(data, sha256=sha256)
        for path in legacy.files():
            checked_path(path)
        return cls(legacy.to_bytes())

    def _v2_files(self, quota_bytes: int) -> dict[str, bytes]:
        if len(self.data) < 12 or len(self.data) > quota_bytes + 4_000_012:
            raise ExecutionError("WORKSPACE_LIMIT", "Workspace archive exceeds quota")
        length = int.from_bytes(self.data[4:12], "big")
        if length > 4_000_000 or 12 + length > len(self.data):
            raise ExecutionError("INVALID_ARCHIVE", "Invalid workspace manifest length")
        try:
            raw = self.data[12 : 12 + length]
            manifest = json.loads(raw)
            if (
                raw != _json(manifest)
                or set(manifest)
                not in (
                    {"format", "files", "chunks"},
                    {"format", "files", "chunks", "excluded_paths"},
                )
                or manifest["format"] != "physharness.workspace.v2"
            ):
                raise ValueError("Invalid manifest")
            chunk_data = {}
            pos = 12 + length
            for entry in manifest["chunks"]:
                if (
                    set(entry) != {"sha256", "size"}
                    or not _DIGEST.fullmatch(entry["sha256"])
                    or type(entry["size"]) is not int
                    or not 0 < entry["size"] <= CHUNK_SIZE
                    or entry["sha256"] in chunk_data
                ):
                    raise ValueError("Invalid chunk entry")
                end = pos + entry["size"]
                chunk = self.data[pos:end]
                if (
                    len(chunk) != entry["size"]
                    or hashlib.sha256(chunk).hexdigest() != entry["sha256"]
                ):
                    raise ValueError("Chunk integrity mismatch")
                chunk_data[entry["sha256"]] = chunk
                pos = end
            if pos != len(self.data):
                raise ValueError("Trailing archive data")
            files = {}
            total = 0
            if len(manifest["files"]) > 10_000:
                raise ExecutionError("WORKSPACE_LIMIT", "Too many workspace files")
            for entry in manifest["files"]:
                if set(entry) != {"path", "size", "chunks"} or entry["path"] in files:
                    raise ValueError("Invalid file entry")
                checked_path(entry["path"])
                if type(entry["size"]) is not int or not 0 <= entry["size"] <= quota_bytes:
                    raise ExecutionError("WORKSPACE_LIMIT", "Workspace file exceeds quota")
                if (
                    not isinstance(entry["chunks"], list)
                    or len(entry["chunks"]) > (quota_bytes + CHUNK_SIZE - 1) // CHUNK_SIZE
                ):
                    raise ExecutionError("WORKSPACE_LIMIT", "Workspace file has too many chunks")
                expected_size = sum(len(chunk_data[key]) for key in entry["chunks"])
                if expected_size != entry["size"]:
                    raise ValueError("File size mismatch")
                total += expected_size
                if total > quota_bytes:
                    raise ExecutionError("WORKSPACE_LIMIT", "Workspace quota exceeded")
                content = b"".join(chunk_data[key] for key in entry["chunks"])
                files[entry["path"]] = content
            if (
                self.build(
                    files,
                    quota_bytes=quota_bytes,
                    excluded_paths=manifest.get("excluded_paths", []),
                ).data
                != self.data
            ):
                raise ValueError("Archive not canonical")
            return files
        except (
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            RecursionError,
            OverflowError,
        ) as exc:
            raise ExecutionError("INVALID_ARCHIVE", "Invalid workspace checkpoint") from exc

    def files(self, *, quota_bytes: int = DEFAULT_QUOTA) -> dict[str, bytes]:
        if self.data.startswith(_MAGIC):
            return self._v2_files(quota_bytes)
        return LegacyArchive.from_bytes(self.data, sha256=self.sha256).files()

    @property
    def excluded_paths(self) -> list[str]:
        if not self.data.startswith(_MAGIC):
            return []
        length = int.from_bytes(self.data[4:12], "big")
        return json.loads(self.data[12 : 12 + length]).get("excluded_paths", [])


@dataclass(frozen=True)
class StreamedWorkspaceArchive:
    """Small canonical manifest; chunk bytes live in separately scoped CAS artifacts."""

    data: bytes
    manifest: dict

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def chunk_artifact_ids(self) -> list[str]:
        return [chunk["artifact_id"] for chunk in self.manifest["chunks"]]

    @classmethod
    def build(
        cls,
        files: list[dict],
        chunks: list[dict],
        *,
        excluded_paths: list[str] | None = None,
        quota_bytes: int = DEFAULT_QUOTA,
    ) -> StreamedWorkspaceArchive:
        return cls.from_bytes(
            _json(
                {
                    "format": _V3_FORMAT,
                    "files": files,
                    "chunks": chunks,
                    "excluded_paths": excluded_paths or [],
                }
            ),
            quota_bytes=quota_bytes,
        )

    @classmethod
    def from_bytes(
        cls, data: bytes, *, sha256: str | None = None, quota_bytes: int = DEFAULT_QUOTA
    ) -> StreamedWorkspaceArchive:
        if type(quota_bytes) is not int or not 1 <= quota_bytes <= DEFAULT_QUOTA:
            raise ExecutionError("WORKSPACE_LIMIT", "Invalid workspace byte quota")
        if not isinstance(data, bytes) or len(data) > 4_000_000:
            raise ExecutionError("WORKSPACE_LIMIT", "Workspace manifest exceeds quota")
        if sha256 is not None and (
            not isinstance(sha256, str)
            or not _DIGEST.fullmatch(sha256)
            or hashlib.sha256(data).hexdigest() != sha256
        ):
            raise ExecutionError("CHECKPOINT_MISMATCH", "Workspace manifest checksum mismatch")
        try:
            manifest = json.loads(data)
            if (
                data != _json(manifest)
                or not isinstance(manifest, dict)
                or set(manifest) != {"format", "files", "chunks", "excluded_paths"}
                or manifest["format"] != _V3_FORMAT
            ):
                raise ValueError("Noncanonical workspace manifest")
            files, chunks, exclusions = (
                manifest["files"],
                manifest["chunks"],
                manifest["excluded_paths"],
            )
            if not isinstance(files, list) or len(files) > 10_000 or not isinstance(chunks, list):
                raise ValueError("Invalid manifest lists")
            max_refs = (quota_bytes + CHUNK_SIZE - 1) // CHUNK_SIZE + 10_000
            if (
                len(chunks) > max_refs
                or not isinstance(exclusions, list)
                or len(exclusions) > 10_000
            ):
                raise ValueError("Manifest list exceeds bound")
            chunk_map = {}
            artifact_ids = set()
            for chunk in chunks:
                if not isinstance(chunk, dict) or set(chunk) != {"sha256", "size", "artifact_id"}:
                    raise ValueError("Invalid chunk entry")
                digest, size, artifact_id = chunk["sha256"], chunk["size"], chunk["artifact_id"]
                if (
                    not isinstance(digest, str)
                    or not _DIGEST.fullmatch(digest)
                    or type(size) is not int
                    or not 0 < size <= CHUNK_SIZE
                    or not isinstance(artifact_id, str)
                    or not 1 <= len(artifact_id) <= 128
                    or digest in chunk_map
                    or artifact_id in artifact_ids
                ):
                    raise ValueError("Invalid or duplicate chunk")
                chunk_map[digest] = size
                artifact_ids.add(artifact_id)
            if chunks != sorted(chunks, key=lambda chunk: chunk["sha256"]):
                raise ValueError("Chunks must be sorted")
            total = 0
            paths = set()
            used = set()
            references = 0
            for entry in files:
                if not isinstance(entry, dict) or set(entry) != {
                    "path",
                    "size",
                    "sha256",
                    "chunks",
                }:
                    raise ValueError("Invalid file entry")
                path, size, digest, refs = (
                    entry["path"],
                    entry["size"],
                    entry["sha256"],
                    entry["chunks"],
                )
                checked_path(path)
                if path in paths or type(size) is not int or not 0 <= size <= quota_bytes:
                    raise ValueError("Invalid or duplicate file")
                if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
                    raise ValueError("Invalid file digest")
                if not isinstance(refs, list) or len(refs) > max_refs:
                    raise ValueError("Invalid file chunks")
                if any(not isinstance(ref, str) or ref not in chunk_map for ref in refs):
                    raise ValueError("Missing chunk declaration")
                if sum(chunk_map[ref] for ref in refs) != size:
                    raise ValueError("File size differs from chunks")
                total += size
                references += len(refs)
                if total > quota_bytes or references > max_refs:
                    raise ExecutionError("WORKSPACE_LIMIT", "Workspace checkpoint exceeds quota")
                paths.add(path)
                used.update(refs)
            if files != sorted(files, key=lambda entry: entry["path"]) or used != set(chunk_map):
                raise ValueError("Noncanonical file or unused chunk")
            if any(
                "/".join(path.split("/")[:i]) in paths
                for path in paths
                for i in range(1, len(path.split("/")))
            ):
                raise ValueError("File shadows directory")
            if exclusions != sorted(set(exclusions)):
                raise ValueError("Noncanonical exclusions")
            for path in exclusions:
                if not isinstance(path, str) or len(path.encode()) > 1024 or not path:
                    raise ValueError("Invalid excluded path")
                if any(
                    not part or part in {".", ".."} or "\\" in part or "\x00" in part
                    for part in path.split("/")
                ):
                    raise ValueError("Unsafe excluded path")
            return cls(data, manifest)
        except (
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            RecursionError,
            OverflowError,
        ) as exc:
            raise ExecutionError(
                "INVALID_ARCHIVE", "Invalid streamed workspace checkpoint"
            ) from exc
