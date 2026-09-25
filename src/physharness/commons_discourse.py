"""Commons discourse: expiring work claims, node threads and urgent digest items.

A claim is an attention signal, never authority: several branches may hold one node, and a
claim lapses when its ``expires_at`` passes, compared at read time (no background job).
Auto-subscriptions are best-effort and never push a reader past its subscription cap.
"""

import json
import time
from collections import Counter

from sqlalchemy import select

from .commons import MAX_PAGE, PLATFORM, _platform
from .commons_models import CLOSED_STATUSES, NodePostCreate
from .domain import utcnow
from .errors import HarnessError
from .storage import RecordRow, record_json_text
from .worker_authority import current_worker_effects

_now = time.time  # Epoch seconds; tests patch this module attribute.
CLAIM_ACTIONS = ("claim", "renew", "release")
CLOSED_NODE_POST_KINDS = frozenset({"synthesis", "update"})
URGENT_STATUSES = frozenset({"accepted", "refuted"})
EXCERPT_BYTES = 1024
ITEM_BYTES = 2048
MAX_LIVE_CLAIMS = 1000  # Bounded claim scan; read_node shows at most MAX_PAGE claimants.


def _claim_not_held():
    return HarnessError(
        "CLAIM_NOT_HELD",
        "This branch holds no live claim on the node.",
        remediation="Claim the node first; claims lapse after the policy TTL.",
    )


def _node_closed(message):
    return HarnessError("NODE_CLOSED", message)


