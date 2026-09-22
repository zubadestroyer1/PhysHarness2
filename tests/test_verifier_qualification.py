"""Synthetic report mutations exercise validation, never qualify an actual deployment."""

import copy
import hashlib
import importlib
import json
import shutil
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]


def api():
    assert importlib.util.find_spec("physharness.verification.qualification"), (
        "Scoped evidence qualification is not implemented"
    )
    return importlib.import_module("physharness.verification.qualification")


def test_qualification_api_reports_evidence_without_acceptance_authority():
    q = api()
    assert callable(q.capture_scope)
    assert callable(q.assess_qualification)
    assert not hasattr(q, "approve_deployment")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_json(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(data, indent=2).encode() + b"\n")
    return api().EvidenceFile(path=name, sha256=sha(path.read_bytes()))


@pytest.fixture
def deployment(tmp_path):
    q = api()
    matrix = json.loads((ROOT / "formal/qualification-matrix.json").read_bytes())
    names = {"formal/qualification-matrix.json", *matrix["input_files"]}
    for group in matrix["regression_groups"]:
        names.update(node.split("::")[0] for node in group["nodeids"])
    for suite in matrix["suites"]:
        names.add(suite["fixture"])
        fixture = json.loads((ROOT / suite["fixture"]).read_bytes())
        base = Path(suite["fixture"]).parent
        names.update(str(base / name) for name in fixture["project_files"].values())
        names.update(
            str(base / case[key]) for case in fixture["cases"] for key in ["challenge", "solution"]
        )
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, path)
    metadata = json.loads((ROOT / "formal/evidence/physics/image-metadata.json").read_bytes())
    # Synthetic scope only: historical image evidence remains immutable.
    metadata["driver_sha256"] = sha(
        (tmp_path / "src/physharness/verification/container_driver.py").read_bytes()
    )
    runtime = json.loads((ROOT / "work/acceptance-evidence/runtime-identity.json").read_bytes())
    image_ref = write_json(tmp_path, "metadata.json", metadata)
    runtime_ref = write_json(tmp_path, "runtime.json", runtime)
    scope = q.capture_scope(tmp_path, image_metadata=image_ref, runtime_identity=runtime_ref)
    return tmp_path, scope, matrix


def suite_report(root, scope, suite, mode):
    fixture = json.loads((root / suite["fixture"]).read_bytes())
    base = (root / suite["fixture"]).parent
    environment = {
        "image": scope.image_digest,
        "checker_versions": scope.checker_versions,
        "binaries": scope.binaries,
        "files": {
            name: sha((base / source).read_bytes())
            for name, source in fixture["project_files"].items()
        },
    }
    results = []
    for case in fixture["cases"]:
        positive = case["expected_status"] == "verified"
        container = "physharness-check-" + uuid4().hex
        logs = "\n".join(case.get("required_diagnostic_substrings", []))
        if positive:
            logs = "Lean default kernel accepts the solution\nYour solution is okay!"
            if mode == "independent_kernel":
                logs += "\nNanoda kernel accepts the solution"
        results.append(
            {
                "id": case["id"],
                "expected_status": case["expected_status"],
                "expected_code": case["expected_code"],
                "required_diagnostic_substrings": case.get("required_diagnostic_substrings", []),
                "outcome": {
                    "status": case["expected_status"],
                    "code": case["expected_code"],
                    "assurance": mode if positive else "none",
                    "message": "synthetic unit fixture",
                    "remediation": "",
                    "target_digest": sha(json.dumps(case, sort_keys=True).encode()),
                    "challenge_sha256": sha((base / case["challenge"]).read_bytes()),
                    "candidate_sha256": sha((base / case["solution"]).read_bytes()),
                    "environment_digest": sha(canonical(environment)),
                    "axioms": ["propext", "Quot.sound", "Classical.choice"] if positive else [],
                    "checker_versions": scope.checker_versions,
                    "diagnostics": {
                        "resource_profile_sha256": scope.resource_profile_sha256,
                        "resource_policy_sha256": scope.inputs[
                            "src/physharness/verification/resource_policy.py"
                        ],
                        "oom_confirmed": False,
                        "memory_events_before": {"status": "observed", "events": {"oom_kill": 0}},
                        "memory_events_after": {"status": "observed", "events": {"oom_kill": 0}},
                        "comparator_exit_code": 0 if positive else 1,
                        "comparator_output": logs,
                        "container_cleanup": {
                            "status": "removed",
                            "container_name": container,
                            "exit_code": 0,
                            "output": container + "\n",
                        },
                    },
                },
            }
        )
    return {
        "status": "passed",
        "run_id": str(uuid4()),
        "purpose": "engineering_smoke",
        "expert_review": "not_provided",
        "production_qualified": False,
        "image_digest": scope.image_digest,
        "image_metadata_sha256": scope.image_metadata.sha256,
        "runtime_identity_sha256": scope.runtime_identity.sha256,
        "resource_profile": scope.resources.model_dump(),
        "resource_profile_sha256": scope.resource_profile_sha256,
        "resource_profile_source_sha256": scope.resource_profile_file.sha256,
        "resource_policy_sha256": scope.inputs["src/physharness/verification/resource_policy.py"],
        "runner_sha256": scope.inputs["infra/run_qualified_lean.py"],
        "fixtures_sha256": scope.inputs[suite["fixture"]],
        "launcher_sha256": scope.launcher_sha256,
        "driver_sha256": scope.driver_sha256,
        "seccomp_sha256": scope.seccomp_sha256,
        "independent_kernel_requested": mode == "independent_kernel",
        "results": results,
    }


