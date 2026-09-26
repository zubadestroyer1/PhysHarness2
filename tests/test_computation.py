"""Bounded computations leave a reproducibility record that is evidence, never proof."""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_sharing import approaches

from physharness.domain import canonical_json
from physharness.errors import HarnessError
from physharness.execution.types import GUEST_PYTHON
from physharness.orchestration.computation import PACKAGES, PROBE, ComputationRunner

SCRIPT_SHA = "a" * 64
ENVIRONMENT = "e" * 64


def probe_result(sha=SCRIPT_SHA, packages=None, **overrides):
    versions = {name: None for name in PACKAGES}
    versions.update(packages or {"numpy": "1.24.2", "scipy": "1.10.1"})
    stdout = json.dumps({"script_sha256": sha, "python": "3.11.2", "packages": versions})
    return {"stdout": stdout + "\n", **overrides}


class FakeWorkspaceTools:
    def __init__(self, *results, timeout_seconds=600):
        self.policy = SimpleNamespace(
            template_id="physharness-workbench-v2",
            environment_digest=ENVIRONMENT,
            timeout_seconds=timeout_seconds,
        )
        self.results = list(results)
        self.calls = []

    async def run(self, arguments, operation_id):
        self.calls.append((arguments, operation_id))
        return {
            "operation_id": operation_id,
            "execution_id": "execution-1",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            **self.results.pop(0),
        }


def society(lab):
    service, _, experiment, _, (agent, _) = approaches(lab, "ideas")
    return service, agent, experiment


def runner(service, agent, *results, timeout_seconds=600):
    tools = FakeWorkspaceTools(*results, timeout_seconds=timeout_seconds)
    return ComputationRunner(tools, service, agent), tools


def arguments(**overrides):
    return {"path": "sim/run.py", "args": [], "timeout_seconds": 30, "seed": 7, **overrides}


def stored_record(service, agent, artifact_id):
    return json.loads(service.artifact_content(artifact_id, agent))


async def test_run_records_reproducibility_artifact(lab):
    service, agent, experiment = society(lab)
    computation, tools = runner(
        service, agent, probe_result(), {"stdout": "energy=1.5\n", "stderr": "note\n"}
    )
    result = await computation.run(
        arguments(args=["--steps", "10"], timeout_seconds=30, seed=7), "call-1"
    )

    (probe_args, probe_op), (run_args, run_op) = tools.calls
    assert probe_args["argv"] == [*GUEST_PYTHON, "-c", PROBE, "sim/run.py"]
    assert probe_args["cwd"] == "."
    assert probe_args["timeout_seconds"] <= 600
    assert run_args == {
        "argv": [
            "timeout",
            "--kill-after=5s",
            "30s",
            "env",
            "PYTHONHASHSEED=0",
            "PHYSHARNESS_SEED=7",
            "python3",
            "-X",
            "utf8",
            "sim/run.py",
            "--steps",
            "10",
        ],
        "cwd": ".",
        "timeout_seconds": 60,
    }
    assert probe_op != run_op and all(op.startswith("call-1") for op in (probe_op, run_op))

    assert set(result) == {
        "artifact_id",
        "exit_code",
        "stdout",
        "stderr",
        "truncated",
        "packages",
        "evidence_status",
        "timed_out",
    }
    assert result["exit_code"] == 0 and result["timed_out"] is False
    assert result["stdout"] == "energy=1.5\n" and result["stderr"] == "note\n"
    assert result["truncated"] is False
    assert set(result["packages"]) == set(PACKAGES)
    assert result["packages"]["numpy"] == "1.24.2" and result["packages"]["flint"] is None

    artifact = service.get_record("artifact", result["artifact_id"], agent)
    assert artifact["artifact_kind"] == "computation_record"
    assert artifact["media_type"] == "application/json"
    assert artifact["experiment_id"] == experiment["id"]
    assert artifact["provenance"] == {"branch_id": agent.branch_id}
    raw = service.artifact_content(result["artifact_id"], agent).decode()
    record = json.loads(raw)
    assert raw == canonical_json(record)
    assert record["script_path"] == "sim/run.py"
    assert record["script_sha256"] == SCRIPT_SHA
    assert record["args"] == ["--steps", "10"]
    assert record["seed"] == 7
    assert record["timeout_seconds"] == 30
    assert record["exit_code"] == 0 and record["timed_out"] is False
    assert isinstance(record["duration_seconds"], (int, float))
    assert record["duration_seconds"] >= 0
    assert record["stdout"] == "energy=1.5\n" and record["stderr"] == "note\n"
    assert record["stdout_sha256"] == hashlib.sha256(b"energy=1.5\n").hexdigest()
    assert record["stderr_sha256"] == hashlib.sha256(b"note\n").hexdigest()
    assert record["stdout_truncated"] is False and record["stderr_truncated"] is False
    assert record["python"] == "3.11.2"
    assert record["packages"] == result["packages"]
    assert record["workspace_template"] == "physharness-workbench-v2"
    assert record["environment_digest"] == ENVIRONMENT


