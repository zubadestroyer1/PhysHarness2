"""Inside-image preparation of hash-verified Lake sources at fixed paths.

Preserve original manifests before redirecting resolved dependencies to image-local
paths. Disable Physlib's local artifact cache so verification can keep imports read-only;
preserve its original configuration and every other setting.
"""

import json
import shutil
from pathlib import Path


def prepare(root: Path, lock: dict) -> None:
    physics_config = root / "physlib" / "lakefile.toml"
    if physics_config.exists():
        saved_config = physics_config.with_name("lakefile.upstream.toml")
        original_config = (saved_config if saved_config.exists() else physics_config).read_text()
        marker = "\nenableArtifactCache = true\n"
        if original_config.count(marker) != 1:
            raise ValueError("Unexpected Physlib artifact-cache configuration")
        if not saved_config.exists():
            shutil.copyfile(physics_config, saved_config)
        physics_config.write_text(
            original_config.replace(marker, "\nenableArtifactCache = false\n")
        )
    for package in root.iterdir():
        path = package / "lake-manifest.json"
        if not path.exists():
            continue
        saved = package / "lake-manifest.upstream.json"
        if not saved.exists():
            shutil.copyfile(path, saved)
        original = json.loads(saved.read_text())
        entries = []
        for item in original["packages"]:
            name = item["name"].strip("«»")
            if name not in lock["sources"]:
                raise ValueError(f"Unpinned dependency {name} in {package.name}")
            if item.get("rev") != lock["sources"][name]["revision"]:
                raise ValueError(f"Dependency revision mismatch for {name} in {package.name}")
            entries.append(
                {
                    "type": "path",
                    "name": item["name"],
                    "dir": str(root / name),
                    "inherited": item["inherited"],
                    "configFile": item["configFile"],
                    "manifestFile": item.get("manifestFile", "lake-manifest.json"),
                }
            )
        original["packages"] = entries
        path.write_text(json.dumps(original, indent=2) + "\n")


if __name__ == "__main__":
    prepare(
        Path("/opt/sources"),
        json.loads(Path("/opt/verifier/metadata/environment.lock.json").read_text()),
    )