def all_evidence(root, scope, matrix):
    return [
        api().SuiteEvidence(
            suite_id=suite["id"],
            report=write_json(
                root, f"evidence/{suite['id']}-{mode}.json", suite_report(root, scope, suite, mode)
            ),
        )
        for suite in matrix["suites"]
        for mode in suite["modes"]
    ]


def boundary_evidence(root, scope):
    container = "physharness-check-" + uuid4().hex
    matrix = json.loads((root / "formal/qualification-matrix.json").read_bytes())
    report = {
        "protocol": "physharness-boundary-evidence-v1",
        "purpose": "fixed_boundary_probe",
        "status": "passed",
        "run_id": str(uuid4()),
        "production_qualified": False,
        "expert_review": "not_provided",
        "image_digest": scope.image_digest,
        "image_metadata_sha256": scope.image_metadata.sha256,
        "runtime_identity_sha256": scope.runtime_identity.sha256,
        "resource_profile": scope.resources.model_dump(),
        "resource_profile_sha256": scope.resource_profile_sha256,
        "resource_profile_source_sha256": scope.resource_profile_file.sha256,
        "resource_policy_sha256": scope.inputs["src/physharness/verification/resource_policy.py"],
        "probe_sha256": scope.inputs["infra/probe_verifier_boundary.py"],
        "launcher_sha256": scope.launcher_sha256,
        "driver_sha256": scope.driver_sha256,
        "seccomp_sha256": scope.seccomp_sha256,
        "checks": {name: True for name in matrix["boundary_probe"]["required_checks"]},
        "observed": {
            "memory_events": {"status": "observed", "events": {"oom_kill": 0}},
            "unix_socket_denied_errno": 1,
            "inet_socket_denied_errno": 1,
            "trusted_write_errno": 30,
            "candidate_write_errno": 30,
            "root_write_errno": 30,
        },
        "container_cleanup": {
            "status": "removed",
            "container_name": container,
            "exit_code": 0,
            "output": container + "\n",
        },
    }
    report["probe_process"] = {
        "exit_code": 0,
        "output": json.dumps(
            {
                "protocol": "physharness-fixed-boundary-inner-v1",
                "checks": report["checks"],
                "observed": report["observed"],
                "probe_sha256": report["probe_sha256"],
                "resource_profile_sha256": report["resource_profile_sha256"],
                "resource_policy_sha256": report["resource_policy_sha256"],
                "driver_sha256": report["driver_sha256"],
                "binaries": scope.binaries,
            }
        )
        + "\n",
    }
    return api().BoundaryEvidence(report=write_json(root, "boundary.json", report))


