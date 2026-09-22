"""Fixed probe schema/configuration tests. No Docker, Lean or host syscall probes run."""

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def synthetic_metadata(tmp_path):
    import json

    from physharness.verification.boundary import driver_digest

    # Synthetic host-transport input only; never rewrite historical image evidence.
    metadata = json.loads((ROOT / "formal/evidence/physics/image-metadata.json").read_bytes())
    metadata["driver_sha256"] = driver_digest()
    path = tmp_path / "synthetic-image-metadata.json"
    path.write_text(json.dumps(metadata))
    return path


def probe():
    path = ROOT / "infra/probe_verifier_boundary.py"
    assert path.exists(), "Fixed boundary probe has not been implemented"
    spec = importlib.util.spec_from_file_location("fixed_boundary_probe", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_probe_has_no_arbitrary_command_input():
    module = probe()
    command = module.container_command(
        "/usr/bin/docker",
        "sha256:" + "a" * 64,
        Path("/trusted-stage"),
        Path("/candidate-stage"),
        "physharness-check-" + "a" * 32,
    )
    assert command[-2:] == ["/trusted/probe.py", "--inside"]
    assert "--read-only" in command
    assert "--network=none" in command
    assert "--user=65532:65532" in command


def inspection():
    return {
        "Config": {
            "User": "65532:65532",
            "Env": ["PATH=/opt/lean/bin:/usr/bin"],
            "Entrypoint": ["/usr/bin/python3"],
            "Cmd": ["/trusted/probe.py", "--inside"],
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "SecurityOpt": ["no-new-privileges", "seccomp=/trusted-stage/seccomp.json"],
            "PidsLimit": 128,
            "Memory": 8 * 1024**3,
            "NanoCpus": 4000000000,
            "Tmpfs": {
                "/work": "rw,nosuid,nodev,size=1g,mode=1777",
                "/tmp": "rw,nosuid,nodev,size=256m,mode=1777",
            },
            "Binds": None,
            "Devices": [],
            "PidMode": "",
            "IpcMode": "private",
        },
        "Mounts": [
            {"Type": "bind", "Source": "/trusted-stage", "Destination": "/trusted", "RW": False},
            {
                "Type": "bind",
                "Source": "/candidate-stage",
                "Destination": "/candidate",
                "RW": False,
            },
        ],
    }


@pytest.mark.parametrize(
    "fault", ["rw", "socket", "secret", "privileged", "network", "env", "memory"]
)
def test_inspection_rejects_weakened_flags_or_unexpected_mounts(fault):
    module = probe()
    expected = inspection()
    image = {"Config": {"Env": expected["Config"]["Env"]}}
    changed = copy.deepcopy(expected)
    if fault == "rw":
        changed["Mounts"][0]["RW"] = True
    elif fault in {"socket", "secret"}:
        changed["Mounts"].append(
            {
                "Type": "bind",
                "Source": "/private/input",
                "Destination": "/var/run/docker.sock" if fault == "socket" else "/root/.ssh",
                "RW": False,
            }
        )
    elif fault == "privileged":
        changed["HostConfig"]["Privileged"] = True
    elif fault == "network":
        changed["HostConfig"]["NetworkMode"] = "host"
    elif fault == "env":
        changed["Config"]["Env"].append("OPENAI_API_KEY=do-not-log")
    elif fault == "memory":
        changed["HostConfig"]["Memory"] = 0
    with pytest.raises(ValueError):
        module.validate_inspection(changed, image, Path("/trusted-stage"), Path("/candidate-stage"))
    module.validate_inspection(expected, image, Path("/trusted-stage"), Path("/candidate-stage"))


def test_probe_flags_match_actual_verifier_launcher(tmp_path, monkeypatch):
    import json

    from test_verification import configured, fake_result

    from physharness.verification import boundary

    module = probe()
    verifier, request = configured(tmp_path)
    commands = []

    def fake_process(command, timeout, limit):
        if "run" in command:
            commands.append(command)
            return 0, json.dumps(fake_result(request)).encode()
        return 0, b""

    monkeypatch.setattr(boundary.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(boundary, "bounded_process", fake_process)
    verifier.verify(request)
    actual = commands[0]
    observed = module.container_command(
        "/usr/bin/docker",
        "sha256:" + "a" * 64,
        Path("/trusted-stage"),
        Path("/candidate-stage"),
        "physharness-check-" + "a" * 32,
    )

    def isolation_flags(command):
        options = command[: command.index("--entrypoint=/usr/bin/python3") + 1]
        return [token for token in options if token.startswith("--")]

    assert isolation_flags(actual) == isolation_flags(observed)


def test_interrupted_probe_checkpoints_blocked_status_and_confirms_cleanup(tmp_path, monkeypatch):
    import json

    from physharness.verification import boundary

    module = probe()
    metadata = synthetic_metadata(tmp_path)
    runtime = ROOT / "work/acceptance-evidence/runtime-identity.json"
    commands = []

    def interrupted(command, timeout, limit):
        commands.append(command)
        if "run" in command:
            raise KeyboardInterrupt("synthetic interruption")
        if "rm" in command:
            return 0, (command[-1] + "\n").encode()
        pytest.fail("Unexpected command in pure transport regression")

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(boundary, "bounded_process", interrupted)
    output = tmp_path / "probe.json"
    with pytest.raises(KeyboardInterrupt):
        module.run_probe(
            image_metadata=metadata,
            image_metadata_sha256=module.sha(metadata.read_bytes()),
            runtime_identity=runtime,
            runtime_identity_sha256=module.sha(runtime.read_bytes()),
            output=output,
        )
    report = json.loads(output.read_bytes())
    assert report["status"] == "blocked"
    assert report["error_type"] == "KeyboardInterrupt"
    assert report["container_cleanup"]["status"] == "removed"
    assert report["container_cleanup"]["container_name"] == commands[0][4]
    assert not report["production_qualified"]


def test_cleanup_failure_keeps_the_original_probe_failure_in_blocked_report(tmp_path, monkeypatch):
    import json

    from physharness.verification import boundary

    module = probe()
    metadata = synthetic_metadata(tmp_path)
    runtime = ROOT / "work/acceptance-evidence/runtime-identity.json"

    def failed_process(command, timeout, limit):
        if "run" in command:
            raise boundary.ExecutionFailure("checker_timeout", {"synthetic": True})
        return 1, b"synthetic unavailable daemon"

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(boundary, "bounded_process", failed_process)
    output = tmp_path / "probe.json"
    with pytest.raises(boundary.ExecutionFailure, match="container_cleanup_failed"):
        module.run_probe(
            image_metadata=metadata,
            image_metadata_sha256=module.sha(metadata.read_bytes()),
            runtime_identity=runtime,
            runtime_identity_sha256=module.sha(runtime.read_bytes()),
            output=output,
        )
    report = json.loads(output.read_bytes())
    assert report["status"] == "blocked"
    assert report["execution_failure"]["prior_failure"]["code"] == "checker_timeout"
    assert "container_cleanup" not in report
    assert not report["production_qualified"]


@pytest.mark.parametrize(
    "exit_code,raw",
    [(2, b"fixed probe missing trusted canary\n"), (0, b"invalid JSON from fixed probe\n")],
)
def test_probe_preserves_returned_exit_and_output_before_validation(
    tmp_path, monkeypatch, exit_code, raw
):
    import json

    from physharness.verification import boundary

    module = probe()
    metadata = synthetic_metadata(tmp_path)
    runtime = ROOT / "work/acceptance-evidence/runtime-identity.json"

    def process(command, timeout, limit):
        if "run" in command:
            return exit_code, raw
        if "rm" in command:
            return 0, (command[-1] + "\n").encode()
        pytest.fail("Unexpected command in synthetic probe")

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(boundary, "bounded_process", process)
    output = tmp_path / "probe.json"
    with pytest.raises(ValueError):
        module.run_probe(
            image_metadata=metadata,
            image_metadata_sha256=module.sha(metadata.read_bytes()),
            runtime_identity=runtime,
            runtime_identity_sha256=module.sha(runtime.read_bytes()),
            output=output,
        )
    report = json.loads(output.read_bytes())
    assert report["status"] == "blocked"
    assert report["probe_process"] == {"exit_code": exit_code, "output": raw.decode()}
    assert report["container_cleanup"]["status"] == "removed"


@pytest.mark.parametrize("kind", ["container", "image"])
@pytest.mark.parametrize("exit_code", [0, 17])
def test_failed_inspection_keeps_bounded_sanitized_context(tmp_path, monkeypatch, kind, exit_code):
    import json

    from physharness.verification import boundary

    module = probe()
    metadata = synthetic_metadata(tmp_path)
    runtime = ROOT / "work/acceptance-evidence/runtime-identity.json"
    image = json.loads(metadata.read_bytes())
    inner = {
        "protocol": "physharness-fixed-boundary-inner-v1",
        "probe_sha256": module.sha(Path(module.__file__).read_bytes()),
        "resource_profile_sha256": boundary.ResourceProfile().sha256,
        "resource_policy_sha256": boundary.resource_policy.policy_digest(),
        "driver_sha256": boundary.driver_digest(),
        "binaries": image["binaries"],
        "checks": {name: True for name in module.CHECKS - {"container_configuration"}},
        "observed": {},
    }

    def process(command, timeout, limit):
        if "run" in command:
            return 0, json.dumps(inner).encode()
        if "inspect" in command:
            if command[1] == kind:
                return (
                    exit_code,
                    b"Cannot inspect synthetic object\nDUMMY_SECRET=never-log\n\x1b[31m"
                    + b"x" * 5000,
                )
            return 0, b"[{}]"
        if "rm" in command:
            return 0, (command[-1] + "\n").encode()
        pytest.fail("Unexpected command in synthetic probe")

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(boundary, "bounded_process", process)
    output = tmp_path / "probe.json"
    with pytest.raises(ValueError, match="inspection"):
        module.run_probe(
            image_metadata=metadata,
            image_metadata_sha256=module.sha(metadata.read_bytes()),
            runtime_identity=runtime,
            runtime_identity_sha256=module.sha(runtime.read_bytes()),
            output=output,
        )
    report = json.loads(output.read_bytes())
    failure = report["inspection_failure"]
    assert failure["kind"] == kind
    assert failure["exit_code"] == exit_code
    assert "Cannot inspect synthetic object" in failure["output"]
    assert "never-log" not in failure["output"]
    assert "\x1b" not in failure["output"]
    assert len(failure["output"]) <= 4096
    assert report["status"] == "blocked"
    assert report["container_cleanup"]["status"] == "removed"


def test_inspection_environment_payload_is_withheld_even_on_failure():
    module = probe()
    diagnostic = module.inspection_diagnostic(b'{"Config":{"Env":["ORDINARY=never-log"]}}')
    assert "never-log" not in diagnostic
    assert "withheld" in diagnostic


def test_successful_inspection_environment_values_are_not_reported(tmp_path, monkeypatch):
    import json

    from physharness.verification import boundary

    module = probe()
    metadata = synthetic_metadata(tmp_path)
    runtime = ROOT / "work/acceptance-evidence/runtime-identity.json"
    image_metadata = json.loads(metadata.read_bytes())
    container = inspection()
    container["Config"]["Env"] = ["ORDINARY=successful-environment-value"]
    inner = {
        "protocol": "physharness-fixed-boundary-inner-v1",
        "probe_sha256": module.sha(Path(module.__file__).read_bytes()),
        "resource_profile_sha256": boundary.ResourceProfile().sha256,
        "resource_policy_sha256": boundary.resource_policy.policy_digest(),
        "driver_sha256": boundary.driver_digest(),
        "binaries": image_metadata["binaries"],
        "checks": {name: True for name in module.CHECKS - {"container_configuration"}},
        "observed": {},
    }

    def process(command, timeout, limit):
        if "run" in command:
            mounts = [command[index + 1] for index, arg in enumerate(command) if arg == "--mount"]
            for entry, arg in zip(container["Mounts"], mounts, strict=True):
                entry["Source"] = arg.split("source=", 1)[1].split(",", 1)[0]
            return 0, json.dumps(inner).encode()
        if "inspect" in command:
            value = container if command[1] == "container" else {"Config": container["Config"]}
            return 0, json.dumps([value]).encode()
        if "rm" in command:
            return 0, (command[-1] + "\n").encode()
        pytest.fail("Unexpected command in synthetic probe")

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(boundary, "bounded_process", process)
    output = tmp_path / "probe.json"
    report = module.run_probe(
        image_metadata=metadata,
        image_metadata_sha256=module.sha(metadata.read_bytes()),
        runtime_identity=runtime,
        runtime_identity_sha256=module.sha(runtime.read_bytes()),
        output=output,
    )
    assert report["status"] == "passed"
    assert "inspection_failure" not in report
    assert "successful-environment-value" not in output.read_text()
    assert report["probe_process"]["exit_code"] == 0
