"""Process-wide admission of provider requests by estimated tokens per minute (R5).

One token bucket per process, shared by every runtime on its event loop. The runtime gives the
estimate (input, cached tokens included, plus expected output) and a priority. The bucket cannot
see other processes: operators give each process a share of the organisation limit.
"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field

THROTTLE_RATE_FACTOR = 0.8  # multiplicative cut on a provider 429

RECOVERY_FRACTION_PER_MINUTE = 0.05  # additive recovery per clean minute, of the limit


@dataclass
class Admission:
    key: str
    tokens: int
    waited_seconds: float
    open: bool = True


@dataclass
class _Waiter:
    key: str
    tokens: int
    priority: int
    sequence: int
    enqueued: float
    future: asyncio.Future = field(repr=False)


class TokenRateGovernor:
    """Priority token bucket: lower numbers first, waiting ages a request one class per
    ``aging_seconds`` so nothing starves, and a request larger than the bucket is admitted once
    the bucket is full."""

    def __init__(
        self,
        *,
        tokens_per_minute: int,
        burst_tokens: int | None = None,
        aging_seconds: float = 30.0,
    ) -> None:
        if (
            tokens_per_minute < 1
            or (burst_tokens is not None and burst_tokens < 1)
            or aging_seconds <= 0
        ):
            raise ValueError("Token rate, burst and aging must be positive")
        self.limit, self.aging_seconds = tokens_per_minute, aging_seconds
        self.capacity = float(burst_tokens or tokens_per_minute)
        self.level, self.paused_until = self.capacity, 0.0
        self._cut_rate, self._cut_at = float(tokens_per_minute), None
        self._updated: float | None = None
        self._waiters: list[_Waiter] = []
        self._sequence = itertools.count()
        self._timer: asyncio.TimerHandle | None = None

    @staticmethod
    def _now() -> float:
        return asyncio.get_running_loop().time()

    def _rate(self, now: float) -> float:
        if self._cut_at is None:
            return float(self.limit)
        minutes = max(0.0, now - self._cut_at) / 60
        return min(
            float(self.limit), self._cut_rate + RECOVERY_FRACTION_PER_MINUTE * self.limit * minutes
        )

    def _refill(self, now: float) -> None:
        if self._updated is not None and now > self._updated:
            self.level = min(
                self.capacity, self.level + (now - self._updated) * self._rate(now) / 60
            )
        self._updated = now

    async def admit(self, *, key: str, tokens: int, priority: int) -> Admission:
        if tokens < 0:
            raise ValueError("Admission tokens cannot be negative")
        loop = asyncio.get_running_loop()
        waiter = _Waiter(
            key, tokens, priority, next(self._sequence), loop.time(), loop.create_future()
        )
        self._waiters.append(waiter)
        self._pump()
        try:
            await waiter.future
        except asyncio.CancelledError:
            if waiter in self._waiters:
                self._waiters.remove(waiter)
                self._pump()
            elif waiter.future.done() and not waiter.future.cancelled():
                self._credit(tokens)  # granted just as the caller was cancelled
            raise
        return Admission(key=key, tokens=tokens, waited_seconds=loop.time() - waiter.enqueued)

    def settle(self, admission: Admission, actual_tokens: int) -> None:
        """Charge actual use: refund an overestimate or take an underestimate."""
        if admission.open:
            admission.open = False
            self._credit(admission.tokens - max(0, actual_tokens))

    def release(self, admission: Admission) -> None:
        """Return every admitted token: the request was never sent."""
        if admission.open:
            admission.open = False
            self._credit(admission.tokens)

    def throttled(self, wait_seconds: float) -> None:
        """A provider 429: pause every admission and cut the rate (AIMD). A 429 during the pause
        belongs to the same congestion event, so it only extends the pause: a burst of refusals
        cuts the rate once, not once per refusal."""
        now = self._now()
        self._refill(now)
        if now >= self.paused_until:
            self._cut_rate, self._cut_at = max(1.0, self._rate(now) * THROTTLE_RATE_FACTOR), now
        self.paused_until = max(self.paused_until, now + max(0.0, wait_seconds))
        self._pump()

    def snapshot(self) -> dict:
        now = self._now()
        self._refill(now)
        return {
            "tokens_per_minute": self.limit,
            "effective_tokens_per_minute": round(self._rate(now)),
            "level": int(self.level),
            "waiting": len(self._waiters),
            "paused_seconds": round(max(0.0, self.paused_until - now), 3),
        }

    def _credit(self, tokens: float) -> None:
        self._refill(self._now())
        self.level = min(self.capacity, self.level + tokens)
        self._pump()

    def _pump(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        now = self._now()
        self._refill(now)
        while self._waiters:
            if now < self.paused_until:
                return self._schedule(self.paused_until - now)
            head = min(
                self._waiters,
                key=lambda w: (
                    w.priority - int((now - w.enqueued) // self.aging_seconds),
                    w.sequence,
                ),
            )
            if head.future.done():
                self._waiters.remove(head)
                continue
            need = min(float(head.tokens), self.capacity)
            if self.level < need:
                return self._schedule((need - self.level) * 60 / self._rate(now))
            self._waiters.remove(head)
            self.level -= head.tokens
            head.future.set_result(None)

    def _schedule(self, delay: float) -> None:
        self._timer = asyncio.get_running_loop().call_later(max(delay, 0.001), self._pump)