def test_fixed_boundary_observations_are_required(deployment):
    root, scope, matrix = deployment
    packet = api().assess_qualification(
        root,
        scope=scope,
        evidence=all_evidence(root, scope, matrix),
        regressions=regressions(root, scope, matrix),
    )
    assert packet.mechanical_status == "incomplete"
    assert any(row.id == "fixed-boundary" and row.status == "missing" for row in packet.checks)


@pytest.mark.parametrize("fault", ["missing", "control", "errno", "cleanup", "pin", "approval"])
def test_fixed_boundary_booleans_alone_cannot_supply_evidence(deployment, fault):
    root, scope, matrix = deployment
    boundary = boundary_evidence(root, scope)
    report = json.loads((root / boundary.report.path).read_bytes())
    if fault == "missing":
        report["checks"].pop("seccomp_filter")
    elif fault == "control":
        report["checks"]["tmp_write_control"] = False
    elif fault == "errno":
        report["observed"]["unix_socket_denied_errno"] = 2
    elif fault == "cleanup":
        report["container_cleanup"]["output"] = "unrelated"
    elif fault == "pin":
        report["probe_sha256"] = "0" * 64
    elif fault == "approval":
        report["deployment_approval"] = "approved"
    boundary = api().BoundaryEvidence(report=write_json(root, "boundary.json", report))
    packet = api().assess_qualification(
        root,
        scope=scope,
        evidence=all_evidence(root, scope, matrix),
        regressions=regressions(root, scope, matrix),
        boundary=boundary,
    )
    assert packet.mechanical_status == "invalid"
    assert not packet.production_qualified


@pytest.mark.parametrize("fault", ["missing_process", "process_exit", "process_output", "mismatch"])
def test_fixed_boundary_requires_successful_matching_probe_process(deployment, fault):
    root, scope, matrix = deployment
    boundary = boundary_evidence(root, scope)
    report = json.loads((root / boundary.report.path).read_bytes())
    if fault == "missing_process":
        del report["probe_process"]
    elif fault == "process_exit":
        report["probe_process"]["exit_code"] = 1
    elif fault == "process_output":
        report["probe_process"]["output"] = "not JSON"
    else:
        inner = json.loads(report["probe_process"]["output"])
        inner["checks"]["nonroot"] = False
        report["probe_process"]["output"] = json.dumps(inner)
    boundary = api().BoundaryEvidence(report=write_json(root, "boundary.json", report))
    packet = api().assess_qualification(
        root,
        scope=scope,
        evidence=all_evidence(root, scope, matrix),
        regressions=regressions(root, scope, matrix),
        boundary=boundary,
    )
    assert packet.mechanical_status == "invalid"
    assert not packet.production_qualified


def regressions(root, scope, matrix, *, omit=None, skipped=None):
    suite = ET.Element("testsuite")
    for group in matrix["regression_groups"]:
        for node in group["nodeids"]:
            if node == omit:
                continue
            path, name = node.split("::")
            case = ET.SubElement(
                suite, "testcase", classname=path[:-3].replace("/", "."), name=name
            )
            if node == skipped:
                ET.SubElement(case, "skipped")
    path = root / "regressions.xml"
    path.write_bytes(ET.tostring(suite))
    report = write_json(
        root,
        "regressions.json",
        {
            "protocol": "physharness-regression-evidence-v1",
            "purpose": "engineering_regression",
            "production_qualified": False,
            "scope_sha256": scope.sha256,
            "exit_code": 0,
            "command": ["pytest", "--junitxml=regressions.xml"],
            "junit": {"path": path.name, "sha256": sha(path.read_bytes())},
        },
    )
    return api().RegressionEvidence(report=report)


def test_complete_synthetic_evidence_never_grants_approval(deployment):
    root, scope, matrix = deployment
    result = api().assess_qualification(
        root,
        scope=scope,
        evidence=all_evidence(root, scope, matrix),
        regressions=regressions(root, scope, matrix),
        boundary=boundary_evidence(root, scope),
    )
    assert result.mechanical_status == "satisfied"
    assert result.production_qualified is False
    assert result.deployment_approval == "pending"
    assert result.scientific_review == "not_provided"
    assert "process-exit" in {gap.id for gap in result.coverage_gaps}
    assert not hasattr(result, "verify")


