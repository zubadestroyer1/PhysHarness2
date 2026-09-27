"""TokenRateGovernor: one priority token bucket per process."""

import asyncio

import pytest

from physharness.config import ConfigurationError, Settings
from physharness.execution.admission import TokenRateGovernor


async def drained(**kwargs):
    governor = TokenRateGovernor(tokens_per_minute=60_000, burst_tokens=1_000, **kwargs)  # 1,000/s
    await governor.admit(key="drain", tokens=1_000, priority=0)
    return governor


async def test_rate_priority_and_aging():
    governor = TokenRateGovernor(tokens_per_minute=60_000, burst_tokens=1_000)
    assert (await governor.admit(key="a", tokens=1_000, priority=1)).waited_seconds < 0.05
    assert (await governor.admit(key="a", tokens=500, priority=1)).waited_seconds >= 0.4
    order = []

    async def request(bucket, name, priority, delay, tokens):
        await asyncio.sleep(delay)
        await bucket.admit(key=name, tokens=tokens, priority=priority)
        order.append(name)

    bucket = await drained()
    await asyncio.gather(
        request(bucket, "low", 2, 0, 300),
        request(bucket, "high", 0, 0.01, 300),
        request(bucket, "mid", 1, 0.02, 300),
    )
    assert order == ["high", "mid", "low"]
    order.clear()
    aging = await drained(aging_seconds=0.1)  # "old" has aged 3 classes when "new" arrives
    await asyncio.gather(request(aging, "old", 3, 0, 500), request(aging, "new", 0, 0.35, 500))
    assert order == ["old", "new"]


async def test_settle_refunds_or_charges_and_release_returns_everything():
    governor = TokenRateGovernor(tokens_per_minute=60, burst_tokens=1_000)  # ~1 token/s
    first = await governor.admit(key="a", tokens=800, priority=1)
    governor.settle(first, 300)
    assert 699 <= governor.snapshot()["level"] <= 702
    second = await governor.admit(key="a", tokens=400, priority=1)
    governor.settle(second, 900)
    governor.settle(second, 0)  # settles once only
    assert -202 <= governor.snapshot()["level"] <= -198
    fresh = TokenRateGovernor(tokens_per_minute=60, burst_tokens=1_000)
    held = await fresh.admit(key="b", tokens=500, priority=1)
    fresh.release(held)
    fresh.release(held)
    assert fresh.snapshot()["level"] == 1_000


async def test_throttle_pauses_and_cuts_rate_and_cancelled_waiters_leave():
    governor = TokenRateGovernor(tokens_per_minute=60_000, burst_tokens=1_000)
    governor.throttled(0.3)
    assert (await governor.admit(key="a", tokens=10, priority=0)).waited_seconds >= 0.29
    assert 47_900 <= governor.snapshot()["effective_tokens_per_minute"] <= 48_100
    slow = TokenRateGovernor(tokens_per_minute=60, burst_tokens=100)
    await slow.admit(key="drain", tokens=100, priority=0)
    waiter = asyncio.create_task(slow.admit(key="b", tokens=50, priority=0))
    await asyncio.sleep(0.01)
    assert slow.snapshot()["waiting"] == 1
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert slow.snapshot()["waiting"] == 0


def test_settings_read_the_process_token_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("PHYSHARNESS_PROVIDER_TOKENS_PER_MINUTE", "1800000")
    assert Settings(auth_file=tmp_path / "none.json").provider_tokens_per_minute == 1_800_000
    monkeypatch.setenv("PHYSHARNESS_PROVIDER_TOKENS_PER_MINUTE", "0")
    with pytest.raises(ConfigurationError):
        Settings(auth_file=tmp_path / "none.json")
