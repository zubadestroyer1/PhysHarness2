"""Operator source freeze and one-shot launch wrapper; no automatic advancement."""

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
    "work/exponential-pilot-2026-09-24/runner.py",
    "work/exponential-pilot-2026-09-24/prepare.py",
    "work/exponential-pilot-2026-09-24/evaluate.py",
    "work/exponential-pilot-2026-09-24/audit_export.py",
    "work/exponential-pilot-2026-09-24/operator_handoffs.py",
    "work/exponential-pilot-2026-09-24/launch_frozen.py",
    "work/parallel-pilot-2026-09-24/evaluate_pilot.py",
)
FORMAL_ASSETS = (
    "environment.lock.json",
    "verifier-resources.json",
    "lean-toolchain",
    "Dockerfile",
    "workbench.Dockerfile",
)


class FreezeError(Exception):
    pass


def file_digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise FreezeError("required frozen file missing or symlinked")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(root: Path, manifest_path: Path, qualification_path: Path) -> dict:
    """Return hashes and file names only; source and credential bytes never enter output."""
    root = root.resolve()
    manifest = json.loads(manifest_path.read_text())
    registry = json.loads(Path(manifest["registry"]).read_text())
    paths = set()
    paths.update((root / "src").rglob("*.py"))
    paths.update((root / "infra").glob("*.py"))
    paths.update(root / name for name in WRAPPERS)
    paths.update(root / name for name in ("pyproject.toml", "uv.lock"))
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
            manifest["model_prices_file"],
        )
    )
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
    return {"protocol": "exponential-source-freeze-v1", "files": output}


def check(root: Path, manifest_path: Path, qualification_path: Path, baseline: dict) -> None:
    if collect(root, manifest_path, qualification_path) != baseline:
        raise FreezeError("frozen source or verifier input drift")


def freeze_path(manifest_path: Path) -> Path:
    return manifest_path.parent / "source-freeze.json"


def launch(manifest_path: Path, qualification_path: Path, label: str) -> int:
    baseline = json.loads(freeze_path(manifest_path).read_text())
    check(ROOT, manifest_path, qualification_path, baseline)
    manifest = json.loads(manifest_path.read_text())
    matches = [a for a in manifest["attempts"] if a["label"] == label]
    if len(matches) != 1:
        raise FreezeError("unknown attempt label")
    attempt = matches[0]
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
    python = ROOT / ".venv/bin/python"
    runner = ROOT / "work/exponential-pilot-2026-09-24/runner.py"
    log_path = Path(attempt["private_directory"]) / "launch.log"
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as log:
        result = subprocess.run(
            [
                str(python),
                str(runner),
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
