"""Shared helpers for the time-and-cost audit: turn reconstruction from extract_<arm>.json."""

import bisect
import collections
import json
import statistics

OUT = ".superpowers/live-run/audit/scripts/out"
COMPLETED = [
    "calibration-doeblin-r2", "calibration-aperiodic", "pilot-doeblin", "S-r2",
    "I-01", "I-02", "I-03", "I-04", "I-05", "I-06", "I-07", "I-08", "single",
]
ALL = ["calibration-doeblin", "S"] + COMPLETED
CLASS = {
    "calibration-doeblin-r2": "calibration", "calibration-aperiodic": "calibration",
    "pilot-doeblin": "pilot", "S-r2": "S-r2", "S": "S(fail)", "calibration-doeblin": "cal(paused)",
    "single": "single",
}
for i in range(1, 9):
    CLASS[f"I-0{i}"] = "I"
PRICE_IN, PRICE_OUT = 2.50, 10.00
MAX_OUT_RESERVED = 64000


def load(arm):
    with open(f"{OUT}/extract_{arm}.json") as f:
        return json.load(f)


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def summ(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0}
    return {
        "n": len(xs), "sum": sum(xs), "mean": statistics.fmean(xs),
        "p50": pct(xs, 0.5), "p90": pct(xs, 0.9), "p99": pct(xs, 0.99), "max": max(xs),
        "min": min(xs),
    }


def turns(d):
    """Reconstruct turns per native session.

    Returns list of dicts with t_gs, t_usage, latency_raw, latency_net (to the first
    checkpoint chunk after generation_started, i.e. response arrival + pre-encode),
    tokens, tools (name, dur), gap_after.
    """
    by_session = collections.defaultdict(list)
    for r in d["runtime"]:
        by_session[r["session"]].append(r)
    chunk_times = {s: [c[0] for c in v] for s, v in d["chunks"].items()}
    manifest_times = {s: [m[0] for m in v] for s, v in d["manifests"].items()}
    out = []
    for sid, evs in by_session.items():
        evs.sort(key=lambda r: r["t"])
        gs = {}
        cur = None
        ct = chunk_times.get(sid, [])
        mt = manifest_times.get(sid, [])
        idx = 0
        prev_end = None
        for r in evs:
            k = r["kind"]
            if k == "generation_started":
                if cur is not None:
                    cur["gap_after"] = r["t"] - cur["last_t"]
                gs[r["op"]] = r["t"]
                cur = None
                pending = r
            elif k == "usage":
                t0 = gs.get(r["op"])
                if t0 is None:
                    continue
                p = r["payload"]
                nu = p.get("native_usage") or {}
                itd = nu.get("input_tokens_details") or {}
                otd = nu.get("output_tokens_details") or {}
                j = bisect.bisect_right(ct, t0)
                first_chunk = ct[j] if j < len(ct) else None
                jm = bisect.bisect_right(mt, t0)
                first_man = mt[jm] if jm < len(mt) else None
                cand = [x for x in (first_chunk, first_man) if x is not None and x <= r["t"]]
                arrival = min(cand) if cand else r["t"]
                cur = {
                    "session": sid, "task_id": r.get("task_id"), "op": r["op"], "t_gs": t0,
                    "t_usage": r["t"], "latency_raw": r["t"] - t0, "latency_net": arrival - t0,
                    "input": p.get("input_tokens") or 0, "output": p.get("output_tokens") or 0,
                    "cached": itd.get("cached_tokens") or 0,
                    "cache_write": itd.get("cache_write_tokens") or 0,
                    "reasoning": otd.get("reasoning_tokens") or 0,
                    "tools": [], "last_t": r["t"], "gap_after": None, "idx": idx,
                }
                idx += 1
                out.append(cur)
            elif k == "tool_completed":
                if cur is None:
                    continue
                cur["tools"].append((r["payload"].get("name"), r["t"] - cur["last_t"], r["op"]))
                cur["last_t"] = r["t"]
            elif k in ("completed",):
                if cur is not None:
                    cur["completed"] = True
                    cur["tail_after_usage"] = r["t"] - cur["last_t"]
                    cur["last_t"] = r["t"]
    return out


def session_saves(d):
    """Per native session: list of (start, end, n_chunks, chunk_bytes) for each save.

    A save's chunks are those created after the previous session.saved of the same
    session; its duration is session.saved minus its first chunk/manifest artifact.
    """
    native_of = {s["id"]: s["native"] for s in d["sessions"]}
    res = {}
    for rec_id, times in d["session_saves"].items():
        native = native_of.get(rec_id)
        times = sorted(times)
        ch = sorted(d["chunks"].get(native, []))
        mans = sorted(m[0] for m in d["manifests"].get(native, []))
        cts = [c[0] for c in ch]
        saves = []
        prev = -1e18
        for t in times:
            a = bisect.bisect_right(cts, prev)
            b = bisect.bisect_right(cts, t)
            mine = ch[a:b]
            ma = bisect.bisect_right(mans, prev)
            mb = bisect.bisect_right(mans, t)
            starts = [c[0] for c in mine] + mans[ma:mb]
            start = min(starts) if starts else t
            saves.append((start, t, len(mine), sum(c[1] for c in mine)))
            prev = t
        res[native] = saves
    return res
