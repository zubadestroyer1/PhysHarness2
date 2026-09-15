"""Run operator-pinned cases using the actual isolated ComparatorVerifier.

Requires a qualified self-hosted Linux runner. No fallback success, mocked driver,
constructed semantic review, or direct candidate execution is permitted here.
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
    ComparatorConfig,
    ComparatorVerifier,
    LinuxQualification,
    VerificationRequest,
)


def pinned_bytes(path: Path, expected: str) -> bytes:
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("A complete reviewed SHA-256 pin is required")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Operator input must be a real file")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Operator input digest mismatch")
    return data


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
    if not isinstance(cases, list) or not cases or len(cases) > 100:
        raise ValueError("Supply 1-100 operator-reviewed cases")
    expected_statuses = {case["expected_status"] for case in cases}
    if not {"verified", "rejected"} <= expected_statuses:
        raise ValueError("Qualification run requires both valid and adversarial expected cases")
    verifier = ComparatorVerifier(
        ComparatorConfig(
            bundle_directory=bundle,
            manifest_sha256=manifest_sha,
            qualification=qualification,
        )
    )
    results = report["results"]
    for case in cases:
        request = VerificationRequest.model_validate(case["request"])
        result = verifier.verify(request)
        results.append(
            {
                "id": case["id"],
                "expected_status": case["expected_status"],
                "outcome": result.model_dump(mode="json"),
            }
        )
        _write_report(output, report)
        if result.status != case["expected_status"]:
            raise RuntimeError(f"Verification case {case['id']} did not match expected outcome")
    report.update(status="passed", manifest_sha256=manifest_sha)
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
    finally:
        if os.path.exists(name):
            os.unlink(name)


def run_from_environment(output: Path) -> None:
    report = {"status": "running", "run_id": str(uuid4()), "results": []}
    _write_report(output, report)
    try:
        _run_cases(output, report)
    except BaseException as error:
        report.update(
            status="blocked",
            error_type=type(error).__name__,
            reason="Current qualification run failed; inspect runner logs.",
        )
        _write_report(output, report)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_from_environment(args.output)
