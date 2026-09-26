"""Prepare one fresh harder-target attempt; review and paid launch stay separate.

The cooperative phase is prepared only after the calibration and every new retired
attempt have fully settled. This script never approves a target or calls a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
from decimal import Decimal
from pathlib import Path

from physharness.bootstrap import build_service
from physharness.config import Settings
from physharness.domain import CampaignCreate, ModelConfiguration, Principal, ResourceEnvelope
from physharness.run_control import RunPlan, TargetInput, prepare_run
from physharness.storage import Database
from physharness.verification.boundary import LinuxQualification, ResourceProfile, safe_read
from physharness.verification.preparation import create_problem_bundle, prepare_environment
from physharness.verification.registry import VerifierRegistry
from physharness.verification.resource_policy import parse_profile

ROOT = Path(__file__).resolve().parents[2]
STATE_PARENT = ROOT / ".state"
NEW_CEILING = Decimal("52")


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("x") as stream:
        os.chmod(path, 0o600)
        stream.write(content)


def remaining_ceiling(prior_spends: list[Decimal]) -> Decimal:
    if any(not value.is_finite() or value < 0 for value in prior_spends):
        raise ValueError("invalid prior budget entry")
    remaining = NEW_CEILING - sum(prior_spends, Decimal(0))
    if remaining <= 0:
        raise ValueError("new pilot budget exhausted")
    return remaining


def build_plan(attempt: dict, spec: dict) -> RunPlan:
    cooperative = attempt["phase"] == "cooperative"
    if attempt["phase"] not in {"calibration", "cooperative"}:
        raise ValueError("unknown attempt phase")
    models = [
        ModelConfiguration(
            runtime="responses",
            model="gpt-6-sol",
            parameters={"reasoning": {"effort": "high"}},
        )
        for _ in range(2 if cooperative else 1)
    ]
    return RunPlan(
        run_id=attempt["label"],
        project_id=attempt["project_id"],
        campaign=CampaignCreate(
            title=spec["title"], objective=spec["informal_statement"], programs=["classical"]
        ),
        target=TargetInput(
            title=spec["title"],
            program="classical",
            informal_statement=spec["informal_statement"],
            formal_source_file="Challenge.lean",
            environment_file="environment.json",
            assumptions=spec.get("assumptions", []),
            definitions=spec.get("definitions", {}),
            source=spec.get("source") or spec.get("provenance", ""),
            target_theorem=spec.get("target_theorem", "physics_target"),
            definition_holes=False,
        ),
        models=models,
        budget=ResourceEnvelope(
            max_cost_usd=attempt["ceiling_usd"],
            max_concurrency=4 if cooperative else 1,
            max_runtime_seconds=7200,
            max_tokens=None,
        ),
        policy="independent",
        sharing="ideas" if cooperative else "none",
        runtime_limits={
            "max_context_tokens": 256000,
            "max_output_tokens": 64000,
            "max_total_tokens": None,
            "max_turns": 1000,
            "timeout_seconds": 7200,
        },
        execution_profile="formal-research",
        context_profile="research",
    )


def _initialize_identity(attempt: dict) -> None:
    private = Path(attempt["private_directory"])
    private.mkdir(parents=True, exist_ok=False, mode=0o700)
    identities = {}
    for role in ("researcher", "reviewer", "operator", "publisher"):
        token = secrets.token_urlsafe(48)
        identities[token] = Principal(
            id=f"{attempt['label']}-{role}", project_id=attempt["project_id"], role=role
        ).model_dump(mode="json")
        write_private(private / f"{role}.token", token + "\n")
    write_private(private / "auth.json", json.dumps(identities, separators=(",", ":")))
    Database(attempt["database_url"]).create_schema()


def _prepare_attempt(
    attempt: dict, spec: dict, environment_bytes: bytes, challenge: bytes, project_directory: Path
) -> dict:
    _initialize_identity(attempt)
    private = Path(attempt["private_directory"])
    plan_dir = private / "plan"
    plan_dir.mkdir(mode=0o700)
    write_private(plan_dir / "Challenge.lean", challenge.decode("utf-8"))
    write_private(plan_dir / "environment.json", environment_bytes.decode("utf-8"))
    settings = Settings(
        _env_prefix="HARDENING_PREP_CONFIG_ONLY_",
        mode="local",
        database_url=attempt["database_url"],
        artifact_root=Path(attempt["artifact_root"]),
        auth_file=private / "auth.json",
        auto_create_schema=False,
    )
    actor = settings.auth_tokens[(private / "researcher.token").read_text().strip()]
    service = build_service(settings)
    preparation = prepare_run(service, actor, build_plan(attempt, spec), plan_dir)
    problem = service.get_record("problem", preparation["problem_id"], actor)
    bundle_directory = private / "bundle"
    manifest_sha = create_problem_bundle(
        bundle_directory,
        problem=problem,
        environment_bytes=environment_bytes,
        project_directory=project_directory,
    )
    return {
        "label": attempt["label"],
        "project_id": attempt["project_id"],
        "experiment_id": preparation["experiment_id"],
        "problem_revision_id": problem["id"],
        "target_digest": problem["target_digest"],
        "challenge_sha256": preparation["challenge_sha256"],
        "environment_digest": preparation["environment_digest"],
        "manifest_sha256": manifest_sha,
        "bundle_directory": str(bundle_directory),
        "review_status": preparation["review_status"],
        "model_calls": preparation["model_calls"],
    }


def prepare_phase(spec: dict, phase: str, *, prior_manifest_path: Path | None = None) -> dict:
    if phase not in {"calibration", "cooperative"}:
        raise ValueError("unknown phase")
    state = Path(spec["state_root"])
    if not state.is_absolute() or not state.resolve().is_relative_to(STATE_PARENT.resolve()):
        raise ValueError("private state root must be inside this workspace")
    challenge_path = Path(spec["challenge_file"])
    challenge = safe_read(challenge_path.parent, challenge_path.name)
    if hashlib.sha256(challenge).hexdigest() != spec["challenge_sha256"]:
        raise ValueError("exact challenge hash changed")
    environment_bytes = prepare_environment(
        Path(spec["image_metadata_path"]),
        image_metadata_sha256=spec["image_metadata_sha256"],
        project_directory=Path(spec["project_directory"]),
        project_files=spec["project_files"],
    )
    from physharness.verification.boundary import Environment

    environment = Environment.model_validate_json(environment_bytes)
    if environment.image != spec["verifier_image_digest"]:
        raise ValueError("pinned verifier image differs from environment metadata")
    earlier = []
    retired = []
    if phase == "cooperative":
        if prior_manifest_path is None:
            raise ValueError("cooperative preparation requires settled calibration manifest")
        import pilot_runner

        prior = pilot_runner.load_manifest(prior_manifest_path)
        if prior["phase"] != "calibration" or Path(prior_manifest_path).parent != state:
            raise ValueError("prior calibration scope changed")
        for key, expected in (
            ("challenge_sha256", spec["challenge_sha256"]),
            ("environment_digest", hashlib.sha256(environment_bytes).hexdigest()),
            ("worker_image_digest", spec["worker_image_digest"]),
            ("verifier_image_digest", spec["verifier_image_digest"]),
            ("source_scope_sha256", spec["source_scope_sha256"]),
        ):
            if prior[key] != expected:
                raise ValueError("prior target or image freeze changed")
        earlier = prior["attempts"]
        retired = prior["retired_attempts"]
        spent = pilot_runner.settled_prior_spend(prior)
        ceiling = remaining_ceiling([spent])
    else:
        if prior_manifest_path is not None:
            raise ValueError("calibration must start with a fresh phase")
        ceiling = Decimal("14")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    label = spec.get("label", f"hardening-{phase}-1")
    if not label or any(a["label"] == label for a in [*earlier, *retired]):
        raise ValueError("attempt label must be fresh")
    private = state / "attempts" / label
    attempt = {
        "label": label,
        "phase": phase,
        "sharing": "ideas" if phase == "cooperative" else "none",
        "ceiling_usd": format(ceiling, "f"),
        "experiment_id": "pending",
        "project_id": label,
        "target_digest": "pending",
        "private_directory": str(private),
        "database_url": f"sqlite:///{private / 'harness.db'}",
        "artifact_root": str(private / "artifacts"),
        "status_file": str(private / "status.json"),
        "result_file": str(private / "result.json"),
    }
    record = _prepare_attempt(
        attempt, spec["target"], environment_bytes, challenge, Path(spec["project_directory"])
    )
    attempt["experiment_id"] = record["experiment_id"]
    attempt["target_digest"] = record["target_digest"]
    manifest = {
        "version": 2,
        "pilot": "hardening-final-2026-09-24",
        "phase": phase,
        "prior_spent_usd": "43.762893",
        "aggregate_ceiling_usd": "100",
        "new_reservation_ceiling_usd": "52",
        "challenge_sha256": spec["challenge_sha256"],
        "challenge_file": str(challenge_path),
        "environment_digest": hashlib.sha256(environment_bytes).hexdigest(),
        "worker_image_digest": spec["worker_image_digest"],
        "verifier_image_digest": spec["verifier_image_digest"],
        "docker_host": spec["docker_host"],
        "tmp_directory": str(state / "tmp"),
        "registry": str(state / f"registry-{phase}.json"),
        "model_prices_file": spec["model_prices_file"],
        "worker_qualification_file": spec["worker_qualification_file"],
        "source_qualification_file": spec["source_qualification_file"],
        "source_scope_sha256": spec["source_scope_sha256"],
        "deployment_decision_file": str(state / f"deployment-decision-{phase}.json"),
        "global_lock_file": str(state / "launcher.lock"),
        "attempts": [*earlier, attempt],
        "retired_attempts": retired,
    }
    (state / "tmp").mkdir(exist_ok=True, mode=0o700)
    manifest_path = state / f"manifest-{phase}.json"
    records_path = state / f"prepared-{phase}.json"
    write_private(manifest_path, json.dumps(manifest, separators=(",", ":")))
    write_private(records_path, json.dumps(record, separators=(",", ":")))
    return {
        "status": "prepared_pending_review",
        "phase": phase,
        "manifest": str(manifest_path),
        "prepared_record": str(records_path),
        "ceiling_usd": attempt["ceiling_usd"],
        "model_calls": 0,
    }


def assemble_registry(
    manifest: dict, record: dict, *, qualification_file: Path, resource_profile: Path
) -> dict:
    qualification = LinuxQualification.model_validate_json(qualification_file.read_bytes())
    profile_bytes = safe_read(resource_profile.parent, resource_profile.name)
    resources = ResourceProfile.model_validate(parse_profile(profile_bytes))
    profile_sha = hashlib.sha256(profile_bytes).hexdigest()
    if (
        qualification.image_digest != manifest["verifier_image_digest"]
        or qualification.resource_profile_source_sha256 != profile_sha
        or qualification.resource_profile_sha256 != resources.sha256
        or record["label"] != manifest["attempts"][-1]["label"]
    ):
        raise ValueError("qualification does not bind current image, resource profile or attempt")
    registry_path = Path(manifest["registry"])
    write_private(
        registry_path,
        json.dumps(
            {
                "protocol": "physharness-verifier-registry-v1",
                "entries": [
                    {
                        "problem_revision_id": record["problem_revision_id"],
                        "resource_profile": str(resource_profile),
                        "config": {
                            "bundle_directory": record["bundle_directory"],
                            "manifest_sha256": record["manifest_sha256"],
                            "resources": resources.model_dump(mode="json"),
                            "resource_profile_source_sha256": profile_sha,
                            "timeout_seconds": None,
                            "output_limit_bytes": None,
                            "qualification": qualification.model_dump(mode="json"),
                        },
                    }
                ],
            },
            separators=(",", ":"),
        ),
    )
    VerifierRegistry.from_file(registry_path)
    return {
        "status": "registry_prepared_pending_deployment_decision",
        "registry": str(registry_path),
        "registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "assemble-registry"))
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--phase", choices=("calibration", "cooperative"))
    parser.add_argument("--prior-manifest", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--qualification", type=Path)
    parser.add_argument("--resources", type=Path)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        if not args.spec or not args.phase:
            parser.error("prepare requires --spec and --phase")
        result = prepare_phase(
            json.loads(args.spec.read_text()), args.phase, prior_manifest_path=args.prior_manifest
        )
    else:
        if not all((args.manifest, args.record, args.qualification, args.resources)):
            parser.error(
                "assemble-registry requires --manifest, --record, --qualification, --resources"
            )
        result = assemble_registry(
            json.loads(args.manifest.read_text()),
            json.loads(args.record.read_text()),
            qualification_file=args.qualification,
            resource_profile=args.resources,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
