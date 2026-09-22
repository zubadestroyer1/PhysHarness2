"""Operator preparation and preflight; neither operation manufactures scientific review."""

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from .domain import (
    ArtifactCreate,
    CampaignCreate,
    ExperimentCreate,
    ModelConfiguration,
    ProblemCreate,
    Program,
    ResourceEnvelope,
    StrictModel,
    canonical_json,
    digest_json,
)
from .errors import HarnessError
from .execution import ExecutionError, ModelConfig, RuntimeLimits
from .execution.parameters import validate_responses_parameters
from .orchestration.pricing import ModelPrice
from .service import require_role
from .verification import VerificationRequest
from .verification.boundary import Environment


class TargetInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    program: Program
    informal_statement: str = Field(min_length=1, max_length=100000)
    formal_source_file: str = Field(min_length=1, max_length=1000)
    environment_file: str = Field(min_length=1, max_length=1000)
    assumptions: list[str] = Field(default_factory=list, max_length=1000)
    definitions: dict[str, str] = Field(default_factory=dict)
    source: str = Field(default="", max_length=20000)
    target_theorem: str = Field(default="target", min_length=1, max_length=500)
    definition_holes: bool = False


class RunPlan(StrictModel):
    version: Literal[1] = 1
    run_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$")
    project_id: str = Field(min_length=1, max_length=200)
    campaign: CampaignCreate
    target: TargetInput
    models: list[ModelConfiguration] = Field(min_length=1, max_length=100)
    budget: ResourceEnvelope
    policy: Literal["direct", "independent"] = "independent"
    sharing: Literal["none", "verified", "ideas"] = "verified"
    runtime_limits: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent(self):
        if self.target.program not in self.campaign.programs:
            raise ValueError("Target program is not included in the campaign")
        validate_runtime_inputs(self.models, self.runtime_limits)
        return self


