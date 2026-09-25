"""Replay-only coordination comparison over the canonical service and runner."""

import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from physharness.execution import ResponsesRuntime, RuntimeLimits
from physharness.orchestration.research_worker import (
    ResearchTaskExecutor,
    ResearchTeamRunner,
    TeamRunManifest,
)

RUNNER = Path(__file__).resolve().parents[1] / "infra/evaluate_research_network.py"
SPEC = importlib.util.spec_from_file_location("network_replay_evaluation", RUNNER)
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


async def test_replay_comparison_keeps_same_envelope_and_counts_actual_deliveries():
    report = await evaluation.compare()
    cases = {case["scenario"]: case for case in report["cases"]}
    assert set(cases) == {"independent", "addressed", "subscribed"}
    assert len({tuple(sorted(case["resource_manifest"].items())) for case in cases.values()}) == 1
    assert all(
        case["mode"] == "replay" and case["evidence_level"] == "mock_provider"
        for case in cases.values()
    )
    assert all(case["completed_tasks"] == 2 for case in cases.values())
    assert cases["independent"]["provider_visible_update_kinds"] == []
    assert cases["addressed"]["provider_visible_update_kinds"] == ["message"]
    assert cases["subscribed"]["provider_visible_update_kinds"] == ["discussion_post"]
    assert cases["addressed"]["exact_source_retrievals"] == 1
    assert cases["subscribed"]["exact_source_retrievals"] == 1
    assert all(case["active_workers_after"] == 0 for case in cases.values())
    assert all(case["pending_deliveries_after"] == 0 for case in cases.values())
    assert report["scientific_effectiveness"] == "not_measured"


async def test_logical_queue_load_keeps_few_mock_workers_and_pending_work_visible():
    probe = await evaluation.load_probe(logical_roots=16, attempted_tasks=4)
    assert probe["logical_root_tasks_admitted"] == 16
    assert probe["completed_tasks"] == probe["provider_requests"] == 4
    assert probe["queued_tasks_after"] == 12
    assert 1 <= probe["peak_mock_workers"] <= 2
    assert probe["active_workers_after"] == 0
    assert probe["qualification"] == "not_live_scale_or_mathematical_effectiveness"


async def test_concurrent_fake_agents_exchange_artifact_during_runner_and_read_exact_source(
    tmp_path,
):
    service, operator, experiment, roots, _ = evaluation._setup(tmp_path)
    sent = asyncio.Event()
    seen = {"beta_update": False, "beta_message": False, "beta_artifact": False}
    request_number = 0

    def tool_response(number, name, args, call_id):
        response = evaluation._native_response(number)
        response["output"] = [
            {
                "id": f"fc-{number}",
                "type": "function_call",
                "name": name,
                "arguments": json.dumps(args),
                "call_id": call_id,
                "status": "completed",
            }
        ]
        return response

    async def route(request):
        nonlocal request_number
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        payload = json.loads(request.content)
        request_number += 1
        number = request_number
        objective = json.loads(payload["input"][0]["content"])["objective"]
        outputs = {
            item.get("call_id"): json.loads(item["output"])
            for item in payload["input"]
            if item.get("type") == "function_call_output"
        }
        if objective == "Explore 0 independently":
            if "store-a" not in outputs:
                return httpx.Response(
                    200,
                    json=tool_response(
                        number,
                        "store_artifact",
                        {"kind": "research_note", "content": "Check invariant I"},
                        "store-a",
                    ),
                )
            if "send-a" not in outputs:
                artifact_id = outputs["store-a"]["id"]
                return httpx.Response(
                    200,
                    json=tool_response(
                        number,
                        "send_message",
                        {
                            "recipient_id": roots[1]["branch"]["id"],
                            "content": "Check invariant I in the linked note",
                            "artifact_ids": [artifact_id],
                        },
                        "send-a",
                    ),
                )
            sent.set()
            return httpx.Response(200, json=evaluation._native_response(number))
        if "wait-b" not in outputs:
            await asyncio.wait_for(sent.wait(), 3)
            return httpx.Response(
                200, json=tool_response(number, "research_capacity", {}, "wait-b")
            )
        updates = evaluation._network_updates(payload)
        seen["beta_update"] = any(
            item["source_kind"] == "message" for batch in updates for item in batch["items"]
        )
        if "read-b" not in outputs:
            assert seen["beta_update"]
            item = next(
                item
                for batch in updates
                for item in batch["items"]
                if item["source_kind"] == "message"
            )
            return httpx.Response(
                200,
                json=tool_response(
                    number, "read_research_message", {"message_id": item["retrieval_id"]}, "read-b"
                ),
            )
        exact = outputs["read-b"]
        seen["beta_message"] = exact["content"] == "Check invariant I in the linked note"
        if "artifact-b" not in outputs:
            return httpx.Response(
                200,
                json=tool_response(
                    number, "read_artifact", {"artifact_id": exact["artifact_ids"][0]}, "artifact-b"
                ),
            )
        seen["beta_artifact"] = "Check invariant I" in str(outputs["artifact-b"])
        return httpx.Response(200, json=evaluation._native_response(number))

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    executor = ResearchTaskExecutor(
        service,
        prices=evaluation.PRICES,
        runtime_factory=lambda **kwargs: ResponsesRuntime(client=client, **kwargs),
        limits=RuntimeLimits(max_turns=10),
    )
    try:
        report = await ResearchTeamRunner(service, executor=executor).run(
            TeamRunManifest(
                experiment_id=experiment["id"],
                project_id=operator.project_id,
                mode="replay",
                task_ids=[root["task"]["id"] for root in roots],
                max_concurrency=2,
                max_tasks=2,
                timeout_seconds=15,
                process_verifications=False,
            )
        )
    finally:
        await client.close()
    assert report["status"] == "completed"
    assert seen == {"beta_update": True, "beta_message": True, "beta_artifact": True}
    assert report["ledger"]["active_workers"] == 0
