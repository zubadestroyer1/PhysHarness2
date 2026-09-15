"""Fixed benign boundary observations, scheduled only by the deployment operator.

The inner probe has no command/source input and runs no Lean. Report success is
engineering evidence only, never approval or proof of exhaustive containment.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import shutil
import socket
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

CANARY = b"physharness fixed boundary canary v1\n"
CHECKS = {
    "nonroot",
    "no_capabilities",
    "no_new_privileges",
    "seccomp_filter",
    "unix_socket_denied",
    "inet_socket_denied",
    "trusted_canary_intact",
    "candidate_canary_intact",
    "trusted_write_denied",
    "candidate_write_denied",
    "root_write_denied",
    "work_write_control",
    "tmp_write_control",
    "no_docker_socket",
    "container_configuration",
}
BINARY_PATHS = {
    "lean": "/opt/lean/bin/lean",
    "lake": "/opt/lean/bin/lake",
    "comparator": "/opt/verifier/bin/comparator",
    "lean4export": "/opt/verifier/bin/lean4export",
    "landrun": "/opt/verifier/bin/landrun",
    "nanoda": "/opt/verifier/bin/nanoda_bin",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inside_probe():
    """Observe only fixed process/filesystem/socket properties in the isolated container."""
    checks = {}
    observed = {}
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    checks["nonroot"] = os.getuid() == 65532 and os.getgid() == 65532
    checks["no_capabilities"] = all(
        int(status[field].strip(), 16) == 0
        for field in ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"]
    )
    checks["no_new_privileges"] = status["NoNewPrivs"].strip() == "1"
    checks["seccomp_filter"] = status["Seccomp"].strip() == "2"
    for name, family in [
        ("unix_socket_denied", socket.AF_UNIX),
        ("inet_socket_denied", socket.AF_INET),
    ]:
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
        except OSError as error:
            observed[name + "_errno"] = error.errno
            checks[name] = error.errno in {errno.EPERM, errno.EACCES}
        else:
            sock.close()
            checks[name] = False
    for prefix in ["trusted", "candidate"]:
        canary = Path("/" + prefix) / "canary"
        checks[prefix + "_canary_intact"] = canary.read_bytes() == CANARY
        try:
            with canary.open("ab") as stream:
                stream.write(b"fixed write probe")
        except OSError as error:
            observed[prefix + "_write_errno"] = error.errno
            checks[prefix + "_write_denied"] = error.errno in {
                errno.EROFS,
                errno.EACCES,
                errno.EPERM,
            }
        else:
            checks[prefix + "_write_denied"] = False
        checks[prefix + "_canary_intact"] &= canary.read_bytes() == CANARY
    root_probe = Path("/opt/physharness/fixed-boundary-write-canary")
    try:
        with root_probe.open("xb") as stream:
            stream.write(CANARY)
    except OSError as error:
        observed["root_write_errno"] = error.errno
        checks["root_write_denied"] = error.errno in {errno.EROFS, errno.EACCES, errno.EPERM}
    else:
        root_probe.unlink()
        checks["root_write_denied"] = False
    for place in ["work", "tmp"]:
        path = Path("/" + place) / "fixed-boundary-write-control"
        with path.open("xb") as stream:
            stream.write(CANARY)
        checks[place + "_write_control"] = path.read_bytes() == CANARY
        path.unlink()
    checks["no_docker_socket"] = not any(
        Path(name).exists()
        for name in ["/var/run/docker.sock", "/run/docker.sock", "/run/podman/podman.sock"]
    )
    return {
        "protocol": "physharness-fixed-boundary-inner-v1",
        "checks": checks,
        "observed": observed,
        "probe_sha256": sha(Path(__file__).read_bytes()),
        "driver_sha256": sha(Path("/opt/physharness/container_driver.py").read_bytes()),
        "binaries": {name: sha(Path(path).read_bytes()) for name, path in BINARY_PATHS.items()},
    }


def container_command(docker, image, trusted, candidate, name):
    return [
        docker,
        "run",
        "--pull=never",
        "--name",
        name,
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--security-opt",
        f"seccomp={trusted / 'seccomp.json'}",
        "--user=65532:65532",
        "--pids-limit=128",
        "--memory=2g",
        "--cpus=2",
        "--tmpfs=/work:rw,nosuid,nodev,size=1g,mode=1777",
        "--tmpfs=/tmp:rw,nosuid,nodev,size=256m,mode=1777",
        "--mount",
        f"type=bind,source={trusted},target=/trusted,readonly",
        "--mount",
        f"type=bind,source={candidate},target=/candidate,readonly",
        "--entrypoint=/usr/bin/python3",
        image,
        "/trusted/probe.py",
        "--inside",
    ]


def validate_inspection(container, image, trusted, candidate):
    """Check actual Docker configuration without logging environment values."""
    config, host = container["Config"], container["HostConfig"]
    expected = {
        "NetworkMode": "none",
        "ReadonlyRootfs": True,
        "Privileged": False,
        "PidsLimit": 128,
        "Memory": 2 * 1024**3,
        "NanoCpus": 2_000_000_000,
    }
    if any(host.get(key) != value for key, value in expected.items()):
        raise ValueError("Container isolation/resource configuration differs")
    if (
        host.get("CapDrop") != ["ALL"]
        or host.get("CapAdd")
        or host.get("Devices")
        or host.get("Binds")
        or host.get("PidMode")
        or host.get("IpcMode") not in {"private", ""}
    ):
        raise ValueError("Unexpected capabilities, devices, binds or host namespace")
    security = host.get("SecurityOpt", [])
    if len(security) != 2 or not any(
        item in {"no-new-privileges", "no-new-privileges=true"} for item in security
    ):
        raise ValueError("No-new-privileges or seccomp configuration differs")
    if not any(item.startswith("seccomp=") for item in security):
        raise ValueError("Seccomp profile is missing")
    if host.get("Tmpfs") != {
        "/work": "rw,nosuid,nodev,size=1g,mode=1777",
        "/tmp": "rw,nosuid,nodev,size=256m,mode=1777",
    }:
        raise ValueError("Temporary filesystem configuration differs")
    mounts = container.get("Mounts", [])
    binds = {entry.get("Destination"): entry for entry in mounts if entry.get("Type") == "bind"}
    if set(binds) != {"/trusted", "/candidate"}:
        raise ValueError("Unexpected or missing bind mount, including credential/socket mounts")
    for target, source in [("/trusted", trusted), ("/candidate", candidate)]:
        entry = binds[target]
        if entry.get("RW") is not False or entry.get("Source") != str(source):
            raise ValueError("A canary mount source or read-only property differs")
    if len(binds) != sum(entry.get("Type") == "bind" for entry in mounts):
        raise ValueError("Duplicate bind mounts")
    if any(
        entry.get("Type") != "bind"
        and not (entry.get("Type") == "tmpfs" and entry.get("Destination") in {"/work", "/tmp"})
        for entry in mounts
    ):
        raise ValueError("Unexpected additional container mount")
    if (
        config.get("User") != "65532:65532"
        or config.get("Entrypoint") != ["/usr/bin/python3"]
        or config.get("Cmd") != ["/trusted/probe.py", "--inside"]
    ):
        raise ValueError("Probe process identity or command differs")
    environment = config.get("Env", [])
    if environment != image["Config"].get("Env", []):
        raise ValueError("Host environment values were forwarded to the container")
    if any(
        any(
            word in entry.partition("=")[0].upper()
            for word in ["TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY"]
        )
        for entry in environment
    ):
        raise ValueError("Image environment contains credential-like keys")


def inspection_diagnostic(data):
    """Retain bounded error context, withholding environment dumps and credential lines."""
    text = data.decode("utf-8", errors="replace")
    if re.search(r'(?i)"Env"\s*:', text):
        return "Inspection payload containing environment values withheld"
    text = re.sub(
        r"(?im)^.*(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY|AUTHORIZATION)\s*[=:].*$",
        "[credential-like diagnostic line redacted]",
        text,
    )
    text = re.sub(r"://[^/\s@:]+:[^@\s/]+@", "://[redacted]@", text)
    text = "".join(char if char.isprintable() or char in "\n\t" else "?" for char in text)
    return text[:4096]


def _write(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".boundary-probe-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_probe(
    *, image_metadata, image_metadata_sha256, runtime_identity, runtime_identity_sha256, output
):
    from physharness.verification.boundary import (
        ComparatorVerifier,
        Environment,
        ExecutionFailure,
        bounded_process,
        driver_digest,
        launcher_digest,
        safe_read,
        seccomp_bytes,
        seccomp_digest,
    )
    from physharness.verification.qualification import validate_runtime_identity

    report = {
        "protocol": "physharness-boundary-evidence-v1",
        "purpose": "fixed_boundary_probe",
        "run_id": str(uuid4()),
        "status": "running",
        "production_qualified": False,
        "expert_review": "not_provided",
        "checks": {},
    }
    _write(output, report)
    try:
        metadata_bytes = safe_read(image_metadata.parent, image_metadata.name)
        runtime_bytes = safe_read(runtime_identity.parent, runtime_identity.name)
        if (
            sha(metadata_bytes) != image_metadata_sha256
            or sha(runtime_bytes) != runtime_identity_sha256
        ):
            raise ValueError("Pinned image/runtime input hash differs")
        validate_runtime_identity(runtime_bytes)
        metadata = json.loads(metadata_bytes)
        env = Environment(
            image=metadata["image"],
            checker_versions=metadata["checker_versions"],
            binaries=metadata["binaries"],
            files={},
        )
        if (
            set(env.binaries) != set(BINARY_PATHS)
            or metadata.get("driver_sha256") != driver_digest()
        ):
            raise ValueError("Complete image binaries and current embedded driver are required")
        source = Path(__file__).read_bytes()
        report.update(
            image_digest=env.image,
            image_metadata_sha256=image_metadata_sha256,
            runtime_identity_sha256=runtime_identity_sha256,
            probe_sha256=sha(source),
            driver_sha256=driver_digest(),
            launcher_sha256=launcher_digest(),
            seccomp_sha256=seccomp_digest(),
        )
        _write(output, report)
        docker = shutil.which("docker")
        if docker is None or Path(docker).name != "docker":
            raise ValueError("Docker executable is unavailable")
        name = "physharness-check-" + uuid4().hex
        with tempfile.TemporaryDirectory(prefix="physharness-boundary-probe-") as temporary:
            staging = Path(temporary)
            trusted, candidate = staging / "trusted", staging / "candidate"
            for path in [trusted, candidate]:
                path.mkdir(mode=0o755)
                path.chmod(0o755)
                (path / "canary").write_bytes(CANARY)
                (path / "canary").chmod(0o444)
            (trusted / "probe.py").write_bytes(source)
            (trusted / "seccomp.json").write_bytes(seccomp_bytes())
            for path in trusted.iterdir():
                path.chmod(0o444)
            prior_failure = None
            try:
                code, data = bounded_process(
                    container_command(docker, env.image, trusted, candidate, name), 45, 64_000
                )
                report["probe_process"] = {
                    "exit_code": code,
                    "output": data.decode("utf-8", errors="replace"),
                }
                _write(output, report)
                if code:
                    raise ValueError("Fixed probe process did not complete successfully")
                observed = json.loads(data)
                if (
                    observed.get("protocol") != "physharness-fixed-boundary-inner-v1"
                    or observed.get("probe_sha256") != sha(source)
                    or observed.get("driver_sha256") != driver_digest()
                    or observed.get("binaries") != env.binaries
                ):
                    raise ValueError("Inner fixed-probe provenance differs")
                report["checks"] = observed["checks"]
                report["observed"] = observed["observed"]
                for kind, key in [("container", name), ("image", env.image)]:
                    try:
                        code, raw = bounded_process([docker, kind, "inspect", key], 10, 256_000)
                    except ExecutionFailure as error:
                        report["inspection_failure"] = {
                            "kind": kind,
                            "exit_code": None,
                            "code": error.code,
                            "output": inspection_diagnostic(json.dumps(error.diagnostics).encode()),
                        }
                        raise
                    try:
                        if code:
                            raise ValueError(f"Docker {kind} inspection failed")
                        inspected = json.loads(raw)
                        if (
                            not isinstance(inspected, list)
                            or len(inspected) != 1
                            or not isinstance(inspected[0], dict)
                        ):
                            raise ValueError(f"Docker {kind} inspection returned an invalid object")
                    except (ValueError, TypeError) as error:
                        report["inspection_failure"] = {
                            "kind": kind,
                            "exit_code": code,
                            "output": inspection_diagnostic(raw),
                        }
                        raise ValueError(
                            f"Docker {kind} inspection failed or was malformed"
                        ) from error
                    if kind == "container":
                        container_inspect = inspected[0]
                    else:
                        image_inspect = inspected[0]
                validate_inspection(container_inspect, image_inspect, trusted, candidate)
                report["checks"]["container_configuration"] = True
                if set(report["checks"]) != CHECKS or any(
                    value is not True for value in report["checks"].values()
                ):
                    raise ValueError("A mandatory fixed boundary observation failed")
                if any((path / "canary").read_bytes() != CANARY for path in [trusted, candidate]):
                    raise ValueError("Host canary bytes changed")
            except BaseException as error:
                prior_failure = {
                    "code": getattr(error, "code", type(error).__name__),
                    "diagnostics": getattr(error, "diagnostics", {"error": str(error)[:2000]}),
                }
                raise
            finally:
                report["container_cleanup"] = ComparatorVerifier._cleanup_container(
                    docker, name, prior_failure
                )
        if (
            Path(__file__).read_bytes() != source
            or safe_read(image_metadata.parent, image_metadata.name) != metadata_bytes
            or safe_read(runtime_identity.parent, runtime_identity.name) != runtime_bytes
        ):
            raise ValueError("Pinned input changed during fixed probe")
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="blocked", error_type=type(error).__name__, reason=str(error)[:2000])
        if isinstance(error, ExecutionFailure):
            report["execution_failure"] = error.diagnostics
        _write(output, report)
        raise
    _write(output, report)
    return report


if __name__ == "__main__":
    if sys.argv[1:] == ["--inside"]:
        print(json.dumps(inside_probe()))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--image-metadata", type=Path, required=True)
        parser.add_argument("--image-metadata-sha256", required=True)
        parser.add_argument("--runtime-identity", type=Path, required=True)
        parser.add_argument("--runtime-identity-sha256", required=True)
        parser.add_argument("--output", type=Path, required=True)
        run_probe(**vars(parser.parse_args()))
