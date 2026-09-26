"""Fenced, canonical handoffs between settled native research sessions."""

from sqlalchemy import and_, select

from .domain import digest_json, utcnow
from .errors import HarnessError
from .execution.types import ExecutionError
from .execution.workspace_archive import checked_path
from .storage import BudgetRow, EventRow, LeaseRow, RecordRow, ReservationRow, record_json_text
from .worker_authority import current_worker_effects


class ContinuationMixin:
    def _continuation_link(self, session, task_id, ordinal, actor):
        rows = list(
            session.scalars(
                select(RecordRow)
                .where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.kind == "continuation_link",
                    RecordRow.payload["task_id"].as_string() == task_id,
                    RecordRow.payload["ordinal"].as_integer() == ordinal,
                )
                .with_for_update()
            )
        )
        if len(rows) != 1:
            raise HarnessError(
                "CONTINUATION_LINEAGE_MISMATCH", "Exact continuation link is unavailable."
            )
        return rows[0]

    def retire_failed_local_workspace(
        self,
        workspace_id,
        expected_revision,
        expected_execution_id,
        evidence_artifact_id,
        actor,
        key,
    ):
        """Record an operator-attested local VM retirement after external destruction.

        This path is deliberately unavailable to model-bound worker effects. The
        evidence is an operator observation, not independent proof of destruction.
        """
        if (
            actor.role not in {"operator", "admin"}
            or actor.experiment_id is not None
            or actor.branch_id is not None
            or current_worker_effects.get() is not None
        ):
            raise HarnessError("FORBIDDEN", "Unbound controller authority is required.", status=403)
        if type(expected_revision) is not int or expected_revision < 1:
            raise HarnessError("REVISION_CONFLICT", "Exact workspace revision required.")
        if not isinstance(expected_execution_id, str) or not expected_execution_id:
            raise HarnessError("WORKSPACE_IDENTITY_MISMATCH", "Exact execution identity required.")

        def action(session, op):
            workspace = self._get(session, "workspace", workspace_id, actor)
            task_id_before_lock = workspace.payload["task_id"]
            self.db.command_lock(session, digest_json(["workspace-task", task_id_before_lock]))
            session.refresh(workspace, with_for_update=True)
            data = workspace.payload
            if data.get("task_id") != task_id_before_lock:
                raise HarnessError("RECOVERY_SCOPE", "Workspace task binding changed.")
            if workspace.revision != expected_revision:
                raise HarnessError("REVISION_CONFLICT", "Workspace changed since observation.")
            if data.get("execution_id") != expected_execution_id:
                raise HarnessError("WORKSPACE_IDENTITY_MISMATCH", "Execution identity changed.")
            if (data.get("provider_spec") or {}).get("provider") != "local_docker":
                raise HarnessError("RECOVERY_SCOPE", "Only zero-charge local workspaces qualify.")
            if (
                data.get("status") != "reconciliation_required"
                or data.get("destruction_confirmed") is True
                or not data.get("active_operation_id")
                or data.get("cost_bound_usd") not in {"0", "0.0", "0.000000"}
            ):
                raise HarnessError("RECOVERY_SCOPE", "Workspace is outside failed local recovery.")
            task = self._get(session, "task", data["task_id"], actor)
            session.refresh(task, with_for_update=True)
            experiment = self._get(session, "experiment", data["experiment_id"], actor)
            session.refresh(experiment, with_for_update=True)
            if experiment.payload.get("status") not in {"paused", "cancelled"}:
                raise HarnessError(
                    "RECOVERY_SCOPE", "Pause or cancel the attempt before retirement."
                )
            # A worker that lost its lease cannot mark the task terminal, so a running
            # task qualifies as an abandoned attempt only when the original lease checked
            # below has expired; no worker can commit under it again.
            if task.payload.get("status") not in {"blocked", "failed", "running"}:
                raise HarnessError("RECOVERY_SCOPE", "Only failed or abandoned attempts qualify.")
            if (
                task.payload.get("experiment_id") != data["experiment_id"]
                or task.payload.get("branch_id") != data["branch_id"]
                or task.payload.get("holder") != data["holder"]
                or task.payload.get("fence") != data["fence"]
                or task.payload.get("worker_slot_id") != data.get("shared_worker_slot_id")
            ):
                raise HarnessError("RECOVERY_SCOPE", "Original task binding changed.")
            lease = session.get(LeaseRow, task.id)
            if lease is not None:
                session.refresh(lease, with_for_update=True)
            if (
                lease is None
                or lease.holder != data["holder"]
                or lease.fence != data["fence"]
                or lease.expires_at > utcnow().timestamp()
            ):
                raise HarnessError("LEASE_HELD", "Original task lease is live or replaced.")
            if self._pending_task_model_reservation(session, task.id, actor):
                raise HarnessError("RECOVERY_RECONCILIATION_REQUIRED", "Model usage remains open.")
            model_bindings = session.scalars(
                select(RecordRow).where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.kind == "model_reservation",
                    RecordRow.payload["task_id"].as_string() == task.id,
                )
            )
            for binding in model_bindings:
                model_charge = session.get(ReservationRow, binding.payload["reservation_id"])
                if (
                    model_charge is None
                    or model_charge.experiment_id != experiment.id
                    or model_charge.state != "settled"
                ):
                    raise HarnessError(
                        "RECOVERY_RECONCILIATION_REQUIRED", "Model charge remains open."
                    )
            evidence = self._get(session, "artifact", evidence_artifact_id, actor).payload
            provenance = evidence.get("provenance") or {}
            archive_hash = provenance.get("archive_sha256")
            if (
                evidence.get("artifact_kind") != "workspace_recovery_observation"
                or evidence.get("experiment_id") != data["experiment_id"]
                or evidence.get("branch_id") is not None
                or evidence.get("task_id") is not None
                or evidence.get("submitted_by") != actor.id
                or evidence.get("trusted_input") is True
                or provenance.get("workspace_id") != workspace_id
                or provenance.get("task_id") is not None
                or provenance.get("execution_id") != expected_execution_id
                or provenance.get("destruction_confirmed") is not True
                or provenance.get("absence_confirmed") is not True
                or not isinstance(archive_hash, str)
                or len(archive_hash) != 64
                or any(c not in "0123456789abcdef" for c in archive_hash)
            ):
                raise HarnessError(
                    "RECOVERY_EVIDENCE_INVALID", "Operator observation is out of scope."
                )
            operation = self._get(
                session, "workspace_operation", data["active_operation_id"], actor
            )
            if (
                operation.payload.get("workspace_id") != workspace_id
                or operation.payload.get("task_id") != task.id
                or operation.payload.get("status") != "reconciliation_required"
                or operation.payload.get("command") not in {"run", "export", "read_range"}
            ):
                raise HarnessError("RECOVERY_SCOPE", "Uncertain operation binding changed.")
            if operation.payload["command"] == "read_range":
                inputs = operation.payload.get("inputs") or {}
                path = inputs.get("path")
                if (
                    operation.payload.get("experiment_id") != experiment.id
                    or operation.payload.get("branch_id") != data["branch_id"]
                    or operation.payload.get("result") is not None
                    or inputs.get("execution_id") != expected_execution_id
                    or inputs.get("command") != "read_range"
                    or not isinstance(path, str)
                    or not path.startswith("/work/")
                    or type(inputs.get("offset")) is not int
                    or inputs["offset"] < 0
                    or type(inputs.get("length")) is not int
                    or not 1 <= inputs["length"] <= 65536
                    or provenance.get("predispatch_rejected_path") != path
                ):
                    raise HarnessError("RECOVERY_SCOPE", "Uncertain operation binding changed.")
                try:
                    checked_path(path)
                except ExecutionError as error:
                    if error.code != "UNSAFE_PATH":
                        raise HarnessError(
                            "RECOVERY_SCOPE", "Read path rejection was not a pure unsafe path."
                        ) from error
                else:
                    raise HarnessError(
                        "RECOVERY_SCOPE", "Read path is valid; dispatch outcome is uncertain."
                    )
            slot_id = data.get("shared_worker_slot_id")
            resource_ids = (
                [data["reservation_id"], slot_id] if slot_id else [data["reservation_id"]]
            )
            locked_resources = {
                resource_id: session.scalar(
                    select(ReservationRow).where(ReservationRow.id == resource_id).with_for_update()
                )
                for resource_id in sorted(set(resource_ids))
            }
            reservation = locked_resources[data["reservation_id"]]
            slot = locked_resources.get(slot_id)
            if (
                reservation is None
                or reservation.experiment_id != experiment.id
                or reservation.state not in {"active", "uncertain"}
                or reservation.reserved != 0
                or reservation.workers != 0
                or reservation.tokens_reserved != 0
                or slot is None
                or slot.experiment_id != experiment.id
                or slot.state not in {"active", "uncertain"}
                or slot.reserved != 0
                or slot.workers != 1
                or slot.tokens_reserved != 0
            ):
                raise HarnessError(
                    "RECOVERY_RECONCILIATION_REQUIRED", "Zero-cost resource bindings changed."
                )
            siblings = session.scalars(
                select(RecordRow).where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.kind == "workspace",
                    RecordRow.payload["shared_worker_slot_id"].as_string() == slot_id,
                )
            )
            if any(
                row.id != workspace_id and row.payload.get("status") != "destroyed"
                for row in siblings
            ):
                raise HarnessError(
                    "RECOVERY_RECONCILIATION_REQUIRED", "Another shared VM remains open."
                )
            budget = session.scalar(
                select(BudgetRow).where(BudgetRow.experiment_id == experiment.id).with_for_update()
            )
            if budget is None or budget.active_workers < 1:
                raise HarnessError("RECOVERY_RECONCILIATION_REQUIRED", "Worker capacity changed.")
            reservation.state, reservation.actual, reservation.tokens_actual = "settled", 0, 0
            slot.state, slot.actual, slot.tokens_actual = "settled", 0, 0
            budget.active_workers -= 1
            self._replace(
                session,
                operation,
                {
                    "status": "failed",
                    "result": {
                        "code": "WORKSPACE_OPERATOR_RETIRED",
                        "message": "Operator-attested retirement after uncertain command.",
                        "evidence_artifact_id": evidence_artifact_id,
                    },
                },
            )
            self._replace(
                session,
                workspace,
                {
                    "status": "destroyed",
                    "destruction_confirmed": True,
                    "destruction_evidence_artifact_id": evidence_artifact_id,
                    "active_operation_id": None,
                    "billing_status": "reconciled",
                    "actual_cost_usd": "0.000000",
                },
            )
            sessions = list(
                session.scalars(
                    select(RecordRow).where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "session",
                        RecordRow.payload["task_id"].as_string() == task.id,
                    )
                )
            )
            if any(
                native.payload.get("status") not in {"handed_off", "running", "completed", "failed"}
                for native in sessions
            ):
                raise HarnessError(
                    "RECOVERY_RECONCILIATION_REQUIRED", "A native session has unexpected status."
                )
            failed_sessions = []
            for native in sessions:
                if native.payload.get("status") in {"handed_off", "running"}:
                    self._replace(
                        session,
                        native,
                        {
                            "status": "failed",
                            "recovery_evidence_artifact_id": evidence_artifact_id,
                            "error_code": "WORKSPACE_RECOVERY_ABORTED",
                        },
                    )
                    failed_sessions.append(native.id)
            self._replace(
                session,
                task,
                {
                    "status": "failed",
                    "execution_status": "failed",
                    "error_code": "WORKSPACE_RECOVERY_ABORTED",
                    "recovery_evidence_artifact_id": evidence_artifact_id,
                },
            )
            for resource_id in (reservation.id, slot.id):
                self._event(
                    session,
                    actor,
                    op,
                    "resources.settled",
                    experiment.id,
                    {
                        "id": resource_id,
                        "state": "settled",
                        "actual_cost_usd": "0.000000",
                        "recovery_evidence_artifact_id": evidence_artifact_id,
                    },
                )
            self._event(
                session,
                actor,
                op,
                "workspace.operator_retired",
                workspace_id,
                {
                    "execution_id": expected_execution_id,
                    "evidence_artifact_id": evidence_artifact_id,
                    "archive_sha256": archive_hash,
                    "attestation": "operator",
                    "command": operation.payload["command"],
                    "predispatch_path_rejection": operation.payload["command"] == "read_range",
                },
            )
            self._event(
                session,
                actor,
                op,
                "workspace.operation.failed",
                operation.id,
                {
                    "workspace_id": workspace_id,
                    "evidence_artifact_id": evidence_artifact_id,
                },
            )
            for session_id in failed_sessions:
                self._event(
                    session,
                    actor,
                    op,
                    "session.failed",
                    session_id,
                    {
                        "task_id": task.id,
                        "evidence_artifact_id": evidence_artifact_id,
                    },
                )
            self._event(
                session,
                actor,
                op,
                "task.failed",
                task.id,
                {
                    "experiment_id": experiment.id,
                    "evidence_artifact_id": evidence_artifact_id,
                },
            )
            return {
                "workspace_id": workspace_id,
                "task_id": task.id,
                "operation_id": operation.id,
                "evidence_artifact_id": evidence_artifact_id,
                "settled_reservation_ids": [reservation.id, slot.id],
                "failed_session_ids": failed_sessions,
            }

        return self._execute(
            actor,
            key,
            "workspace.retire-failed-local",
            {
                "workspace_id": workspace_id,
                "expected_revision": expected_revision,
                "expected_execution_id": expected_execution_id,
                "evidence_artifact_id": evidence_artifact_id,
            },
            action,
        )

    def requeue_settled_terminal(self, task_id, holder, fence, actor, key):
        """Retry a failed terminal boundary decision without replaying provider work."""
        if actor.role not in {"operator", "admin"}:
            raise HarnessError("FORBIDDEN", "Controller authority is required.", status=403)

        def action(session, op):
            task = self._get(session, "task", task_id, actor)
            lease = self._fenced(session, task_id, holder, fence)
            if self._pending_task_model_reservation(session, task_id, actor):
                raise HarnessError("RECOVERY_RECONCILIATION_REQUIRED", "Model usage is unresolved.")
            if int(task.payload.get("terminal_recovery_count", 0)) >= 3:
                raise HarnessError("RECOVERY_LIMIT", "Terminal boundary recovery limit reached.")
            slot_id = task.payload.get("worker_slot_id")
            if slot_id:
                workspaces = list(
                    session.scalars(
                        select(RecordRow).where(
                            RecordRow.project_id == actor.project_id,
                            RecordRow.kind == "workspace",
                            RecordRow.payload["shared_worker_slot_id"].as_string() == slot_id,
                        )
                    )
                )
                if any(row.payload.get("status") != "destroyed" for row in workspaces):
                    raise HarnessError(
                        "RECOVERY_RECONCILIATION_REQUIRED", "Source workspace remains active."
                    )
            row = session.scalar(
                select(RecordRow)
                .where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.kind == "session",
                    RecordRow.payload["task_id"].as_string() == task_id,
                )
                .order_by(RecordRow.payload["created_at"].as_string().desc())
                .limit(1)
            )
            if row is None:
                raise HarnessError("RECOVERY_RECONCILIATION_REQUIRED", "No source session exists.")
            checkpoint = self.load_native_checkpoint(row.payload["checkpoint_artifact_id"], actor)
            if (checkpoint.native_state.get("stagnation") or {}).get("exhausted"):
                raise HarnessError(
                    "RESEARCH_STAGNATION_EXHAUSTED",
                    "Recovery did not change research progress.",
                )
            if (
                checkpoint.session.id != row.payload.get("native_record_id")
                or checkpoint.session.status not in {"failed", "interrupted", "running"}
                or checkpoint.native_state.get("terminal_response_pending") is not True
                or checkpoint.native_state.get("settled_boundary") is not True
                or checkpoint.native_state.get("pending_operation")
                or checkpoint.native_state.get("pending_tool_call")
            ):
                raise HarnessError(
                    "RECOVERY_RECONCILIATION_REQUIRED", "Terminal state is not settled."
                )
            self._replace(
                session,
                task,
                {
                    "status": "queued",
                    "holder": None,
                    "terminal_recovery_count": int(task.payload.get("terminal_recovery_count", 0))
                    + 1,
                    "terminal_recovery": {
                        "session_id": checkpoint.session.id,
                        "checkpoint_digest": checkpoint.state_digest,
                    },
                },
            )
            lease.expires_at = 0
            self._event(
                session,
                actor,
                op,
                "task.queued",
                task_id,
                {
                    "experiment_id": task.payload["experiment_id"],
                    "terminal_recovery": checkpoint.state_digest,
                },
                dispatch=True,
            )
            return {
                "task_id": task_id,
                "status": "queued",
                "checkpoint_digest": checkpoint.state_digest,
            }

        return self._execute(
            actor,
            key,
            "task.requeue-settled-terminal",
            {
                "task_id": task_id,
                "holder": holder,
                "fence": fence,
            },
            action,
        )

    def joined_task_statuses(self, task_id, actor):
        """Read direct joined children by canonical lineage, including terminal failures."""
        with self.db.sessions() as session:
            parent = self._get(session, "task", task_id, actor)
            if actor.role == "agent" and parent.payload.get("branch_id") != actor.branch_id:
                raise HarnessError("TASK_SCOPE", "Current branch does not own this task.")
            rows = list(
                session.scalars(
                    select(RecordRow).where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "task",
                        RecordRow.payload["reply_to_parent_task_id"].as_string() == task_id,
                    )
                )
            )
            children = [
                row
                for row in rows
                if row.payload.get("experiment_id") == parent.payload["experiment_id"]
            ]
            return {
                "task_id": task_id,
                "children": [
                    {
                        "task_id": row.id,
                        "status": row.payload["status"],
                        "strategy": row.payload.get("strategy"),
                    }
                    for row in children
                ],
                "pending_ids": [
                    row.id
                    for row in children
                    if row.payload["status"] not in {"completed", "failed", "blocked"}
                ],
            }

    def reconcile_orphan_worker_slot(self, task_id, actor, key):
        """Release an expired source's capacity only after its VM and model effects settle."""
        if actor.role not in {"operator", "admin"}:
            raise HarnessError("FORBIDDEN", "Controller authority is required.", status=403)

        def action(session, op):
            task = self._get(session, "task", task_id, actor)
            self._active(session, task.payload["experiment_id"], actor)
            slot_id = task.payload.get("worker_slot_id")
            if not slot_id:
                return {"task_id": task_id, "released": False}
            lease = session.get(LeaseRow, task_id)
            if (
                lease is None
                or lease.holder != task.payload.get("holder")
                or lease.fence != task.payload.get("fence")
                or lease.expires_at > utcnow().timestamp()
            ):
                raise HarnessError("LEASE_HELD", "Source lease has not expired.")
            slot = session.scalar(
                select(ReservationRow).where(ReservationRow.id == slot_id).with_for_update()
            )
            if (
                slot is None
                or slot.experiment_id != task.payload["experiment_id"]
                or slot.workers != 1
                or slot.reserved != 0
                or slot.tokens_reserved != 0
            ):
                raise HarnessError("WORKER_SLOT_AUTHORITY", "Source slot binding changed.")
            if slot.state == "settled":
                return {"task_id": task_id, "released": False}
            if slot.state != "active" or self._pending_task_model_reservation(
                session, task_id, actor
            ):
                raise HarnessError(
                    "RECOVERY_RECONCILIATION_REQUIRED", "Source resource effects remain open."
                )
            workspaces = list(
                session.scalars(
                    select(RecordRow).where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "workspace",
                        RecordRow.payload["shared_worker_slot_id"].as_string() == slot_id,
                    )
                )
            )
            if any(row.payload.get("status") != "destroyed" for row in workspaces):
                raise HarnessError(
                    "RECOVERY_RECONCILIATION_REQUIRED", "Source VM is not confirmed destroyed."
                )
            budget = session.scalar(
                select(BudgetRow)
                .where(BudgetRow.experiment_id == task.payload["experiment_id"])
                .with_for_update()
            )
            if budget is None or budget.active_workers < 1:
                raise HarnessError("WORKER_SLOT_AUTHORITY", "Worker capacity accounting changed.")
            slot.state = "settled"
            slot.actual = 0
            slot.tokens_actual = 0
            budget.active_workers -= 1
            self._event(
                session,
                actor,
                op,
                "resources.settled",
                task.payload["experiment_id"],
                {"id": slot_id, "state": "settled", "actual_cost_usd": "0.000000"},
            )
            return {"task_id": task_id, "released": True, "slot_id": slot_id}

        return self._execute(actor, key, "task.reconcile-orphan-slot", {"task_id": task_id}, action)

    def reconcile_model_reservations(self, task_id, actor, key):
        """Clear only bindings whose authoritative ledger row is settled."""
        if actor.role not in {"operator", "admin"}:
            raise HarnessError("FORBIDDEN", "Controller authority is required.", status=403)

        def action(session, op):
            task = self._get(session, "task", task_id, actor)
            rows = list(
                session.scalars(
                    select(RecordRow).where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "model_reservation",
                        RecordRow.payload["task_id"].as_string() == task_id,
                        RecordRow.payload["status"].as_string() == "active",
                    )
                )
            )
            reconciled = []
            for row in rows:
                reservation = session.get(ReservationRow, row.payload["reservation_id"])
                if not reservation or reservation.experiment_id != task.payload["experiment_id"]:
                    raise HarnessError("RESERVATION_SCOPE", "Model reservation binding changed.")
                if reservation.state == "settled":
                    self._replace(session, row, {"status": "settled"})
                    reconciled.append(row.payload["reservation_id"])
            return {
                "task_id": task_id,
                "reconciled": reconciled,
                "pending": len(rows) - len(reconciled),
            }

        return self._execute(
            actor, key, "task.reconcile-model-reservations", {"task_id": task_id}, action
        )

    def task_model_effects_settled(self, task_id, actor):
        with self.db.sessions() as session:
            self._get(session, "task", task_id, actor)
            return not bool(self._pending_task_model_reservation(session, task_id, actor))

    def _pending_task_model_reservation(self, session, task_id, actor):
        return session.scalar(
            select(RecordRow.id)
            .where(
                RecordRow.project_id == actor.project_id,
                RecordRow.kind == "model_reservation",
                RecordRow.payload["task_id"].as_string() == task_id,
                RecordRow.payload["status"].as_string() == "active",
            )
            .limit(1)
        )

    def record_workspace_handoff(self, task_id, holder, fence, ticket, actor, key):
        if actor.role not in {"operator", "admin"}:
            raise HarnessError("FORBIDDEN", "Controller authority is required.", status=403)

        def action(session, op):
            task = self._get(session, "task", task_id, actor)
            self._fenced(session, task_id, holder, fence)
            artifact = self._get(session, "artifact", ticket["artifact_id"], actor)
            if (
                artifact.payload.get("experiment_id") != task.payload["experiment_id"]
                or artifact.payload.get("task_id") != task_id
                or artifact.payload.get("sha256") != ticket.get("archive_sha256")
            ):
                raise HarnessError(
                    "HANDOFF_WORKSPACE_MISMATCH", "Workspace ticket is out of task scope."
                )
            self.artifacts.get(artifact.payload["sha256"])
            self._replace(session, task, {"workspace_handoff_ticket": ticket})
            return {"task_id": task_id, "workspace_ticket": ticket}

        return self._execute(
            actor,
            key,
            "task.workspace-handoff",
            {
                "task_id": task_id,
                "holder": holder,
                "fence": fence,
                "ticket": ticket,
            },
            action,
        )

    def track_model_reservation(self, task_id, holder, fence, reservation_id, active, actor, key):
        """Bind a model reservation to its task, separate from concurrent siblings."""
        if actor.role not in {"operator", "admin"}:
            raise HarnessError("FORBIDDEN", "Controller authority is required.", status=403)

        def action(session, op):
            task = self._get(session, "task", task_id, actor)
            self._fenced(session, task_id, holder, fence)
            reservation = session.get(ReservationRow, reservation_id)
            if (
                not reservation
                or reservation.experiment_id != task.payload["experiment_id"]
                or reservation.workers != 0
            ):
                raise HarnessError("RESERVATION_SCOPE", "Model reservation is out of task scope.")
            existing = session.scalar(
                select(RecordRow).where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.kind == "model_reservation",
                    RecordRow.payload["reservation_id"].as_string() == reservation_id,
                )
            )
            if active:
                if existing is not None:
                    raise HarnessError("RESERVATION_SCOPE", "Model reservation was already bound.")
                self._insert(
                    session,
                    "model_reservation",
                    actor,
                    {
                        "experiment_id": task.payload["experiment_id"],
                        "task_id": task_id,
                        "reservation_id": reservation_id,
                        "holder": holder,
                        "fence": fence,
                        "status": "active",
                    },
                )
            else:
                if not existing or existing.payload.get("task_id") != task_id:
                    raise HarnessError("RESERVATION_SCOPE", "Model reservation binding is missing.")
                self._replace(session, existing, {"status": "settled"})
            return {"task_id": task_id, "reservation_id": reservation_id, "active": active}

        return self._execute(
            actor,
            key,
            "task.track-model-reservation",
            {
                "task_id": task_id,
                "holder": holder,
                "fence": fence,
                "reservation_id": reservation_id,
                "active": active,
            },
            action,
        )

    def restore_unstarted_continuation(self, task_id, actor, key):
        """Restore a consumed ticket only if no successor session was ever saved."""
        if actor.role not in {"operator", "admin"}:
            raise HarnessError("FORBIDDEN", "Controller authority is required.", status=403)

        def action(session, op):
            task = self._get(session, "task", task_id, actor)
            self._active(session, task.payload["experiment_id"], actor)
            consumed = task.payload.get("consumed_continuation")
            if not consumed or task.payload.get("ready_continuation"):
                raise HarnessError("CONTINUATION_STALE", "No consumed ticket needs restoration.")
            link = self._continuation_link(session, task_id, consumed["ordinal"], actor)
            if (
                link.payload.get("status") != "consumed"
                or link.payload.get("source_session_id") != consumed.get("source_session_id")
                or link.payload.get("source_checkpoint_digest")
                != consumed.get("source_checkpoint_digest")
                or link.payload.get("successor_session_id") is not None
            ):
                raise HarnessError(
                    "CONTINUATION_LINEAGE_MISMATCH", "Consumed link cannot be reissued."
                )
            lease = session.get(LeaseRow, task_id)
            if (
                not lease
                or lease.holder != consumed["holder"]
                or lease.fence != consumed["fence"]
                or lease.expires_at > utcnow().timestamp()
            ):
                raise HarnessError("LEASE_HELD", "Current successor lease has not expired.")
            rows = list(
                session.scalars(
                    select(RecordRow).where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "session",
                        RecordRow.payload["task_id"].as_string() == task_id,
                    )
                )
            )
            if len(rows) != consumed["ordinal"] or not any(
                r.payload.get("native_record_id") == consumed["source_session_id"]
                and r.payload.get("status") == "handed_off"
                for r in rows
            ):
                raise HarnessError(
                    "RECOVERY_RECONCILIATION_REQUIRED", "A successor session may already exist."
                )
            if self._pending_task_model_reservation(session, task_id, actor):
                raise HarnessError("RECOVERY_RECONCILIATION_REQUIRED", "Model usage is unresolved.")
            ready = {
                k: v for k, v in consumed.items() if k not in {"holder", "fence", "consumed_at"}
            }
            self._replace(
                session,
                link,
                {
                    "status": "issued",
                    "ready_digest": digest_json(ready),
                    "holder": None,
                    "fence": None,
                    "consumed_at": None,
                    "successor_model": None,
                    "successor_runtime": None,
                    "successor_runtime_limits": None,
                    "continuation_mode": None,
                },
            )
            result = self._replace(
                session,
                task,
                {
                    "status": "queued",
                    "holder": None,
                    "ready_continuation": ready,
                    "consumed_continuation": None,
                },
            )
            lease.expires_at = 0
            self._event(
                session,
                actor,
                op,
                "task.queued",
                task_id,
                {
                    "experiment_id": task.payload["experiment_id"],
                    "continuation": ready,
                },
                dispatch=True,
            )
            return {"task_id": task_id, "status": result["status"]}

        return self._execute(
            actor, key, "task.handoff-restore-unstarted", {"task_id": task_id}, action
        )

    def delegated_task_statuses(self, task_id, child_ids, actor):
        """Show relationship and terminal scheduling state, never child private work."""
        if actor.role != "agent" or len(child_ids) > 100:
            raise HarnessError("FORBIDDEN", "Agent task scope is required.", status=403)
        with self.db.sessions() as session:
            parent = self._get(session, "task", task_id, actor)
            if parent.payload.get("branch_id") != actor.branch_id:
                raise HarnessError("TASK_SCOPE", "Current branch does not own this task.")
            found = []
            experiment = self._get(session, "experiment", parent.payload["experiment_id"], actor)
            for identifier in child_ids:
                child = session.get(RecordRow, identifier)
                if (
                    child is None
                    or child.project_id != actor.project_id
                    or child.kind != "task"
                    or child.payload.get("experiment_id") != parent.payload["experiment_id"]
                    or child.payload.get("delegated_from_task_id") != task_id
                ):
                    raise HarnessError("HANDOFF_CHILD_SCOPE", "Task is not a delegated child.")
                found.append(
                    {
                        "task_id": identifier,
                        "status": child.payload["status"],
                        "strategy": child.payload.get("strategy"),
                        "execution_status": child.payload.get(
                            "execution_status", child.payload["status"]
                        ),
                        "error_code": child.payload.get("error_code"),
                        "return_result": (
                            child.payload.get("return_result")
                            if experiment.payload.get("sharing") == "ideas"
                            else {
                                "evidence_status": "withheld_by_sharing_policy",
                                "artifact_ids": [],
                                "unresolved_obligations": [],
                                "execution_failure": (
                                    {"status": child.payload["status"]}
                                    if child.payload["status"] in {"failed", "blocked"}
                                    else None
                                ),
                                "execution_status": child.payload["status"],
                            }
                        )
                        if child.payload["status"] in {"completed", "failed", "blocked"}
                        else None,
                    }
                )
            return {
                "task_id": task_id,
                "children": found,
                "all_terminal": all(
                    x["status"] in {"completed", "failed", "blocked"} for x in found
                ),
            }

    def request_handoff(self, task_id, reason, wait_task_ids, actor, key):
        """An active worker records intent; only the controller can issue a successor."""
        self._research_role(actor)
        binding = current_worker_effects.get()
        if (
            actor.role != "agent"
            or binding is None
            or binding.task_id != task_id
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 200
            or len(wait_task_ids) > 100
            or len(set(wait_task_ids)) != len(wait_task_ids)
        ):
            raise HarnessError(
                "HANDOFF_INTENT_INVALID", "A fenced task needs a bounded handoff intent."
            )

        def action(session, op):
            task = self._get(session, "task", task_id, actor)
            self._fenced(session, task_id, binding.holder, binding.fence)
            if (
                task.payload.get("status") != "running"
                or task.payload.get("branch_id") != actor.branch_id
            ):
                raise HarnessError(
                    "HANDOFF_INTENT_INVALID", "Only the current task may request handoff."
                )
            for identifier in wait_task_ids:
                child = session.get(RecordRow, identifier)
                if (
                    child is None
                    or child.project_id != actor.project_id
                    or child.kind != "task"
                    or child.payload.get("experiment_id") != task.payload["experiment_id"]
                    or child.payload.get("delegated_from_task_id") != task_id
                ):
                    raise HarnessError(
                        "HANDOFF_CHILD_SCOPE", "Wait targets must be delegated children."
                    )
            intent = {
                "reason": reason,
                "wait_task_ids": wait_task_ids,
                "holder": binding.holder,
                "fence": binding.fence,
                "requested_at": utcnow().isoformat(),
            }
            result = self._replace(session, task, {"handoff_intent": intent})
            self._event(
                session,
                actor,
                op,
                "task.handoff_requested",
                task_id,
                {"wait_count": len(wait_task_ids)},
            )
            return {"task_id": task_id, "intent": intent, "revision": result["revision"]}

        return self._execute(
            actor,
            key,
            "task.handoff-request",
            {
                "task_id": task_id,
                "reason": reason,
                "wait_task_ids": wait_task_ids,
            },
            action,
        )

    def request_peer_wait(self, task_id, recipient_branch_id, timeout_seconds, actor, key):
        """Yield a running task until a specific peer replies or a bounded deadline passes."""
        self._research_role(actor)
        binding = current_worker_effects.get()
        if (
            actor.role != "agent"
            or binding is None
            or binding.task_id != task_id
            or type(timeout_seconds) is not int
            or not 1 <= timeout_seconds <= 3600
            or not isinstance(recipient_branch_id, str)
        ):
            raise HarnessError(
                "PEER_WAIT_INVALID", "A fenced task and finite timeout are required."
            )

        def action(session, op):
            task = self._get(session, "task", task_id, actor)
            self._fenced(session, task_id, binding.holder, binding.fence)
            if (
                task.payload.get("status") != "running"
                or task.payload["branch_id"] != actor.branch_id
            ):
                raise HarnessError("PEER_WAIT_INVALID", "Only the current task can wait.")
            experiment = self._get(session, "experiment", task.payload["experiment_id"], actor)
            recipient = session.get(RecordRow, recipient_branch_id)
            if (
                experiment.payload.get("sharing") != "ideas"
                or recipient is None
                or recipient.project_id != actor.project_id
                or recipient.kind != "branch"
                or recipient.payload.get("experiment_id") != experiment.id
                or recipient_branch_id == actor.branch_id
            ):
                raise HarnessError(
                    "PEER_WAIT_SCOPE",
                    "Peer wait requires a branch in this ideas-sharing experiment.",
                )
            now = utcnow()
            # Anchor the wake on this branch's acknowledged delivery position, not
            # registration time: a reply that landed earlier in the same model turn
            # is still unseen, while already delivered messages must not wake it.
            reader = self._discussion_reader(session, experiment.id, actor)
            peer_wait = {
                "experiment_id": experiment.id,
                "task_id": task_id,
                "branch_id": actor.branch_id,
                "recipient_branch_id": recipient_branch_id,
                "requested_at": now.isoformat(),
                "deadline_at": now.timestamp() + timeout_seconds,
                "after_sequence": reader.payload["ack_sequence"] if reader else 0,
            }
            intent = {
                "reason": "wait_for_peer",
                "wait_task_ids": [],
                "peer_wait": peer_wait,
                "holder": binding.holder,
                "fence": binding.fence,
                "requested_at": now.isoformat(),
            }
            result = self._replace(session, task, {"handoff_intent": intent})
            self._event(
                session,
                actor,
                op,
                "task.peer_wait_requested",
                task_id,
                {
                    "recipient_branch_id": recipient_branch_id,
                    "deadline_at": peer_wait["deadline_at"],
                },
            )
            return {"task_id": task_id, "intent": intent, "revision": result["revision"]}

        return self._execute(
            actor,
            key,
            "task.peer-wait",
            {
                "task_id": task_id,
                "recipient_branch_id": recipient_branch_id,
                "timeout_seconds": timeout_seconds,
            },
            action,
        )

    def peer_wait_status(self, peer_wait, actor):
        """Return only the wake reason; message content remains mailbox scoped."""
        self._research_role(actor)
        if not isinstance(peer_wait, dict) or type(peer_wait.get("after_sequence")) is not int:
            raise HarnessError("PEER_WAIT_INVALID", "Peer wait ticket is malformed.")
        branch_id = peer_wait.get("branch_id")
        if actor.role == "agent" and branch_id != actor.branch_id:
            raise HarnessError(
                "BRANCH_AUTHORITY", "Peer wait belongs to another branch.", status=403
            )
        with self.db.sessions() as session:
            branch = self._get(session, "branch", branch_id, actor)
            if branch.payload.get("experiment_id") != peer_wait.get("experiment_id"):
                raise HarnessError("PEER_WAIT_SCOPE", "Peer wait experiment changed.")
            experiment = self._get(session, "experiment", peer_wait["experiment_id"], actor)
            waiter = session.get(RecordRow, peer_wait.get("task_id") or "")
            if experiment.payload.get("status") == "cancelled" or (
                waiter is not None
                and waiter.kind == "task"
                and waiter.project_id == actor.project_id
                and waiter.payload.get("branch_id") == branch_id
                and waiter.payload.get("status") in {"completed", "failed", "blocked"}
            ):
                return {"ready": True, "reason": "cancelled", "message_id": None}
            # A later sharing downgrade or recipient move withdraws the wait scope;
            # wake the waiter instead of failing its supervisor.
            recipient = session.get(RecordRow, peer_wait.get("recipient_branch_id") or "")
            if (
                experiment.payload.get("sharing") != "ideas"
                or recipient is None
                or recipient.kind != "branch"
                or recipient.project_id != actor.project_id
                or recipient.payload.get("experiment_id") != experiment.id
            ):
                return {"ready": True, "reason": "scope_withdrawn", "message_id": None}
            message = session.scalar(
                select(RecordRow)
                .join(
                    EventRow,
                    and_(
                        EventRow.project_id == RecordRow.project_id,
                        EventRow.kind == "message.created",
                        EventRow.payload["message_id"].as_string() == RecordRow.id,
                    ),
                )
                .where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.kind == "message",
                    record_json_text("experiment_id") == peer_wait["experiment_id"],
                    record_json_text("sender_branch_id") == peer_wait.get("recipient_branch_id"),
                    record_json_text("recipient_branch_id") == branch_id,
                    EventRow.aggregate_id == branch_id,
                    EventRow.sequence > peer_wait["after_sequence"],
                )
                .order_by(EventRow.sequence)
                .limit(1)
            )
            if message:
                return {"ready": True, "reason": "message_received", "message_id": message.id}
            recipient_tasks = list(
                session.scalars(
                    select(RecordRow).where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "task",
                        record_json_text("experiment_id") == peer_wait["experiment_id"],
                        record_json_text("branch_id") == peer_wait.get("recipient_branch_id"),
                    )
                )
            )
            if recipient_tasks and all(
                row.payload.get("status") in {"completed", "failed", "blocked"}
                for row in recipient_tasks
            ):
                return {"ready": True, "reason": "recipient_terminal", "message_id": None}
            if utcnow().timestamp() >= peer_wait.get("deadline_at", 0):
                return {"ready": True, "reason": "timeout", "message_id": None}
            return {"ready": False, "reason": "pending", "message_id": None}

    def handoff_intent(self, task_id, holder, fence, actor):
        with self.db.sessions() as session:
            task = self._get(session, "task", task_id, actor)
            self._fenced(session, task_id, holder, fence)
            intent = task.payload.get("handoff_intent")
            if intent and (intent["holder"], intent["fence"]) == (holder, fence):
                return intent
            return None

    def issue_continuation(
        self,
        task_id,
        holder,
        fence,
        source_session_id,
        source_checkpoint_digest,
        reason,
        actor,
        key,
        *,
        recover_expired=False,
        workspace_ticket=None,
    ):
        """Convert a terminal settled checkpoint into one runnable successor."""
        if actor.role not in {"operator", "admin"}:
            raise HarnessError("FORBIDDEN", "Controller authority is required.", status=403)

        def action(session, op):
            task = self._get(session, "task", task_id, actor)
            self._active(session, task.payload["experiment_id"], actor)
            if recover_expired:
                lease = session.get(LeaseRow, task_id)
                if (
                    lease is None
                    or lease.holder != holder
                    or lease.fence != fence
                    or lease.expires_at > utcnow().timestamp()
                ):
                    raise HarnessError("STALE_LEASE", "Recovery requires the expired source fence.")
            else:
                lease = self._fenced(session, task_id, holder, fence)
            intent = task.payload.get("handoff_intent")
            if intent:
                if (intent["holder"], intent["fence"], intent["reason"]) != (holder, fence, reason):
                    raise HarnessError("HANDOFF_INTENT_MISMATCH", "Handoff intent changed.")
            elif reason != "automatic_context_boundary":
                raise HarnessError(
                    "HANDOFF_INTENT_REQUIRED", "No authorized handoff intent exists."
                )
            if reason == "root_unproved_replan":
                experiment_for_policy = self._get(
                    session, "experiment", task.payload["experiment_id"], actor
                )
                if task.payload.get("root_replans_used", 0) >= task.payload.get(
                    "root_replan_limit", 0
                ) or task.payload.get("root_target_digest") != experiment_for_policy.payload.get(
                    "target_digest"
                ):
                    raise HarnessError(
                        "ROOT_REPLAN_EXHAUSTED", "Root continuation policy is exhausted."
                    )
            rows = list(
                session.scalars(
                    select(RecordRow).where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "session",
                        RecordRow.payload["native_record_id"].as_string() == source_session_id,
                    )
                )
            )
            if len(rows) != 1 or rows[0].payload.get("task_id") != task_id:
                raise HarnessError(
                    "HANDOFF_SOURCE_MISMATCH", "Source session is absent or out of scope."
                )
            source = rows[0].payload
            if source.get("status") != "handed_off":
                raise HarnessError(
                    "HANDOFF_SOURCE_UNSETTLED", "Source session is not terminal for handoff."
                )
            checkpoint = self.load_native_checkpoint(source["checkpoint_artifact_id"], actor)
            stagnation_state = checkpoint.native_state.get("stagnation", {})
            if not isinstance(stagnation_state, dict):
                raise HarnessError("CONTINUATION_STALE", "Source progress state is malformed.")
            if (
                checkpoint.state_digest != source_checkpoint_digest
                or checkpoint.session.id != source_session_id
                or checkpoint.session.status != "handed_off"
                or checkpoint.session.model.model_dump(mode="json") != source["model"]
                or source.get("experiment_id") != task.payload["experiment_id"]
            ):
                raise HarnessError("HANDOFF_SOURCE_MISMATCH", "Source checkpoint digest changed.")
            native = checkpoint.native_state
            if (
                native.get("settled_boundary") is not True
                or native.get("pending_operation")
                or native.get("pending_tool_call")
            ):
                raise HarnessError("HANDOFF_SOURCE_UNSETTLED", "Source has pending native effects.")
            if checkpoint.session.turns < 1 or checkpoint.session.input_tokens < 1:
                raise HarnessError("HANDOFF_NO_PROGRESS", "Source made no billable progress.")
            if self._pending_task_model_reservation(session, task_id, actor):
                raise HarnessError(
                    "RECOVERY_RECONCILIATION_REQUIRED",
                    "Outstanding model reservation blocks handoff.",
                )
            experiment = self._get(session, "experiment", task.payload["experiment_id"], actor)
            problem = self._get(session, "problem", experiment.payload["problem_id"], actor)
            if (
                problem.payload.get("target_digest") != experiment.payload.get("target_digest")
                or problem.payload.get("semantic_review") != "approved"
            ):
                raise HarnessError("TARGET_CHANGED", "Reviewed target changed before handoff.")
            selected_ticket = workspace_ticket or task.payload.get("workspace_handoff_ticket")
            source_workspaces = list(
                session.scalars(
                    select(RecordRow).where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "workspace",
                        RecordRow.payload["task_id"].as_string() == task_id,
                        RecordRow.payload["holder"].as_string() == holder,
                        RecordRow.payload["fence"].as_integer() == fence,
                    )
                )
            )
            if source_workspaces and not selected_ticket:
                raise HarnessError(
                    "WORKSPACE_RESTORE_REQUIRED", "Source VM has no durable handoff archive."
                )
            if selected_ticket:
                artifact = self._get(session, "artifact", selected_ticket["artifact_id"], actor)
                if (
                    artifact.payload.get("experiment_id") != experiment.id
                    or artifact.payload.get("task_id") != task_id
                    or artifact.payload.get("sha256") != selected_ticket.get("archive_sha256")
                    or selected_ticket.get("environment_digest")
                    != problem.payload["environment_digest"]
                ):
                    raise HarnessError(
                        "HANDOFF_WORKSPACE_MISMATCH", "Workspace archive binding changed."
                    )
                self.artifacts.get(artifact.payload["sha256"])
            portable = session.scalar(
                select(RecordRow)
                .where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.kind == "artifact",
                    RecordRow.payload["experiment_id"].as_string() == experiment.id,
                    RecordRow.payload["branch_id"].as_string() == task.payload["branch_id"],
                    RecordRow.payload["artifact_kind"].as_string() == "checkpoint",
                    record_json_text("context_format").in_(
                        [
                            "physharness.portable-context.v1",
                            "physharness.research-notes.v1",
                        ]
                    ),
                    RecordRow.payload["task_id"].as_string() == task_id,
                )
                .order_by(RecordRow.payload["created_at"].as_string().desc(), RecordRow.id.desc())
                .limit(1)
            )
            ready = {
                "source_session_id": source_session_id,
                "source_checkpoint_digest": source_checkpoint_digest,
                "reason": reason,
                "recover_expired": recover_expired,
                "wait_task_ids": intent["wait_task_ids"] if intent else [],
                "peer_wait": intent.get("peer_wait") if intent else None,
                "model": source["model"],
                "experiment_id": experiment.id,
                "branch_id": task.payload["branch_id"],
                "target_digest": problem.payload["target_digest"],
                "review_id": problem.payload.get("review_id"),
                "environment_digest": problem.payload["environment_digest"],
                "runtime": checkpoint.session.runtime,
                "runtime_limits": checkpoint.session.limits.model_dump(mode="json"),
                "stagnation_state": stagnation_state,
                "tool_definition_digest": source.get("tool_definition_digest"),
                "workspace_policy_digest": digest_json(task.payload.get("workspace_policy")),
                "portable_checkpoint": (
                    {"artifact_id": portable.id, "sha256": portable.payload["sha256"]}
                    if portable
                    else None
                ),
                "workspace_ticket": selected_ticket,
                "ordinal": int(task.payload.get("continuation_count", 0)) + 1,
                "issued_at": utcnow().isoformat(),
            }
            prior_links = list(
                session.scalars(
                    select(RecordRow).where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "continuation_link",
                        RecordRow.payload["task_id"].as_string() == task_id,
                    )
                )
            )
            if (
                len(prior_links) != ready["ordinal"] - 1
                or {link.payload.get("ordinal") for link in prior_links}
                != set(range(1, ready["ordinal"]))
                or any(link.payload.get("status") != "started" for link in prior_links)
            ):
                raise HarnessError(
                    "CONTINUATION_LINEAGE_MISMATCH", "Prior continuation links are unresolved."
                )
            # Only the newest successor may hand off; an older handed-off source
            # would fork the chain into a second ticket from superseded context.
            if prior_links and (
                max(prior_links, key=lambda link: link.payload["ordinal"]).payload.get(
                    "successor_session_id"
                )
                != source_session_id
            ):
                raise HarnessError(
                    "HANDOFF_SOURCE_NOT_HEAD",
                    "Handoff source is not the latest session in this task's continuation chain.",
                )
            # Cleanup has already destroyed the source VM. Settle its shared
            # capacity in this same transaction as issuing the runnable ticket:
            # process death after commit must not strand a one-slot successor.
            slot_id = task.payload.get("worker_slot_id")
            if slot_id:
                slot = session.scalar(
                    select(ReservationRow).where(ReservationRow.id == slot_id).with_for_update()
                )
                if (
                    slot is None
                    or slot.experiment_id != experiment.id
                    or slot.workers != 1
                    or slot.reserved != 0
                    or slot.tokens_reserved != 0
                    or slot.state not in {"active", "settled"}
                ):
                    raise HarnessError("WORKER_SLOT_AUTHORITY", "Source slot binding changed.")
                linked_workspaces = list(
                    session.scalars(
                        select(RecordRow).where(
                            RecordRow.project_id == actor.project_id,
                            RecordRow.kind == "workspace",
                            RecordRow.payload["shared_worker_slot_id"].as_string() == slot_id,
                        )
                    )
                )
                if any(row.payload.get("status") != "destroyed" for row in linked_workspaces):
                    raise HarnessError(
                        "RECOVERY_RECONCILIATION_REQUIRED", "Source VM is not destroyed."
                    )
                if slot.state == "active":
                    budget = session.scalar(
                        select(BudgetRow)
                        .where(BudgetRow.experiment_id == experiment.id)
                        .with_for_update()
                    )
                    if budget is None or budget.active_workers < 1:
                        raise HarnessError(
                            "WORKER_SLOT_AUTHORITY", "Worker capacity accounting changed."
                        )
                    slot.state = "settled"
                    slot.actual = 0
                    slot.tokens_actual = 0
                    budget.active_workers -= 1
                    self._event(
                        session,
                        actor,
                        op,
                        "resources.settled",
                        experiment.id,
                        {"id": slot_id, "state": "settled", "actual_cost_usd": "0.000000"},
                    )
            result = self._replace(
                session,
                task,
                {
                    "status": "queued",
                    "holder": None,
                    "handoff_intent": None,
                    "workspace_handoff_ticket": None,
                    "ready_continuation": ready,
                    "continuation_count": ready["ordinal"],
                    "root_replans_used": task.payload.get("root_replans_used", 0)
                    + (1 if reason == "root_unproved_replan" else 0),
                    "continuation_link_protocol": 1,
                    "stagnation_state": ready["stagnation_state"],
                    "delivered_child_task_ids": sorted(
                        set(task.payload.get("delivered_child_task_ids", []))
                        | set(ready["wait_task_ids"])
                    ),
                },
            )
            self._insert(
                session,
                "continuation_link",
                actor,
                {
                    "experiment_id": experiment.id,
                    "task_id": task_id,
                    "ordinal": ready["ordinal"],
                    "status": "issued",
                    "source_session_record_id": source["id"],
                    "source_session_id": source_session_id,
                    "source_checkpoint_artifact_id": source["checkpoint_artifact_id"],
                    "source_checkpoint_digest": source_checkpoint_digest,
                    "source_model": ready["model"],
                    "source_runtime": ready["runtime"],
                    "source_runtime_limits": ready["runtime_limits"],
                    "ready_digest": digest_json(ready),
                    "target_digest": ready["target_digest"],
                    "review_id": ready["review_id"],
                    "environment_digest": ready["environment_digest"],
                    "workspace_ticket": selected_ticket,
                    "portable_checkpoint": ready["portable_checkpoint"],
                    "issued_at": ready["issued_at"],
                    "successor_session_id": None,
                    "successor_record_id": None,
                },
            )
            lease.expires_at = 0
            self._event(
                session,
                actor,
                op,
                "task.queued",
                task_id,
                {
                    "experiment_id": task.payload["experiment_id"],
                    "continuation": ready,
                },
                dispatch=True,
            )
            return {"task_id": task_id, "status": result["status"], "ready_continuation": ready}

        return self._execute(
            actor,
            key,
            "task.handoff-issue",
            {
                "task_id": task_id,
                "holder": holder,
                "fence": fence,
                "source_session_id": source_session_id,
                "source_checkpoint_digest": source_checkpoint_digest,
                "reason": reason,
                "recover_expired": recover_expired,
                "workspace_ticket": workspace_ticket,
            },
            action,
        )

    def consume_continuation(
        self,
        task_id,
        holder,
        fence,
        ready,
        actor,
        key,
        *,
        successor_model=None,
        successor_runtime_limits=None,
        continuation_mode="portable",
    ):
        if actor.role not in {"operator", "admin"}:
            raise HarnessError("FORBIDDEN", "Controller authority is required.", status=403)

        def action(session, op):
            task = self._get(session, "task", task_id, actor)
            self._fenced(session, task_id, holder, fence)
            if task.payload.get("ready_continuation") != ready:
                raise HarnessError("CONTINUATION_STALE", "Continuation was consumed or changed.")
            link = self._continuation_link(session, task_id, ready["ordinal"], actor)
            if (
                link.payload.get("status") != "issued"
                or link.payload.get("ready_digest") != digest_json(ready)
                or link.payload.get("source_session_id") != ready.get("source_session_id")
                or link.payload.get("source_checkpoint_digest")
                != ready.get("source_checkpoint_digest")
            ):
                raise HarnessError("CONTINUATION_LINEAGE_MISMATCH", "Issued link changed.")
            experiment = self._get(session, "experiment", task.payload["experiment_id"], actor)
            problem = self._get(session, "problem", experiment.payload["problem_id"], actor)
            if (
                ready.get("experiment_id") != experiment.id
                or ready.get("branch_id") != task.payload["branch_id"]
                or ready.get("target_digest") != problem.payload.get("target_digest")
                or ready.get("review_id") != problem.payload.get("review_id")
                or ready.get("environment_digest") != problem.payload.get("environment_digest")
                or problem.payload.get("semantic_review") != "approved"
            ):
                raise HarnessError("CONTINUATION_STALE", "Reviewed successor scope changed.")
            consumed_at = utcnow().isoformat()
            chosen_model = successor_model or ready["model"]
            chosen_limits = successor_runtime_limits or ready["runtime_limits"]
            result = self._replace(
                session,
                task,
                {
                    "ready_continuation": None,
                    "consumed_continuation": {
                        **ready,
                        "successor_model": chosen_model,
                        "successor_runtime_limits": chosen_limits,
                        "successor_runtime": ready["runtime"],
                        "continuation_mode": continuation_mode,
                        "holder": holder,
                        "fence": fence,
                        "consumed_at": consumed_at,
                    },
                    "terminal_recovery": None,
                },
            )
            self._replace(
                session,
                link,
                {
                    "status": "consumed",
                    "holder": holder,
                    "fence": fence,
                    "consumed_at": consumed_at,
                    "successor_model": chosen_model,
                    "successor_runtime": ready["runtime"],
                    "successor_runtime_limits": chosen_limits,
                    "continuation_mode": continuation_mode,
                },
            )
            return {"task_id": task_id, "revision": result["revision"]}

        return self._execute(
            actor,
            key,
            "task.handoff-consume",
            {
                "task_id": task_id,
                "holder": holder,
                "fence": fence,
                "ready_digest": digest_json(ready),
                "successor_model": successor_model,
                "successor_runtime_limits": successor_runtime_limits,
                "continuation_mode": continuation_mode,
            },
            action,
        )
