"""Blueprint commons: attributed research nodes, typed edges and a platform-only ladder.

Agents propose nodes and relationships. Status moves only through ``_set_node_status``,
which platform code calls; the single author-initiated move is abandonment with a reason.
"""

import copy
import hashlib
from collections import Counter, defaultdict, deque
from datetime import datetime

from sqlalchemy import select

from .commons_models import (
    ALLOWED_TRANSITIONS,
    CLOSED_STATUSES,
    EDGE_RELATIONS,
    NODE_TYPES,
    STATUSES,
    NodeCreate,
)
from .domain import Principal, new_id, utcnow
from .errors import HarnessError
from .knowledge.index import tokens
from .storage import EdgeRow, RecordRow, record_json_text

PLATFORM = "commons-platform"  # Principal id used for platform-authored inserts/posts
EDGE_PREFIX = "commons:"
DEPENDS_ON = EDGE_PREFIX + "depends_on"
COMMONS_RELATIONS = tuple(EDGE_PREFIX + relation for relation in EDGE_RELATIONS)
MAX_GRAPH_NODES = 5000
MAX_GRAPH_EDGES = 50_000
MAX_RESTS_ON = 500
MAX_EDGE_LIST = 50
MAX_PAGE = 20
MAX_QUERY_TEXT = 2000
ROOT_PATH_SCORE = 3.0
MAX_WAITING_DEPENDENTS = 5
NEGLECT_MINUTES = 30
MAX_NEGLECT = 3.0


def _platform(project_id):
    return Principal(id=PLATFORM, project_id=project_id, role="operator")


def _lean_digest(header, name, statement):
    if statement is None:
        return None
    return hashlib.sha256(f"{header or ''}\n{name}\n{statement}".encode()).hexdigest()


def _not_found():
    return HarnessError("NOT_FOUND", "The requested project object was not found.", status=404)


def _graph_too_large():
    return HarnessError(
        "COMMONS_GRAPH_TOO_LARGE",
        "The commons graph exceeds its bounded traversal.",
        remediation="Narrow the query or consolidate duplicate nodes.",
    )


