"""Bounded numerical computations in the offline workbench, with a reproducibility record.

A computation record is numerical evidence, never proof. It cannot accept a claim, change
a node status, or stand in for a verification receipt.
"""

import hashlib
import json
import math
import re
from time import monotonic

from ..domain import ArtifactCreate, canonical_json
from ..errors import HarnessError

PACKAGES = ("numpy", "scipy", "sympy", "mpmath", "flint", "cvxpy", "z3", "networkx", "matplotlib")
EVIDENCE_STATUS = "numerical_evidence_not_proof"
MAX_ARGS = 32
MAX_ARG_CHARS = 500
MAX_PATH_BYTES = 1024
MAX_TIMEOUT_SECONDS = 1800
# The script runs under guest-side GNU `timeout`, so an overrun ends as exit 124 (TERM) or
# 137 (KILL after the grace period) instead of a provider timeout, which quarantines the VM.
# Assumed GNU coreutils behaviour (not checked against local docs or source): without
# --foreground, timeout signals the script's whole process group, so children die too.
KILL_AFTER = "--kill-after=5s"
PROVIDER_MARGIN_SECONDS = 30
TIMED_OUT_EXIT_CODES = (124, 137)
PROBE_TIMEOUT_SECONDS = 60
RECORD_STREAM_CHARS = 16384
RETURN_STDOUT_CHARS = 4000
RETURN_STDERR_CHARS = 2000
MAX_VERSION_CHARS = 100

# Distribution names tried with importlib.metadata before importing the module itself.
_DISTRIBUTIONS = {
    "numpy": ["numpy"],
    "scipy": ["scipy"],
    "sympy": ["sympy"],
    "mpmath": ["mpmath"],
    "flint": ["python-flint"],
    "cvxpy": ["cvxpy", "cvxpy-base"],
    "z3": ["z3-solver"],
    "networkx": ["networkx"],
    "matplotlib": ["matplotlib"],
}

# Runs as `python3 -c PROBE <path>` from the workspace root. It never imports the script.
# Workspace-local modules are removed from sys.path so they cannot shadow installed ones.
PROBE = (
    """
import hashlib, importlib, json, os, sys
from importlib import metadata
sys.path[:] = [entry for entry in sys.path if entry not in ('', '.', os.getcwd())]
SOURCES = __SOURCES__
path = sys.argv[1]
digest = None
if os.path.isfile(path):
    with open(path, 'rb') as stream:
        digest = hashlib.sha256(stream.read()).hexdigest()
def version(module_name, distributions):
    for distribution in distributions:
        try:
            return str(metadata.version(distribution))[:100]
        except Exception:
            pass
    try:
        module = importlib.import_module(module_name)
        value = getattr(module, '__version__', None)
        if value is None and callable(getattr(module, 'get_version_string', None)):
            value = module.get_version_string()
    except BaseException:
        return None
    return None if value is None else str(value)[:100]
packages = {name: version(name, distributions) for name, distributions in SOURCES}
print()
print(json.dumps({'script_sha256': digest, 'python': sys.version.split()[0],
                  'packages': packages}, sort_keys=True))
"""
).replace("__SOURCES__", json.dumps([[name, _DISTRIBUTIONS[name]] for name in PACKAGES]))

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _invalid(message: str) -> HarnessError:
    return HarnessError(
        "INVALID_COMPUTATION",
        message,
        remediation="Supply a workspace-relative .py path, at most 32 string arguments of at "
        "most 500 characters, a positive timeout and an optional non-negative integer seed.",
    )


def _script_path(value) -> str:
    if (
        not isinstance(value, str)
        or not value.endswith(".py")
        or value.startswith("-")
        or len(value.encode("utf-8")) > MAX_PATH_BYTES
        or any(
            not part or part in {".", ".."} or "\\" in part or "\x00" in part
            for part in value.split("/")
        )
    ):
        raise _invalid("Computation path must be a canonical workspace-relative .py file.")
    return value


def _script_args(value) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > MAX_ARGS
        or any(
            not isinstance(item, str) or len(item) > MAX_ARG_CHARS or "\x00" in item
            for item in value
        )
    ):
        raise _invalid("Computation args must be at most 32 strings of at most 500 characters.")
    return list(value)


def _seed(value) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value < 2**64:
        raise _invalid("Computation seed must be null or a non-negative 64-bit integer.")
    return value


