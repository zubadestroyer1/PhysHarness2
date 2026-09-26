"""Counterfactual token simulations on the observed per-turn context sequences.

Assumes the agents' trajectories (turn count, outputs, tool results) are unchanged; only the
context resent each turn changes. Reports total input tokens, the implied throughput under a
fixed TPM ceiling, and cost at list price and with a 10% cached-input price.
Usage: PYTHONPATH=src .venv/bin/python .superpowers/live-run/audit/scripts/timecost_simulate.py
"""

import collections
import json
import sys

sys.path.insert(0, ".superpowers/live-run/audit/scripts")
from timecost_lib import COMPLETED, OUT, PRICE_IN, PRICE_OUT, load, turns  # noqa: E402

STUB = 40  # tokens left behind for an elided tool result
SUMMARY = 6000  # tokens of a compaction summary carried forward
SUMMARY_OUT = 3000  # output tokens to write the summary


def sessions(arm):
    by = collections.defaultdict(list)
    for t in turns(load(arm)):
        by[t["session"]].append(t)
    for v in by.values():
        v.sort(key=lambda t: t["t_gs"])
    return list(by.values())


def seq(ts_):
    """base, per-turn output, per-turn added non-output tokens (deltas >= 0)."""
    base = ts_[0]["input"]
    outs, adds = [], []
    for a, b in zip(ts_, ts_[1:]):
        dlt = b["input"] - a["input"]
        if dlt < 0:  # a real compaction happened: treat as reset, no growth
            dlt = a["output"]
        outs.append(a["output"])
        adds.append(max(0, dlt - a["output"]))
    return base, outs, adds


def observed(ts_):
    return sum(t["input"] for t in ts_), 0


def compaction(ts_, threshold):
    base, outs, adds = seq(ts_)
    y = base
    total = y
    extra_out = 0
    n = 0
    for o, a in zip(outs, adds):
        y += o + a
        if y > threshold:
            total += y  # the compaction request itself reads the full context
            extra_out += SUMMARY_OUT
            n += 1
            y = base + SUMMARY
        total += y
    return total, extra_out, n


def elide(ts_, keep):
    """Every `keep` turns, replace tool results older than `keep` turns by a stub."""
    base, outs, adds = seq(ts_)
    total = base
    for k in range(1, len(ts_)):
        boundary = (k // keep) * keep - keep
        ctx = base + sum(outs[:k])
        for j in range(k):
            ctx += adds[j] if j >= boundary else min(adds[j], STUB)
        total += ctx
    return total, 0


def main():
    rows = {}
    scenarios = [("observed", lambda s: observed(s))]
    for c in (128_000, 96_000, 64_000, 48_000):
        scenarios.append((f"compact@{c // 1000}k", lambda s, c=c: compaction(s, c)[:2]))
    for k in (40, 20, 10):
        scenarios.append((f"elide>{k}turns", lambda s, k=k: elide(s, k)))
    groups = {"S-r2": ["S-r2"], "I(8 arms)": [f"I-0{i}" for i in range(1, 9)], "single": ["single"],
              "all completed": COMPLETED}
    for g, arms in groups.items():
        ss = [s for a in arms for s in sessions(a)]
        out_tok = sum(t["output"] for s in ss for t in s)
        cached_share = sum(t["cached"] for s in ss for t in s) / sum(t["input"] for s in ss for t in s)
        n_turns = sum(len(s) for s in ss)
        base_total = None
        rows[g] = {}
        for name, fn in scenarios:
            tin = 0
            xo = 0
            for s in ss:
                a, b = fn(s)
                tin += a
                xo += b
            if base_total is None:
                base_total = tin
            list_cost = tin / 1e6 * PRICE_IN + (out_tok + xo) / 1e6 * PRICE_OUT
            cached_cost = (tin * (1 - cached_share) / 1e6 * PRICE_IN
                           + tin * cached_share / 1e6 * PRICE_IN * 0.1
                           + (out_tok + xo) / 1e6 * PRICE_OUT)
            rows[g][name] = {"input": tin, "vs_observed": tin / base_total,
                             "tokens_per_turn": (tin + out_tok + xo) / n_turns,
                             "throughput_x_at_fixed_tpm": base_total / tin,
                             "cost_list": list_cost, "cost_cached10": cached_cost}
        print(f"== {g}: turns={n_turns}")
        for name, r in rows[g].items():
            print(f"   {name:16s} input={r['input']/1e6:7.2f}M ({r['vs_observed']:5.1%}) tok/turn={r['tokens_per_turn']/1e3:5.1f}k "
                  f"TPM-bound throughput x{r['throughput_x_at_fixed_tpm']:4.2f} list=${r['cost_list']:7.2f} cached10=${r['cost_cached10']:6.2f}")
    # fixed-prefix share: first-turn input resent every turn
    for g, arms in groups.items():
        ss = [s for a in arms for s in sessions(a)]
        prefix = sum(s[0]["input"] * len(s) for s in ss)
        tot = sum(t["input"] for s in ss for t in s)
        rows[g]["fixed_prefix_share"] = prefix / tot
        print(f"{g}: fixed first-turn prefix resent each turn = {prefix / tot:.1%} of input")
    with open(f"{OUT}/simulate.json", "w") as f:
        json.dump(rows, f, indent=1)


if __name__ == "__main__":
    main()
