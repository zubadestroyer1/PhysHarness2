"""Atomic research recruitment with central task admission and opt-in discovery."""

import re

from sqlalchemy import func, select

from .domain import Principal, make_record, new_id, utcnow
from .errors import HarnessError
from .storage import BudgetRow, EdgeRow, EventRow, LeaseRow, RecordRow, record_json_text
from .worker_authority import current_worker_effects
from .workforce_models import (
    LAB_PATTERN,
    ConfigureWorkforceRequest,
    JoinResearchTeamRequest,
    PublishResearchProfileRequest,
    RecruitResearcherRequest,
    RequestResearchCapacityRequest,
    SeedPortfolioRequest,
)

DEFAULT_MAX_TOTAL_TASKS = 10_000
DEFAULT_MAX_PENDING_TASKS = 10_000
LAB_NAME = re.compile(LAB_PATTERN)


def _lab_not_found():
    return HarnessError(
        "LAB_NOT_FOUND",
        "No branch in this experiment belongs to that lab.",
        status=404,
        remediation="Use the lab of an existing branch, or recruit with lab='new'.",
    )


class WorkforceMixin:
    def configure_root_replans(self, task_id, max_replans, actor, key):
        """Bind a finite native-continuation policy to an unstarted root task."""
        if actor.role not in {"operator", "admin"}:
            raise HarnessError("FORBIDDEN", "Controller authority is required.", status=403)
        if type(max_replans) is not int or not 0 <= max_replans <= 8:
            raise HarnessError("ROOT_REPLAN_LIMIT", "Root replan limit must be 0–8.")

        def action(session, op):
            self.db.command_lock(session, self._digest(["task-lease", task_id]))
            task = self._get(session, "task", task_id, actor)
            branch = self._get(session, "branch", task.payload["branch_id"], actor)
            if branch.payload.get("parent_id") or task.payload.get("delegated_from_task_id"):
                raise HarnessError("ROOT_TASK_REQUIRED", "Only a root task can use this policy.")
            existing = task.payload.get("root_replan_limit")
            if existing is not None:
                if existing != max_replans:
                    raise HarnessError(
                        "ROOT_REPLAN_POLICY_CONFLICT", "Root policy is already bound."
                    )
                return task.payload
            if task.payload.get("status") != "queued" or session.get(LeaseRow, task_id):
                raise HarnessError("TASK_NOT_QUEUED", "Bind root policy before first lease.")
            result = self._replace(
                session,
                task,
                {
                    "root_replan_limit": max_replans,
                    "root_replans_used": 0,
                    "root_target_digest": task.payload.get("target_digest")
                    or self._get(
                        session, "experiment", task.payload["experiment_id"], actor
                    ).payload["target_digest"],
                },
            )
            self._event(
                session, actor, op, "task.root_replan_policy", task_id, {"max_replans": max_replans}
            )
            return result

        return self._execute(
            actor,
            key,
            "task.root-replan-policy",
            {
                "task_id": task_id,
                "max_replans": max_replans,
            },
            action,
        )

    def register_component(
        self,
        experiment_id,
        component_key,
        statement,
        owner_task_id,
        artifact_ids,
        actor,
        key,
        *,
        expected_revision=None,
    ):
        """Publish an attributed ownership hint; no proof authority is created."""
        self._research_role(actor)
        if (
            not isinstance(component_key, str)
            or not component_key.strip()
            or len(component_key) > 120
            or not isinstance(statement, str)
            or not statement.strip()
            or len(statement) > 2000
            or not isinstance(artifact_ids, list)
            or len(artifact_ids) > 20
        ):
            raise HarnessError("COMPONENT_INVALID", "Component metadata exceeds bounds.")

        def action(session, op):
            experiment = self._get(session, "experiment", experiment_id, actor)
            owner = self._get(session, "task", owner_task_id, actor)
            if owner.payload.get("experiment_id") != experiment.id:
                raise HarnessError("COMPONENT_SCOPE", "Owner task belongs to another experiment.")
            branch_id = owner.payload["branch_id"]
            self._writable_branch(session, branch_id, actor)
            self.db.command_lock(
                session,
                self._digest(
                    ["component-registry", experiment_id, branch_id, component_key.strip()]
                ),
            )
            for identifier in artifact_ids:
                artifact = self._get(session, "artifact", identifier, actor)
                if artifact.payload.get("experiment_id") != experiment.id:
                    raise HarnessError("COMPONENT_SCOPE", "Evidence belongs to another experiment.")
            values = {
                "experiment_id": experiment_id,
                "branch_id": branch_id,
                "component_key": component_key.strip(),
                "statement": statement.strip(),
                "owner_task_id": owner_task_id,
                "artifact_ids": list(dict.fromkeys(artifact_ids)),
                "proof_status": "unverified",
            }
            existing = session.scalar(
                select(RecordRow)
                .where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.kind == "component_registry",
                    record_json_text("experiment_id") == experiment_id,
                    record_json_text("branch_id") == branch_id,
                    record_json_text("component_key") == component_key.strip(),
                )
                .limit(1)
            )
            if existing:
                if expected_revision is None:
                    raise HarnessError("REVISION_REQUIRED", "Supply current component revision.")
                record = self._replace(session, existing, values, expected_revision)
            else:
                if expected_revision is not None:
                    raise HarnessError("REVISION_CONFLICT", "Component does not yet exist.")
                record = self._insert(session, "component_registry", actor, values)
            self._event(
                session,
                actor,
                op,
                "component.registered",
                record["id"],
                {"experiment_id": experiment_id, "component_key": component_key.strip()},
            )
            return record

        return self._execute(
            actor,
            key,
            "component.register",
            {
                "experiment_id": experiment_id,
                "component_key": component_key,
                "statement": statement,
                "owner_task_id": owner_task_id,
                "artifact_ids": artifact_ids,
                "expected_revision": expected_revision,
            },
            action,
        )

    def component_directory(self, experiment_id, actor, *, after=None, limit=20):
        self._research_role(actor)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise HarnessError("INVALID_PAGE_SIZE", "Directory page size is 1–50.")
        with self.db.sessions() as session:
            experiment = self._get(session, "experiment", experiment_id, actor)
            items = []
            cursor = after
            more = False
            while len(items) < limit + 1:
                query = select(RecordRow).where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.kind == "component_registry",
                    record_json_text("experiment_id") == experiment_id,
                )
                if actor.role == "agent" and experiment.payload.get("sharing") != "ideas":
                    query = query.where(record_json_text("branch_id") == actor.branch_id)
                if cursor:
                    query = query.where(RecordRow.id > cursor)
                rows = list(session.scalars(query.order_by(RecordRow.id).limit(100)))
                if not rows:
                    break
                for row in rows:
                    cursor = row.id
                    if len(items) >= limit:
                        more = True
                        break
                    data = row.payload
                    items.append(self._component_directory_item(session, row, data, actor))
                if more or len(rows) < 100:
                    break
            return {
                "items": items,
                "next_cursor": items[-1]["id"] if more else None,
                "evidence_status": "attributed_registry_only",
            }

    def _component_directory_item(self, session, row, data, actor):
        owner = session.get(RecordRow, data["owner_task_id"])
        status = owner.payload.get("status") if owner else None
        if status in {"completed", "failed", "blocked"} or status is None:
            owner_status = "stale"
        elif status == "running":
            lease = session.get(LeaseRow, data["owner_task_id"])
            live = lease and lease.expires_at > utcnow().timestamp()
            owner_status = "running" if live else "stale"
        else:
            owner_status = "queued"
        return {
            "id": row.id,
            "component_key": data["component_key"],
            "revision": row.revision,
            "statement": data["statement"],
            "branch_id": data["branch_id"],
            "owner_task_id": data["owner_task_id"],
            "owner_status": owner_status,
            "owner_strategy": owner.payload.get("strategy")
            if owner
            and (self._in_scope(session, owner, actor) or self._ideas_shared(session, actor))
            else None,
            "artifact_ids": [
                identifier
                for identifier in data["artifact_ids"]
                if (artifact := session.get(RecordRow, identifier)) is not None
                and self._in_scope(session, artifact, actor)
            ],
            "proof_status": "unverified",
        }

    def _ideas_shared(self, session, actor):
        experiment = session.get(RecordRow, actor.experiment_id) if actor.experiment_id else None
        return bool(experiment and experiment.payload.get("sharing") == "ideas")

    def _workforce_policy(self, session, experiment_id, actor):
        return session.scalar(
            select(RecordRow).where(
                RecordRow.project_id == actor.project_id,
                RecordRow.kind == "workforce_policy",
                record_json_text("experiment_id") == experiment_id,
            )
        )

    def _workforce_lock(self, session, experiment_id, actor):
        # The experiment row is the common scheduling/admission lock for legacy
        # task creation, portfolio seeding and recruitment. SQLite transactions
        # use BEGIN IMMEDIATE; PostgreSQL uses this FOR UPDATE lock.
        return self._active(session, experiment_id, actor)

    def _admit_research_tasks(self, session, experiment_id, actor, count=1):
        self._workforce_lock(session, experiment_id, actor)
        policy = self._workforce_policy(session, experiment_id, actor)
        total_limit = policy.payload["max_total_tasks"] if policy else DEFAULT_MAX_TOTAL_TASKS
        pending_limit = policy.payload["max_pending_tasks"] if policy else DEFAULT_MAX_PENDING_TASKS
        total = session.scalar(
            select(func.count())
            .select_from(RecordRow)
            .where(
                RecordRow.project_id == actor.project_id,
                RecordRow.kind == "task",
                record_json_text("experiment_id") == experiment_id,
            )
        )
        pending = session.scalar(
            select(func.count())
            .select_from(RecordRow)
            .where(
                RecordRow.project_id == actor.project_id,
                RecordRow.kind == "task",
                record_json_text("experiment_id") == experiment_id,
                record_json_text("status").in_(["queued", "running"]),
            )
        )
        if total + count > total_limit:
            raise HarnessError("TASK_TOTAL_CAP", "Experiment task total cap reached.")
        if pending + count > pending_limit:
            raise HarnessError("TASK_PENDING_CAP", "Experiment pending task cap reached.")

    def configure_workforce(
        self, experiment_id: str, request: ConfigureWorkforceRequest, actor: Principal, key: str
    ) -> dict:
        if actor.role not in {"operator", "admin"}:
            raise HarnessError(
                "FORBIDDEN", "Only an operator can set admission policy.", status=403
            )
        data = request.model_dump(mode="json")

        def action(session, op):
            self._workforce_lock(session, experiment_id, actor)
            budget = session.get(BudgetRow, experiment_id)
            if budget is None:
                raise HarnessError("NOT_FOUND", "Experiment ledger is missing.", status=404)
            # This policy contains only task queue caps; the immutable experiment
            # envelope and BudgetRow still authorize money, time and concurrency.
            existing = self._workforce_policy(session, experiment_id, actor)
            values = {
                "max_total_tasks": request.max_total_tasks,
                "max_pending_tasks": request.max_pending_tasks,
                "synthesis_interval_posts": request.synthesis_interval_posts,
            }
            if existing:
                if request.expected_revision is None:
                    raise HarnessError("REVISION_REQUIRED", "Supply current policy revision.")
                record = self._replace(session, existing, values, request.expected_revision)
            else:
                if request.expected_revision is not None:
                    raise HarnessError("REVISION_CONFLICT", "Policy does not yet exist.")
                record = self._insert(
                    session,
                    "workforce_policy",
                    actor,
                    {
                        "experiment_id": experiment_id,
                        "last_synthesis_sequence": 0,
                        "pending_synthesis_post_ids": [],
                        "pending_synthesis_post_count": 0,
                        **values,
                    },
                )
            self._event(
                session,
                actor,
                op,
                "workforce.configured",
                record["id"],
                {
                    "experiment_id": experiment_id,
                },
            )
            return record

        return self._execute(
            actor,
            key,
            "workforce.configure",
            {
                **data,
                "experiment_id": experiment_id,
            },
            action,
        )

    def _new_branch_task(
        self,
        session,
        op,
        experiment,
        actor,
        *,
        title,
        objective,
        parent_id=None,
        relation="competing",
        model_index=None,
        discussion_refs=None,
        synthesis=False,
        synthesis_scope=None,
        detached=False,
        public_summary=None,
        lab="inherit",
    ):
        models = experiment.payload["models"]
        if model_index is not None and model_index >= len(models):
            raise HarnessError("MODEL_NOT_ALLOWED", "Select a recorded experiment model index.")
        parent = None
        if parent_id:
            parent = self._writable_branch(session, parent_id, actor)
            if parent.payload["experiment_id"] != experiment.id:
                raise HarnessError(
                    "BRANCH_EXPERIMENT_MISMATCH", "Parent belongs to another experiment."
                )
            if actor.role == "agent" and parent_id != actor.branch_id:
                raise HarnessError("BRANCH_AUTHORITY", "Recruit from your own branch.", status=403)
        binding = current_worker_effects.get() if actor.role == "agent" else None
        if actor.role == "agent" and parent_id and not detached and binding is None:
            raise HarnessError(
                "PARENT_TASK_REQUIRED", "Joined recruitment requires a current parent task."
            )
        parent_task_id = binding.task_id if binding and parent_id and not detached else None
        selected_model = (
            models[model_index]
            if model_index is not None
            else parent.payload["model_configuration"]
            if parent
            else models[0]
        )
        branch_id = new_id()
        branch = self._insert(
            session,
            "branch",
            actor,
            {
                "title": title,
                "objective": objective,
                "relation": relation,
                "parent_id": parent_id,
                "reply_to_parent": parent_id,
                "checkpoint_id": None,
                "model_index": model_index,
                "experiment_id": experiment.id,
                "target_digest": experiment.payload["target_digest"],
                "status": "open",
                "execution_identity": new_id(),
                "model_configuration": selected_model,
                **self._branch_lab(session, experiment, parent, branch_id, lab),
            },
            record_id=branch_id,
        )
        if parent_id:
            session.add(
                EdgeRow(
                    source_id=branch["id"],
                    target_id=parent_id,
                    relation=relation,
                    project_id=actor.project_id,
                )
            )
        task = self._insert(
            session,
            "task",
            actor,
            {
                "branch_id": branch["id"],
                "objective": objective,
                "dependency_ids": [],
                "detached": detached,
                "experiment_id": experiment.id,
                "status": "queued",
                "evidence_ids": [],
                "created_by": actor.id,
                "reply_to_parent_task_id": parent_task_id,
                "delegated_from_task_id": binding.task_id if binding and parent_id else None,
                "discussion_refs": discussion_refs or [],
                "synthesis": synthesis,
                "synthesis_scope": synthesis_scope,
            },
        )
        if public_summary:
            # The recruiter can opt to publish only this bounded summary for the
            # new child. The child branch's private objective stays scoped.
            profile = make_record(
                "workforce_profile",
                actor,
                {
                    "experiment_id": experiment.id,
                    "branch_id": branch["id"],
                    "published": True,
                    "summary": public_summary,
                    "assignment": "",
                    "interests": [],
                    "origin_actor_id": actor.id,
                },
            )
            session.add(
                RecordRow(
                    id=profile["id"],
                    project_id=actor.project_id,
                    kind="workforce_profile",
                    revision=1,
                    payload=profile,
                )
            )
        self._event(
            session,
            actor,
            op,
            "branch.created",
            branch["id"],
            {
                "experiment_id": experiment.id,
            },
        )
        self._event(
            session,
            actor,
            op,
            "task.queued",
            task["id"],
            {
                "experiment_id": experiment.id,
            },
            dispatch=True,
        )
        return {"branch": branch, "task": task}

    @staticmethod
    def _lab_filter(experiment, lab):
        return (
            RecordRow.project_id == experiment.project_id,
            RecordRow.kind == "branch",
            record_json_text("experiment_id") == experiment.id,
            record_json_text("lab") == lab,
        )

    def _branch_lab(self, session, experiment, parent, branch_id, lab="inherit"):
        """Resolve a new branch's lab and admit it under the cap.

        Returns the payload fields to merge: ``{}`` for legacy experiments (their branch
        payloads carry no lab key) and ``{"lab": name_or_None}`` for society experiments.
        ``"inherit"`` joins the parent's lab (a root founds one), ``"new"`` founds
        ``"lab-" + branch_id[:8]``, a name joins that existing lab, and ``None`` records an
        unaffiliated branch (e.g. an independent referee) that no lab counts.
        """
        policy = experiment.payload.get("society")
        if not policy:
            if lab not in {"inherit", None}:
                raise HarnessError(
                    "SOCIETY_DISABLED",
                    "Labs exist only in research-society experiments.",
                    remediation="Omit the lab for experiments without a society policy.",
                )
            return {}
        if lab == "inherit":
            lab = "new" if parent is None else parent.payload.get("lab")
        if lab is None:
            return {"lab": None}
        if lab == "new":
            return {"lab": "lab-" + branch_id[:8]}
        if not isinstance(lab, str) or not LAB_NAME.fullmatch(lab):
            raise HarnessError("INVALID_LAB", "Lab names match ^[a-z0-9-]{1,40}$.", status=422)
        # Serialize joins per lab so concurrent recruits cannot overshoot the cap.
        self.db.command_lock(session, self._digest(["lab", experiment.id, lab]))
        members = session.scalar(
            select(func.count()).select_from(RecordRow).where(*self._lab_filter(experiment, lab))
        )
        if not members:
            raise _lab_not_found()
        if members >= policy["lab_size_max"]:
            raise HarnessError(
                "LAB_FULL",
                f"Lab {lab} already has {members} of {policy['lab_size_max']} members.",
                status=409,
                remediation="Recruit into a new lab (lab='new') or another lab with room.",
            )
        return {"lab": lab}

    def lab_members(self, experiment_id, lab, actor) -> dict:
        """Bounded roster of one society lab: branch id, title and status per member."""
        self._research_role(actor)
        if not isinstance(lab, str) or not LAB_NAME.fullmatch(lab):
            raise HarnessError("INVALID_LAB", "Lab names match ^[a-z0-9-]{1,40}$.", status=422)
        with self.db.sessions() as session:
            experiment = self._commons_experiment(session, experiment_id, actor, active=False)
            size_max = experiment.payload["society"]["lab_size_max"]
            # Joins are capped, so the roster never exceeds size_max rows.
            rows = session.scalars(
                select(RecordRow)
                .where(*self._lab_filter(experiment, lab))
                .order_by(record_json_text("created_at"), RecordRow.id)
                .limit(size_max)
            ).all()
            if not rows:
                raise _lab_not_found()
            return {
                "lab": lab,
                "members": [
                    {
                        "branch_id": row.id,
                        "title": row.payload["title"],
                        "status": row.payload["status"],
                    }
                    for row in rows
                ],
                "size_max": size_max,
            }

    def seed_portfolio(
        self, experiment_id: str, request: SeedPortfolioRequest, actor: Principal, key: str
    ) -> dict:
        if actor.role not in {"operator", "admin"}:
            raise HarnessError("FORBIDDEN", "Only an operator can seed roots.", status=403)
        data = request.model_dump(mode="json")

        def action(session, op):
            experiment = self._workforce_lock(session, experiment_id, actor)
            self._admit_research_tasks(session, experiment_id, actor, len(request.roots))
            roots = [
                self._new_branch_task(
                    session,
                    op,
                    experiment,
                    actor,
                    title=root.title,
                    objective=root.objective,
                    model_index=root.model_index,
                    public_summary=root.public_summary,
                )
                for root in request.roots
            ]
            return {"experiment_id": experiment_id, "roots": roots}

        return self._execute(
            actor,
            key,
            "workforce.seed",
            {
                **data,
                "experiment_id": experiment_id,
            },
            action,
        )

    def recruit_researcher(
        self, experiment_id: str, request: RecruitResearcherRequest, actor: Principal, key: str
    ) -> dict:
        self._research_role(actor)
        # Legacy command fingerprints predate labs; the key appears only when supplied.
        data = request.model_dump(mode="json", exclude={"lab"} if request.lab is None else None)

        def action(session, op):
            experiment = self._workforce_lock(session, experiment_id, actor)
            refs = request.discussion_refs
            if len(set(refs)) != len(refs):
                raise HarnessError("DUPLICATE_REFERENCE", "Discussion references must be unique.")
            if request.synthesis and not refs:
                raise HarnessError("SYNTHESIS_REFS_REQUIRED", "Synthesis needs source posts.")
            for identifier in refs:
                post = self._get(session, "discussion_post", identifier, actor)
                if (
                    post.payload.get("experiment_id") != experiment_id
                    or post.payload.get("target_digest") != experiment.payload["target_digest"]
                ):
                    raise HarnessError(
                        "DISCUSSION_SCOPE", "Source post targets another experiment."
                    )
            self._admit_research_tasks(session, experiment_id, actor)
            result = self._new_branch_task(
                session,
                op,
                experiment,
                actor,
                title=request.title,
                objective=request.objective,
                parent_id=request.parent_branch_id,
                relation=request.relation,
                model_index=request.model_index,
                discussion_refs=refs,
                synthesis=request.synthesis,
                detached=request.detached,
                public_summary=request.public_summary,
                lab="inherit" if request.lab is None else request.lab,
            )
            return {"experiment_id": experiment_id, **result}

        return self._execute(
            actor,
            key,
            "workforce.recruit",
            {
                **data,
                "experiment_id": experiment_id,
            },
            action,
        )

    def _branch_owner(self, session, experiment_id, branch_id, actor):
        branch = self._writable_branch(session, branch_id, actor)
        if branch.payload["experiment_id"] != experiment_id:
            raise HarnessError(
                "BRANCH_EXPERIMENT_MISMATCH", "Branch belongs to another experiment."
            )
        return branch

    def _latest_branch_record(self, session, kind, experiment_id, branch_id, actor):
        return session.scalar(
            select(RecordRow)
            .where(
                RecordRow.project_id == actor.project_id,
                RecordRow.kind == kind,
                record_json_text("experiment_id") == experiment_id,
                record_json_text("branch_id") == branch_id,
            )
            .order_by(record_json_text("created_at").desc(), RecordRow.id.desc())
            .limit(1)
        )

    def _public_team_labels(self, session, experiment_id, branch_id, actor):
        team = record_json_text("team")
        latest = (
            select(
                team.label("team"),
                RecordRow.payload["joined"].as_boolean().label("joined"),
                func.row_number()
                .over(
                    partition_by=team,
                    order_by=(record_json_text("created_at").desc(), RecordRow.id.desc()),
                )
                .label("rank"),
            )
            .where(
                RecordRow.project_id == actor.project_id,
                RecordRow.kind == "workforce_team",
                record_json_text("experiment_id") == experiment_id,
                record_json_text("branch_id") == branch_id,
            )
            .subquery()
        )
        return list(
            session.scalars(
                select(latest.c.team)
                .where(
                    latest.c.rank == 1,
                    latest.c.joined.is_(True),
                )
                .order_by(latest.c.team)
                .limit(12)
            )
        )

    def _public_team_directory(self, session, experiment_id, actor):
        team = record_json_text("team")
        branch = record_json_text("branch_id")
        latest = (
            select(
                team.label("team"),
                branch.label("branch_id"),
                RecordRow.payload["joined"].as_boolean().label("joined"),
                func.row_number()
                .over(
                    partition_by=(branch, team),
                    order_by=(record_json_text("created_at").desc(), RecordRow.id.desc()),
                )
                .label("rank"),
            )
            .where(
                RecordRow.project_id == actor.project_id,
                RecordRow.kind == "workforce_team",
                record_json_text("experiment_id") == experiment_id,
            )
            .subquery()
        )
        members = session.execute(
            select(latest.c.team, func.count())
            .where(
                latest.c.rank == 1,
                latest.c.joined.is_(True),
            )
            .group_by(latest.c.team)
            .order_by(latest.c.team)
            .limit(50)
        ).all()
        return [{"name": name, "member_count": count} for name, count in members]

    def publish_research_profile(
        self, experiment_id: str, request: PublishResearchProfileRequest, actor: Principal, key: str
    ) -> dict:
        self._research_role(actor)
        data = request.model_dump(mode="json")

        def action(session, op):
            self._workforce_lock(session, experiment_id, actor)
            self._branch_owner(session, experiment_id, request.branch_id, actor)
            if request.published and not request.summary.strip():
                raise HarnessError("PROFILE_SUMMARY_REQUIRED", "Published profile needs a summary.")
            record = self._insert(
                session,
                "workforce_profile",
                actor,
                {
                    **data,
                    "experiment_id": experiment_id,
                },
            )
            self._event(
                session,
                actor,
                op,
                "workforce.profile",
                record["id"],
                {
                    "experiment_id": experiment_id,
                },
            )
            return record

        return self._execute(
            actor,
            key,
            "workforce.profile",
            {
                **data,
                "experiment_id": experiment_id,
            },
            action,
        )

    def research_directory(
        self, experiment_id: str, actor: Principal, *, after: str | None = None, limit: int = 20
    ) -> dict:
        self._research_role(actor)
        if not 1 <= limit <= 50:
            raise HarnessError("INVALID_PAGE_SIZE", "Directory page size is 1–50.", status=422)
        with self.db.sessions() as session:
            self._get(session, "experiment", experiment_id, actor)
            # Directory discovery is opt-in even when the experiment shares ideas.
            # A raw profile record is never returned; only its public fields are.
            query = select(RecordRow).where(
                RecordRow.project_id == actor.project_id,
                RecordRow.kind == "workforce_profile",
                record_json_text("experiment_id") == experiment_id,
            )
            if after:
                query = query.where(RecordRow.id > after)
            rows = list(session.scalars(query.order_by(RecordRow.id).limit(201)))
            items = []
            last = None
            scanned = 0
            for row in rows[:200]:
                scanned += 1
                last = row.id
                data = row.payload
                latest = self._latest_branch_record(
                    session, "workforce_profile", experiment_id, data["branch_id"], actor
                )
                if latest.id != row.id or not data["published"]:
                    continue
                items.append(
                    {
                        "branch_id": data["branch_id"],
                        "summary": data["summary"],
                        "interests": data["interests"],
                        "profile_id": row.id,
                        "assignment": data.get("assignment", ""),
                        "teams": self._public_team_labels(
                            session, experiment_id, data["branch_id"], actor
                        ),
                    }
                )
                if len(items) >= limit:
                    break
            return {
                "items": items,
                "next_cursor": last if last and scanned < len(rows) else None,
                "teams": self._public_team_directory(session, experiment_id, actor),
            }

    def join_research_team(
        self, experiment_id: str, request: JoinResearchTeamRequest, actor: Principal, key: str
    ) -> dict:
        self._research_role(actor)
        data = request.model_dump(mode="json")

        def action(session, op):
            self._workforce_lock(session, experiment_id, actor)
            self._branch_owner(session, experiment_id, request.branch_id, actor)
            active = self._public_team_labels(session, experiment_id, request.branch_id, actor)
            if request.joined and request.team not in active and len(active) >= 12:
                raise HarnessError("TEAM_LIMIT", "A branch may join at most twelve teams.")
            record = self._insert(
                session,
                "workforce_team",
                actor,
                {
                    **data,
                    "experiment_id": experiment_id,
                },
            )
            self._event(
                session,
                actor,
                op,
                "workforce.team",
                record["id"],
                {
                    "experiment_id": experiment_id,
                },
            )
            return record

        return self._execute(
            actor,
            key,
            "workforce.team",
            {
                **data,
                "experiment_id": experiment_id,
            },
            action,
        )

    def research_capacity(self, experiment_id: str, actor: Principal) -> dict:
        self._research_role(actor)
        with self.db.sessions() as session:
            self._get(session, "experiment", experiment_id, actor)
            budget = session.get(BudgetRow, experiment_id)
            policy = self._workforce_policy(session, experiment_id, actor)
            statuses = dict(
                session.execute(
                    select(
                        record_json_text("status"),
                        func.count(),
                    )
                    .select_from(RecordRow)
                    .where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "task",
                        record_json_text("experiment_id") == experiment_id,
                    )
                    .group_by(record_json_text("status"))
                ).all()
            )
            queued, running = statuses.get("queued", 0), statuses.get("running", 0)
            requests = list(
                session.scalars(
                    select(RecordRow)
                    .where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "workforce_capacity_request",
                        record_json_text("experiment_id") == experiment_id,
                    )
                    .order_by(RecordRow.id.desc())
                    .limit(20)
                )
            )
            return {
                "experiment_id": experiment_id,
                "queued_tasks": queued,
                "running_tasks": running,
                "total_tasks": sum(statuses.values()),
                "max_total_tasks": policy.payload["max_total_tasks"]
                if policy
                else DEFAULT_MAX_TOTAL_TASKS,
                "max_pending_tasks": policy.payload["max_pending_tasks"]
                if policy
                else DEFAULT_MAX_PENDING_TASKS,
                "synthesis_interval_posts": policy.payload.get("synthesis_interval_posts", 0)
                if policy
                else 0,
                "active_workers": budget.active_workers,
                "max_concurrency": budget.max_concurrency,
                "requests": [
                    {
                        "id": r.id,
                        "branch_id": r.payload["branch_id"],
                        "requested_workers": r.payload["requested_workers"],
                        "rationale": r.payload["rationale"],
                    }
                    for r in requests
                    if actor.role != "agent" or r.payload["branch_id"] == actor.branch_id
                ],
            }

    def request_research_capacity(
        self,
        experiment_id: str,
        request: RequestResearchCapacityRequest,
        actor: Principal,
        key: str,
    ) -> dict:
        self._research_role(actor)
        data = request.model_dump(mode="json")

        def action(session, op):
            self._workforce_lock(session, experiment_id, actor)
            self._branch_owner(session, experiment_id, request.branch_id, actor)
            record = self._insert(
                session,
                "workforce_capacity_request",
                actor,
                {
                    **data,
                    "experiment_id": experiment_id,
                    "status": "requested",
                    "granted_workers": 0,
                },
            )
            self._event(
                session,
                actor,
                op,
                "workforce.capacity_requested",
                record["id"],
                {
                    "experiment_id": experiment_id,
                },
            )
            return record

        return self._execute(
            actor,
            key,
            "workforce.capacity_request",
            {
                **data,
                "experiment_id": experiment_id,
            },
            action,
        )

    def schedule_research_synthesis(self, experiment_id: str, actor: Principal, key: str) -> dict:
        """Queue one ordinary synthesis task when new public discourse merits it.

        A controller may call this at a safe coordination tick. No model is
        invoked here; the returned task runs through the normal scheduler.
        """
        if actor.role not in {"operator", "admin"}:
            raise HarnessError("FORBIDDEN", "Only a controller schedules synthesis.", status=403)

        def action(session, op):
            experiment = self._workforce_lock(session, experiment_id, actor)
            policy = self._workforce_policy(session, experiment_id, actor)
            interval = policy.payload.get("synthesis_interval_posts", 0) if policy else 0
            if not interval:
                return {"scheduled": False, "reason": "disabled"}
            if experiment.payload.get("sharing") != "ideas":
                return {"scheduled": False, "reason": "ideas_sharing_required"}
            outstanding = session.scalar(
                select(RecordRow.id)
                .where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.kind == "task",
                    record_json_text("experiment_id") == experiment_id,
                    RecordRow.payload["synthesis"].as_boolean().is_(True),
                    record_json_text("status").in_(["queued", "running"]),
                )
                .limit(1)
            )
            if outstanding:
                return {"scheduled": False, "reason": "outstanding", "task_id": outstanding}
            watermark = policy.payload.get("last_synthesis_sequence", 0)
            events = list(
                session.scalars(
                    select(EventRow)
                    .where(
                        EventRow.project_id == actor.project_id,
                        EventRow.kind == "discussion.post_created",
                        EventRow.sequence > watermark,
                        EventRow.payload["experiment_id"].as_string() == experiment_id,
                    )
                    .order_by(EventRow.sequence)
                    .limit(101)
                )
            )
            if not events:
                return {"scheduled": False, "reason": "no_new_posts"}
            posts = []
            target = session.get(RecordRow, experiment.payload["problem_id"])
            if target is None or target.project_id != actor.project_id:
                raise HarnessError("TARGET_SCOPE", "Experiment target is missing.")
            for event in events[:100]:
                post_id = event.payload.get("post_id")
                if not post_id:
                    raise HarnessError(
                        "DISCUSSION_EVENT_SCOPE", "Discussion event lacks a post ID."
                    )
                post = self._get(session, "discussion_post", post_id, actor)
                if (
                    post.payload.get("experiment_id") != experiment_id
                    or post.payload.get("target_digest") != experiment.payload["target_digest"]
                    or post.payload.get("environment_digest")
                    != target.payload.get("environment_digest")
                ):
                    raise HarnessError("DISCUSSION_SCOPE", "Discussion source target changed.")
                posts.append((event.sequence, post))
            source_ids = list(policy.payload.get("pending_synthesis_post_ids", []))
            eligible_count = policy.payload.get("pending_synthesis_post_count", 0)
            sampled = [
                self._get(session, "discussion_post", identifier, actor)
                for identifier in source_ids
            ]
            sampled_topics = {post.payload["topic_id"] for post in sampled}
            first_topic = sampled[0].payload["topic_id"] if sampled else None
            for _, post in posts:
                eligible_count += 1
                if len(source_ids) < 20:
                    source_ids.append(post.id)
                    sampled.append(post)
                    sampled_topics.add(post.payload["topic_id"])
                    if first_topic is None:
                        first_topic = post.payload["topic_id"]
                elif post.payload["topic_id"] != first_topic:
                    # Bounded sample retains the first nineteen exact sources
                    # and one source from a different topic, even after a long
                    # single-topic backlog.
                    if len(sampled_topics) == 1:
                        source_ids[-1] = post.id
                        sampled[-1] = post
                        sampled_topics.add(post.payload["topic_id"])
            through = events[min(len(events), 100) - 1].sequence if events else watermark
            topic_ids = sorted(sampled_topics)
            if eligible_count < interval or len(topic_ids) < 2:
                self._replace(
                    session,
                    policy,
                    {
                        "last_synthesis_sequence": through,
                        "pending_synthesis_post_ids": source_ids,
                        "pending_synthesis_post_count": eligible_count,
                    },
                    policy.revision,
                )
                return {
                    "scheduled": False,
                    "reason": "insufficient_posts" if eligible_count < interval else "single_topic",
                    "eligible_posts": eligible_count,
                    "through_sequence": through,
                }
            self._admit_research_tasks(session, experiment_id, actor)
            objective = (
                "Compare only the sampled, attributed posts in discussion_refs. "
                "Preserve disagreements and objections present in those sampled posts "
                "with exact source IDs; do not claim to cover all discussion. "
                "Identify useful next experiments; treat every claim as unverified "
                "until the normal verifier accepts independent evidence."
            )
            parent_branch_id = sampled[0].payload.get("branch_id")
            if not parent_branch_id:
                return {"scheduled": False, "reason": "source_branch_missing"}
            result = self._new_branch_task(
                session,
                op,
                experiment,
                actor,
                title="Research discussion synthesis",
                objective=objective,
                parent_id=parent_branch_id,
                discussion_refs=source_ids,
                synthesis=True,
                synthesis_scope={
                    "coverage": "bounded_sample",
                    "eligible_post_count": eligible_count,
                    "sampled_post_count": len(source_ids),
                    "through_sequence": through,
                },
                detached=True,
                public_summary="Synthesis of sampled public research discussions",
                # Synthesizers review across labs; they neither join nor fill the source lab.
                lab=None,
            )
            self._replace(
                session,
                policy,
                {
                    "last_synthesis_sequence": through,
                    "pending_synthesis_post_ids": [],
                    "pending_synthesis_post_count": 0,
                },
                policy.revision,
            )
            return {
                "scheduled": True,
                "experiment_id": experiment_id,
                "source_post_ids": source_ids,
                "source_topic_ids": topic_ids,
                "through_sequence": through,
                "eligible_post_count": eligible_count,
                "sampled_post_count": len(source_ids),
                "parent_branch_id": parent_branch_id,
                **result,
            }

        return self._execute(
            actor,
            key,
            "workforce.synthesis_schedule",
            {
                "experiment_id": experiment_id,
            },
            action,
        )
