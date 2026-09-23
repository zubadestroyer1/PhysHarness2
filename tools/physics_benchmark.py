#!/usr/bin/env python3
"""Prepare physics review/evaluator inputs without issuing scientific approval."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from physharness.errors import HarnessError
from physharness.science.benchmark_artifacts import assess_benchmark_reports, prepare_benchmark
from physharness.science.physics_benchmarks import load_physics_benchmarks
from physharness.verification.boundary import safe_read
from physharness.verification.bundles import canonical_json


def write_fresh(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical_json(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, action="append")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inventory")
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--project-root", type=Path, default=Path("formal"))
    export = commands.add_parser("export")
    export.add_argument("--split", choices=["development", "holdout"], required=True)
    export.add_argument("--output", type=Path, required=True)
    assess = commands.add_parser("assess")
    assess.add_argument("--bundle", type=Path, required=True)
    assess.add_argument("--image-metadata", type=Path, required=True)
    assess.add_argument("--kernel-report", type=Path, required=True)
    assess.add_argument("--independent-report", type=Path, required=True)
    assess.add_argument(
        "--resource-profile", type=Path, default=Path("formal/verifier-resources.json")
    )
    assess.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        benchmark = load_physics_benchmarks(
            args.collection
            or [Path("benchmarks/physics/quantum.json"), Path("benchmarks/physics/classical.json")]
        )
        if args.command == "inventory":
            result = benchmark.inventory()
            print(json.dumps(result, indent=2))
            return 0 if result["required_inventory_complete"] and not result["quality_flags"] else 2
        if args.command == "export":
            result = {
                "benchmark_sha256": benchmark.revision_digest(),
                "split": args.split,
                "tasks": benchmark.discovery_tasks(args.split),
                "information_policy": (
                    "targets_only; isolate evaluator storage and network separately"
                ),
                "contamination_status": "not_ruled_out",
                "scientific_review": "pending",
            }
            write_fresh(args.output, result)
        elif args.command == "prepare":
            project = {
                "lakefile.toml": safe_read(args.project_root, "lakefile.physics.toml"),
                "lake-manifest.json": safe_read(args.project_root, "lake-manifest.physics.json"),
                "lean-toolchain": safe_read(args.project_root, "lean-toolchain"),
            }
            result = prepare_benchmark(benchmark, args.output, project_files=project)
        else:
            result = assess_benchmark_reports(
                benchmark,
                args.bundle,
                image_metadata=args.image_metadata,
                kernel_report=args.kernel_report,
                independent_report=args.independent_report,
                resource_profile=args.resource_profile,
            )
            write_fresh(args.output, result)
        print(json.dumps({"output": str(args.output), "scientific_review": "pending"}, indent=2))
        return 0
    except HarnessError as error:
        print(json.dumps(error.envelope()), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        failure = HarnessError(
            "physics_benchmark_command_failed",
            "Physics benchmark command failed; no approval was issued.",
            details={"reason": str(error)[:2000]},
        )
        print(json.dumps(failure.envelope()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