def test_readable_packet_keeps_coverage_gaps_and_pending_authority_visible(deployment):
    root, scope, _ = deployment
    packet = api().assess_qualification(root, scope=scope, evidence=[])
    assert hasattr(api(), "render_review_packet"), "Readable operator packet is missing"
    rendered = api().render_review_packet(packet)
    assert "Deployment approval: pending" in rendered
    assert "Production qualified: false" in rendered
    assert "process-exit" in rendered
    assert scope.image_digest in rendered
    assert scope.sha256 in rendered


@pytest.mark.parametrize(
    "field,value",
    [
        ("image_digest", "sha256:" + "0" * 64),
        ("driver_sha256", "0" * 64),
        ("launcher_sha256", "0" * 64),
        ("seccomp_sha256", "0" * 64),
        ("runtime_identity_sha256", "0" * 64),
        ("runner_sha256", "0" * 64),
        ("fixtures_sha256", "0" * 64),
        ("production_qualified", True),
        ("expert_review", "approved"),
        ("status", "blocked"),
    ],
)
def test_stale_or_approval_shaped_report_fails(deployment, field, value):
    root, scope, matrix = deployment
    report = suite_report(root, scope, matrix["suites"][0], "kernel")
    report[field] = value
    ref = api().SuiteEvidence(suite_id="core", report=write_json(root, "changed.json", report))
    result = api().assess_qualification(root, scope=scope, evidence=[ref])
    assert result.mechanical_status == "invalid"
    assert any(check.status == "invalid" for check in result.checks)
    assert not result.production_qualified


@pytest.mark.parametrize(
    "field", ["target_digest", "challenge_sha256", "candidate_sha256", "environment_digest"]
)
def test_outcome_identity_must_match_current_fixture(deployment, field):
    root, scope, matrix = deployment
    report = suite_report(root, scope, matrix["suites"][0], "independent_kernel")
    report["results"][0]["outcome"][field] = "0" * 64
    ref = api().SuiteEvidence(suite_id="core", report=write_json(root, "changed.json", report))
    assert (
        api().assess_qualification(root, scope=scope, evidence=[ref]).mechanical_status == "invalid"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "syntax",
        "no_positive",
        "duplicate",
        "assurance",
        "cleanup",
        "preflight",
        "versions",
        "legacy_runtime",
    ],
)
def test_incomplete_or_unrelated_observations_cannot_satisfy_matrix(deployment, fault):
    root, scope, matrix = deployment
    report = suite_report(root, scope, matrix["suites"][0], "independent_kernel")
    rows = report["results"]
    if fault == "syntax":
        rows[2]["outcome"]["diagnostics"]["comparator_output"] = "unexpected token"
    elif fault == "no_positive":
        report["results"] = rows[2:]
    elif fault == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif fault == "assurance":
        rows[0]["outcome"]["assurance"] = "kernel"
    elif fault == "cleanup":
        rows[0]["outcome"]["diagnostics"]["container_cleanup"]["output"] = "other-container\n"
    elif fault == "preflight":
        rows[2]["outcome"]["code"] = "boundary_unqualified"
    elif fault == "versions":
        rows[2]["outcome"]["checker_versions"] = {"lean": "invented"}
    elif fault == "legacy_runtime":
        report.pop("runtime_identity_sha256")
    ref = api().SuiteEvidence(suite_id="core", report=write_json(root, "changed.json", report))
    assert (
        api().assess_qualification(root, scope=scope, evidence=[ref]).mechanical_status == "invalid"
    )


def test_changed_input_after_capture_invalidates_even_unchanged_report(deployment):
    root, scope, matrix = deployment
    evidence = all_evidence(root, scope, matrix)
    path = root / "formal/adversarial/ExtraAxiom.lean"
    path.write_bytes(path.read_bytes() + b"\n-- changed\n")
    packet = api().assess_qualification(root, scope=scope, evidence=evidence)
    assert packet.mechanical_status == "invalid"
    assert packet.checks[0].id == "current-inputs"


