"""Phase-specific source freeze and one-shot operator launch wrapper.

`freeze` and `check` are read-only apart from the exclusive freeze file. `launch`
reads the private model credential only after all frozen inputs match. No command
in this module automatically advances to a later attempt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY_FILE = Path.home() / ".config/physharness/openai-api-key"
WRAPPERS = (
    "work/hardening-final-2026-09-24/pilot_prepare.py",
    "work/hardening-final-2026-09-24/pilot_runner.py",
    "work/hardening-final-2026-09-24/pilot_launch.py",
    "work/hardening-final-2026-09-24/qualify_capacity.py",
    "work/exponential-pilot-2026-09-24/runner.py",
    "work/exponential-pilot-2026-09-24/operator_handoffs.py",
    "work/exponential-pilot-2026-09-24/audit_export.py",
)
FORMAL_ASSETS = (
    "environment.lock.json",
    "verifier-resources.json",
    "lean-toolchain",
    "Dockerfile",
    "workbench.Dockerfile",
)
HISTORICAL_LEDGER = "work/exponential-pilot-2026-09-24/final-ledger-audit.json"
HISTORICAL_RECHECK = "work/hardening-final-2026-09-24/historical-budget-recheck.json"


class FreezeError(Exception):
    pass


def file_digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise FreezeError("required frozen file missing or symlinked")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_path(manifest_path: Path) -> Path:
    return (
        manifest_path.parent / f"source-freeze-{manifest_path.stem.removeprefix('manifest-')}.json"
    )


def check_phase_continuity(earlier: dict, current: dict) -> None:
    old_files, new_files = earlier["files"], current["files"]

    def invariant(name: str) -> bool:
        return (
            name.startswith(("src/", "infra/", "formal/"))
            or name in WRAPPERS
            or name in {"pyproject.toml", "uv.lock"}
        )

    old_paths = {name for name in old_files if invariant(name)}
    new_paths = {name for name in new_files if invariant(name)}
    shared = set(old_files) & set(new_files)
    if (
        old_paths != new_paths
        or not shared
        or any(old_files[name] != new_files[name] for name in shared)
    ):
        raise FreezeError("cross-phase frozen input drift")


def collect(root: Path, manifest_path: Path, qualification_path: Path) -> dict:
    """Return hashes and names only; never print target, proof or credential bytes."""
    root = root.resolve()
    manifest = json.loads(manifest_path.read_text())
    registry = json.loads(Path(manifest["registry"]).read_text())
    historical = json.loads((root / HISTORICAL_LEDGER).read_text())
    recheck = json.loads((root / HISTORICAL_RECHECK).read_text())
    qualification = json.loads(qualification_path.read_text())
    scope = json.loads((qualification_path.parent / "scope.json").read_text())
    if (
        qualification.get("mechanical_status") != "satisfied"
        or qualification.get("production_qualified") is not False
        or qualification.get("scope_sha256") != manifest["source_scope_sha256"]
        or qualification.get("scope") != scope
        or scope.get("image_digest") != manifest["verifier_image_digest"]
    ):
        raise FreezeError("source qualification does not match frozen verifier scope")
    if historical.get("aggregate_conservative_spend_usd") != manifest["prior_spent_usd"]:
        raise FreezeError("historical ledger anchor changed")
    if (
        recheck.get("prior_conservative_spent_usd") != manifest["prior_spent_usd"]
        or recheck.get("all_reservations_settled") is not True
        or recheck.get("all_experiments_stopped_without_budget_uncertainty") is not True
    ):
        raise FreezeError("historical ledger recheck changed")
    paths = set((root / "src").rglob("*.py"))
    paths.update((root / "infra").glob("*.py"))
    paths.update(root / name for name in WRAPPERS)
    paths.update(
        root / name for name in ("pyproject.toml", "uv.lock", HISTORICAL_LEDGER, HISTORICAL_RECHECK)
    )
    paths.update(root / "formal" / name for name in FORMAL_ASSETS)
    paths.update((root / "formal").glob("lakefile*.toml"))
    paths.update((root / "formal").glob("lake-manifest*.json"))
    paths.update(
        Path(name)
        for name in (
            manifest_path,
            qualification_path,
            manifest["registry"],
            manifest["challenge_file"],
            manifest["worker_qualification_file"],
            manifest["source_qualification_file"],
            manifest["model_prices_file"],
            manifest["deployment_decision_file"],
        )
    )
    paths.update(
        path for path in qualification_path.parent.rglob("*") if path.is_file() or path.is_symlink()
    )
    if manifest["phase"] == "cooperative":
        paths.add(manifest_path.parent / "manifest-calibration.json")
        paths.add(manifest_path.parent / "source-freeze-calibration.json")
    for entry in registry["entries"]:
        paths.add(Path(entry["resource_profile"]))
        bundle = Path(entry["config"]["bundle_directory"])
        if bundle.is_symlink() or not bundle.is_dir():
            raise FreezeError("verifier bundle unavailable")
        paths.update(path for path in bundle.rglob("*") if path.is_file() or path.is_symlink())
    output = {}
    for path in sorted(paths):
        absolute = path.absolute()
        if not absolute.is_relative_to(root):
            raise FreezeError("frozen input outside workspace")
        output[str(absolute.relative_to(root))] = file_digest(absolute)
    current = {"protocol": "hardening-source-freeze-v1", "files": output}
    if manifest["phase"] == "cooperative":
        earlier = json.loads((manifest_path.parent / "source-freeze-calibration.json").read_text())
        check_phase_continuity(earlier, current)
    return current


def check_from_collection(baseline: dict, current: dict) -> None:
    if baseline != current:
        raise FreezeError("frozen source or verifier input drift")


def check(root: Path, manifest_path: Path, qualification_path: Path, baseline: dict) -> None:
    manifest = json.loads(manifest_path.read_text())
    if qualification_path.resolve() != Path(manifest["source_qualification_file"]).resolve():
        raise FreezeError("source qualification path changed")
    check_from_collection(baseline, collect(root, manifest_path, qualification_path))


def launch(manifest_path: Path, qualification_path: Path, label: str) -> int:
    baseline = json.loads(freeze_path(manifest_path).read_text())
    check(ROOT, manifest_path, qualification_path, baseline)
    manifest = json.loads(manifest_path.read_text())
    if manifest["attempts"][-1]["label"] != label:
        raise FreezeError("unknown or prior attempt label")
    key = KEY_FILE.read_text().strip()
    if not key:
        raise FreezeError("operator model credential unavailable")
    env = os.environ.copy()
    env.update(
        {
            "OPENAI_API_KEY": key,
            "DOCKER_HOST": manifest["docker_host"],
            "TMPDIR": manifest["tmp_directory"],
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONPATH": str(ROOT / "src"),
        }
    )
    log_path = Path(manifest["attempts"][-1]["private_directory"]) / "launch.log"
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as log:
        result = subprocess.run(
            [
                str(ROOT / ".venv/bin/python"),
                str(ROOT / "work/hardening-final-2026-09-24/pilot_runner.py"),
                "launch-one",
                "--manifest",
                str(manifest_path),
                "--label",
                label,
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return result.returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "check", "launch"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--label")
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            baseline = collect(ROOT, args.manifest, args.qualification)
            path = freeze_path(args.manifest)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(baseline, stream, sort_keys=True, separators=(",", ":"))
            print(json.dumps({"status": "frozen", "file_count": len(baseline["files"])}))
            return 0
        baseline = json.loads(freeze_path(args.manifest).read_text())
        check(ROOT, args.manifest, args.qualification, baseline)
        if args.command == "check":
            print(json.dumps({"status": "matching", "file_count": len(baseline["files"])}))
            return 0
        if not args.label:
            raise FreezeError("launch requires --label")
        return launch(args.manifest, args.qualification, args.label)
    except (FreezeError, OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "blocked", "code": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
