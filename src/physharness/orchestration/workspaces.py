"""Fenced, budgeted VM lifecycle using the canonical database and artifact store.

No provider call occurs inside a database transaction. Durable pending records
prevent repeated dispatch; the provider cannot enforce SQL fences itself, so a
fence lost during a call produces a reconciliation record, never success.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from ..domain import Principal, canonical_json, digest_json, new_id, utcnow
from ..errors import HarnessError
from ..execution.e2b import WorkspaceArchive
from ..execution.types import CommandRequest, CommandResult, ExecutionError
from ..service import HarnessService, money_string, money_units, require_role
from ..storage import BudgetRow, RecordRow, ReservationRow


def _identifier(*parts: str) -> str:
    return str(uuid5(NAMESPACE_URL, digest_json(parts)))


def _reconcile(message: str = "VM outcome requires operator reconciliation.") -> HarnessError:
    return HarnessError(
        "WORKSPACE_RECONCILIATION_REQUIRED",
        message,
        remediation="Reconcile recorded VM identity and provider charges; "
        "do not retry allocation or release its reservation automatically.",
    )


class CanonicalWorkspaceJournal:
    """Synchronous CommandJournal contract backed exclusively by canonical records.

    Native child allocation is deliberately prohibited: it needs another broker
    reservation and lifecycle, which this bounded version does not implement.
    """

    def __init__(self, broker: WorkspaceBroker, workspace_id: str):
        self.broker, self.workspace_id = broker, workspace_id

    def begin(
        self, program_id: str, operation_id: str, command: str, arguments: dict[str, Any]
    ) -> dict | None:
        if command in {"fork", "restore_snapshot"}:
            raise ExecutionError(
                "CAPABILITY_UNAVAILABLE",
                "Native child allocation requires a separate broker reservation",
            )
        b = self.broker
        identity = b._operation_id(self.workspace_id, "native:" + program_id + ":" + operation_id)
        with b.service.db.transaction() as session:
            b._lock(session)
            workspace = b._workspace(session, self.workspace_id)
            b._guard(session, workspace, workspace.payload["execution_id"])
            if program_id != "e2b:" + workspace.payload["execution_id"]:
                raise ExecutionError(
                    "CHECKPOINT_MISMATCH", "Native journal execution identity mismatch"
                )
            inputs = {"program_id": program_id, "command": command, "arguments": arguments}
            prior = b._prior(session, identity, inputs)
            if prior is not None:
                return prior
            if workspace.payload["status"] != "ready" or workspace.payload.get(
                "active_operation_id"
            ):
                raise _reconcile("Workspace has another pending or uncertain operation.")
            b._operation(session, identity, workspace.payload, command, inputs)
            b.service._replace(session, workspace, {"active_operation_id": identity})
            return None

    def complete(self, program_id: str, operation_id: str, result: dict[str, Any]) -> None:
        if not isinstance(result, dict):
            raise ExecutionError(
                "INVALID_TOOL_RESULT", "Native journal result must be a JSON object"
            )
        b = self.broker
        identity = b._operation_id(self.workspace_id, "native:" + program_id + ":" + operation_id)
        with b.service.db.transaction() as session:
            b._lock(session)
            workspace = b._workspace(session, self.workspace_id)
            b._guard(session, workspace, workspace.payload["execution_id"])
            op = b.service._get(session, "workspace_operation", identity, b.actor)
            if op.payload["status"] != "pending":
                raise ExecutionError("OPERATION_CONFLICT", "Native operation is no longer pending")
            if workspace.payload.get("active_operation_id") != identity:
                raise ExecutionError("OPERATION_CONFLICT", "Native operation ownership changed")
            values = {"active_operation_id": None}
            if result.get("kind") in {"pause", "snapshot"}:
                artifact = b._artifact(
                    session,
                    workspace.payload,
                    canonical_json(result).encode(),
                    "native_checkpoint",
                    identity,
                )
                values["checkpoint_artifact_id"] = artifact["id"]
            b.service._replace(
                session, op, {"status": "completed", "result": copy.deepcopy(result)}
            )
            if values:
                b.service._replace(session, workspace, values)


class WorkspaceBroker:
    def __init__(
        self,
        service: HarnessService,
        *,
        actor: Principal,
        task_id: str,
        holder: str,
        fence: int,
        provider_factory: Callable[..., Any],
        provider_spec: dict[str, Any],
        worker_slot_id: str | None = None,
    ):
        require_role(actor, "operator")
        if (
            set(provider_spec) != {"provider", "template_id", "timeout_seconds"}
            or provider_spec["provider"] != "e2b"
            or not isinstance(provider_spec["template_id"], str)
            or not provider_spec["template_id"].strip()
            or provider_spec["template_id"] != provider_spec["template_id"].strip()
            or isinstance(provider_spec["timeout_seconds"], bool)
            or not isinstance(provider_spec["timeout_seconds"], int)
            or provider_spec["timeout_seconds"] <= 0
        ):
            raise HarnessError(
                "INVALID_PROVIDER_SPEC",
                "Supply exact E2B template ID and positive timeout; no credentials.",
                status=422,
            )
        self.service, self.actor, self.task_id = service, actor, task_id
        self.holder, self.fence = holder, fence
        self.provider_factory = provider_factory
        self.provider_spec = copy.deepcopy(provider_spec)
        self._providers: dict[str, Any] = {}
        self.worker_slot_id = worker_slot_id
        self.reconciliation_observations: dict[str, dict[str, Any]] = {}

    def inspect(self, workspace_id: str) -> dict:
        """Operator-only current observation; grants no mutation authority."""
        require_role(self.actor, "operator")
        with self.service.db.sessions() as session:
            return copy.deepcopy(self._workspace(session, workspace_id).payload)

    def _lock(self, session):
        self.service.db.command_lock(session, digest_json(["workspace-task", self.task_id]))

    def _operation_id(self, workspace_id, operation_id):
        if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 500:
            raise HarnessError(
                "INVALID_OPERATION_ID", "Explicit bounded operation ID required.", status=422
            )
        return _identifier(self.actor.project_id, self.task_id, workspace_id, operation_id)

    def _workspace(self, session, identifier):
        row = self.service._get(session, "workspace", identifier, self.actor)
        if row.payload["task_id"] != self.task_id:
            raise HarnessError("WORKSPACE_SCOPE", "Workspace belongs to another task.", status=403)
        return row

    def _guard(self, session, workspace=None, execution_id=None, *, cleanup=False):
        require_role(self.actor, "operator")
        task = self.service._get(session, "task", self.task_id, self.actor)
        if cleanup:
            experiment = self.service._get(
                session, "experiment", task.payload["experiment_id"], self.actor
            )
            session.refresh(experiment, with_for_update=True)
        else:
            self.service._active(session, task.payload["experiment_id"], self.actor)
            if task.payload["status"] != "running" or task.payload.get("cancel_requested"):
                raise HarnessError("TASK_NOT_RUNNABLE", "Task is cancelled or no longer running.")
        self.service._fenced(session, self.task_id, self.holder, self.fence)
        if self.worker_slot_id:
            slot = session.scalar(
                select(ReservationRow)
                .where(ReservationRow.id == self.worker_slot_id)
                .with_for_update()
            )
            if (
                task.payload.get("worker_slot_id") != self.worker_slot_id
                or slot is None
                or slot.state != "active"
                or slot.workers != 1
                or slot.experiment_id != task.payload["experiment_id"]
            ):
                raise HarnessError(
                    "WORKER_SLOT_AUTHORITY",
                    "Shared worker slot requires the task's active controller reservation.",
                )
        if workspace is not None:
            data = workspace.payload
            if data.get("shared_worker_slot_id") != self.worker_slot_id:
                raise HarnessError(
                    "WORKER_SLOT_AUTHORITY", "Workspace shared slot binding changed."
                )
            if (
                data["holder"] != self.holder
                or data["fence"] != self.fence
                or data["experiment_id"] != task.payload["experiment_id"]
            ):
                raise HarnessError("STALE_LEASE", "Workspace belongs to a different task fence.")
            if not execution_id or data["execution_id"] != execution_id:
                raise HarnessError(
                    "WORKSPACE_IDENTITY_MISMATCH", "Exact known VM execution identity required."
                )
        return task.payload

    def _inputs(self, values):
        return {
            "holder": self.holder,
            "fence": self.fence,
            "provider_spec": self.provider_spec,
            "worker_slot_id": self.worker_slot_id,
            **values,
        }

    def _prior(self, session, identity, inputs):
        row = session.get(RecordRow, identity)
        if row is None:
            return None
        if row.project_id != self.actor.project_id or row.kind != "workspace_operation":
            raise HarnessError("WORKSPACE_SCOPE", "Operation identity belongs to another scope.")
        if row.payload["fingerprint"] != digest_json(self._inputs(inputs)):
            raise HarnessError(
                "IDEMPOTENCY_CONFLICT", "Operation ID already identifies different inputs."
            )
        if row.payload["status"] in {"rejected", "failed"}:
            raise HarnessError(
                row.payload["result"]["code"],
                row.payload["result"]["message"],
                operation_id=identity,
            )
        if row.payload["status"] != "completed":
            raise _reconcile(
                "Pending or uncertain VM operation requires reconciliation before retry."
            )
        return copy.deepcopy(row.payload["result"])

    def _operation(self, session, identity, workspace, command, inputs):
        payload = {
            "id": identity,
            "kind": "workspace_operation",
            "project_id": self.actor.project_id,
            "revision": 1,
            "created_at": utcnow().isoformat(),
            "origin_actor_id": self.actor.id,
            "experiment_id": workspace["experiment_id"],
            "branch_id": workspace["branch_id"],
            "task_id": self.task_id,
            "workspace_id": workspace["id"],
            "command": command,
            "fingerprint": digest_json(self._inputs(inputs)),
            "inputs": self._inputs(inputs),
            "status": "pending",
            "result": None,
        }
        session.add(
            RecordRow(
                id=identity,
                project_id=self.actor.project_id,
                kind="workspace_operation",
                revision=1,
                payload=payload,
            )
        )
        self.service._event(
            session,
            self.actor,
            identity,
            "workspace.operation.pending",
            workspace["id"],
            {"command": command, "task_id": self.task_id},
        )

    async def provision(self, *, cost_bound_usd: str, operation_id: str) -> dict:
        amount = money_units(cost_bound_usd)
        if amount <= 0:
            raise HarnessError(
                "VM_COST_BOUND_REQUIRED",
                "Supply an explicit positive conservative VM cost bound.",
                status=422,
            )
        identity = self._operation_id("provision", operation_id)
        inputs = {"cost_bound_units": amount, "task_id": self.task_id}
        with self.service.db.transaction() as session:
            self._lock(session)
            task = self._guard(session)
            prior = self._prior(session, identity, inputs)
            if prior is not None:
                return copy.deepcopy(self._workspace(session, prior["id"]).payload)
            experiment = self.service._get(session, "experiment", task["experiment_id"], self.actor)
            elapsed = (
                utcnow() - datetime.fromisoformat(experiment.payload["started_at"])
            ).total_seconds()
            remaining = experiment.payload["budget"]["max_runtime_seconds"] - elapsed
            if self.provider_spec["timeout_seconds"] > remaining:
                raise HarnessError(
                    "EXPERIMENT_DEADLINE", "VM timeout exceeds remaining experiment runtime."
                )
            budget = session.scalar(
                select(BudgetRow)
                .where(BudgetRow.experiment_id == task["experiment_id"])
                .with_for_update()
            )
            if budget.spent + budget.reserved + amount > budget.max_cost:
                raise HarnessError(
                    "BUDGET_EXCEEDED", "VM reservation exceeds experiment budget envelope."
                )
            workers = 0 if self.worker_slot_id else 1
            if self.worker_slot_id:
                existing = session.scalars(
                    select(RecordRow).where(
                        RecordRow.project_id == self.actor.project_id,
                        RecordRow.kind == "workspace",
                        RecordRow.payload["shared_worker_slot_id"].as_string()
                        == self.worker_slot_id,
                    )
                )
                if any(row.payload["status"] != "destroyed" for row in existing):
                    raise HarnessError(
                        "WORKER_SLOT_IN_USE",
                        "Shared worker slot already has an unresolved workspace.",
                    )
            if budget.active_workers + workers > budget.max_concurrency:
                raise HarnessError(
                    "CONCURRENCY_EXCEEDED", "No experiment concurrency slot for another VM."
                )
            reservation_id = new_id()
            session.add(
                ReservationRow(
                    id=reservation_id,
                    experiment_id=task["experiment_id"],
                    reserved=amount,
                    workers=workers,
                    state="active",
                    tokens_reserved=0,
                )
            )
            budget.reserved += amount
            budget.active_workers += workers
            workspace = self.service._insert(
                session,
                "workspace",
                self.actor,
                {
                    "task_id": self.task_id,
                    "experiment_id": task["experiment_id"],
                    "branch_id": task["branch_id"],
                    "holder": self.holder,
                    "fence": self.fence,
                    "provider_spec": self.provider_spec,
                    "reservation_id": reservation_id,
                    "shared_worker_slot_id": self.worker_slot_id,
                    "cost_bound_usd": money_string(amount),
                    "status": "provisioning",
                    "execution_id": None,
                    "active_operation_id": identity,
                    "checkpoint_artifact_id": None,
                },
            )
            self._operation(session, identity, workspace, "provision", inputs)
            self.service._event(
                session,
                self.actor,
                identity,
                "resources.reserved",
                task["experiment_id"],
                {
                    "reservation_id": reservation_id,
                    "workspace_id": workspace["id"],
                    "reserved_cost_usd": money_string(amount),
                    "workers": workers,
                },
            )
        provider, observed = None, None
        try:
            provider = self.provider_factory(
                journal=CanonicalWorkspaceJournal(self, workspace["id"])
            )
            if (
                provider.template_id != self.provider_spec["template_id"]
                or provider.timeout_seconds != self.provider_spec["timeout_seconds"]
                or provider.capabilities.isolation != "provider_vm"
                or not provider.capabilities.available
                or provider.network_disabled is not True
            ):
                raise HarnessError(
                    "PROVIDER_POLICY_MISMATCH",
                    "Factory did not provide the qualified isolated VM configuration.",
                )
            await provider.create()
            observed = provider.execution_id
            if not isinstance(observed, str) or not observed:
                raise HarnessError(
                    "WORKSPACE_IDENTITY_MISMATCH", "Provider returned no execution identity."
                )
            self._providers[workspace["id"]] = provider
            with self.service.db.transaction() as session:
                self._lock(session)
                self._guard(session)
                row = self._workspace(session, workspace["id"])
                result = self.service._replace(
                    session,
                    row,
                    {"status": "ready", "execution_id": observed, "active_operation_id": None},
                )
                op = self.service._get(session, "workspace_operation", identity, self.actor)
                self.service._replace(session, op, {"status": "completed", "result": result})
                self.service._event(
                    session,
                    self.actor,
                    identity,
                    "workspace.ready",
                    row.id,
                    {"execution_id": observed},
                )
            return result
        except BaseException as exc:
            self._uncertain(workspace["id"], identity, observed_execution_id=observed)
            raise _reconcile(
                "VM provision outcome requires reconciliation; reservation remains held."
            ) from exc

    def _uncertain(
        self, workspace_id, operation_id, *, observed_execution_id=None, destruction_confirmed=False
    ):
        observation = {
            "workspace_id": workspace_id,
            "operation_id": operation_id,
            "execution_id": observed_execution_id,
            "destruction_confirmed": destruction_confirmed,
            "reservation_held": True,
        }
        self.reconciliation_observations[workspace_id] = observation
        try:
            self._record_uncertainty(
                workspace_id,
                operation_id,
                observed_execution_id=observed_execution_id,
                destruction_confirmed=destruction_confirmed,
            )
        except Exception as exc:
            raise HarnessError(
                "WORKSPACE_RECONCILIATION_REQUIRED",
                f"Cannot persist reconciliation for workspace {workspace_id}, "
                f"VM {observed_execution_id}. "
                "Reservation remains held; retain this observation for recovery.",
                details=observation,
            ) from exc

    def _record_uncertainty(
        self, workspace_id, operation_id, *, observed_execution_id=None, destruction_confirmed=False
    ):
        # Observation-only authority: cannot mark ready, release a reservation or
        # change task ownership. Useful even when the dispatching lease has expired.
        with self.service.db.transaction() as session:
            self._lock(session)
            workspace = self._workspace(session, workspace_id)
            op = self.service._get(session, "workspace_operation", operation_id, self.actor)
            if op.payload["status"] == "completed":
                return
            values = {
                "status": "reconciliation_required",
                "destruction_confirmed": destruction_confirmed,
            }
            if observed_execution_id:
                values["execution_id"] = observed_execution_id
            self.service._replace(session, workspace, values)
            self.service._replace(session, op, {"status": "reconciliation_required"})
            reservation = session.get(ReservationRow, workspace.payload["reservation_id"])
            if reservation.state != "settled":
                reservation.state = "uncertain"
            self.service._event(
                session,
                self.actor,
                operation_id,
                "workspace.reconciliation_required",
                workspace_id,
                {
                    "execution_id": observed_execution_id or workspace.payload["execution_id"],
                    "reservation_held": True,
                    "destruction_confirmed": destruction_confirmed,
                },
            )

    def _start(self, workspace_id, execution_id, operation_id, command, inputs, *, cleanup=False):
        identity = self._operation_id(workspace_id, operation_id)
        inputs = {"execution_id": execution_id, "command": command, **inputs}
        with self.service.db.transaction() as session:
            self._lock(session)
            row = self._workspace(session, workspace_id)
            self._guard(session, row, execution_id, cleanup=cleanup)
            prior = self._prior(session, identity, inputs)
            if prior is not None:
                return identity, prior
            if row.payload["status"] != "ready" or row.payload.get("active_operation_id"):
                raise _reconcile(
                    "Workspace is busy, destroyed or uncertain; reconcile before dispatch."
                )
            provider = self._providers.get(workspace_id)
            if provider is None:
                raise _reconcile(
                    "Canonical VM exists without a local handle; "
                    "reconcile its identity before reconnecting."
                )
            if provider.execution_id != execution_id:
                raise HarnessError(
                    "WORKSPACE_IDENTITY_MISMATCH",
                    "Attached provider has a different execution identity.",
                )
            self._operation(session, identity, row.payload, command, inputs)
            self.service._replace(session, row, {"active_operation_id": identity})
        return identity, None

    def _artifact(self, session, workspace, data, kind, operation_id):
        digest = self.service.artifacts.put(data)
        # Object storage can outlive the lease while this SQL transaction remains open.
        # Unreferenced content-addressed bytes are harmless; stale canonical issuance is not.
        self._guard(
            session,
            self._workspace(session, workspace["id"]),
            workspace["execution_id"],
        )
        artifact = self.service._insert(
            session,
            "artifact",
            self.actor,
            {
                "experiment_id": workspace["experiment_id"],
                "branch_id": workspace["branch_id"],
                "task_id": self.task_id,
                "artifact_kind": kind,
                "media_type": "application/json",
                "sha256": digest,
                "size_bytes": len(data),
                "submitted_by": self.actor.id,
                "provenance": {
                    "workspace_id": workspace["id"],
                    "execution_id": workspace["execution_id"],
                    "task_id": self.task_id,
                    "holder": self.holder,
                    "fence": self.fence,
                },
            },
        )
        self.service._event(
            session,
            self.actor,
            operation_id,
            "artifact.created",
            artifact["id"],
            {"sha256": digest},
        )
        return artifact

    async def _perform(
        self,
        workspace_id,
        execution_id,
        operation_id,
        command,
        inputs,
        call,
        *,
        archive=False,
        cleanup=False,
        actual=None,
    ):
        identity, prior = self._start(
            workspace_id, execution_id, operation_id, command, inputs, cleanup=cleanup
        )
        if prior is not None:
            return prior
        confirmed = False
        try:
            value = await call(self._providers[workspace_id])
            confirmed = cleanup
            with self.service.db.transaction() as session:
                self._lock(session)
                row = self._workspace(session, workspace_id)
                self._guard(session, row, execution_id, cleanup=cleanup)
                if row.payload["active_operation_id"] != identity:
                    raise _reconcile("Workspace operation ownership changed during provider call.")
                values = {"active_operation_id": None}
                result = value
                if archive:
                    verified = WorkspaceArchive.from_bytes(value.to_bytes(), sha256=value.sha256)
                    artifact = self._artifact(
                        session, row.payload, verified.to_bytes(), "checkpoint", identity
                    )
                    values["checkpoint_artifact_id"] = artifact["id"]
                    result = {
                        "artifact": artifact,
                        "archive_sha256": verified.sha256,
                        "workspace_id": workspace_id,
                        "execution_id": execution_id,
                    }
                if cleanup:
                    reservation = session.scalar(
                        select(ReservationRow)
                        .where(ReservationRow.id == row.payload["reservation_id"])
                        .with_for_update()
                    )
                    if reservation.state == "settled":
                        raise _reconcile(
                            "Reservation unexpectedly settled before confirmed destruction."
                        )
                    budget = session.scalar(
                        select(BudgetRow)
                        .where(BudgetRow.experiment_id == reservation.experiment_id)
                        .with_for_update()
                    )
                    released_workers = reservation.workers
                    budget.active_workers -= reservation.workers
                    if actual is None:
                        reservation.workers = 0
                        reservation.state = "uncertain"
                    else:
                        budget.reserved -= reservation.reserved
                        budget.spent += actual
                        reservation.actual, reservation.tokens_actual = actual, 0
                        reservation.state = "settled"
                    values.update(
                        status="destroyed",
                        destruction_confirmed=True,
                        actual_cost_usd=money_string(actual) if actual is not None else None,
                        billing_status="unreconciled" if actual is None else "reconciled",
                    )
                    result = self.service._replace(session, row, values)
                    self.service._event(
                        session,
                        self.actor,
                        identity,
                        "resources.capacity_released" if actual is None else "resources.settled",
                        reservation.experiment_id,
                        {
                            "reservation_id": reservation.id,
                            "workspace_id": workspace_id,
                            "actual_cost_usd": money_string(actual) if actual is not None else None,
                            "released_workers": released_workers,
                            "billing_status": values["billing_status"],
                        },
                    )
                else:
                    self.service._replace(session, row, values)
                op = self.service._get(session, "workspace_operation", identity, self.actor)
                self.service._replace(session, op, {"status": "completed", "result": result})
                self.service._event(
                    session,
                    self.actor,
                    identity,
                    "workspace.operation.completed",
                    workspace_id,
                    {"command": command},
                )
            return result
        except BaseException as exc:
            if isinstance(exc, ExecutionError) and exc.code == "WORKSPACE_TRANSFER_REJECTED":
                try:
                    with self.service.db.transaction() as session:
                        self._lock(session)
                        row = self._workspace(session, workspace_id)
                        self._guard(session, row, execution_id)
                        if row.payload.get("active_operation_id") != identity:
                            raise _reconcile("Workspace ownership changed after helper refusal.")
                        op = self.service._get(session, "workspace_operation", identity, self.actor)
                        failure = {
                            "code": exc.code,
                            "message": "Workspace helper refused the operation; VM is available.",
                        }
                        self.service._replace(
                            session, op, {"status": "rejected", "result": failure}
                        )
                        self.service._replace(session, row, {"active_operation_id": None})
                        self.service._event(
                            session,
                            self.actor,
                            identity,
                            "workspace.operation.rejected",
                            workspace_id,
                            {"code": exc.code, "command": command},
                        )
                except Exception:
                    self._uncertain(workspace_id, identity, observed_execution_id=execution_id)
                    raise _reconcile() from exc
                raise HarnessError(
                    failure["code"], failure["message"], operation_id=identity
                ) from exc
            observation = getattr(
                self._providers.get(workspace_id), "last_execution_observation", None
            )
            confirmed = confirmed or bool(
                isinstance(observation, dict)
                and observation.get("execution_id") == execution_id
                and observation.get("destruction_confirmed") is True
            )
            if confirmed:
                try:
                    with self.service.db.transaction() as session:
                        self._lock(session)
                        row = self._workspace(session, workspace_id)
                        self._guard(session, row, execution_id, cleanup=True)
                        reservation = session.scalar(
                            select(ReservationRow)
                            .where(ReservationRow.id == row.payload["reservation_id"])
                            .with_for_update()
                        )
                        budget = session.scalar(
                            select(BudgetRow)
                            .where(BudgetRow.experiment_id == reservation.experiment_id)
                            .with_for_update()
                        )
                        released_workers = reservation.workers
                        if reservation.state != "settled":
                            budget.active_workers -= reservation.workers
                            reservation.workers = 0
                            reservation.state = "uncertain"
                        self.service._replace(
                            session,
                            row,
                            {
                                "status": "destroyed",
                                "destruction_confirmed": True,
                                "billing_status": "unreconciled",
                                "active_operation_id": None,
                            },
                        )
                        op = self.service._get(session, "workspace_operation", identity, self.actor)
                        self.service._replace(
                            session,
                            op,
                            {
                                "status": "failed",
                                "result": {
                                    "code": "WORKSPACE_COMMAND_FAILED",
                                    "message": (
                                        "Command failed; VM destruction confirmed, "
                                        "billing unresolved."
                                    ),
                                },
                            },
                        )
                        self.service._event(
                            session,
                            self.actor,
                            identity,
                            "workspace.destroyed_after_failure",
                            workspace_id,
                            {
                                "execution_id": execution_id,
                                "released_workers": released_workers,
                                "billing_status": "unreconciled",
                            },
                        )
                except Exception:
                    self._uncertain(
                        workspace_id,
                        identity,
                        observed_execution_id=execution_id,
                        destruction_confirmed=True,
                    )
                    raise _reconcile() from exc
                raise HarnessError(
                    "WORKSPACE_COMMAND_FAILED",
                    "Command failed; VM destruction confirmed, billing remains unresolved.",
                    operation_id=identity,
                ) from exc
            self._uncertain(
                workspace_id,
                identity,
                observed_execution_id=execution_id,
                destruction_confirmed=confirmed,
            )
            raise _reconcile(
                "VM operation requires reconciliation; reservation remains held."
            ) from exc

    async def run(
        self, workspace_id: str, *, expected_execution_id: str, request: CommandRequest
    ) -> dict:
        async def call(provider):
            result = await provider.run(request)
            checked = CommandResult.model_validate(result)
            if (
                checked.execution_id != expected_execution_id
                or checked.operation_id != request.operation_id
            ):
                raise HarnessError(
                    "WORKSPACE_IDENTITY_MISMATCH", "VM result identity differs from dispatch."
                )
            return checked.model_dump(mode="json")

        return await self._perform(
            workspace_id,
            expected_execution_id,
            request.operation_id,
            "run",
            request.model_dump(mode="json"),
            call,
        )

    async def upload_file(
        self,
        workspace_id: str,
        *,
        expected_execution_id: str,
        path: str,
        data: bytes,
        operation_id: str,
    ) -> dict:
        validated = WorkspaceArchive.build({path: data})

        async def call(provider):
            digest = await provider.upload_file(
                path, data, expected_execution_id=expected_execution_id
            )
            if digest != validated.sha256:
                raise HarnessError(
                    "WORKSPACE_INTEGRITY_MISMATCH", "Upload receipt hash differs from content."
                )
            return {
                "workspace_id": workspace_id,
                "execution_id": expected_execution_id,
                "path": path,
                "archive_sha256": digest,
            }

        return await self._perform(
            workspace_id,
            expected_execution_id,
            operation_id,
            "upload",
            {"path": path, "sha256": hashlib.sha256(data).hexdigest()},
            call,
        )

    async def export_workspace(
        self, workspace_id: str, *, expected_execution_id: str, operation_id: str
    ) -> dict:
        return await self._perform(
            workspace_id,
            expected_execution_id,
            operation_id,
            "export",
            {},
            lambda provider: provider.export_workspace(expected_execution_id=expected_execution_id),
            archive=True,
        )

    async def destroy(
        self,
        workspace_id: str,
        *,
        expected_execution_id: str,
        operation_id: str,
        actual_cost_usd: str | None,
    ) -> dict:
        require_role(self.actor, "operator")
        actual = money_units(actual_cost_usd) if actual_cost_usd is not None else None
        return await self._perform(
            workspace_id,
            expected_execution_id,
            operation_id,
            "destroy",
            {"actual_cost_units": actual},
            lambda provider: provider.close(),
            cleanup=True,
            actual=actual,
        )