async def test_seed_env_and_omission(lab):
    service, agent, _ = society(lab)
    computation, tools = runner(
        service, agent, probe_result(), {}, probe_result(), {}, probe_result(), {}
    )
    omitted = await computation.run(arguments(seed=None), "no-seed")
    zero = await computation.run(arguments(seed=0), "zero-seed")
    await computation.run({"path": "sim/run.py", "timeout_seconds": 30}, "defaults")

    no_seed_argv = tools.calls[1][0]["argv"]
    assert no_seed_argv == [
        "timeout",
        "--kill-after=5s",
        "30s",
        "env",
        "PYTHONHASHSEED=0",
        "python3",
        "-X",
        "utf8",
        "sim/run.py",
    ]
    assert not any(part.startswith("PHYSHARNESS_SEED") for part in no_seed_argv)
    assert "PHYSHARNESS_SEED=0" in tools.calls[3][0]["argv"]
    assert tools.calls[5][0]["argv"] == no_seed_argv
    assert stored_record(service, agent, omitted["artifact_id"])["seed"] is None
    assert stored_record(service, agent, zero["artifact_id"])["seed"] == 0

    for seed in (True, -1, 1.5, "7", 2**64):
        with pytest.raises(HarnessError) as error:
            await computation.run(arguments(seed=seed), f"bad-seed-{seed!r}")
        assert error.value.code == "INVALID_COMPUTATION"
    assert len(tools.calls) == 6


async def test_timeout_capped(lab):
    service, agent, _ = society(lab)
    computation, tools = runner(service, agent, probe_result(), {}, probe_result(), {})
    within = await computation.run(arguments(timeout_seconds=12.5), "within")
    capped = await computation.run(arguments(timeout_seconds=5000), "capped")
    assert tools.calls[1][0]["argv"][:3] == ["timeout", "--kill-after=5s", "12.5s"]
    assert tools.calls[1][0]["timeout_seconds"] == 42.5
    assert tools.calls[3][0]["argv"][:3] == ["timeout", "--kill-after=5s", "570s"]
    assert tools.calls[3][0]["timeout_seconds"] == 600
    assert stored_record(service, agent, within["artifact_id"])["timeout_seconds"] == 12.5
    assert stored_record(service, agent, capped["artifact_id"])["timeout_seconds"] == 570
    assert all(call[0]["timeout_seconds"] <= 600 for call in tools.calls)

    long_policy, long_tools = runner(service, agent, probe_result(), {}, timeout_seconds=86400)
    result = await long_policy.run(arguments(timeout_seconds=86400), "absolute-cap")
    assert long_tools.calls[1][0]["argv"][2] == "1800s"
    assert long_tools.calls[1][0]["timeout_seconds"] == 1830
    assert stored_record(service, agent, result["artifact_id"])["timeout_seconds"] == 1800

    edge, edge_tools = runner(service, agent, probe_result(), {}, timeout_seconds=31)
    await edge.run(arguments(timeout_seconds=10), "one-second-budget")
    assert edge_tools.calls[1][0]["argv"][2] == "1s"
    assert edge_tools.calls[1][0]["timeout_seconds"] == 31
    short, short_tools = runner(service, agent, timeout_seconds=30)
    with pytest.raises(HarnessError) as error:
        await short.run(arguments(timeout_seconds=10), "no-budget")
    assert error.value.code == "INVALID_COMPUTATION"
    assert short_tools.calls == []

    for timeout in (0, -3, float("nan"), float("inf"), True, "30", None):
        with pytest.raises(HarnessError) as error:
            await computation.run(arguments(timeout_seconds=timeout), f"bad-{timeout!r}")
        assert error.value.code == "INVALID_COMPUTATION"
    assert len(tools.calls) == 4


