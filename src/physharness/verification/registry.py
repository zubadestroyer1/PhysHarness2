"""Operator-owned exact revision routing for independently qualified proof checkers."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Literal

from pydantic import Field, model_validator

from .boundary import (
    ComparatorConfig,
    ComparatorVerifier,
    Contract,
    EngineeringRequest,
    Manifest,
    ResourceProfile,
    VerificationRequest,
    digest,
    outcome,
    safe_read,
)
from .resource_policy import parse_profile


class RegistryEntry(Contract):
    problem_revision_id: str = Field(min_length=1, max_length=256)
    resource_profile: Path
    config: ComparatorConfig


class RegistryDocument(Contract):
    protocol: Literal["physharness-verifier-registry-v1"]
    entries: list[RegistryEntry] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_revisions(self):
        revisions = [entry.problem_revision_id for entry in self.entries]
        if len(set(revisions)) != len(revisions):
            raise ValueError("Each problem revision must have exactly one verifier route")
        return self


class VerifierRegistry:
    def __init__(self, document: RegistryDocument):
        if not isinstance(document, RegistryDocument):
            raise TypeError("A validated operator registry is required")
        routes = {}
        for entry in document.entries:
            config = entry.config
            if not config.bundle_directory.is_absolute():
                raise ValueError("Registry bundle directories must be absolute")
            path = entry.resource_profile
            if not path.is_absolute():
                raise ValueError("Registry resource profile paths must be absolute")
            if any(parent.is_symlink() for parent in path.parents):
                raise ValueError("Registry resource profile paths must not contain symlinks")
            try:
                profile_bytes = safe_read(path.parent, path.name)
                resources = ResourceProfile.model_validate(parse_profile(profile_bytes))
            except (OSError, ValueError, TypeError) as exc:
                raise ValueError("Invalid registry resource profile file or bounds") from exc
            if (
                digest(profile_bytes) != config.resource_profile_source_sha256
                or digest(profile_bytes) != config.qualification.resource_profile_source_sha256
                or resources.sha256 != config.resources.sha256
                or resources.sha256 != config.qualification.resource_profile_sha256
            ):
                raise ValueError(
                    "Registry resource profile source differs from configuration or qualification"
                )
            manifest_bytes = safe_read(config.bundle_directory, "manifest.json")
            if digest(manifest_bytes) != config.manifest_sha256:
                raise ValueError("Registry manifest digest mismatch")
            manifest = Manifest.model_validate_json(manifest_bytes)
            if manifest.problem_revision_id != entry.problem_revision_id:
                raise ValueError("Registry route differs from the pinned manifest revision")
            verifier = ComparatorVerifier(config)
            # Validate all structural bundle/policy pins without inventing semantic review
            # or running a candidate. Actual scientific requests additionally bind the selector.
            verifier._bundle(
                EngineeringRequest(
                    problem_revision_id=manifest.problem_revision_id,
                    target_digest=manifest.target_digest,
                    challenge_sha256=manifest.challenge_sha256,
                    environment_digest=manifest.environment_digest,
                    candidate_sha256=digest(b""),
                    candidate_source="",
                )
            )
            routes[entry.problem_revision_id] = verifier
        self._routes = MappingProxyType(routes)

    @classmethod
    def from_file(cls, path: Path) -> VerifierRegistry:
        path = Path(path)
        data = safe_read(path.parent, path.name)
        if len(data) > 2_000_000:
            raise ValueError("Verifier registry exceeds 2 MB")
        return cls(RegistryDocument.model_validate_json(data))

    def _route(self, request):
        if not isinstance(request, VerificationRequest):
            raise TypeError("Registry routes scientific VerificationRequest inputs only")
        return self._routes.get(request.problem_revision_id)

    @staticmethod
    def _unknown(request):
        return outcome(
            request,
            "blocked",
            "verifier_revision_unconfigured",
            "No trusted verifier bundle is registered for this exact revision.",
            "Prepare and pin this revision's trusted bundle in the operator registry.",
        )

    def verify(self, request: VerificationRequest):
        verifier = self._route(request)
        return verifier.verify(request) if verifier else self._unknown(request)

    def preflight(self, request: VerificationRequest):
        verifier = self._route(request)
        return verifier.preflight(request) if verifier else self._unknown(request)
