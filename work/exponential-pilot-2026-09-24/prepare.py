"""Prepare fresh private attempts and exact verifier routes without scientific review.

The operator supplies an exact challenge and pinned project/image inputs. The
reviewer must separately decide each stored problem revision; this script never
sets semantic_review or launches a worker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
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


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("x") as stream:
        os.chmod(path, 0o600)
        stream.write(content)


def build_plan(attempt: dict, spec: dict) -> RunPlan:
    count = 1 if attempt["phase"] == "calibration" else 2
    models = [
        ModelConfiguration(
            runtime="responses",
            model="gpt-6-sol",
            parameters={"reasoning": {"effort": "high"}},
        )
        for _ in range(count)
    ]
    return RunPlan(
        run_id=attempt["label"],
        project_id=attempt["project_id"],
        campaign=CampaignCreate(
            title=spec["title"],
            objective=spec["informal_statement"],
            programs=["classical"],
        ),
        target=TargetInput(
            title=spec["title"],
            program="classical",
            informal_statement=spec["informal_statement"],
            formal_source_file="Challenge.lean",
            environment_file="environment.json",
            assumptions=spec.get("assumptions", []),
            definitions=spec.get("definitions", {}),
            source=spec.get("source", ""),
            target_theorem=spec.get("target_theorem", "physics_target"),
            definition_holes=False,
        ),
        models=models,
        budget=ResourceEnvelope(
            max_cost_usd=attempt["ceiling_usd"],
            max_concurrency=count,
            max_runtime_seconds=2700,
            max_tokens=None,
        ),
        policy="independent",
        sharing=attempt["sharing"],
        runtime_limits={
            "max_context_tokens": 256000,
            "max_output_tokens": 64000,
            "max_total_tokens": None,
            "max_turns": 1000,
            "timeout_seconds": 2700,
        },
        execution_profile="formal-research",
        context_profile="research",
    )


def initialize_identity(attempt: dict) -> None:
    private = Path(attempt["private_directory"])
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(private.iterdir()):
        raise ValueError("Fresh attempt directory required; no credential or DB overwrite")
    identities = {}
    for role in ("researcher", "reviewer", "operator", "publisher"):
        token = secrets.token_urlsafe(48)
        identities[token] = Principal(
            id=f"{attempt['label']}-{role}",
            project_id=attempt["project_id"],
            role=role,
        ).model_dump(mode="json")
        write_private(private / f"{role}.token", token + "\n")
    write_private(private / "auth.json", json.dumps(identities, separators=(",", ":")))
    Database(attempt["database_url"]).create_schema()


def prepare_attempt(
    attempt: dict, spec: dict, environment_bytes: bytes, challenge: bytes, project_directory: Path
) -> dict:
    private = Path(attempt["private_directory"])
    initialize_identity(attempt)
    plan_dir = private / "plan"
    plan_dir.mkdir(mode=0o700)
    write_private(plan_dir / "Challenge.lean", challenge.decode("utf-8"))
    write_private(plan_dir / "environment.json", environment_bytes.decode("utf-8"))
    settings = Settings(
        _env_prefix="EXPONENTIAL_PREP_CONFIG_ONLY_",
        mode="local",
        database_url=attempt["database_url"],
        artifact_root=Path(attempt["artifact_root"]),
        auth_file=private / "auth.json",
        auto_create_schema=False,
    )
    token = (private / "researcher.token").read_text().strip()
    actor = settings.auth_tokens[token]
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


def prepare_replacement(
    retired: dict,
    *,
    label: str,
    private_directory: Path,
    spec: dict,
    environment_bytes: bytes,
    challenge: bytes,
    project_directory: Path,
    challenge_sha256: str,
    environment_digest: str,
) -> dict:
    """Prepare a fresh slot replacement; the operator separately updates the manifest.

    The old attempt is left intact for ledger accounting. The supplied challenge and
    environment must match the already reviewed freeze before any files are made.
    """
    if (
        not label
        or label == retired["label"]
        or not private_directory.is_absolute()
        or private_directory.resolve() == Path(retired["private_directory"]).resolve()
        or private_directory.exists()
    ):
        raise ValueError("Replacement requires a fresh label and private directory")
    if (
        hashlib.sha256(challenge).hexdigest() != challenge_sha256
        or hashlib.sha256(environment_bytes).hexdigest() != environment_digest
    ):
        raise ValueError("Replacement does not match reviewed target and environment")
    attempt = {
        **retired,
        "label": label,
        "project_id": label,
        "experiment_id": "pending",
        "target_digest": "pending",
        "private_directory": str(private_directory),
        "database_url": f"sqlite:///{private_directory / 'harness.db'}",
        "artifact_root": str(private_directory / "artifacts"),
        "status_file": str(private_directory / "status.json"),
        "result_file": str(private_directory / "result.json"),
    }
    record = prepare_attempt(attempt, spec, environment_bytes, challenge, project_directory)
    attempt["experiment_id"] = record["experiment_id"]
    attempt["target_digest"] = record["target_digest"]
    return {"attempt": attempt, "prepared_record": record}


def prepare_all(spec: dict) -> dict:
    state = Path(spec["state_root"])
    challenge_path = Path(spec["challenge_file"])
    challenge = safe_read(challenge_path.parent, challenge_path.name)
    if hashlib.sha256(challenge).hexdigest() != spec["challenge_sha256"]:
        raise ValueError("Exact challenge hash changed")
    environment_bytes = prepare_environment(
        Path(spec["image_metadata_path"]),
        image_metadata_sha256=spec["image_metadata_sha256"],
        project_directory=Path(spec["project_directory"]),
        project_files=spec["project_files"],
    )
    from physharness.verification.boundary import Environment

    environment = Environment.model_validate_json(environment_bytes)
    if environment.image != spec["verifier_image_digest"]:
        raise ValueError("Pinned verifier image differs from environment metadata")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    attempts = []
    details = []
    for index in range(7):
        label = f"exponential-{'calibration' if index < 3 else 'comparison'}-{index + 1}"
        private = state / "attempts" / label
        attempt = {
            "label": label,
            "phase": "calibration" if index < 3 else "comparison",
            "sharing": "none" if index < 3 or index in (3, 6) else "ideas",
            "ceiling_usd": "12" if index < 3 else "14",
            "experiment_id": "pending",
            "project_id": label,
            "target_digest": "pending",
            "private_directory": str(private),
            "database_url": f"sqlite:///{private / 'harness.db'}",
            "artifact_root": str(private / "artifacts"),
            "status_file": str(private / "status.json"),
            "result_file": str(private / "result.json"),
        }
        record = prepare_attempt(
            attempt, spec["target"], environment_bytes, challenge, Path(spec["project_directory"])
        )
        attempt["experiment_id"] = record["experiment_id"]
        attempt["target_digest"] = record["target_digest"]
        attempts.append(attempt)
        details.append(record)
    manifest = {
        "version": 1,
        "prior_spent_usd": "3.658018",
        "aggregate_ceiling_usd": "100",
        "new_reservation_ceiling_usd": "92",
        "challenge_sha256": spec["challenge_sha256"],
        "challenge_file": str(challenge_path),
        "environment_digest": hashlib.sha256(environment_bytes).hexdigest(),
        "worker_image_digest": spec["worker_image_digest"],
        "verifier_image_digest": spec["verifier_image_digest"],
        "docker_host": spec["docker_host"],
        "tmp_directory": str(state / "tmp"),
        "registry": str(state / "verifier-registry.json"),
        "model_prices_file": spec["model_prices_file"],
        "worker_qualification_file": spec["worker_qualification_file"],
        "calibration_decision_file": str(state / "calibration-decision.json"),
        "deployment_decision_file": str(state / "deployment-decision.json"),
        "global_lock_file": str(state / "launcher.lock"),
        "attempts": attempts,
        "retired_attempts": [],
    }
    (state / "tmp").mkdir(mode=0o700, exist_ok=True)
    write_private(state / "manifest.json", json.dumps(manifest, separators=(",", ":")))
    write_private(state / "prepared-records.json", json.dumps(details, separators=(",", ":")))
    return {
        "status": "prepared_pending_review",
        "manifest": str(state / "manifest.json"),
        "prepared_records": str(state / "prepared-records.json"),
        "attempt_count": len(attempts),
    }


def assemble_registry(
    manifest: dict, records: list[dict], *, qualification_file: Path, resource_profile: Path
) -> dict:
    """Write exact routes from externally supplied qualification; no approval is inferred."""
    qualification = LinuxQualification.model_validate_json(qualification_file.read_bytes())
    profile_bytes = safe_read(resource_profile.parent, resource_profile.name)
    resources = ResourceProfile.model_validate(parse_profile(profile_bytes))
    profile_sha = hashlib.sha256(profile_bytes).hexdigest()
    if (
        qualification.image_digest != manifest["verifier_image_digest"]
        or qualification.resource_profile_source_sha256 != profile_sha
        or qualification.resource_profile_sha256 != resources.sha256
    ):
        raise ValueError("Qualification does not bind selected image and resource profile")
    entries = []
    by_label = {record["label"]: record for record in records}
    for attempt in manifest["attempts"]:
        record = by_label[attempt["label"]]
        entries.append(
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
        )
    registry_path = Path(manifest["registry"])
    write_private(
        registry_path,
        json.dumps(
            {
                "protocol": "physharness-verifier-registry-v1",
                "entries": entries,
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
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--records", type=Path)
    parser.add_argument("--qualification", type=Path)
    parser.add_argument("--resources", type=Path)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        if not args.spec:
            parser.error("prepare requires --spec")
        result = prepare_all(json.loads(args.spec.read_text()))
    else:
        if not all((args.manifest, args.records, args.qualification, args.resources)):
            parser.error(
                "assemble-registry requires --manifest, --records, --qualification and --resources"
            )
        result = assemble_registry(
            json.loads(args.manifest.read_text()),
            json.loads(args.records.read_text()),
            qualification_file=args.qualification,
            resource_profile=args.resources,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
