"""Benchmark packaging/authority tests; synthetic Lean is never executed here."""

import copy
import json
from pathlib import Path
from uuid import uuid4

import pytest

from physharness.errors import HarnessError
from physharness.science.benchmark_artifacts import assess_benchmark_reports, prepare_benchmark
from physharness.science.physics_benchmarks import PhysicsBenchmark, load_physics_benchmarks


def task():
    return {
        "id": "quantum.gates.involution",
        "family": "gates",
        "split": "development",
        "title": "Gate involution",
        "difficulty_band": "foundation",
        "difficulty_rationale": "Synthetic test; author estimate, not calibrated.",
        "capabilities": ["composition"],
        "statement": "A gate squares to identity.",
        "assumptions": ["Finite dimension"],
        "physical_scope": "Synthetic fixture only",
        "provenance": [{"uri": "local:test", "locator": "fixture", "note": "Test data only"}],
        "target_theorem": "target",
        "target_source": "theorem target : True := by sorry\n",
        "reference_source": "theorem target : True := by trivial -- EVALUATOR_REFERENCE\n",
        "reference_outline": "EVALUATOR_OUTLINE",
        "known_shortcuts": [{"declaration": "EVALUATOR_PREMISE", "note": "test only"}],
        "limitations": ["Not a physics benchmark"],
    }


def collection():
    positive = task()
    return {
        "version": 1,
        "program": "quantum",
        "tasks": [positive],
        "negative_cases": [
            {
                "id": "quantum.gates.involution.hole",
                "parent_id": positive["id"],
                "category": "incomplete_proof",
                "expected_outcome": "kernel_nonacceptance",
                "target_source": positive["target_source"],
                "candidate_source": positive["target_source"],
                "rationale": "Unfinished candidate must fail",
                "required_diagnostics": ["Illegal axiom detected: 'sorryAx'"],
                "semantic_change": "None; the submitted proof has a hole",
            },
            {
                "id": "quantum.gates.involution.meaning",
                "parent_id": positive["id"],
                "category": "semantic_weakening",
                "expected_outcome": "semantic_hold",
                "target_source": "theorem target : True := by sorry\n",
                "candidate_source": "theorem target : True := by trivial\n",
                "rationale": "Correct tautology does not state the physical claim",
                "required_diagnostics": [],
                "semantic_change": "Replace physical property with True",
            },
        ],
    }


def benchmark():
    return PhysicsBenchmark(collections=[collection()])


def test_target_export_omits_all_evaluator_material_and_copies_data():
    release = benchmark()
    exported = release.discovery_tasks("development")
    text = json.dumps(exported)
    assert "EVALUATOR_" not in text
    assert len(exported) == 1 and exported[0]["target_source"] == task()["target_source"]
    exported[0]["assumptions"].append("mutated")
    assert release.discovery_tasks("development")[0]["assumptions"] == ["Finite dimension"]
    assert release.discovery_tasks("holdout") == []


@pytest.mark.parametrize(
    "field,value",
    [("review_status", "approved"), ("compiler_status", "passed"), ("calibrated_difficulty", 0.8)],
)
def test_author_cannot_add_approval_or_measurements(field, value):
    data = collection()
    data["tasks"][0][field] = value
    with pytest.raises(ValueError):
        PhysicsBenchmark(collections=[data])


def test_duplicate_targets_and_family_leakage_are_rejected():
    data = collection()
    other = copy.deepcopy(data["tasks"][0])
    other["id"] = "quantum.gates.other"
    data["tasks"].append(other)
    with pytest.raises(ValueError, match="duplicate.*source"):
        PhysicsBenchmark(collections=[data])
    other["target_source"] += "-- variant\n"
    other["split"] = "holdout"
    with pytest.raises(ValueError, match="family"):
        PhysicsBenchmark(collections=[data])


def test_relabelled_family_cannot_bypass_id_split_contract():
    data = collection()
    data["tasks"][0]["family"] = "gates_alias"
    with pytest.raises(ValueError, match="family"):
        PhysicsBenchmark(collections=[data])


