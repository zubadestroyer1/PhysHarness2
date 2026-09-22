"""Pin trusted inputs, isolate compilation, and validate the trusted driver response."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ImageDigest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
ALLOWED_AXIOMS = frozenset({"propext", "Quot.sound", "Classical.choice"})
PROTOCOL = "physharness-comparator-v2"
MAX_CANDIDATE_CHARACTERS = 2_000_000


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class VerificationRequest(Contract):
    problem_revision_id: str = Field(min_length=1, max_length=256)
    target_digest: SHA256
    challenge_sha256: SHA256
    environment_digest: SHA256
    candidate_sha256: SHA256
    candidate_source: str = Field(max_length=MAX_CANDIDATE_CHARACTERS)
    publication: bool = False
    target_theorem: str = Field(min_length=1, max_length=500)
    semantic_reviewed: bool
    definition_holes: bool = False


class VerificationOutcome(Contract):
    status: Literal["verified", "rejected", "blocked"]
    assurance: Literal["none", "kernel", "independent_kernel"]
    code: str
    message: str
    remediation: str
    target_digest: SHA256
    challenge_sha256: SHA256
    candidate_sha256: SHA256
    environment_digest: SHA256
    axioms: list[str] = Field(default_factory=list)
    checker_versions: dict[str, str] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "verified") != (self.assurance != "none"):
            raise ValueError("only verified outcomes may carry kernel assurance")
        if self.status == "verified":
            if not set(self.axioms) <= ALLOWED_AXIOMS:
                raise ValueError("unapproved axiom")
            if not {"lean", "comparator"} <= self.checker_versions.keys():
                raise ValueError("kernel version provenance is missing")
            if self.assurance == "independent_kernel" and not self.checker_versions.get("nanoda"):
                raise ValueError("independent kernel version is missing")
        return self


class Verifier(Protocol):
    def verify(self, request: VerificationRequest) -> VerificationOutcome: ...


class LinuxQualification(Contract):
    """Operator-owned deployment evidence reference, never populated from worker data."""

    image_digest: ImageDigest
    qualification_report_sha256: SHA256
    driver_sha256: SHA256
    launcher_sha256: SHA256
    seccomp_sha256: SHA256
    linux_boundary: Literal["docker-landlock-seccomp-v1"]
    independent_kernel: bool = False


class ComparatorConfig(Contract):
    bundle_directory: Path
    manifest_sha256: SHA256
    qualification: LinuxQualification
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    output_limit_bytes: int = Field(default=256_000, ge=1024, le=2_000_000)


class Manifest(Contract):
    protocol: Literal["physharness-comparator-v2"]
    problem_revision_id: str
    target_digest: SHA256
    challenge_sha256: SHA256
    environment_digest: SHA256
    theorem_names: list[str] = Field(min_length=1, max_length=128)


class Environment(Contract):
    image: ImageDigest
    checker_versions: dict[str, str]
    files: dict[str, SHA256]
    binaries: dict[str, SHA256]


class DriverResult(Contract):
    protocol: Literal["physharness-comparator-v2"]
    status: Literal["verified", "rejected", "blocked"]
    code: str
    target_digest: SHA256
    challenge_sha256: SHA256
    environment_digest: SHA256
    candidate_sha256: SHA256
    independent_kernel: bool
    axioms: list[str]
    checker_versions: dict[str, str]
    diagnostics: dict[str, Any]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def driver_digest() -> str:
    return digest(Path(__file__).with_name("container_driver.py").read_bytes())


def launcher_digest() -> str:
    return digest(Path(__file__).read_bytes())


def seccomp_policy() -> dict:
    return {
        "defaultAction": "SCMP_ACT_ALLOW",
        "syscalls": [
            {
                "names": [
                    "socket",
                    "socketpair",
                    "io_uring_setup",
                    "io_uring_enter",
                    "io_uring_register",
                    "ptrace",
                    "process_vm_writev",
                    "mount",
                    "umount2",
                    "bpf",
                    "perf_event_open",
                    "keyctl",
                    "add_key",
                    "request_key",
                    "userfaultfd",
                ],
                "action": "SCMP_ACT_ERRNO",
                "errnoRet": 1,
            }
        ],
    }


def seccomp_bytes() -> bytes:
    return json.dumps(seccomp_policy(), sort_keys=True, separators=(",", ":")).encode()


def seccomp_digest() -> str:
    return digest(seccomp_bytes())


def outcome(req, status, code, message, remediation, **kwargs):
    return VerificationOutcome(
        status=status,
        assurance=kwargs.pop("assurance", "none"),
        code=code,
        message=message,
        remediation=remediation,
        target_digest=req.target_digest,
        challenge_sha256=req.challenge_sha256,
        environment_digest=req.environment_digest,
        candidate_sha256=req.candidate_sha256,
        **kwargs,
    )


def preflight(req: VerificationRequest) -> VerificationOutcome | None:
    try:
        actual = digest(req.candidate_source.encode("utf-8"))
    except UnicodeEncodeError:
        actual = "invalid unicode"
    if actual != req.candidate_sha256:
        return outcome(
            req,
            "rejected",
            "candidate_digest_mismatch",
            "Candidate bytes do not match.",
            "Submit the exact UTF-8 source with its SHA256 digest.",
        )
    if not req.semantic_reviewed:
        return outcome(
            req,
            "blocked",
            "semantic_review_required",
            "Target meaning is unreviewed.",
            "Obtain and record expert review of the immutable target revision.",
        )
    if req.definition_holes:
        return outcome(
            req,
            "blocked",
            "definition_review_required",
            "Definition holes are unsupported.",
            "Review the proposed definitions and create a target revision without holes.",
        )
    return None


class UnavailableVerifier:
    def verify(self, request: VerificationRequest) -> VerificationOutcome:
        return preflight(request) or outcome(
            request,
            "blocked",
            "verifier_unavailable",
            "No qualified independent verification service is configured.",
            "Configure a pinned trusted bundle and qualify Linux Comparator isolation.",
        )


class ExecutionFailure(Exception):
    def __init__(self, code: str, diagnostics: dict):
        super().__init__(code)
        self.code, self.diagnostics = code, diagnostics


def bounded_process(argv: list[str], timeout: int, limit: int) -> tuple[int, bytes]:
    """Bound combined output and wall time; terminate the whole client process group."""
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise ExecutionFailure("launcher_unavailable", {"error": str(exc)}) from exc
    output = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() - started > timeout:
                    raise ExecutionFailure("checker_timeout", {"timeout_seconds": timeout})
                for key, _ in selector.select(timeout=0.1):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output.extend(chunk)
                    if len(output) > limit:
                        raise ExecutionFailure(
                            "checker_output_limit", {"output_limit_bytes": limit}
                        )
            remaining = timeout - (time.monotonic() - started)
            try:
                return proc.wait(timeout=max(0.001, remaining)), bytes(output)
            except subprocess.TimeoutExpired as exc:
                raise ExecutionFailure("checker_timeout", {"timeout_seconds": timeout}) from exc
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        if proc.stdout:
            proc.stdout.close()


def safe_read(root: Path, name: str) -> bytes:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(x in {"..", "."} for x in path.parts):
        raise ValueError("unsafe bundle path")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlinks are forbidden in trusted bundles")
    if not current.is_file() or current.stat().st_size > 16_000_000:
        raise ValueError("bundle file missing or oversized")
    return current.read_bytes()


class ComparatorVerifier:
    def __init__(self, config: ComparatorConfig | None = None):
        self.config = config

    def _bundle(self, req):
        config = self.config
        root = config.bundle_directory
        if root.is_symlink() or not root.is_dir():
            raise ValueError("trusted bundle directory unavailable")
        raw = safe_read(root, "manifest.json")
        if digest(raw) != config.manifest_sha256:
            raise ValueError("pinned manifest digest mismatch")
        manifest = Manifest.model_validate_json(raw)
        if manifest.theorem_names != [req.target_theorem]:
            raise ValueError("bundle theorem selection differs from the reviewed target theorem")
        if any(
            getattr(manifest, key) != getattr(req, key)
            for key in (
                "problem_revision_id",
                "target_digest",
                "challenge_sha256",
                "environment_digest",
            )
        ):
            raise ValueError("request does not match trusted manifest")
        target = safe_read(root, "Challenge.lean")
        raw_env = safe_read(root, "environment.json")
        if digest(target) != req.challenge_sha256 or digest(raw_env) != req.environment_digest:
            raise ValueError("target or environment digest mismatch")
        env = Environment.model_validate_json(raw_env)
        if env.image != config.qualification.image_digest:
            raise ValueError("image differs from qualified image")
        if config.qualification.driver_sha256 != driver_digest():
            raise ValueError("qualification predates this driver")
        if config.qualification.launcher_sha256 != launcher_digest():
            raise ValueError("qualification predates this host launcher")
        if config.qualification.seccomp_sha256 != seccomp_digest():
            raise ValueError("qualification does not match this seccomp policy")
        if not all(env.checker_versions.get(x) for x in ("lean", "comparator")):
            raise ValueError("missing pinned checker versions")
        if not {"lean", "lake", "comparator", "lean4export", "landrun"} <= env.binaries.keys():
            raise ValueError("missing binary pins")
        files = {"Challenge.lean": target, "environment.json": raw_env, "manifest.json": raw}
        for name, expected in env.files.items():
            # Candidate compilation may only create artifacts in the fresh .lake directory.
            if (
                name in files
                or name in {"Solution.lean", "request.json", "config.json", "seccomp.json"}
                or name.startswith(".lake/")
            ):
                raise ValueError("reserved project file")
            data = safe_read(root, name)
            if digest(data) != expected:
                raise ValueError(f"trusted file digest mismatch: {name}")
            files[name] = data
        if "lakefile.toml" not in files and "lakefile.lean" not in files:
            raise ValueError("trusted Lake configuration missing")
        return manifest, env, files

    def verify(self, request: VerificationRequest) -> VerificationOutcome:
        failed = preflight(request)
        if failed:
            return failed
        if self.config is None:
            return outcome(
                request,
                "blocked",
                "verifier_unconfigured",
                "Comparator is unconfigured.",
                "Pin a trusted bundle and qualify the Linux execution image.",
            )
        try:
            manifest, env, files = self._bundle(request)
        except (ValueError, OSError) as exc:
            return outcome(
                request,
                "blocked",
                "trusted_bundle_invalid",
                "Trusted bundle validation failed.",
                "Restore the immutable bundle or create and review a new pinned revision.",
                diagnostics={"error": str(exc)},
            )
        if request.publication and (
            not self.config.qualification.independent_kernel
            or not env.checker_versions.get("nanoda")
            or not env.binaries.get("nanoda")
        ):
            return outcome(
                request,
                "blocked",
                "independent_kernel_required",
                "Publication requires nanoda.",
                "Qualify and pin the compatible independent kernel image.",
            )
        try:
            result = DriverResult.model_validate(self._run_container(request, manifest, env, files))
            for key in (
                "target_digest",
                "challenge_sha256",
                "environment_digest",
                "candidate_sha256",
            ):
                if getattr(result, key) != getattr(request, key):
                    raise ValueError(f"driver returned mismatched {key}")
            if result.checker_versions != env.checker_versions:
                raise ValueError("checker version provenance differs from pinned environment")
            if not set(result.axioms) <= ALLOWED_AXIOMS:
                return outcome(
                    request,
                    "rejected",
                    "unapproved_axiom",
                    "Checker reported unapproved axioms.",
                    "Remove the unapproved transitive assumptions and resubmit.",
                )
            if result.status != "verified":
                return outcome(
                    request,
                    result.status,
                    result.code,
                    "Comparator did not verify the candidate.",
                    "Inspect checker diagnostics, fix the candidate or qualify the environment.",
                    diagnostics=result.diagnostics,
                    checker_versions=result.checker_versions,
                )
            if request.publication and not result.independent_kernel:
                return outcome(
                    request,
                    "blocked",
                    "independent_kernel_required",
                    "Independent replay is missing.",
                    "Run the publication request using a qualified independent kernel.",
                )
            if result.independent_kernel and not self.config.qualification.independent_kernel:
                raise ValueError("unqualified independent kernel")
            return outcome(
                request,
                "verified",
                "kernel_checked",
                "Pinned Comparator accepted the candidate.",
                "",
                assurance="independent_kernel" if result.independent_kernel else "kernel",
                axioms=result.axioms,
                checker_versions=result.checker_versions,
                diagnostics={
                    **result.diagnostics,
                    "qualification_report_sha256": (
                        self.config.qualification.qualification_report_sha256
                    ),
                },
            )
        except ExecutionFailure as exc:
            return outcome(
                request,
                "blocked",
                exc.code,
                "Verification execution did not complete.",
                "Inspect execution diagnostics and repair or qualify the Linux verifier.",
                diagnostics=exc.diagnostics,
            )
        except (ValueError, OSError) as exc:
            return outcome(
                request,
                "blocked",
                "invalid_checker_response",
                "Trusted checker response is invalid.",
                "Investigate the verifier transport; do not accept candidate-supplied receipts.",
                diagnostics={"error": str(exc)},
            )

    def _run_container(self, req, manifest, env, files):
        config = self.config
        # PATH and the Docker daemon are service-owned deployment dependencies.
        resolved = shutil.which("docker")
        if resolved is None or Path(resolved).name != "docker":
            raise ExecutionFailure(
                "launcher_unavailable", {"operation": "resolve Docker executable"}
            )
        name = "physharness-check-" + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="physharness-verifier-") as tmp:
            staging = Path(tmp)
            trusted, candidate = staging / "trusted", staging / "candidate"
            trusted.mkdir(mode=0o755)
            candidate.mkdir(mode=0o755)
            trusted.chmod(0o755)
            candidate.chmod(0o755)
            for filename, data in files.items():
                path = trusted / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                path.chmod(0o444)
            (candidate / "Solution.lean").write_bytes(req.candidate_source.encode("utf-8"))
            (candidate / "Solution.lean").chmod(0o444)
            meta = req.model_dump(exclude={"candidate_source"})
            meta["driver_sha256"] = driver_digest()
            meta["seccomp_sha256"] = seccomp_digest()
            (trusted / "request.json").write_text(json.dumps(meta))
            seccomp = trusted / "seccomp.json"
            seccomp.write_bytes(seccomp_bytes())
            # Explicit final modes are independent of the service umask. The outer
            # staging directory remains private; Docker bind mounts expose only these roots.
            for item in trusted.rglob("*"):
                item.chmod(0o755 if item.is_dir() else 0o444)
            argv = [
                resolved,
                "run",
                "--pull=never",
                "--name",
                name,
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--security-opt",
                f"seccomp={seccomp}",
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
                env.image,
                "/opt/physharness/container_driver.py",
            ]
            prior_failure = None
            result = None
            try:
                code, output = bounded_process(
                    argv, config.timeout_seconds, config.output_limit_bytes
                )
                if code:
                    raise ExecutionFailure(
                        "container_failed",
                        {
                            "operation": "docker run",
                            "exit_code": code,
                            "output": output.decode("utf-8", errors="replace"),
                        },
                    )
                result = json.loads(output)
                return result
            except (ExecutionFailure, ValueError, OSError) as exc:
                prior_failure = {
                    "code": getattr(exc, "code", type(exc).__name__),
                    "diagnostics": getattr(exc, "diagnostics", {"error": str(exc)}),
                }
                raise
            finally:
                # Do not use --rm: explicit removal or an authoritative empty listing
                # must confirm absence before acceptance. Preserve cleanup diagnostics.
                cleanup = self._cleanup_container(resolved, name, prior_failure)
                if isinstance(result, dict) and isinstance(result.get("diagnostics"), dict):
                    result["diagnostics"]["container_cleanup"] = cleanup

    @staticmethod
    def _cleanup_container(docker, name, prior_failure):
        try:
            code, output = bounded_process([docker, "rm", "--force", name], 10, 16384)
            removal = {"exit_code": code, "output": output.decode("utf-8", errors="replace")}
            if code == 0:
                return {"status": "removed", "container_name": name, **removal}
        except ExecutionFailure as exc:
            removal = {"code": exc.code, **exc.diagnostics}
        try:
            # A failed inspect cannot distinguish absent containers from a broken daemon.
            # A successful exact-name listing with no output confirms absence.
            code, output = bounded_process(
                [
                    docker,
                    "container",
                    "ls",
                    "--all",
                    "--filter",
                    f"name=^/{name}$",
                    "--format",
                    "{{json .Names}}",
                ],
                10,
                16384,
            )
            absence_check = {"exit_code": code, "output": output.decode("utf-8", errors="replace")}
            if code == 0 and not output.strip():
                return {
                    "status": "confirmed_absent",
                    "container_name": name,
                    "removal": removal,
                    "absence_check": absence_check,
                }
        except ExecutionFailure as exc:
            absence_check = {"code": exc.code, **exc.diagnostics}
        raise ExecutionFailure(
            "container_cleanup_failed",
            {
                "operation": "docker rm --force",
                "container_name": name,
                "cleanup": removal,
                "absence_check": absence_check,
                "prior_failure": prior_failure,
            },
        )
