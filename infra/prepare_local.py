"""Generate secret-bearing local Compose configuration without printing credentials."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path


def prepare(destination: Path, image_lock: Path) -> None:
    images = json.loads(image_lock.read_text())["images"]
    password = secrets.token_hex(24)
    principals = {
        secrets.token_urlsafe(36): {"id": f"local-{role}", "project_id": "local", "role": role}
        for role in ("researcher", "reviewer", "operator")
    }
    fields = {
        "PYTHON_IMAGE": images["python"],
        "UV_IMAGE": images["uv"],
        "POSTGRES_IMAGE": images["postgres"],
        "TEMPORAL_SERVER_IMAGE": images["temporal_server"],
        "TEMPORAL_ADMIN_IMAGE": images["temporal_admin"],
        "TEMPORAL_UI_IMAGE": images["temporal_ui"],
        "POSTGRES_PASSWORD": password,
        "PHYSHARNESS_DATABASE_URL": f"postgresql+psycopg://harness_dev:{password}@postgres:5432/physharness",
        "PHYSHARNESS_AUTH_TOKENS": json.dumps(principals, separators=(",", ":")),
        "PHYSHARNESS_MODEL_PRICES": "{}",
    }
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write("# Local development only. Do not commit or publish this file.\n")
        for name, value in fields.items():
            output.write(f"{name}='{value}'\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".env"))
    args = parser.parse_args()
    prepare(args.output, Path(__file__).parent / "images.lock.json")
    print(f"Created {args.output}; values are private, and no model credentials were added.")