def validate_runtime_inputs(models, limits):
    """Reject invalid execution contracts and credential fields before durable preparation."""
    reserved = {
        "apikey",
        "authorization",
        "password",
        "secret",
        "accesstoken",
        "refreshtoken",
        "clientsecret",
        "credentials",
        "headers",
        "extraheaders",
    }

    def no_credentials(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower().replace("_", "").replace("-", "") in reserved:
                    raise ValueError("Credentials must be supplied privately, outside run plans")
                no_credentials(item)
        elif isinstance(value, list):
            for item in value:
                no_credentials(item)

    RuntimeLimits.model_validate(limits)
    for model in models:
        config = model.model_dump() if isinstance(model, ModelConfiguration) else model
        parsed = ModelConfig(model=config["model"], parameters=config.get("parameters", {}))
        no_credentials(parsed.parameters)
        if config["runtime"] == "responses":
            try:
                validate_responses_parameters(parsed.parameters)
            except ExecutionError:
                raise ValueError("Invalid Responses parameter schema; values omitted") from None


def read_input(base_directory: Path, relative: str, limit: int) -> bytes:
    """Read bounded regular input beneath an explicit root without following child symlinks."""
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(p in {"..", "."} for p in path.parts):
        raise HarnessError("RUN_INPUT_PATH", "Run inputs must be relative files below the plan.")
    if "\\" in relative or "\x00" in relative:
        raise HarnessError("RUN_INPUT_PATH", "Run input path contains invalid characters.")
    descriptors = []
    try:
        parent = os.open(base_directory.resolve(), os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(parent)
        for component in path.parts[:-1]:
            parent = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            descriptors.append(parent)
        descriptor = os.open(
            path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )
        descriptors.append(descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise HarnessError("RUN_INPUT_LIMIT", "Run input must be a bounded regular file.")
        chunks, size = [], 0
        while block := os.read(descriptor, min(65536, limit + 1 - size)):
            chunks.append(block)
            size += len(block)
            if size > limit:
                raise HarnessError("RUN_INPUT_LIMIT", "Run input exceeds its byte limit.")
        return b"".join(chunks)
    except OSError:
        raise HarnessError(
            "RUN_INPUT_UNAVAILABLE",
            "Run input is missing, unreadable or contains a symlink.",
            remediation="Place regular source/environment files beneath the plan directory.",
        ) from None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def prepare_run(service, actor, plan: RunPlan, base_directory: Path) -> dict:
    require_role(actor, "researcher", "operator")
    if actor.project_id != plan.project_id:
        raise HarnessError("PROJECT_SCOPE", "Run plan belongs to another project.")
    # Validate every input before the first durable mutation. No source is executed here.
    source = read_input(base_directory, plan.target.formal_source_file, 100000)
    environment = read_input(base_directory, plan.target.environment_file, 500000)
    try:
        source_text = source.decode("utf-8")
        Environment.model_validate_json(environment)
        fields = plan.target.model_dump(exclude={"formal_source_file", "environment_file"})
        proposed = ProblemCreate(
            campaign_id="pending",
            formal_statement=source_text,
            environment_digest=hashlib.sha256(environment).hexdigest(),
            **fields,
        )
    except (UnicodeError, ValidationError):
        raise HarnessError(
            "RUN_INPUT_INVALID", "Source or environment schema is invalid."
        ) from None
    prefix = f"prepare:{plan.run_id}"
    campaign = service.create_campaign(plan.campaign, actor, prefix + ":campaign")
    problem = service.create_problem(
        proposed.model_copy(update={"campaign_id": campaign["id"]}),
        actor,
        prefix + ":problem",
    )
    experiment = service.create_experiment(
        ExperimentCreate(
            campaign_id=campaign["id"],
            problem_id=problem["id"],
            models=plan.models,
            budget=plan.budget,
            policy=plan.policy,
            sharing=plan.sharing,
            runtime_limits=plan.runtime_limits,
        ),
        actor,
        prefix + ":experiment",
    )
    provenance = {
        "plan": plan.model_dump(mode="json"),
        "challenge_sha256": hashlib.sha256(source).hexdigest(),
        "environment_digest": problem["environment_digest"],
        "target_digest": problem["target_digest"],
    }
    artifact = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            kind="run_preparation",
            media_type="application/json",
            content=canonical_json(provenance),
            provenance={"run_id": plan.run_id},
        ),
        actor,
        prefix + ":manifest",
    )
    current = service.get_record("problem", problem["id"], actor)
    return {
        "run_id": plan.run_id,
        "campaign_id": campaign["id"],
        "problem_id": problem["id"],
        "experiment_id": experiment["id"],
        "preparation_artifact_id": artifact["id"],
        "target_digest": problem["target_digest"],
        "challenge_sha256": provenance["challenge_sha256"],
        "environment_digest": problem["environment_digest"],
        "plan_digest": digest_json(provenance),
        "review_status": current["semantic_review"],
        "model_calls": 0,
    }


def run_preflight(service, actor, experiment_id, *, prices, environment, publication=True) -> dict:
    require_role(actor, "operator")
    experiment = service.get_record("experiment", experiment_id, actor)
    problem = service.get_record("problem", experiment["problem_id"], actor)
    blockers, observations = [], []

    def block(code, remediation):
        blockers.append({"code": code, "remediation": remediation})

    if experiment["status"] not in {"created", "queued", "running", "paused", "blocked"}:
        block("EXPERIMENT_TERMINAL", "Prepare a new experiment; this one has terminated.")
    if experiment["policy"] not in {"direct", "independent"}:
        block("SEARCH_POLICY_NOT_INTEGRATED", "Choose direct or independent for this runner.")
    if problem["semantic_review"] != "approved" or not problem.get("review_id"):
        block("TARGET_REVIEW_REQUIRED", "Have a reviewer record a decision on this exact target.")
    else:
        review = service.get_record("review", problem["review_id"], actor)
        if (
            review.get("decision") != "approved"
            or review.get("target_digest") != problem["target_digest"]
        ):
            block("TARGET_REVIEW_MISMATCH", "Review and target identities must agree.")
    if experiment["target_digest"] != problem["target_digest"] or problem["definition_holes"]:
        block("TARGET_NOT_FIXED", "Prepare a concrete target with reviewed definitions.")
    if not environment.get("OPENAI_API_KEY"):
        block("MODEL_CREDENTIAL_REQUIRED", "Supply OPENAI_API_KEY privately to the worker process.")
    try:
        validate_runtime_inputs(experiment["models"], experiment.get("runtime_limits", {}))
    except (ValueError, TypeError, KeyError):
        block("RUNTIME_CONFIG_INVALID", "Correct model parameters and runtime limits in a new run.")
    for config in experiment["models"]:
        if config["runtime"] != "responses":
            block(
                "RUNTIME_NOT_INTEGRATED",
                "Use the Responses worker until this adapter is qualified.",
            )
        try:
            ModelPrice.model_validate(prices[config["model"]])
        except (KeyError, ValidationError, TypeError):
            block(
                "MODEL_PRICE_REQUIRED",
                f"Configure recorded input/output prices for {config['model']}.",
            )
    verifier = service.verifier
    if verifier is None or not callable(getattr(verifier, "preflight", None)):
        block("VERIFIER_REQUIRED", "Configure the independent verifier and pinned bundle.")
    else:
        request = VerificationRequest(
            problem_revision_id=problem["id"],
            target_digest=problem["target_digest"],
            target_theorem=problem["target_theorem"],
            challenge_sha256=hashlib.sha256(problem["formal_statement"].encode()).hexdigest(),
            environment_digest=problem["environment_digest"],
            candidate_sha256=hashlib.sha256(b"").hexdigest(),
            candidate_source="",
            semantic_reviewed=problem["semantic_review"] == "approved",
            definition_holes=problem["definition_holes"],
            publication=publication,
        )
        checked = verifier.preflight(request)
        if checked.code != "configured_unprobed":
            block(checked.code, checked.remediation)
        observations.append({"component": "verifier", "code": checked.code, "executed": False})
    return {
        "status": "blocked" if blockers else "ready_for_live_attempt",
        "experiment_id": experiment_id,
        "problem_id": problem["id"],
        "target_digest": problem["target_digest"],
        "review_id": problem.get("review_id"),
        "blockers": blockers,
        "observations": observations,
        "model_calls": 0,
        "assurance": "none",
        "qualification": "preflight_only",
    }
