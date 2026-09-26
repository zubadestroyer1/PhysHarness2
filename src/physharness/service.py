"""Application authority: actors, immutable targets, commands, and budget invariants."""

import copy
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from .acceptance import AcceptanceMixin
from .artifacts import ArtifactStore
from .collaboration import CollaborationMixin
from .commons import CommonsMixin
from .commons_discourse import CommonsDiscourseMixin
from .commons_review import CommonsReviewMixin
from .continuation import ContinuationMixin
from .discussion import DiscussionMixin
from .domain import (
    ArtifactCreate,
    BranchCreate,
    CampaignCreate,
    ExperimentCreate,
    Principal,
    ProblemCreate,
    digest_json,
    make_record,
    new_id,
    utcnow,
)
from .errors import HarnessError
from .research import ResearchMixin
from .storage import (
    BudgetRow,
    CommandRow,
    Database,
    EdgeRow,
    EventRow,
    OutboxRow,
    RecordRow,
    ReservationRow,
    record_json_text,
)
from .worker_authority import current_worker_effects
from .workforce import WorkforceMixin

log = logging.getLogger(__name__)
MICRO_USD = Decimal(1_000_000)


def money_units(value: str | Decimal) -> int:
    try:
        amount = Decimal(value)
        scaled = amount * MICRO_USD
        if not amount.is_finite() or amount < 0 or scaled != scaled.to_integral_value():
            raise ValueError("nonnegative exact micro-USD amount required")
        if scaled > 9_000_000_000_000_000:
            raise ValueError("amount exceeds accounting range")
        return int(scaled)
    except (ValueError, InvalidOperation, TypeError) as error:
        raise HarnessError(
            "INVALID_RESOURCE_AMOUNT",
            "Use a nonnegative USD amount with at most six decimals.",
            status=422,
        ) from error


def money_string(units: int) -> str:
    return format(Decimal(units) / MICRO_USD, "f")


def scan_cursor(after: str) -> tuple[str | None, int] | None:
    """Split a page cursor into its last returned record ID and unseen rows skipped after it."""
    anchor, mark, skipped = after.rpartition("+")
    if not mark:
        return after, 0
    if len(skipped) != 9 or not skipped.isascii() or not skipped.isdigit() or not int(skipped):
        return None
    return anchor or None, int(skipped)


def next_cursor(anchor: str | None, skipped: int) -> str | None:
    # A cursor names only a record its reader received; rows hidden from that reader are
    # a count, so paging never discloses their IDs. "+" sorts below ID characters and the
    # padded count keeps successive cursors increasing.
    return f"{anchor or ''}+{skipped:09d}" if skipped else anchor


def require_role(actor: Principal, *roles: str) -> None:
    if actor.role not in roles and actor.role != "admin":
        raise HarnessError(
            "FORBIDDEN",
            "This identity does not have the required capability.",
            status=403,
            remediation="Use an identity assigned the required project role.",
        )


# Record kinds a society experiment's export adds; the commons edges are exported beside them.
SOCIETY_EXPORT_KINDS = ("commons_node", "commons_claim", "commons_review", "literature_fetch")


