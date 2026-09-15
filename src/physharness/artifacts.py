"""Content-addressed storage checks content at every trust boundary."""

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

from .errors import HarnessError


def validate_digest(digest: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise HarnessError(
            "INVALID_DIGEST", "Artifact digest must be a SHA-256 hex string.", status=422
        )


def checked_bytes(digest: str, content: bytes) -> bytes:
    if hashlib.sha256(content).hexdigest() != digest:
        raise HarnessError(
            "ARTIFACT_INTEGRITY_ERROR",
            "Stored bytes do not match their digest.",
            status=500,
            details={"digest": digest},
            remediation="Quarantine the object and restore it from a verified backup.",
        )
    return content


class ArtifactStore(Protocol):
    def put(self, content: bytes) -> str: ...
    def get(self, digest: str) -> bytes: ...


class LocalArtifactStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, digest: str) -> Path:
        validate_digest(digest)
        path = self.root / digest[:2] / digest
        if path.parent.is_symlink() or path.is_symlink():
            raise HarnessError(
                "ARTIFACT_PATH_UNSAFE", "Artifact paths cannot be symlinks.", status=500
            )
        return path

    def put(self, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        path = self.path_for(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.get(digest)
            return digest
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            # Atomic creation: existing content is never overwritten by a second uploader.
            try:
                os.link(name, path)
            except FileExistsError:
                self.get(digest)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(name).unlink(missing_ok=True)
        return digest

    def get(self, digest: str) -> bytes:
        path = self.path_for(digest)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                return checked_bytes(digest, stream.read())
        except FileNotFoundError as error:
            raise HarnessError(
                "ARTIFACT_NOT_FOUND",
                "Artifact bytes are unavailable.",
                status=404,
                details={"digest": digest},
            ) from error


class S3ArtifactStore:
    def __init__(self, bucket: str, client=None, prefix: str = "artifacts"):
        if not bucket:
            raise HarnessError("STORAGE_UNCONFIGURED", "An S3 bucket must be configured.")
        if client is None:
            import boto3

            client = boto3.client("s3")
        self.client, self.bucket, self.prefix = client, bucket, prefix.rstrip("/")

    def key(self, digest: str) -> str:
        validate_digest(digest)
        return f"{self.prefix}/{digest[:2]}/{digest}"

    def put(self, content: bytes) -> str:
        from botocore.exceptions import ClientError

        digest = hashlib.sha256(content).hexdigest()
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=self.key(digest),
                Body=content,
                IfNoneMatch="*",
                Metadata={"sha256": digest},
            )
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
                raise HarnessError(
                    "STORAGE_WRITE_FAILED", "S3 artifact upload failed.", status=503, retryable=True
                ) from error
            self.get(digest)
        return digest

    def get(self, digest: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self.key(digest))
            with response["Body"] as body:
                return checked_bytes(digest, body.read())
        except ClientError as error:
            raise HarnessError(
                "STORAGE_READ_FAILED",
                "S3 artifact retrieval failed.",
                status=503,
                retryable=True,
                details={"digest": digest},
            ) from error
