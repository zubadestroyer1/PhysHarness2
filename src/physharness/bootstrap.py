"""Service construction shared by API, workers and migration/bootstrap tooling."""

import hashlib
import json
from pathlib import Path

from .artifacts import LocalArtifactStore, S3ArtifactStore
from .config import ConfigurationError, Settings
from .service import HarnessService
from .storage import Database
from .verification import (
    ComparatorConfig,
    ComparatorVerifier,
    LinuxQualification,
    VerifierRegistry,
    resource_policy,
)
from .verification.boundary import ResourceProfile, safe_read
from .verification.resource_policy import parse_profile


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
        path = settings.verification_resources
        try:
            resource_bytes = safe_read(path.parent, path.name)
            resources = ResourceProfile.model_validate(parse_profile(resource_bytes))
        except (OSError, ValueError, TypeError):
            raise ConfigurationError(
                "Invalid verifier resource profile; check the configured file, "
                "schema and bounds. File contents were omitted."
            ) from None
        resource_source_sha256 = hashlib.sha256(resource_bytes).hexdigest()
        if (
            resources.sha256 != qualification.resource_profile_sha256
            or resource_source_sha256 != qualification.resource_profile_source_sha256
        ):
            raise ConfigurationError(
                "Verifier resource profile source does not match qualification; collect new "
                "evidence and obtain review for the exact resource profile."
            )
        if resource_policy.policy_digest() != qualification.resource_policy_sha256:
            raise ConfigurationError(
                "Verifier resource policy does not match qualification; collect new evidence "
                "and obtain review for the exact policy implementation."
            )
        verifier = ComparatorVerifier(
            ComparatorConfig(
                bundle_directory=settings.verification_bundle,
                manifest_sha256=settings.verification_manifest_sha256,
                qualification=qualification,
                resources=resources,
                resource_profile_source_sha256=resource_source_sha256,
            )
        )
    return HarnessService(database, artifacts, verifier)
