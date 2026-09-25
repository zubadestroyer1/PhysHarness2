"""Platform-assigned referee reviews and evidence-bound commons ladder transitions.

A referee is an independent helper branch the platform assigns: it joins no lab and, when the
experiment records several models, runs a different model from the node's author. Each referee
task submits exactly one verdict. Verdicts, Lean elaboration results, local compiles and
independent kernel receipts become ladder moves only here, through ``_set_node_status``.
"""

import copy
import json
from typing import Annotated, Any

from pydantic import Field, StrictBool, ValidationError, model_validator
from sqlalchemy import func, select

from .commons import _lean_digest
from .commons_models import ALLOWED_TRANSITIONS, CLOSED_STATUSES, LEAN_NAME
from .domain import StrictModel, digest_json, new_id
from .errors import HarnessError
from .storage import RecordRow, record_json_text
from .worker_authority import current_worker_effects

REVIEW_VERDICTS = {"informal": ("sound", "gaps", "wrong"), "fidelity": ("faithful", "unfaithful")}
NEGATIVE_VERDICTS = frozenset({"gaps", "wrong", "unfaithful"})
FORMAL_STATUSES = frozenset({"formally_stated", "compiles_locally"})
TERMINAL_TASK_STATUSES = ("completed", "failed", "blocked")
MAX_OPEN_REVIEWS = 100  # Bounded scan of one node's open referee tasks.
MAX_EVIDENCE_REVIEWS = 20  # Review ids cited in one status evidence record.
MAX_OBJECTIVE = 20_000  # The task objective bound shared with recruitment and task creation.
# Applied only when the full objective would exceed MAX_OBJECTIVE; the node keeps the exact text.
OBJECTIVE_CLIPS = {"assumptions": 3000, "lean_header": 1000, "lean_statement": 6000}
MAX_AXIOMS_BYTES = 8000
SHA256 = r"^[0-9a-f]{64}$"
REFEREE_OBJECTIVE = {
    "informal": (
        "You are an independent referee assigned by the platform to commons node {node_id}. "
        "You did not write it; judge only what it states.\n\n"
        "Title: {title}\n\n"
        "Informal statement:\n{statement}\n\n"
        "Assumptions:\n{assumptions}\n\n"
        "Task: judge whether the argument or claim is sound and complete. List concrete gaps: "
        "each missing step, unjustified inference or unstated hypothesis, located precisely. "
        "Answer sound, gaps or wrong.\n"
        "Call submit_review exactly once. Your verdict is recorded; it is not a proof."
    ),
    "fidelity": (
        "You are an independent referee assigned by the platform to commons node {node_id}. "
        "You did not write it; judge only what it states.\n\n"
        "Title: {title}\n\n"
        "Informal statement:\n{statement}\n\n"
        "Assumptions:\n{assumptions}\n\n"
        "Lean header:\n{lean_header}\n\n"
        "Lean name: {lean_name}\n\n"
        "Lean statement:\n{lean_statement}\n\n"
        "Task: translate the Lean statement back to English and compare it with the informal "
        "statement and its assumptions. Probe vacuity: are the hypotheses satisfiable, and can "
        "False be derived from them with automation? Answer faithful or unfaithful.\n"
        "Call submit_review exactly once. Your verdict is recorded; it is not a proof."
    ),
}


def statement_digest(node):
    """Digest of what an informal referee judges: the statement and its assumptions."""
    return digest_json({"statement": node["statement"], "assumptions": node["assumptions"]})


def referee_objective(scope, node_id, node):
    fields = {
        "node_id": node_id,
        "title": node["title"],
        "statement": node["statement"],
        "assumptions": "\n".join(f"- {item}" for item in node["assumptions"]) or "(none stated)",
        "lean_header": node.get("lean_header") or "(none)",
        "lean_name": node.get("lean_name") or "",
        "lean_statement": node.get("lean_statement") or "",
    }
    template = REFEREE_OBJECTIVE[scope]
    objective = template.format(**fields)
    if len(objective) <= MAX_OBJECTIVE:
        return objective
    marker = f"\n[truncated; read node {node_id} for the exact text]"
    for field, limit in OBJECTIVE_CLIPS.items():
        if len(fields[field]) > limit:
            fields[field] = fields[field][:limit] + marker
    return template.format(**fields)


