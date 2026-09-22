"""Static deployment metadata validation. This does not qualify infrastructure or proofs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml


def validate_image(value: str) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", value):
        return "image must be pinned by a complete SHA-256 digest"
    if ":latest@" in value:
        return "latest tags are not release metadata"
    return None


def validate_action(value: str) -> str | None:
    if value.startswith("./"):
        return None
    if not re.fullmatch(r"[a-zA-Z0-9_./-]+@[0-9a-f]{40}", value):
        return "third-party CI actions must be pinned by a full commit SHA"
    return None


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def validate_repository(root: Path) -> list[str]:
    errors = []
    lock_path = root / "infra/images.lock.json"
    try:
        lock = json.loads(lock_path.read_text())
        if lock.get("qualification") != "manifest_metadata_only":
            errors.append("image lock must not imply executed image qualification")
        for name, value in lock["images"].items():
            if error := validate_image(value):
                errors.append(f"image {name}: {error}")
    except (OSError, KeyError, ValueError) as exc:
        errors.append(f"image lock invalid: {exc}")
    try:
        compose = yaml.safe_load((root / "compose.yaml").read_text())
        for name, service in compose["services"].items():
            value = service.get("image", "")
            if "build" not in service and not re.fullmatch(r"\$\{[A-Z_]+:\?.+\}", value):
                if error := validate_image(value):
                    errors.append(f"Compose service {name}: {error}")
            for port in service.get("ports", []):
                if not str(port).startswith("127.0.0.1:"):
                    errors.append(f"Compose service {name}: development ports must bind loopback")
    except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        errors.append(f"Compose metadata invalid: {exc}")
    for path in sorted((root / ".github/workflows").glob("*.yaml")):
        try:
            workflow = yaml.safe_load(path.read_text())
            if workflow.get("permissions") != {"contents": "read"}:
                errors.append(f"{path.name}: workflow defaults must be read-only")
            for mapping in walk(workflow):
                if "uses" in mapping and (error := validate_action(mapping["uses"])):
                    errors.append(f"{path.name}: {error}")
                if "image" in mapping and (error := validate_image(mapping["image"])):
                    errors.append(f"{path.name}: {error}")
        except (ValueError, yaml.YAMLError) as exc:
            errors.append(f"{path.name}: invalid YAML: {exc}")
    for relative in ["formal/qualification.json", "infra/selfhost/qualification.json"]:
        path = root / relative
        if path.exists():
            try:
                data = json.loads(path.read_text())
                if data.get("status") not in {"blocked", "unqualified", "qualified"}:
                    errors.append(f"{relative}: unknown qualification state")
                if data.get("status") == "qualified" and not data.get(
                    "qualification_report_sha256"
                ):
                    errors.append(f"{relative}: qualified state requires evidence digest")
            except ValueError as exc:
                errors.append(f"{relative}: invalid JSON: {exc}")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = validate_repository(args.root)
    if errors:
        raise SystemExit("\n".join(errors))
    print("Deployment metadata valid; no live infrastructure or proof qualification implied.")