def test_mutation_after_construction_is_revalidated_before_export_and_packaging(tmp_path):
    release = benchmark()
    release.collections[0].tasks.append(release.collections[0].tasks[0])
    with pytest.raises(ValueError):
        release.discovery_tasks("development")
    with pytest.raises(ValueError):
        prepare_benchmark(release, tmp_path / "bad", project_files=project())
    assert not (tmp_path / "bad").exists()


def test_negative_labels_cannot_confuse_semantic_holds_with_kernel_failures():
    data = collection()
    data["negative_cases"][0]["required_diagnostics"] = []
    with pytest.raises(ValueError, match="diagnostic"):
        PhysicsBenchmark(collections=[data])
    data = collection()
    data["negative_cases"][1]["semantic_change"] = " "
    with pytest.raises(ValueError, match="semantic"):
        PhysicsBenchmark(collections=[data])
    data = collection()
    data["negative_cases"][0]["parent_id"] = "classical.unknown.task"
    with pytest.raises(ValueError, match="parent"):
        PhysicsBenchmark(collections=[data])


def test_inventory_gaps_stay_explicit_and_difficulty_uncalibrated():
    summary = benchmark().inventory()
    assert not summary["required_inventory_complete"]
    assert summary["difficulty_status"] == "author_estimates_not_calibrated"
    assert summary["scientific_review"] == "pending"
    assert summary["production_qualified"] is False
    assert summary["counts"]["quantum"]["positive"] == 1
    assert summary["counts"]["classical"]["positive"] == 0


def test_loader_rejects_symlinks_and_invalid_json_with_coded_fault(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(collection()))
    link = tmp_path / "link.json"
    link.symlink_to(source)
    with pytest.raises(HarnessError) as error:
        load_physics_benchmarks([link])
    assert error.value.code == "physics_benchmark_invalid"
    source.write_text("{")
    with pytest.raises(HarnessError):
        load_physics_benchmarks([source])


def project():
    return {"lakefile.toml": b'name = "test"\n', "lean-toolchain": b"leanprover/lean4:v4.33.0\n"}


def test_packaging_is_exclusive_and_preserves_semantic_negative_meaning(tmp_path):
    destination = tmp_path / "packet"
    manifest = prepare_benchmark(benchmark(), destination, project_files=project())
    assert manifest["benchmark_sha256"] == benchmark().revision_digest()
    cases = json.loads((destination / "cases.json").read_bytes())["cases"]
    assert len(cases) == 3
    assert cases[1]["expected_status"] == "blocked"
    assert cases[2]["expected_status"] == "verified"
    review = json.loads((destination / "review.json").read_bytes())
    assert review["scientific_review"] == "pending" and review["production_qualified"] is False
    assert review["negative_cases"][1]["required_review_disposition"] == "hold_for_semantic_review"
    assert (destination / "REVIEW.md").is_file()
    with pytest.raises(FileExistsError):
        prepare_benchmark(benchmark(), destination, project_files=project())
    assert json.loads((destination / "manifest.json").read_bytes()) == manifest


def test_packaging_rejects_bad_project_before_creating_destination(tmp_path):
    destination = tmp_path / "packet"
    with pytest.raises(ValueError):
        prepare_benchmark(benchmark(), destination, project_files={"../escaped": b"bad"})
    assert not destination.exists() and not (tmp_path / "escaped").exists()


def test_evidence_missing_or_changed_release_cannot_be_marked_complete(tmp_path):
    destination = tmp_path / "packet"
    prepare_benchmark(benchmark(), destination, project_files=project())
    with pytest.raises(HarnessError) as error:
        assess_benchmark_reports(
            benchmark(),
            destination,
            image_metadata=tmp_path / "missing",
            kernel_report=tmp_path / "missing",
            independent_report=tmp_path / "missing",
        )
    assert error.value.code == "physics_benchmark_evidence_invalid"


