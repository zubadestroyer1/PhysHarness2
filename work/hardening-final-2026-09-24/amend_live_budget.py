"""Operator-only, idempotent increase of one live experiment's USD ceiling.

The caller supplies the exact observed revision and old ceiling. This module has
no credential loading or automatic execution against a live database.
"""

from __future__ import annotations

from sqlalchemy import select

from physharness.domain import Principal
from physharness.errors import HarnessError
from physharness.service import HarnessService, money_string, money_units
from physharness.storage import BudgetRow

MAX_AMENDED_USD_UNITS = money_units("100")


def amend_live_budget(
    service: HarnessService,
    *,
    experiment_id: str,
    actor: Principal,
    key: str,
    expected_revision: int,
    expected_old_usd: str,
    new_max_usd: str,
    authorization_ref: str,
) -> dict:
    """Increase one live experiment's cost cap without touching reservations or usage."""
    if actor.role != "operator" or actor.experiment_id or actor.branch_id:
        raise HarnessError("FORBIDDEN", "A project operator identity is required.", status=403)
    if type(expected_revision) is not int or expected_revision < 1:
        raise HarnessError("REVISION_CONFLICT", "Exact positive experiment revision required.")
    if not isinstance(authorization_ref, str) or not 1 <= len(authorization_ref.strip()) <= 200:
        raise HarnessError(
            "AUTHORIZATION_REFERENCE_REQUIRED",
            "Record the explicit user authorization for this amendment.",
            status=422,
        )
    old_units = money_units(expected_old_usd)
    new_units = money_units(new_max_usd)
    if new_units <= old_units or new_units > MAX_AMENDED_USD_UNITS:
        raise HarnessError(
            "INVALID_BUDGET_AMENDMENT",
            "The new ceiling must increase the current ceiling and remain at or below $100.",
            status=422,
        )
    inputs = {
        "experiment_id": experiment_id,
        "expected_revision": expected_revision,
        "expected_old_usd": money_string(old_units),
        "new_max_usd": money_string(new_units),
        "authorization_ref": authorization_ref.strip(),
    }

    def action(session, operation_id):
        experiment = service._get(session, "experiment", experiment_id, actor)
        session.refresh(experiment, with_for_update=True)
        if experiment.revision != expected_revision:
            raise HarnessError("REVISION_CONFLICT", "Experiment revision changed before amendment.")
        if experiment.payload["status"] not in {"queued", "running"}:
            raise HarnessError("EXPERIMENT_NOT_ACTIVE", "Only a live experiment can be amended.")
        observed_old = money_units(experiment.payload["budget"]["max_cost_usd"])
        budget = session.scalar(
            select(BudgetRow).where(BudgetRow.experiment_id == experiment_id).with_for_update()
        )
        if budget is None or observed_old != old_units or budget.max_cost != old_units:
            raise HarnessError(
                "BUDGET_CEILING_CONFLICT", "Current budget ceiling differs from expected."
            )
        if budget.spent + budget.reserved > new_units:
            raise HarnessError(
                "BUDGET_RECONCILIATION_REQUIRED", "Existing charges exceed new ceiling."
            )
        budget.max_cost = new_units
        revised_budget = {**experiment.payload["budget"], "max_cost_usd": money_string(new_units)}
        updated = service._replace(
            session, experiment, {"budget": revised_budget}, expected_revision
        )
        service._event(
            session,
            actor,
            operation_id,
            "experiment.budget.amended",
            experiment_id,
            {
                "old_max_cost_usd": money_string(old_units),
                "new_max_cost_usd": money_string(new_units),
                "authorization_ref": authorization_ref.strip(),
                "revision": updated["revision"],
                "actor_id": actor.id,
            },
        )
        return updated

    return service._execute(actor, key, "experiment.budget.amend", inputs, action)