class CommonsDiscourseMixin:
    # Claims --------------------------------------------------------------------

    @staticmethod
    def _claim_live(claim, now):
        return not claim["released"] and claim["expires_at"] > now

    @staticmethod
    def _live_claim_rows(session, project_id, experiment_id, now, node_id=None, branch_id=None):
        query = select(RecordRow).where(
            RecordRow.project_id == project_id,
            RecordRow.kind == "commons_claim",
            record_json_text("experiment_id") == experiment_id,
            RecordRow.payload["released"].as_boolean().is_(False),
            RecordRow.payload["expires_at"].as_float() > now,
        )
        if node_id is not None:
            query = query.where(record_json_text("node_id") == node_id)
        if branch_id is not None:
            query = query.where(record_json_text("branch_id") == branch_id)
        return session.scalars(query.order_by(RecordRow.id).limit(MAX_LIVE_CLAIMS))

    @staticmethod
    def _claim_row(session, node_row, branch_id):
        return session.scalar(
            select(RecordRow)
            .where(
                RecordRow.project_id == node_row.project_id,
                RecordRow.kind == "commons_claim",
                record_json_text("experiment_id") == node_row.payload["experiment_id"],
                record_json_text("node_id") == node_row.id,
                record_json_text("branch_id") == branch_id,
            )
            .order_by(RecordRow.id)
            .limit(1)
        )

    def _active_claims(self, session, node_id, now=None):
        """Live (unreleased, unexpired) claims on a node, ordered by branch."""
        node = session.get(RecordRow, node_id)
        if node is None or node.kind != "commons_node":
            return []
        now = _now() if now is None else now
        rows = self._live_claim_rows(
            session, node.project_id, node.payload["experiment_id"], now, node_id
        )
        claims = [
            {
                "branch_id": row.payload["branch_id"],
                "task_id": row.payload["task_id"],
                "expires_at": row.payload["expires_at"],
            }
            for row in rows
        ]
        return sorted(claims, key=lambda claim: claim["branch_id"])

    def _live_claim_counts(self, session, experiment, now=None):
        """Live claims per node across the experiment, for the frontier score."""
        now = _now() if now is None else now
        rows = self._live_claim_rows(session, experiment.project_id, experiment.id, now)
        return Counter(row.payload["node_id"] for row in rows)

    def branch_claims(self, experiment_id, actor, *, limit=MAX_PAGE):
        """The actor branch's live work claims (its focus nodes), with each node's summary."""
        self._research_role(actor)
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
            raise HarnessError(
                "INVALID_PAGE_SIZE", f"Commons page size is 1–{MAX_PAGE}.", status=422
            )
        if not actor.branch_id:
            return {"items": []}
        with self.db.sessions() as session:
            experiment = self._commons_experiment(session, experiment_id, actor, active=False)
            rows = list(
                self._live_claim_rows(
                    session, experiment.project_id, experiment.id, _now(), branch_id=actor.branch_id
                )
            )[:limit]
            summaries = self._node_summaries(
                session, experiment, actor, {row.payload["node_id"] for row in rows}
            )
        return {
            "items": [
                {
                    "node_id": row.payload["node_id"],
                    **summaries[row.payload["node_id"]],
                    "expires_at": row.payload["expires_at"],
                }
                for row in rows
                if row.payload["node_id"] in summaries
            ]
        }

    def _claim_event(self, session, actor, op, claim, action):
        self._event(
            session,
            actor,
            op,
            "commons.node_claim",
            claim["node_id"],
            {
                "experiment_id": claim["experiment_id"],
                "node_id": claim["node_id"],
                "branch_id": claim["branch_id"],
                "action": action,
                "expires_at": claim["expires_at"],
            },
        )

    def claim_node(self, node_id, action, actor, key):
        """Claim, renew or release this branch's expiring work claim on a node."""
        self._research_role(actor)
        if action not in CLAIM_ACTIONS:
            raise HarnessError(
                "INVALID_CLAIM_ACTION", f"Use one of: {', '.join(CLAIM_ACTIONS)}.", status=422
            )
        if not actor.branch_id:
            raise HarnessError(
                "BRANCH_AUTHORITY", "A branch identity is required to claim work.", status=403
            )
        branch_id = actor.branch_id

        def apply(session, op):
            row = self._get(session, "commons_node", node_id, actor)
            experiment = self._commons_experiment(session, row.payload["experiment_id"], actor)
            # Under the experiment lock: see writes committed while this command waited.
            session.refresh(row)
            if action != "release" and row.payload["status"] in CLOSED_STATUSES:
                raise _node_closed("A closed node takes no work claims.")
            # Reader lock before claim lock, the same order as post_on_node.
            subscribed = (
                self._auto_subscribe(session, op, row.payload.get("topic_id"), branch_id, actor)
                if action == "claim"
                else None
            )
            self.db.command_lock(session, self._digest(["commons-claim", node_id, branch_id]))
            prior = self._claim_row(session, row, branch_id)
            now = _now()
            held = prior is not None and self._claim_live(prior.payload, now)
            if action == "release":
                if prior is None:
                    raise _claim_not_held()
                record = self._replace(session, prior, {"released": True})
            else:
                if action == "renew" and not held:
                    raise _claim_not_held()
                binding = current_worker_effects.get()
                values = {
                    "task_id": binding.task_id
                    if binding is not None
                    else (prior.payload["task_id"] if held else None),
                    "expires_at": now + experiment.payload["society"]["claim_ttl_seconds"],
                    "released": False,
                }
                if prior is None:
                    record = self._insert(
                        session,
                        "commons_claim",
                        actor,
                        {
                            "experiment_id": experiment.id,
                            "node_id": row.id,
                            "branch_id": branch_id,
                            **values,
                        },
                    )
                else:
                    record = self._replace(session, prior, values)
            self._claim_event(session, actor, op, record, action)
            if subscribed is not None:
                record = {**record, "auto_subscribed": subscribed}
            return record

        return self._execute(
            actor, key, "commons.claim", {"node_id": node_id, "action": action}, apply
        )

    def _touch_node(self, session, row, actor, op):
        """Record activity on a node and extend the actor's live claim on it, if any."""
        self._replace(session, row, {"last_activity_at": utcnow().isoformat()})
        if not actor.branch_id or row.payload["status"] in CLOSED_STATUSES:
            return
        self.db.command_lock(session, self._digest(["commons-claim", row.id, actor.branch_id]))
        claim = self._claim_row(session, row, actor.branch_id)
        now = _now()
        if claim is None or not self._claim_live(claim.payload, now):
            return
        experiment = session.get(RecordRow, row.payload["experiment_id"])
        record = self._replace(
            session,
            claim,
            {"expires_at": now + experiment.payload["society"]["claim_ttl_seconds"]},
        )
        self._claim_event(session, actor, op, record, "renew")

    # Threads and subscriptions -------------------------------------------------

    def _open_node_thread(self, session, op, experiment, node, actor):
        """Create the node's topic in the caller's transaction and store its id on the node."""
        _, target = self._discussion_experiment(session, experiment.id, actor)
        topic = self._insert_topic(
            session,
            op,
            experiment,
            target,
            node["branch_id"],
            f"[{node['node_type']}] {node['title']}"[:200],
            node["statement"][:4000],
            actor,
            node_id=node["id"],
        )
        return self._replace(session, session.get(RecordRow, node["id"]), {"topic_id": topic["id"]})

    def _auto_subscribe(self, session, op, topic_id, branch_id, actor):
        """Best-effort subscription of a branch reader to a node thread.

        Never pushes the reader past its 100-subscription cap. At the cap it first frees the
        slot of the reader's oldest closed-node thread; failing that it returns False instead
        of raising, so the reader's inbox keeps working. Another branch's reader is written by
        the platform.
        """
        if not topic_id or not branch_id:
            return False
        topic = session.get(RecordRow, topic_id)
        if topic is None or topic.kind != "discussion_topic":
            return False
        writer = actor if actor.branch_id == branch_id else _platform(topic.project_id)
        if self._try_subscribe(session, op, topic, branch_id, writer):
            return True
        return self._release_closed_thread(
            session, op, topic.payload["experiment_id"], branch_id, writer
        ) and self._try_subscribe(session, op, topic, branch_id, writer)

    def _try_subscribe(self, session, op, topic, branch_id, writer):
        try:
            self._set_subscription(session, op, topic, branch_id, True, writer)
        except HarnessError as error:
            if error.code != "SUBSCRIPTION_LIMIT":
                raise
            return False
        return True

    def _release_closed_thread(self, session, op, experiment_id, branch_id, writer):
        """Unsubscribe a branch reader from its oldest closed-node thread; False if none.

        Only threads of accepted, refuted or abandoned nodes are eligible. Open-node threads
        and ordinary topics are never evicted. Oldest means the earliest subscription start.
        """
        project_id = writer.project_id
        subscriptions = list(
            session.scalars(
                select(RecordRow)
                .where(
                    RecordRow.project_id == project_id,
                    RecordRow.kind == "discussion_subscription",
                    record_json_text("experiment_id") == experiment_id,
                    record_json_text("reader_key") == f"branch:{branch_id}",
                    RecordRow.payload["subscribed"].as_boolean().is_(True),
                )
                .limit(101)
            )
        )
        topics = {
            row.id: row
            for row in session.scalars(
                select(RecordRow).where(
                    RecordRow.id.in_({row.payload["topic_id"] for row in subscriptions}),
                    RecordRow.project_id == project_id,
                    RecordRow.kind == "discussion_topic",
                )
            )
            if row.payload.get("experiment_id") == experiment_id and row.payload.get("node_id")
        }
        closed = {
            row.id
            for row in session.scalars(
                select(RecordRow).where(
                    RecordRow.id.in_({row.payload["node_id"] for row in topics.values()}),
                    RecordRow.project_id == project_id,
                    RecordRow.kind == "commons_node",
                )
            )
            if row.payload["status"] in CLOSED_STATUSES
        }
        candidates = [
            row
            for row in subscriptions
            if row.payload["topic_id"] in topics
            and topics[row.payload["topic_id"]].payload["node_id"] in closed
        ]
        if not candidates:
            return False
        oldest = min(candidates, key=lambda row: (row.payload["start_sequence"], row.id))
        self._set_subscription(
            session, op, topics[oldest.payload["topic_id"]], branch_id, False, writer
        )
        return True

    # Posts ---------------------------------------------------------------------

    def post_on_node(self, node_id, request: NodePostCreate, actor, key):
        """Post on a node's thread. Cited nodes gain a citation and the poster's attention."""
        self._research_role(actor)
        if actor.role == "agent" and not actor.branch_id:
            raise HarnessError(
                "BRANCH_AUTHORITY", "A branch identity is required to post on nodes.", status=403
            )
        data = request.model_dump(mode="json")

        def apply(session, op):
            row = self._get(session, "commons_node", node_id, actor)
            experiment = self._commons_experiment(session, row.payload["experiment_id"], actor)
            # Under the experiment lock: see writes committed while this command waited.
            session.refresh(row)
            if (
                row.payload["status"] in CLOSED_STATUSES
                and request.kind not in CLOSED_NODE_POST_KINDS
            ):
                raise _node_closed("A closed node takes only synthesis and update posts.")
            if not row.payload.get("topic_id"):
                raise HarnessError("NODE_THREAD_MISSING", "This node has no discussion thread.")
            topic, _, _ = self._discussion_topic(session, row.payload["topic_id"], actor)
            if request.reply_to_post_id:
                self._discussion_post(session, request.reply_to_post_id, actor, topic)
            for identifier in request.artifact_ids:
                self._node_evidence(session, identifier, experiment, actor)
            cited = [self._commons_node(session, i, actor, experiment.id) for i in request.cites]
            subscribed = []
            for cited_row in cited:
                cited_topic = cited_row.payload.get("topic_id")
                self._replace(
                    session, cited_row, {"citation_count": cited_row.payload["citation_count"] + 1}
                )
                subscribed.append(
                    self._auto_subscribe(session, op, cited_topic, actor.branch_id, actor)
                )
            post = self._insert_post(
                session,
                op,
                topic,
                {
                    "kind": request.kind,
                    "content": request.body if request.body.strip() else request.abstract,
                    "abstract": request.abstract,
                    "artifact_ids": request.artifact_ids,
                    "reference_post_ids": [],
                    "reply_to_post_id": request.reply_to_post_id,
                    "node_id": row.id,
                    "cites": request.cites,
                    "branch_id": actor.branch_id,
                },
                actor,
            )
            self._touch_node(session, row, actor, op)
            return {**post, "auto_subscribed": all(subscribed)}

        return self._execute(actor, key, "commons.node_post", {"node_id": node_id, **data}, apply)

    def _post_status_update(self, session, row, old, new, op):
        """Announce a ladder move on the node thread; subscribers get it as a delivery."""
        topic = session.get(RecordRow, row.payload.get("topic_id") or "")
        if topic is None or topic.kind != "discussion_topic":
            return
        reason = row.payload["status_reason"]
        abstract = f"Status {old} → {new}: {reason}"[:600]
        self._insert_post(
            session,
            op,
            topic,
            {
                "kind": "update",
                "content": abstract,
                "abstract": abstract,
                "artifact_ids": [],
                "reference_post_ids": [],
                "reply_to_post_id": None,
                "node_id": row.id,
                "cites": [],
                "platform_status": {"from": old, "to": new, "reason": reason},
                "branch_id": None,
            },
            _platform(row.project_id),
        )

    # Digest items --------------------------------------------------------------

    def _post_urgent(self, session, post, node_id, actor):
        status = post.get("platform_status")
        if status is not None and post.get("origin_actor_id") == PLATFORM:
            return status.get("to") in URGENT_STATUSES
        reader_branch = actor.branch_id if actor.role == "agent" else None
        if (
            post["post_kind"] != "objection"
            or not reader_branch
            or post.get("branch_id") == reader_branch
        ):
            return False
        node = session.get(RecordRow, node_id)
        return bool(
            node is not None
            and node.kind == "commons_node"
            and node.payload.get("branch_id") == reader_branch
        )

    def _node_thread_item(self, session, post, topic, actor):
        """A node-thread delivery item: the abstract as excerpt, plus node id and urgency."""
        node_id = topic.payload["node_id"]
        # Same keys and order as a legacy item, then the node fields.
        item = {
            **self._discussion_excerpt({**post, "content": ""}),
            "node_id": node_id,
            "urgent": self._post_urgent(session, post, node_id, actor),
        }
        abstract = post.get("abstract")
        text = abstract or post["content"]
        more = abstract is not None and post["content"] != abstract
        raw = text.encode("utf-8")[:EXCERPT_BYTES]
        while True:
            excerpt = raw.decode("utf-8", errors="ignore")
            item.update(excerpt=excerpt, truncated=more or len(excerpt) < len(text))
            if len(json.dumps(item, ensure_ascii=False).encode("utf-8")) <= ITEM_BYTES:
                return item
            if not raw:
                raise HarnessError("DELIVERY_BOUNDS", "Discussion excerpt exceeds its byte bound.")
            raw = raw[: len(raw) * 3 // 4]
