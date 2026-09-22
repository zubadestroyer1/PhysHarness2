"""Evaluator packages and hash-bound review evidence; never issues scientific approval."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from physharness.errors import HarnessError
from physharness.verification.boundary import (
    Environment,
    ResourceProfile,
    VerificationOutcome,
    digest,
    driver_digest,
    launcher_digest,
    safe_read,
    seccomp_digest,
)
from physharness.verification.bundles import canonical_json, project_path
from physharness.verification.resource_policy import parse_profile, policy_digest

from .physics_benchmarks import PhysicsBenchmark


def _files(benchmark: PhysicsBenchmark, project_files: dict[str, bytes]):
    benchmark = benchmark.snapshot()
    if not {"lakefile.toml", "lakefile.lean"} & project_files.keys():
        raise ValueError("Trusted Lake configuration required")
    files = {}
    for name, content in project_files.items():
        project_path(name)
        if not isinstance(content, bytes) or len(content) > 16_000_000:
            raise ValueError("Project files must be bounded bytes")
        files["project/" + name] = content
    cases = []
    review = dict(benchmark.inventory(), positive_tasks=[], negative_cases=[])
    for collection in benchmark.collections:
        parents = {task.id: task for task in collection.tasks}
        for task in collection.tasks:
            folder = "cases/" + task.id
            files[folder + "/Challenge.lean"] = task.target_source.encode()
            files[folder + "/Solution.lean"] = task.reference_source.encode()
            cases.append(
                {
                    "id": task.id,
                    "challenge": folder + "/Challenge.lean",
                    "solution": folder + "/Solution.lean",
                    "theorem_names": [task.target_theorem],
                    "expected_status": "verified",
                    "expected_code": "kernel_checked",
                    "required_diagnostic_substrings": [],
                }
            )
            review["positive_tasks"].append(
                dict(
                    task.model_dump(mode="json"),
                    program=collection.program,
                    review_status="pending",
                    difficulty_status="author_estimate",
                )
            )
        for case in collection.negative_cases:
            parent = parents[case.parent_id]
            folder = "cases/" + case.id
            files[folder + "/Challenge.lean"] = case.target_source.encode()
            files[folder + "/Solution.lean"] = case.candidate_source.encode()
            mechanical_failure = case.expected_outcome == "kernel_nonacceptance"
            cases.append(
                {
                    "id": case.id,
                    "challenge": folder + "/Challenge.lean",
                    "solution": folder + "/Solution.lean",
                    "theorem_names": [parent.target_theorem],
                    "expected_status": "blocked" if mechanical_failure else "verified",
                    "expected_code": "comparator_failed"
                    if mechanical_failure
                    else "kernel_checked",
                    "required_diagnostic_substrings": case.required_diagnostics,
                }
            )
            review["negative_cases"].append(
                dict(
                    case.model_dump(mode="json"),
                    program=collection.program,
                    family=parent.family,
                    split=parent.split,
                    review_status="pending",
                    required_review_disposition="hold_for_semantic_review"
                    if not mechanical_failure
                    else "confirm_negative_case_rationale",
                )
            )
    fixture = {
        "schema_version": 1,
        "purpose": "engineering_smoke",
        "project_files": {name: "project/" + name for name in project_files},
        "cases": cases,
    }
    files["cases.json"] = canonical_json(fixture)
    files["review.json"] = canonical_json(review)
    for split in ["development", "holdout"]:
        files["discovery/" + split + ".json"] = canonical_json(
            {
                "benchmark_sha256": benchmark.revision_digest(),
                "split": split,
                "tasks": benchmark.discovery_tasks(split),
                "information_policy": (
                    "targets_only_export; evaluator storage/network isolation remains required"
                ),
                "contamination_status": "not_ruled_out",
            }
        )
    lines = [
        "# Physics benchmark review packet",
        "",
        "**Pending human review. No scientific or deployment approval is issued by this packet.**",
        "",
        "Difficulty bands are author estimates, not measured model performance. "
        "The full packet contains evaluator-only reference solutions; "
        "do not mount it in discovery workspaces.",
        "",
        "Review each intended claim against its formal quantifiers, domains, units/conventions, "
        "differentiability, boundary assumptions and definitions. Record an explicit decision "
        "against the exact source and benchmark revision.",
        "",
    ]
    for item in review["positive_tasks"]:
        lines += [
            f"## {item['id']}: {item['title']}",
            "",
            item["statement"],
            "",
            "**Physical scope:** " + item["physical_scope"],
            "",
            "**Assumptions:**",
            "",
        ]
        lines += ["- " + assumption for assumption in item["assumptions"]] or [
            "- None beyond the explicit typed domain."
        ]
        lines += [
            "",
            "**Difficulty estimate:** "
            + item["difficulty_band"]
            + ". "
            + item["difficulty_rationale"],
            "",
            "**Reference outline:** " + item["reference_outline"],
            "",
            "**Known shortcuts:**",
            "",
        ]
        lines += [
            "- `" + shortcut["declaration"] + "`: " + shortcut["note"]
            for shortcut in item["known_shortcuts"]
        ] or ["- No shortcut recorded; absence is not a proof that none exists."]
        lines += [
            "",
            f"[Exact target](cases/{item['id']}/Challenge.lean) · "
            f"[Evaluator reference](cases/{item['id']}/Solution.lean)",
            "",
            "**Decision: pending.**",
            "",
        ]
    lines += [
        "## Altered cases",
        "",
        "A semantic-hold case may be a valid theorem for the wrong intended question. "
        "Kernel acceptance cannot approve its scientific interpretation.",
        "",
    ]
    for item in review["negative_cases"]:
        lines += [
            f"### {item['id']}",
            "",
            item["rationale"],
            "",
            "**Expected review:** " + item["required_review_disposition"],
            "",
            "**Change:** " + item["semantic_change"],
            "",
        ]
    files["REVIEW.md"] = ("\n".join(lines) + "\n").encode()
    return files


def prepare_benchmark(
    benchmark: PhysicsBenchmark, destination: Path, *, project_files: dict[str, bytes]
) -> dict:
    """Write an exclusive evaluator package. No Lean, model or review is executed."""
    files = _files(benchmark, project_files)
    manifest = {
        "schema": "physharness-physics-package-v1",
        "benchmark_sha256": benchmark.revision_digest(),
        "files": {name: digest(content) for name, content in files.items()},
        "scientific_review": "pending",
        "production_qualified": False,
    }
    files["manifest.json"] = canonical_json(manifest)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    destination.mkdir(parents=True, mode=0o700)
    try:
        for name, data in files.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write(data)
    except BaseException:
        shutil.rmtree(destination)
        raise
    return manifest


def assess_benchmark_reports(
    benchmark: PhysicsBenchmark,
    bundle: Path,
    *,
    image_metadata: Path,
    kernel_report: Path,
    independent_report: Path,
    resource_profile: Path = Path("formal/verifier-resources.json"),
) -> dict:
    """Validate operator-supplied engineering observations; always leaves human review pending."""
    try:
        resource_bytes = safe_read(resource_profile.parent, resource_profile.name)
        resources = ResourceProfile.model_validate(parse_profile(resource_bytes))
        resource_pins = {
            "resource_profile_sha256": resources.sha256,
            "resource_policy_sha256": policy_digest(),
        }
        manifest = json.loads(safe_read(bundle, "manifest.json"))
        if (
            set(manifest)
            != {"schema", "benchmark_sha256", "files", "scientific_review", "production_qualified"}
            or manifest["schema"] != "physharness-physics-package-v1"
            or manifest["benchmark_sha256"] != benchmark.revision_digest()
            or manifest.get("scientific_review") != "pending"
            or manifest.get("production_qualified") is not False
        ):
            raise ValueError("Benchmark revision differs from evaluator package")
        # Reconstruct expected artifacts, not just self-declared manifest hashes.
        fixture_bytes = safe_read(bundle, "cases.json")
        fixture = json.loads(fixture_bytes)
        if not isinstance(fixture, dict) or not isinstance(fixture.get("project_files"), dict):
            raise ValueError("Evaluator project mapping is malformed")
        project = {
            name: safe_read(bundle, source) for name, source in fixture["project_files"].items()
        }
        expected_files = _files(benchmark, project)
        if manifest["files"] != {name: digest(data) for name, data in expected_files.items()}:
            raise ValueError("Evaluator package differs from benchmark contents")
        for name, data in expected_files.items():
            if safe_read(bundle, name) != data:
                raise ValueError("Evaluator artifact bytes changed: " + name)
        metadata_bytes = safe_read(image_metadata.parent, image_metadata.name)
        metadata = json.loads(metadata_bytes)
        environment = Environment(
            image=metadata["image"],
            checker_versions=metadata["checker_versions"],
            binaries=metadata["binaries"],
            files={name: digest(data) for name, data in project.items()},
        )
        environment_hash = digest(canonical_json(environment.model_dump()))
        cases = {case["id"]: case for case in fixture["cases"]}
        report_pins = []
        for path, independent in [(kernel_report, False), (independent_report, True)]:
            raw = safe_read(path.parent, path.name)
            report = json.loads(raw)
            if not isinstance(report, dict) or any(
                report.get(key) != expected
                for key, expected in {
                    **resource_pins,
                    "resource_profile": resources.model_dump(),
                    "resource_profile_source_sha256": digest(resource_bytes),
                    "driver_sha256": driver_digest(),
                    "launcher_sha256": launcher_digest(),
                    "seccomp_sha256": seccomp_digest(),
                }.items()
            ):
                raise ValueError("Report does not match current acceptance execution pins")
            if any(
                [
                    report.get("status") != "passed",
                    report.get("purpose") != "engineering_smoke",
                    report.get("production_qualified") is not False,
                    report.get("image_digest") != environment.image,
                    report.get("image_metadata_sha256") != digest(metadata_bytes),
                    report.get("fixtures_sha256") != digest(fixture_bytes),
                    report.get("independent_kernel_requested") is not independent,
                ]
            ):
                raise ValueError("Report does not match the exact successful engineering run")
            rows = report["results"]
            if len(rows) != len(cases) or {row["id"] for row in rows} != cases.keys():
                raise ValueError("Report has missing or duplicate cases")
            for row in rows:
                case = cases[row["id"]]
                result = VerificationOutcome.model_validate(row["outcome"])
                if (result.status, result.code) != (case["expected_status"], case["expected_code"]):
                    raise ValueError("Unexpected case disposition: " + row["id"])
                if (
                    result.target_digest != digest(json.dumps(case, sort_keys=True).encode())
                    or result.challenge_sha256 != digest(expected_files[case["challenge"]])
                    or result.candidate_sha256 != digest(expected_files[case["solution"]])
                    or result.environment_digest != environment_hash
                ):
                    raise ValueError("Observed theorem/source/environment identity differs")
                if result.checker_versions != environment.checker_versions:
                    raise ValueError("Observed checker versions differ")
                diagnostics = result.diagnostics
                if any(diagnostics.get(key) != value for key, value in resource_pins.items()):
                    raise ValueError("Outcome resource profile or policy differs from intended run")
                logs = diagnostics.get("comparator_output")
                cleanup = diagnostics.get("container_cleanup")
                if not isinstance(logs, str) or not isinstance(cleanup, dict):
                    raise ValueError("Malformed execution diagnostics")
                code = diagnostics.get("comparator_exit_code")
                if (
                    type(code) is not int
                    or (result.status == "verified" and code != 0)
                    or (result.status != "verified" and not 0 < code < 128)
                ):
                    raise ValueError("Missing successful checker execution or causal failure")
                if result.status == "verified" and result.assurance != (
                    "independent_kernel" if independent else "kernel"
                ):
                    raise ValueError("Kernel assurance does not match requested mode")
                if result.status != "verified" and "Building Solution" not in logs:
                    raise ValueError("Failure did not reach candidate construction")
                if any(marker not in logs for marker in case["required_diagnostic_substrings"]):
                    raise ValueError("Expected negative cause was not observed")
                if cleanup.get("status") not in {
                    "removed",
                    "confirmed_absent",
                }:
                    raise ValueError("Container cleanup was not confirmed")
            report_pins.append(
                {"sha256": digest(raw), "independent_kernel": independent, "cases": len(rows)}
            )
        if (
            safe_read(resource_profile.parent, resource_profile.name) != resource_bytes
            or policy_digest() != resource_pins["resource_policy_sha256"]
        ):
            raise ValueError("Resource profile or policy changed during assessment")
        return dict(
            benchmark.inventory(),
            mechanical_status="expected_outcomes_observed_in_both_kernel_modes",
            reports=report_pins,
            resource_profile=resources.model_dump(),
            resource_profile_source_sha256=digest(resource_bytes),
            **resource_pins,
            semantic_hold_ids=[
                case.id
                for collection in benchmark.collections
                for case in collection.negative_cases
                if case.expected_outcome == "semantic_hold"
            ],
            qualification_status="awaiting_human_scientific_review_and_deployment_qualification",
        )
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise HarnessError(
            "physics_benchmark_evidence_invalid",
            "Benchmark evidence is missing, stale or inconsistent.",
            details={"reason": str(error)[:2000]},
        ) from error
