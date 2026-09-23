"""Resource policy and failure-cause regressions; no Docker or Lean execution."""

import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def policy():
    assert importlib.util.find_spec("physharness.verification.resource_policy"), (
        "Shared resource policy is missing"
    )
    return importlib.import_module("physharness.verification.resource_policy")


@pytest.mark.parametrize(
    "change",
    [
        {"memory_bytes": 0},
        {"cpus": 0},
        {"comparator_timeout_seconds": 0},
        {"comparator_output_limit_bytes": 0},
        {"checker_slots": 2},
        {"cpus": True},
        {"memory_bytes": 100 * 1024**3},
        {"unexpected": 1},
    ],
)
def test_invalid_or_unbounded_profile_is_rejected(change):
    module = policy()
    with pytest.raises(ValueError):
        module.validate_profile(module.DEFAULT_PROFILE | change)


def test_profile_hash_binds_all_resource_values():
    module = policy()
    original = module.DEFAULT_PROFILE
    changed = original | {"cpus": 2}
    assert module.profile_digest(original) != module.profile_digest(changed)
    assert original["memory_bytes"] == 8 * 1024**3
    assert original["comparator_timeout_seconds"] == 600
    assert original["checker_slots"] == 1


def test_profile_cannot_be_changed_without_execution_pin(tmp_path):
    from test_verification import configured

    from physharness.verification.boundary import ResourceProfile

    verifier, request = configured(tmp_path)
    verifier.config = verifier.config.model_copy(update={"resources": ResourceProfile(cpus=2)})
    assert verifier.preflight(request).code == "trusted_bundle_invalid"


def test_policy_only_change_is_rejected_before_container_launch(tmp_path, monkeypatch):
    from test_verification import configured

    from physharness.verification import boundary

    verifier, request = configured(tmp_path)
    monkeypatch.setattr(boundary.resource_policy, "policy_digest", lambda: "0" * 64)
    monkeypatch.setattr(
        verifier,
        "_run_container",
        lambda *args: pytest.fail("stale resource policy reached container launch"),
    )
    assert verifier.preflight(request).code == "trusted_bundle_invalid"


def test_raw_profile_source_pin_is_checked_before_container_launch(tmp_path, monkeypatch):
    from test_verification import configured

    verifier, request = configured(tmp_path)
    verifier.config = verifier.config.model_copy(
        update={"resource_profile_source_sha256": "0" * 64}
    )
    monkeypatch.setattr(
        verifier,
        "_run_container",
        lambda *args: pytest.fail("stale resource source reached container launch"),
    )
    assert verifier.preflight(request).code == "trusted_bundle_invalid"


def test_confirmed_oom_requires_an_observed_counter_increase():
    module = policy()
    assert module.confirmed_oom({"oom_kill": 0}, {"oom_kill": 1})
    assert not module.confirmed_oom({"oom_kill": 1}, {"oom_kill": 1})
    assert not module.confirmed_oom(None, {"oom_kill": 1})
    assert not module.confirmed_oom({"oom": 0}, {"oom": 1})


def test_single_checker_slot_rejects_concurrent_use(tmp_path):
    from physharness.verification.boundary import ExecutionFailure, checker_slot

    with checker_slot(tmp_path / "slot"):
        with pytest.raises(ExecutionFailure, match="checker_busy"):
            with checker_slot(tmp_path / "slot"):
                pytest.fail("Two verifier processes acquired a single checker slot")


@pytest.mark.parametrize(
    "exit_code,logs,delta,expected",
    [
        (1, b"uncaught exception: Child exited with 137", 1, "resource_oom"),
        (137, b"", 1, "resource_oom"),
        (137, b"", 0, "comparator_terminated"),
        (1, b"uncaught exception: Child exited with 137", 0, "comparator_child_terminated"),
        (1, b"Illegal axiom detected: 'sorryAx'", 0, "comparator_failed"),
    ],
)
def test_resource_failure_causes_remain_blocked_and_do_not_infer_oom_from_text(
    exit_code, logs, delta, expected
):
    from physharness.verification import container_driver as driver

    assert hasattr(driver, "classify_execution"), "Resource cause classification is missing"
    status, code, diagnostics = driver.classify_execution(
        exit_code,
        logs,
        {"status": "observed", "events": {"oom_kill": 0}},
        {"status": "observed", "events": {"oom_kill": delta}},
    )
    assert (status, code) == ("blocked", expected)
    assert diagnostics["oom_confirmed"] is bool(delta)


