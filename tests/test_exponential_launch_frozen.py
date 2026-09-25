"""The paid-launch wrapper detects drift without reading a model credential."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "work/exponential-pilot-2026-09-24/launch_frozen.py"
SPEC = importlib.util.spec_from_file_location("exponential_launch_frozen", SCRIPT)
frozen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(frozen)


def fixture(tmp_path):
    for name in (
        "src/physharness/a.py",
        "infra/tool.py",
        "formal/environment.lock.json",
        "formal/verifier-resources.json",
        "formal/lean-toolchain",
        "formal/Dockerfile",
        "formal/workbench.Dockerfile",
        "pyproject.toml",
        "uv.lock",
        "work/exponential-pilot-2026-09-24/runner.py",
        "work/exponential-pilot-2026-09-24/prepare.py",
        "work/exponential-pilot-2026-09-24/evaluate.py",
        "work/exponential-pilot-2026-09-24/audit_export.py",
        "work/exponential-pilot-2026-09-24/operator_handoffs.py",
        "work/exponential-pilot-2026-09-24/launch_frozen.py",
        "work/parallel-pilot-2026-09-24/evaluate_pilot.py",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    state = tmp_path / ".state/experiment"
    bundle = state / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "Challenge.lean").write_text("theorem target : True := by trivial")
    for name in ("qualification.json", "challenge.lean", "prices.json", "worker.json"):
        (state / name).write_text(name)
    (state / "registry.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "resource_profile": str(tmp_path / "formal/verifier-resources.json"),
                        "config": {"bundle_directory": str(bundle)},
                    }
                ]
            }
        )
    )
    manifest = {
        "registry": str(state / "registry.json"),
        "worker_qualification_file": str(state / "worker.json"),
        "challenge_file": str(state / "challenge.lean"),
        "model_prices_file": str(state / "prices.json"),
        "attempts": [],
    }
    (state / "manifest.json").write_text(json.dumps(manifest))
    return state / "manifest.json", state / "qualification.json"


def test_freeze_detects_changed_and_added_source(tmp_path):
    manifest, qualification = fixture(tmp_path)
    baseline = frozen.collect(tmp_path, manifest, qualification)
    frozen.check(tmp_path, manifest, qualification, baseline)
    (tmp_path / "src/physharness/a.py").write_text("changed")
    with pytest.raises(frozen.FreezeError, match="drift"):
        frozen.check(tmp_path, manifest, qualification, baseline)
    (tmp_path / "src/physharness/a.py").write_text("src/physharness/a.py")
    (tmp_path / "src/physharness/new.py").write_text("new")
    with pytest.raises(frozen.FreezeError, match="drift"):
        frozen.check(tmp_path, manifest, qualification, baseline)