class CommonsMixin:
    def society_policy(self, experiment_id, actor):
        with self.db.sessions() as session:
            policy = self._get(session, "experiment", experiment_id, actor).payload.get("society")
            return copy.deepcopy(policy)

    def _commons_experiment(self, session, experiment_id, actor, *, active=True):
        """Scope the experiment, require its society policy, and (for mutations) activity."""
        experiment = self._get(session, "experiment", experiment_id, actor)
        if not experiment.payload.get("society") or experiment.payload.get("sharing") != "ideas":
            raise HarnessError(
                "SOCIETY_DISABLED",
                "This experiment has no research-society commons.",
                remediation="Create the experiment with a society policy and ideas sharing.",
            )
        if active:
            self._active(session, experiment_id, actor)
        return experiment

    def _commons_node(self, session, node_id, actor, experiment_id):
        row = self._get(session, "commons_node", node_id, actor)
        if row.payload.get("experiment_id") != experiment_id:
            raise _not_found()
        return row

    @staticmethod
    def _node_payload(experiment, **fields):
        header, name, statement = (
            fields.get("lean_header"),
            fields.get("lean_name"),
            fields.get("lean_statement"),
        )
        return {
            "experiment_id": experiment.id,
            "node_type": fields["node_type"],
            "title": fields["title"],
            "statement": fields["statement"],
            "assumptions": list(fields.get("assumptions", [])),
            "lean_header": header,
            "lean_statement": statement,
            "lean_name": name,
            "lean_statement_sha256": _lean_digest(header, name, statement),
            "lean_elaborated": False,
            "status": fields["status"],
            "status_reason": fields["status_reason"],
            "status_evidence": dict(fields.get("status_evidence") or {}),
            "lab": None,
            "topic_id": None,
            "artifact_ids": list(fields.get("artifact_ids", [])),
            "citation_count": 0,
            "last_activity_at": utcnow().isoformat(),
            "target_digest": experiment.payload["target_digest"],
        }

    # Goal node -----------------------------------------------------------------

    @staticmethod
    def _goal_row(session, experiment):
        return session.scalar(
            select(RecordRow)
            .where(
                RecordRow.project_id == experiment.project_id,
                RecordRow.kind == "commons_node",
                record_json_text("experiment_id") == experiment.id,
                record_json_text("node_type") == "goal",
            )
            .order_by(RecordRow.id)
            .limit(1)
        )

    @staticmethod
    def _reviewed_target(session, experiment):
        target = session.get(RecordRow, experiment.payload["problem_id"])
        if (
            target is None
            or target.kind != "problem"
            or target.project_id != experiment.project_id
            or target.payload.get("semantic_review") != "approved"
            or target.payload.get("target_digest") != experiment.payload.get("target_digest")
        ):
            return None
        return target

    def _goal_node(self, session, experiment, op=None):
        """Create the platform goal once per experiment inside the caller's transaction."""
        self.db.command_lock(session, self._digest(["commons-goal", experiment.id]))
        existing = self._goal_row(session, experiment)
        if existing is not None:
            return existing.payload
        target = self._reviewed_target(session, experiment)
        if target is None:
            raise HarnessError(
                "TARGET_REVIEW_REQUIRED",
                "The goal node mirrors the current reviewed target.",
                remediation="Obtain a recorded target review before using the commons.",
            )
        problem = target.payload
        platform = _platform(experiment.project_id)
        record = self._insert(
            session,
            "commons_node",
            platform,
            {
                **self._node_payload(
                    experiment,
                    node_type="goal",
                    title=problem["title"],
                    statement=problem["informal_statement"][:8000],
                    assumptions=[a[:512] for a in problem.get("assumptions", [])[:32]],
                    status="formally_stated",
                    status_reason="reviewed target",
                    status_evidence={"review_id": problem.get("review_id")},
                ),
                "branch_id": None,
                "formal_target": True,
                "problem_revision_id": target.id,
            },
        )
        self._event(
            session,
            platform,
            op or new_id(),
            "commons.node_created",
            record["id"],
            {"experiment_id": experiment.id, "node_id": record["id"], "node_type": "goal"},
        )
        return record

    def ensure_goal_node(self, experiment_id, actor):
        """Idempotent platform creation of the goal; never changes an existing status."""
        self._research_role(actor)
        with self.db.transaction() as session:
            experiment = self._commons_experiment(session, experiment_id, actor, active=False)
            return copy.deepcopy(self._goal_node(session, experiment))

    def _ensure_goal_for_read(self, experiment_id, actor):
        with self.db.sessions() as session:
            experiment = self._commons_experiment(session, experiment_id, actor, active=False)
            if (
                self._goal_row(session, experiment) is not None
                or self._reviewed_target(session, experiment) is None
            ):
                return
        self.ensure_goal_node(experiment_id, actor)

    def _goal_receipt(self, experiment_id, actor, items):
        if any(i["node_type"] == "goal" and i["status"] != "accepted" for i in items):
            return self.verified_target_receipt(experiment_id, actor)
        return None

    @staticmethod
    def _goal_view(item, receipt):
        """Report (never persist) acceptance evidenced by a current independent receipt."""
        if receipt is None or item["node_type"] != "goal" or item["status"] == "accepted":
            return item
        return {
            **item,
            "status": "accepted",
            "status_derived": True,
            "status_reason": "independent kernel receipt",
            "status_evidence": {"receipt_id": receipt["receipt_id"]},
        }

    # Nodes and edges -----------------------------------------------------------

    def _node_evidence(self, session, identifier, experiment, actor):
        artifact = self._get(session, "artifact", identifier, actor)
        if (
            artifact.payload.get("experiment_id") != experiment.id
            or artifact.payload.get("artifact_kind") in self._private_artifact_kinds
        ):
            raise HarnessError(
                "EVIDENCE_SCOPE", "A referenced artifact is private or outside the experiment."
            )

    def create_node(self, experiment_id, request: NodeCreate, actor, key):
        self._research_role(actor)
        if request.node_type == "goal":
            raise HarnessError(
                "GOAL_NODE_RESERVED", "Only the platform creates the goal node.", status=403
            )
        if actor.role == "agent" and not actor.branch_id:
            raise HarnessError(
                "BRANCH_AUTHORITY", "A branch identity is required to author nodes.", status=403
            )
        data = request.model_dump(mode="json")

        def action(session, op):
            experiment = self._commons_experiment(session, experiment_id, actor)
            for identifier in request.artifact_ids:
                self._node_evidence(session, identifier, experiment, actor)
            record = self._insert(
                session,
                "commons_node",
                actor,
                {
                    **self._node_payload(
                        experiment,
                        **{k: data[k] for k in data if k != "edges"},
                        status="informal",
                        status_reason="proposed",
                    ),
                    "branch_id": actor.branch_id,
                },
            )
            self._event(
                session,
                actor,
                op,
                "commons.node_created",
                record["id"],
                {
                    "experiment_id": experiment_id,
                    "node_id": record["id"],
                    "node_type": request.node_type,
                },
            )
            for edge in request.edges:
                self._add_edge(
                    session, op, experiment, record["id"], edge.relation, edge.target_id, actor
                )
            return record

        return self._execute(
            actor, key, "commons.node_create", {"experiment_id": experiment_id, **data}, action
        )

    def _depends_targets(self, session, node_id, project_id):
        return session.scalars(
            select(EdgeRow.target_id)
            .where(
                EdgeRow.source_id == node_id,
                EdgeRow.relation == DEPENDS_ON,
                EdgeRow.project_id == project_id,
            )
            .order_by(EdgeRow.target_id)
        ).all()

    def _depends_path(self, session, start, goal, project_id):
        """Whether ``goal`` is reachable from ``start`` over depends_on (bounded DFS)."""
        stack, seen = [start], set()
        while stack:
            node = stack.pop()
            if node == goal:
                return True
            if node in seen:
                continue
            seen.add(node)
            if len(seen) > MAX_GRAPH_NODES:
                raise _graph_too_large()
            stack.extend(
                t for t in self._depends_targets(session, node, project_id) if t not in seen
            )
        return False

    def _add_edge(self, session, op, experiment, source_id, relation, target_id, actor):
        if relation not in EDGE_RELATIONS:
            raise HarnessError(
                "INVALID_EDGE", f"Use one of: {', '.join(EDGE_RELATIONS)}.", status=422
            )
        if target_id == source_id:
            raise HarnessError("SELF_EDGE", "A node cannot relate to itself.", status=422)
        self._commons_node(session, target_id, actor, experiment.id)
        stored = EDGE_PREFIX + relation
        if session.get(EdgeRow, (source_id, target_id, stored)) is not None:
            return False
        if relation == "depends_on" and self._depends_path(
            session, target_id, source_id, experiment.project_id
        ):
            raise HarnessError(
                "DEPENDENCY_CYCLE",
                "The target already depends on the source.",
                remediation="Link the dependency in the other direction or split the node.",
            )
        session.add(
            EdgeRow(
                source_id=source_id,
                target_id=target_id,
                relation=stored,
                project_id=experiment.project_id,
            )
        )
        session.flush()
        self._event(
            session,
            actor,
            op,
            "commons.edge_added",
            source_id,
            {
                "experiment_id": experiment.id,
                "source_id": source_id,
                "relation": relation,
                "target_id": target_id,
            },
        )
        return True

    def link_nodes(self, experiment_id, source_id, relation, target_id, actor, key):
        """Any experiment agent may relate nodes; a link is never a status claim."""
        self._research_role(actor)
        if relation not in EDGE_RELATIONS:
            raise HarnessError(
                "INVALID_EDGE", f"Use one of: {', '.join(EDGE_RELATIONS)}.", status=422
            )
        inputs = {
            "experiment_id": experiment_id,
            "source_id": source_id,
            "relation": relation,
            "target_id": target_id,
        }

        def action(session, op):
            experiment = self._commons_experiment(session, experiment_id, actor)
            self._commons_node(session, source_id, actor, experiment_id)
            created = self._add_edge(session, op, experiment, source_id, relation, target_id, actor)
            return {**inputs, "created": created}

        return self._execute(actor, key, "commons.link", inputs, action)

    # Reads ---------------------------------------------------------------------

    def _edge_list(self, session, node_id, actor, *, outgoing):
        here, there = (
            (EdgeRow.source_id, EdgeRow.target_id)
            if outgoing
            else (EdgeRow.target_id, EdgeRow.source_id)
        )
        edges = session.execute(
            select(EdgeRow.relation, there)
            .where(
                here == node_id,
                EdgeRow.project_id == actor.project_id,
                EdgeRow.relation.in_(COMMONS_RELATIONS),
            )
            .order_by(EdgeRow.relation, there)
            .limit(MAX_EDGE_LIST)
        ).all()
        items = []
        for relation, identifier in edges:
            row = session.get(RecordRow, identifier)
            if row is None or row.kind != "commons_node" or not self._in_scope(session, row, actor):
                continue
            items.append(
                {
                    "relation": relation.removeprefix(EDGE_PREFIX),
                    "node_id": identifier,
                    "title": row.payload["title"],
                    "status": row.payload["status"],
                    "node_type": row.payload["node_type"],
                }
            )
        return items

    def _dependencies(self, session, node_id, actor):
        """Breadth-first transitive depends_on closure, bounded for agent reads."""
        seen, queue, found = {node_id}, deque([node_id]), []
        while queue:
            for target in self._depends_targets(session, queue.popleft(), actor.project_id):
                if target in seen:
                    continue
                if len(found) >= MAX_RESTS_ON:
                    return found, True
                seen.add(target)
                row = session.get(RecordRow, target)
                if row is None or row.kind != "commons_node":
                    continue
                if not self._in_scope(session, row, actor):
                    continue
                found.append(
                    {"node_type": row.payload["node_type"], "status": row.payload["status"]}
                )
                queue.append(target)
        return found, False

    def read_node(self, node_id, actor):
        self._research_role(actor)
        with self.db.sessions() as session:
            row = self._get(session, "commons_node", node_id, actor)
            experiment_id = row.payload["experiment_id"]
            self._commons_experiment(session, experiment_id, actor, active=False)
            node = copy.deepcopy(row.payload)
            edges_out = self._edge_list(session, row.id, actor, outgoing=True)
            edges_in = self._edge_list(session, row.id, actor, outgoing=False)
            dependencies, truncated = self._dependencies(session, row.id, actor)
        receipt = self._goal_receipt(
            experiment_id, actor, [node, *edges_out, *edges_in, *dependencies]
        )

        def edge(item):
            view = self._goal_view(item, receipt)
            return {k: view[k] for k in ("relation", "node_id", "title", "status")}

        statuses = [self._goal_view(d, receipt)["status"] for d in dependencies]
        return {
            "node": self._goal_view(node, receipt),
            "edges_out": [edge(e) for e in edges_out],
            "edges_in": [edge(e) for e in edges_in],
            "rests_on": {
                "counts": dict(Counter(statuses)),
                "conditional": any(status != "accepted" for status in statuses),
                "truncated": truncated,
            },
            "claimants": [],
        }

    def _experiment_nodes(self, session, experiment, actor):
        rows = list(
            session.scalars(
                select(RecordRow)
                .where(
                    RecordRow.project_id == experiment.project_id,
                    RecordRow.kind == "commons_node",
                    record_json_text("experiment_id") == experiment.id,
                )
                .order_by(RecordRow.id)
                .limit(MAX_GRAPH_NODES + 1)
            )
        )
        if len(rows) > MAX_GRAPH_NODES:
            raise _graph_too_large()
        # Hold the scope branch so row authorization does not reload it per record.
        _scope_branch = session.get(RecordRow, actor.branch_id) if actor.branch_id else None
        return [row for row in rows if self._in_scope(session, row, actor)]

    @staticmethod
    def _experiment_dependencies(session, experiment):
        nodes = select(RecordRow.id).where(
            RecordRow.project_id == experiment.project_id,
            RecordRow.kind == "commons_node",
            record_json_text("experiment_id") == experiment.id,
        )
        edges = session.execute(
            select(EdgeRow.source_id, EdgeRow.target_id)
            .where(
                EdgeRow.project_id == experiment.project_id,
                EdgeRow.relation == DEPENDS_ON,
                EdgeRow.source_id.in_(nodes),
            )
            .limit(MAX_GRAPH_EDGES + 1)
        ).all()
        if len(edges) > MAX_GRAPH_EDGES:
            raise _graph_too_large()
        return edges

    @staticmethod
    def _node_item(node):
        item = {
            key: node[key]
            for key in ("id", "node_type", "title", "status", "lab", "lean_name", "citation_count")
        }
        item["statement"] = node["statement"][:300]
        if node.get("status_derived"):
            item["status_derived"] = True
        return item

    @staticmethod
    def _frontier(nodes, selected, dependencies, limit):
        """Transparent ranking of open work: root path, waiting dependents, neglect."""
        visible = {node["id"] for node in nodes}
        open_ids = {node["id"] for node in nodes if node["status"] not in CLOSED_STATUSES}
        children, waiting = defaultdict(list), Counter()
        for source, target in dependencies:
            if source in visible and target in visible:
                children[source].append(target)
                if source in open_ids:
                    waiting[target] += 1
        goal = next((node["id"] for node in nodes if node["node_type"] == "goal"), None)
        root_path, queue = ({goal}, deque([goal])) if goal else (set(), deque())
        while queue:
            for target in children[queue.popleft()]:
                if target not in root_path:
                    root_path.add(target)
                    queue.append(target)
        now = utcnow()
        items = []
        for node in selected:
            if node["status"] in CLOSED_STATUSES:
                continue
            idle = (now - datetime.fromisoformat(node["last_activity_at"])).total_seconds()
            components = {
                "on_root_path": ROOT_PATH_SCORE if node["id"] in root_path else 0.0,
                "waiting_dependents": float(min(waiting[node["id"]], MAX_WAITING_DEPENDENTS)),
                "neglect": round(min(max(idle, 0) / 60 / NEGLECT_MINUTES, MAX_NEGLECT), 4),
                "claimants": 0.0,  # -1.0 per live work claim once claims exist
            }
            items.append(
                {
                    **CommonsMixin._node_item(node),
                    "score": round(sum(components.values()), 4),
                    "score_components": components,
                }
            )
        items.sort(key=lambda item: (-item["score"], item["id"]))
        return items[:limit]

    def query_nodes(
        self,
        experiment_id,
        actor,
        *,
        text=None,
        status=None,
        node_type=None,
        frontier=False,
        after=None,
        limit=20,
    ):
        self._research_role(actor)
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
            raise HarnessError(
                "INVALID_PAGE_SIZE", f"Commons page size is 1–{MAX_PAGE}.", status=422
            )
        if (
            (status is not None and status not in STATUSES)
            or (node_type is not None and node_type not in NODE_TYPES)
            or (text is not None and (not isinstance(text, str) or len(text) > MAX_QUERY_TEXT))
            or (after is not None and not isinstance(after, str))
        ):
            raise HarnessError(
                "INVALID_QUERY", "Use a known status and node type and bounded text.", status=422
            )
        if frontier and after is not None:
            raise HarnessError(
                "INVALID_QUERY", "Frontier results are ranked and have no cursor.", status=422
            )
        self._ensure_goal_for_read(experiment_id, actor)
        with self.db.sessions() as session:
            experiment = self._commons_experiment(session, experiment_id, actor, active=False)
            nodes = [
                copy.deepcopy(row.payload)
                for row in self._experiment_nodes(session, experiment, actor)
            ]
            dependencies = self._experiment_dependencies(session, experiment) if frontier else []
        receipt = self._goal_receipt(experiment_id, actor, nodes)
        nodes = [self._goal_view(node, receipt) for node in nodes]
        wanted = tokens(text) if text is not None else None

        def matches(node):
            if status is not None and node["status"] != status:
                return False
            if node_type is not None and node["node_type"] != node_type:
                return False
            if wanted is None:
                return True
            corpus = f"{node['title']} {node['statement']} {node.get('lean_statement') or ''}"
            return bool(wanted & tokens(corpus))

        selected = [node for node in nodes if matches(node)]
        if frontier:
            return {
                "items": self._frontier(nodes, selected, dependencies, limit),
                "next_cursor": None,
            }
        # Order and cursor in one comparison domain, independent of database collation.
        selected = sorted(
            (node for node in selected if after is None or node["id"] > after),
            key=lambda node: node["id"],
        )
        page = selected[:limit]
        return {
            "items": [self._node_item(node) for node in page],
            "next_cursor": page[-1]["id"] if len(selected) > limit else None,
        }

    # Ladder --------------------------------------------------------------------

    def abandon_node(self, node_id, reason, actor, key):
        """The author branch's only status move: close its own open node with a reason."""
        self._research_role(actor)
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise HarnessError(
                "INVALID_REASON", "Abandoning a node needs a 1–2000 character reason.", status=422
            )

        def action(session, op):
            row = self._get(session, "commons_node", node_id, actor)
            self._commons_experiment(session, row.payload["experiment_id"], actor)
            if row.payload["node_type"] == "goal":
                raise HarnessError(
                    "GOAL_NODE_RESERVED", "The goal node cannot be abandoned.", status=403
                )
            author_branch = row.payload.get("branch_id")
            if not (
                author_branch == actor.branch_id
                if author_branch
                else row.payload.get("origin_actor_id") == actor.id
            ):
                raise HarnessError(
                    "NODE_AUTHORITY", "Only the author branch may abandon a node.", status=403
                )
            if row.payload["status"] in CLOSED_STATUSES:
                raise HarnessError("NODE_CLOSED", "The node is already closed.")
            return self._set_node_status(
                session,
                row,
                "abandoned",
                reason=reason,
                evidence={"abandoned_by": actor.id},
                op=op,
            )

        return self._execute(
            actor, key, "commons.node_abandon", {"node_id": node_id, "reason": reason}, action
        )

    def _set_node_status(self, session, row, status, *, reason, evidence, op):
        """The single ladder gate; platform code only (plus author abandonment)."""
        old = row.payload["status"]
        if status not in ALLOWED_TRANSITIONS.get(old, ()):
            raise HarnessError(
                "ILLEGAL_STATUS_TRANSITION",
                f"A node cannot move from {old} to {status}.",
                details={"from": old, "to": status},
            )
        reason = str(reason)[:2000]
        platform = _platform(row.project_id)
        record = self._replace(
            session,
            row,
            {
                "status": status,
                "status_reason": reason,
                "status_evidence": copy.deepcopy(evidence or {}),
                "last_activity_at": utcnow().isoformat(),
            },
        )
        self._event(
            session,
            platform,
            op,
            "commons.node_status",
            record["id"],
            {
                "experiment_id": record["experiment_id"],
                "node_id": record["id"],
                "from": old,
                "to": status,
                "reason": reason,
            },
        )
        self._node_hooks_after_status(session, row, old, status, op)
        return record

    def _node_hooks_after_status(self, session, row, old, new, op):
        """Extension point for thread notifications (no-op until node threads exist)."""
