"""Operator-run current-source verifier controls for one restored local image.

Each attempt is exclusive. Existing qualification APIs assess the records; this
collector only captures observations and never grants deployment approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from physharness.verification.qualification import (
    BoundaryEvidence,
    DeploymentScope,
    EvidenceFile,
    RegressionEvidence,
    SuiteEvidence,
    assess_qualification,
    capture_scope,
    load_matrix,
    render_review_packet,
)

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path("work/pilot-qualification-2026-09-23")
STATE = Path(".state/pilot-qualification")
IMAGE_ID = "sha256:84deccc518a7aa5ce916d15236dac5ae416a5288449bd8620a2c8bb374c24b67"
RUNTIME_KEYS = (
    "SystemTime", "KernelVersion", "OperatingSystem", "OSType", "Architecture",
    "ServerVersion", "CgroupVersion", "DefaultRuntime", "RuncCommit",
    "ContainerdCommit", "SecurityOptions",
)


def ref(path: Path) -> EvidenceFile:
    return EvidenceFile(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def write_new(path: Path, data: str) -> None:
    with path.open("x") as stream:
        stream.write(data)


def json_new(path: Path, value: object) -> None:
    write_new(path, json.dumps(value, indent=2) + "\n")


def observed_scope(directory: Path) -> DeploymentScope:
    return capture_scope(ROOT, image_metadata=ref(directory / "image-metadata.json"), runtime_identity=ref(directory / "runtime-identity.json"))


def frozen_scope(directory: Path) -> DeploymentScope:
    scope = DeploymentScope.model_validate_json((directory / "scope.json").read_bytes())
    if observed_scope(directory) != scope:
        raise RuntimeError("Current inputs differ from the frozen qualification scope")
    return scope


def capture(directory: Path, scratch: Path, image_tag: str) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    scratch.mkdir(parents=True, exist_ok=False)
    image = subprocess.check_output(["docker", "image", "inspect", image_tag, "--format", "{{.Id}}"], text=True).strip()
    if image != IMAGE_ID:
        raise RuntimeError(f"Restored image ID differs: {image}")
    name = "physharness-pilot-metadata-" + uuid4().hex
    subprocess.run(["docker", "create", "--name", name, "--network=none", "--read-only", "--entrypoint=/bin/true", image], check=True, stdout=subprocess.DEVNULL)
    try:
        subprocess.run(["docker", "cp", name + ":/opt/verifier/metadata/.", str(scratch)], check=True)
        for source, target in [
            ("/opt/physharness/container_driver.py", "container_driver.py"),
            ("/opt/physharness/resource_policy.py", "resource_policy.py"),
        ]:
            subprocess.run(["docker", "cp", name + ":" + source, str(scratch / target)], check=True)
    finally:
        subprocess.run(["docker", "rm", name], check=True, stdout=subprocess.DEVNULL)
    driver = (scratch / "container_driver.py").read_bytes()
    policy = (scratch / "resource_policy.py").read_bytes()
    if driver != (ROOT / "src/physharness/verification/container_driver.py").read_bytes():
        raise RuntimeError("Embedded driver differs from current source")
    if policy != (ROOT / "src/physharness/verification/resource_policy.py").read_bytes():
        raise RuntimeError("Embedded resource policy differs from current source")
    if (scratch / "environment.lock.json").read_bytes() != (ROOT / "formal/environment.lock.json").read_bytes():
        raise RuntimeError("Embedded source lock differs from current source")
    metadata = json.loads((scratch / "build.json").read_bytes())
    metadata.update(image=image, driver_sha256=hashlib.sha256(driver).hexdigest(), resource_policy_sha256=hashlib.sha256(policy).hexdigest())
    raw_runtime = json.loads(subprocess.check_output(["docker", "info", "--format", "{{json .}}"], text=True))
    runtime = {key: raw_runtime[key] for key in RUNTIME_KEYS}
    runtime.update(purpose="engineering_runtime_observation", production_qualified=False)
    json_new(directory / "image-metadata.json", metadata)
    json_new(directory / "runtime-identity.json", runtime)
    scope = observed_scope(directory)
    json_new(directory / "scope.json", scope.model_dump(mode="json"))
    print(json.dumps({"image": image, "scope_sha256": scope.sha256, "attempt": directory.relative_to(ROOT).as_posix()}), flush=True)


def run_logged(command: list[str], log: Path) -> int:
    with log.open("x") as stream:
        result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    return result.returncode


def regressions(directory: Path) -> None:
    scope = frozen_scope(directory)
    matrix = load_matrix(ROOT)
    files = sorted({node.split("::")[0] for group in matrix.regression_groups for node in group.nodeids})
    junit = directory / "regressions.xml"
    report = directory / "regressions.json"
    if junit.exists() or report.exists():
        raise FileExistsError("Regression output exists; use a new attempt")
    command = [".venv/bin/pytest", "-q", *files, "--junitxml=" + ref_path(junit)]
    code = run_logged(command, directory / "regressions.log")
    record = {
        "protocol": "physharness-regression-evidence-v1", "purpose": "engineering_regression",
        "production_qualified": False, "scope_sha256": scope.sha256,
        "exit_code": code, "command": command,
        "junit": ref(junit).model_dump() if junit.exists() else None,
    }
    json_new(report, record)
    frozen_scope(directory)
    if code:
        raise RuntimeError(f"Host regressions exited {code}; see {directory / 'regressions.log'}")


def ref_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def suite(directory: Path, suite_id: str, independent: bool) -> None:
    frozen_scope(directory)
    mode = "independent" if independent else "kernel"
    output = directory / f"{suite_id}-{mode}.json"
    if output.exists():
        raise FileExistsError(f"{output} exists; use a new attempt")
    fixture = "formal/adversarial/cases.json" if suite_id == "core" else "formal/library-cases.json"
    command = [
        ".venv/bin/python", "infra/run_qualified_lean.py",
        "--engineering-image-metadata", ref_path(directory / "image-metadata.json"),
        "--runtime-identity", ref_path(directory / "runtime-identity.json"),
        "--fixtures", fixture, "--output", ref_path(output),
    ]
    if independent:
        command.append("--publication")
    code = run_logged(command, directory / f"{suite_id}-{mode}.log")
    frozen_scope(directory)
    if code:
        raise RuntimeError(f"{suite_id}/{mode} exited {code}; report and log retained")


def boundary(directory: Path) -> None:
    frozen_scope(directory)
    output = directory / "fixed-boundary.json"
    if output.exists():
        raise FileExistsError(f"{output} exists; use a new attempt")
    command = [
        ".venv/bin/python", "infra/probe_verifier_boundary.py",
        "--image-metadata", ref_path(directory / "image-metadata.json"),
        "--image-metadata-sha256", ref(directory / "image-metadata.json").sha256,
        "--runtime-identity", ref_path(directory / "runtime-identity.json"),
        "--runtime-identity-sha256", ref(directory / "runtime-identity.json").sha256,
        "--output", ref_path(output),
    ]
    code = run_logged(command, directory / "fixed-boundary.log")
    frozen_scope(directory)
    if code:
        raise RuntimeError(f"Fixed boundary probe exited {code}; report and log retained")


def assess(directory: Path) -> None:
    scope = frozen_scope(directory)
    if (directory / "qualification-review.json").exists() or (directory / "QUALIFICATION_REVIEW.md").exists():
        raise FileExistsError("Assessment output exists; use a new attempt")
    packet = assess_qualification(
        ROOT, scope=scope,
        evidence=[SuiteEvidence(suite_id=suite_id, report=ref(directory / f"{suite_id}-{mode}.json"))
                  for suite_id in ("core", "library") for mode in ("kernel", "independent")],
        regressions=RegressionEvidence(report=ref(directory / "regressions.json")),
        boundary=BoundaryEvidence(report=ref(directory / "fixed-boundary.json")),
    )
    json_new(directory / "qualification-review.json", packet.model_dump(mode="json"))
    write_new(directory / "QUALIFICATION_REVIEW.md", render_review_packet(packet))
    print(json.dumps({"mechanical_status": packet.mechanical_status, "checks": {check.id: check.status for check in packet.checks}, "production_qualified": packet.production_qualified, "deployment_approval": packet.deployment_approval}), flush=True)
    if packet.mechanical_status != "satisfied":
        raise RuntimeError("Qualification assessment is not mechanically satisfied; packet retained")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("capture", "regressions", "core-kernel", "core-independent", "library-kernel", "library-independent", "boundary", "assess", "all"))
    parser.add_argument("--attempt", required=True, help="New attempt directory name, for example attempt-01")
    parser.add_argument("--image-tag", default="physharness-formal:wave01-resources")
    args = parser.parse_args()
    if not re.fullmatch(r"attempt-[a-zA-Z0-9_-]{1,40}", args.attempt):
        parser.error("Attempt must match attempt-[a-zA-Z0-9_-]{1,40}")
    directory = ROOT / EVIDENCE / args.attempt
    scratch = ROOT / STATE / args.attempt
    steps = ("capture", "regressions", "core-kernel", "core-independent", "library-kernel", "library-independent", "boundary", "assess") if args.stage == "all" else (args.stage,)
    for step in steps:
        print(f"Starting {step}", flush=True)
        if step == "capture":
            capture(directory, scratch, args.image_tag)
        elif step == "regressions":
            regressions(directory)
        elif step == "boundary":
            boundary(directory)
        elif step == "assess":
            assess(directory)
        else:
            suite_id, mode = step.split("-", 1)
            suite(directory, suite_id, mode == "independent")
    print("Completed requested stages", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Collector stopped: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        raise
