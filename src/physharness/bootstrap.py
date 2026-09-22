"""Service construction shared by API, workers and migration/bootstrap tooling."""

import json
from pathlib import Path

from .artifacts import LocalArtifactStore, S3ArtifactStore
from .config import Settings
from .service import HarnessService
from .storage import Database
from .verification import ComparatorConfig, ComparatorVerifier, LinuxQualification, VerifierRegistry


def build_service(settings: Settings) -> HarnessService:
    if settings.database_url.startswith("sqlite:///") and ":memory:" not in settings.database_url:
        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(
            parents=True, exist_ok=True
        )
    database = Database(settings.database_url)
    if settings.auto_create_schema:
        database.create_schema()
    artifacts = (
        S3ArtifactStore(settings.artifact_bucket)
        if settings.artifact_bucket
        else LocalArtifactStore(settings.artifact_root)
    )
    verifier = None
    values = [
        settings.verification_bundle,
        settings.verification_manifest_sha256,
        settings.verification_qualification,
    ]
    if settings.verification_registry:
        if any(values):
            raise ValueError(
                "Verifier registry and single-bundle configuration cannot be combined."
            )
        verifier = VerifierRegistry.from_file(settings.verification_registry)
    elif any(values):
        if not all(values):
            raise ValueError(
                "Verifier configuration needs bundle, manifest hash and qualification evidence."
            )
        qualification = LinuxQualification.model_validate(
            json.loads(settings.verification_qualification.read_text())
        )
        verifier = ComparatorVerifier(
            ComparatorConfig(
                bundle_directory=settings.verification_bundle,
                manifest_sha256=settings.verification_manifest_sha256,
                qualification=qualification,
            )
        )
    return HarnessService(database, artifacts, verifier)
