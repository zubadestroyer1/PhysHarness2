import asyncio
from decimal import Decimal

import httpx
import pytest
from test_core import setup_experiment
from test_execution_responses import message
from test_research_loop_integration import campaign, mock_executor, response

from physharness.domain import Principal
from physharness.execution import ExecutionError
from physharness.orchestration.research_worker import (
    ResearchTeamRunner,
    TeamRunManifest,
    _reserve_model_with_wait,
)


def running_experiment(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, cost="1.00")
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    operator = Principal(id="operator", project_id=actor.project_id, role="operator")
    return service, operator, experiment["id"]


async def reserve(service, experiment_id, actor, operation_id="response"):
    return await _reserve_model_with_wait(
        service, experiment_id, Decimal("0.50"), 100, actor, operation_id, None
    )


@pytest.mark.asyncio
async def test_model_reservation_waits_for_a_confirmed_hold_to_settle(lab):
    service, actor, experiment_id = running_experiment(lab)
    held = service.reserve_resources(experiment_id, "0.75", 0, actor, "held")
    waiting = asyncio.create_task(reserve(service, experiment_id, actor))
    await asyncio.sleep(0.05)
    assert not waiting.done()
    assert Decimal(service.ledger(experiment_id, actor)["reserved_cost_usd"]) == Decimal("0.75")
    service.settle_resources(held["id"], "0.10", False, actor, "settle-held")
    admitted = await asyncio.wait_for(waiting, 2)
    assert admitted["id"]
    ledger = service.ledger(experiment_id, actor)
    assert Decimal(ledger["spent_cost_usd"]) == Decimal("0.10")
    assert Decimal(ledger["reserved_cost_usd"]) == Decimal("0.50")


@pytest.mark.asyncio
async def test_cancelled_wait_does_not_allocate_model_funds(lab):
    service, actor, experiment_id = running_experiment(lab)
    service.reserve_resources(experiment_id, "0.75", 0, actor, "held")
    waiting = asyncio.create_task(reserve(service, experiment_id, actor))
    await asyncio.sleep(0.05)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert Decimal(service.ledger(experiment_id, actor)["reserved_cost_usd"]) == Decimal("0.75")


@pytest.mark.asyncio
async def test_uncertain_hold_stops_wait_for_reconciliation(lab):
    service, actor, experiment_id = running_experiment(lab)
    held = service.reserve_resources(experiment_id, "0.75", 0, actor, "held")
    service.settle_resources(held["id"], None, True, actor, "uncertain-held")
    with pytest.raises(ExecutionError) as error:
        await reserve(service, experiment_id, actor)
    assert error.value.code == "BUDGET_RECONCILIATION_REQUIRED"
    assert Decimal(service.ledger(experiment_id, actor)["reserved_cost_usd"]) == Decimal("0.75")


@pytest.mark.asyncio
async def test_spent_balance_below_request_is_genuine_exhaustion(lab):
    service, actor, experiment_id = running_experiment(lab)
    held = service.reserve_resources(experiment_id, "0.75", 0, actor, "held")
    service.settle_resources(held["id"], "0.75", False, actor, "settle-held")
    with pytest.raises(ExecutionError) as error:
        await reserve(service, experiment_id, actor)
    assert error.value.code == "BUDGET_EXCEEDED"
    assert "0.500000" in str(error.value)
    assert "0.250000" in str(error.value)


@pytest.mark.asyncio
async def test_worker_stops_after_settlement_exceeds_reserved_cost(lab):
    service, actor, _ = lab
    experiment, _, task = campaign(lab, concurrency=1)
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        native = response([message("reported usage beyond reservation")])
        native["usage"] = {
            "input_tokens": 100_000,
            "output_tokens": 5,
            "total_tokens": 100_005,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }
        return httpx.Response(200, json=native)

    executor, client = mock_executor(service, handler)
    try:
        report = await ResearchTeamRunner(service, executor=executor).run(
            TeamRunManifest(
                experiment_id=experiment["id"],
                project_id=actor.project_id,
                mode="replay",
                task_ids=[task["id"]],
                max_concurrency=1,
                max_tasks=1,
                timeout_seconds=10,
            )
        )
    finally:
        await client.close()
    assert calls == 1
    assert report["outcomes"][0]["code"] == "BUDGET_RECONCILIATION_REQUIRED"
    assert (
        service.get_record("experiment", experiment["id"], actor)["budget_reconciliation_required"]
        is True
    )
