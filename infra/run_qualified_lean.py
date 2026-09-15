"""Exercise real isolated Comparator cases and archive engineering evidence.

A passing report is not expert review or production qualification. The engineering
mode bootstraps evidence from actual image pins, without a circular report digest.
The legacy CI environment mode additionally checks an operator qualification pin.
Neither path can persist a scientific claim or manufacture a semantic review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import tempfile
from pathlib import Path
from uuid import uuid4

from physharness.verification import (
    EngineeringConfig,
    EngineeringRequest,
    EngineeringVerifier,
    ExecutionPins,
    LinuxQualification,
    create_bundle,
    driver_digest,
    launcher_digest,
    seccomp_digest,
)
from physharness.verification.boundary import Environment, digest, safe_read
from physharness.verification.qualification import validate_runtime_identity

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {("verified", "kernel_checked"), ("blocked", "comparator_failed")}


def pinned_bytes(path: Path, expected: str) -> bytes:
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("A complete SHA-256 pin is required")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Operator input must be a real file")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Operator input digest mismatch")
    return data


def diagnostic_expectations(case: dict) -> list[str]:
    markers = case.get("required_diagnostic_substrings", [])
    required = case["expected_status"] == "blocked"
    if (
        not isinstance(markers, list)
        or len(markers) > 16
        or (required and not markers)
        or any(
            not isinstance(marker, str) or not marker.strip() or len(marker) > 2000
            for marker in markers
        )
    ):
        raise ValueError(
            f"Verification case {case['id']} requires bounded nonempty causal diagnostic substrings"
        )
    return markers


def check_case_outcome(case: dict, result, *, publication: bool | None = None) -> None:
    markers = diagnostic_expectations(case)
    expected = case["expected_status"], case["expected_code"]
    if expected not in EXPECTED:
        raise ValueError("A suite case must observe comparator execution, not a preflight failure")
    if (result.status, result.code) != expected:
        raise RuntimeError(
            f"Verification case {case['id']} did not match its exact expected outcome"
        )
    exit_code = result.diagnostics.get("comparator_exit_code")
    if type(exit_code) is not int or (exit_code == 0) != (result.status == "verified"):
        raise RuntimeError(
            f"Verification case {case['id']} has no matching comparator exit evidence"
        )
    if result.status == "blocked" and not 0 < exit_code < 128:
        raise RuntimeError(f"Verification case {case['id']} terminated without a checker result")
    logs = result.diagnostics.get("comparator_output")
    if result.status == "verified":
        expected_assurance = (
            ("independent_kernel" if publication else "kernel")
            if publication is not None
            else result.assurance
        )
        controls = ["Lean default kernel accepts the solution", "Your solution is okay!"]
        if expected_assurance == "independent_kernel":
            controls.append("Nanoda kernel accepts the solution")
        if (
            expected_assurance not in {"kernel", "independent_kernel"}
            or result.assurance != expected_assurance
            or not isinstance(logs, str)
            or any(marker not in logs for marker in controls)
        ):
            raise RuntimeError(
                f"Verification case {case['id']} lacks its requested positive kernel evidence"
            )
    if markers and (not isinstance(logs, str) or any(marker not in logs for marker in markers)):
        raise RuntimeError(
            f"Verification case {case['id']} lacks its required causal diagnostic evidence"
        )


def check_cases(cases) -> None:
    if not isinstance(cases, list) or not cases or len(cases) > 100:
        raise ValueError("Supply 1-100 engineering cases")
    identities = [case["id"] for case in cases]
    if len(set(identities)) != len(identities):
        raise ValueError("Case IDs must be unique")
    expected = {(case["expected_status"], case["expected_code"]) for case in cases}
    if expected != EXPECTED:
        raise ValueError("Suite requires kernel success and comparator nonacceptance cases")
    for case in cases:
        diagnostic_expectations(case)


def _append_result(output, report, case, result, *, publication=None):
    report["results"].append(
        {
            "id": case["id"],
            "expected_status": case["expected_status"],
            "expected_code": case["expected_code"],
            "required_diagnostic_substrings": diagnostic_expectations(case),
            "outcome": result.model_dump(mode="json"),
        }
    )
    _write_report(output, report)
    check_case_outcome(case, result, publication=publication)


def _run_cases(output: Path, report: dict) -> None:
    if platform.system() != "Linux":
        raise RuntimeError("Qualified verifier CI requires Linux")
    bundle = Path(os.environ["CI_BUNDLE_PATH"])
    manifest_sha = os.environ["CI_MANIFEST_SHA256"]
    pinned_bytes(bundle / "manifest.json", manifest_sha)
    qualification = LinuxQualification.model_validate_json(
        pinned_bytes(
            Path(os.environ["CI_QUALIFICATION_PATH"]),
            os.environ["CI_QUALIFICATION_SHA256"],
        )
    )
    cases = json.loads(
        pinned_bytes(Path(os.environ["CI_CASES_PATH"]), os.environ["CI_CASES_SHA256"])
    )
    check_cases(cases)
    execution = ExecutionPins.model_validate(
        qualification.model_dump(exclude={"qualification_report_sha256"})
    )
    verifier = EngineeringVerifier(
        EngineeringConfig(
            bundle_directory=bundle,
            manifest_sha256=manifest_sha,
            execution=execution,
        )
    )
    for case in cases:
        request = EngineeringRequest.model_validate(case["request"])
        _append_result(
            output, report, case, verifier.run(request).outcome, publication=request.publication
        )
    report.update(
        status="passed",
        manifest_sha256=manifest_sha,
        supplied_qualification_report_sha256=qualification.qualification_report_sha256,
    )
    _write_report(output, report)


def _run_engineering(
    output: Path,
    report: dict,
    metadata_path: Path,
    fixtures_path: Path,
    publication: bool,
    runtime_identity: Path | None = None,
) -> None:
    snapshots = {}

    def snapshot(base, name):
        data = safe_read(base, name)
        identity = digest(data)
        if (base, name) in snapshots and snapshots[base, name] != identity:
            raise RuntimeError(f"Engineering input changed during execution: {name}")
        snapshots[base, name] = identity
        return data

    runner_sha = digest(snapshot(Path(__file__).parent, Path(__file__).name))
    runtime_sha = None
    if runtime_identity is not None:
        runtime_bytes = snapshot(runtime_identity.parent, runtime_identity.name)
        validate_runtime_identity(runtime_bytes)
        runtime_sha = digest(runtime_bytes)
    metadata_bytes = snapshot(metadata_path.parent, metadata_path.name)
    metadata = json.loads(metadata_bytes)
    image = Environment.model_validate(
        {
            "image": metadata["image"],
            "checker_versions": metadata["checker_versions"],
            "binaries": metadata["binaries"],
            "files": {},
        }
    )
    fixture_bytes = snapshot(fixtures_path.parent, fixtures_path.name)
    fixture = json.loads(fixture_bytes)
    if fixture.get("purpose") != "engineering_smoke" or fixture.get("schema_version") != 1:
        raise ValueError("Expected versioned engineering fixture manifest")
    cases = fixture["cases"]
    check_cases(cases)
    report.update(
        image_digest=image.image,
        image_metadata_sha256=digest(metadata_bytes),
        fixtures_sha256=digest(fixture_bytes),
        independent_kernel_requested=publication,
        launcher_sha256=launcher_digest(),
        driver_sha256=driver_digest(),
        seccomp_sha256=seccomp_digest(),
        runner_sha256=runner_sha,
        runtime_identity_sha256=runtime_sha,
    )
    _write_report(output, report)
    execution = ExecutionPins(
        image_digest=image.image,
        driver_sha256=driver_digest(),
        launcher_sha256=launcher_digest(),
        seccomp_sha256=seccomp_digest(),
        linux_boundary="docker-landlock-seccomp-v1",
        independent_kernel=publication,
    )
    project_files = {
        name: snapshot(fixtures_path.parent, source)
        for name, source in fixture["project_files"].items()
    }
    # TemporaryDirectory honors TMPDIR for a shared Colima bind directory on macOS.
    with tempfile.TemporaryDirectory(prefix="physharness-engineering-") as temporary:
        for index, case in enumerate(cases):
            source = snapshot(fixtures_path.parent, case["challenge"])
            candidate = snapshot(fixtures_path.parent, case["solution"])
            bundle = Path(temporary) / str(index)
            # This identity labels an engineering fixture; no scientific revision or review is made.
            target_digest = digest(json.dumps(case, sort_keys=True).encode())
            revision_id = "engineering:" + case["id"]
            manifest_sha = create_bundle(
                bundle,
                problem_revision_id=revision_id,
                target_digest=target_digest,
                challenge_source=source.decode("utf-8"),
                theorem_names=case["theorem_names"],
                image_digest=image.image,
                checker_versions=image.checker_versions,
                binaries=image.binaries,
                project_files=project_files,
            )
            manifest = json.loads((bundle / "manifest.json").read_bytes())
            request = EngineeringRequest(
                problem_revision_id=revision_id,
                target_digest=target_digest,
                challenge_sha256=digest(source),
                environment_digest=manifest["environment_digest"],
                candidate_sha256=digest(candidate),
                candidate_source=candidate.decode("utf-8"),
                publication=publication,
            )
            verifier = EngineeringVerifier(
                EngineeringConfig(
                    bundle_directory=bundle,
                    manifest_sha256=manifest_sha,
                    execution=execution,
                )
            )
            _append_result(
                output, report, case, verifier.run(request).outcome, publication=request.publication
            )
    for (base, name), expected in snapshots.items():
        if digest(safe_read(base, name)) != expected:
            raise RuntimeError(f"Engineering input changed during execution: {name}")
    report.update(status="passed")
    _write_report(output, report)


def _write_report(output: Path, report: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".qualification-", dir=output.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, output)
        directory_fd = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _record_run(output, action):
    report = {
        "status": "running",
        "run_id": str(uuid4()),
        "results": [],
        "purpose": "engineering_smoke",
        "expert_review": "not_provided",
        "production_qualified": False,
    }
    _write_report(output, report)
    try:
        action(output, report)
    except BaseException as error:
        report.update(
            status="blocked",
            error_type=type(error).__name__,
            reason=str(error)[:2000] or "Current engineering run failed",
        )
        _write_report(output, report)
        raise


def run_from_environment(output: Path) -> None:
    _record_run(output, _run_cases)


def run_engineering(
    output: Path,
    metadata: Path,
    fixtures: Path,
    publication: bool = False,
    *,
    runtime_identity: Path | None = None,
) -> None:
    _record_run(
        output,
        lambda path, report: _run_engineering(
            path, report, metadata, fixtures, publication, runtime_identity
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engineering-image-metadata", type=Path)
    parser.add_argument(
        "--runtime-identity",
        type=Path,
        help="Operator-observed Linux runtime JSON; required for scoped qualification evidence",
    )
    parser.add_argument("--fixtures", type=Path, default=ROOT / "formal/adversarial/cases.json")
    parser.add_argument(
        "--publication", action="store_true", help="Observe independent nanoda replay"
    )
    args = parser.parse_args()
    if args.engineering_image_metadata:
        run_engineering(
            args.output,
            args.engineering_image_metadata,
            args.fixtures,
            args.publication,
            runtime_identity=args.runtime_identity,
        )
    else:
        run_from_environment(args.output)
