import hashlib
import json

import pytest

from physharness.execution.types import ExecutionError
from physharness.execution.workspace_archive import WorkspaceArchive


def test_v2_archive_preserves_large_files_and_deduplicates_content():
    data = b"x" * 100_000
    archive = WorkspaceArchive.build({"notes/a.txt": data, "notes/b.txt": data})
    assert archive.files() == {"notes/a.txt": data, "notes/b.txt": data}
    assert len(archive.to_bytes()) < 201_000
    assert archive.to_bytes().startswith(b"PHW2")


def test_archive_rejects_secrets_traversal_and_tampering():
    for path in ["../secret", ".env", "notes/.ssh/key", "notes/__pycache__/x"]:
        with pytest.raises(ExecutionError):
            WorkspaceArchive.build({path: b"x"})
    archive = WorkspaceArchive.build({"notes.txt": b"result"})
    damaged = bytearray(archive.to_bytes())
    damaged[-1] ^= 1
    with pytest.raises(ExecutionError):
        WorkspaceArchive.from_bytes(bytes(damaged), sha256=hashlib.sha256(damaged).hexdigest())


def test_v1_archives_remain_readable():
    raw = json.dumps(
        {
            "format": "physharness.workspace.v1",
            "files": [
                {
                    "path": "notes.txt",
                    "data": "b2xk",
                    "sha256": hashlib.sha256(b"old").hexdigest(),
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    archive = WorkspaceArchive.from_bytes(raw, sha256=hashlib.sha256(raw).hexdigest())
    assert archive.files() == {"notes.txt": b"old"}


def test_repeated_chunk_references_cannot_expand_past_quota():
    chunk = b"x" * 1024
    digest = hashlib.sha256(chunk).hexdigest()
    manifest = json.dumps(
        {
            "format": "physharness.workspace.v2",
            "files": [{"path": "large", "size": 1024 * 10000, "chunks": [digest] * 10000}],
            "chunks": [{"sha256": digest, "size": len(chunk)}],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    raw = b"PHW2" + len(manifest).to_bytes(8, "big") + manifest + chunk
    with pytest.raises(ExecutionError) as err:
        WorkspaceArchive.from_bytes(raw, sha256=hashlib.sha256(raw).hexdigest(), quota_bytes=1024)
    assert err.value.code == "WORKSPACE_LIMIT"


def test_checkpoint_records_reconstructible_cache_exclusions():
    archive = WorkspaceArchive.build({"notes.txt": b"keep"}, excluded_paths=["__pycache__"])
    restored = WorkspaceArchive.from_bytes(archive.to_bytes(), sha256=archive.sha256)
    assert restored.files() == {"notes.txt": b"keep"}
    assert restored.excluded_paths == ["__pycache__"]
