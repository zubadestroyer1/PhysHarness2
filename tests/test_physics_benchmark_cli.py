"""CLI failure contracts and separation of evaluator material from worker inputs."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def invoke(*arguments):
    return subprocess.run(
        [sys.executable, str(ROOT / "tools/physics_benchmark.py"), *map(str, arguments)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
    )


def test_inventory_requires_both_programs_but_never_grants_review():
    result = invoke("inventory")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["required_inventory_complete"]
    assert payload["scientific_review"] == "pending"
    assert not payload["production_qualified"]
    incomplete = invoke("--collection", "benchmarks/physics/quantum.json", "inventory")
    assert incomplete.returncode == 2
    assert not json.loads(incomplete.stdout)["required_inventory_complete"]


def test_target_export_is_fresh_and_omits_evaluator_answers(tmp_path):
    destination = tmp_path / "worker.json"
    result = invoke("export", "--split", "holdout", "--output", destination)
    assert result.returncode == 0, result.stderr
    payload = json.loads(destination.read_text())
    assert payload["tasks"]
    for task in payload["tasks"]:
        assert set(task) == {
            "id",
            "title",
            "statement",
            "assumptions",
            "physical_scope",
            "target_theorem",
            "target_source",
            "program",
        }
    previous = destination.read_bytes()
    duplicate = invoke("export", "--split", "development", "--output", destination)
    assert duplicate.returncode == 1
    assert json.loads(duplicate.stderr)["error"]["code"] == "physics_benchmark_command_failed"
    assert destination.read_bytes() == previous


def test_prepare_has_pending_review_and_existing_runner_contract(tmp_path):
    destination = tmp_path / "evaluator"
    result = invoke("prepare", "--output", destination)
    assert result.returncode == 0, result.stderr
    fixture = json.loads((destination / "cases.json").read_text())
    assert len(fixture["cases"]) == 60
    assert "lakefile.toml" in fixture["project_files"]
    assert json.loads((destination / "review.json").read_text())["scientific_review"] == "pending"
    assert "Pending human review" in (destination / "REVIEW.md").read_text()


def test_missing_input_emits_coded_diagnostic():
    result = invoke("--collection", "absent.json", "inventory")
    assert result.returncode == 1
    error = json.loads(result.stderr)["error"]
    assert error["code"] == "physics_benchmark_invalid"
    assert error["details"]["reason"]