def test_duplicate_mode_or_run_id_does_not_fill_missing_mode(deployment):
    root, scope, matrix = deployment
    evidence = all_evidence(root, scope, matrix)
    packet = api().assess_qualification(root, scope=scope, evidence=[evidence[0], evidence[0]])
    assert packet.mechanical_status == "invalid"


@pytest.mark.parametrize("fault", ["missing", "skipped"])
def test_missing_or_skipped_authority_test_is_not_a_pass(deployment, fault):
    root, scope, matrix = deployment
    node = matrix["regression_groups"][1]["nodeids"][0]
    ref = regressions(root, scope, matrix, **{"omit" if fault == "missing" else "skipped": node})
    packet = api().assess_qualification(
        root, scope=scope, evidence=all_evidence(root, scope, matrix), regressions=ref
    )
    assert packet.mechanical_status in {"invalid", "incomplete"}
    assert any(
        check.id == "authority-and-atomicity" and check.status != "observed"
        for check in packet.checks
    )


def test_reports_are_pinned_and_never_follow_symlinks(deployment):
    root, scope, matrix = deployment
    evidence = all_evidence(root, scope, matrix)
    path = root / evidence[0].report.path
    path.write_bytes(b"{}")
    assert (
        api().assess_qualification(root, scope=scope, evidence=evidence).mechanical_status
        == "invalid"
    )
    path.unlink()
    path.symlink_to(ROOT / "formal/qualification.json")
    assert (
        api().assess_qualification(root, scope=scope, evidence=evidence).mechanical_status
        == "invalid"
    )


def test_no_reports_produce_explicit_missing_requirements(deployment):
    root, scope, _ = deployment
    packet = api().assess_qualification(root, scope=scope, evidence=[])
    assert packet.mechanical_status == "incomplete"
    assert {
        "core/kernel",
        "core/independent_kernel",
        "library/kernel",
        "library/independent_kernel",
    } <= {row.id for row in packet.checks if row.status == "missing"}


def test_junit_mutation_during_assessment_invalidates_packet(deployment, monkeypatch):
    root, scope, matrix = deployment
    evidence = all_evidence(root, scope, matrix)
    regression = regressions(root, scope, matrix)
    original = api()._regressions

    def mutate_after_read(*args):
        checked = original(*args)
        (root / "regressions.xml").write_bytes(b"<testsuite />")
        return checked

    monkeypatch.setattr(api(), "_regressions", mutate_after_read)
    packet = api().assess_qualification(
        root, scope=scope, evidence=evidence, regressions=regression
    )
    assert packet.mechanical_status == "invalid"


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "qualification_runtime_runner", ROOT / "infra/run_qualified_lean.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


def test_runner_records_explicit_runtime_and_current_runner_before_execution(
    deployment, monkeypatch
):
    root, scope, matrix = deployment
    runner = load_runner()

    class StopBeforeExecution(Exception):
        pass

    def stop(*args, **kwargs):
        raise StopBeforeExecution

    monkeypatch.setattr(runner, "create_bundle", stop)
    output = root / "runner-report.json"
    with pytest.raises(StopBeforeExecution):
        runner.run_engineering(
            output,
            root / scope.image_metadata.path,
            root / matrix["suites"][0]["fixture"],
            True,
            runtime_identity=root / scope.runtime_identity.path,
        )
    report = json.loads(output.read_bytes())
    assert report["runtime_identity_sha256"] == scope.runtime_identity.sha256
    assert report["runner_sha256"] == sha((ROOT / "infra/run_qualified_lean.py").read_bytes())
    assert report["status"] == "blocked"
    assert report["results"] == []