def _timeout(value, policy_seconds) -> int | float:
    """Return the script budget, leaving the provider a margin above it."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise _invalid("Computation timeout_seconds must be a positive finite number.")
    budget = min(value, MAX_TIMEOUT_SECONDS, policy_seconds - PROVIDER_MARGIN_SECONDS)
    if budget < 1:
        raise _invalid("The workspace timeout leaves less than one second for the script.")
    return budget


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _version(value) -> str | None:
    return value[:MAX_VERSION_CHARS] if isinstance(value, str) else None


def _probe_observation(result: dict) -> dict:
    try:
        if result["exit_code"] != 0:
            raise ValueError("probe exited nonzero")
        observed = json.loads(result["stdout"].strip().splitlines()[-1])
        digest, python, packages = (
            observed["script_sha256"],
            observed["python"],
            observed["packages"],
        )
        if (
            (digest is not None and not (isinstance(digest, str) and _SHA256.fullmatch(digest)))
            or not isinstance(python, str)
            or not isinstance(packages, dict)
        ):
            raise ValueError("probe output is malformed")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise HarnessError(
            "COMPUTATION_PROBE_FAILED",
            "The workbench could not report the script digest and package versions.",
            remediation="Check that python3 is available in the workbench, then retry.",
            details={
                "exit_code": result.get("exit_code"),
                "stderr": str(result.get("stderr", ""))[:RETURN_STDERR_CHARS],
            },
        ) from exc
    if digest is None:
        raise HarnessError(
            "COMPUTATION_SCRIPT_MISSING",
            "The computation script is not a regular file in the workspace.",
            remediation="Write the script with write_file first, then run it by the same path.",
        )
    return {
        "script_sha256": digest,
        "python": python[:MAX_VERSION_CHARS],
        "packages": {name: _version(packages.get(name)) for name in PACKAGES},
    }


class ComputationRunner:
    """Run one bounded script and store its reproducibility record as an artifact."""

    def __init__(self, workspace_tools, service, agent):
        self.workspace_tools, self.service, self.agent = workspace_tools, service, agent

    async def run(self, arguments: dict, operation_id: str) -> dict:
        if not isinstance(arguments, dict):
            raise _invalid("Computation arguments must be an object.")
        policy = self.workspace_tools.policy
        path = _script_path(arguments.get("path"))
        args = _script_args(arguments.get("args", []))
        seed = _seed(arguments.get("seed"))
        timeout = _timeout(arguments.get("timeout_seconds"), policy.timeout_seconds)

        probe = await self.workspace_tools.run(
            {
                "argv": ["python3", "-c", PROBE, path],
                "cwd": ".",
                "timeout_seconds": min(policy.timeout_seconds, PROBE_TIMEOUT_SECONDS),
            },
            f"{operation_id}:probe",
        )
        observed = _probe_observation(probe)

        argv = ["timeout", KILL_AFTER, f"{timeout}s", "env", "PYTHONHASHSEED=0"]
        if seed is not None:
            argv.append(f"PHYSHARNESS_SEED={seed}")
        argv += ["python3", "-X", "utf8", path, *args]
        started = monotonic()
        # WorkspaceTools.run applies the broker's 65536-byte output capture limit.
        result = await self.workspace_tools.run(
            {
                "argv": argv,
                "cwd": ".",
                "timeout_seconds": timeout + PROVIDER_MARGIN_SECONDS,
            },
            f"{operation_id}:run",
        )
        duration = round(monotonic() - started, 3)

        stdout, stderr = result["stdout"], result["stderr"]
        timed_out = result["exit_code"] in TIMED_OUT_EXIT_CODES
        stdout_captured_short = bool(result.get("stdout_truncated"))
        stderr_captured_short = bool(result.get("stderr_truncated"))
        record = {
            "script_path": path,
            "script_sha256": observed["script_sha256"],
            "args": args,
            "seed": seed,
            "timeout_seconds": timeout,
            "argv": argv,
            "exit_code": result["exit_code"],
            "timed_out": timed_out,
            "duration_seconds": duration,
            "stdout": stdout[:RECORD_STREAM_CHARS],
            "stderr": stderr[:RECORD_STREAM_CHARS],
            "stdout_sha256": _sha256(stdout),
            "stderr_sha256": _sha256(stderr),
            "stdout_truncated": stdout_captured_short or len(stdout) > RECORD_STREAM_CHARS,
            "stderr_truncated": stderr_captured_short or len(stderr) > RECORD_STREAM_CHARS,
            "stdout_capture_truncated": stdout_captured_short,
            "stderr_capture_truncated": stderr_captured_short,
            "python": observed["python"],
            "packages": observed["packages"],
            "workspace_template": policy.template_id,
            "environment_digest": policy.environment_digest,
            "execution_id": result.get("execution_id"),
            "evidence_status": EVIDENCE_STATUS,
        }
        content = canonical_json(record)
        # Keyed on content: an identical replay returns the same record, while a replay
        # that re-ran with different timing or output stores a second evidence record.
        artifact = self.service.create_artifact(
            ArtifactCreate(
                experiment_id=self.agent.experiment_id,
                kind="computation_record",
                media_type="application/json",
                content=content,
                provenance={"branch_id": self.agent.branch_id},
            ),
            self.agent,
            f"{operation_id}:computation:{_sha256(content)[:16]}",
        )
        return {
            "artifact_id": artifact["id"],
            "exit_code": result["exit_code"],
            "stdout": stdout[:RETURN_STDOUT_CHARS],
            "stderr": stderr[:RETURN_STDERR_CHARS],
            "truncated": stdout_captured_short
            or stderr_captured_short
            or len(stdout) > RETURN_STDOUT_CHARS
            or len(stderr) > RETURN_STDERR_CHARS,
            "packages": observed["packages"],
            "evidence_status": EVIDENCE_STATUS,
            "timed_out": timed_out,
        }