class HarnessService(
    AcceptanceMixin,
    CollaborationMixin,
    CommonsDiscourseMixin,
    CommonsMixin,
    CommonsReviewMixin,
    ContinuationMixin,
    DiscussionMixin,
    ResearchMixin,
    WorkforceMixin,
):
    _digest = staticmethod(digest_json)

    def submit_candidate_source(self, experiment_id, source, actor, key):
        """Store exact candidate bytes, then idempotently queue independent checking."""
        artifact = self.create_artifact(
            ArtifactCreate(
                experiment_id=experiment_id,
                kind="lean_source",
                content=source,
                provenance={"branch_id": actor.branch_id} if actor.branch_id else {},
            ),
            actor,
            f"{key}:source",
        )
        receipt = self.verify_candidate(
            experiment_id, artifact["id"], True, actor, f"{key}:verification"
        )
        return {
            "artifact_id": artifact["id"],
            "candidate_sha256": artifact["sha256"],
            "receipt_id": receipt["id"],
            "status": receipt["status"],
        }

    @staticmethod
    def _research_role(actor):
        require_role(actor, "researcher", "operator", "agent")

    _private_artifact_kinds = frozenset(
        {
            "checkpoint",
            "checkpoint_chunk",
            "native_checkpoint",
            "native_checkpoint_chunk",
            "native_archive",
            "runtime_event",
            "execution_failure",
            "workspace_recovery_observation",
            "masked_reference",
            "literature_screen",
        }
    )

    def _accepted_evidence(self, session, row, experiment, assurances):
        """Require a canonical receipt bound to the exact reviewed target."""
        if row.kind == "artifact":
            target = session.get(RecordRow, experiment.payload["problem_id"])
            if (
                target is None
                or target.kind != "problem"
                or target.project_id != row.project_id
                or target.payload.get("semantic_review") != "approved"
                or target.payload.get("target_digest") != experiment.payload.get("target_digest")
                or row.payload.get("experiment_id") != experiment.id
            ):
                return False
            expected = {
                "artifact_id": row.id,
                "status": "verified",
                "experiment_id": experiment.id,
                "review_id": target.payload.get("review_id"),
                "target_theorem": target.payload.get("target_theorem", "target"),
                "challenge_sha256": hashlib.sha256(
                    target.payload["formal_statement"].encode("utf-8")
                ).hexdigest(),
                "problem_revision_id": target.id,
                "target_digest": target.payload.get("target_digest"),
                "environment_digest": target.payload.get("environment_digest"),
                "candidate_sha256": row.payload.get("sha256"),
            }
            if len(assurances) == 1:
                expected["assurance"] = next(iter(assurances))
            query = select(RecordRow).where(
                RecordRow.project_id == row.project_id,
                RecordRow.kind == "verification",
                *(record_json_text(field) == value for field, value in expected.items()),
            )
            if len(assurances) > 1:
                query = query.where(record_json_text("assurance").in_(assurances))
            receipts = session.scalars(query.limit(1))
            return any(
                self._accepted_evidence(session, r, experiment, assurances) for r in receipts
            )
        if row.kind == "claim":
            receipt = session.get(RecordRow, row.payload.get("verification_id", ""))
            return bool(
                receipt
                and row.payload.get("proof_status") == "verified"
                and receipt.payload.get("claim_id") == row.id
                and self._accepted_evidence(session, receipt, experiment, assurances)
            )
        if row.kind != "verification":
            return False
        data = row.payload
        target = session.get(RecordRow, experiment.payload["problem_id"])
        artifact = session.get(RecordRow, data.get("artifact_id", ""))
        return bool(
            data.get("status") == "verified"
            and data.get("assurance") in assurances
            and data.get("experiment_id") == experiment.id
            and target
            and target.project_id == row.project_id
            and target.kind == "problem"
            and target.payload.get("semantic_review") == "approved"
            and data.get("review_id") == target.payload.get("review_id")
            and data.get("target_theorem") == target.payload.get("target_theorem", "target")
            and data.get("challenge_sha256")
            == hashlib.sha256(target.payload["formal_statement"].encode("utf-8")).hexdigest()
            and data.get("problem_revision_id") == target.id
            and data.get("target_digest")
            == target.payload.get("target_digest")
            == experiment.payload.get("target_digest")
            and data.get("environment_digest") == target.payload.get("environment_digest")
            and artifact
            and artifact.project_id == row.project_id
            and artifact.kind == "artifact"
            and artifact.payload.get("experiment_id") == experiment.id
            and data.get("candidate_sha256") == artifact.payload.get("sha256")
        )

    def _accepted_for_sharing(self, session, row, experiment):
        """Only independent kernel receipts may cross branch boundaries."""
        return self._accepted_evidence(session, row, experiment, {"independent_kernel"})

    def _in_scope(self, session, row, actor):
        if row.kind == "discussion_withdrawal":
            return actor.role in {"operator", "admin"} and row.project_id == actor.project_id
        if actor.role != "agent":
            return True
        experiment = session.get(RecordRow, actor.experiment_id)
        if not experiment or experiment.project_id != actor.project_id:
            return False
        if actor.branch_id:
            branch = session.get(RecordRow, actor.branch_id)
            if (
                not branch
                or branch.kind != "branch"
                or branch.project_id != actor.project_id
                or branch.payload.get("experiment_id") != actor.experiment_id
            ):
                return False
        if row.kind == "experiment":
            return row.id == actor.experiment_id
        if row.kind in {"problem", "campaign"}:
            return row.id == experiment.payload[f"{row.kind}_id"]
        if row.kind == "review":
            target = session.get(RecordRow, experiment.payload["problem_id"])
            return bool(
                target
                and target.project_id == actor.project_id
                and target.payload.get("review_id") == row.id
                and row.payload.get("problem_id") == target.id
                and row.payload.get("target_digest") == target.payload.get("target_digest")
            )
        if row.payload.get("experiment_id") != actor.experiment_id:
            return False
        if row.kind == "message" and row.payload.get("recipient_branch_id") == actor.branch_id:
            for identifier in row.payload.get("artifact_ids", []):
                artifact = session.get(RecordRow, identifier)
                if (
                    not artifact
                    or artifact.kind != "artifact"
                    or artifact.project_id != actor.project_id
                    or not self._in_scope(session, artifact, actor)
                ):
                    return False
        # Reader state and capacity policy are never social permissions. Branch
        # successors share their inbox; another branch cannot inspect it.
        if row.kind in {"discussion_reader", "discussion_subscription", "discussion_delivery"}:
            key = f"branch:{actor.branch_id}" if actor.branch_id else None
            if not key or row.payload.get("reader_key") != key:
                return False
            if row.kind == "discussion_delivery":
                for item in row.payload.get("items", []):
                    if item.get("source_kind") == "withdrawal":
                        continue
                    source = session.get(RecordRow, item.get("id"))
                    if item.get("source_kind") == "message":
                        if (
                            not source
                            or source.kind != "message"
                            or source.payload.get("recipient_branch_id") != actor.branch_id
                            or not self._in_scope(session, source, actor)
                        ):
                            return False
                    elif (
                        item.get("source_kind") != "discussion_post"
                        or not source
                        or source.kind != "discussion_post"
                        or not self._in_scope(session, source, actor)
                    ):
                        return False
            return True
        if row.kind in {
            "workforce_policy",
            "workforce_profile",
            "workforce_team",
            "workforce_capacity_request",
        }:
            return row.payload.get("branch_id") == actor.branch_id and bool(actor.branch_id)
        if row.kind in {"discussion_topic", "discussion_post"}:
            target = session.get(RecordRow, experiment.payload["problem_id"])
            if not target or any(
                (
                    row.payload.get("problem_revision_id") != target.id,
                    row.payload.get("target_digest") != experiment.payload.get("target_digest"),
                    row.payload.get("environment_digest")
                    != target.payload.get("environment_digest"),
                )
            ):
                return False
            if row.kind == "discussion_post":
                topic = session.get(RecordRow, row.payload.get("topic_id"))
                if (
                    not topic
                    or topic.kind != "discussion_topic"
                    or topic.project_id != actor.project_id
                    or topic.payload.get("experiment_id") != actor.experiment_id
                    or topic.payload.get("problem_revision_id") != target.id
                    or topic.payload.get("target_digest") != experiment.payload.get("target_digest")
                    or topic.payload.get("environment_digest")
                    != target.payload.get("environment_digest")
                ):
                    return False
            if (
                row.payload.get("branch_id") != actor.branch_id
                and experiment.payload.get("sharing") != "ideas"
            ):
                return False
            if row.kind == "discussion_post":
                for identifier in row.payload.get("artifact_ids", []):
                    artifact = session.get(RecordRow, identifier)
                    if (
                        not artifact
                        or artifact.kind != "artifact"
                        or artifact.project_id != actor.project_id
                        or not self._in_scope(session, artifact, actor)
                    ):
                        return False
                for identifier in row.payload.get("reference_post_ids", []):
                    reference = session.get(RecordRow, identifier)
                    if (
                        not reference
                        or reference.kind != "discussion_post"
                        or reference.project_id != actor.project_id
                        or reference.payload.get("experiment_id") != actor.experiment_id
                        or (
                            reference.payload.get("branch_id") != actor.branch_id
                            and experiment.payload.get("sharing") != "ideas"
                        )
                    ):
                        return False
            return True
        if row.kind in {"commons_node", "commons_claim", "commons_review"}:
            # The commons is an ideas-sharing grant to the whole experiment, not authorship.
            return experiment.payload.get("sharing") == "ideas"
        if row.kind in {"session", "model_reservation", "continuation_link"} or (
            row.kind == "artifact"
            and row.payload.get("artifact_kind") in self._private_artifact_kinds - {"checkpoint"}
        ):
            return False
        owner = row.id if row.kind == "branch" else row.payload.get("branch_id")
        if owner and owner == actor.branch_id:
            return True
        # Legacy experiment-only identities retain their own submissions, never a group's history.
        if not actor.branch_id and row.payload.get("origin_actor_id") == actor.id:
            return True
        if row.payload.get("trusted_input") is True:
            return True
        if actor.agent_orchestrator and row.kind in {"branch", "task"}:
            return True
        # A parent may schedule its newly created child, but receives no child result access.
        if (
            row.kind == "branch"
            and actor.branch_id
            and row.payload.get("parent_id") == actor.branch_id
        ):
            return True
        if row.kind == "artifact" and row.payload.get("artifact_kind") == "checkpoint":
            return False
        sharing = experiment.payload.get("sharing", "none")
        if sharing == "none" or not actor.branch_id:
            return False
        if row.kind == "message":
            return sharing == "ideas" and actor.branch_id == row.payload.get("recipient_branch_id")
        if sharing == "ideas" and owner and row.payload.get("origin_actor_id"):
            return row.kind in {"artifact", "claim", "source", "program"}
        return self._accepted_for_sharing(session, row, experiment)

    def _writable_branch(self, session, branch_id, actor, *, delegation=False):
        branch = self._get(session, "branch", branch_id, actor)
        if delegation:
            self._guard_referee_branch(branch, actor)
        if actor.role == "agent" and not actor.agent_orchestrator:
            own = actor.branch_id == branch_id
            legacy = not actor.branch_id and branch.payload.get("origin_actor_id") == actor.id
            child = (
                delegation
                and actor.branch_id
                and branch.payload.get("parent_id") == actor.branch_id
            )
            if not (own or legacy or child):
                raise HarnessError(
                    "BRANCH_AUTHORITY", "The identity cannot write another branch.", status=403
                )
        return branch

    def __init__(self, db: Database, artifacts: ArtifactStore, verifier=None):
        self.db, self.artifacts, self.verifier = db, artifacts, verifier

    def _get(self, session: Session, kind: str, identifier: str, actor: Principal) -> RecordRow:
        row = session.get(RecordRow, identifier)
        if (
            row is None
            or row.project_id != actor.project_id
            or row.kind != kind
            or not self._in_scope(session, row, actor)
        ):
            raise HarnessError(
                "NOT_FOUND", "The requested project object was not found.", status=404
            )
        return row

    def get_record(self, kind: str, identifier: str, actor: Principal) -> dict:
        with self.db.sessions() as session:
            return copy.deepcopy(self._get(session, kind, identifier, actor).payload)

    def page_records(self, kind, actor, experiment_id=None, limit=500, after=None):
        if not 1 <= limit <= 5000:
            raise HarnessError("INVALID_PAGE_SIZE", "Page size must be 1–5000.", status=422)
        with self.db.sessions() as session:
            query = select(RecordRow).where(
                RecordRow.project_id == actor.project_id, RecordRow.kind == kind
            )
            if experiment_id:
                self._get(session, "experiment", experiment_id, actor)
                query = query.where(record_json_text("experiment_id") == experiment_id)
            if actor.role == "agent":
                experiment = session.get(RecordRow, actor.experiment_id)
                if not experiment or experiment.project_id != actor.project_id:
                    return {"items": [], "next_cursor": None}
                # SQLAlchemy's identity map holds weak references. Retain the common
                # branch explicitly so row authorization does not reload it per record.
                _scope_branch = session.get(RecordRow, actor.branch_id) if actor.branch_id else None
                _scope_target = session.get(RecordRow, experiment.payload["problem_id"])
                if kind in {"experiment", "problem", "campaign"}:
                    identifier = (
                        experiment.id if kind == "experiment" else experiment.payload[f"{kind}_id"]
                    )
                    query = query.where(RecordRow.id == identifier)
                elif kind == "review":
                    query = query.where(
                        record_json_text("problem_id") == experiment.payload["problem_id"]
                    )
                else:
                    query = query.where(record_json_text("experiment_id") == actor.experiment_id)
            anchor, skipped = None, 0
            if after:
                position = scan_cursor(after)
                if position is None:
                    raise HarnessError("INVALID_CURSOR", "Page cursor is malformed.", status=422)
                anchor, skipped = position
            if anchor:
                query = query.where(RecordRow.id > anchor)
            # Limit scanned metadata, not just visible output. The unexamined lookahead
            # proves continuation without authorizing or exposing that row's contents.
            scan_limit = max(100, limit)
            chunk = list(
                session.scalars(
                    query.order_by(RecordRow.id).offset(skipped or None).limit(scan_limit + 1)
                )
            )
            visible, scanned = [], 0
            for row in chunk[:scan_limit]:
                scanned += 1
                if self._in_scope(session, row, actor):
                    visible.append(row)
                    anchor, skipped = row.id, 0
                    if len(visible) == limit:
                        break
                else:
                    skipped += 1
            return {
                "items": [copy.deepcopy(r.payload) for r in visible],
                "next_cursor": next_cursor(anchor, skipped) if scanned < len(chunk) else None,
            }

    def list_records(self, kind, actor, experiment_id=None, limit=500):
        """Internal complete metadata read. Public callers should use bounded keyset pages."""
        items, cursor = [], None
        while True:
            page = self.page_records(kind, actor, experiment_id, limit, cursor)
            items.extend(page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                return items

    def _insert(
        self,
        session: Session,
        kind: str,
        actor: Principal,
        data: dict,
        *,
        record_id: str | None = None,
    ) -> dict:
        data = dict(data)
        data["origin_actor_id"] = actor.id
        experiment_id = data.get("experiment_id")
        if experiment_id:
            declared = data.get("branch_id")
            provenance = data.get("provenance") or {}
            hinted = provenance.get("branch_id")
            if declared and hinted and declared != hinted:
                raise HarnessError(
                    "BRANCH_AUTHORITY", "Conflicting branch attribution.", status=403
                )
            branch_id = declared or hinted
            if actor.role == "agent" and kind not in {"branch", "task"}:
                if branch_id and branch_id != actor.branch_id:
                    raise HarnessError(
                        "BRANCH_AUTHORITY", "Branch attribution cannot be forged.", status=403
                    )
                branch_id = actor.branch_id
            # Controller-written receipts, claims, sessions, and runtime artifacts retain
            # the canonical branch of their task or source. Free-form provenance is not authority.
            linked = None
            for field, reference_kind in (
                ("task_id", "task"),
                ("artifact_id", "artifact"),
                ("source_artifact_id", "artifact"),
                ("verification_id", "verification"),
            ):
                identifier = data.get(field) or (
                    provenance.get(field) if field == "task_id" else None
                )
                if identifier:
                    reference = self._get(session, reference_kind, identifier, actor)
                    if reference.payload.get("experiment_id") != experiment_id:
                        raise HarnessError(
                            "RECORD_SCOPE", "Linked evidence belongs to another experiment."
                        )
                    linked = reference
                    reference_branch = reference.payload.get("branch_id")
                    if (
                        actor.role != "agent"
                        and branch_id
                        and reference_branch
                        and branch_id != reference_branch
                    ):
                        raise HarnessError(
                            "BRANCH_AUTHORITY", "Linked record branch does not match."
                        )
                    if actor.role != "agent" and not branch_id:
                        branch_id = reference_branch
            if branch_id:
                branch = self._get(session, "branch", branch_id, actor)
                if branch.payload.get("experiment_id") != experiment_id:
                    raise HarnessError("BRANCH_AUTHORITY", "Branch belongs to another experiment.")
            if kind != "branch":
                data["branch_id"] = branch_id
            if actor.role == "agent" and data.get("trusted_input"):
                raise HarnessError(
                    "TRUSTED_INPUT_AUTHORITY",
                    "Only a trusted input supplier may mark inputs.",
                    status=403,
                )
            if kind == "source" and linked and linked.payload.get("trusted_input"):
                data["trusted_input"] = True
        record = make_record(kind, actor, data)
        if record_id:
            # A caller that derives payload fields from the new id reserves it first.
            record["id"] = record_id
        session.add(
            RecordRow(
                id=record["id"], project_id=actor.project_id, kind=kind, revision=1, payload=record
            )
        )
        session.flush()
        return record

    def _replace(
        self, session: Session, row: RecordRow, values: dict, expected_revision: int | None = None
    ) -> dict:
        expected = row.revision if expected_revision is None else expected_revision
        if row.revision != expected:
            raise HarnessError(
                "REVISION_CONFLICT",
                "The object changed since it was read.",
                details={"expected": expected, "actual": row.revision},
                remediation="Reload the object and review the change before retrying.",
            )
        replacement = {**row.payload, **values, "revision": expected + 1}
        result = session.execute(
            update(RecordRow)
            .where(RecordRow.id == row.id, RecordRow.revision == expected)
            .values(revision=expected + 1, payload=replacement),
            execution_options={"synchronize_session": False},
        )
        if result.rowcount != 1:
            raise HarnessError("REVISION_CONFLICT", "A concurrent update superseded this command.")
        session.expire(row)
        return replacement

    def _event(
        self,
        session: Session,
        actor: Principal,
        operation_id: str,
        kind: str,
        aggregate_id: str,
        payload: dict,
        dispatch: bool = False,
    ) -> None:
        session.add(
            EventRow(
                project_id=actor.project_id,
                operation_id=operation_id,
                kind=kind,
                aggregate_id=aggregate_id,
                payload=payload,
                created_at=utcnow().isoformat(),
            )
        )
        if dispatch:
            session.add(
                OutboxRow(
                    id=new_id(),
                    project_id=actor.project_id,
                    kind=kind,
                    aggregate_id=aggregate_id,
                    payload={**payload, "operation_id": operation_id},
                )
            )

    def _check_worker_effects(self, session, actor):
        binding = current_worker_effects.get()
        if binding is None:
            return
        if actor != binding.actor:
            raise HarnessError("WORKER_EFFECT_SCOPE", "Bound effects cannot change principal.")
        task = self._get(session, "task", binding.task_id, actor)
        if actor.role == "agent" and (
            actor.experiment_id != task.payload["experiment_id"]
            or actor.branch_id != task.payload["branch_id"]
        ):
            raise HarnessError("WORKER_EFFECT_SCOPE", "Bound effects belong to another task.")
        if binding.require_active:
            self._active(session, task.payload["experiment_id"], actor)
        self._fenced(session, binding.task_id, binding.holder, binding.fence)

    def _execute(
        self,
        actor: Principal,
        key: str,
        operation: str,
        inputs: dict,
        action: Callable[[Session, str], dict],
    ) -> dict:
        if not key or len(key) > 200:
            raise HarnessError(
                "IDEMPOTENCY_KEY_REQUIRED",
                "Supply an Idempotency-Key of 1–200 characters.",
                status=422,
            )
        command_key = digest_json([actor.project_id, actor.id, key])
        fingerprint = digest_json(
            [
                operation,
                inputs,
                actor.role,
                actor.experiment_id,
                actor.branch_id,
                actor.agent_orchestrator,
            ]
        )
        operation_id = new_id()
        try:
            with self.db.transaction() as session:
                self.db.command_lock(session, command_key)
                self._check_worker_effects(session, actor)
                prior = session.get(CommandRow, command_key)
                if prior:
                    if prior.fingerprint != fingerprint:
                        raise HarnessError(
                            "IDEMPOTENCY_CONFLICT",
                            "This key already identifies different inputs.",
                            remediation="Reuse the original inputs or issue a new command key.",
                        )
                    return copy.deepcopy(prior.result)
                result = action(session, operation_id)
                # A slow external write may have consumed the lease. Roll back authoritative
                # metadata even when its replaceable object-store bytes already exist.
                self._check_worker_effects(session, actor)
                session.add(
                    CommandRow(
                        id=command_key,
                        project_id=actor.project_id,
                        operation_id=operation_id,
                        fingerprint=fingerprint,
                        result=copy.deepcopy(result),
                    )
                )
            log.info(
                "command_completed", extra={"operation_id": operation_id, "operation": operation}
            )
            return result
        except HarnessError as error:
            error.operation_id = operation_id
            log.warning(
                "command_rejected",
                extra={
                    "operation_id": operation_id,
                    "operation": operation,
                    "error_code": error.code,
                },
            )
            raise

    def create_campaign(self, request: CampaignCreate, actor: Principal, key: str) -> dict:
        require_role(actor, "researcher", "operator")
        data = request.model_dump(mode="json")

        def action(session, op):
            record = self._insert(session, "campaign", actor, data)
            self._event(session, actor, op, "campaign.created", record["id"], {})
            return record

        return self._execute(actor, key, "campaign.create", data, action)

    def create_problem(self, request: ProblemCreate, actor: Principal, key: str) -> dict:
        require_role(actor, "researcher", "operator")
        data = request.model_dump(mode="json")

        def action(session, op):
            campaign = self._get(session, "campaign", request.campaign_id, actor)
            if request.program not in campaign.payload["programs"]:
                raise HarnessError(
                    "PROGRAM_MISMATCH", "Problem program is not part of this campaign."
                )
            if request.parent_revision_id:
                parent = self._get(session, "problem", request.parent_revision_id, actor)
                if parent.payload["campaign_id"] != request.campaign_id:
                    raise HarnessError(
                        "REVISION_PARENT_MISMATCH", "Target revisions must stay in their campaign."
                    )
            record = self._insert(
                session,
                "problem",
                actor,
                {**data, "target_digest": digest_json(data), "semantic_review": "pending"},
            )
            self._event(
                session,
                actor,
                op,
                "problem.proposed",
                record["id"],
                {"target_digest": record["target_digest"]},
            )
            return record

        return self._execute(actor, key, "problem.create", data, action)

    def review_problem(
        self, problem_id: str, decision: str, rationale: str, actor: Principal, key: str
    ) -> dict:
        require_role(actor, "reviewer")
        if decision not in {"approved", "rejected"} or not rationale.strip():
            raise HarnessError(
                "INVALID_REVIEW", "A review needs a decision and substantive rationale.", status=422
            )

        def action(session, op):
            row = self._get(session, "problem", problem_id, actor)
            review = self._insert(
                session,
                "review",
                actor,
                {
                    "problem_id": problem_id,
                    "scope": "target",
                    "target_digest": row.payload["target_digest"],
                    "decision": decision,
                    "rationale": rationale,
                    "reviewed_by": actor.id,
                },
            )
            self._replace(session, row, {"semantic_review": decision, "review_id": review["id"]})
            self._event(
                session,
                actor,
                op,
                "problem.reviewed",
                problem_id,
                {"review_id": review["id"], "decision": decision},
            )
            return review

        return self._execute(
            actor,
            key,
            "problem.review",
            {"id": problem_id, "decision": decision, "rationale": rationale},
            action,
        )

    def create_experiment(self, request: ExperimentCreate, actor: Principal, key: str) -> dict:
        require_role(actor, "researcher", "operator")
        data = request.model_dump(mode="json")
        if data.get("society") is None:
            # Legacy experiments keep byte-identical payloads and command fingerprints.
            data.pop("society", None)

        def action(session, op):
            problem = self._get(session, "problem", request.problem_id, actor)
            self._get(session, "campaign", request.campaign_id, actor)
            if problem.payload["campaign_id"] != request.campaign_id:
                raise HarnessError("CAMPAIGN_MISMATCH", "The target belongs to another campaign.")
            record = self._insert(
                session,
                "experiment",
                actor,
                {**data, "target_digest": problem.payload["target_digest"], "status": "created"},
            )
            session.add(
                BudgetRow(
                    experiment_id=record["id"],
                    max_cost=money_units(request.budget.max_cost_usd),
                    max_concurrency=request.budget.max_concurrency,
                    max_tokens=request.budget.max_tokens,
                )
            )
            self._event(session, actor, op, "experiment.created", record["id"], {})
            return record

        return self._execute(actor, key, "experiment.create", data, action)

    def transition_experiment(
        self, identifier: str, action: str, expected_revision: int, actor: Principal, key: str
    ) -> dict:
        require_role(actor, "researcher", "operator")
        transitions = {
            "start": ({"created"}, "queued"),
            "pause": ({"queued", "running"}, "paused"),
            "resume": ({"paused", "blocked"}, "queued"),
            "cancel": ({"created", "queued", "running", "paused", "blocked"}, "cancelled"),
        }
        if action not in transitions:
            raise HarnessError(
                "INVALID_TRANSITION", "Unsupported experiment transition.", status=422
            )

        def apply(session, op):
            row = self._get(session, "experiment", identifier, actor)
            if row.revision != expected_revision:
                raise HarnessError("REVISION_CONFLICT", "The experiment has a newer revision.")
            allowed, status = transitions[action]
            if row.payload["status"] not in allowed:
                raise HarnessError("INVALID_TRANSITION", f"Cannot {action} this experiment.")
            if action in {"start", "resume"}:
                problem = self._get(session, "problem", row.payload["problem_id"], actor)
                if problem.payload["semantic_review"] != "approved":
                    raise HarnessError(
                        "TARGET_REVIEW_REQUIRED",
                        "The target interpretation needs expert review.",
                        remediation=(
                            "Obtain a recorded target review before starting this experiment."
                        ),
                    )
                if problem.payload["target_digest"] != row.payload["target_digest"]:
                    raise HarnessError(
                        "TARGET_CHANGED", "The experiment is anchored to a different target."
                    )
            values = {"status": status}
            if action == "start":
                values["started_at"] = utcnow().isoformat()
            record = self._replace(session, row, values, expected_revision)
            self._event(
                session,
                actor,
                op,
                f"experiment.{status}",
                identifier,
                {"revision": record["revision"], "actor_id": actor.id},
                dispatch=True,
            )
            return record

        return self._execute(
            actor,
            key,
            "experiment.transition",
            {"id": identifier, "action": action, "expected_revision": expected_revision},
            apply,
        )

    def _active(self, session: Session, identifier: str, actor: Principal) -> RecordRow:
        row = self._get(session, "experiment", identifier, actor)
        session.refresh(row, with_for_update=True)
        if row.payload.get("budget_reconciliation_required"):
            raise HarnessError(
                "BUDGET_RECONCILIATION_REQUIRED",
                "A settled charge exceeded its reservation; reconcile the experiment budget.",
            )
        if row.payload["status"] not in {"queued", "running"}:
            raise HarnessError("EXPERIMENT_NOT_ACTIVE", "Allocation requires an active experiment.")
        started = datetime.fromisoformat(row.payload["started_at"])
        if (utcnow() - started).total_seconds() >= row.payload["budget"]["max_runtime_seconds"]:
            raise HarnessError(
                "EXPERIMENT_DEADLINE", "The experiment runtime envelope is exhausted."
            )
        return row

    def reserve_resources(
        self,
        experiment_id: str,
        cost: str | Decimal,
        workers: int,
        actor: Principal,
        key: str,
        *,
        tokens: int = 0,
        model_task_binding: tuple[str, str, int] | None = None,
    ) -> dict:
        require_role(actor, "researcher", "operator")
        amount = money_units(cost)
        if (
            not isinstance(workers, int)
            or isinstance(workers, bool)
            or workers < 0
            or not isinstance(tokens, int)
            or isinstance(tokens, bool)
            or tokens < 0
        ):
            raise HarnessError(
                "INVALID_RESOURCE_AMOUNT",
                "Resource allocations must use nonnegative integer counts.",
                status=422,
            )

        def action(session, op):
            self._active(session, experiment_id, actor)
            if model_task_binding is not None:
                task_id, holder, fence = model_task_binding
                task = self._get(session, "task", task_id, actor)
                self._fenced(session, task_id, holder, fence)
                if workers != 0 or task.payload.get("experiment_id") != experiment_id:
                    raise HarnessError("RESERVATION_SCOPE", "Model task binding is out of scope.")
            budget = session.scalar(
                select(BudgetRow).where(BudgetRow.experiment_id == experiment_id).with_for_update()
            )
            if (
                budget.max_tokens is not None
                and budget.tokens_spent + budget.tokens_reserved + tokens > budget.max_tokens
            ):
                raise HarnessError(
                    "TOKEN_BUDGET_EXCEEDED", "The experiment token envelope is exhausted."
                )
            if budget.spent + budget.reserved + amount > budget.max_cost:
                raise HarnessError(
                    "BUDGET_EXCEEDED",
                    "The requested reservation exceeds the experiment envelope.",
                    remediation=(
                        "Reconcile outstanding usage or increase the approved experiment envelope."
                    ),
                )
            if budget.active_workers + workers > budget.max_concurrency:
                raise HarnessError(
                    "CONCURRENCY_EXCEEDED",
                    "The experiment has no free worker slots.",
                    retryable=True,
                    remediation="Wait for an existing worker allocation to settle.",
                )
            reservation = ReservationRow(
                id=new_id(),
                experiment_id=experiment_id,
                reserved=amount,
                workers=workers,
                state="active",
                tokens_reserved=tokens,
            )
            session.add(reservation)
            if model_task_binding is not None:
                self._insert(
                    session,
                    "model_reservation",
                    actor,
                    {
                        "experiment_id": experiment_id,
                        "task_id": task_id,
                        "reservation_id": reservation.id,
                        "holder": holder,
                        "fence": fence,
                        "status": "active",
                    },
                )
            budget.reserved += amount
            budget.tokens_reserved += tokens
            budget.active_workers += workers
            result = {
                "id": reservation.id,
                "experiment_id": experiment_id,
                "reserved_cost_usd": money_string(amount),
                "workers": workers,
                "state": "active",
            }
            self._event(session, actor, op, "resources.reserved", experiment_id, result)
            return result

        return self._execute(
            actor,
            key,
            "resources.reserve",
            {
                "experiment_id": experiment_id,
                "amount": amount,
                "workers": workers,
                "tokens": tokens,
                "model_task_binding": model_task_binding,
            },
            action,
        )

    def settle_resources(
        self,
        reservation_id: str,
        actual_cost: str | Decimal | None,
        uncertain: bool,
        actor: Principal,
        key: str,
        *,
        actual_tokens: int = 0,
    ) -> dict:
        require_role(actor, "operator")
        if uncertain and actual_cost is not None or not uncertain and actual_cost is None:
            raise HarnessError(
                "INVALID_SETTLEMENT",
                "Supply either actual cost or an uncertain outcome.",
                status=422,
            )
        if (
            not isinstance(actual_tokens, int)
            or isinstance(actual_tokens, bool)
            or actual_tokens < 0
        ):
            raise HarnessError(
                "INVALID_SETTLEMENT", "Actual tokens must be a nonnegative integer.", status=422
            )
        actual = money_units(actual_cost) if actual_cost is not None else None

        def action(session, op):
            # Use the same experiment -> reservation -> budget lock order as VM
            # cleanup. The first read only discovers scope; refresh after the
            # experiment lock before trusting mutable reservation state.
            reservation = session.get(ReservationRow, reservation_id)
            if reservation is None:
                raise HarnessError("NOT_FOUND", "Reservation not found.", status=404)
            experiment = self._get(session, "experiment", reservation.experiment_id, actor)
            session.refresh(experiment, with_for_update=True)
            session.refresh(reservation, with_for_update=True)
            if reservation.experiment_id != experiment.id:
                raise HarnessError("RESERVATION_SCOPE", "Reservation experiment binding changed.")
            budget = session.scalar(
                select(BudgetRow)
                .where(BudgetRow.experiment_id == reservation.experiment_id)
                .with_for_update()
            )
            overrun = False
            if reservation.state == "settled":
                if (
                    actual != reservation.actual
                    or actual_tokens != reservation.tokens_actual
                    or uncertain
                ):
                    raise HarnessError(
                        "SETTLEMENT_CONFLICT", "The reservation was already settled differently."
                    )
                overrun = bool(experiment.payload.get("budget_reconciliation_required"))
            elif uncertain:
                reservation.state = "uncertain"
            else:
                overrun = (
                    actual > reservation.reserved
                    or actual_tokens > reservation.tokens_reserved
                    or budget.spent + budget.reserved - reservation.reserved + actual
                    > budget.max_cost
                    or (
                        budget.max_tokens is not None
                        and budget.tokens_spent
                        + budget.tokens_reserved
                        - reservation.tokens_reserved
                        + actual_tokens
                        > budget.max_tokens
                    )
                )
                budget.reserved -= reservation.reserved
                budget.tokens_reserved -= reservation.tokens_reserved
                budget.tokens_spent += actual_tokens
                reservation.tokens_actual = actual_tokens
                budget.spent += actual
                budget.active_workers -= reservation.workers
                reservation.actual = actual
                reservation.state = "settled"
                if overrun and not experiment.payload.get("budget_reconciliation_required"):
                    self._replace(
                        session,
                        experiment,
                        {"budget_reconciliation_required": True},
                        experiment.revision,
                    )
                if overrun:
                    self._event(
                        session,
                        actor,
                        op,
                        "resources.overrun",
                        reservation.experiment_id,
                        {
                            "reservation_id": reservation.id,
                            "reserved_cost_usd": money_string(reservation.reserved),
                            "actual_cost_usd": money_string(actual),
                            "reserved_tokens": reservation.tokens_reserved,
                            "actual_tokens": actual_tokens,
                        },
                    )
            result = {
                "id": reservation.id,
                "state": reservation.state,
                "actual_cost_usd": money_string(reservation.actual)
                if reservation.actual is not None
                else None,
                "reconciliation_required": overrun,
                "code": "BUDGET_RECONCILIATION_REQUIRED" if overrun else None,
            }
            self._event(session, actor, op, "resources.settled", reservation.experiment_id, result)
            return result

        return self._execute(
            actor,
            key,
            "resources.settle",
            {
                "id": reservation_id,
                "actual": actual,
                "uncertain": uncertain,
                "actual_tokens": actual_tokens,
            },
            action,
        )

    def ledger(self, experiment_id: str, actor: Principal) -> dict:
        with self.db.sessions() as session:
            return self._ledger(session, experiment_id, actor)

    def _ledger(self, session, experiment_id, actor):
        self._get(session, "experiment", experiment_id, actor)
        budget = session.get(BudgetRow, experiment_id)
        uncertain = session.scalar(
            select(func.count())
            .select_from(ReservationRow)
            .where(
                ReservationRow.experiment_id == experiment_id,
                ReservationRow.state == "uncertain",
            )
        )
        return {
            "max_cost_usd": money_string(budget.max_cost),
            "reserved_cost_usd": money_string(budget.reserved),
            "spent_cost_usd": money_string(budget.spent),
            "active_workers": budget.active_workers,
            "max_concurrency": budget.max_concurrency,
            "uncertain_operations": uncertain,
            "max_tokens": budget.max_tokens,
            "tokens_reserved": budget.tokens_reserved,
            "tokens_spent": budget.tokens_spent,
        }

    def create_branch(
        self, experiment_id: str, request: BranchCreate, actor: Principal, key: str
    ) -> dict:
        self._research_role(actor)
        data = request.model_dump(mode="json")

        def action(session, op):
            experiment = self._get(session, "experiment", experiment_id, actor)
            parent = None
            if request.parent_id:
                parent = self._writable_branch(session, request.parent_id, actor)
                self._guard_referee_branch(parent, actor)
                if parent.payload["experiment_id"] != experiment_id:
                    raise HarnessError(
                        "BRANCH_EXPERIMENT_MISMATCH",
                        "A branch parent must belong to this experiment.",
                    )
            if actor.role == "agent" and actor.branch_id and request.parent_id != actor.branch_id:
                raise HarnessError(
                    "BRANCH_AUTHORITY", "A scoped worker forks from its own branch.", status=403
                )
            if request.checkpoint_id:
                checkpoint = self._get(session, "artifact", request.checkpoint_id, actor)
                if (
                    checkpoint.payload.get("experiment_id") != experiment_id
                    or checkpoint.payload.get("artifact_kind") != "checkpoint"
                ):
                    raise HarnessError(
                        "CHECKPOINT_MISMATCH", "Checkpoint belongs to a different experiment."
                    )
            if request.model_index is not None and request.model_index >= len(
                experiment.payload["models"]
            ):
                raise HarnessError("MODEL_NOT_ALLOWED", "Select a recorded experiment model index.")
            selected_model = (
                experiment.payload["models"][request.model_index]
                if request.model_index is not None
                else parent.payload["model_configuration"]
                if request.parent_id
                else experiment.payload["models"][0]
            )
            branch_id = new_id()
            record = self._insert(
                session,
                "branch",
                actor,
                {
                    **data,
                    "reply_to_parent": request.parent_id,
                    "experiment_id": experiment_id,
                    "target_digest": experiment.payload["target_digest"],
                    "status": "open",
                    "execution_identity": new_id(),
                    "model_configuration": selected_model,
                    # Society roots found a lab; forks join their parent's lab.
                    **self._branch_lab(session, experiment, parent, branch_id),
                },
                record_id=branch_id,
            )
            if request.parent_id:
                session.add(
                    EdgeRow(
                        source_id=record["id"],
                        target_id=request.parent_id,
                        relation=request.relation,
                        project_id=actor.project_id,
                    )
                )
            self._event(
                session, actor, op, "branch.created", record["id"], {"experiment_id": experiment_id}
            )
            return record

        return self._execute(
            actor, key, "branch.create", {**data, "experiment_id": experiment_id}, action
        )

    def create_artifact(self, request: ArtifactCreate, actor: Principal, key: str) -> dict:
        require_role(actor, "researcher", "operator", "verifier", "agent")
        if request.kind == "workspace_recovery_observation" and (
            actor.role not in {"operator", "admin"}
            or actor.experiment_id is not None
            or actor.branch_id is not None
            or request.branch_id is not None
            or request.provenance.get("task_id") is not None
            or request.trusted_input
            or current_worker_effects.get() is not None
        ):
            raise HarnessError(
                "RECOVERY_EVIDENCE_AUTHORITY",
                "Only an unbound operator may record private workspace recovery evidence.",
                status=403,
            )
        if actor.role == "agent" and request.kind in {"masked_reference", "literature_screen"}:
            raise HarnessError(
                "ARTIFACT_KIND_RESERVED",
                "Masked references and literature screens are written only by the platform.",
                status=403,
            )
        # Controllers write native state, checkpoints and failure evidence; export and
        # restore decode these kinds, so model or researcher bytes must not claim them.
        # A masked reference is researcher-uploaded; the check above refuses agents.
        if request.kind in self._private_artifact_kinds - {
            "masked_reference"
        } and actor.role not in {"operator", "admin"}:
            raise HarnessError(
                "ARTIFACT_KIND_RESERVED",
                "This artifact kind is reserved for controller-written platform state.",
                status=403,
                remediation="Store findings or Lean source under a scientific artifact kind.",
            )
        if actor.role == "agent" and request.experiment_id != actor.experiment_id:
            raise HarnessError(
                "ARTIFACT_SCOPE", "Agent artifacts require their assigned experiment.", status=403
            )
        data = request.model_dump(mode="json")

        def action(session, op):
            if request.experiment_id:
                self._get(session, "experiment", request.experiment_id, actor)
            content = request.content.encode("utf-8")
            digest = self.artifacts.put(content)
            metadata = {k: v for k, v in data.items() if k != "content"}
            record = self._insert(
                session,
                "artifact",
                actor,
                {
                    **metadata,
                    "artifact_kind": request.kind,
                    "sha256": digest,
                    "size_bytes": len(content),
                    "submitted_by": actor.id,
                },
            )
            self._event(session, actor, op, "artifact.created", record["id"], {"sha256": digest})
            return record

        return self._execute(actor, key, "artifact.create", data, action)

    def artifact_content(self, artifact_id: str, actor: Principal) -> bytes:
        record = self.get_record("artifact", artifact_id, actor)
        return self.artifacts.get(record["sha256"])

    def load_native_checkpoint(self, artifact_id: str, actor: Principal):
        """Restore a runtime checkpoint from old JSON or a scoped chunk graph."""
        from .execution.checkpoint_chunks import MAX_BYTES, MAX_NODES, decode, references

        manifest = self.get_record("artifact", artifact_id, actor)
        if manifest.get("artifact_kind") != "native_checkpoint":
            raise HarnessError("NATIVE_CHECKPOINT_SCOPE", "Artifact is not a native checkpoint.")
        provenance = manifest.get("provenance") or {}
        task_id = provenance.get("task_id")
        if not task_id or not provenance.get("session_id"):
            raise HarnessError("NATIVE_CHECKPOINT_SCOPE", "Native checkpoint owner is missing.")

        def in_scope(chunk, ref):
            return (
                chunk.get("artifact_kind") == "native_checkpoint_chunk"
                and chunk.get("experiment_id") == manifest.get("experiment_id")
                and (chunk.get("provenance") or {}).get("task_id") == task_id
                and (chunk.get("provenance") or {}).get("session_id") == provenance["session_id"]
                and chunk.get("sha256") == ref["sha256"]
            )

        raw = self.artifacts.get(manifest["sha256"])
        # Prefetch the graph with one record query per depth level. Anything not
        # cleanly prefetched falls back to the exact per-reference path below,
        # and decode still checks every edge, digest and bound.
        loaded: dict[str, bytes] = {}
        try:
            frontier = [json.loads(raw).get("root")]
        except (ValueError, UnicodeDecodeError, AttributeError):
            frontier = []
        total = len(raw)
        while frontier and len(loaded) < MAX_NODES and total <= MAX_BYTES:
            refs = {
                ref["artifact_id"]: ref
                for ref in frontier
                if isinstance(ref, dict)
                and isinstance(ref.get("artifact_id"), str)
                and isinstance(ref.get("sha256"), str)
                and ref["artifact_id"] not in loaded
            }
            frontier = []
            identifiers = list(refs)[:MAX_NODES]
            with self.db.sessions() as session:
                rows = [
                    row
                    for start in range(0, len(identifiers), 500)
                    for row in session.scalars(
                        select(RecordRow).where(RecordRow.id.in_(identifiers[start : start + 500]))
                    )
                ]
                chunks = [
                    (row.payload, refs[row.id])
                    for row in rows
                    if row.project_id == actor.project_id
                    and row.kind == "artifact"
                    and self._in_scope(session, row, actor)
                    and in_scope(row.payload, refs[row.id])
                ]
            for chunk, ref in chunks:
                try:
                    content = self.artifacts.get(chunk["sha256"])
                    node = json.loads(content)
                except (HarnessError, ValueError, UnicodeDecodeError):
                    continue
                loaded[ref["artifact_id"]] = content
                total += len(content)
                frontier.extend(references(node))

        def read(ref):
            if ref["artifact_id"] in loaded:
                return loaded[ref["artifact_id"]]
            chunk = self.get_record("artifact", ref["artifact_id"], actor)
            if not in_scope(chunk, ref):
                raise HarnessError(
                    "NATIVE_CHECKPOINT_SCOPE", "Native checkpoint chunk is out of scope."
                )
            return self.artifacts.get(chunk["sha256"])

        checkpoint = decode(raw, read)
        if checkpoint.session.id != provenance["session_id"]:
            raise HarnessError("NATIVE_CHECKPOINT_SCOPE", "Native checkpoint session changed.")
        return checkpoint

    def create_claim(
        self,
        experiment_id: str,
        statement: str,
        assumptions: list[str],
        evidence: str,
        artifact_id: str | None,
        actor: Principal,
        key: str,
    ) -> dict:
        self._research_role(actor)
        if evidence not in {"conjecture", "numerical", "conditional"}:
            raise HarnessError(
                "INVALID_EVIDENCE",
                "Only the independent verifier can establish proof status.",
                status=422,
            )
        if not statement.strip():
            raise HarnessError("INVALID_CLAIM", "A claim needs an explicit statement.", status=422)
        data = {
            "experiment_id": experiment_id,
            "statement": statement,
            "assumptions": assumptions,
            "evidence": evidence,
            "artifact_id": artifact_id,
        }

        def action(session, op):
            experiment = self._get(session, "experiment", experiment_id, actor)
            if artifact_id:
                artifact = self._get(session, "artifact", artifact_id, actor)
                if artifact.payload.get("experiment_id") != experiment_id:
                    raise HarnessError(
                        "ARTIFACT_EXPERIMENT_MISMATCH", "Evidence belongs to another experiment."
                    )
            record = self._insert(
                session,
                "claim",
                actor,
                {
                    **data,
                    "proof_status": "unproved",
                    "semantic_review": "pending",
                    "novelty_status": "unreviewed",
                    "target_digest": experiment.payload["target_digest"],
                },
            )
            self._event(
                session, actor, op, "claim.proposed", record["id"], {"experiment_id": experiment_id}
            )
            return record

        return self._execute(actor, key, "claim.create", data, action)

    def events(self, actor: Principal, after: int = 0, limit: int = 100) -> list[dict]:
        return self.event_page(actor, after, limit)["items"]

    def event_page(self, actor, after=0, limit=100, tail=False):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise HarnessError("INVALID_EVENT_PAGE", "Use a nonnegative cursor and limit 1-1000.")
        with self.db.sessions() as session:
            high = (
                session.scalar(
                    select(func.max(EventRow.sequence)).where(
                        EventRow.project_id == actor.project_id
                    )
                )
                or 0
            )
            cursor = high + 1 if tail else after
            items, scanned = [], 0
            while scanned < 5000 and len(items) < limit:
                query = (
                    select(EventRow)
                    .where(
                        EventRow.project_id == actor.project_id,
                        EventRow.sequence <= high,
                        EventRow.sequence > after,
                        EventRow.sequence < cursor if tail else EventRow.sequence > cursor,
                    )
                    .order_by(EventRow.sequence.desc() if tail else EventRow.sequence)
                    .limit(500)
                )
                rows = list(session.scalars(query))
                if not rows:
                    cursor = after if tail else max(after, high)
                    break
                for row in rows:
                    scanned += 1
                    cursor = row.sequence
                    if row.kind == "discussion.source_withdrawn" and actor.role not in {
                        "operator",
                        "admin",
                    }:
                        continue
                    aggregate = (
                        session.get(RecordRow, row.aggregate_id) if actor.role == "agent" else None
                    )
                    if actor.role == "agent" and (
                        aggregate is None or not self._in_scope(session, aggregate, actor)
                    ):
                        continue
                    if actor.role == "agent" and row.kind == "message.created":
                        message = session.get(RecordRow, row.payload.get("message_id"))
                        if (
                            not message
                            or message.kind != "message"
                            or message.payload.get("recipient_branch_id") != actor.branch_id
                            or not self._in_scope(session, message, actor)
                        ):
                            continue
                    items.append(
                        {
                            "sequence": row.sequence,
                            "kind": row.kind,
                            "aggregate_id": row.aggregate_id,
                            "operation_id": row.operation_id,
                            "payload": row.payload,
                            "created_at": row.created_at,
                        }
                    )
                    if len(items) == limit:
                        break
            return {
                "items": list(reversed(items)) if tail else items,
                "next_cursor": max(after, high) if tail else cursor,
                "has_more": cursor > after if tail else cursor < high,
                "window": "latest" if tail else "forward",
                "scan_limited": scanned >= 5000,
            }

    def pending_outbox(self, limit: int = 100) -> list[dict]:
        """Internal dispatcher interface, never exposed to project HTTP clients."""
        with self.db.sessions() as session:
            rows = session.scalars(
                select(OutboxRow).where(OutboxRow.state == "pending").limit(limit)
            )
            return [
                {
                    "id": r.id,
                    "project_id": r.project_id,
                    "kind": r.kind,
                    "aggregate_id": r.aggregate_id,
                    "payload": r.payload,
                }
                for r in rows
            ]

    def export_experiment(self, experiment_id: str, actor: Principal) -> dict:
        # Snapshot all metadata in one transaction. Artifact bytes are immutable and checked
        # afterward, so object-store latency does not extend the metadata lock.
        with self.db.transaction() as session:
            isolation = "sqlite_immediate"
            if self.db.engine.dialect.name == "postgresql":
                session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
                isolation = "postgresql_repeatable_read"
            experiment = copy.deepcopy(
                self._get(session, "experiment", experiment_id, actor).payload
            )
            problem = copy.deepcopy(
                self._get(session, "problem", experiment["problem_id"], actor).payload
            )
            records = {
                kind: []
                for kind in (
                    "branch",
                    "task",
                    "claim",
                    "artifact",
                    "session",
                    "continuation_link",
                    "verification",
                    "program",
                    "message",
                    "source",
                    "workspace",
                    "workspace_operation",
                    "review",
                    "discussion_topic",
                    "discussion_post",
                    "discussion_reader",
                    "discussion_subscription",
                    "discussion_delivery",
                    "discussion_withdrawal",
                    "workforce_policy",
                    "workforce_profile",
                    "workforce_team",
                    "workforce_capacity_request",
                )
            }
            society = experiment.get("society") is not None
            if society:
                # Only society exports carry commons and literature records; legacy exports
                # keep their exact keys.
                records.update({kind: [] for kind in SOCIETY_EXPORT_KINDS})
            rows = session.scalars(
                select(RecordRow)
                .where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.payload["experiment_id"].as_string() == experiment_id,
                )
                .order_by(RecordRow.id)
            )
            for row in rows:
                if row.kind in records and self._in_scope(session, row, actor):
                    records[row.kind].append(copy.deepcopy(row.payload))
            if problem.get("review_id"):
                records["review"].append(
                    copy.deepcopy(self._get(session, "review", problem["review_id"], actor).payload)
                )
            commons_edges = {}
            if society:
                visible = {node["id"] for node in records["commons_node"]}
                commons_edges["edges"] = self._commons_edges(
                    session, actor.project_id, experiment_id, visible
                )
            manifest = {
                "format": "physharness.reproduction.v1",
                "experiment": experiment,
                "problem": problem,
                "records": records,
                **commons_edges,
                "ledger": self._ledger(session, experiment_id, actor),
                "snapshot": {
                    "isolation": isolation,
                    "last_project_event_sequence": session.scalar(
                        select(func.max(EventRow.sequence)).where(
                            EventRow.project_id == actor.project_id
                        )
                    )
                    or 0,
                },
                "qualification": {"scientific_novelty": "unreviewed", "live_fleet": "unqualified"},
            }
        for artifact in records["artifact"]:
            self.artifacts.get(artifact["sha256"])
        # Native runtime manifests name immutable private dependencies. Verify
        # the complete graph against this same metadata snapshot before export.
        from .execution.checkpoint_chunks import decode, is_manifest

        exported_artifacts = {row["id"]: row for row in records["artifact"]}
        for artifact in records["artifact"]:
            if artifact.get("artifact_kind") != "native_checkpoint":
                continue  # Workspace pause snapshots share this kind but have another format.
            raw = self.artifacts.get(artifact["sha256"])
            try:
                parsed = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
            if not is_manifest(parsed):
                continue
            owner = (artifact.get("provenance") or {}).get("task_id")
            if not owner:
                raise HarnessError("NATIVE_CHECKPOINT_SCOPE", "Checkpoint owner is missing.")

            def read(ref, *, artifact=artifact, owner=owner):
                chunk = exported_artifacts.get(ref["artifact_id"])
                if (
                    chunk is None
                    or chunk.get("artifact_kind") != "native_checkpoint_chunk"
                    or chunk.get("experiment_id") != artifact.get("experiment_id")
                    or (chunk.get("provenance") or {}).get("task_id") != owner
                    or (chunk.get("provenance") or {}).get("session_id")
                    != (artifact.get("provenance") or {}).get("session_id")
                    or chunk.get("sha256") != ref["sha256"]
                ):
                    raise HarnessError(
                        "NATIVE_CHECKPOINT_SCOPE", "Export checkpoint dependency is out of scope."
                    )
                return self.artifacts.get(chunk["sha256"])

            restored = decode(raw, read)
            if restored.session.id != (artifact.get("provenance") or {}).get("session_id"):
                raise HarnessError("NATIVE_CHECKPOINT_SCOPE", "Export checkpoint session changed.")
        return {**manifest, "manifest_sha256": digest_json(manifest)}