def synthetic_reports(tmp_path):
    """Deliberately simulated checker transport for validation tests, never live evidence."""
    import hashlib

    from physharness.verification.boundary import (
        Environment,
        ResourceProfile,
        driver_digest,
        launcher_digest,
        seccomp_digest,
    )
    from physharness.verification.bundles import canonical_json
    from physharness.verification.resource_policy import policy_digest

    resources = ResourceProfile()
    resource_pins = {
        "resource_profile_sha256": resources.sha256,
        "resource_policy_sha256": policy_digest(),
    }

    release = benchmark()
    bundle = tmp_path / "packet"
    prepare_benchmark(release, bundle, project_files=project())
    metadata = {
        "image": "sha256:" + "a" * 64,
        "checker_versions": {
            "lean": "test-lean",
            "comparator": "test-comparator",
            "nanoda": "test-nanoda",
        },
        "binaries": {
            name: "b" * 64
            for name in ["lean", "lake", "comparator", "lean4export", "landrun", "nanoda"]
        },
    }
    meta = tmp_path / "metadata.json"
    meta.write_bytes(canonical_json(metadata))
    fixture_bytes = (bundle / "cases.json").read_bytes()
    fixture = json.loads(fixture_bytes)

    def sha(data):
        return hashlib.sha256(data).hexdigest()

    environment = Environment(
        **metadata, files={name: sha(content) for name, content in project().items()}
    )
    paths = []
    for independent in [False, True]:
        rows = []
        for case in fixture["cases"]:
            ok = case["expected_status"] == "verified"
            container = "physharness-check-" + uuid4().hex
            logs = "Building Challenge\nBuilding Solution\n"
            if ok:
                logs += "Lean default kernel accepts the solution\nYour solution is okay!\n"
                if independent:
                    logs += "Nanoda kernel accepts the solution\n"
            logs += "\n".join(case["required_diagnostic_substrings"])
            outcome = {
                "status": case["expected_status"],
                "assurance": ("independent_kernel" if independent else "kernel") if ok else "none",
                "code": case["expected_code"],
                "message": "Simulated unit-test outcome",
                "remediation": "No real checker executed",
                "target_digest": sha(json.dumps(case, sort_keys=True).encode()),
                "challenge_sha256": sha((bundle / case["challenge"]).read_bytes()),
                "candidate_sha256": sha((bundle / case["solution"]).read_bytes()),
                "environment_digest": sha(canonical_json(environment.model_dump())),
                "axioms": [],
                "checker_versions": metadata["checker_versions"],
                "diagnostics": {
                    **resource_pins,
                    "comparator_exit_code": 0 if ok else 1,
                    "comparator_output": logs,
                    "container_cleanup": {
                        "status": "removed",
                        "container_name": container,
                        "exit_code": 0,
                        "output": container + "\n",
                    },
                    "synthetic": True,
                },
            }
            rows.append({"id": case["id"], "outcome": outcome})
        report = {
            **resource_pins,
            "resource_profile": resources.model_dump(),
            "resource_profile_source_sha256": sha(
                Path("formal/verifier-resources.json").read_bytes()
            ),
            "status": "passed",
            "purpose": "engineering_smoke",
            "expert_review": "not_provided",
            "production_qualified": False,
            "image_digest": metadata["image"],
            "image_metadata_sha256": sha(meta.read_bytes()),
            "fixtures_sha256": sha(fixture_bytes),
            "independent_kernel_requested": independent,
            "driver_sha256": driver_digest(),
            "launcher_sha256": launcher_digest(),
            "seccomp_sha256": seccomp_digest(),
            "results": rows,
        }
        path = tmp_path / ("independent.json" if independent else "kernel.json")
        path.write_bytes(canonical_json(report))
        paths.append(path)
    return release, bundle, meta, *paths


