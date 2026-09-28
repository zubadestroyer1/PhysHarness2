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
    # Cut to 48,000, then recovering at 300 per second of the wait.
    assert 48_000 <= governor.snapshot()["effective_tokens_per_minute"] <= 48_300
    slow = TokenRateGovernor(tokens_per_minute=60, burst_tokens=100)
    await slow.admit(key="drain", tokens=100, priority=0)
    waiter = asyncio.create_task(slow.admit(key="b", tokens=50, priority=0))
    await asyncio.sleep(0.01)
    assert slow.snapshot()["waiting"] == 1
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert slow.snapshot()["waiting"] == 0


async def test_a_grant_that_races_a_cancel_returns_its_tokens():
    governor = TokenRateGovernor(tokens_per_minute=60, burst_tokens=100)  # ~1 token/s
    first = await governor.admit(key="a", tokens=100, priority=0)
    waiter = asyncio.create_task(governor.admit(key="b", tokens=100, priority=0))
    await asyncio.sleep(0.01)
    governor.release(first)  # grants b synchronously
    waiter.cancel()  # before b resumes
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert governor.snapshot()["level"] >= 99


async def test_a_pause_ends_at_the_rate_not_in_a_burst():
    governor = TokenRateGovernor(tokens_per_minute=60_000, burst_tokens=10_000)  # 1,000/s, full
    governor.throttled(0.1)
    start = asyncio.get_running_loop().time()
    await governor.admit(key="a", tokens=500, priority=0)
    # The 429 spent the bucket and nothing refilled while paused: 500 tokens at the cut rate
    # (800/s) take about 0.6 s after the pause, rather than coming at once from a full bucket.
    assert asyncio.get_running_loop().time() - start >= 0.6


def test_settings_read_the_process_token_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("PHYSHARNESS_PROVIDER_TOKENS_PER_MINUTE", "1800000")
    assert Settings(auth_file=tmp_path / "none.json").provider_tokens_per_minute == 1_800_000
    monkeypatch.setenv("PHYSHARNESS_PROVIDER_TOKENS_PER_MINUTE", "0")
    with pytest.raises(ConfigurationError):
        Settings(auth_file=tmp_path / "none.json")


def fake_clock(monkeypatch, governor, start=0.0):
    """Drive ``governor`` from a clock the test advances by hand."""
    clock = [start]
    monkeypatch.setattr(governor, "_now", lambda: clock[0])
    return clock


async def test_429s_inside_the_cooldown_cause_no_extra_cut(monkeypatch):
    governor = TokenRateGovernor(tokens_per_minute=1_800_000)
    clock = fake_clock(monkeypatch, governor, start=100.0)
    for wait in [2.0] * 8 + [5.0] + [2.0] * 7:  # 16 creates refused together
        governor.throttled(wait)
    snapshot = governor.snapshot()
    # One congestion event: one 20% cut, not 0.8**16; the longest wait sets the pause.
    assert (snapshot["effective_tokens_per_minute"], snapshot["paused_seconds"]) == (1_440_000, 5.0)
    clock[0] = 103.0  # inside the pause: a longer wait extends it, with no second cut
    governor.throttled(4.0)
    snapshot = governor.snapshot()
    # Recovery is 5% of the limit per 10 s: 3 s adds 27,000.
    assert (snapshot["effective_tokens_per_minute"], snapshot["paused_seconds"]) == (1_467_000, 4.0)
    clock[0] = 120.0  # the pause is over but the cooldown is not: the 429 only pauses
    governor.throttled(1.0)
    snapshot = governor.snapshot()
    assert (snapshot["effective_tokens_per_minute"], snapshot["paused_seconds"]) == (1_620_000, 1.0)
    clock[0] = 130.0  # 30 s after the cut: a new 429 cuts again
    governor.throttled(1.0)
    assert governor.snapshot()["effective_tokens_per_minute"] == round(1_710_000 * 0.8)


async def test_one_isolated_429_a_minute_keeps_at_least_80_percent_of_the_limit(monkeypatch):
    limit = 1_800_000
    governor = TokenRateGovernor(tokens_per_minute=limit)
    clock = fake_clock(monkeypatch, governor)
    rates = []
    for second in range(30 * 60):
        clock[0] = float(second)
        if second % 60 == 30:
            governor.throttled(1.0)  # one isolated refusal a minute, as from unseen traffic
        rates.append(governor.snapshot()["effective_tokens_per_minute"])
    # Each cut takes 20% of a fully recovered rate, so the rate never falls below 80%.
    assert min(rates) >= 0.8 * limit


async def test_one_cut_recovers_to_the_full_rate_within_a_minute(monkeypatch):
    governor = TokenRateGovernor(tokens_per_minute=1_800_000)
    clock = fake_clock(monkeypatch, governor)
    governor.throttled(0.5)
    rates = {}
    for second in (0, 20, 40, 60):
        clock[0] = float(second)
        rates[second] = governor.snapshot()["effective_tokens_per_minute"]
    assert rates == {0: 1_440_000, 20: 1_620_000, 40: 1_800_000, 60: 1_800_000}


async def test_the_default_burst_is_fifteen_seconds_of_tokens():
    assert TokenRateGovernor(tokens_per_minute=1_800_000).snapshot()["level"] == 450_000


@pytest.mark.parametrize(("hint", "first"), [(True, "requeued"), (False, "fresh")])
async def test_a_requeued_request_keeps_its_queue_age(monkeypatch, hint, first):
    governor = TokenRateGovernor(tokens_per_minute=60, burst_tokens=1_000)  # a class per 30 s
    fake_clock(monkeypatch, governor, start=1_000.0)
    drain = await governor.admit(key="drain", tokens=1_000, priority=0)
    order = []

    async def request(name, priority, **kwargs):
        await governor.admit(key=name, tokens=1_000, priority=priority, **kwargs)
        order.append(name)

    # A priority-1 create that first queued 60 s ago has aged two classes, so it outranks a new
    # priority-0 request, but only if the re-queue keeps its original queue time.
    queued = asyncio.create_task(request("requeued", 1, **({"enqueued": 940.0} if hint else {})))
    fresh = asyncio.create_task(request("fresh", 0))
    for _ in range(3):
        await asyncio.sleep(0)
    governor.release(drain)  # room for exactly one of them
    for _ in range(3):
        await asyncio.sleep(0)
    assert order == [first]
    for task in (queued, fresh):
        task.cancel()
    await asyncio.gather(queued, fresh, return_exceptions=True)
    assert governor.snapshot()["waiting"] == 0
