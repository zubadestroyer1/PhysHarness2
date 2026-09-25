"""Read-only local launch checks before a paid formal research team starts."""

import json
import subprocess
from pathlib import Path

import pytest
from test_core import setup_experiment

from physharness.config import ConfigurationError, Settings
from physharness.domain import ExperimentCreate, Principal
from physharness.errors import HarnessError
from physharness.orchestration.workspace_selection import configured_workspace_factory
from physharness.orchestration.workspace_tools import WorkspacePolicy
from physharness.run_control import run_preflight

IMAGE = "sha256:" + "a" * 64
GIB = 1024**3


def local_settings(capacity=3):
    return Settings(
        worker_workspace=WorkspacePolicy(
            template_id=IMAGE,
            environment_digest="b" * 64,
            qualification_report_sha256="c" * 64,
            timeout_seconds=60,
            cost_bound_usd="0",
            cost_source="local_no_external_invoice",
        ),
        worker_workspace_provider="local_docker",
        worker_docker_host="unix:///tmp/physharness-dedicated.sock",
        worker_image_digest=IMAGE,
        worker_max_active_workspaces=capacity,
    )


def fake_docker(
    monkeypatch,
    *,
    active=0,
    capacity_label="3",
    memory_gib=16,
    cpus=2,
    info_error=False,
    running_containers=None,
):
    monkeypatch.setattr(Path, "is_socket", lambda self: True)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if "image" in argv:
            output = IMAGE
        elif "ps" in argv:
            output = "\n".join(f"container-{index}\t{capacity_label}" for index in range(active))
        else:
            assert "info" in argv
            if info_error:
                raise subprocess.CalledProcessError(1, argv)
            output = json.dumps(
                {
                    "MemTotal": memory_gib * GIB,
                    "NCPU": cpus,
                    "ContainersRunning": active
                    if running_containers is None
                    else running_containers,
                }
            )
        return subprocess.CompletedProcess(argv, 0, stdout=output)

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_settings_validate_local_capacity():
    assert Settings().worker_max_active_workspaces == 1
    for value in (0, 101, True):
        with pytest.raises(ConfigurationError):
            Settings(worker_max_active_workspaces=value)


def test_local_preflight_reports_requested_capacity_memory_and_cpu(monkeypatch):
    calls = fake_docker(monkeypatch, active=1, memory_gib=16, cpus=2)
    factory = configured_workspace_factory(local_settings(capacity=3))
    result = factory.preflight(requested_concurrency=2)
    checks = {check["code"]: check for check in result["checks"]}
    assert checks["WORKSPACE_CAPACITY"]["status"] == "ready"
    assert checks["WORKSPACE_CAPACITY"]["available_slots"] == 2
    assert checks["WORKBENCH_MEMORY_INSUFFICIENT"]["status"] == "ready"
    assert checks["WORKBENCH_MEMORY_INSUFFICIENT"]["required_memory_bytes"] == 14 * GIB
    assert checks["WORKBENCH_CPU_OVERSUBSCRIBED"]["status"] == "warning"
    assert len(calls) == 3


def test_local_preflight_blocks_over_capacity_and_memory_without_start(monkeypatch):
    calls = fake_docker(monkeypatch, active=1, memory_gib=12)
    factory = configured_workspace_factory(local_settings(capacity=3))
    checks = factory.preflight(requested_concurrency=3)["checks"]
    assert {check["code"] for check in checks if check["status"] == "blocked"} == {
        "WORKSPACE_CAPACITY",
        "WORKBENCH_MEMORY_INSUFFICIENT",
    }
    assert not any("run" in argv or "start" in argv for argv in calls)


def test_local_preflight_fails_loudly_when_daemon_info_unavailable(monkeypatch):
    fake_docker(monkeypatch, info_error=True)
    factory = configured_workspace_factory(local_settings())
    with pytest.raises(HarnessError) as error:
        factory.preflight()
    assert error.value.code == "PROVIDER_UNAVAILABLE"


def test_local_preflight_rejects_active_capacity_policy_conflict(monkeypatch):
    fake_docker(monkeypatch, active=1, capacity_label="2")
    factory = configured_workspace_factory(local_settings(capacity=3))
    checks = {check["code"]: check for check in factory.preflight()["checks"]}
    assert checks["WORKSPACE_CAPACITY_POLICY_MISMATCH"]["status"] == "blocked"
    assert checks["WORKSPACE_CAPACITY"]["available_slots"] == 0


def test_local_preflight_rejects_unrelated_running_container(monkeypatch):
    fake_docker(monkeypatch, running_containers=1)
    factory = configured_workspace_factory(local_settings())
    checks = {check["code"]: check for check in factory.preflight()["checks"]}
    assert checks["WORKBENCH_DAEMON_NOT_DEDICATED"]["status"] == "blocked"


def test_run_preflight_exposes_local_checks_as_coded_blockers(lab):
    service, actor, _ = lab
    baseline, _ = setup_experiment(lab, concurrency=2)
    experiment = service.create_experiment(
        ExperimentCreate(
            campaign_id=baseline["campaign_id"],
            problem_id=baseline["problem_id"],
            models=baseline["models"],
            budget=baseline["budget"],
            execution_profile="formal-research",
        ),
        actor,
        "capacity-preflight-experiment",
    )
    operator = Principal(id="operator", project_id=actor.project_id, role="operator")
    observed = []

    def factory(*args, **kwargs):
        raise AssertionError("Preflight must not allocate a workbench")

    def preflight(*, requested_concurrency):
        observed.append(requested_concurrency)
        return {
            "checks": [
                {
                    "code": "WORKSPACE_CAPACITY",
                    "status": "blocked",
                    "available_slots": 1,
                    "remediation": "Reduce concurrency.",
                }
            ]
        }

    factory.provider = "local_docker"
    factory.preflight = preflight
    factory.capabilities = frozenset(
        {
            "isolated_workspace",
            "checkpoint_restore",
            "library_source_lookup",
            "library_source_search",
            "library_declaration_lookup",
            "lean_scratch",
            "scientific_command",
            "workspace_files",
            "exact_polynomial",
            "exact_matrix",
        }
    )
    result = run_preflight(
        service,
        operator,
        experiment["id"],
        prices={},
        environment={},
        workbench_factory=factory,
        requested_concurrency=2,
    )
    assert observed == [2]
    assert result["status"] == "blocked" and result["model_calls"] == 0
    assert "WORKSPACE_CAPACITY" in {block["code"] for block in result["blockers"]}
    assert any(check["code"] == "WORKSPACE_CAPACITY" for check in result["observations"])
