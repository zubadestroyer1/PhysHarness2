"""Atomic operator ceiling increase for an already running experiment."""

import importlib.util
from pathlib import Path

import pytest
from test_core import setup_experiment

from physharness.domain import Principal
from physharness.errors import HarnessError
from physharness.storage import ReservationRow

HELPER = (
    Path(__file__).resolve().parents[1] / "work/hardening-final-2026-09-24/amend_live_budget.py"
)
SPEC = importlib.util.spec_from_file_location("hardening_budget_amendment", HELPER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
amend_live_budget = MODULE.amend_live_budget


def test_running_amendment_preserves_reservations_usage_and_idempotence(lab):
    service, researcher, _ = lab
    experiment, _ = setup_experiment(lab, cost="8.796745", concurrency=2)
    started = service.transition_experiment(experiment["id"], "start", 1, researcher, "start")
    operator = Principal(id="budget-operator", project_id=researcher.project_id, role="operator")
    settled = service.reserve_resources(experiment["id"], "0.75", 0, operator, "spent-hold")
    service.settle_resources(settled["id"], "0.60", False, operator, "spent-settlement")
    reservation = service.reserve_resources(experiment["id"], "2.50", 1, operator, "hold")
    before = service.ledger(experiment["id"], operator)
    assert before["spent_cost_usd"] == "0.6"
    kwargs = dict(
        experiment_id=experiment["id"],
        actor=operator,
        key="authorized-amendment",
        expected_revision=started["revision"],
        expected_old_usd="8.796745",
        new_max_usd="100",
        authorization_ref="user-authorized-live-retry-100",
    )
    changed = amend_live_budget(service, **kwargs)
    assert changed["budget"]["max_cost_usd"] == "100"
    assert changed["revision"] == started["revision"] + 1
    after = service.ledger(experiment["id"], operator)
    assert after["max_cost_usd"] == "100"
    for field in (
        "spent_cost_usd",
        "reserved_cost_usd",
        "active_workers",
        "tokens_spent",
        "tokens_reserved",
    ):
        assert after[field] == before[field]
    with service.db.sessions() as session:
        held = session.get(ReservationRow, reservation["id"])
        assert held is not None and held.state == "active" and held.reserved == 2_500_000
    assert amend_live_budget(service, **kwargs) == changed
    events = [e for e in service.events(operator) if e["kind"] == "experiment.budget.amended"]
    assert len(events) == 1
    assert events[0]["payload"]["authorization_ref"] == kwargs["authorization_ref"]
    with pytest.raises(HarnessError) as mismatch:
        amend_live_budget(service, **{**kwargs, "new_max_usd": "99"})
    assert mismatch.value.code == "IDEMPOTENCY_CONFLICT"


def test_stale_ceiling_revision_scope_and_agent_rejected(lab):
    service, researcher, _ = lab
    experiment, _ = setup_experiment(lab, cost="8.796745")
    started = service.transition_experiment(experiment["id"], "start", 1, researcher, "start")
    operator = Principal(id="budget-operator", project_id=researcher.project_id, role="operator")
    kwargs = dict(
        experiment_id=experiment["id"],
        actor=operator,
        expected_revision=started["revision"],
        expected_old_usd="8.796745",
        new_max_usd="100",
        authorization_ref="user-authorized-live-retry-100",
    )
    for changes, code in (
        ({"expected_revision": 1}, "REVISION_CONFLICT"),
        ({"expected_old_usd": "8.00"}, "BUDGET_CEILING_CONFLICT"),
        (
            {"actor": Principal(id="other", project_id="other-project", role="operator")},
            "NOT_FOUND",
        ),
        (
            {
                "actor": Principal(
                    id="agent",
                    project_id=researcher.project_id,
                    role="agent",
                    experiment_id=experiment["id"],
                )
            },
            "FORBIDDEN",
        ),
        ({"new_max_usd": "100.000001"}, "INVALID_BUDGET_AMENDMENT"),
    ):
        with pytest.raises(HarnessError) as error:
            amend_live_budget(
                service, key=f"negative-{code}-{len(changes)}", **{**kwargs, **changes}
            )
        assert error.value.code == code
    assert service.ledger(experiment["id"], operator)["max_cost_usd"] == "8.796745"
