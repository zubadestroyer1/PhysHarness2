"""Offline, scoped engineering evidence checks. This module cannot approve deployment.

Hashes establish identity, not report authenticity. Operator review must establish
who collected the observations and whether the runtime was the intended deployment.
No candidate, subprocess, verifier, database write or approval is invoked here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import UUID
from xml.etree import ElementTree as ET

from pydantic import Field, model_validator

from . import resource_policy as resource_policy
from .boundary import (
    SHA256,
    Contract,
    Environment,
    ImageDigest,
    ResourceProfile,
    VerificationOutcome,
    digest,
    seccomp_digest,
)
from .bundles import canonical_json, project_path

MATRIX_PATH = "formal/qualification-matrix.json"
MAX_FILE_BYTES = 16_000_000
Mode = Literal["kernel", "independent_kernel"]


class EvidenceError(ValueError):
    """Invalid or stale engineering evidence; never a mathematical refutation."""


def _relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or path.as_posix() != name
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise EvidenceError("Evidence paths must be normalized relative paths")
    return path


class EvidenceFile(Contract):
    path: str = Field(min_length=1, max_length=1000)
    sha256: SHA256

    @model_validator(mode="after")
    def safe_path(self):
        _relative(self.path)
        return self


class SuiteEvidence(Contract):
    suite_id: str
    report: EvidenceFile


class BoundaryEvidence(Contract):
    report: EvidenceFile


class RegressionEvidence(Contract):
    report: EvidenceFile


class Gap(Contract):
    id: str
    reason: str


class SuiteRequirement(Contract):
    id: str
    fixture: str
    modes: list[Mode]
    required_cases: list[str]


class RegressionRequirement(Contract):
    id: str
    nodeids: list[str]


BOUNDARY_CHECKS = frozenset(
    [
        "nonroot",
        "no_capabilities",
        "no_new_privileges",
        "seccomp_filter",
        "unix_socket_denied",
        "inet_socket_denied",
        "trusted_canary_intact",
        "candidate_canary_intact",
        "trusted_write_denied",
        "candidate_write_denied",
        "root_write_denied",
        "work_write_control",
        "tmp_write_control",
        "no_docker_socket",
        "container_configuration",
        "memory_events_readable",
    ]
)


class BoundaryRequirement(Contract):
    id: Literal["fixed-boundary"]
    script: Literal["infra/probe_verifier_boundary.py"]
    required_checks: list[str]

    @model_validator(mode="after")
    def fixed_controls(self):
        if set(self.required_checks) != BOUNDARY_CHECKS or len(self.required_checks) != len(
            BOUNDARY_CHECKS
        ):
            raise ValueError("Every fixed boundary observation and positive control is required")
        return self


class Matrix(Contract):
    version: Literal[1]
    id: Literal["linux-comparator-wave01-v1"]
    scope: str
    suites: list[SuiteRequirement]
    regression_groups: list[RegressionRequirement]
    boundary_probe: BoundaryRequirement
    input_files: list[str]
    review_gates: list[Gap]
    coverage_gaps: list[Gap]

    @model_validator(mode="after")
    def required_coverage(self):
        if {suite.id for suite in self.suites} != {"core", "library"} or len(self.suites) != 2:
            raise ValueError("Both fixed engineering suites are required")
        for suite in self.suites:
            _relative(suite.fixture)
            if set(suite.modes) != {"kernel", "independent_kernel"} or len(suite.modes) != 2:
                raise ValueError("Both kernel modes are required")
            if not suite.required_cases or len(set(suite.required_cases)) != len(
                suite.required_cases
            ):
                raise ValueError("Unique required case IDs are required")
        ids = [group.id for group in self.regression_groups]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("Unique regression groups are required")
        for group in self.regression_groups:
            if not group.nodeids or len(set(group.nodeids)) != len(group.nodeids):
                raise ValueError("Unique regression test identities are required")
            for node in group.nodeids:
                if not re.fullmatch(
                    r"tests/[a-z0-9_]+\.py::test_[a-z0-9_]+(?:\[[a-zA-Z0-9_-]+\])?", node
                ):
                    raise ValueError("Regression nodes must identify specific repository tests")
        if "process-exit" not in {gap.id for gap in self.coverage_gaps}:
            raise ValueError("The security-filtered process-exit coverage gap must remain explicit")
        return self


class DeploymentScope(Contract):
    protocol: Literal["physharness-qualification-scope-v1"] = "physharness-qualification-scope-v1"
    image_metadata: EvidenceFile
    runtime_identity: EvidenceFile
    resource_profile_file: EvidenceFile
    resources: ResourceProfile
    resource_profile_sha256: SHA256
    image_digest: ImageDigest
    launcher_sha256: SHA256
    driver_sha256: SHA256
    seccomp_sha256: SHA256
    checker_versions: dict[str, str]
    binaries: dict[str, SHA256]
    inputs: dict[str, SHA256]

    @property
    def sha256(self) -> str:
        return digest(canonical_json(self.model_dump(mode="json")))


class Check(Contract):
    id: str
    status: Literal["observed", "missing", "invalid"]
    detail: str
    evidence_sha256: str | None = None


class ReviewPacket(Contract):
    protocol: Literal["physharness-deployment-review-packet-v1"] = (
        "physharness-deployment-review-packet-v1"
    )
    purpose: Literal["deployment_review_packet"] = "deployment_review_packet"
    scope_sha256: SHA256
    scope: DeploymentScope
    mechanical_status: Literal["satisfied", "incomplete", "invalid"]
    checks: list[Check]
    coverage_gaps: list[Gap]
    review_gates: list[Gap]
    production_qualified: Literal[False] = False
    deployment_approval: Literal["pending"] = "pending"
    scientific_review: Literal["not_provided"] = "not_provided"
    provenance_limit: str = (
        "Input hashes cannot authenticate reports or grant authority; "
        "an authorized human must review their provenance."
    )


def render_review_packet(packet: ReviewPacket) -> str:
    """Render the same pending assessment for a human reviewer; create no approval."""
    # JSON encoding keeps untrusted diagnostic/path newlines inside the code block.
    payload = json.dumps(packet.model_dump(mode="json"), indent=2, ensure_ascii=True)
    return (
        "# Scoped verifier deployment review\n\n"
        "Deployment approval: pending\n\nProduction qualified: false\n\n"
        f"Mechanical checks: {packet.mechanical_status}\n\n"
        "The packet identifies observations and remaining gaps. Hash agreement does not "
        "authenticate their collector or approve a deployment or scientific target.\n\n"
        "```json\n" + payload + "\n```\n"
    )


def _read(root: Path, name: str, expected: str | None = None) -> bytes:
    path = root
    for part in _relative(name).parts:
        path = path / part
        if path.is_symlink():
            raise EvidenceError(f"Symlink evidence is forbidden: {name}")
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise EvidenceError(f"Missing, nonregular or oversized evidence: {name}")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES or (expected is not None and digest(data) != expected):
        raise EvidenceError(f"Evidence digest mismatch or size limit: {name}")
    return data


def _json(data: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    result = json.loads(data, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise EvidenceError("Evidence must be a JSON object")
    return result


def load_matrix(repository: Path) -> Matrix:
    return Matrix.model_validate(_json(_read(Path(repository), MATRIX_PATH)))


def validate_runtime_identity(data: bytes) -> dict:
    """Validate the shape of a separately observed runtime snapshot, not its origin."""
    runtime = _json(data)
    if (
        runtime.get("purpose") != "engineering_runtime_observation"
        or runtime.get("production_qualified") is not False
        or runtime.get("OSType") != "linux"
    ):
        raise EvidenceError(
            "A Linux engineering runtime observation without qualification is required"
        )
    for field in [
        "KernelVersion",
        "Architecture",
        "ServerVersion",
        "CgroupVersion",
        "DefaultRuntime",
    ]:
        if not isinstance(runtime.get(field), str) or not runtime[field].strip():
            raise EvidenceError(f"Runtime identity is missing {field}")
    return runtime


def _fixture(root: Path, suite: SuiteRequirement) -> dict:
    fixture = _json(_read(root, suite.fixture))
    if fixture.get("schema_version") != 1 or fixture.get("purpose") != "engineering_smoke":
        raise EvidenceError("Expected a versioned engineering fixture manifest")
    cases = fixture.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 100:
        raise EvidenceError("A bounded, nonempty engineering suite is required")
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)) or set(ids) != set(suite.required_cases):
        raise EvidenceError("Fixture identities differ from the required matrix")
    statuses = {(case["expected_status"], case["expected_code"]) for case in cases}
    if statuses != {("verified", "kernel_checked"), ("blocked", "comparator_failed")}:
        raise EvidenceError(
            "Each suite requires successful controls and causal comparator failures"
        )
    for case in cases:
        markers = case.get("required_diagnostic_substrings", [])
        if (
            not isinstance(markers, list)
            or len(markers) > 16
            or (case["expected_status"] == "blocked" and not markers)
            or any(
                not isinstance(item, str) or not item.strip() or len(item) > 2000
                for item in markers
            )
        ):
            raise EvidenceError("Negative fixtures require bounded causal diagnostics")
    projects = fixture.get("project_files")
    if not isinstance(projects, dict) or not projects or len(projects) > 1000:
        raise EvidenceError("Pinned trusted project files are required")
    for name in projects:
        project_path(name)
    if not {"lakefile.toml", "lakefile.lean"} & projects.keys():
        raise EvidenceError("A trusted Lake configuration is required")
    return fixture


def capture_scope(
    repository: Path,
    *,
    image_metadata: EvidenceFile,
    runtime_identity: EvidenceFile,
    resource_profile: EvidenceFile | None = None,
) -> DeploymentScope:
    """Snapshot current trusted inputs before scheduled runs; never probe a runtime."""
    root = Path(repository).resolve()
    matrix = load_matrix(root)
    resource_profile = resource_profile or EvidenceFile(
        path="formal/verifier-resources.json",
        sha256=digest(_read(root, "formal/verifier-resources.json")),
    )
    resources = ResourceProfile.model_validate(
        resource_policy.parse_profile(_read(root, resource_profile.path, resource_profile.sha256))
    )
    metadata = _json(_read(root, image_metadata.path, image_metadata.sha256))
    validate_runtime_identity(_read(root, runtime_identity.path, runtime_identity.sha256))
    environment = Environment.model_validate(
        {
            "image": metadata["image"],
            "checker_versions": metadata["checker_versions"],
            "binaries": metadata["binaries"],
            "files": {},
        }
    )
    required_binaries = {"lean", "lake", "comparator", "lean4export", "landrun", "nanoda"}
    if not required_binaries <= environment.binaries.keys():
        raise EvidenceError("Complete pinned checker binaries, including nanoda, are required")
    names = {
        resource_profile.path,
        MATRIX_PATH,
        "formal/environment.lock.json",
        matrix.boundary_probe.script,
        *matrix.input_files,
    }
    for group in matrix.regression_groups:
        names.update(node.split("::")[0] for node in group.nodeids)
    for suite in matrix.suites:
        fixture = _fixture(root, suite)
        names.add(suite.fixture)
        base = PurePosixPath(suite.fixture).parent
        sources = [*fixture["project_files"].values()]
        sources.extend(case[key] for case in fixture["cases"] for key in ("challenge", "solution"))
        for source in sources:
            names.add(str(base / _relative(source)))
    inputs = {name: digest(_read(root, name)) for name in sorted(names)}
    lock = _json(_read(root, "formal/environment.lock.json"))
    if metadata.get("source_lock_sha256") != inputs["formal/environment.lock.json"]:
        raise EvidenceError("Image source lock differs from current pinned inputs")
    for name in ["comparator", "lean4export", "landrun", "nanoda"]:
        if environment.checker_versions.get(name) != lock["sources"][name]["revision"]:
            raise EvidenceError(f"Checker source revision differs: {name}")
    lean_version = re.match(
        r"Lean \(version ([^,\s]+),", environment.checker_versions.get("lean", "")
    )
    if lean_version is None or lean_version[1] != lock["lean"]["version"].removeprefix("v"):
        raise EvidenceError("Lean version provenance differs from the source lock")
    driver = inputs["src/physharness/verification/container_driver.py"]
    if metadata.get("driver_sha256") != driver:
        raise EvidenceError("Image driver differs from current source")
    return DeploymentScope(
        image_metadata=image_metadata,
        runtime_identity=runtime_identity,
        resource_profile_file=resource_profile,
        resources=resources,
        resource_profile_sha256=resources.sha256,
        image_digest=environment.image,
        driver_sha256=driver,
        launcher_sha256=inputs["src/physharness/verification/boundary.py"],
        seccomp_sha256=seccomp_digest(),
        checker_versions=environment.checker_versions,
        binaries=environment.binaries,
        inputs=inputs,
    )


def _cleanup(value: dict) -> str:
    if not isinstance(value, dict):
        raise EvidenceError("Container cleanup evidence is missing")
    name = value.get("container_name")
    if not isinstance(name, str) or not re.fullmatch(r"physharness-check-[a-f0-9]{32}", name):
        raise EvidenceError("Cleanup must identify the exact checker container")
    if value.get("status") == "removed":
        valid = type(value.get("exit_code")) is int and value["exit_code"] == 0
        valid = valid and value.get("output", "").strip() == name
    elif value.get("status") == "confirmed_absent":
        check = value.get("absence_check", {})
        valid = type(check.get("exit_code")) is int and check["exit_code"] == 0
        valid = valid and isinstance(check.get("output"), str) and not check["output"].strip()
    else:
        valid = False
    if not valid:
        raise EvidenceError("Cleanup did not prove removal or authoritative absence")
    return name


def _suite_report(root, scope, suite, report, seen_containers) -> str:
    if report.get("purpose") != "engineering_smoke" or report.get("status") != "passed":
        raise EvidenceError("A completed engineering report is required")
    if (
        report.get("expert_review") != "not_provided"
        or report.get("production_qualified") is not False
    ):
        raise EvidenceError("Engineering reports cannot supply human approval")
    if report.get("deployment_approval", "pending") != "pending":
        raise EvidenceError("A report cannot approve deployment")
    pins = {
        "image_digest": scope.image_digest,
        "image_metadata_sha256": scope.image_metadata.sha256,
        "runtime_identity_sha256": scope.runtime_identity.sha256,
        "resource_profile_sha256": scope.resource_profile_sha256,
        "resource_profile_source_sha256": scope.resource_profile_file.sha256,
        "resource_policy_sha256": scope.inputs["src/physharness/verification/resource_policy.py"],
        "resource_profile": scope.resources.model_dump(),
        "runner_sha256": scope.inputs["infra/run_qualified_lean.py"],
        "fixtures_sha256": scope.inputs[suite.fixture],
        "launcher_sha256": scope.launcher_sha256,
        "driver_sha256": scope.driver_sha256,
        "seccomp_sha256": scope.seccomp_sha256,
    }
    for key, expected in pins.items():
        if report.get(key) != expected:
            raise EvidenceError(f"Report input identity mismatch: {key}")
    independent = report.get("independent_kernel_requested")
    if type(independent) is not bool:
        raise EvidenceError("An explicit kernel mode is required")
    mode = "independent_kernel" if independent else "kernel"
    fixture = _fixture(root, suite)
    cases = {case["id"]: case for case in fixture["cases"]}
    rows = report.get("results")
    if not isinstance(rows, list) or len(rows) != len(cases):
        raise EvidenceError("Report is incomplete or duplicates required cases")
    ids = [row["id"] for row in rows]
    if set(ids) != set(cases) or len(set(ids)) != len(ids):
        raise EvidenceError("Report case identities differ from the required matrix")
    base = PurePosixPath(suite.fixture).parent
    environment = Environment(
        image=scope.image_digest,
        checker_versions=scope.checker_versions,
        binaries=scope.binaries,
        files={
            name: scope.inputs[str(base / source)]
            for name, source in fixture["project_files"].items()
        },
    )
    environment_sha = digest(canonical_json(environment.model_dump()))
    for row in rows:
        case = cases[row["id"]]
        value = VerificationOutcome.model_validate(row["outcome"])
        for key in ["expected_status", "expected_code"]:
            if row.get(key) != case[key]:
                raise EvidenceError("Report changed the expected case outcome")
        markers = case.get("required_diagnostic_substrings", [])
        if row.get("required_diagnostic_substrings", []) != markers:
            raise EvidenceError("Report changed the required causal diagnostics")
        expected_pins = {
            "target_digest": digest(json.dumps(case, sort_keys=True).encode()),
            "candidate_sha256": scope.inputs[str(base / case["solution"])],
            "challenge_sha256": scope.inputs[str(base / case["challenge"])],
            "environment_digest": environment_sha,
        }
        if any(getattr(value, key) != expected for key, expected in expected_pins.items()):
            raise EvidenceError("Outcome source, target or environment identity mismatch")
        if value.diagnostics.get("resource_profile_sha256") != scope.resource_profile_sha256:
            raise EvidenceError("Outcome resource profile differs from the deployment")
        if (
            value.diagnostics.get("resource_policy_sha256")
            != scope.inputs["src/physharness/verification/resource_policy.py"]
        ):
            raise EvidenceError("Outcome resource policy source differs from the deployment")
        if value.diagnostics.get("oom_confirmed") is not False:
            raise EvidenceError("OOM or missing resource observations cannot satisfy a fixed case")
        counters = []
        for key in ("memory_events_before", "memory_events_after"):
            record = value.diagnostics.get(key, {})
            events = record.get("events", {})
            if (
                record.get("status") != "observed"
                or type(events.get("oom_kill")) is not int
                or events["oom_kill"] < 0
            ):
                raise EvidenceError("Actual cgroup memory.events observations are required")
            counters.append(events)
        if (
            resource_policy.confirmed_oom(*counters)
            or counters[1]["oom_kill"] < counters[0]["oom_kill"]
        ):
            raise EvidenceError("OOM counters contradict the expected case evidence")
        if value.checker_versions != scope.checker_versions:
            raise EvidenceError("Outcome checker provenance differs from the scoped image")
        positive = case["expected_status"] == "verified"
        if (value.status, value.code) != (
            case["expected_status"],
            case["expected_code"],
        ) or value.assurance != (mode if positive else "none"):
            raise EvidenceError("Unexpected comparator result or assurance")
        code = value.diagnostics.get("comparator_exit_code")
        if type(code) is not int or (code != 0 if positive else not 0 < code < 128):
            raise EvidenceError("No ordinary comparator exit supports the expected outcome")
        logs = value.diagnostics.get("comparator_output")
        if not isinstance(logs, str) or any(marker not in logs for marker in markers):
            raise EvidenceError("Required causal diagnostic evidence is missing")
        if positive:
            controls = ["Lean default kernel accepts the solution", "Your solution is okay!"]
            if independent:
                controls.append("Nanoda kernel accepts the solution")
            if any(marker not in logs for marker in controls):
                raise EvidenceError("Positive control lacks expected kernel replay diagnostics")
        name = _cleanup(value.diagnostics.get("container_cleanup"))
        if name in seen_containers:
            raise EvidenceError("Container evidence was reused across outcomes")
        seen_containers.add(name)
    return mode


def _boundary_report(scope, matrix, report, runs, containers):
    if (
        report.get("protocol") != "physharness-boundary-evidence-v1"
        or report.get("purpose") != "fixed_boundary_probe"
        or report.get("status") != "passed"
        or report.get("production_qualified") is not False
        or report.get("expert_review") != "not_provided"
        or report.get("deployment_approval", "pending") != "pending"
    ):
        raise EvidenceError("Completed fixed observations without approval are required")
    pins = {
        "image_digest": scope.image_digest,
        "image_metadata_sha256": scope.image_metadata.sha256,
        "runtime_identity_sha256": scope.runtime_identity.sha256,
        "resource_profile_sha256": scope.resource_profile_sha256,
        "resource_profile_source_sha256": scope.resource_profile_file.sha256,
        "resource_policy_sha256": scope.inputs["src/physharness/verification/resource_policy.py"],
        "resource_profile": scope.resources.model_dump(),
        "probe_sha256": scope.inputs[matrix.boundary_probe.script],
        "launcher_sha256": scope.launcher_sha256,
        "driver_sha256": scope.driver_sha256,
        "seccomp_sha256": scope.seccomp_sha256,
    }
    if any(report.get(key) != expected for key, expected in pins.items()):
        raise EvidenceError("Fixed boundary probe input identity mismatch")
    checks = report.get("checks", {})
    if (
        not isinstance(checks, dict)
        or set(checks) != BOUNDARY_CHECKS
        or any(value is not True for value in checks.values())
    ):
        raise EvidenceError("Every fixed observation and writable positive control must pass")
    observed = report.get("observed", {})
    memory = observed.get("memory_events", {}) if isinstance(observed, dict) else {}
    if (
        memory.get("status") != "observed"
        or type(memory.get("events", {}).get("oom_kill")) is not int
    ):
        raise EvidenceError("Actual cgroup memory.events readability is required")
    # These are Linux errno values; a missing file or unsupported operation is not denial.
    for key, allowed in {
        "unix_socket_denied_errno": {1, 13},
        "inet_socket_denied_errno": {1, 13},
        "trusted_write_errno": {1, 13, 30},
        "candidate_write_errno": {1, 13, 30},
        "root_write_errno": {1, 13, 30},
    }.items():
        if (
            not isinstance(observed, dict)
            or type(observed.get(key)) is not int
            or observed[key] not in allowed
        ):
            raise EvidenceError("Expected causal permission-denial observations are missing")
    run = str(UUID(report["run_id"]))
    name = _cleanup(report.get("container_cleanup"))
    if run in runs or name in containers:
        raise EvidenceError("Fixed probe reused another execution or container observation")
    runs.add(run)
    containers.add(name)


def _regressions(root, scope, matrix, evidence) -> list[Check]:
    report = _json(_read(root, evidence.report.path, evidence.report.sha256))
    if (
        report.get("protocol") != "physharness-regression-evidence-v1"
        or report.get("purpose") != "engineering_regression"
        or report.get("production_qualified") is not False
        or report.get("scope_sha256") != scope.sha256
        or report.get("expert_review", "not_provided") != "not_provided"
        or report.get("scientific_review", "not_provided") != "not_provided"
        or report.get("deployment_approval", "pending") != "pending"
        or type(report.get("exit_code")) is not int
        or report["exit_code"] != 0
    ):
        raise EvidenceError("Regression report is unsuccessful, stale or claims approval")
    command = report.get("command")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) for item in command)
    ):
        raise EvidenceError("Record the actual regression command for operator review")
    junit = EvidenceFile.model_validate(report["junit"])
    data = _read(root, junit.path, junit.sha256)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise EvidenceError("JUnit entities and document types are unsupported")
    tree = ET.fromstring(data)
    if tree.tag not in {"testsuite", "testsuites"}:
        raise EvidenceError("Expected JUnit suite evidence")
    tests = {}
    for test in tree.iter("testcase"):
        identity = test.get("classname", "").replace(".", "/") + ".py::" + test.get("name", "")
        if identity in tests:
            raise EvidenceError("JUnit contains duplicate test identities")
        tests[identity] = not any(child.tag in {"failure", "error", "skipped"} for child in test)
    checks = []
    for group in matrix.regression_groups:
        missing = [node for node in group.nodeids if node not in tests]
        failed = [node for node in group.nodeids if node in tests and not tests[node]]
        checks.append(
            Check(
                id=group.id,
                status="invalid" if failed else "missing" if missing else "observed",
                detail=f"Missing: {missing}; failed or skipped: {failed}"
                if missing or failed
                else (
                    "Required host regressions passed; synthetic transport tests "
                    "remain distinct from real isolation."
                ),
                evidence_sha256=evidence.report.sha256,
            )
        )
    return checks


def assess_qualification(
    repository: Path,
    *,
    scope: DeploymentScope,
    evidence: list[SuiteEvidence],
    regressions: RegressionEvidence | None = None,
    boundary: BoundaryEvidence | None = None,
) -> ReviewPacket:
    """Produce a pending human review packet. No evidence JSON can issue approval."""
    root = Path(repository).resolve()
    matrix = load_matrix(root)
    checks = []
    try:
        current = capture_scope(
            root,
            image_metadata=scope.image_metadata,
            runtime_identity=scope.runtime_identity,
            resource_profile=scope.resource_profile_file,
        )
        if current != scope:
            raise EvidenceError("Current input hashes differ from the captured deployment scope")
    except (ValueError, OSError, KeyError, TypeError) as error:
        checks.append(Check(id="current-inputs", status="invalid", detail=str(error)))
    else:
        checks.append(
            Check(
                id="current-inputs",
                status="observed",
                detail="All scoped current input hashes match.",
            )
        )
    expected = {f"{suite.id}/{mode}" for suite in matrix.suites for mode in suite.modes}
    observed, runs, containers = set(), set(), set()
    suites = {suite.id: suite for suite in matrix.suites}
    if len(evidence) > 32:
        checks.append(
            Check(id="evidence-count", status="invalid", detail="Too many evidence reports")
        )
        evidence = []
    for item in evidence:
        identity = item.suite_id
        try:
            suite = suites[item.suite_id]
            report = _json(_read(root, item.report.path, item.report.sha256))
            run = str(UUID(report["run_id"]))
            if run in runs:
                raise EvidenceError("Duplicate execution run identity")
            runs.add(run)
            mode = _suite_report(root, scope, suite, report, containers)
            identity = f"{suite.id}/{mode}"
            if identity in observed:
                raise EvidenceError("Duplicate suite mode does not fill another requirement")
            observed.add(identity)
            checks.append(
                Check(
                    id=identity,
                    status="observed",
                    detail="Exact fixed cases, modes, sources, causal outcomes and cleanup match.",
                    evidence_sha256=item.report.sha256,
                )
            )
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            checks.append(
                Check(
                    id=identity,
                    status="invalid",
                    detail=str(error),
                    evidence_sha256=item.report.sha256,
                )
            )
    checks.extend(
        Check(id=key, status="missing", detail="No valid report for this deployment and mode.")
        for key in sorted(expected - observed)
    )
    if boundary is None:
        checks.append(
            Check(
                id="fixed-boundary",
                status="missing",
                detail="No pinned fixed boundary observations supplied.",
            )
        )
    else:
        try:
            report = _json(_read(root, boundary.report.path, boundary.report.sha256))
            _boundary_report(scope, matrix, report, runs, containers)
            checks.append(
                Check(
                    id="fixed-boundary",
                    status="observed",
                    detail=(
                        "Fixed process, syscall, canary, writable control, inspected "
                        "configuration and cleanup observations match."
                    ),
                    evidence_sha256=boundary.report.sha256,
                )
            )
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            checks.append(
                Check(
                    id="fixed-boundary",
                    status="invalid",
                    detail=str(error),
                    evidence_sha256=boundary.report.sha256,
                )
            )
    if regressions is None:
        checks.extend(
            Check(id=group.id, status="missing", detail="No pinned regression report supplied.")
            for group in matrix.regression_groups
        )
    else:
        try:
            checks.extend(_regressions(root, scope, matrix, regressions))
        except (ValueError, OSError, KeyError, TypeError, ET.ParseError) as error:
            checks.append(Check(id="regressions", status="invalid", detail=str(error)))
    # Recheck after all reads so source/evidence mutation cannot yield a satisfied packet.
    try:
        if (
            capture_scope(
                root,
                image_metadata=scope.image_metadata,
                runtime_identity=scope.runtime_identity,
                resource_profile=scope.resource_profile_file,
            )
            != scope
        ):
            raise EvidenceError("Inputs changed while checking evidence")
        for item in evidence:
            _read(root, item.report.path, item.report.sha256)
        if boundary is not None:
            _read(root, boundary.report.path, boundary.report.sha256)
        if regressions is not None:
            regression_record = _json(
                _read(root, regressions.report.path, regressions.report.sha256)
            )
            junit = EvidenceFile.model_validate(regression_record["junit"])
            _read(root, junit.path, junit.sha256)
    except (ValueError, OSError, KeyError, TypeError) as error:
        checks.append(Check(id="final-inputs", status="invalid", detail=str(error)))
    status = (
        "invalid"
        if any(row.status == "invalid" for row in checks)
        else "incomplete"
        if any(row.status == "missing" for row in checks)
        else "satisfied"
    )
    return ReviewPacket(
        scope_sha256=scope.sha256,
        scope=scope,
        mechanical_status=status,
        checks=checks,
        coverage_gaps=matrix.coverage_gaps,
        review_gates=matrix.review_gates,
    )