@pytest.mark.parametrize(
    "mutation",
    ["profile", "profile_pin", "source_pin", "policy_pin", "row_profile", "row_policy", "missing"],
)
def test_benchmark_cannot_mix_or_omit_resource_evidence(tmp_path, mutation):
    release, bundle, meta, kernel, independent = synthetic_reports(tmp_path)
    report = json.loads(independent.read_bytes())
    if mutation == "profile":
        report["resource_profile"]["cpus"] = 2
    elif mutation == "profile_pin":
        report["resource_profile_sha256"] = "a" * 64
    elif mutation == "source_pin":
        report["resource_profile_source_sha256"] = "a" * 64
    elif mutation == "policy_pin":
        report["resource_policy_sha256"] = "a" * 64
    elif mutation == "row_profile":
        report["results"][0]["outcome"]["diagnostics"]["resource_profile_sha256"] = "a" * 64
    elif mutation == "row_policy":
        report["results"][0]["outcome"]["diagnostics"]["resource_policy_sha256"] = "a" * 64
    else:
        del report["resource_profile"]
    independent.write_text(json.dumps(report))
    with pytest.raises(HarnessError, match="Benchmark evidence"):
        assess_benchmark_reports(
            release,
            bundle,
            image_metadata=meta,
            kernel_report=kernel,
            independent_report=independent,
        )


def test_custom_profile_requires_explicit_assessment_input(tmp_path):
    from physharness.verification.boundary import ResourceProfile, digest

    release, bundle, meta, kernel, independent = synthetic_reports(tmp_path)
    resources = ResourceProfile(cpus=2)
    path = tmp_path / "resources.json"
    path.write_text(resources.model_dump_json(indent=2))
    for report_path in (kernel, independent):
        report = json.loads(report_path.read_bytes())
        report.update(
            resource_profile=resources.model_dump(),
            resource_profile_sha256=resources.sha256,
            resource_profile_source_sha256=digest(path.read_bytes()),
        )
        for row in report["results"]:
            row["outcome"]["diagnostics"]["resource_profile_sha256"] = resources.sha256
        report_path.write_text(json.dumps(report))
    arguments = dict(image_metadata=meta, kernel_report=kernel, independent_report=independent)
    with pytest.raises(HarnessError):
        assess_benchmark_reports(release, bundle, **arguments)
    assessment = assess_benchmark_reports(release, bundle, **arguments, resource_profile=path)
    assert assessment["resource_profile_sha256"] == resources.sha256
    assert assessment["scientific_review"] == "pending"


def test_mathematically_valid_semantic_mutation_still_awaits_review(tmp_path):
    release, bundle, meta, kernel, independent = synthetic_reports(tmp_path)
    assessment = assess_benchmark_reports(
        release, bundle, image_metadata=meta, kernel_report=kernel, independent_report=independent
    )
    assert assessment["mechanical_status"] == "expected_outcomes_observed_in_both_kernel_modes"
    assert assessment["semantic_hold_ids"] == ["quantum.gates.involution.meaning"]
    assert (
        assessment["scientific_review"] == "pending" and assessment["production_qualified"] is False
    )


