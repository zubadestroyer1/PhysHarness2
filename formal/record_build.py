"""Executed inside the image, after building real tools; never grants qualification."""

import hashlib
import json
import subprocess
from pathlib import Path

metadata = Path("/opt/verifier/metadata")
paths = {
    "lean": "/opt/lean/bin/lean",
    "lake": "/opt/lean/bin/lake",
    "comparator": "/opt/verifier/bin/comparator",
    "lean4export": "/opt/verifier/bin/lean4export",
    "landrun": "/opt/verifier/bin/landrun",
    "nanoda": "/opt/verifier/bin/nanoda_bin",
}


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


lock = json.loads((metadata / "environment.lock.json").read_text())
result = {
    "schema": "physharness-formal-build-v1",
    "build_status": "built",
    "sandbox_qualification": "not_run",
    "semantic_review": "not_reviewed",
    "independent_kernel_compatibility": "not_run",
    "source_lock_sha256": sha(metadata / "environment.lock.json"),
    "binaries": {name: sha(path) for name, path in paths.items()},
    "binary_paths": paths,
    "checker_versions": {
        "lean": subprocess.check_output([paths["lean"], "--version"], text=True).strip(),
        **{
            name: lock["sources"][name]["revision"]
            for name in ["comparator", "lean4export", "landrun", "nanoda"]
        },
    },
    "compiler_versions": {
        name: subprocess.check_output(command, text=True).strip()
        for name, command in {
            "rust": ["rustc", "--version"],
            "cargo": ["cargo", "--version"],
            "go": ["/usr/local/go/bin/go", "version"],
        }.items()
    },
    "prepared_lake_manifests": {
        str(path.relative_to("/opt/sources")): sha(path)
        for path in Path("/opt/sources").glob("*/lake-manifest.json")
    },
}
(metadata / "build.json").write_text(json.dumps(result, indent=2) + "\n")
with (metadata / "dpkg-packages.txt").open("w") as f:
    subprocess.run(["dpkg-query", "-W", "-f=${Package}\t${Version}\n"], stdout=f, check=True)