async def test_missing_script_error(lab):
    service, agent, _ = society(lab)
    computation, tools = runner(service, agent, probe_result(sha=None))
    with pytest.raises(HarnessError) as error:
        await computation.run(arguments(), "missing")
    assert error.value.code == "COMPUTATION_SCRIPT_MISSING"
    assert len(tools.calls) == 1  # the probe only; the script never runs

    for path in (
        "/work/sim/run.py",
        "../run.py",
        "sim/../run.py",
        "sim//run.py",
        "./run.py",
        "run.txt",
        "-m.py",
        "sim\\run.py",
        "a\x00.py",
        "x" * 1100 + ".py",
        None,
    ):
        with pytest.raises(HarnessError) as error:
            await computation.run(arguments(path=path), "bad-path")
        assert error.value.code == "INVALID_COMPUTATION"
    for args in (["x"] * 33, ["y" * 501], ["ok", 3], "--steps 10", ["nul\x00"]):
        with pytest.raises(HarnessError) as error:
            await computation.run(arguments(args=args), "bad-args")
        assert error.value.code == "INVALID_COMPUTATION"
    assert len(tools.calls) == 1

    failing, failing_tools = runner(
        service,
        agent,
        {"exit_code": 1, "stdout": "", "stderr": "python3: not found"},
        {"stdout": "not json"},
    )
    for key in ("probe-exit", "probe-garbage"):
        with pytest.raises(HarnessError) as error:
            await failing.run(arguments(), key)
        assert error.value.code == "COMPUTATION_PROBE_FAILED"
    assert len(failing_tools.calls) == 2


async def test_outputs_bounded_and_hashed(lab):
    stdout = "λ" * 70_000
    stderr = "w" * 20_000
    service, agent, _ = society(lab)
    computation, _ = runner(
        service,
        agent,
        probe_result(packages={"numpy": "9" * 500}),
        {"stdout": stdout, "stderr": stderr, "stdout_truncated": True, "exit_code": 3},
    )
    result = await computation.run(arguments(args=["a" * 500] * 32), "bounded")

    assert len(result["stdout"]) == 4000 and result["stdout"] == stdout[:4000]
    assert len(result["stderr"]) == 2000 and result["stderr"] == stderr[:2000]
    assert result["truncated"] is True
    assert len(result["packages"]["numpy"]) <= 100
    record = stored_record(service, agent, result["artifact_id"])
    assert record["exit_code"] == 3
    assert record["stdout"] == stdout[:16384] and record["stderr"] == stderr[:16384]
    assert record["stdout_sha256"] == hashlib.sha256(stdout.encode()).hexdigest()
    assert record["stderr_sha256"] == hashlib.sha256(stderr.encode()).hexdigest()
    assert record["stdout_truncated"] is True and record["stderr_truncated"] is True
    assert record["stdout_capture_truncated"] is True
    assert record["stderr_capture_truncated"] is False
    assert record["packages"] == result["packages"]

    small, _ = runner(
        service, agent, probe_result(), {"stdout": "ok", "stderr": "", "stderr_truncated": True}
    )
    flagged = await small.run(arguments(), "capture-flag")
    assert flagged["truncated"] is True
    small_record = stored_record(service, agent, flagged["artifact_id"])
    assert small_record["stdout_truncated"] is False
    assert small_record["stderr_truncated"] is True
    assert small_record["stderr_capture_truncated"] is True


async def test_record_is_evidence_not_proof(lab):
    service, agent, _ = society(lab)
    computation, _ = runner(
        service, agent, probe_result(), {"stdout": "all checks passed", "exit_code": 0}
    )
    result = await computation.run(arguments(), "evidence")
    assert result["evidence_status"] == "numerical_evidence_not_proof"
    record = stored_record(service, agent, result["artifact_id"])
    assert record["evidence_status"] == "numerical_evidence_not_proof"
    assert "accepted" not in json.dumps(record)
    assert not {"proof_status", "receipt_id", "status"} & set(record)
    artifact = service.get_record("artifact", result["artifact_id"], agent)
    assert artifact["artifact_kind"] == "computation_record"
    assert artifact["trusted_input"] is False


async def test_overrun_reports_timed_out(lab):
    service, agent, _ = society(lab)
    outcomes = {0: False, 1: False, 124: True, 137: True}
    results = []
    for code in outcomes:
        results += [probe_result(), {"exit_code": code, "stdout": f"exit {code}"}]
    computation, _ = runner(service, agent, *results)
    for code, expected in outcomes.items():
        result = await computation.run(arguments(), f"exit-{code}")
        assert result["exit_code"] == code and result["timed_out"] is expected
        assert stored_record(service, agent, result["artifact_id"])["timed_out"] is expected


