"""Scoped research discussions and crash-safe, explicitly acknowledged deliveries."""

import copy
import json

from sqlalchemy import and_, func, or_, select

from .discussion_models import DiscussionCreate, DiscussionPostCreate
from .domain import Principal, new_id, utcnow
from .errors import HarnessError
from .storage import EventRow, RecordRow, record_json_text


class DiscussionMixin:
    @staticmethod
    def _discussion_reader_key(experiment_id: str, actor: Principal) -> str:
        if actor.role == "agent":
            if not actor.branch_id or actor.agent_orchestrator:
                raise HarnessError(
                    "BRANCH_AUTHORITY", "A branch identity is required for discussions.", status=403
                )
            return f"branch:{actor.branch_id}"
        return f"actor:{actor.id}"

    def _discussion_experiment(self, session, experiment_id, actor):
        experiment = self._get(session, "experiment", experiment_id, actor)
        target = session.get(RecordRow, experiment.payload["problem_id"])
        if (
            target is None
            or target.project_id != actor.project_id
            or target.kind != "problem"
            or target.payload.get("target_digest") != experiment.payload.get("target_digest")
        ):
            raise HarnessError("TARGET_CHANGED", "The discussion target revision is stale.")
        return experiment, target

    @staticmethod
    def _discussion_pins(experiment, target):
        return {
            "problem_revision_id": target.id,
            "target_digest": experiment.payload["target_digest"],
            "environment_digest": target.payload["environment_digest"],
        }

    def _discussion_topic(self, session, topic_id, actor):
        topic = self._get(session, "discussion_topic", topic_id, actor)
        experiment, target = self._discussion_experiment(
            session, topic.payload["experiment_id"], actor
        )
        if any(
            topic.payload.get(k) != v for k, v in self._discussion_pins(experiment, target).items()
        ):
            raise HarnessError("TARGET_CHANGED", "The discussion is pinned to a stale target.")
        return topic, experiment, target

    def _discussion_post(self, session, post_id, actor, topic=None):
        post = self._get(session, "discussion_post", post_id, actor)
        self._discussion_topic(session, post.payload["topic_id"], actor)
        if topic and post.payload["topic_id"] != topic.id:
            raise HarnessError(
                "DISCUSSION_SCOPE", "The reply belongs to another topic.", status=422
            )
        return post

    def _discussion_safe_post(self, session, post, actor):
        # References are checked again on delivery: later sharing changes revoke access.
        for identifier in post.payload.get("artifact_ids", []):
            artifact = self._get(session, "artifact", identifier, actor)
            if (
                artifact.payload.get("experiment_id") != post.payload["experiment_id"]
                or artifact.payload.get("artifact_kind") in self._private_artifact_kinds
            ):
                raise HarnessError(
                    "EVIDENCE_SCOPE", "A referenced artifact is private or outside the experiment."
                )
        return copy.deepcopy(post.payload)

    def _research_message(self, session, message_id, actor, experiment_id=None):
        message = self._get(session, "message", message_id, actor)
        if actor.role == "agent" and message.payload.get("recipient_branch_id") != actor.branch_id:
            raise HarnessError("NOT_FOUND", "The addressed message was not found.", status=404)
        if experiment_id and message.payload.get("experiment_id") != experiment_id:
            raise HarnessError("NOT_FOUND", "The addressed message was not found.", status=404)
        for identifier in message.payload.get("artifact_ids", []):
            artifact = self._get(session, "artifact", identifier, actor)
            if artifact.payload.get("experiment_id") != message.payload["experiment_id"]:
                raise HarnessError("EVIDENCE_SCOPE", "Message evidence is outside the experiment.")
        return message

    def read_research_message(self, message_id, actor):
        """Retrieve an exact message addressed to this research branch."""
        self._research_role(actor)
        with self.db.sessions() as session:
            message = self._research_message(session, message_id, actor)
            self._discussion_experiment(session, message.payload["experiment_id"], actor)
            return copy.deepcopy(message.payload)

    @staticmethod
    def _discussion_excerpt(post):
        raw = post["content"].encode("utf-8")
        excerpt = raw[:1024].decode("utf-8", errors="ignore")
        item = {
            "id": post["id"],
            "topic_id": post["topic_id"],
            "sequence": post["sequence"],
            "post_kind": post["post_kind"],
            "attributed_to": post["attributed_to"],
            "branch_id": post.get("branch_id"),
            "excerpt": excerpt,
            "truncated": len(raw) > 1024,
            "retrieval_post_id": post["id"],
            "retrieval_id": post["id"],
            "source_kind": "discussion_post",
            "evidence_status": "unverified_discussion",
        }
        if len(json.dumps(item, ensure_ascii=False).encode("utf-8")) > 2048:
            raise HarnessError("DELIVERY_BOUNDS", "Discussion excerpt exceeds its byte bound.")
        return item

    @staticmethod
    def _research_message_excerpt(message, sequence):
        raw = message["content"].encode("utf-8")
        item = {
            "id": message["id"],
            "sequence": sequence,
            "source_kind": "message",
            "attributed_to": message["attributed_to"],
            "branch_id": message.get("sender_branch_id"),
            "recipient_branch_id": message["recipient_branch_id"],
            "excerpt": raw[:1024].decode("utf-8", errors="ignore"),
            "truncated": len(raw) > 1024,
            "retrieval_id": message["id"],
            "evidence_status": "attributed_idea",
        }
        if len(json.dumps(item, ensure_ascii=False).encode("utf-8")) > 2048:
            raise HarnessError("DELIVERY_BOUNDS", "Message excerpt exceeds its byte bound.")
        return item

    @staticmethod
    def _withdrawal_notice(sequence):
        return {
            "id": None,
            "sequence": sequence,
            "source_kind": "withdrawal",
            "excerpt": "An addressed update is no longer available to this branch.",
            "truncated": False,
            "retrieval_id": None,
            "reason": "access_revoked",
            "evidence_status": "withdrawn_unreadable",
        }

    def _source_accessible(self, session, source_kind, source_id, experiment, actor):
        expected = "message" if source_kind == "message" else "discussion_post"
        if source_kind not in {"message", "discussion_post"}:
            raise HarnessError("DELIVERY_SOURCE_INVALID", "Unknown delivery source kind.")
        source = session.get(RecordRow, source_id)
        if (
            not source
            or source.kind != expected
            or source.project_id != actor.project_id
            or source.payload.get("experiment_id") != experiment.id
        ):
            raise HarnessError("DELIVERY_SOURCE_MISSING", "Delivery source metadata is missing.")
        if source_kind == "message":
            if source.payload.get("recipient_branch_id") != actor.branch_id:
                raise HarnessError("DELIVERY_SOURCE_INVALID", "Addressed recipient changed.")
        else:
            target = session.get(RecordRow, experiment.payload["problem_id"])
            topic = session.get(RecordRow, source.payload.get("topic_id"))
            pins = self._discussion_pins(experiment, target)
            if (
                not topic
                or topic.kind != "discussion_topic"
                or topic.project_id != actor.project_id
                or topic.payload.get("experiment_id") != experiment.id
                or any(
                    source.payload.get(k) != v or topic.payload.get(k) != v for k, v in pins.items()
                )
            ):
                raise HarnessError("TARGET_CHANGED", "The delivery target pins changed.")
            for identifier in source.payload.get("reference_post_ids", []):
                reference = session.get(RecordRow, identifier)
                if (
                    not reference
                    or reference.kind != "discussion_post"
                    or reference.project_id != actor.project_id
                    or reference.payload.get("experiment_id") != experiment.id
                ):
                    raise HarnessError("DELIVERY_SOURCE_INVALID", "A post reference is missing.")
        artifacts = []
        for identifier in source.payload.get("artifact_ids", []):
            artifact = session.get(RecordRow, identifier)
            if (
                not artifact
                or artifact.kind != "artifact"
                or artifact.project_id != actor.project_id
                or artifact.payload.get("experiment_id") != experiment.id
            ):
                raise HarnessError("DELIVERY_SOURCE_INVALID", "A source attachment is missing.")
            artifacts.append(artifact)
        if not self._in_scope(session, source, actor):
            return False
        for artifact in artifacts:
            if (
                source_kind == "discussion_post"
                and artifact.payload.get("artifact_kind") in self._private_artifact_kinds
            ) or not self._in_scope(session, artifact, actor):
                return False
        return True

    def _record_withdrawal(self, session, actor, experiment_id, reader_key, delivery_id, item):
        audit = self._insert(
            session,
            "discussion_withdrawal",
            actor,
            {
                "experiment_id": experiment_id,
                "reader_key": reader_key,
                "delivery_id": delivery_id,
                "event_sequence": item["sequence"],
                "source_kind": item["source_kind"],
                "source_record_id": item["id"],
                "reason": "access_revoked",
            },
        )
        self._event(
            session,
            actor,
            new_id(),
            "discussion.source_withdrawn",
            audit["id"],
            {"experiment_id": experiment_id, "event_sequence": item["sequence"]},
        )

    def _sanitize_delivery(self, session, delivery, experiment, actor, reader_key):
        revised = []
        changed = False
        for item in delivery.payload["items"]:
            if item["source_kind"] == "withdrawal":
                revised.append(item)
                continue
            if self._source_accessible(session, item["source_kind"], item["id"], experiment, actor):
                revised.append(item)
                continue
            self._record_withdrawal(session, actor, experiment.id, reader_key, delivery.id, item)
            revised.append(self._withdrawal_notice(item["sequence"]))
            changed = True
        if changed:
            self._replace(session, delivery, {"items": revised})
        return revised, changed

    def create_discussion(
        self, experiment_id: str, request: DiscussionCreate, actor: Principal, key: str
    ) -> dict:
        self._research_role(actor)
        data = request.model_dump(mode="json")

        def action(session, op):
            experiment, target = self._discussion_experiment(session, experiment_id, actor)
            self._active(session, experiment_id, actor)
            branch_id = request.branch_id or actor.branch_id
            if actor.role == "agent" and branch_id != actor.branch_id:
                raise HarnessError(
                    "BRANCH_AUTHORITY", "A topic must belong to the author's branch.", status=403
                )
            if branch_id:
                branch = self._writable_branch(session, branch_id, actor)
                if branch.payload["experiment_id"] != experiment_id:
                    raise HarnessError(
                        "DISCUSSION_SCOPE", "The branch belongs to another experiment."
                    )
            record = self._insert(
                session,
                "discussion_topic",
                actor,
                {
                    "experiment_id": experiment_id,
                    "branch_id": branch_id,
                    "title": request.title,
                    "summary": request.summary,
                    "attributed_to": actor.id,
                    "evidence_status": "unverified_discussion",
                    **self._discussion_pins(experiment, target),
                },
            )
            self._event(
                session,
                actor,
                op,
                "discussion.topic_created",
                record["id"],
                {"experiment_id": experiment_id, "topic_id": record["id"]},
            )
            return record

        return self._execute(
            actor, key, "discussion.create", {"experiment_id": experiment_id, **data}, action
        )

    def post_discussion(
        self, topic_id: str, request: DiscussionPostCreate, actor: Principal, key: str
    ) -> dict:
        self._research_role(actor)
        data = request.model_dump(mode="json")

        def action(session, op):
            topic, experiment, target = self._discussion_topic(session, topic_id, actor)
            self._active(session, experiment.id, actor)
            post_branch = (
                actor.branch_id if actor.role == "agent" else topic.payload.get("branch_id")
            )
            if actor.role == "agent" and topic.payload.get("branch_id") != actor.branch_id:
                if experiment.payload.get("sharing") != "ideas":
                    raise HarnessError(
                        "SHARING_POLICY", "Cross-branch posts require ideas sharing.", status=403
                    )
            if request.reply_to_post_id:
                self._discussion_post(session, request.reply_to_post_id, actor, topic)
            for identifier in request.reference_post_ids:
                reference = self._discussion_post(session, identifier, actor)
                if reference.payload["experiment_id"] != experiment.id:
                    raise HarnessError(
                        "DISCUSSION_SCOPE", "A post reference belongs to another experiment."
                    )
                if (
                    post_branch
                    and reference.payload.get("branch_id") != post_branch
                    and experiment.payload.get("sharing") != "ideas"
                ):
                    raise HarnessError(
                        "SHARING_POLICY",
                        "Cross-branch references require ideas sharing.",
                        status=403,
                    )
            for identifier in request.artifact_ids:
                artifact = self._get(session, "artifact", identifier, actor)
                if (
                    artifact.payload.get("experiment_id") != experiment.id
                    or artifact.payload.get("artifact_kind") in self._private_artifact_kinds
                ):
                    raise HarnessError(
                        "EVIDENCE_SCOPE",
                        "A referenced artifact is private or outside the experiment.",
                    )
                if (
                    post_branch
                    and artifact.payload.get("branch_id") != post_branch
                    and experiment.payload.get("sharing") != "ideas"
                ):
                    raise HarnessError(
                        "SHARING_POLICY",
                        "Cross-branch artifacts require ideas sharing.",
                        status=403,
                    )
            record = self._insert(
                session,
                "discussion_post",
                actor,
                {
                    "experiment_id": experiment.id,
                    "topic_id": topic_id,
                    "branch_id": post_branch,
                    "attributed_to": actor.id,
                    "post_kind": request.kind,
                    "content": request.content,
                    "reply_to_post_id": request.reply_to_post_id,
                    "artifact_ids": request.artifact_ids,
                    "reference_post_ids": request.reference_post_ids,
                    "evidence_status": "unverified_discussion",
                    **self._discussion_pins(experiment, target),
                },
            )
            event = EventRow(
                project_id=actor.project_id,
                operation_id=op,
                kind="discussion.post_created",
                aggregate_id=topic_id,
                payload={
                    "experiment_id": experiment.id,
                    "topic_id": topic_id,
                    "post_id": record["id"],
                },
                created_at=utcnow().isoformat(),
            )
            session.add(event)
            session.flush()
            return self._replace(
                session, session.get(RecordRow, record["id"]), {"sequence": event.sequence}
            )

        return self._execute(actor, key, "discussion.post", {"topic_id": topic_id, **data}, action)

    def discussion_page(self, experiment_id, actor, *, after=None, limit=20):
        self._research_role(actor)
        if not 1 <= limit <= 20:
            raise HarnessError("INVALID_PAGE_SIZE", "Discussion page size is 1–20.", status=422)
        cursor = self._discussion_cursor(after)
        with self.db.sessions() as session:
            self._discussion_experiment(session, experiment_id, actor)
            query = (
                select(EventRow)
                .where(
                    EventRow.project_id == actor.project_id,
                    EventRow.kind == "discussion.topic_created",
                    EventRow.sequence > cursor,
                    EventRow.payload["experiment_id"].as_string() == experiment_id,
                )
                .order_by(EventRow.sequence)
            )
            return self._discussion_event_page(session, query, "discussion_topic", actor, limit)

    def discussion_posts(self, topic_id, actor, *, after=None, limit=20):
        self._research_role(actor)
        if not 1 <= limit <= 20:
            raise HarnessError("INVALID_PAGE_SIZE", "Discussion page size is 1–20.", status=422)
        cursor = self._discussion_cursor(after)
        with self.db.sessions() as session:
            self._discussion_topic(session, topic_id, actor)
            query = (
                select(EventRow)
                .where(
                    EventRow.project_id == actor.project_id,
                    EventRow.kind == "discussion.post_created",
                    EventRow.aggregate_id == topic_id,
                    EventRow.sequence > cursor,
                )
                .order_by(EventRow.sequence)
            )
            return self._discussion_event_page(session, query, "discussion_post", actor, limit)

    def read_discussion_post(self, post_id, actor):
        """Retrieve the exact attributed source behind a bounded delivery excerpt."""
        self._research_role(actor)
        with self.db.sessions() as session:
            post = self._discussion_post(session, post_id, actor)
            return self._discussion_safe_post(session, post, actor)

    @staticmethod
    def _discussion_cursor(after):
        if after is None:
            return 0
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise HarnessError(
                "INVALID_CURSOR", "Use a nonnegative event sequence cursor.", status=422
            )
        return after

    def _discussion_event_page(self, session, query, kind, actor, limit):
        # Bounded scan protects metadata reads even when some records are private.
        events = list(session.scalars(query.limit(max(100, limit) + 1)))
        items, scanned = [], 0
        for event in events[: max(100, limit)]:
            scanned += 1
            try:
                record = self._get(
                    session,
                    kind,
                    event.payload["topic_id"]
                    if kind == "discussion_topic"
                    else event.payload["post_id"],
                    actor,
                )
                items.append(
                    self._discussion_safe_post(session, record, actor)
                    if kind == "discussion_post"
                    else copy.deepcopy(record.payload)
                )
            except HarnessError as error:
                if error.code != "NOT_FOUND":
                    raise
            if len(items) == limit:
                break
        return {
            "items": items,
            "next_cursor": events[scanned - 1].sequence if scanned < len(events) else None,
        }

    def _discussion_reader(self, session, experiment_id, actor, *, create=False):
        reader_key = self._discussion_reader_key(experiment_id, actor)
        row = session.scalar(
            select(RecordRow)
            .where(
                RecordRow.project_id == actor.project_id,
                RecordRow.kind == "discussion_reader",
                record_json_text("experiment_id") == experiment_id,
                record_json_text("reader_key") == reader_key,
            )
            .limit(1)
        )
        if row is None and create:
            data = {
                "experiment_id": experiment_id,
                "reader_key": reader_key,
                "ack_sequence": 0,
                "pending_delivery_id": None,
            }
            row_data = self._insert(session, "discussion_reader", actor, data)
            row = session.get(RecordRow, row_data["id"])
        return row

    def subscribe_discussion(self, topic_id, subscribed, actor, key):
        self._research_role(actor)
        if not isinstance(subscribed, bool):
            raise HarnessError("INVALID_SUBSCRIPTION", "Subscribed must be Boolean.", status=422)

        def action(session, op):
            topic, experiment, _ = self._discussion_topic(session, topic_id, actor)
            reader_key = self._discussion_reader_key(experiment.id, actor)
            self.db.command_lock(
                session, self._digest(["discussion-reader", experiment.id, reader_key])
            )
            reader = self._discussion_reader(session, experiment.id, actor, create=True)
            if reader.payload.get("pending_delivery_id"):
                raise HarnessError(
                    "DELIVERY_PENDING",
                    "Acknowledge the outstanding delivery before changing subscriptions.",
                )
            prior = session.scalar(
                select(RecordRow)
                .where(
                    RecordRow.project_id == actor.project_id,
                    RecordRow.kind == "discussion_subscription",
                    record_json_text("experiment_id") == experiment.id,
                    record_json_text("topic_id") == topic.id,
                    record_json_text("reader_key") == reader_key,
                )
                .limit(1)
            )
            if prior:
                if prior.payload["subscribed"] == subscribed:
                    return copy.deepcopy(prior.payload)
                if subscribed:
                    count = (
                        session.scalar(
                            select(func.count())
                            .select_from(RecordRow)
                            .where(
                                RecordRow.project_id == actor.project_id,
                                RecordRow.kind == "discussion_subscription",
                                record_json_text("experiment_id") == experiment.id,
                                record_json_text("reader_key") == reader_key,
                                RecordRow.payload["subscribed"].as_boolean().is_(True),
                            )
                        )
                        or 0
                    )
                    if count >= 100:
                        raise HarnessError(
                            "SUBSCRIPTION_LIMIT",
                            "A reader may subscribe to at most 100 topics.",
                            status=422,
                        )
                values = {
                    "subscribed": subscribed,
                    "start_sequence": self._discussion_max_sequence(session)
                    if subscribed
                    else prior.payload["start_sequence"],
                }
                result = self._replace(session, prior, values)
            else:
                count = (
                    session.scalar(
                        select(func.count())
                        .select_from(RecordRow)
                        .where(
                            RecordRow.project_id == actor.project_id,
                            RecordRow.kind == "discussion_subscription",
                            record_json_text("experiment_id") == experiment.id,
                            record_json_text("reader_key") == reader_key,
                            RecordRow.payload["subscribed"].as_boolean().is_(True),
                        )
                    )
                    or 0
                )
                if subscribed and count >= 100:
                    raise HarnessError(
                        "SUBSCRIPTION_LIMIT",
                        "A reader may subscribe to at most 100 topics.",
                        status=422,
                    )
                result = self._insert(
                    session,
                    "discussion_subscription",
                    actor,
                    {
                        "experiment_id": experiment.id,
                        "topic_id": topic.id,
                        "reader_key": reader_key,
                        "branch_id": actor.branch_id,
                        "subscribed": subscribed,
                        "start_sequence": self._discussion_max_sequence(session),
                    },
                )
            self._event(
                session,
                actor,
                op,
                "discussion.subscription_changed",
                topic.id,
                {"experiment_id": experiment.id, "subscribed": subscribed},
            )
            return result

        return self._execute(
            actor,
            key,
            "discussion.subscribe",
            {"topic_id": topic_id, "subscribed": subscribed},
            action,
        )

    @staticmethod
    def _discussion_max_sequence(session):
        return session.scalar(select(func.max(EventRow.sequence))) or 0

    def discussion_updates(self, experiment_id, actor, *, after=None, limit=10):
        self._research_role(actor)
        if not 1 <= limit <= 10:
            raise HarnessError("INVALID_PAGE_SIZE", "Discussion update size is 1–10.", status=422)
        cursor = self._discussion_cursor(after)
        reader_key = self._discussion_reader_key(experiment_id, actor)
        with self.db.transaction() as session:
            experiment, _ = self._discussion_experiment(session, experiment_id, actor)
            self._check_worker_effects(session, actor)
            self.db.command_lock(
                session, self._digest(["discussion-reader", experiment_id, reader_key])
            )
            reader = self._discussion_reader(session, experiment_id, actor, create=True)
            ack = reader.payload["ack_sequence"]
            if after is not None and cursor != ack:
                raise HarnessError(
                    "INVALID_CURSOR",
                    "The update cursor must equal the acknowledged sequence.",
                    status=409,
                )
            pending_id = reader.payload.get("pending_delivery_id")
            if pending_id:
                pending = session.get(RecordRow, pending_id)
                if (
                    not pending
                    or pending.kind != "discussion_delivery"
                    or pending.project_id != actor.project_id
                    or pending.payload.get("reader_key") != reader_key
                    or pending.payload.get("experiment_id") != experiment_id
                ):
                    raise HarnessError("DELIVERY_MISMATCH", "Pending delivery identity changed.")
                items, _ = self._sanitize_delivery(session, pending, experiment, actor, reader_key)
                return {
                    "delivery_id": pending_id,
                    "items": items,
                    "next_cursor": pending.payload["end_sequence"],
                    "redelivered": True,
                }
            subscriptions = list(
                session.scalars(
                    select(RecordRow)
                    .where(
                        RecordRow.project_id == actor.project_id,
                        RecordRow.kind == "discussion_subscription",
                        record_json_text("experiment_id") == experiment_id,
                        record_json_text("reader_key") == reader_key,
                        RecordRow.payload["subscribed"].as_boolean().is_(True),
                    )
                    .limit(101)
                )
            )
            if len(subscriptions) > 100:
                raise HarnessError(
                    "SUBSCRIPTION_LIMIT", "Reader subscriptions exceed the supported bound."
                )
            starts = {r.payload["topic_id"]: r.payload["start_sequence"] for r in subscriptions}
            eligible_posts = [
                and_(
                    EventRow.kind == "discussion.post_created",
                    EventRow.aggregate_id == topic_id,
                    EventRow.sequence > max(ack, start),
                    EventRow.payload["experiment_id"].as_string() == experiment.id,
                )
                for topic_id, start in starts.items()
            ]
            if actor.role == "agent":
                eligible_posts.append(
                    and_(
                        EventRow.kind == "message.created",
                        EventRow.aggregate_id == actor.branch_id,
                        EventRow.sequence > ack,
                    )
                )
            if not eligible_posts:
                return {"delivery_id": None, "items": [], "next_cursor": ack, "redelivered": False}
            events = list(
                session.scalars(
                    select(EventRow)
                    .where(
                        EventRow.project_id == actor.project_id,
                        or_(*eligible_posts),
                    )
                    .order_by(EventRow.sequence)
                    .limit(100)
                )
            )
            items = []
            withdrawals = []
            for event in events:
                source_kind = "message" if event.kind == "message.created" else "discussion_post"
                source_id = (
                    event.payload["message_id"]
                    if source_kind == "message"
                    else event.payload["post_id"]
                )
                if not self._source_accessible(session, source_kind, source_id, experiment, actor):
                    excerpt = self._withdrawal_notice(event.sequence)
                    withdrawals.append(
                        {"id": source_id, "sequence": event.sequence, "source_kind": source_kind}
                    )
                elif source_kind == "message":
                    message = self._research_message(session, source_id, actor, experiment_id)
                    excerpt = self._research_message_excerpt(message.payload, event.sequence)
                else:
                    post = self._discussion_post(session, source_id, actor)
                    safe_post = self._discussion_safe_post(session, post, actor)
                    excerpt = self._discussion_excerpt(safe_post)
                if len(json.dumps(items + [excerpt], ensure_ascii=False).encode("utf-8")) > 12000:
                    break
                items.append(excerpt)
                if len(items) == limit:
                    break
            if not items:
                return {"delivery_id": None, "items": [], "next_cursor": ack, "redelivered": False}
            end = items[-1]["sequence"]
            delivery = self._insert(
                session,
                "discussion_delivery",
                actor,
                {
                    "experiment_id": experiment_id,
                    "reader_key": reader_key,
                    "start_sequence": ack,
                    "end_sequence": end,
                    "items": items,
                    "status": "pending",
                },
            )
            for item in withdrawals:
                if item["sequence"] <= end:
                    self._record_withdrawal(
                        session, actor, experiment_id, reader_key, delivery["id"], item
                    )
            # The record ID is the opaque delivery identity checked during ack.
            self._replace(session, reader, {"pending_delivery_id": delivery["id"]})
            return {
                "delivery_id": delivery["id"],
                "items": items,
                "next_cursor": end,
                "redelivered": False,
            }

    def acknowledge_discussion_updates(self, experiment_id, delivery_id, actor, key):
        self._research_role(actor)
        # Persist withdrawal representation before attempting an acknowledgement.
        # A caller must reread and checkpoint that new representation first.
        changed_before_ack = False
        with self.db.transaction() as session:
            experiment, _ = self._discussion_experiment(session, experiment_id, actor)
            self._check_worker_effects(session, actor)
            reader_key = self._discussion_reader_key(experiment_id, actor)
            self.db.command_lock(
                session, self._digest(["discussion-reader", experiment_id, reader_key])
            )
            reader = self._discussion_reader(session, experiment_id, actor)
            if reader and reader.payload.get("pending_delivery_id") == delivery_id:
                delivery = session.get(RecordRow, delivery_id)
                if (
                    delivery
                    and delivery.kind == "discussion_delivery"
                    and delivery.project_id == actor.project_id
                    and delivery.payload.get("experiment_id") == experiment_id
                    and delivery.payload.get("reader_key") == reader_key
                ):
                    _, changed_before_ack = self._sanitize_delivery(
                        session, delivery, experiment, actor, reader_key
                    )
        if changed_before_ack:
            raise HarnessError(
                "DELIVERY_CHANGED",
                "The pending delivery changed. Read and persist it before acknowledgement.",
                status=409,
            )

        def action(session, op):
            experiment, _ = self._discussion_experiment(session, experiment_id, actor)
            reader_key = self._discussion_reader_key(experiment_id, actor)
            self.db.command_lock(
                session, self._digest(["discussion-reader", experiment_id, reader_key])
            )
            reader = self._discussion_reader(session, experiment_id, actor)
            if reader is None or reader.payload.get("pending_delivery_id") != delivery_id:
                raise HarnessError(
                    "DELIVERY_MISMATCH",
                    "Only the current delivered batch can be acknowledged.",
                    status=409,
                )
            delivery = session.get(RecordRow, delivery_id)
            if (
                not delivery
                or delivery.kind != "discussion_delivery"
                or delivery.project_id != actor.project_id
                or delivery.payload["reader_key"] != reader_key
                or delivery.payload["experiment_id"] != experiment_id
                or delivery.payload["start_sequence"] != reader.payload["ack_sequence"]
                or delivery.payload["status"] != "pending"
            ):
                raise HarnessError(
                    "DELIVERY_MISMATCH", "Delivery identity or sequence changed.", status=409
                )
            items, changed_during_ack = self._sanitize_delivery(
                session, delivery, experiment, actor, reader_key
            )
            if changed_during_ack:
                raise HarnessError(
                    "DELIVERY_CHANGED",
                    "The pending delivery changed. Read and persist it before acknowledgement.",
                    status=409,
                )
            end = delivery.payload["end_sequence"]
            self._replace(session, delivery, {"status": "acknowledged"})
            self._replace(session, reader, {"ack_sequence": end, "pending_delivery_id": None})
            self._event(
                session,
                actor,
                op,
                "discussion.delivery_acknowledged",
                delivery_id,
                {"experiment_id": experiment_id, "end_sequence": end},
            )
            return {
                "delivery_id": delivery_id,
                "acknowledged": True,
                "next_cursor": end,
                "delivered_count": sum(item["source_kind"] != "withdrawal" for item in items),
                "withdrawn_count": sum(item["source_kind"] == "withdrawal" for item in items),
            }

        return self._execute(
            actor,
            key,
            "discussion.acknowledge",
            {"experiment_id": experiment_id, "delivery_id": delivery_id},
            action,
        )
