"""Replay-only concurrency benchmark. Allocates no VMs and calls no hosted models."""

import argparse
import json
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from physharness.artifacts import LocalArtifactStore
from physharness.domain import CampaignCreate, ExperimentCreate, Principal, ProblemCreate
from physharness.errors import HarnessError
from physharness.service import HarnessService
from physharness.storage import Database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", type=int, default=128)
    parser.add_argument("--operations", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 1000 or not 1 <= args.operations <= 100000:
        parser.error("Use 1–1000 clients and 1–100000 operations")
    args.output.mkdir(parents=True, exist_ok=False)
    db = Database(f"sqlite:///{args.output / 'records.db'}")
    db.create_schema()
    lab = HarnessService(db, LocalArtifactStore(args.output / "artifacts"))
    actor = Principal(id="replay-operator", project_id="isolated-ledger-replay", role="operator")
    reviewer = Principal(id="fixture-reviewer", project_id=actor.project_id, role="reviewer")
    campaign = lab.create_campaign(
        CampaignCreate(
            title="Infrastructure replay fixture",
            objective="Measure local ledger concurrency; no scientific or model throughput claim.",
            programs=["quantum"],
        ),
        actor,
        "campaign",
    )
    problem = lab.create_problem(
        ProblemCreate(
            campaign_id=campaign["id"],
            title="Replay fixture",
            program="quantum",
            informal_statement="Reflexivity fixture for controller testing only.",
            formal_statement="theorem target : (1 : Nat) = 1 := by rfl",
            environment_digest="0" * 64,
        ),
        actor,
        "problem",
    )
    lab.review_problem(
        problem["id"],
        "approved",
        "Synthetic infrastructure fixture, not expert physics review.",
        reviewer,
        "review",
    )
    experiment = lab.create_experiment(
        ExperimentCreate(
            campaign_id=campaign["id"],
            problem_id=problem["id"],
            models=[{"runtime": "replay", "model": "scripted-ledger-replay"}],
            mode="replay",
            budget={
                "max_cost_usd": str(args.operations),
                "max_concurrency": args.concurrency,
                "max_runtime_seconds": 3600,
            },
        ),
        actor,
        "experiment",
    )
    lab.transition_experiment(experiment["id"], "start", 1, actor, "start")
    latencies, errors = [], Counter()

    def request(index):
        started = time.monotonic()
        try:
            reservation = lab.reserve_resources(experiment["id"], "0.01", 1, actor, f"r:{index}")
            lab.settle_resources(reservation["id"], "0.001", False, actor, f"s:{index}")
            return time.monotonic() - started, None
        except HarnessError as error:
            return time.monotonic() - started, error.code

    start = time.monotonic()
    with ThreadPoolExecutor(args.concurrency) as pool:
        for elapsed, error in pool.map(request, range(args.operations)):
            latencies.append(elapsed)
            if error:
                errors[error] += 1
    ledger = lab.ledger(experiment["id"], actor)
    report = {
        "kind": "replay_infrastructure",
        "backend": "local_sqlite",
        "clients": args.concurrency,
        "operations": args.operations,
        "elapsed_seconds": time.monotonic() - start,
        "p50_seconds": statistics.median(latencies),
        "p95_seconds": sorted(latencies)[int(len(latencies) * 0.95) - 1],
        "errors": dict(errors),
        "ledger": ledger,
        "live_model_calls": 0,
        "allocated_vms": 0,
        "live_fleet_qualified": False,
        "scientific_throughput_measured": False,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if errors or ledger["active_workers"] or ledger["reserved_cost_usd"] != "0":
        raise SystemExit("ERROR: ledger replay did not cleanly reconcile")


if __name__ == "__main__":
    main()
