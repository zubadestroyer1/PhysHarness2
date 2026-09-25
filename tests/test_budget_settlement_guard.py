"""An incurred charge beyond its hold is recorded and blocks further spending."""

from decimal import Decimal

import pytest
from test_core import setup_experiment

from physharness.domain import Principal
from physharness.errors import HarnessError


def test_over_reserve_settlement_preserves_actual_and_blocks_future_allocations(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, cost="1.00")
    started = service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    reservation = service.reserve_resources(experiment["id"], "0.40", 1, actor, "hold")
    operator = Principal(id="controller", project_id=actor.project_id, role="operator")

    settled = service.settle_resources(
        reservation["id"], "1.10", False, operator, "settle", actual_tokens=5
    )
    assert settled["state"] == "settled"
    assert Decimal(settled["actual_cost_usd"]) == Decimal("1.10")
    assert settled["reconciliation_required"] is True
    assert settled["code"] == "BUDGET_RECONCILIATION_REQUIRED"
    assert (
        service.settle_resources(
            reservation["id"], "1.10", False, operator, "settle", actual_tokens=5
        )
        == settled
    )
    assert (
        service.settle_resources(
            reservation["id"], "1.10", False, operator, "settle-replay", actual_tokens=5
        )["reconciliation_required"]
        is True
    )
    assert Decimal(service.ledger(experiment["id"], actor)["spent_cost_usd"]) == Decimal("1.10")
    flagged = service.get_record("experiment", experiment["id"], actor)
    assert flagged["budget_reconciliation_required"] is True
    assert flagged["status"] == started["status"]
    with pytest.raises(HarnessError) as error:
        service.reserve_resources(experiment["id"], "0", 1, actor, "another-worker")
    assert error.value.code == "BUDGET_RECONCILIATION_REQUIRED"
    events = service.events(actor)
    assert any(event["kind"] == "resources.overrun" for event in events)


def test_over_reserve_charge_within_envelope_still_requires_reconciliation(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, cost="1.00")
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    reservation = service.reserve_resources(experiment["id"], "0.10", 0, actor, "hold")
    operator = Principal(id="controller", project_id=actor.project_id, role="operator")
    result = service.settle_resources(reservation["id"], "0.20", False, operator, "settle")
    assert result["reconciliation_required"] is True
    assert Decimal(service.ledger(experiment["id"], actor)["spent_cost_usd"]) == Decimal("0.20")