@pytest.mark.parametrize(
    "mutation",
    ["lean_marker", "nanoda_marker", "cleanup_exit", "cleanup_output", "cleanup_absence"],
)
def test_positive_benchmark_requires_kernel_and_causal_cleanup_evidence(tmp_path, mutation):
    release, bundle, meta, kernel, independent = synthetic_reports(tmp_path)
    report = json.loads(independent.read_bytes())
    diagnostics = report["results"][0]["outcome"]["diagnostics"]
    if mutation == "lean_marker":
        diagnostics["comparator_output"] = diagnostics["comparator_output"].replace(
            "Lean default kernel accepts the solution", "Lean execution started"
        )
    elif mutation == "nanoda_marker":
        diagnostics["comparator_output"] = diagnostics["comparator_output"].replace(
            "Nanoda kernel accepts the solution", "Nanoda execution started"
        )
    elif mutation == "cleanup_exit":
        diagnostics["container_cleanup"]["exit_code"] = 1
    elif mutation == "cleanup_output":
        diagnostics["container_cleanup"]["output"] = "unrelated container\n"
    else:
        cleanup = diagnostics["container_cleanup"]
        diagnostics["container_cleanup"] = {
            "status": "confirmed_absent",
            "container_name": cleanup["container_name"],
            "absence_check": {"exit_code": 1, "output": ""},
        }
    independent.write_text(json.dumps(report))
    with pytest.raises(HarnessError, match="Benchmark evidence"):
        assess_benchmark_reports(
            release,
            bundle,
            image_metadata=meta,
            kernel_report=kernel,
            independent_report=independent,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "image",
        "mode",
        "source",
        "environment",
        "duplicate",
        "cleanup",
        "cause",
        "target",
        "assurance",
        "policy",
        "challenge_failure",
    ],
)
def test_changed_or_incomplete_observations_cannot_pass(tmp_path, mutation):
    release, bundle, meta, kernel, independent = synthetic_reports(tmp_path)
    report = json.loads(independent.read_bytes())
    first = report["results"][0]["outcome"]
    if mutation == "image":
        report["image_digest"] = "sha256:" + "c" * 64
    elif mutation == "mode":
        report["independent_kernel_requested"] = False
    elif mutation == "source":
        first["candidate_sha256"] = "c" * 64
    elif mutation == "environment":
        first["environment_digest"] = "c" * 64
    elif mutation == "duplicate":
        report["results"][1] = copy.deepcopy(report["results"][0])
    elif mutation == "cleanup":
        first["diagnostics"]["container_cleanup"]["status"] = "unknown"
    elif mutation == "cause":
        report["results"][1]["outcome"]["diagnostics"]["comparator_output"] = (
            "unrelated syntax error"
        )
    elif mutation == "challenge_failure":
        report["results"][1]["outcome"]["diagnostics"]["comparator_output"] = (
            "Building Challenge\nIllegal axiom detected: 'sorryAx'"
        )
    elif mutation == "target":
        first["target_digest"] = "c" * 64
    elif mutation == "assurance":
        first["assurance"] = "kernel"
    elif mutation == "policy":
        report["launcher_sha256"] = "c" * 64
    independent.write_text(json.dumps(report))
    with pytest.raises(HarnessError) as error:
        assess_benchmark_reports(
            release,
            bundle,
            image_metadata=meta,
            kernel_report=kernel,
            independent_report=independent,
        )
    assert error.value.code == "physics_benchmark_evidence_invalid"


def test_reference_or_review_packet_edits_invalidate_existing_evidence(tmp_path):
    release, bundle, meta, kernel, independent = synthetic_reports(tmp_path)
    review = bundle / "review.json"
    review.write_text(review.read_text().replace("pending", "approved"))
    with pytest.raises(HarnessError):
        assess_benchmark_reports(
            release,
            bundle,
            image_metadata=meta,
            kernel_report=kernel,
            independent_report=independent,
        )


@pytest.mark.parametrize(
    "mutation", ["manifest_approval", "manifest_extra", "project_array", "rows_array"]
)
def test_malformed_package_metadata_emits_coded_failure(tmp_path, mutation):
    release, bundle, meta, kernel, independent = synthetic_reports(tmp_path)
    if mutation in {"manifest_approval", "manifest_extra"}:
        path = bundle / "manifest.json"
        payload = json.loads(path.read_bytes())
        if mutation == "manifest_approval":
            payload["scientific_review"] = "approved"
            payload["production_qualified"] = True
        else:
            payload["review_decision"] = "approved"
    elif mutation == "project_array":
        path = bundle / "cases.json"
        payload = json.loads(path.read_bytes())
        payload["project_files"] = []
    else:
        path = independent
        payload = json.loads(path.read_bytes())
        payload["results"] = [None, None, None]
    path.write_text(json.dumps(payload))
    with pytest.raises(HarnessError) as error:
        assess_benchmark_reports(
            release,
            bundle,
            image_metadata=meta,
            kernel_report=kernel,
            independent_report=independent,
        )
    assert error.value.code == "physics_benchmark_evidence_invalid"