def test_runner_rejects_nonlinux_runtime_without_attempting_a_bundle(deployment, monkeypatch):
    root, scope, matrix = deployment
    runtime = json.loads((root / scope.runtime_identity.path).read_bytes())
    runtime["OSType"] = "darwin"
    (root / scope.runtime_identity.path).write_text(json.dumps(runtime))
    runner = load_runner()

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid runtime identity must fail before bundle creation")

    monkeypatch.setattr(runner, "create_bundle", forbidden)
    with pytest.raises(ValueError, match="Linux"):
        runner.run_engineering(
            root / "runner-report.json",
            root / scope.image_metadata.path,
            root / matrix["suites"][0]["fixture"],
            True,
            runtime_identity=root / scope.runtime_identity.path,
        )


def test_runner_snapshot_cannot_escape_the_fixture_directory(deployment, monkeypatch):
    root, scope, matrix = deployment
    fixture_path = root / matrix["suites"][0]["fixture"]
    fixture = json.loads(fixture_path.read_bytes())
    fixture["project_files"]["lakefile.toml"] = "../outside.toml"
    (fixture_path.parent.parent / "outside.toml").write_text('name = "outside"')
    fixture_path.write_text(json.dumps(fixture))
    runner = load_runner()

    def forbidden(*args, **kwargs):
        pytest.fail("Escaping fixture paths must fail before bundle creation")

    monkeypatch.setattr(runner, "create_bundle", forbidden)
    with pytest.raises(ValueError):
        runner.run_engineering(
            root / "runner-report.json",
            root / scope.image_metadata.path,
            fixture_path,
            True,
            runtime_identity=root / scope.runtime_identity.path,
        )


@pytest.mark.parametrize("version", ["4.33.01", "14.33.0", "4.33.0-rc1"])
def test_image_lean_version_must_be_the_exact_locked_version(deployment, version):
    root, scope, _ = deployment
    metadata = json.loads((root / scope.image_metadata.path).read_bytes())
    metadata["checker_versions"]["lean"] = metadata["checker_versions"]["lean"].replace(
        "4.33.0", version
    )
    ref = write_json(root, "changed-metadata.json", metadata)
    with pytest.raises(ValueError, match="Lean version"):
        api().capture_scope(root, image_metadata=ref, runtime_identity=scope.runtime_identity)


@pytest.mark.parametrize("fault", ["assurance", "nanoda", "lean", "success"])
def test_runner_requires_requested_positive_kernel_evidence_before_pass(deployment, fault):
    from physharness.verification import VerificationOutcome

    root, scope, matrix = deployment
    runner = load_runner()
    suite = matrix["suites"][0]
    fixture = json.loads((root / suite["fixture"]).read_bytes())
    case = fixture["cases"][0]
    source = suite_report(root, scope, suite, "independent_kernel")["results"][0]["outcome"]
    if fault == "assurance":
        source["assurance"] = "kernel"
    else:
        marker = {
            "nanoda": "Nanoda kernel accepts the solution",
            "lean": "Lean default kernel accepts the solution",
            "success": "Your solution is okay!",
        }[fault]
        source["diagnostics"]["comparator_output"] = source["diagnostics"][
            "comparator_output"
        ].replace(marker, "unrelated text")
    result = VerificationOutcome.model_validate(source)

    def attempt(output, report):
        runner._append_result(output, report, case, result, publication=True)
        report["status"] = "passed"

    output = root / "downgrade.json"
    with pytest.raises(RuntimeError, match="positive kernel"):
        runner._record_run(output, attempt)
    assert json.loads(output.read_bytes())["status"] == "blocked"


@pytest.mark.parametrize("field", ["expert_review", "deployment_approval", "scientific_review"])
def test_regression_evidence_cannot_carry_approval_flags(deployment, field):
    root, scope, matrix = deployment
    regression = regressions(root, scope, matrix)
    report = json.loads((root / regression.report.path).read_bytes())
    report[field] = "approved"
    regression = api().RegressionEvidence(report=write_json(root, "regressions.json", report))
    packet = api().assess_qualification(
        root,
        scope=scope,
        evidence=all_evidence(root, scope, matrix),
        regressions=regression,
        boundary=boundary_evidence(root, scope),
    )
    assert packet.mechanical_status == "invalid"