def _stale(assignment, node):
    """An informal review judged the statement; a fidelity review also judged the Lean text."""
    if assignment["statement_sha256"] != statement_digest(node):
        return True
    return (
        assignment["scope"] == "fidelity"
        and assignment["lean_statement_sha256"] != node["lean_statement_sha256"]
    )


class _ReviewText(StrictModel):
    summary: str = Field(min_length=1, max_length=4000)
    objections: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(max_length=10)

    @model_validator(mode="after")
    def substantive(self):
        if not self.summary.strip() or any(not text.strip() for text in self.objections):
            raise ValueError("Review text must be substantive")
        return self


class _Elaboration(StrictModel):
    ok: StrictBool
    backend: str = Field(min_length=1, max_length=200)
    diagnostics_sha256: str = Field(pattern=SHA256)


class _LeanStatement(StrictModel):
    lean_header: str | None = Field(default=None, max_length=2000)
    lean_name: str = Field(pattern=LEAN_NAME)
    lean_statement: str = Field(min_length=1, max_length=20000)
    elaboration: _Elaboration

    @model_validator(mode="after")
    def substantive(self):
        if not self.lean_statement.strip():
            raise ValueError("A Lean statement must be substantive")
        return self


class _CompileResult(StrictModel):
    complete: StrictBool
    backend: str = Field(min_length=1, max_length=200)
    statement_found: StrictBool
    axioms: dict[str, Any]
    # _lean_digest of the header/name/statement the platform found in the compiled source.
    lean_statement_sha256: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def bounded(self):
        if len(json.dumps(self.axioms, ensure_ascii=False).encode("utf-8")) > MAX_AXIOMS_BYTES:
            raise ValueError(f"Axiom report exceeds {MAX_AXIOMS_BYTES} bytes")
        return self


class _LocalCompile(StrictModel):
    source_sha256: str = Field(pattern=SHA256)
    compile_result: _CompileResult


def _validated(model, code, message, **values):
    try:
        return model.model_validate(values)
    except (ValidationError, TypeError, ValueError) as error:
        raise HarnessError(code, message, status=422) from error


def _not_assigned():
    return HarnessError(
        "REVIEW_NOT_ASSIGNED", "Only the assigned referee submits this review.", status=403
    )