def test_driver_timeout_retains_partial_output_and_uses_profile(tmp_path, monkeypatch):
    import subprocess
    import sys

    from physharness.verification import container_driver as driver

    assert hasattr(driver, "ComparatorFailure"), "Typed driver failure is missing"
    popen = subprocess.Popen

    def temporary_cwd(*args, **kwargs):
        kwargs["cwd"] = tmp_path
        return popen(*args, **kwargs)

    monkeypatch.setattr(driver.subprocess, "Popen", temporary_cwd)
    profile = policy().DEFAULT_PROFILE | {"comparator_timeout_seconds": 1}
    with pytest.raises(driver.ComparatorFailure) as failure:
        driver.run_comparator(
            [
                sys.executable,
                "-c",
                "import time; print('fixed timeout control', flush=True); time.sleep(3)",
            ],
            {},
            profile,
        )
    assert failure.value.code == "comparator_timeout"
    assert "fixed timeout control" in failure.value.diagnostics["comparator_output"]


@pytest.mark.parametrize("oom", [False, True])
def test_outer_container_failure_preserves_state_and_successful_cleanup(tmp_path, monkeypatch, oom):
    from test_verification import configured

    from physharness.verification import boundary

    verifier, request = configured(tmp_path)

    def process(command, timeout, limit):
        if "run" in command:
            return 137, b"fixed killed container diagnostic"
        if "inspect" in command:
            return 0, json.dumps({"OOMKilled": oom, "ExitCode": 137, "Error": ""}).encode()
        if "rm" in command:
            return 0, (command[-1] + "\n").encode()
        pytest.fail("Unexpected synthetic command")

    monkeypatch.setattr(boundary.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(boundary, "bounded_process", process)
    result = verifier.verify(request)
    assert result.code == ("resource_oom" if oom else "container_failed")
    assert result.status == "blocked"
    assert result.diagnostics["container_state"]["oom_killed"] is oom
    assert result.diagnostics["container_cleanup"]["status"] == "removed"
    assert result.diagnostics["output"] == "fixed killed container diagnostic"


@pytest.mark.parametrize("oom", [False, True])
def test_outer_container_success_captures_state_before_cleanup(tmp_path, monkeypatch, oom):
    from test_verification import configured, fake_result

    from physharness.verification import boundary

    verifier, request = configured(tmp_path)
    receipt = fake_result(request)
    calls = []

    def process(command, timeout, limit):
        calls.append(command)
        if "run" in command:
            return 0, json.dumps(receipt).encode()
        if "inspect" in command:
            return 0, json.dumps({"OOMKilled": oom, "ExitCode": 0, "Error": ""}).encode()
        if "rm" in command:
            return 0, (command[-1] + "\n").encode()
        pytest.fail("Unexpected synthetic command")

    monkeypatch.setattr(boundary.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(boundary, "bounded_process", process)
    result = verifier.verify(request)
    assert result.code == ("resource_oom" if oom else "kernel_checked")
    assert result.diagnostics["container_state"]["oom_killed"] is oom
    assert result.diagnostics["container_cleanup"]["status"] == "removed"
    assert next(i for i, call in enumerate(calls) if "inspect" in call) < next(
        i for i, call in enumerate(calls) if "rm" in call
    )


def test_observed_oom_prevents_success_even_if_comparator_returned_zero(
    tmp_path, monkeypatch, capsys
):
    from test_verification import run_synthetic_driver

    from physharness.verification import container_driver as driver

    observations = iter(
        [
            {"status": "observed", "events": {"oom_kill": 0}},
            {"status": "observed", "events": {"oom_kill": 1}},
        ]
    )
    monkeypatch.setattr(driver.resource_policy, "read_memory_events", lambda: next(observations))
    _, result = run_synthetic_driver(tmp_path, monkeypatch, capsys)
    assert result["status"] == "blocked" and result["code"] == "resource_oom"
    assert result["diagnostics"]["comparator_exit_code"] == 0
    assert result["axioms"] == [] and result["independent_kernel"] is False
