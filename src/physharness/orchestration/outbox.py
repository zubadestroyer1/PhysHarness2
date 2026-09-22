"""Transactional application commands delivered at least once through stable workflow identities."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import or_, select, update

from ..domain import new_id, utcnow
from ..errors import HarnessError
from ..storage import OutboxRow

log = logging.getLogger(__name__)


class OutboxDispatcher:
    def __init__(
        self,
        service,
        deliver: Callable[[dict], Awaitable[None]],
        *,
        owner=None,
        retry_backoff_seconds=2,
    ):
        self.service, self.deliver = service, deliver
        self.owner = owner or new_id()
        self.retry_backoff_seconds = retry_backoff_seconds

    def claim(self, limit=20):
        now = utcnow().timestamp()
        with self.service.db.transaction() as session:
            query = (
                select(OutboxRow)
                .where(
                    or_(
                        (OutboxRow.state == "pending") & (OutboxRow.lease_until <= now),
                        (OutboxRow.state == "dispatching") & (OutboxRow.lease_until <= now),
                    )
                )
                .order_by(OutboxRow.id)
                .limit(limit)
            )
            if self.service.db.engine.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            result = []
            for row in session.scalars(query):
                row.state, row.owner, row.lease_until = "dispatching", self.owner, now + 60
                row.attempts += 1
                result.append(
                    {
                        "id": row.id,
                        "project_id": row.project_id,
                        "kind": row.kind,
                        "aggregate_id": row.aggregate_id,
                        "payload": row.payload,
                        "attempt": row.attempts,
                    }
                )
            return result

    async def _deliver_one(self, item):
        failure, permanent = None, False
        try:
            async with asyncio.timeout(45):
                await self.deliver(item)
        except Exception as error:
            failure = getattr(error, "code", type(error).__name__)
            permanent = isinstance(error, HarnessError) and not error.retryable
            log.exception(
                "Outbox delivery failed; inspect operation state",
                extra={"operation_id": item["id"], "error_code": failure},
            )
        with self.service.db.transaction() as session:
            delay = min(60, self.retry_backoff_seconds * 2 ** min(item["attempt"] - 1, 10))
            result = session.execute(
                update(OutboxRow)
                .where(
                    OutboxRow.id == item["id"],
                    OutboxRow.owner == self.owner,
                    OutboxRow.attempts == item["attempt"],
                    OutboxRow.state == "dispatching",
                )
                .values(
                    state="blocked" if permanent else "pending" if failure else "delivered",
                    lease_until=utcnow().timestamp() + delay if failure else 0,
                    last_error=failure,
                )
            )
            if result.rowcount != 1:
                log.error(
                    "Outbox acknowledgement lost its lease", extra={"operation_id": item["id"]}
                )
                return False
        return failure is None

    async def run_once(self, limit=20):
        # Bounded parallel dispatch keeps later entries inside their lease deadline.
        outcomes = await asyncio.gather(*(self._deliver_one(item) for item in self.claim(limit)))
        return {"delivered": sum(outcomes), "failed": len(outcomes) - sum(outcomes)}
