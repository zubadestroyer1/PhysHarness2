"""Trusted image entrypoint. Never run generated Lean outside this Linux boundary.

Only this driver emits the protocol response. Candidate/Comparator output is captured,
not interpreted as JSON and never forwarded as a receipt. The immutable image and
independently administered qualification record establish trust in the driver.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import platform
import selectors
import signal
import socket
import subprocess
import time
from pathlib import Path

ALLOWED = ["propext", "Quot.sound", "Classical.choice"]
BINARIES = {
    "comparator": "/opt/verifier/bin/comparator",
    "lean4export": "/opt/verifier/bin/lean4export",
    "landrun": "/opt/verifier/bin/landrun",
    "lean": "/opt/lean/bin/lean",
    "lake": "/opt/lean/bin/lake",
    "nanoda": "/opt/verifier/bin/nanoda_bin",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_io_uring_denied(libc):
    # Linux x86_64/aarch64 syscall numbers. Invalid arguments cannot create a ring;
    # only EPERM establishes the required seccomp rejection, not EINVAL/EBADF/ENOSYS.
    for number, args in ((425, (0, 0)), (426, (-1, 0, 0, 0, 0, 0)), (427, (-1, 0, 0, 0))):
        ctypes.set_errno(0)
        result = libc.syscall(number, *(ctypes.c_long(arg) for arg in args))
        if result != -1 or ctypes.get_errno() != errno.EPERM:
            if number == 425 and result >= 0:
                os.close(result)
            raise RuntimeError("seccomp must deny all io_uring syscalls with EPERM")


def classify_comparator_exit(code):
    if code == 0:
        return "verified", "kernel_checked"
    if code < 0 or code >= 128:
        return "blocked", "comparator_terminated"
    # Upstream nonzero exits cover both checker rejection and infrastructure errors.
    # Candidate-controlled stdout cannot be used to distinguish those phases.
    return "blocked", "comparator_failed"


def check_boundary():
    if platform.system() != "Linux" or os.geteuid() == 0:
        raise RuntimeError("Linux and an unprivileged uid are required")
    if platform.machine() not in {"x86_64", "aarch64"}:
        raise RuntimeError("unqualified syscall architecture")
    # landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION).
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise RuntimeError("Landlock ABI >= 3 is required")
    check_io_uring_denied(libc)
    for family in (socket.AF_UNIX, socket.AF_INET):
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
        except OSError as exc:
            if exc.errno not in {errno.EPERM, errno.EACCES}:
                raise RuntimeError("socket restriction probe was inconclusive") from exc
        else:
            sock.close()
            raise RuntimeError("seccomp must deny socket creation, including AF_UNIX")
    status = Path("/proc/self/status").read_text()
    if "NoNewPrivs:\t1" not in status:
        raise RuntimeError("no-new-privileges is required")
    if "Seccomp:\t2" not in status:
        raise RuntimeError("seccomp filter mode is required")


def run_comparator(argv, env):
    proc = subprocess.Popen(
        argv,
        cwd="/work",
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    data = bytearray()
    started = time.monotonic()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() - started > 110:
                    raise RuntimeError("Comparator timed out after 110 seconds")
                for key, _ in selector.select(0.1):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    data.extend(chunk)
                    if len(data) > 100_000:
                        raise RuntimeError("Comparator exceeded 100000 output bytes")
        code = proc.wait(timeout=max(0.001, 110 - (time.monotonic() - started)))
        return code, bytes(data)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        proc.stdout.close()


def main():
    req = json.loads(Path("/trusted/request.json").read_text())
    env = json.loads(Path("/trusted/environment.json").read_text())
    result = {
        "protocol": "physharness-comparator-v1",
        "status": "blocked",
        "code": "boundary_unqualified",
        "target_digest": req["target_digest"],
        "candidate_sha256": req["candidate_sha256"],
        "environment_digest": req["environment_digest"],
        "independent_kernel": False,
        "axioms": [],
        "checker_versions": env["checker_versions"],
        "diagnostics": {},
    }
    try:
        check_boundary()
        if sha(Path(__file__).read_bytes()) != req["driver_sha256"]:
            raise RuntimeError("driver digest does not match qualification")
        if sha(Path("/trusted/seccomp.json").read_bytes()) != req["seccomp_sha256"]:
            raise RuntimeError("seccomp profile differs from qualification")
        for name in ("comparator", "lean4export", "landrun", "lean", "lake"):
            if sha(Path(BINARIES[name]).read_bytes()) != env["binaries"][name]:
                raise RuntimeError(f"binary digest mismatch: {name}")
        if req["publication"]:
            if sha(Path(BINARIES["nanoda"]).read_bytes()) != env["binaries"]["nanoda"]:
                raise RuntimeError("independent kernel binary digest mismatch")
        source = Path("/candidate/Solution.lean").read_bytes()
        if sha(source) != req["candidate_sha256"]:
            raise RuntimeError("candidate changed in transit")
        if sha(Path("/trusted/Challenge.lean").read_bytes()) != req["target_digest"]:
            raise RuntimeError("target changed in transit")
        if sha(Path("/trusted/environment.json").read_bytes()) != req["environment_digest"]:
            raise RuntimeError("environment changed in transit")
        manifest = json.loads(Path("/trusted/manifest.json").read_text())
        # Source remains a read-only bind mount, separate from the trusted bundle.
        # Only the new .lake directory is writable during candidate elaboration.
        for name in ["Challenge.lean", *env["files"]]:
            target = Path("/work") / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(Path("/trusted") / name)
        Path("/work/Solution.lean").symlink_to("/candidate/Solution.lean")
        config = {
            "challenge_module": "Challenge",
            "solution_module": "Solution",
            "theorem_names": manifest["theorem_names"],
            "permitted_axioms": ALLOWED,
            "enable_nanoda": req["publication"],
        }
        Path("/work/config.json").write_text(json.dumps(config))
        child_env = {
            "PATH": "/opt/verifier/bin:/opt/lean/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "COMPARATOR_LANDRUN": BINARIES["landrun"],
            "COMPARATOR_LEAN4EXPORT": BINARIES["lean4export"],
            "COMPARATOR_NANODA": BINARIES["nanoda"],
        }
        code, logs = run_comparator(
            [BINARIES["lake"], "env", BINARIES["comparator"], "/work/config.json"], child_env
        )
        result["diagnostics"] = {
            "comparator_exit_code": code,
            "comparator_output": logs.decode("utf-8", errors="replace"),
            "axioms_are_policy_upper_bound": True,
        }
        status, result_code = classify_comparator_exit(code)
        result.update(status=status, code=result_code)
        if code == 0:
            result.update(
                status="verified",
                code="kernel_checked",
                axioms=ALLOWED,
                independent_kernel=req["publication"],
            )
        elif code < 0:
            result["diagnostics"]["termination_signal"] = -code
        elif code >= 128:
            result["diagnostics"]["possible_termination_signal"] = code - 128
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        result["diagnostics"] = {"operation": "trusted container driver", "error": str(exc)}
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
