"""Durable delegation, fenced completion, mailboxes and evidence-preserving restart briefs."""

from sqlalchemy import select

from .domain import Principal, TaskCreate, canonical_json, utcnow
from .errors import HarnessError
from .storage import EdgeRow, LeaseRow, RecordRow
from .worker_authority import current_worker_effects


def controller_only(actor):
    if actor.role not in {"operator", "admin"}:
        raise HarnessError(
            "FORBIDDEN", "This identity does not have the controller capability.", status=403
        )


class CollaborationMixin:
    def create_task(self, request: TaskCreate, actor: Principal, key: str) -> dict:
        self._research_role(actor)
        data = request.model_dump(mode="json")
        binding = current_worker_effects.get()
        delegated_from_task_id = binding.task_id if actor.role == "agent" and binding else None
        if delegated_from_task_id:
            data["delegated_from_task_id"] = delegated_from_task_id

        def action(session, op):
            branch = self._writable_branch(session, request.branch_id, actor, delegation=True)
            experiment_id = branch.payload["experiment_id"]
            self._active(session, experiment_id, actor)
            if len(set(request.dependency_ids)) != len(request.dependency_ids):
                raise HarnessError(
                    "DUPLICATE_DEPENDENCY", "Task dependencies must be unique.", status=422
                )
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
            for identifier in evidence_ids:
                artifact = self._get(session, "artifact", identifier, actor)
                if artifact.payload.get("experiment_id") != task.payload["experiment_id"]:
                    raise HarnessError(
                        "EVIDENCE_SCOPE", "Completion evidence belongs to another experiment."
                    )
                self.artifacts.get(artifact.payload["sha256"])
            self._fenced(session, task_id, holder, fence)
            result = self._replace(session, task, {"status": status, "evidence_ids": evidence_ids})
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

    def send_message(self, branch_id, recipient_id, content, artifact_ids, actor, key):
        self._research_role(actor)
        if not content.strip() or len(content) > 20000:
            raise HarnessError(
                "INVALID_MESSAGE", "Messages require 1–20,000 characters.", status=422
            )

        def action(session, op):
            sender = self._writable_branch(session, branch_id, actor)
            experiment = self._get(session, "experiment", sender.payload["experiment_id"], actor)
            if branch_id != recipient_id and experiment.payload.get("sharing", "none") != "ideas":
                raise HarnessError(
                    "SHARING_POLICY",
                    "Cross-branch free-text messages require ideas sharing.",
                    status=403,
                )
            # Recipient routing is not permission to read the recipient's private branch record.
            recipient = session.get(RecordRow, recipient_id)
            if (
                not recipient
                or recipient.kind != "branch"
                or recipient.project_id != actor.project_id
            ):
                raise HarnessError("NOT_FOUND", "Recipient branch was not found.", status=404)
            experiment_id = sender.payload["experiment_id"]
            if recipient.payload["experiment_id"] != experiment_id:
                raise HarnessError(
                    "MAILBOX_SCOPE", "Branches must share an experiment to exchange messages."
                )
            for identifier in artifact_ids:
                evidence = self._get(session, "artifact", identifier, actor)
                if evidence.payload.get("experiment_id") != experiment_id:
                    raise HarnessError(
                        "EVIDENCE_SCOPE", "Message evidence belongs to another experiment."
                    )
            record = self._insert(
                session,
                "message",
                actor,
                {
                    "experiment_id": experiment_id,
                    "sender_branch_id": branch_id,
                    "branch_id": branch_id,
                    "recipient_branch_id": recipient_id,
                    "attributed_to": actor.id,
                    "content": content,
                    "artifact_ids": artifact_ids,
                    "evidence_status": "attributed_idea",
                },
            )
            self._event(
                session, actor, op, "message.created", recipient_id, {"message_id": record["id"]}
            )
            return record

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
