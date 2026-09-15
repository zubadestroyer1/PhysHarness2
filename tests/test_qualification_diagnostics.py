"""Offline runner checks: these tests never start Docker or execute Lean."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runner():
    spec = importlib.util.spec_from_file_location(
        "qualification_diagnostics", ROOT / "infra/run_qualified_lean.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def negative_case(**changes):
    case = {
        "id": "sorry-attack",
        "expected_status": "blocked",
        "expected_code": "comparator_failed",
        "required_diagnostic_substrings": ["Illegal axiom detected: 'sorryAx'"],
    }
    return case | changes


def observed_failure(output):
    return SimpleNamespace(
        status="blocked",
        code="comparator_failed",
        diagnostics={"comparator_exit_code": 1, "comparator_output": output},
    )


def test_unrelated_syntax_error_cannot_count_as_axiom_rejection(runner):
    result = observed_failure(
        "warning: Challenge.lean:1:8: declaration uses `sorry`\n"
        "error: Solution.lean:2:10: unexpected token ':'\n"
        "uncaught exception: Child exited with 1\n"
    )
    with pytest.raises(RuntimeError, match="causal diagnostic"):
        runner.check_case_outcome(negative_case(), result)


@pytest.mark.parametrize("markers", [None, [], [""], ["   "], "sorryAx", [1]])
def test_negative_fixture_requires_nonempty_diagnostic_expectations(runner, markers):
    case = negative_case(required_diagnostic_substrings=markers)
    with pytest.raises(ValueError, match="diagnostic"):
        runner.check_case_outcome(case, observed_failure("Illegal axiom detected: 'sorryAx'"))


def test_all_diagnostic_markers_must_match_the_comparator_output(runner):
    case = negative_case(
        required_diagnostic_substrings=["permission denied", "file: /work/config.json"]
    )
    with pytest.raises(RuntimeError, match="causal diagnostic"):
        runner.check_case_outcome(case, observed_failure("permission denied\nfile: /other/file"))
    runner.check_case_outcome(case, observed_failure("permission denied\nfile: /work/config.json"))


def test_malformed_negative_case_fails_before_any_suite_execution(runner):
    cases = [
        {"id": "positive", "expected_status": "verified", "expected_code": "kernel_checked"},
        negative_case(required_diagnostic_substrings=[]),
    ]
    with pytest.raises(ValueError, match="diagnostic"):
        runner.check_cases(cases)


@pytest.mark.parametrize(
    "name", ["engineering-kernel-report.json", "engineering-independent-report.json"]
)
def test_archived_default_suite_matches_causal_expectations_offline(runner, name):
    fixture = json.loads((ROOT / "formal/adversarial/cases.json").read_bytes())
    runner.check_cases(fixture["cases"])
    cases = {case["id"]: case for case in fixture["cases"]}
    report = json.loads((ROOT / "work/acceptance-evidence" / name).read_bytes())
    assert set(cases) == {entry["id"] for entry in report["results"]}
    for entry in report["results"]:
        case = cases[entry["id"]]
        for source_key, outcome_key in [
            ("solution", "candidate_sha256"),
            ("challenge", "challenge_sha256"),
        ]:
            source = (ROOT / "formal/adversarial" / case[source_key]).read_bytes()
            assert hashlib.sha256(source).hexdigest() == entry["outcome"][outcome_key]
        runner.check_case_outcome(case, SimpleNamespace(**entry["outcome"]))


def test_archived_initializer_syntax_failure_remains_incomplete(runner):
    fixture = json.loads((ROOT / "formal/adversarial/process-exit-cases.json").read_bytes())
    case = next(case for case in fixture["cases"] if case["id"] == "InitializeExitZero")
    report = json.loads(
        (ROOT / "work/acceptance-evidence/engineering-process-exit-report.json").read_bytes()
    )
    entry = next(entry for entry in report["results"] if entry["id"] == case["id"])
    with pytest.raises(RuntimeError, match="causal diagnostic"):
        runner.check_case_outcome(case, SimpleNamespace(**entry["outcome"]))


def test_causal_mismatch_checkpoints_blocked_report_with_observed_output(runner, tmp_path):
    from physharness.verification import VerificationOutcome

    archived = json.loads(
        (ROOT / "work/acceptance-evidence/engineering-kernel-report.json").read_bytes()
    )
    source = next(entry["outcome"] for entry in archived["results"] if entry["id"] == "Sorry")
    source["diagnostics"]["comparator_output"] = "error: unrelated syntax failure"
    result = VerificationOutcome.model_validate(source)
    output = tmp_path / "report.json"

    def observe(path, report):
        runner._append_result(path, report, negative_case(), result)
        report["status"] = "passed"
        runner._write_report(path, report)

    with pytest.raises(RuntimeError, match="causal diagnostic"):
        runner._record_run(output, observe)
    recorded = json.loads(output.read_bytes())
    assert recorded["status"] == "blocked"
    assert recorded["production_qualified"] is False
    assert (
        recorded["results"][0]["required_diagnostic_substrings"]
        == negative_case()["required_diagnostic_substrings"]
    )
    assert recorded["results"][0]["outcome"]["diagnostics"]["comparator_output"] == (
        "error: unrelated syntax failure"
    )