def test_engineering_runner_propagates_requested_mode_to_case_validation(deployment, monkeypatch):
    from types import SimpleNamespace

    from physharness.verification import VerificationOutcome

    root, scope, matrix = deployment
    runner = load_runner()
    suite = matrix["suites"][0]
    source = suite_report(root, scope, suite, "kernel")["results"][0]["outcome"]
    result = VerificationOutcome.model_validate(source)

    class StubVerifier:
        def __init__(self, config):
            pass

        def run(self, request):
            assert request.publication is True
            return SimpleNamespace(outcome=result)

    monkeypatch.setattr(runner, "EngineeringVerifier", StubVerifier)
    output = root / "mode-report.json"
    with pytest.raises(RuntimeError, match="positive kernel"):
        runner.run_engineering(
            output,
            root / scope.image_metadata.path,
            root / suite["fixture"],
            True,
            runtime_identity=root / scope.runtime_identity.path,
        )
    report = json.loads(output.read_bytes())
    assert report["status"] == "blocked"
    assert report["results"][0]["outcome"]["assurance"] == "kernel"


def test_exact_parameterized_guard_node_cannot_be_replaced_by_another_case(deployment):
    root, scope, matrix = deployment
    node = (
        "tests/test_verification.py::"
        "test_container_driver_rejects_manifest_identity_tamper[protocol]"
    )
    matrix["regression_groups"][0]["nodeids"] = [node]
    api().Matrix.model_validate(matrix)
    write_json(root, "formal/qualification-matrix.json", matrix)
    scope = api().capture_scope(
        root, image_metadata=scope.image_metadata, runtime_identity=scope.runtime_identity
    )
    regression = regressions(root, scope, matrix)
    junit = root / "regressions.xml"
    junit.write_bytes(junit.read_bytes().replace(b"[protocol]", b"[target_digest]"))
    report = json.loads((root / regression.report.path).read_bytes())
    report["junit"]["sha256"] = sha(junit.read_bytes())
    regression = api().RegressionEvidence(report=write_json(root, "regressions.json", report))
    packet = api().assess_qualification(
        root,
        scope=scope,
        evidence=all_evidence(root, scope, matrix),
        regressions=regression,
        boundary=boundary_evidence(root, scope),
    )
    assert packet.mechanical_status == "incomplete"
    assert any(
        row.id == "transport-and-isolation" and row.status == "missing" for row in packet.checks
    )


def test_historical_real_image_driver_is_not_recast_as_current_scope(deployment):
    root, scope, _ = deployment
    historical = json.loads((ROOT / "formal/evidence/physics/image-metadata.json").read_bytes())
    assert historical["driver_sha256"] != scope.driver_sha256
    ref = write_json(root, "historical-metadata.json", historical)
    with pytest.raises(ValueError, match="Image driver"):
        api().capture_scope(root, image_metadata=ref, runtime_identity=scope.runtime_identity)


@pytest.mark.parametrize("fault", ["profile", "source", "policy", "outcome", "oom"])
def test_reports_cannot_mix_profiles_or_count_resource_failure_as_case_evidence(deployment, fault):
    root, scope, matrix = deployment
    report = suite_report(root, scope, matrix["suites"][0], "kernel")
    if fault == "profile":
        report["resource_profile"]["cpus"] = 2
    elif fault == "source":
        report["resource_profile_source_sha256"] = "0" * 64
    elif fault == "policy":
        report["resource_policy_sha256"] = "0" * 64
    elif fault == "outcome":
        report["results"][0]["outcome"]["diagnostics"]["resource_profile_sha256"] = "0" * 64
    else:
        report["results"][0]["outcome"]["diagnostics"]["oom_confirmed"] = True
    item = api().SuiteEvidence(suite_id="core", report=write_json(root, "mixed.json", report))
    packet = api().assess_qualification(root, scope=scope, evidence=[item])
    assert packet.mechanical_status == "invalid"


def test_scoped_resource_source_mutation_invalidates_packet(deployment):
    root, scope, _ = deployment
    path = root / scope.resource_profile_file.path
    path.write_bytes(path.read_bytes() + b"\n")
    packet = api().assess_qualification(root, scope=scope, evidence=[])
    assert packet.mechanical_status == "invalid"