async def test_replay_keys_record_on_content(lab, monkeypatch):
    from physharness.orchestration import computation as module

    ticks = iter([100.0, 101.25] * 3)
    monkeypatch.setattr(module, "monotonic", lambda: next(ticks))
    service, agent, _ = society(lab)
    computation, _ = runner(
        service,
        agent,
        probe_result(),
        {"stdout": "energy=1.5"},
        probe_result(),
        {"stdout": "energy=1.5"},
        probe_result(),
        {"stdout": "energy=1.7"},
    )
    first = await computation.run(arguments(), "replayed-call")
    identical = await computation.run(arguments(), "replayed-call")
    different = await computation.run(arguments(), "replayed-call")

    assert identical["artifact_id"] == first["artifact_id"]
    assert different["artifact_id"] != first["artifact_id"]
    assert stored_record(service, agent, first["artifact_id"])["stdout"] == "energy=1.5"
    assert stored_record(service, agent, different["artifact_id"])["stdout"] == "energy=1.7"
    assert stored_record(service, agent, first["artifact_id"])["duration_seconds"] == 1.25


def test_probe_reports_script_digest_and_package_versions(tmp_path):
    """Execute the real probe source with the host interpreter (no VM needed)."""
    script = tmp_path / "sim" / "run.py"
    script.parent.mkdir()
    script.write_bytes(b"print('hello')\n")
    # Workspace files must not masquerade as installed packages in the record.
    (tmp_path / "numpy.py").write_text("raise SystemExit('workspace module must not shadow')\n")
    (tmp_path / "z3.py").write_text("__version__ = 'workspace-shadow'\n")
    shadow = tmp_path / "cvxpy-99.0.dist-info"
    shadow.mkdir()
    (shadow / "METADATA").write_text("Metadata-Version: 2.1\nName: cvxpy\nVersion: 99.0\n")

    def probe(path):
        completed = subprocess.run(
            [sys.executable, "-c", PROBE, path],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        return json.loads(completed.stdout.strip().splitlines()[-1])

    observed = probe("sim/run.py")
    assert observed["script_sha256"] == hashlib.sha256(b"print('hello')\n").hexdigest()
    assert observed["python"] == sys.version.split()[0]
    assert set(observed["packages"]) == set(PACKAGES)
    assert all(value is None or isinstance(value, str) for value in observed["packages"].values())
    assert observed["packages"]["z3"] != "workspace-shadow"
    assert observed["packages"]["cvxpy"] != "99.0"
    assert probe("sim/missing.py")["script_sha256"] is None
    assert probe("sim")["script_sha256"] is None


ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = "TODO(pin-at-rebuild)"


def test_workbench_definition_gates_unpinned_builds(tmp_path):
    """The pinned definition passes its gate; any placeholder fails it (no Docker used)."""
    dockerfile = (ROOT / "formal/workbench-v2.Dockerfile").read_text()
    lock = (ROOT / "formal/workbench-requirements.lock").read_text()
    start = dockerfile.index("RUN if grep -v '^[[:space:]]*#' /opt/workbench/requirements.lock")
    gate = dockerfile[start + len("RUN ") : dockerfile.index("\n# ", start)]
    gate = gate.replace("/opt/workbench/requirements.lock", str(tmp_path / "requirements.lock"))

    def gate_status(lock_text, revision, digest):
        (tmp_path / "requirements.lock").write_text(lock_text)
        environment = {
            "PATH": "/usr/bin:/bin",
            "LEAN_REPL_REVISION": revision,
            "LEAN_REPL_SHA256": digest,
        }
        return subprocess.run(["/bin/sh", "-c", gate], env=environment, capture_output=True)

    revision = re.search(r'^ARG LEAN_REPL_REVISION="([^"]*)"$', dockerfile, re.M).group(1)
    digest = re.search(r'^ARG LEAN_REPL_SHA256="([^"]*)"$', dockerfile, re.M).group(1)
    version = re.search(r"^cvxpy==(\S+)", lock, re.M).group(1)
    wheel = re.search(r"--hash=sha256:([0-9a-f]{64})", lock).group(1)
    assert gate_status(lock, revision, digest).returncode == 0
    unpinned_version = lock.replace("cvxpy==" + version, "cvxpy==" + PLACEHOLDER, 1)
    assert gate_status(unpinned_version, revision, digest).returncode == 1
    assert gate_status(lock.replace(wheel, PLACEHOLDER, 1), revision, digest).returncode == 1
    assert gate_status(lock, PLACEHOLDER, digest).returncode == 1
    assert gate_status(lock, revision, PLACEHOLDER).returncode == 1
    assert gate_status(lock, revision, digest.upper()).returncode == 1

    import_check = next(line for line in dockerfile.splitlines() if "import numpy," in line)
    imported = import_check.split("import ", 1)[1].split(";", 1)[0].split(",")
    assert set(PACKAGES) <= set(imported)
    assert "/opt/lean-repl/.lake/build/bin/repl" in dockerfile
    assert "codeload.github.com/leanprover-community/repl/tar.gz/" in dockerfile
