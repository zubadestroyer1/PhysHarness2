"""Durable delegation, fenced completion, mailboxes and evidence-preserving restart briefs."""

import copy

from sqlalchemy import select

from .domain import Principal, TaskCreate, canonical_json, utcnow
from .errors import HarnessError
from .storage import EdgeRow, EventRow, LeaseRow, RecordRow, ReservationRow, record_json_text
from .worker_authority import current_worker_effects


def controller_only(actor):
    if actor.role not in {"operator", "admin"}:
        raise HarnessError(
            "FORBIDDEN", "This identity does not have the controller capability.", status=403
        )


class CollaborationMixin:
    def retire_queued_after_verified(self, task_id, receipt_id, actor, key):
        """Durably supersede an unleased task after exact independent acceptance."""
        controller_only(actor)

        def action(session, op):
            self.db.command_lock(session, self._digest(["task-lease", task_id]))
            task = self._get(session, "task", task_id, actor)
            experiment = self._get(session, "experiment", task.payload["experiment_id"], actor)
            receipt = session.get(RecordRow, receipt_id)
            if (
                receipt is None
                or receipt.project_id != actor.project_id
                or receipt.kind != "verification"
                or not self._accepted_evidence(session, receipt, experiment, {"independent_kernel"})
            ):
                raise HarnessError("TARGET_NOT_VERIFIED", "Exact target has no accepted receipt.")
            if task.payload.get("status") != "queued":
                return {"retired": False, "task_id": task_id, "status": task.payload.get("status")}
            lease = session.get(LeaseRow, task_id)
            if lease and lease.expires_at > utcnow().timestamp():
                return {"retired": False, "task_id": task_id, "status": "leased"}
            ready = task.payload.get("ready_continuation")
            if ready:
                link = session.scalar(
                    select(RecordRow)
                    .where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "continuation_link",
                        record_json_text("task_id") == task_id,
                        RecordRow.payload["ordinal"].as_integer() == ready["ordinal"],
                    )
                    .limit(1)
                )
                if link is None or link.payload.get("status") != "issued":
                    raise HarnessError("CONTINUATION_LINEAGE_MISMATCH", "Ready link changed.")
                self._replace(
                    session, link, {"status": "retired", "retired_by_receipt_id": receipt_id}
                )
            result = self._replace(
                session,
                task,
                {
                    "status": "blocked",
                    "error_code": "TARGET_ALREADY_VERIFIED",
                    "superseded_by_receipt_id": receipt_id,
                    "retired_continuation": ready,
                    "ready_continuation": None,
                },
            )
            self._event(
                session,
                actor,
                op,
                "task.superseded_by_verification",
                task_id,
                {"experiment_id": experiment.id, "receipt_id": receipt_id},
            )
            return {
                "retired": True,
                "task_id": task_id,
                "status": result["status"],
                "code": "TARGET_ALREADY_VERIFIED",
            }

        return self._execute(
            actor,
            key,
            "task.retire-after-verification",
            {
                "task_id": task_id,
                "receipt_id": receipt_id,
            },
            action,
        )

    def message_delivery_status(self, message_id, actor):
        """Expose sender-visible delivery progress, never recipient mailbox contents."""
        self._research_role(actor)
        with self.db.sessions() as session:
            message = self._get(session, "message", message_id, actor)
            data = message.payload
            if actor.role == "agent" and data.get("sender_branch_id") != actor.branch_id:
                raise HarnessError(
                    "BRANCH_AUTHORITY", "Only the sender can inspect delivery.", status=403
                )
            event = session.scalar(
                select(EventRow)
                .where(
                    EventRow.project_id == actor.project_id,
                    EventRow.kind == "message.created",
                    EventRow.payload["message_id"].as_string() == message_id,
                )
                .limit(1)
            )
            if event is None:
                raise HarnessError("DELIVERY_MISMATCH", "Message event is missing.")
            deliveries = list(
                session.scalars(
                    select(RecordRow)
                    .where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "discussion_delivery",
                        record_json_text("experiment_id") == data["experiment_id"],
                        record_json_text("reader_key") == f"branch:{data['recipient_branch_id']}",
                        RecordRow.payload["start_sequence"].as_integer() < event.sequence,
                        RecordRow.payload["end_sequence"].as_integer() >= event.sequence,
                    )
                    .order_by(RecordRow.id)
                    .limit(11)
                )
            )
            if len(deliveries) > 10:
                raise HarnessError(
                    "DELIVERY_MISMATCH", "Overlapping delivery history exceeds bound."
                )
            state = "queued"
            for delivery in deliveries:
                for item in delivery.payload.get("items", []):
                    if item.get("sequence") != event.sequence:
                        continue
                    if item.get("source_kind") == "withdrawal":
                        state = "withdrawn_unavailable"
                    elif item.get("source_kind") == "message" and item.get("id") == message_id:
                        if state != "withdrawn_unavailable":
                            state = (
                                "acknowledged"
                                if delivery.payload.get("status") == "acknowledged"
                                else "presented_unacknowledged"
                            )
            if (
                state == "queued"
                and self._branch_availability(
                    session, data["experiment_id"], data["recipient_branch_id"], actor
                )
                == "terminal"
            ):
                # Never presented, and no live or queued recipient work will read it.
                state = "recipient_unavailable"
            return {
                "message_id": message_id,
                "recipient_branch_id": data["recipient_branch_id"],
                "state": state,
                "meaning": "acknowledged means delivered, not adopted",
            }

    def _branch_availability(self, session, experiment_id, branch_id, actor):
        """Coarse scheduling state from at most 100 unfinished tasks; no task content."""
        rows = list(
            session.scalars(
                select(RecordRow)
                .where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.kind == "task",
                    record_json_text("experiment_id") == experiment_id,
                    record_json_text("branch_id") == branch_id,
                    record_json_text("status").in_(["queued", "running"]),
                )
                .order_by(RecordRow.id)
                .limit(100)
            )
        )
        now = utcnow().timestamp()
        states = set()
        for row in rows:
            ready = row.payload.get("ready_continuation") or {}
            lease = session.get(LeaseRow, row.id)
            if row.payload["status"] == "running" and lease and lease.expires_at > now:
                states.add("active")
            elif ready.get("peer_wait") or ready.get("wait_task_ids"):
                states.add("waiting")
            else:
                states.add("queued")
        return next((s for s in ("active", "queued", "waiting") if s in states), "terminal")

    def peer_availability(self, experiment_id, actor, *, after=None, limit=20):
        """Page peer branch availability; agents see peers only under ideas sharing."""
        self._research_role(actor)
        if type(limit) is not int or not 1 <= limit <= 20:
            raise HarnessError("INVALID_PAGE_SIZE", "Availability page size is 1–20.", status=422)
        with self.db.sessions() as session:
            experiment = self._get(session, "experiment", experiment_id, actor)
            shared = actor.role != "agent" or experiment.payload.get("sharing") == "ideas"
            items, cursor, more = [], after, False
            while not more:
                query = select(RecordRow).where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.kind == "branch",
                    record_json_text("experiment_id") == experiment_id,
                )
                if cursor:
                    query = query.where(RecordRow.id > cursor)
                rows = list(session.scalars(query.order_by(RecordRow.id).limit(100)))
                for row in rows:
                    if len(items) >= limit:
                        more = True
                        break
                    cursor = row.id
                    if row.id == actor.branch_id or not (
                        shared or self._in_scope(session, row, actor)
                    ):
                        continue
                    items.append(
                        {
                            "branch_id": row.id,
                            "state": self._branch_availability(
                                session, experiment_id, row.id, actor
                            ),
                        }
                    )
                if len(rows) < 100:
                    break
            return {
                "items": items,
                "next_cursor": cursor if more else None,
                "meaning": "scheduling state only; no task content or proof status",
            }

    def amend_queued_task_objective(self, task_id, expected_revision, objective, actor, key):
        """Replace an unstarted assignment under the same lock as lease admission."""
        self._research_role(actor)
        if not isinstance(objective, str) or not objective.strip() or len(objective) > 20000:
            raise HarnessError("INVALID_OBJECTIVE", "Objective must contain 1–20,000 characters.")
        if type(expected_revision) is not int or expected_revision < 1:
            raise HarnessError("REVISION_REQUIRED", "Exact task revision is required.")

        def action(session, op):
            self.db.command_lock(session, self._digest(["task-lease", task_id]))
            task = session.get(RecordRow, task_id)
            if task is None or task.kind != "task" or task.project_id != actor.project_id:
                raise HarnessError("NOT_FOUND", "Assignment was not found.", status=404)
            self._guard_referee_task(task, actor)
            self._active(session, task.payload["experiment_id"], actor)
            binding = current_worker_effects.get()
            owner = task.payload.get("created_by") == actor.id
            parent_worker = (
                actor.role == "agent"
                and binding is not None
                and task.payload.get("delegated_from_task_id") == binding.task_id
            )
            if actor.role not in {"operator", "admin"} and not (owner or parent_worker):
                raise HarnessError(
                    "TASK_AUTHORITY", "Only the assignment owner may amend it.", status=403
                )
            if not parent_worker:
                self._get(session, "task", task_id, actor)
            if task.payload["status"] != "queued" or session.get(LeaseRow, task_id):
                raise HarnessError("TASK_NOT_QUEUED", "Assignment has already started.")
            history = list(task.payload.get("superseded_objectives", []))
            history.append({"revision": task.revision, "objective": task.payload["objective"]})
            # Keep the last 8 objectives verbatim; older ones survive as a hash chain.
            dropped = dict(
                task.payload.get("superseded_objectives_dropped") or {"count": 0, "digest": None}
            )
            changes = {"objective": objective, "superseded_objectives": history[-8:]}
            for entry in history[:-8]:
                dropped = {
                    "count": dropped["count"] + 1,
                    "digest": self._digest([dropped["digest"], entry]),
                }
            if dropped["count"]:
                changes["superseded_objectives_dropped"] = dropped
            result = self._replace(session, task, changes, expected_revision)
            self._event(
                session,
                actor,
                op,
                "task.objective_amended",
                task_id,
                {"experiment_id": result["experiment_id"], "revision": result["revision"]},
            )
            if parent_worker:
                return {
                    key: result[key]
                    for key in (
                        "id",
                        "revision",
                        "objective",
                        "superseded_objectives",
                        "superseded_objectives_dropped",
                        "status",
                    )
                    if key in result
                }
            return result

        return self._execute(
            actor,
            key,
            "task.objective-amend",
            {"task_id": task_id, "expected_revision": expected_revision, "objective": objective},
            action,
        )

    def _recipient_visible_artifacts(
        self, session, artifact_ids, experiment_id, recipient_branch_id, actor, *, strict
    ):
        """Check actual recipient branch scope before queuing a message."""
        recipient = Principal(
            id=f"recipient:{recipient_branch_id}",
            project_id=actor.project_id,
            role="agent",
            experiment_id=experiment_id,
            branch_id=recipient_branch_id,
        )
        visible = []
        for identifier in artifact_ids:
            evidence = self._get(session, "artifact", identifier, actor)
            if evidence.payload.get("experiment_id") != experiment_id:
                raise HarnessError(
                    "EVIDENCE_SCOPE", "Message evidence belongs to another experiment."
                )
            if self._in_scope(session, evidence, recipient):
                visible.append(identifier)
            elif strict:
                raise HarnessError(
                    "MESSAGE_ATTACHMENT_INACCESSIBLE",
                    "The recipient cannot read a referenced artifact.",
                    status=422,
                )
        return visible

    def mailbox_page(self, branch_id, actor, *, after=None, limit=3):
        """Page only messages addressed to this branch under existing sharing rules."""
        self._research_role(actor)
        if not 1 <= limit <= 3:
            raise HarnessError("INVALID_PAGE_SIZE", "Mailbox page size is 1–3.", status=422)
        branch = self.get_record("branch", branch_id, actor)
        if actor.role == "agent" and branch_id != actor.branch_id:
            raise HarnessError("BRANCH_AUTHORITY", "Mailbox belongs to another branch.", status=403)
        page = self.page_records("message", actor, branch["experiment_id"], limit, after)
        return {
            "items": [
                {
                    key: msg.get(key)
                    for key in (
                        "id",
                        "sender_branch_id",
                        "recipient_branch_id",
                        "attributed_to",
                        "content",
                        "artifact_ids",
                        "evidence_status",
                        "reply_to_parent_task_id",
                        "child_task_id",
                        "created_at",
                    )
                }
                for msg in page["items"]
                if msg.get("recipient_branch_id") == branch_id
            ],
            "next_cursor": page["next_cursor"],
            "evidence_status": "attributed_idea",
        }

    def create_task(self, request: TaskCreate, actor: Principal, key: str) -> dict:
        self._research_role(actor)
        data = request.model_dump(mode="json")
        if data.get("strategy") is None:
            data.pop("strategy")  # Absent strategies keep legacy payloads and command digests.
        binding = current_worker_effects.get()
        delegated_from_task_id = binding.task_id if actor.role == "agent" and binding else None
        if delegated_from_task_id:
            data["delegated_from_task_id"] = delegated_from_task_id
        elif request.detached and actor.role == "agent":
            raise HarnessError("DETACHED_SCOPE", "Detached work requires a current parent task.")

        def action(session, op):
            branch = self._writable_branch(session, request.branch_id, actor, delegation=True)
            experiment_id = branch.payload["experiment_id"]
            self._admit_research_tasks(session, experiment_id, actor)
            if len(set(request.dependency_ids)) != len(request.dependency_ids):
                raise HarnessError(
                    "DUPLICATE_DEPENDENCY", "Task dependencies must be unique.", status=422
                )
            if delegated_from_task_id and not request.detached:
                ancestor_id = delegated_from_task_id
                while ancestor_id:
                    if ancestor_id in request.dependency_ids:
                        raise HarnessError(
                            "JOIN_DEPENDENCY_CYCLE",
                            "Joined work cannot depend on an ancestor that waits for it.",
                            status=422,
                        )
                    ancestor = session.get(RecordRow, ancestor_id)
                    if (
                        ancestor is None
                        or ancestor.kind != "task"
                        or ancestor.project_id != actor.project_id
                        or ancestor.payload.get("experiment_id") != experiment_id
                    ):
                        raise HarnessError("TASK_SCOPE", "Delegated task lineage changed.")
                    ancestor_id = ancestor.payload.get("reply_to_parent_task_id")
            for identifier in request.dependency_ids:
                dependency = self._get(session, "task", identifier, actor)
                if dependency.payload["experiment_id"] != experiment_id:
                    raise HarnessError(
                        "DEPENDENCY_SCOPE", "Delegated task dependencies must share an experiment."
                    )
            record = self._insert(
                session,
                "task",
                actor,
                {
                    **data,
                    "experiment_id": experiment_id,
                    "status": "queued",
                    "evidence_ids": [],
                    "created_by": actor.id,
                    "reply_to_parent_task_id": delegated_from_task_id
                    if not request.detached
                    else None,
                },
            )
            for identifier in request.dependency_ids:
                session.add(
                    EdgeRow(
                        source_id=record["id"],
                        target_id=identifier,
                        relation="requires",
                        project_id=actor.project_id,
                    )
                )
            self._event(
                session,
                actor,
                op,
                "task.queued",
                record["id"],
                {"experiment_id": experiment_id},
                dispatch=True,
            )
            return record

        return self._execute(actor, key, "task.create", data, action)

    def acquire_task(
        self, task_id: str, holder: str, ttl_seconds: int, actor: Principal, key: str
    ) -> dict:
        controller_only(actor)
        if not holder or not 1 <= ttl_seconds <= 300:
            raise HarnessError(
                "INVALID_LEASE",
                "Lease holder and a duration of 1–300 seconds are required.",
                status=422,
            )

        def action(session, op):
            self.db.command_lock(session, self._digest(["task-lease", task_id]))
            task = self._get(session, "task", task_id, actor)
            self._active(session, task.payload["experiment_id"], actor)
            if task.payload["status"] not in {"queued", "running"}:
                raise HarnessError("TASK_NOT_RUNNABLE", "Task is not queued or recoverable.")
            for dependency_id in task.payload["dependency_ids"]:
                dependency = self._get(session, "task", dependency_id, actor)
                if dependency.payload["status"] != "completed":
                    raise HarnessError(
                        "DEPENDENCIES_PENDING",
                        "Task prerequisites have not completed.",
                        retryable=True,
                    )
            lease = session.get(LeaseRow, task_id)
            now = utcnow().timestamp()
            if lease and lease.expires_at > now:
                raise HarnessError("LEASE_HELD", "A live worker holds this task.", retryable=True)
            fence = lease.fence + 1 if lease else 1
            if lease:
                lease.holder, lease.fence, lease.expires_at = holder, fence, now + ttl_seconds
            else:
                session.add(
                    LeaseRow(
                        task_id=task_id, holder=holder, fence=fence, expires_at=now + ttl_seconds
                    )
                )
            self._replace(session, task, {"status": "running", "holder": holder, "fence": fence})
            result = {
                "task_id": task_id,
                "holder": holder,
                "fence": fence,
                "expires_at": now + ttl_seconds,
            }
            self._event(session, actor, op, "task.leased", task_id, result)
            return result

        return self._execute(
            actor,
            key,
            "task.acquire",
            {"task_id": task_id, "holder": holder, "ttl_seconds": ttl_seconds},
            action,
        )

    def _fenced(self, session, task_id, holder, fence):
        lease = session.scalar(
            select(LeaseRow).where(LeaseRow.task_id == task_id).with_for_update()
        )
        if (
            lease is None
            or lease.holder != holder
            or lease.fence != fence
            or lease.expires_at <= utcnow().timestamp()
        ):
            raise HarnessError(
                "STALE_LEASE",
                "The worker no longer holds the current execution lease.",
                remediation="Discard authoritative updates and let the current worker continue.",
            )
        return lease

    def renew_task(self, task_id, holder, fence, ttl_seconds, actor, key):
        controller_only(actor)
        if not 1 <= ttl_seconds <= 300:
            raise HarnessError("INVALID_LEASE", "Lease duration must be 1–300 seconds.", status=422)

        def action(session, op):
            task = self._get(session, "task", task_id, actor)
            self._active(session, task.payload["experiment_id"], actor)
            lease = self._fenced(session, task_id, holder, fence)
            lease.expires_at = utcnow().timestamp() + ttl_seconds
            return {"task_id": task_id, "fence": fence, "expires_at": lease.expires_at}

        return self._execute(
            actor,
            key,
            "task.renew",
            {"task_id": task_id, "holder": holder, "fence": fence, "ttl_seconds": ttl_seconds},
            action,
        )

    def renew_task_for_cleanup(
        self, task_id, holder, fence, worker_slot_id, ttl_seconds, actor, key
    ):
        """Extend a live lease while its holder closes its own VM.

        Unlike `renew_task`, a paused, cancelled or expired experiment or a cancelled task
        does not refuse this, so a slow final checkpoint and teardown can finish. It still
        needs the exact current holder, fence and worker slot, never revives an expired or
        replaced lease, never shortens one, and applies only while that holder has a ready
        workspace to close.
        """
        controller_only(actor)
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 300:
            raise HarnessError("INVALID_LEASE", "Lease duration must be 1–300 seconds.", status=422)

        def action(session, op):
            task = self._get(session, "task", task_id, actor)
            experiment = self._get(session, "experiment", task.payload["experiment_id"], actor)
            session.refresh(experiment, with_for_update=True)
            lease = self._fenced(session, task_id, holder, fence)
            if worker_slot_id:
                slot = session.scalar(
                    select(ReservationRow)
                    .where(ReservationRow.id == worker_slot_id)
                    .with_for_update()
                )
                if (
                    task.payload.get("worker_slot_id") != worker_slot_id
                    or slot is None
                    or slot.state != "active"
                    or slot.workers != 1
                    or slot.experiment_id != experiment.id
                ):
                    raise HarnessError(
                        "WORKER_SLOT_AUTHORITY",
                        "Shared worker slot requires the task's active controller reservation.",
                    )
            workspaces = session.scalars(
                select(RecordRow).where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.kind == "workspace",
                    record_json_text("experiment_id") == experiment.id,
                    record_json_text("task_id") == task_id,
                    record_json_text("status") == "ready",
                )
            )
            if not any(
                row.payload.get("holder") == holder
                and row.payload.get("fence") == fence
                and row.payload.get("shared_worker_slot_id") == worker_slot_id
                for row in workspaces
            ):
                raise HarnessError(
                    "CLEANUP_SCOPE", "This holder has no open workspace left to close."
                )
            lease.expires_at = max(lease.expires_at, utcnow().timestamp() + ttl_seconds)
            return {"task_id": task_id, "fence": fence, "expires_at": lease.expires_at}

        return self._execute(
            actor,
            key,
            "task.cleanup-renew",
            {
                "task_id": task_id,
                "holder": holder,
                "fence": fence,
                "worker_slot_id": worker_slot_id,
                "ttl_seconds": ttl_seconds,
            },
            action,
        )

    def finish_task(self, task_id, holder, fence, evidence_ids, status, actor, key):
        controller_only(actor)
        if status not in {"completed", "failed", "blocked"} or not evidence_ids:
            raise HarnessError(
                "COMPLETION_EVIDENCE_REQUIRED",
                "Completion needs evidence and an explicit outcome.",
                status=422,
            )

        def action(session, op):
            task = self._get(session, "task", task_id, actor)
            self._active(session, task.payload["experiment_id"], actor)
            lease = self._fenced(session, task_id, holder, fence)
            if status == "completed":
                pending = session.scalar(
                    select(RecordRow.id)
                    .where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "task",
                        RecordRow.payload["reply_to_parent_task_id"].as_string() == task_id,
                        RecordRow.payload["status"]
                        .as_string()
                        .not_in(["completed", "failed", "blocked"]),
                    )
                    .limit(1)
                )
                if pending:
                    raise HarnessError(
                        "JOINED_CHILDREN_PENDING", "Joined work must settle before task completion."
                    )
            output_summary = None
            for identifier in evidence_ids:
                artifact = self._get(session, "artifact", identifier, actor)
                if artifact.payload.get("experiment_id") != task.payload["experiment_id"]:
                    raise HarnessError(
                        "EVIDENCE_SCOPE", "Completion evidence belongs to another experiment."
                    )
                content = self.artifacts.get(artifact.payload["sha256"])
                if (
                    output_summary is None
                    and artifact.payload.get("artifact_kind") == "research_output"
                    and artifact.payload.get("branch_id") == task.payload["branch_id"]
                ):
                    output_summary = content.decode("utf-8", errors="replace")[:4000]
            self._fenced(session, task_id, holder, fence)
            result = self._replace(
                session,
                task,
                {
                    "status": status,
                    "evidence_ids": evidence_ids,
                    "execution_status": status,
                    "terminal_recovery": None,
                    "error_code": (
                        "RESEARCH_STAGNATION_EXHAUSTED"
                        if status == "blocked"
                        and task.payload.get("research_progress_status") == "recovery_exhausted"
                        else task.payload.get("error_code")
                    ),
                    "return_result": {
                        **(task.payload.get("return_result") or {}),
                        "execution_status": status,
                        "artifact_ids": list(
                            dict.fromkeys(
                                (task.payload.get("return_result") or {}).get("artifact_ids", [])
                                + evidence_ids
                            )
                        ),
                        "summary": (task.payload.get("return_result") or {}).get("summary")
                        or output_summary,
                        "execution_failure": (
                            (task.payload.get("return_result") or {}).get("execution_failure")
                            if status == "completed"
                            else {"status": status, "artifact_ids": evidence_ids}
                        ),
                        "evidence_status": (task.payload.get("return_result") or {}).get(
                            "evidence_status", "unverified"
                        ),
                    }
                    if task.payload.get("reply_to_parent_task_id")
                    else task.payload.get("return_result"),
                },
            )
            if (
                status == "blocked"
                and task.payload.get("research_progress_status") == "recovery_exhausted"
            ):
                branch = self._get(session, "branch", task.payload["branch_id"], actor)
                self._replace(
                    session,
                    branch,
                    {"status": "parked", "error_code": "RESEARCH_STAGNATION_EXHAUSTED"},
                )
            parent_task_id = task.payload.get("reply_to_parent_task_id")
            if parent_task_id:
                experiment = self._get(session, "experiment", task.payload["experiment_id"], actor)
                if experiment.payload.get("sharing") == "ideas":
                    parent = session.get(RecordRow, parent_task_id)
                    if (
                        parent is None
                        or parent.kind != "task"
                        or parent.project_id != actor.project_id
                        or parent.payload.get("experiment_id") != task.payload["experiment_id"]
                    ):
                        raise HarnessError("RETURN_RESULT_SCOPE", "Parent task binding changed.")
                    returned = result["return_result"]
                    visible_ids = self._recipient_visible_artifacts(
                        session,
                        returned.get("artifact_ids", []),
                        task.payload["experiment_id"],
                        parent.payload["branch_id"],
                        actor,
                        strict=False,
                    )
                    parent_result = copy.deepcopy(returned)
                    parent_result["artifact_ids"] = visible_ids
                    if len(visible_ids) != len(returned.get("artifact_ids", [])):
                        parent_result["attachments_omitted_for_recipient"] = True
                    failure = parent_result.get("execution_failure")
                    if isinstance(failure, dict) and "artifact_ids" in failure:
                        failure["artifact_ids"] = [
                            identifier
                            for identifier in failure["artifact_ids"]
                            if identifier in visible_ids
                        ]
                    notice = self._insert(
                        session,
                        "message",
                        actor,
                        {
                            "experiment_id": task.payload["experiment_id"],
                            "sender_branch_id": task.payload["branch_id"],
                            "branch_id": task.payload["branch_id"],
                            "recipient_branch_id": parent.payload["branch_id"],
                            "reply_to_parent_task_id": parent_task_id,
                            "child_task_id": task_id,
                            "attributed_to": returned.get("attributed_to", holder),
                            "content": canonical_json(parent_result),
                            "artifact_ids": visible_ids,
                            "evidence_status": "attributed_idea",
                        },
                    )
                    self._inbox_event_lock(session, task.payload["experiment_id"])
                    self._event(
                        session,
                        actor,
                        op,
                        "message.created",
                        parent.payload["branch_id"],
                        {"message_id": notice["id"], "child_task_id": task_id},
                    )
            lease.expires_at = 0
            self._event(
                session,
                actor,
                op,
                f"task.{status}",
                task_id,
                {"experiment_id": task.payload["experiment_id"], "evidence_ids": evidence_ids},
                dispatch=True,
            )
            return result

        return self._execute(
            actor,
            key,
            "task.finish",
            {
                "task_id": task_id,
                "holder": holder,
                "fence": fence,
                "evidence_ids": evidence_ids,
                "status": status,
            },
            action,
        )

    def return_result(
        self,
        task_id,
        evidence_status,
        artifact_ids,
        unresolved_obligations,
        execution_failure,
        actor,
        key,
        *,
        summary=None,
    ):
        """Record a typed child finding; parent visibility follows sharing policy."""
        self._research_role(actor)
        binding = current_worker_effects.get()
        if (
            actor.role != "agent"
            or binding is None
            or binding.task_id != task_id
            or evidence_status not in {"unverified", "rejected", "unknown"}
            or len(artifact_ids) > 100
            or len(set(artifact_ids)) != len(artifact_ids)
            or len(unresolved_obligations) > 100
            or any(not isinstance(item, str) or len(item) > 2000 for item in unresolved_obligations)
            or (summary is not None and (not isinstance(summary, str) or len(summary) > 8192))
            or (
                execution_failure is not None
                and (
                    not isinstance(execution_failure, dict)
                    or set(execution_failure) - {"code", "message"}
                    or not isinstance(execution_failure.get("code"), str)
                    or len(execution_failure["code"]) > 100
                    or not isinstance(execution_failure.get("message", ""), str)
                    or len(execution_failure.get("message", "")) > 1000
                )
            )
        ):
            raise HarnessError(
                "RETURN_RESULT_INVALID", "A current child needs a bounded typed result."
            )

        def action(session, op):
            task = self._get(session, "task", task_id, actor)
            self._fenced(session, task_id, binding.holder, binding.fence)
            if task.payload.get("branch_id") != actor.branch_id or not task.payload.get(
                "reply_to_parent_task_id"
            ):
                raise HarnessError(
                    "RETURN_RESULT_SCOPE", "Only joined child work returns to a parent."
                )
            for identifier in artifact_ids:
                artifact = self._get(session, "artifact", identifier, actor)
                if artifact.payload.get("experiment_id") != task.payload["experiment_id"]:
                    raise HarnessError(
                        "EVIDENCE_SCOPE", "Result artifact is outside the experiment."
                    )
            result = {
                "evidence_status": evidence_status,
                "artifact_ids": artifact_ids,
                "unresolved_obligations": unresolved_obligations,
                "summary": summary,
                "execution_failure": execution_failure,
                "execution_status": "running",
                "attributed_to": actor.id,
                "task_id": task_id,
            }
            self._replace(session, task, {"return_result": result})
            self._event(
                session,
                actor,
                op,
                "task.result_recorded",
                task_id,
                {
                    "parent_task_id": task.payload["reply_to_parent_task_id"],
                    "evidence_status": evidence_status,
                },
            )
            return result

        return self._execute(
            actor,
            key,
            "task.return-result",
            {
                "task_id": task_id,
                "evidence_status": evidence_status,
                "artifact_ids": artifact_ids,
                "unresolved_obligations": unresolved_obligations,
                "summary": summary,
                "execution_failure": execution_failure,
            },
            action,
        )

    @staticmethod
    def _message_text(content):
        if not content.strip() or len(content) > 20000:
            raise HarnessError(
                "INVALID_MESSAGE", "Messages require 1–20,000 characters.", status=422
            )

    @staticmethod
    def _lab_route(experiment, sender, recipient):
        """Society direct messages stay in a lab or parent/child pair unless policy opens them."""
        policy = experiment.payload.get("society")
        if not policy or policy.get("cross_lab_direct_messages") or sender.id == recipient.id:
            return
        lab = sender.payload.get("lab")
        if lab is not None and recipient.payload.get("lab") == lab:
            return
        if sender.id == recipient.payload.get("parent_id") or recipient.id == sender.payload.get(
            "parent_id"
        ):
            return
        raise HarnessError(
            "CROSS_LAB_MESSAGE",
            "Direct messages reach only your lab and your parent or child branches.",
            status=403,
            remediation=(
                "Post on the relevant commons node; cross-lab discourse goes through the commons."
            ),
        )

    def _deliver_message(
        self, session, op, actor, experiment, sender, recipient_id, content, artifact_ids, extra
    ):
        """Insert one routed message and its event; shared by direct and lab sends."""
        # Recipient routing is not permission to read the recipient's private branch record.
        recipient = session.get(RecordRow, recipient_id)
        if not recipient or recipient.kind != "branch" or recipient.project_id != actor.project_id:
            raise HarnessError("NOT_FOUND", "Recipient branch was not found.", status=404)
        experiment_id = sender.payload["experiment_id"]
        if recipient.payload["experiment_id"] != experiment_id:
            raise HarnessError(
                "MAILBOX_SCOPE", "Branches must share an experiment to exchange messages."
            )
        self._guard_referee_recipient(sender, recipient)
        self._lab_route(experiment, sender, recipient)
        self._recipient_visible_artifacts(
            session, artifact_ids, experiment_id, recipient_id, actor, strict=True
        )
        record = self._insert(
            session,
            "message",
            actor,
            {
                "experiment_id": experiment_id,
                "sender_branch_id": sender.id,
                "branch_id": sender.id,
                "recipient_branch_id": recipient_id,
                "attributed_to": actor.id,
                "content": content,
                "artifact_ids": artifact_ids,
                "evidence_status": "attributed_idea",
                **extra,
            },
        )
        self._inbox_event_lock(session, experiment_id)
        self._event(
            session, actor, op, "message.created", recipient_id, {"message_id": record["id"]}
        )
        return record

    def send_message(self, branch_id, recipient_id, content, artifact_ids, actor, key):
        self._research_role(actor)
        self._message_text(content)

        def action(session, op):
            sender = self._writable_branch(session, branch_id, actor)
            experiment = self._get(session, "experiment", sender.payload["experiment_id"], actor)
            if branch_id != recipient_id and experiment.payload.get("sharing", "none") != "ideas":
                raise HarnessError(
                    "SHARING_POLICY",
                    "Cross-branch free-text messages require ideas sharing.",
                    status=403,
                )
            return self._deliver_message(
                session, op, actor, experiment, sender, recipient_id, content, artifact_ids, {}
            )

        return self._execute(
            actor,
            key,
            "message.send",
            {
                "branch_id": branch_id,
                "recipient_id": recipient_id,
                "content": content,
                "artifact_ids": artifact_ids,
            },
            action,
        )

    def send_lab_message(self, branch_id, content, artifact_ids, actor, key):
        """Fan one attributed message out to every other member of the sender's lab."""
        self._research_role(actor)
        self._message_text(content)

        def action(session, op):
            sender = self._writable_branch(session, branch_id, actor)
            experiment = self._commons_experiment(
                session, sender.payload["experiment_id"], actor, active=False
            )
            lab = sender.payload.get("lab")
            if lab is None:
                raise HarnessError(
                    "LAB_NOT_FOUND",
                    "This branch belongs to no lab.",
                    status=404,
                    remediation="Message your parent directly or post on a commons node.",
                )
            # Membership is capped at lab_size_max, which bounds the fan-out.
            recipients = session.scalars(
                select(RecordRow.id)
                .where(*self._lab_filter(experiment, lab), RecordRow.id != branch_id)
                .order_by(record_json_text("created_at"), RecordRow.id)
                .limit(experiment.payload["society"]["lab_size_max"])
            ).all()
            if not recipients:
                raise HarnessError(
                    "LAB_EMPTY",
                    "The lab has no other members.",
                    remediation="Recruit a lab member or post on a commons node.",
                )
            records = [
                self._deliver_message(
                    session,
                    op,
                    actor,
                    experiment,
                    sender,
                    recipient,
                    content,
                    artifact_ids,
                    {"lab": lab, "delivery_key": f"{key}:{recipient}"},
                )
                for recipient in recipients
            ]
            return {"lab": lab, "message_ids": [record["id"] for record in records]}

        return self._execute(
            actor,
            key,
            "message.lab-send",
            {
                "branch_id": branch_id,
                "content": content,
                "artifact_ids": artifact_ids,
            },
            action,
        )

    def restart_brief(self, branch_id, actor):
        branch = self.get_record("branch", branch_id, actor)
        experiment = self.get_record("experiment", branch["experiment_id"], actor)
        problem = self.get_record("problem", experiment["problem_id"], actor)
        claims = self.list_records("claim", actor, experiment["id"])
        tasks = self.list_records("task", actor, experiment["id"])
        receipts = self.list_records("verification", actor, experiment["id"])
        return {
            "format": "physharness.restart.v1",
            "branch": branch,
            "target": problem,
            "assumptions": problem["assumptions"],
            "claims_with_evidence_status": claims,
            "verification_receipts": receipts,
            "open_obligations": [t for t in tasks if t["status"] != "completed"],
            "completed_tasks": [t for t in tasks if t["status"] == "completed"],
            "artifacts": self.list_records("artifact", actor, experiment["id"]),
            "messages": self.list_records("message", actor, experiment["id"]),
            "history_retained": True,
            "novelty": "unreviewed",
        }

    def checkpoint_branch(
        self,
        branch_id,
        expected_revision,
        approach,
        workspace_digest,
        environment_digest,
        native_artifact_id,
        actor,
        key,
    ):
        self._research_role(actor)

        def action(session, op):
            branch = self._writable_branch(session, branch_id, actor)
            reader = Principal(
                id=actor.id,
                project_id=actor.project_id,
                role="agent",
                experiment_id=branch.payload["experiment_id"],
                branch_id=branch_id,
            )
            brief = self.restart_brief(branch_id, reader)
            if environment_digest != brief["target"]["environment_digest"]:
                raise HarnessError(
                    "ENVIRONMENT_MISMATCH",
                    "Checkpoint environment differs from the experiment target.",
                )
            if native_artifact_id:
                native = self.get_record("artifact", native_artifact_id, reader)
                if native.get("experiment_id") != brief["branch"]["experiment_id"]:
                    raise HarnessError(
                        "CHECKPOINT_MISMATCH", "Native state belongs to another experiment."
                    )
            payload = {
                "brief": brief,
                "approach": approach,
                "workspace_digest": workspace_digest,
                "environment_digest": environment_digest,
                "native_artifact_id": native_artifact_id,
            }
            # Later records remain retrievable from the canonical event log.
            content_hash = self.artifacts.put(canonical_json(payload).encode())
            branch = self._writable_branch(session, branch_id, actor)
            artifact = self._insert(
                session,
                "artifact",
                actor,
                {
                    "experiment_id": branch.payload["experiment_id"],
                    "branch_id": branch_id,
                    "artifact_kind": "checkpoint",
                    "sha256": content_hash,
                    "media_type": "application/json",
                    "submitted_by": actor.id,
                    "size_bytes": len(canonical_json(payload).encode()),
                    "provenance": {"branch_id": branch_id, "revision": expected_revision},
                },
            )
            result = self._replace(
                session, branch, {"checkpoint_id": artifact["id"]}, expected_revision
            )
            self._event(
                session,
                actor,
                op,
                "branch.checkpointed",
                branch_id,
                {"checkpoint_id": artifact["id"]},
            )
            return result

        return self._execute(
            actor,
            key,
            "branch.checkpoint",
            {
                "branch_id": branch_id,
                "revision": expected_revision,
                "approach": approach,
                "workspace_digest": workspace_digest,
                "environment_digest": environment_digest,
                "native_artifact_id": native_artifact_id,
            },
            action,
        )
