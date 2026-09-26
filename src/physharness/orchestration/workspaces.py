"""Fenced, budgeted VM lifecycle using the canonical database and artifact store.

No provider I/O occurs inside a database transaction. Durable pending records
prevent repeated dispatch; the provider cannot enforce SQL fences itself, so a
fence lost during a call produces a reconciliation record, never success.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import inspect
import math
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from ..domain import Principal, canonical_json, digest_json, new_id, utcnow
from ..errors import HarnessError
from ..execution.e2b import WorkspaceArchive as LegacyWorkspaceArchive
from ..execution.types import CommandRequest, CommandResult, ExecutionError
from ..execution.workspace_archive import StreamedWorkspaceArchive, WorkspaceArchive, checked_path
from ..service import HarnessService, money_string, money_units, require_role
from ..storage import BudgetRow, RecordRow, ReservationRow

_MIN_LOCAL_WORKSPACE_SECONDS = 30
_LOCAL_DEADLINE_MARGIN_SECONDS = 2
_PROMOTION_MAX_BYTES = 4_000_000
_PURE_REQUEST_REJECTIONS = frozenset(
    {"UNSAFE_PATH", "WORKSPACE_EXCLUDED", "WORKSPACE_LIMIT", "UNSAFE_RUNTIME", "TIMEOUT_LIMIT"}
)
_READ_ONLY_COMMANDS = frozenset({"download", "read_range", "export"})


def _definite_refusal(provider: str, command: str, exc: BaseException) -> bool:
    """Provider failures proven to leave the VM unchanged, so it stays usable."""
    if not isinstance(exc, ExecutionError):
        return False
    if command in _READ_ONLY_COMMANDS:
        # A helper refusal or a complete over-limit response cannot have written files.
        return exc.code in {"WORKSPACE_TRANSFER_REJECTED", "WORKSPACE_LIMIT"}
    # A nonzero E2B helper exit may follow a partial write, so uploads stay uncertain
    # there; the local helper reports a write refusal only after undoing its effects.
    return exc.code == "WORKSPACE_TRANSFER_REJECTED" and (
        command == "promote_file" or (command == "upload" and provider == "local_docker")
    )


def _identifier(*parts: str) -> str:
    return str(uuid5(NAMESPACE_URL, digest_json(parts)))


def _reconcile(message: str = "VM outcome requires operator reconciliation.") -> HarnessError:
    return HarnessError(
        "WORKSPACE_RECONCILIATION_REQUIRED",
        message,
        remediation="Reconcile recorded VM identity and provider charges; "
        "do not retry allocation or release its reservation automatically.",
    )


def _validate_file_request(provider, path: str) -> None:
    """Use the attached provider's pure file rules before any durable operation."""
    validate = getattr(provider, "validate_workspace_path", None)
    if validate is not None:
        validate(path)
    else:
        checked_path(path)


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
            or provider_spec["provider"] not in {"e2b", "local_docker"}
            or not isinstance(provider_spec["template_id"], str)
            or not provider_spec["template_id"].strip()
            or provider_spec["template_id"] != provider_spec["template_id"].strip()
            or isinstance(provider_spec["timeout_seconds"], bool)
            or not isinstance(provider_spec["timeout_seconds"], int)
            or provider_spec["timeout_seconds"] <= 0
        ):
            raise HarnessError(
                "INVALID_PROVIDER_SPEC",
                "Supply exact provider image/template ID and positive timeout; no credentials.",
                status=422,
            )
        if provider_spec["provider"] == "local_docker":
            try:
                inspect.signature(provider_factory).bind(
                    journal=None, timeout_seconds=provider_spec["timeout_seconds"]
                )
            except (TypeError, ValueError) as exc:
                raise HarnessError(
                    "PROVIDER_POLICY_MISMATCH",
                    "Local provider factory must accept an effective timeout.",
                    status=422,
                ) from exc
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
        if amount < 0 or (amount == 0 and self.provider_spec["provider"] != "local_docker"):
            raise HarnessError(
                "VM_COST_BOUND_REQUIRED",
                "Supply a positive provider cost bound, except documented local zero charge.",
                status=422,
            )
        identity = self._operation_id("provision", operation_id)
        inputs = {"cost_bound_units": amount, "task_id": self.task_id}
        effective_spec = copy.deepcopy(self.provider_spec)
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
            if self.provider_spec["provider"] == "local_docker":
                effective_spec["timeout_seconds"] = min(
                    self.provider_spec["timeout_seconds"],
                    math.floor(remaining) - _LOCAL_DEADLINE_MARGIN_SECONDS,
                )
                if effective_spec["timeout_seconds"] < _MIN_LOCAL_WORKSPACE_SECONDS:
                    raise HarnessError(
                        "EXPERIMENT_DEADLINE",
                        "Insufficient experiment time remains for a local workbench.",
                    )
            elif self.provider_spec["timeout_seconds"] > remaining:
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
                    "effective_provider_spec": effective_spec,
                    "effective_timeout_seconds": effective_spec["timeout_seconds"],
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
            factory_args = {"journal": CanonicalWorkspaceJournal(self, workspace["id"])}
            if self.provider_spec["provider"] == "local_docker":
                factory_args["timeout_seconds"] = effective_spec["timeout_seconds"]
            provider = self.provider_factory(**factory_args)
            if (
                provider.template_id != self.provider_spec["template_id"]
                or provider.timeout_seconds != effective_spec["timeout_seconds"]
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
        except asyncio.CancelledError as exc:
            self._observe_cancellation(workspace["id"], identity, exc, provider=provider)
            raise
        except BaseException as exc:
            if (
                self.provider_spec["provider"] == "local_docker"
                and isinstance(exc, ExecutionError)
                and exc.code == "WORKSPACE_CAPACITY"
                and provider is not None
                and getattr(provider, "_container_id", None) is None
                and not getattr(provider, "_quarantined", True)
            ):
                with self.service.db.transaction() as session:
                    self._lock(session)
                    self._guard(session)
                    row = self._workspace(session, workspace["id"])
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
                    budget.active_workers -= reservation.workers
                    budget.reserved -= reservation.reserved
                    reservation.workers = 0
                    reservation.actual = 0
                    reservation.state = "settled"
                    self.service._replace(
                        session,
                        row,
                        {
                            "status": "destroyed",
                            "destruction_confirmed": True,
                            "active_operation_id": None,
                            "billing_status": "reconciled",
                        },
                    )
                    op = self.service._get(session, "workspace_operation", identity, self.actor)
                    self.service._replace(
                        session,
                        op,
                        {
                            "status": "rejected",
                            "result": {"code": "WORKSPACE_CAPACITY"},
                        },
                    )
                    self.service._event(
                        session,
                        self.actor,
                        identity,
                        "workspace.provision.rejected",
                        workspace["id"],
                        {"code": "WORKSPACE_CAPACITY"},
                    )
                raise HarnessError(
                    "WORKSPACE_CAPACITY", "Dedicated workbench capacity is occupied."
                ) from exc
            self._uncertain(workspace["id"], identity, observed_execution_id=observed)
            raise _reconcile(
                "VM provision outcome requires reconciliation; reservation remains held."
            ) from exc

    def _observe_cancellation(
        self, workspace_id, operation_id, cancellation, *, provider, execution_id=None
    ):
        # Record observation only; cancellation never grants settlement or reuse authority.
        if execution_id is None and provider is not None:
            try:
                execution_id = provider.execution_id
            except Exception:
                pass
        observation = getattr(provider, "last_execution_observation", None)
        if execution_id is None and isinstance(observation, dict):
            recorded_id = observation.get("execution_id")
            if isinstance(recorded_id, str) and recorded_id:
                execution_id = recorded_id
        confirmed = bool(
            isinstance(observation, dict)
            and execution_id is not None
            and observation.get("execution_id") == execution_id
            and observation.get("destruction_confirmed") is True
        )
        try:
            self._uncertain(
                workspace_id,
                operation_id,
                observed_execution_id=execution_id,
                destruction_confirmed=confirmed,
            )
        except Exception as exc:
            # _uncertain retains the in-memory evidence even if persistence fails.
            cancellation.add_note(str(exc))

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

    def _start(
        self,
        workspace_id,
        execution_id,
        operation_id,
        command,
        inputs,
        *,
        cleanup=False,
        predispatch_validate=None,
    ):
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
            if predispatch_validate is not None:
                # Pure request validation must precede the durable pending marker.
                # Provider calls and uncertain outcomes remain outside this transaction.
                try:
                    predispatch_validate(provider)
                except ExecutionError as error:
                    if error.code not in _PURE_REQUEST_REJECTIONS:
                        raise
                    raise HarnessError(
                        error.code,
                        str(error),
                        operation_id=identity,
                    ) from error
            self._operation(session, identity, row.payload, command, inputs)
            self.service._replace(session, row, {"active_operation_id": identity})
        return identity, None

    def _artifact(self, session, workspace, data, kind, operation_id, *, dependencies=None):
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
                "media_type": (
                    "application/octet-stream"
                    if kind == "checkpoint_chunk"
                    else "text/plain; charset=utf-8"
                    if kind == "lean_source"
                    else "application/json"
                ),
                "sha256": digest,
                "size_bytes": len(data),
                "submitted_by": self.actor.id,
                "provenance": {
                    "workspace_id": workspace["id"],
                    "execution_id": workspace["execution_id"],
                    "task_id": self.task_id,
                    "holder": self.holder,
                    "fence": self.fence,
                    **({"chunk_artifact_ids": dependencies} if dependencies is not None else {}),
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
        predispatch_validate=None,
        promoted_target_digest=None,
    ):
        identity, prior = self._start(
            workspace_id,
            execution_id,
            operation_id,
            command,
            inputs,
            cleanup=cleanup,
            predispatch_validate=predispatch_validate,
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
                if promoted_target_digest is not None:
                    experiment = self.service._get(
                        session, "experiment", row.payload["experiment_id"], self.actor
                    )
                    problem = self.service._get(
                        session, "problem", experiment.payload["problem_id"], self.actor
                    )
                    if (
                        experiment.payload["target_digest"] != promoted_target_digest
                        or problem.payload["target_digest"] != promoted_target_digest
                    ):
                        raise ExecutionError(
                            "WORKSPACE_TRANSFER_REJECTED", "Current target changed during capture"
                        )
                    artifact = self._artifact(session, row.payload, value, "lean_source", identity)
                    result = {
                        "artifact_id": artifact["id"],
                        "sha256": artifact["sha256"],
                        "size_bytes": artifact["size_bytes"],
                        "branch_id": artifact["branch_id"],
                        "task_id": self.task_id,
                        "target_digest": promoted_target_digest,
                        "proof_status": "not_accepted",
                    }
                if archive:
                    if isinstance(value, StreamedWorkspaceArchive):
                        verified = StreamedWorkspaceArchive.from_bytes(
                            value.data, sha256=value.sha256
                        )
                    else:
                        verified = WorkspaceArchive.from_bytes(
                            value.to_bytes(), sha256=value.sha256
                        )
                    artifact = self._artifact(
                        session,
                        row.payload,
                        verified.data
                        if isinstance(verified, StreamedWorkspaceArchive)
                        else verified.to_bytes(),
                        "checkpoint",
                        identity,
                        dependencies=(
                            verified.chunk_artifact_ids
                            if isinstance(verified, StreamedWorkspaceArchive)
                            else None
                        ),
                    )
                    values["checkpoint_artifact_id"] = artifact["id"]
                    result = {
                        "artifact": artifact,
                        "archive_sha256": verified.sha256,
                        "workspace_id": workspace_id,
                        "execution_id": execution_id,
                    }
                if command == "restore":
                    values.update(
                        restored_from_artifact_id=result["artifact_id"],
                        restored_from_sha256=result["archive_sha256"],
                        restored_from_execution_id=result["source_execution_id"],
                    )
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
        except asyncio.CancelledError as exc:
            self._observe_cancellation(
                workspace_id,
                identity,
                exc,
                provider=self._providers.get(workspace_id),
                execution_id=execution_id,
            )
            raise
        except BaseException as exc:
            if _definite_refusal(self.provider_spec["provider"], command, exc):
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
                            "message": (
                                "Workspace helper refused the operation; VM is available."
                                if exc.code == "WORKSPACE_TRANSFER_REJECTED"
                                else f"{exc}; VM is available."
                            ),
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
                            if self.provider_spec["provider"] == "local_docker":
                                budget.reserved -= reservation.reserved
                                reservation.actual = 0
                                reservation.state = "settled"
                            else:
                                reservation.state = "uncertain"
                        local = self.provider_spec["provider"] == "local_docker"
                        self.service._replace(
                            session,
                            row,
                            {
                                "status": "destroyed",
                                "destruction_confirmed": True,
                                "billing_status": "reconciled" if local else "unreconciled",
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
                                    "message": ("Command failed; VM destruction confirmed."),
                                    "diagnostics": getattr(
                                        self._providers.get(workspace_id),
                                        "last_command_diagnostics",
                                        None,
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
                                "billing_status": "reconciled" if local else "unreconciled",
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
                    "Command failed; VM destruction confirmed. Inspect operation diagnostics.",
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
        def predispatch_validate(provider):
            validate = getattr(provider, "validate_command", None)
            if validate is not None:
                validate(request)

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
            outcome = checked.model_dump(mode="json")
            diagnostics = getattr(provider, "last_command_diagnostics", None)
            if diagnostics is not None:
                outcome["diagnostics"] = copy.deepcopy(diagnostics)
            return outcome

        return await self._perform(
            workspace_id,
            expected_execution_id,
            request.operation_id,
            "run",
            request.model_dump(mode="json"),
            call,
            predispatch_validate=predispatch_validate,
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
        archive_type = (
            LegacyWorkspaceArchive if self.provider_spec["provider"] == "e2b" else WorkspaceArchive
        )
        validated = None

        def predispatch_validate(provider):
            nonlocal validated
            _validate_file_request(provider, path)
            quota = getattr(provider, "workspace_quota_bytes", None)
            validated = archive_type.build(
                {path: data}, **({"quota_bytes": quota} if quota is not None else {})
            )

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
            predispatch_validate=predispatch_validate,
        )

    async def promote_file(
        self,
        workspace_id: str,
        *,
        expected_execution_id: str,
        path: str,
        expected_sha256: str,
        expected_target_digest: str,
        operation_id: str,
    ) -> dict:
        """Capture exact bounded source under the live workspace lease, without model echo."""
        if not isinstance(expected_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_sha256
        ):
            raise HarnessError("INVALID_DIGEST", "An exact SHA-256 digest is required.", status=422)
        if not isinstance(expected_target_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_target_digest
        ):
            raise HarnessError(
                "INVALID_TARGET_DIGEST", "An exact target digest is required.", status=422
            )
        current_workspace = self.inspect(workspace_id)
        current_experiment = self.service.get_record(
            "experiment", current_workspace["experiment_id"], self.actor
        )
        current_problem = self.service.get_record(
            "problem", current_experiment["problem_id"], self.actor
        )
        if (
            current_experiment["target_digest"] != expected_target_digest
            or current_problem["target_digest"] != expected_target_digest
        ):
            raise HarnessError(
                "TARGET_CHANGED", "Current reviewed target differs from capture request."
            )
        provider = self._providers.get(workspace_id)
        if provider is not None:
            try:
                _validate_file_request(provider, path)
            except ExecutionError as error:
                # Pure path rules are model-visible tool rejections, as for other file tools.
                if error.code not in _PURE_REQUEST_REJECTIONS:
                    raise
                raise HarnessError(error.code, str(error)) from error
            if not callable(getattr(provider, "capture_file", None)):
                raise HarnessError(
                    "CAPABILITY_UNAVAILABLE", "Provider lacks bounded safe file capture."
                )

        async def call(provider):
            data = await provider.capture_file(
                path,
                expected_execution_id=expected_execution_id,
                max_bytes=_PROMOTION_MAX_BYTES,
            )
            if not isinstance(data, bytes) or not 1 <= len(data) <= _PROMOTION_MAX_BYTES:
                raise ExecutionError(
                    "WORKSPACE_TRANSFER_REJECTED", "Capture size is invalid or exceeds limit"
                )
            if hashlib.sha256(data).hexdigest() != expected_sha256:
                raise ExecutionError("WORKSPACE_TRANSFER_REJECTED", "Captured file hash changed")
            try:
                source = data.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ExecutionError(
                    "WORKSPACE_TRANSFER_REJECTED", "Lean source must be valid UTF-8"
                ) from error
            try:
                self.service._check_candidate_size(source)
            except HarnessError as error:
                if error.code != "CANDIDATE_TOO_LARGE":
                    raise
                raise ExecutionError("WORKSPACE_TRANSFER_REJECTED", str(error)) from error
            return data

        return await self._perform(
            workspace_id,
            expected_execution_id,
            operation_id,
            "promote_file",
            {
                "path": path,
                "expected_sha256": expected_sha256,
                "expected_target_digest": expected_target_digest,
            },
            call,
            predispatch_validate=lambda provider: _validate_file_request(provider, path),
            promoted_target_digest=expected_target_digest,
        )

    async def download_file(
        self, workspace_id: str, *, expected_execution_id: str, path: str, operation_id: str
    ) -> dict:
        async def call(provider):
            data = await provider.download_file(path, expected_execution_id=expected_execution_id)
            return {
                "workspace_id": workspace_id,
                "execution_id": expected_execution_id,
                "path": path,
                "content_sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
                "content_base64": base64.b64encode(data).decode(),
            }

        return await self._perform(
            workspace_id,
            expected_execution_id,
            operation_id,
            "download",
            {"path": path},
            call,
            predispatch_validate=lambda provider: _validate_file_request(provider, path),
        )

    async def read_workspace_range(
        self,
        workspace_id: str,
        *,
        expected_execution_id: str,
        path: str,
        offset: int,
        length: int,
        operation_id: str,
    ) -> dict:
        async def call(provider):
            if not callable(getattr(provider, "read_range", None)):
                data = await provider.download_file(
                    path, expected_execution_id=expected_execution_id
                )
                return {
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                    "data": base64.b64encode(data[offset : offset + length]).decode(),
                }
            return await provider.read_range(
                path,
                offset=offset,
                length=length,
                expected_execution_id=expected_execution_id,
            )

        def predispatch_validate(provider):
            _validate_file_request(provider, path)
            if (
                type(offset) is not int
                or offset < 0
                or type(length) is not int
                or not 1 <= length <= 65536
            ):
                raise ExecutionError("WORKSPACE_LIMIT", "Read range must be at most 65536 bytes")

        return await self._perform(
            workspace_id,
            expected_execution_id,
            operation_id,
            "read_range",
            {"path": path, "offset": offset, "length": length},
            call,
            predispatch_validate=predispatch_validate,
        )

    async def export_workspace(
        self, workspace_id: str, *, expected_execution_id: str, operation_id: str
    ) -> dict:
        async def call(provider):
            if self.provider_spec["provider"] != "local_docker":
                return await provider.export_workspace(expected_execution_id=expected_execution_id)
            identity = self._operation_id(workspace_id, operation_id)

            async def accept_chunk(piece: bytes, digest: str) -> str:
                if len(piece) > 1024 * 1024 or hashlib.sha256(piece).hexdigest() != digest:
                    raise HarnessError("CHECKPOINT_MISMATCH", "Invalid streamed checkpoint chunk.")
                with self.service.db.transaction() as session:
                    self._lock(session)
                    row = self._workspace(session, workspace_id)
                    self._guard(session, row, expected_execution_id)
                    if row.payload.get("active_operation_id") != identity:
                        raise _reconcile("Workspace checkpoint operation ownership changed.")
                    return self._artifact(
                        session, row.payload, piece, "checkpoint_chunk", identity
                    )["id"]

            files, chunks, exclusions = await provider.export_workspace_stream(
                expected_execution_id=expected_execution_id, accept_chunk=accept_chunk
            )
            return StreamedWorkspaceArchive.build(
                files,
                chunks,
                excluded_paths=exclusions,
                quota_bytes=provider.workspace_quota_bytes,
            )

        return await self._perform(
            workspace_id,
            expected_execution_id,
            operation_id,
            "export",
            {},
            call,
            archive=True,
        )

    def load_handoff_archive(
        self, artifact_id: str, archive_sha256: str, source_execution_id: str
    ) -> WorkspaceArchive | StreamedWorkspaceArchive:
        """Validate the artifact's exact task and source VM before allocation."""
        task = self.service.get_record("task", self.task_id, self.actor)
        artifact = self.service.get_record("artifact", artifact_id, self.actor)
        provenance = artifact.get("provenance") or {}
        if (
            artifact.get("artifact_kind") != "checkpoint"
            or artifact.get("experiment_id") != task["experiment_id"]
            or artifact.get("branch_id") != task["branch_id"]
            or artifact.get("task_id") != self.task_id
            or artifact.get("sha256") != archive_sha256
            or provenance.get("task_id") != self.task_id
            or provenance.get("execution_id") != source_execution_id
        ):
            raise HarnessError(
                "WORKSPACE_HANDOFF_MISMATCH", "Workspace archive scope or source differs."
            )
        data = self.service.artifact_content(artifact_id, self.actor)
        if data.startswith(b'{"chunks":'):
            archive = StreamedWorkspaceArchive.from_bytes(data, sha256=archive_sha256)
            if provenance.get("chunk_artifact_ids") != archive.chunk_artifact_ids:
                raise HarnessError("WORKSPACE_HANDOFF_MISMATCH", "Checkpoint dependencies differ.")
            for chunk in archive.manifest["chunks"]:
                record = self.service.get_record("artifact", chunk["artifact_id"], self.actor)
                source = record.get("provenance") or {}
                if (
                    record.get("artifact_kind") != "checkpoint_chunk"
                    or record.get("experiment_id") != task["experiment_id"]
                    or record.get("branch_id") != task["branch_id"]
                    or record.get("task_id") != self.task_id
                    or record.get("sha256") != chunk["sha256"]
                    or record.get("size_bytes") != chunk["size"]
                    or source.get("workspace_id") != provenance.get("workspace_id")
                    or source.get("execution_id") != source_execution_id
                ):
                    raise HarnessError(
                        "WORKSPACE_HANDOFF_MISMATCH", "Checkpoint chunk scope differs."
                    )
                content = self.service.artifact_content(chunk["artifact_id"], self.actor)
                if (
                    len(content) != chunk["size"]
                    or hashlib.sha256(content).hexdigest() != chunk["sha256"]
                ):
                    raise HarnessError(
                        "CHECKPOINT_MISMATCH", "Checkpoint chunk integrity mismatch."
                    )
            return archive
        return WorkspaceArchive.from_bytes(data, sha256=archive_sha256)

    async def restore_workspace(
        self,
        workspace_id: str,
        *,
        expected_execution_id: str,
        archive_artifact_id: str,
        archive_sha256: str,
        source_execution_id: str,
        operation_id: str,
    ) -> dict:
        if expected_execution_id == source_execution_id:
            raise HarnessError(
                "WORKSPACE_IDENTITY_MISMATCH", "Successor VM reused the source execution identity."
            )
        archive = self.load_handoff_archive(
            archive_artifact_id, archive_sha256, source_execution_id
        )

        async def call(provider):
            if isinstance(archive, StreamedWorkspaceArchive):
                if not callable(getattr(provider, "restore_workspace_stream", None)):
                    raise HarnessError(
                        "WORKSPACE_RESTORE_INCOMPATIBLE",
                        "Provider cannot restore streamed checkpoint.",
                    )

                async def read_chunk(chunk):
                    content = self.service.artifact_content(chunk["artifact_id"], self.actor)
                    if (
                        len(content) != chunk["size"]
                        or hashlib.sha256(content).hexdigest() != chunk["sha256"]
                    ):
                        raise HarnessError(
                            "CHECKPOINT_MISMATCH", "Checkpoint chunk integrity mismatch."
                        )
                    return content

                await provider.restore_workspace_stream(
                    archive, expected_execution_id=expected_execution_id, read_chunk=read_chunk
                )
            else:
                await provider.restore_workspace(
                    archive, expected_execution_id=expected_execution_id
                )
            return {
                "workspace_id": workspace_id,
                "execution_id": expected_execution_id,
                "artifact_id": archive_artifact_id,
                "archive_sha256": archive_sha256,
                "source_execution_id": source_execution_id,
            }

        return await self._perform(
            workspace_id,
            expected_execution_id,
            operation_id,
            "restore",
            {
                "artifact_id": archive_artifact_id,
                "archive_sha256": archive_sha256,
                "source_execution_id": source_execution_id,
            },
            call,
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