class CommonsReviewMixin:
    def _review_node(self, session, node_id, actor):
        """Scope a node, lock its experiment, then re-read the node under that lock."""
        row = self._get(session, "commons_node", node_id, actor)
        experiment = self._commons_experiment(session, row.payload["experiment_id"], actor)
        session.refresh(row)
        return row, experiment

    # Requests ------------------------------------------------------------------

    @staticmethod
    def _review_precondition(node, scope):
        status = node["status"]
        if scope == "fidelity":
            if not node.get("lean_statement") or not node.get("lean_elaborated"):
                raise HarnessError(
                    "LEAN_STATEMENT_REQUIRED",
                    "A fidelity review needs a Lean statement that elaborates.",
                    remediation="Record an elaborated Lean statement with set_lean_statement.",
                )
            allowed = {"informal", "refereed"}
        else:
            allowed = {"informal"}
        if status not in allowed:
            raise HarnessError(
                "REVIEW_PRECONDITION",
                f"A {scope} review does not apply to a {status} node.",
                details={"status": status, "scope": scope},
            )

    @staticmethod
    def _task_review(session, task):
        return session.scalar(
            select(RecordRow.id)
            .where(
                RecordRow.project_id == task.project_id,
                RecordRow.kind == "commons_review",
                record_json_text("experiment_id") == task.payload["experiment_id"],
                record_json_text("task_id") == task.id,
            )
            .limit(1)
        )

    def _open_review_task(self, session, experiment, assignment):
        """The live referee task for this exact assignment that has not yet submitted."""
        tasks = session.scalars(
            select(RecordRow)
            .where(
                RecordRow.project_id == experiment.project_id,
                RecordRow.kind == "task",
                record_json_text("experiment_id") == experiment.id,
                record_json_text("hat") == "referee",
                record_json_text("status").not_in(TERMINAL_TASK_STATUSES),
                RecordRow.payload[("review_assignment", "node_id")].as_string()
                == assignment["node_id"],
            )
            .order_by(RecordRow.id)
            .limit(MAX_OPEN_REVIEWS)
        )
        for task in tasks:
            if (
                task.payload.get("review_assignment") == assignment
                and self._task_review(session, task) is None
            ):
                return task
        return None

    @staticmethod
    def _author_model_index(session, node, models):
        """The author branch's model: its index, or the configuration it inherited."""
        branch = session.get(RecordRow, node.get("branch_id") or "")
        if branch is None or branch.kind != "branch":
            return 0
        index = branch.payload.get("model_index")
        if index is None:
            configuration = branch.payload.get("model_configuration")
            index = models.index(configuration) if configuration in models else 0
        return index

    def request_review(self, node_id, scope, actor, key) -> dict:
        """Assign an independent referee (a detached, lab-less helper branch) to a node."""
        self._research_role(actor)
        if scope not in REVIEW_VERDICTS:
            raise HarnessError(
                "INVALID_REVIEW_SCOPE", "Use scope informal or fidelity.", status=422
            )
        if actor.role == "agent" and not actor.branch_id:
            raise HarnessError(
                "BRANCH_AUTHORITY", "A branch identity is required to request reviews.", status=403
            )

        def action(session, op):
            row, experiment = self._review_node(session, node_id, actor)
            node = row.payload
            self._review_precondition(node, scope)
            assignment = {
                "node_id": row.id,
                "scope": scope,
                "statement_sha256": statement_digest(node),
                "lean_statement_sha256": node["lean_statement_sha256"],
            }
            models = experiment.payload["models"]
            cross_model = len(models) > 1
            existing = self._open_review_task(session, experiment, assignment)
            if existing is not None:
                branch = session.get(RecordRow, existing.payload["branch_id"])
                return {
                    "review_task_id": existing.id,
                    "branch_id": branch.id,
                    "model_index": branch.payload["model_index"],
                    "cross_model": cross_model,
                    "deduplicated": True,
                }
            model_index = (
                (self._author_model_index(session, node, models) + 1) % len(models)
                if cross_model
                else None
            )
            self._admit_research_tasks(session, experiment.id, actor)
            created = self._new_branch_task(
                session,
                op,
                experiment,
                actor,
                title=f"Referee {scope}: {node['title']}"[:200],
                objective=referee_objective(scope, row.id, node),
                parent_id=actor.branch_id,
                relation="helper",
                model_index=model_index,
                detached=True,
                # Independent reviewers are not lab members and fill no lab cap.
                lab=None,
                task_extra={"review_assignment": assignment, "hat": "referee"},
            )
            return {
                "review_task_id": created["task"]["id"],
                "branch_id": created["branch"]["id"],
                "model_index": model_index,
                "cross_model": cross_model,
                "deduplicated": False,
            }

        return self._execute(
            actor, key, "commons.review_request", {"node_id": node_id, "scope": scope}, action
        )

    # Submissions ---------------------------------------------------------------

    def _assigned_review_task(self, session, task_id, actor):
        task = session.get(RecordRow, task_id) if isinstance(task_id, str) else None
        binding = current_worker_effects.get()
        if (
            actor.role != "agent"
            or not actor.branch_id
            or task is None
            or task.kind != "task"
            or task.project_id != actor.project_id
            or task.payload.get("experiment_id") != actor.experiment_id
            or task.payload.get("branch_id") != actor.branch_id
            or not isinstance(task.payload.get("review_assignment"), dict)
            or (binding is not None and binding.task_id != task.id)
        ):
            raise _not_assigned()
        return task

    def _review_tally(self, session, row, scope):
        """Verdict counts and positive review ids among non-stale reviews of the current text.

        Informal reviews count for the current statement digest; fidelity reviews also for the
        current Lean digest. Negative verdicts keep counting until that text changes.
        """
        filters = [
            RecordRow.project_id == row.project_id,
            RecordRow.kind == "commons_review",
            record_json_text("experiment_id") == row.payload["experiment_id"],
            record_json_text("node_id") == row.id,
            record_json_text("scope") == scope,
            record_json_text("statement_sha256") == statement_digest(row.payload),
            RecordRow.payload["stale"].as_boolean().is_(False),
        ]
        if scope == "fidelity":
            filters.append(
                record_json_text("lean_statement_sha256") == row.payload["lean_statement_sha256"]
            )
        verdict = record_json_text("verdict")
        found = dict(
            session.execute(select(verdict, func.count()).where(*filters).group_by(verdict)).all()
        )
        counts = {name: found.get(name, 0) for name in REVIEW_VERDICTS[scope]}
        positive = REVIEW_VERDICTS[scope][0]
        ids = session.scalars(
            select(RecordRow.id)
            .where(*filters, verdict == positive)
            .order_by(RecordRow.id)
            .limit(MAX_EVIDENCE_REVIEWS)
        ).all()
        return counts, list(ids)

    def _refereed_evidence(self, session, row, quorum):
        """Evidence for refereed: a sound quorum that outnumbers every gap and no wrong verdict."""
        counts, ids = self._review_tally(session, row, "informal")
        sound = counts["sound"]
        if sound < quorum or sound <= counts["gaps"] + counts["wrong"] or counts["wrong"]:
            return None
        return {
            "review_ids": ids,
            "counts": counts,
            "statement_sha256": statement_digest(row.payload),
        }

    def _formally_stated_evidence(self, session, row):
        """Evidence for formally_stated: faithful verdicts outnumber unfaithful ones."""
        counts, ids = self._review_tally(session, row, "fidelity")
        if counts["faithful"] < 1 or counts["faithful"] <= counts["unfaithful"]:
            return None
        return {
            "review_ids": ids,
            "counts": counts,
            "lean_statement_sha256": row.payload["lean_statement_sha256"],
        }

    def _review_objection(self, session, op, row, review_id, review, verdict, stale, actor):
        """Post a negative verdict as the referee's objection on the node thread."""
        if not row.payload.get("topic_id"):
            return None
        topic, _, _ = self._discussion_topic(session, row.payload["topic_id"], actor)
        scope = review["scope"]
        lines = [f"Review {review_id}: {scope} verdict {verdict}."]
        if stale:
            lines.append(
                "Stale: this review judged an earlier version of the node; it moves no status."
            )
        lines.append("Objections:")
        lines.extend(
            [f"{index}. {text}" for index, text in enumerate(review["objections"], 1)]
            or ["none listed."]
        )
        return self._insert_post(
            session,
            op,
            topic,
            {
                "kind": "objection",
                "content": "\n".join(lines),
                "abstract": f"Referee ({scope}): {verdict}: {review['summary']}"[:600],
                "artifact_ids": [],
                "reference_post_ids": [],
                "reply_to_post_id": None,
                "node_id": row.id,
                "cites": [],
                "branch_id": actor.branch_id,
            },
            actor,
        )

    def _apply_review(self, session, op, row, experiment, review):
        """Move the ladder for a non-stale review of an open node, when its evidence suffices."""
        status = row.payload["status"]
        if review["scope"] == "informal":
            if review["verdict"] != "sound" or status != "informal":
                return
            quorum = experiment.payload["society"]["referee_quorum"]
            evidence = self._refereed_evidence(session, row, quorum)
            if evidence is not None:
                self._set_node_status(
                    session,
                    row,
                    "refereed",
                    reason=f"referee quorum met ({evidence['counts']['sound']} sound, "
                    f"{quorum} required)",
                    evidence=evidence,
                    op=op,
                )
            return
        if (
            review["verdict"] != "faithful"
            or not row.payload.get("lean_elaborated")
            or status not in {"informal", "refereed"}
        ):
            return
        evidence = self._formally_stated_evidence(session, row)
        if evidence is not None:
            self._set_node_status(
                session,
                row,
                "formally_stated",
                reason="fidelity review: faithful",
                evidence=evidence,
                op=op,
            )

    def submit_review(self, task_id, verdict, summary, objections, actor, key) -> dict:
        """The assigned referee's single verdict; the platform decides what it moves."""
        self._research_role(actor)
        text = _validated(
            _ReviewText,
            "INVALID_REVIEW",
            "A review needs a 1–4000 character summary and at most 10 objections of "
            "1–1000 characters.",
            summary=summary,
            objections=objections,
        )
        inputs = {
            "task_id": task_id,
            "verdict": verdict,
            "summary": text.summary,
            "objections": list(text.objections),
        }

        def action(session, op):
            task = self._assigned_review_task(session, task_id, actor)
            assignment = task.payload["review_assignment"]
            scope = assignment["scope"]
            if verdict not in REVIEW_VERDICTS[scope]:
                raise HarnessError(
                    "INVALID_VERDICT",
                    f"A {scope} review answers one of: {', '.join(REVIEW_VERDICTS[scope])}.",
                    status=422,
                )
            row, experiment = self._review_node(session, assignment["node_id"], actor)
            if self._task_review(session, task) is not None:
                raise HarnessError(
                    "REVIEW_ALREADY_SUBMITTED",
                    "This review task already recorded its verdict.",
                    status=409,
                )
            stale = _stale(assignment, row.payload)
            open_node = row.payload["status"] not in CLOSED_STATUSES
            referee_branch = session.get(RecordRow, task.payload["branch_id"])
            review_id = new_id()
            review = {
                "experiment_id": experiment.id,
                "node_id": row.id,
                "scope": scope,
                "verdict": verdict,
                "summary": text.summary,
                "objections": list(text.objections),
                "task_id": task.id,
                "referee_branch_id": referee_branch.id,
                "model_index": referee_branch.payload.get("model_index"),
                "cross_model": len(experiment.payload["models"]) > 1,
                "statement_sha256": assignment["statement_sha256"],
                "lean_statement_sha256": assignment["lean_statement_sha256"],
                "stale": stale,
            }
            post = None
            if verdict in NEGATIVE_VERDICTS and open_node:
                # A closed node takes no objections, like post_on_node.
                post = self._review_objection(
                    session, op, row, review_id, review, verdict, stale, actor
                )
            record = self._insert(
                session,
                "commons_review",
                actor,
                {**review, "objection_post_id": post["id"] if post else None},
                record_id=review_id,
            )
            self._event(
                session,
                actor,
                op,
                "commons.review_submitted",
                review_id,
                {
                    "experiment_id": experiment.id,
                    "node_id": row.id,
                    "review_id": review_id,
                    "task_id": task.id,
                    "scope": scope,
                    "verdict": verdict,
                    "stale": stale,
                },
            )
            if open_node:
                if not stale:
                    self._apply_review(session, op, row, experiment, record)
                self._touch_node(session, row, actor, op)
            return {**record, "node_status": row.payload["status"]}

        return self._execute(actor, key, "commons.review_submit", inputs, action)

    # Lean statements -----------------------------------------------------------

    def _may_formalize(self, session, row, actor):
        """The author, or a branch holding a live claim on the node."""
        author_branch = row.payload.get("branch_id")
        if (
            author_branch == actor.branch_id
            if author_branch
            else row.payload.get("origin_actor_id") == actor.id
        ):
            return True
        return bool(actor.branch_id) and any(
            claim["branch_id"] == actor.branch_id for claim in self._active_claims(session, row.id)
        )

    def set_lean_statement(
        self, node_id, lean_header, lean_name, lean_statement, elaboration, actor, key
    ) -> dict:
        """Record a node's Lean statement with the platform's elaboration result."""
        self._research_role(actor)
        request = _validated(
            _LeanStatement,
            "INVALID_LEAN_STATEMENT",
            "Supply a valid Lean name, a 1–20000 character statement, a header of at most 2000 "
            "characters and the platform elaboration result {ok, backend, diagnostics_sha256}.",
            lean_header=lean_header,
            lean_name=lean_name,
            lean_statement=lean_statement,
            elaboration=elaboration,
        )
        data = request.model_dump(mode="json")

        def action(session, op):
            row, experiment = self._review_node(session, node_id, actor)
            if row.payload["node_type"] == "goal":
                raise HarnessError(
                    "GOAL_NODE_RESERVED", "The goal mirrors the reviewed target.", status=403
                )
            if row.payload["status"] in CLOSED_STATUSES:
                raise HarnessError("NODE_CLOSED", "A closed node takes no Lean statement.")
            if not self._may_formalize(session, row, actor):
                raise HarnessError(
                    "NODE_AUTHORITY",
                    "Only the author or a live claimant may set the Lean statement.",
                    status=403,
                    remediation="Claim the node first; claims lapse after the policy TTL.",
                )
            previous = row.payload["lean_statement_sha256"]
            digest = _lean_digest(request.lean_header, request.lean_name, request.lean_statement)
            elaborated = request.elaboration.ok
            self._replace(
                session,
                row,
                {
                    "lean_header": request.lean_header,
                    "lean_name": request.lean_name,
                    "lean_statement": request.lean_statement,
                    "lean_statement_sha256": digest,
                    "lean_elaborated": elaborated,
                },
            )
            self._event(
                session,
                actor,
                op,
                "commons.lean_statement_set",
                row.id,
                {
                    "experiment_id": experiment.id,
                    "node_id": row.id,
                    "lean_statement_sha256": digest,
                    "lean_elaborated": elaborated,
                    "backend": request.elaboration.backend,
                    "diagnostics_sha256": request.elaboration.diagnostics_sha256,
                },
            )
            if row.payload["status"] in FORMAL_STATUSES and (digest != previous or not elaborated):
                quorum = experiment.payload["society"]["referee_quorum"]
                self._set_node_status(
                    session,
                    row,
                    "refereed" if self._refereed_evidence(session, row, quorum) else "informal",
                    reason="Lean statement changed"
                    if digest != previous
                    else "Lean statement no longer elaborates",
                    evidence={
                        "lean_statement_sha256": digest,
                        "previous_lean_statement_sha256": previous,
                    },
                    op=op,
                )
            self._touch_node(session, row, actor, op)
            return copy.deepcopy(row.payload)

        return self._execute(
            actor, key, "commons.lean_statement", {"node_id": node_id, **data}, action
        )

    # Local compiles ------------------------------------------------------------

    def record_local_compile(self, node_id, source_sha256, compile_result, actor, key) -> dict:
        """Move a formally stated node to compiles_locally on a complete platform compile."""
        self._research_role(actor)
        if actor.role == "agent" and not actor.branch_id:
            raise HarnessError(
                "BRANCH_AUTHORITY", "A branch identity is required to record compiles.", status=403
            )
        request = _validated(
            _LocalCompile,
            "INVALID_COMPILE_RESULT",
            "Supply a source SHA-256 and the platform compile result "
            "{complete, backend, statement_found, axioms, lean_statement_sha256}.",
            source_sha256=source_sha256,
            compile_result=compile_result,
        )
        data = request.model_dump(mode="json")
        compiled = request.compile_result

        def action(session, op):
            row, _ = self._review_node(session, node_id, actor)
            status = row.payload["status"]
            current = row.payload.get("lean_statement_sha256")
            if current is None:
                return {"recorded": False, "reason": "The node has no Lean statement to compile."}
            if compiled.lean_statement_sha256 != current:
                # The compiled statement is no longer the node's statement.
                return {"recorded": False, "reason": "statement_changed"}
            if status != "formally_stated":
                reason = f"The node is {status}; a local compile counts only when formally_stated."
                return {"recorded": False, "reason": reason}
            if not compiled.complete:
                return {"recorded": False, "reason": "The compile was incomplete."}
            if not compiled.statement_found:
                return {
                    "recorded": False,
                    "reason": "The node's Lean statement was not found in the compiled source.",
                }
            record = self._set_node_status(
                session,
                row,
                "compiles_locally",
                reason="complete local compile",
                evidence={
                    "source_sha256": request.source_sha256,
                    "backend": compiled.backend,
                    "axioms": data["compile_result"]["axioms"],
                },
                op=op,
            )
            self._touch_node(session, row, actor, op)
            return {
                "recorded": True,
                "node_id": row.id,
                "status": record["status"],
                "status_evidence": record["status_evidence"],
            }

        return self._execute(
            actor, key, "commons.local_compile", {"node_id": node_id, **data}, action
        )

    # Goal acceptance -----------------------------------------------------------

    def _commons_goal_accepted(self, session, experiment, receipt_id, op):
        """Persist goal acceptance from a canonical independent-kernel receipt of the target.

        Called inside the verification commit for society experiments only. A goal that is
        already accepted (a later receipt) is left alone.
        """
        if not experiment.payload.get("society"):
            return None
        # Commons writers hold the experiment row lock; take it before writing the goal.
        session.refresh(experiment, with_for_update=True)
        receipt = session.get(RecordRow, receipt_id)
        if receipt is None or not self._accepted_evidence(
            session, receipt, experiment, {"independent_kernel"}
        ):
            return None
        self._goal_node(session, experiment, op)
        goal = self._goal_row(session, experiment)
        session.refresh(goal)
        if "accepted" not in ALLOWED_TRANSITIONS[goal.payload["status"]]:
            return None
        return self._set_node_status(
            session,
            goal,
            "accepted",
            reason="independent kernel receipt",
            evidence={"receipt_id": receipt_id},
            op=op,
        )
