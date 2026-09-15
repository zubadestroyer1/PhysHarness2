"""Application authority: actors, immutable targets, commands, and budget invariants."""

import copy
import hashlib
import logging
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from .acceptance import AcceptanceMixin
from .artifacts import ArtifactStore
from .collaboration import CollaborationMixin
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
)

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


def require_role(actor: Principal, *roles: str) -> None:
    if actor.role not in roles and actor.role != "admin":
        raise HarnessError(
            "FORBIDDEN",
            "This identity does not have the required capability.",
            status=403,
            remediation="Use an identity assigned the required project role.",
        )


class HarnessService(AcceptanceMixin, CollaborationMixin, ResearchMixin):
    _digest = staticmethod(digest_json)

    @staticmethod
    def _research_role(actor):
        require_role(actor, "researcher", "operator", "agent")

    _private_artifact_kinds = frozenset(
        {
            "checkpoint",
            "native_checkpoint",
            "runtime_event",
            "execution_failure",
        }
    )

    def _accepted_for_sharing(self, session, row, experiment):
        """Only canonical receipts bound to the exact reviewed target confer visibility."""
        if row.kind == "artifact":
            receipts = session.scalars(
                select(RecordRow).where(
                    RecordRow.project_id == row.project_id,
                    RecordRow.kind == "verification",
                    RecordRow.payload["artifact_id"].as_string() == row.id,
                )
            )
            return any(self._accepted_for_sharing(session, r, experiment) for r in receipts)
        if row.kind == "claim":
            receipt = session.get(RecordRow, row.payload.get("verification_id", ""))
            return bool(
                receipt
                and row.payload.get("proof_status") == "verified"
                and receipt.payload.get("claim_id") == row.id
                and self._accepted_for_sharing(session, receipt, experiment)
            )
        if row.kind != "verification":
            return False
        data = row.payload
        target = session.get(RecordRow, experiment.payload["problem_id"])
        artifact = session.get(RecordRow, data.get("artifact_id", ""))
        return bool(
            data.get("status") == "verified"
            and data.get("assurance") == "independent_kernel"
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

    def _in_scope(self, session, row, actor):
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
        if row.kind == "session" or (
            row.kind == "artifact"
            and row.payload.get("artifact_kind") in self._private_artifact_kinds
        ):
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
                query = query.where(RecordRow.payload["experiment_id"].as_string() == experiment_id)
            if actor.role == "agent":
                experiment = session.get(RecordRow, actor.experiment_id)
                if not experiment or experiment.project_id != actor.project_id:
                    return {"items": [], "next_cursor": None}
                if kind in {"experiment", "problem", "campaign"}:
                    identifier = (
                        experiment.id if kind == "experiment" else experiment.payload[f"{kind}_id"]
                    )
                    query = query.where(RecordRow.id == identifier)
                elif kind == "review":
                    query = query.where(
                        RecordRow.payload["problem_id"].as_string()
                        == experiment.payload["problem_id"]
                    )
                else:
                    query = query.where(
                        RecordRow.payload["experiment_id"].as_string() == actor.experiment_id
                    )
            if after:
                query = query.where(RecordRow.id > after)
            # Apply authorization before pagination. Hidden rows cannot truncate a visible page.
            rows, scanned = [], None
            while len(rows) < limit + 1:
                chunk_query = query if scanned is None else query.where(RecordRow.id > scanned)
                chunk = list(
                    session.scalars(chunk_query.order_by(RecordRow.id).limit(max(100, limit + 1)))
                )
                if not chunk:
                    break
                for row in chunk:
                    if self._in_scope(session, row, actor):
                        rows.append(row)
                        if len(rows) == limit + 1:
                            break
                scanned = chunk[-1].id
            visible = rows[:limit]
            return {
                "items": [copy.deepcopy(r.payload) for r in visible],
                "next_cursor": visible[-1].id if len(rows) > limit else None,
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

    def _insert(self, session: Session, kind: str, actor: Principal, data: dict) -> dict:
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
            reservation = session.scalar(
                select(ReservationRow).where(ReservationRow.id == reservation_id).with_for_update()
            )
            if reservation is None:
                raise HarnessError("NOT_FOUND", "Reservation not found.", status=404)
            self._get(session, "experiment", reservation.experiment_id, actor)
            budget = session.scalar(
                select(BudgetRow)
                .where(BudgetRow.experiment_id == reservation.experiment_id)
                .with_for_update()
            )
            if reservation.state == "settled":
                if (
                    actual != reservation.actual
                    or actual_tokens != reservation.tokens_actual
                    or uncertain
                ):
                    raise HarnessError(
                        "SETTLEMENT_CONFLICT", "The reservation was already settled differently."
                    )
            elif uncertain:
                reservation.state = "uncertain"
            else:
                budget.reserved -= reservation.reserved
                budget.tokens_reserved -= reservation.tokens_reserved
                budget.tokens_spent += actual_tokens
                reservation.tokens_actual = actual_tokens
                budget.spent += actual
                budget.active_workers -= reservation.workers
                reservation.actual = actual
                reservation.state = "settled"
            result = {
                "id": reservation.id,
                "state": reservation.state,
                "actual_cost_usd": money_string(reservation.actual)
                if reservation.actual is not None
                else None,
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
            if request.parent_id:
                parent = self._writable_branch(session, request.parent_id, actor)
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
            record = self._insert(
                session,
                "branch",
                actor,
                {
                    **data,
                    "experiment_id": experiment_id,
                    "target_digest": experiment.payload["target_digest"],
                    "status": "open",
                    "execution_identity": new_id(),
                    "model_configuration": selected_model,
                },
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
                    aggregate = (
                        session.get(RecordRow, row.aggregate_id) if actor.role == "agent" else None
                    )
                    if actor.role == "agent" and (
                        aggregate is None or not self._in_scope(session, aggregate, actor)
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
                    "verification",
                    "program",
                    "message",
                    "source",
                    "workspace",
                    "workspace_operation",
                    "review",
                )
            }
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
            manifest = {
                "format": "physharness.reproduction.v1",
                "experiment": experiment,
                "problem": problem,
                "records": records,
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
        return {**manifest, "manifest_sha256": digest_json(manifest)}
