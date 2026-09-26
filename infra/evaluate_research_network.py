"""Reproducible synthetic coordination comparison; no provider, VM, or proof claim."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from physharness.artifacts import LocalArtifactStore
from physharness.discussion_models import DiscussionCreate, DiscussionPostCreate
from physharness.domain import CampaignCreate, ExperimentCreate, Principal, ProblemCreate
from physharness.execution import ResponsesRuntime, RuntimeLimits
from physharness.orchestration.research_worker import (
    ResearchTaskExecutor,
    ResearchTeamRunner,
    TeamRunManifest,
)
from physharness.service import HarnessService
from physharness.storage import Database
from physharness.workforce_models import ConfigureWorkforceRequest, SeedPortfolioRequest

RESOURCE_MANIFEST = {
    "max_cost_usd": "1.000000",
    "max_concurrency": 2,
    "max_runtime_seconds": 600,
    "max_total_tasks": 2,
    "max_pending_tasks": 2,
    "root_count": 2,
    "runner_max_tasks": 2,
}
PRICES = {
    "explicit-test-model": {
        "input_usd_per_million": "1",
        "output_usd_per_million": "2",
        "source": "synthetic_mock",
    }
}


def _setup(path: Path, *, root_count: int = 2):
    if not 1 <= root_count <= 128:
        raise ValueError("Synthetic load supports 1–128 logical roots")
    database = Database(f"sqlite:///{path / 'harness.db'}")
    database.create_schema()
    service = HarnessService(database, LocalArtifactStore(path / "artifacts"))
    researcher = Principal(id="researcher", project_id="replay-lab", role="researcher")
    reviewer = Principal(id="reviewer", project_id="replay-lab", role="reviewer")
    operator = Principal(id="operator", project_id="replay-lab", role="operator")
    campaign = service.create_campaign(
        CampaignCreate(
            title="Synthetic coordination", objective="Compare protocols", programs=["quantum"]
        ),
        researcher,
        "campaign",
    )
    problem = service.create_problem(
        ProblemCreate(
            campaign_id=campaign["id"],
            title="Synthetic target",
            program="quantum",
            informal_statement="The fixture identity is one.",
            formal_statement="theorem target : (1 : Nat) = 1 := by rfl",
            assumptions=["Synthetic fixture only"],
            environment_digest="a" * 64,
        ),
        researcher,
        "problem",
    )
    service.review_problem(problem["id"], "approved", "Synthetic test review", reviewer, "review")
    experiment = service.create_experiment(
        ExperimentCreate(
            campaign_id=campaign["id"],
            problem_id=problem["id"],
            models=[{"runtime": "responses", "model": "explicit-test-model"}],
            budget={
                "max_cost_usd": RESOURCE_MANIFEST["max_cost_usd"],
                "max_concurrency": RESOURCE_MANIFEST["max_concurrency"],
                "max_runtime_seconds": RESOURCE_MANIFEST["max_runtime_seconds"],
            },
            mode="replay",
            sharing="ideas",
        ),
        researcher,
        "experiment",
    )
    service.transition_experiment(experiment["id"], "start", 1, researcher, "start")
    service.configure_workforce(
        experiment["id"],
        ConfigureWorkforceRequest(
            max_total_tasks=root_count,
            max_pending_tasks=root_count,
        ),
        operator,
        "workforce",
    )
    seeded = []
    for offset in range(0, root_count, 32):
        end = min(root_count, offset + 32)
        batch = SeedPortfolioRequest(
            roots=[
                {"title": f"Root {number}", "objective": f"Explore {number} independently"}
                for number in range(offset, end)
            ]
        )
        seeded.extend(
            service.seed_portfolio(experiment["id"], batch, operator, f"portfolio-{offset}")[
                "roots"
            ]
        )
    agents = [
        Principal(
            id=root["branch"]["execution_identity"],
            project_id="replay-lab",
            role="agent",
            experiment_id=experiment["id"],
            branch_id=root["branch"]["id"],
        )
        for root in seeded
    ]
    return service, operator, experiment, seeded, agents


def _native_response(number: int) -> dict:
    return {
        "id": f"synthetic-response-{number}",
        "object": "response",
        "created_at": 1,
        "model": "explicit-test-model",
        "status": "completed",
        "output": [
            {
                "id": f"synthetic-message-{number}",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Unverified synthetic finding.",
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _network_updates(payload: dict) -> list[dict]:
    updates = []
    for item in payload["input"]:
        if item.get("role") != "user":
            continue
        try:
            value = json.loads(item["content"])
        except (TypeError, ValueError):
            continue
        if value.get("type") == "research_network_updates":
            updates.append(value)
    return updates


async def run_case(scenario: str) -> dict:
    if scenario not in {"independent", "addressed", "subscribed"}:
        raise ValueError("Unknown synthetic scenario")
    with tempfile.TemporaryDirectory(prefix=f"network-{scenario}-") as directory:
        service, operator, experiment, roots, (alpha, beta) = _setup(Path(directory))
        if scenario == "addressed":
            service.send_message(
                alpha.branch_id,
                beta.branch_id,
                "Inspect the invariant candidate",
                [],
                alpha,
                "message",
            )
        elif scenario == "subscribed":
            topic = service.create_discussion(
                experiment["id"],
                DiscussionCreate(title="Invariant", summary="Compare ideas"),
                alpha,
                "topic",
            )
            service.subscribe_discussion(topic["id"], True, beta, "subscribe")
            service.post_discussion(
                topic["id"],
                DiscussionPostCreate(kind="finding", content="Inspect the invariant candidate"),
                alpha,
                "post",
            )

        provider_inputs = []

        async def route(request):
            payload = json.loads(request.content)
            if request.url.path.endswith("/input_tokens"):
                return httpx.Response(
                    200, json={"object": "response.input_tokens", "input_tokens": 10}
                )
            provider_inputs.append(payload)
            await asyncio.sleep(0)
            number = len(provider_inputs)
            updates = _network_updates(payload)
            tool_outputs = [
                item for item in payload["input"] if item.get("type") == "function_call_output"
            ]
            if updates and not tool_outputs:
                source = updates[-1]["items"][0]
                if source["source_kind"] in {"discussion_post", "message"}:
                    name, argument = (
                        ("read_discussion_post", "post_id")
                        if source["source_kind"] == "discussion_post"
                        else ("read_research_message", "message_id")
                    )
                    native = _native_response(number)
                    native["output"] = [
                        {
                            "id": f"synthetic-call-{number}",
                            "type": "function_call",
                            "call_id": f"retrieve-{number}",
                            "name": name,
                            "arguments": json.dumps({argument: source["retrieval_id"]}),
                            "status": "completed",
                        }
                    ]
                    return httpx.Response(200, json=native)
            return httpx.Response(200, json=_native_response(number))

        client = AsyncOpenAI(
            api_key="mock-only",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
        )
        executor = ResearchTaskExecutor(
            service,
            prices=PRICES,
            runtime_factory=lambda **kwargs: ResponsesRuntime(client=client, **kwargs),
            limits=RuntimeLimits(max_turns=4),
        )
        started = time.monotonic()
        try:
            report = await ResearchTeamRunner(service, executor=executor).run(
                TeamRunManifest(
                    experiment_id=experiment["id"],
                    project_id=operator.project_id,
                    mode="replay",
                    task_ids=[root["task"]["id"] for root in roots],
                    max_concurrency=RESOURCE_MANIFEST["max_concurrency"],
                    max_tasks=RESOURCE_MANIFEST["runner_max_tasks"],
                    timeout_seconds=30,
                    process_verifications=False,
                )
            )
        finally:
            await client.close()
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        delivered = []
        provider_context_repetitions = 0
        seen_delivery_ids = set()
        for payload in provider_inputs:
            for value in _network_updates(payload):
                if value["delivery_id"] in seen_delivery_ids:
                    provider_context_repetitions += 1
                else:
                    seen_delivery_ids.add(value["delivery_id"])
                    delivered.append(value)
        source_items = [item for batch in delivered for item in batch["items"]]
        retrievals = 0
        for payload in provider_inputs:
            for item in payload["input"]:
                if item.get("type") != "function_call_output":
                    continue
                result = json.loads(item["output"])
                if result.get("content") == "Inspect the invariant candidate":
                    retrievals += 1
        delivery_ids = [batch["delivery_id"] for batch in delivered]
        pending = service.discussion_updates(experiment["id"], beta)["items"]
        acknowledgements = [
            item
            for item in service.event_page(operator, limit=1000)["items"]
            if item["kind"] == "discussion.delivery_acknowledged"
            and item["payload"].get("experiment_id") == experiment["id"]
        ]
        return {
            "scenario": scenario,
            "mode": report["mode"],
            "evidence_level": report["evidence_level"],
            "resource_manifest": RESOURCE_MANIFEST,
            "completed_tasks": sum(item["status"] == "completed" for item in report["outcomes"]),
            "provider_requests": len(provider_inputs),
            "provider_visible_update_kinds": sorted({item["source_kind"] for item in source_items}),
            "delivery_count": len(delivery_ids),
            "acknowledged_deliveries": len(acknowledgements),
            "duplicate_delivery_ids": len(delivery_ids) - len(set(delivery_ids)),
            "provider_context_repetitions": provider_context_repetitions,
            "exact_source_retrievals": retrievals,
            "pending_deliveries_after": len(pending),
            "active_workers_after": report["ledger"]["active_workers"],
            "mock_tokens_spent": report["ledger"]["tokens_spent"],
            "wall_elapsed_ms": elapsed_ms,
            "runner_status": report["status"],
            "proof_status": "unverified",
        }


async def compare() -> dict:
    cases = [await run_case(name) for name in ("independent", "addressed", "subscribed")]
    return {
        "format": "physharness.research-network-replay.v1",
        "scientific_effectiveness": "not_measured",
        "token_accounting": "mock fixed usage, not a context-efficiency measurement",
        "cases": cases,
    }


async def load_probe(logical_roots: int = 128, attempted_tasks: int = 8) -> dict:
    """Exercise bounded canonical queueing with only two simultaneous fake workers."""
    with tempfile.TemporaryDirectory(prefix="network-logical-load-") as directory:
        service, operator, experiment, roots, _ = _setup(Path(directory), root_count=logical_roots)
        provider_calls = 0
        peak_workers = 0
        started_roots = []

        async def route(request):
            nonlocal provider_calls, peak_workers
            if request.url.path.endswith("/input_tokens"):
                return httpx.Response(
                    200, json={"object": "response.input_tokens", "input_tokens": 10}
                )
            provider_calls += 1
            payload = json.loads(request.content)
            started_roots.append(json.loads(payload["input"][0]["content"])["objective"])
            peak_workers = max(
                peak_workers, service.ledger(experiment["id"], operator)["active_workers"]
            )
            await asyncio.sleep(0)
            return httpx.Response(200, json=_native_response(provider_calls))

        client = AsyncOpenAI(
            api_key="mock-only",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
        )
        executor = ResearchTaskExecutor(
            service,
            prices=PRICES,
            runtime_factory=lambda **kwargs: ResponsesRuntime(client=client, **kwargs),
            limits=RuntimeLimits(max_turns=4),
        )
        started = time.monotonic()
        try:
            report = await ResearchTeamRunner(service, executor=executor).run(
                TeamRunManifest(
                    experiment_id=experiment["id"],
                    project_id=operator.project_id,
                    mode="replay",
                    task_ids=[root["task"]["id"] for root in roots[:attempted_tasks]],
                    max_concurrency=2,
                    max_tasks=attempted_tasks,
                    timeout_seconds=60,
                    process_verifications=False,
                )
            )
        finally:
            await client.close()
        capacity = service.research_capacity(experiment["id"], operator)
        return {
            "label": "synthetic_logical_queue_load",
            "logical_root_tasks_admitted": logical_roots,
            "attempted_tasks": report["attempted_tasks"],
            "completed_tasks": sum(item["status"] == "completed" for item in report["outcomes"]),
            "queued_tasks_after": capacity["queued_tasks"],
            "peak_mock_workers": peak_workers,
            "provider_requests": provider_calls,
            "provider_start_order": started_roots,
            "active_workers_after": report["ledger"]["active_workers"],
            "wall_elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "qualification": "not_live_scale_or_mathematical_effectiveness",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--load-roots", type=int, default=128)
    arguments = parser.parse_args()
    report = asyncio.run(compare())
    report["load_probe"] = asyncio.run(load_probe(arguments.load_roots))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(arguments.output)


if __name__ == "__main__":
    main()
