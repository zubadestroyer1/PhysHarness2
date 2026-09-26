"""Time/token/cost decomposition per arm from extract_<arm>.json (see timecost_extract.py).

Per-turn model (responses.py `_loop`): saves A (pending op) -> generation_started -> provider ->
save B -> usage -> save C -> per tool: save D, dispatch, save E, tool_completed -> save F
(settled boundary) -> [delivery/turn-note saves] -> token-count preflight -> save A' -> ...
C (usage -> next session.saved) and F (last tool_completed -> next session.saved) are clean,
fully-observed save durations; S(turn) = mean of the two stands for every save of that turn.

Usage: PYTHONPATH=src .venv/bin/python .superpowers/live-run/audit/scripts/timecost_analyze.py
Writes out/analysis.json and prints tables.
"""

import bisect
import collections
import json
import statistics
import sys

import numpy as np

sys.path.insert(0, ".superpowers/live-run/audit/scripts")
from timecost_lib import (  # noqa: E402
    ALL, CLASS, COMPLETED, MAX_OUT_RESERVED, OUT, PRICE_IN, PRICE_OUT, load, pct, summ, turns,
)

LEAN = {"lean_repl_inline", "lean_one_shot", "lean_verify_statement", "lean_backend_probe",
        "lean_repl_daemon"}


def ws_bucket(cls):
    if cls in LEAN:
        return "ws_lean"
    if cls == "search_library_scan":
        return "ws_search_library"
    if cls == "shell_other":
        return "ws_shell"
    if cls in {"upload", "read_range", "promote_file"}:
        return "ws_upload_io"
    return "ws_lifecycle"  # provision/export/destroy/restore


BASELINE_ARMS = ["single", "calibration-doeblin-r2", "calibration-aperiodic", "pilot-doeblin"]


def latency_model():
    """Latency baseline fitted on arms whose org-wide TPM stayed below the 2M limit."""
    X, y = [], []
    for a in BASELINE_ARMS:
        if True:
            for t in turns(load(a)):
                X.append([1, t["output"], t["input"] - t["cached"], t["input"]])
                y.append(t["latency_net"])
    return np.linalg.lstsq(np.array(X, float), np.array(y), rcond=None)[0]


def analyze(arm, coef):
    d = load(arm)
    T = turns(d)
    native_of = {s["id"]: s["native"] for s in d["sessions"]}
    saves = {native_of.get(k): sorted(v) for k, v in d["session_saves"].items()}
    ws_by_tool = collections.defaultdict(list)
    ws_unattributed = []
    for o in d["workspace_ops"]:
        if o["end"] is None:
            continue
        if o["tool"] is not None:
            ws_by_tool[o["tool_op"]].append(o)
        else:
            ws_unattributed.append(o)
    # uploads have no operation id: attribute by time window to the enclosing tool call
    by_session = collections.defaultdict(list)
    for t in T:
        by_session[t["session"]].append(t)
    comp = collections.Counter()
    pred_total = 0.0
    tool_time = collections.Counter()
    tool_count = collections.Counter()
    save_costs = []
    per_turn = []
    windows = []  # (start, end, session, tool_op, tool_name)
    for sid, ts_ in by_session.items():
        ts_.sort(key=lambda t: t["t_gs"])
        S = saves.get(sid, [])
        # measure C and F per turn
        meas = []
        for i, t in enumerate(ts_):
            c = None
            j = bisect.bisect_right(S, t["t_usage"])
            if j < len(S) and (not t["tools"] or S[j] <= t["t_usage"] + t["tools"][0][1]):
                c = S[j] - t["t_usage"]
            f = None
            if t["tools"] and i + 1 < len(ts_):
                j = bisect.bisect_right(S, t["last_t"])
                if j < len(S) and S[j] <= ts_[i + 1]["t_gs"]:
                    f = S[j] - t["last_t"]
            vals = [v for v in (c, f) if v is not None]
            meas.append(statistics.fmean(vals) if vals else None)
        # fill gaps by per-session linear fit on index
        pts = [(i, m) for i, m in enumerate(meas) if m is not None]
        if len(pts) >= 2:
            xs = np.array([p[0] for p in pts], float)
            ys = np.array([p[1] for p in pts], float)
            b, a = np.polyfit(xs, ys, 1)
        elif pts:
            a, b = pts[0][1], 0.0
        else:
            a, b = 0.03, 0.0
        for i, t in enumerate(ts_):
            s_cost = meas[i] if meas[i] is not None else max(0.005, a + b * i)
            save_costs.append(s_cost)
            provider = max(0.0, t["latency_raw"] - s_cost)
            pred = float(coef @ np.array([1, t["output"], t["input"] - t["cached"], t["input"]]))
            comp["provider_generation"] += provider
            pred_total += pred
            comp["persist_saves"] += s_cost  # save B
            n_saves_turn = 2  # A (pending) and B (post-response)
            for k, (name, dur, op) in enumerate(t["tools"]):
                ws = ws_by_tool.get(op, [])
                ws_t = collections.Counter()
                for o in ws:
                    ws_t[ws_bucket(o["class"])] += o["end"] - o["start"]
                n_s = 3 if k == 0 else 2
                n_saves_turn += n_s
                if name == "wait":
                    comp["peer_wait_tool"] += max(0.0, dur - n_s * s_cost)
                    comp["persist_saves"] += min(dur, n_s * s_cost)
                else:
                    rest = dur - sum(ws_t.values()) - n_s * s_cost
                    for kk, v in ws_t.items():
                        comp[kk] += v
                    comp["persist_saves"] += n_s * s_cost
                    comp["tool_dispatch_other"] += max(0.0, rest)
                    if rest < 0:
                        comp["persist_saves"] += rest  # saves overestimated
                tool_time[name] += dur
                tool_count[name] += 1
                start = t["t_usage"] if k == 0 else t["tools"][k - 1][1]
                windows.append((name, dur))
            if t.get("tail_after_usage") is not None:
                comp["persist_saves"] += t["tail_after_usage"]
            if t["gap_after"] is not None:
                i0 = bisect.bisect_right(S, t["last_t"])
                i1 = bisect.bisect_right(S, t["last_t"] + t["gap_after"])
                n_gap = max(0, i1 - i0)
                n_saves_turn += n_gap
                sv = min(t["gap_after"], n_gap * s_cost)
                comp["persist_saves"] += sv
                comp["pregen_preflight_and_updates"] += t["gap_after"] - sv
            per_turn.append({"idx": i, "save": s_cost, "n_saves": n_saves_turn,
                             "provider": provider, "gap": t["gap_after"]})
    # Ops without a tool operation id (uploads, provision, restore, read_range, promote, and
    # export/destroy) ran inside some tool call when they fall within the task's runtime span;
    # move their time out of tool_dispatch_other. Export/destroy after the last runtime event
    # of the task are teardown and stay outside the busy total.
    span = {}
    for r in d["runtime"]:
        tid = r.get("task_id")
        if tid is None:
            continue
        lo, hi = span.get(tid, (r["t"], r["t"]))
        span[tid] = (min(lo, r["t"]), max(hi, r["t"]))
    moved = 0.0
    teardown = 0.0
    for o in ws_unattributed:
        lo, hi = span.get(o["task_id"], (None, None))
        dur = o["end"] - o["start"]
        if lo is not None and lo <= o["start"] <= hi:
            comp[ws_bucket(o["class"])] += dur
            moved += dur
        else:
            teardown += dur
    comp["tool_dispatch_other"] = max(0.0, comp["tool_dispatch_other"] - moved)
    # Arm-level split of model wait into the unthrottled baseline and the excess over it.
    excess = max(0.0, sum(t["latency_net"] for t in T) - pred_total)
    excess = min(excess, comp["provider_generation"])
    comp["provider_generation"] -= excess
    comp["provider_throttle_excess"] = excess
    busy = sum(comp.values())
    # session envelopes
    tasks = {t["id"]: t for t in d["tasks"]}
    lease_to_first = []
    last_to_complete = []
    task_first_gs = {}
    task_last_rt = {}
    for r in d["runtime"]:
        tid = r.get("task_id")
        if tid is None:
            continue
        if r["kind"] == "generation_started":
            task_first_gs.setdefault(tid, r["t"])
        task_last_rt[tid] = r["t"]
    active = 0.0
    leased_total = 0.0
    peer_parked = 0.0
    for tid, evs in d["task_events"].items():
        evs = sorted(evs, key=lambda e: e[1])
        leases = [e[1] for e in evs if e[0] == "task.leased"]
        ends = [e[1] for e in evs if e[0] in ("task.completed", "task.peer_wait_requested",
                                              "task.superseded_by_verification")]
        # lease intervals: each lease until the next end event after it
        for lt in leases:
            nxt = [e for e in ends if e > lt]
            if nxt:
                leased_total += nxt[0] - lt
            else:
                leased_total += d["event_times"]["last"] - lt
        pw = [e[1] for e in evs if e[0] == "task.peer_wait_requested"]
        for p in pw:
            nxt = [lt for lt in leases if lt > p]
            peer_parked += (nxt[0] if nxt else d["event_times"]["last"]) - p
        if tid in task_first_gs and leases:
            lease_to_first.append(task_first_gs[tid] - leases[0])
        comp_t = [e[1] for e in evs if e[0] == "task.completed"]
        if comp_t and tid in task_last_rt:
            last_to_complete.append(comp_t[-1] - task_last_rt[tid])
    for tid in task_first_gs:
        pass
    first_gs = min(t["t_gs"] for t in T)
    last_rt = max(r["t"] for r in d["runtime"])
    lr = d.get("launch_record") or {}
    conc = (lr.get("launch") or {}).get("concurrency")
    wall = last_rt - first_gs
    # tokens and cost
    tin = sum(t["input"] for t in T)
    tcached = sum(t["cached"] for t in T)
    tcw = sum(t["cache_write"] for t in T)
    tout = sum(t["output"] for t in T)
    treas = sum(t["reasoning"] for t in T)
    cost_list = tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT

    def cost_cached(frac):
        return ((tin - tcached) / 1e6 * PRICE_IN + tcached / 1e6 * PRICE_IN * frac
                + tout / 1e6 * PRICE_OUT)

    # verification
    v = d["verifications"]
    promote = [o for o in d["workspace_ops"] if o["command"] == "promote_file"]
    ver = None
    if v and v[0]["queued"] and v[0]["done"]:
        ver = {"queued_to_verified_s": v[0]["done"] - v[0]["queued"],
               "promote_to_queued_s": (v[0]["queued"] - promote[-1]["start"]) if promote else None,
               "first_gs_to_verified_min": (v[0]["done"] - first_gs) / 60}
    fe = d["first_event"]
    t0 = fe.get("experiment.created") or d["event_times"]["first"]
    startup = {
        "created_to_task_queued_s": (fe.get("task.queued") or t0) - t0,
        "task_queued_to_leased_s": (fe.get("task.leased") or t0) - (fe.get("task.queued") or t0),
        "leased_to_first_generation_s": first_gs - (fe.get("task.leased") or t0),
        "first_generation_to_first_usage_s": min(t["t_usage"] for t in T) - first_gs,
        "first_generation_to_first_provision_s": (fe.get("workspace.operation.pending") or first_gs) - first_gs,
    }
    # queue waits
    qwait = []
    for tid, evs in d["task_events"].items():
        q = [e[1] for e in evs if e[0] == "task.queued"]
        lz = [e[1] for e in evs if e[0] == "task.leased"]
        if q and lz:
            qwait.append(lz[0] - q[0])
    ops = d["workspace_ops"]
    op_summary = {}
    for cls in sorted({o["class"] for o in ops}):
        durs = [o["end"] - o["start"] for o in ops if o["class"] == cls and o["end"]]
        op_summary[cls] = summ(durs)
    peaks = [o["peak_bytes"] for o in ops if o["peak_bytes"]]
    lean_peaks = [o["peak_bytes"] for o in ops if o["peak_bytes"] and o["class"] in LEAN]
    res = {
        "arm": arm, "class": CLASS.get(arm), "concurrency": conc, "wall_s": wall,
        "slot_seconds": (conc or 0) * wall, "turns": len(T), "sessions": len(by_session),
        "tasks": len(d["tasks"]), "components_s": dict(comp), "busy_s": busy,
        "ws_ops_outside_runtime_s": teardown,
        "leased_s": leased_total, "peer_parked_s": peer_parked,
        "lease_to_first_generation_s": summ(lease_to_first),
        "last_runtime_to_task_completed_s": summ(last_to_complete),
        "save_cost_s": summ(save_costs),
        "saves_total": sum(len(v) for v in d["session_saves"].values()),
        "saves_per_turn": sum(len(v) for v in d["session_saves"].values()) / len(T),
        "latency_raw": summ([t["latency_raw"] for t in T]),
        "latency_net": summ([t["latency_net"] for t in T]),
        "gap": summ([t["gap_after"] for t in T if t["gap_after"] is not None]),
        "tokens": {"input": tin, "cached": tcached, "cache_write": tcw, "output": tout,
                   "reasoning": treas, "cached_share": tcached / tin if tin else None,
                   "in_out_ratio": tin / tout if tout else None,
                   "input_per_turn": summ([t["input"] for t in T]),
                   "output_per_turn": summ([t["output"] for t in T])},
        "cost": {"list": cost_list, "cached_10pct": cost_cached(0.10),
                 "cached_25pct": cost_cached(0.25), "cached_50pct": cost_cached(0.50),
                 "ledger": (d["run_team"].get("ledger") or {}).get("spent_cost_usd")},
        "verification": ver, "startup": startup, "queue_wait": summ(qwait),
        "tool_time_s": dict(tool_time), "tool_count": dict(tool_count),
        "workspace_ops": op_summary,
        "ws_peak_bytes": summ(peaks), "ws_lean_peak_bytes": summ(lean_peaks),
        "artifact_counts": d["artifact_counts"], "artifact_bytes": d["artifact_bytes"],
        "event_count": len(d["event_ts"]),
        "db_rows_est": sum(d["artifact_counts"].values()) + len(d["event_ts"]),
    }
    return res


def main():
    coef = latency_model()
    results = {"latency_model": {"const_s": coef[0], "per_output_token_s": coef[1],
                                 "per_uncached_input_token_s": coef[2],
                                 "per_input_token_s": coef[3]}}
    for arm in ALL:
        results[arm] = analyze(arm, coef)
    with open(f"{OUT}/analysis.json", "w") as f:
        json.dump(results, f, indent=1, default=float)
    keys = ["provider_generation", "provider_throttle_excess", "ws_lean", "ws_search_library",
            "ws_shell", "ws_upload_io", "ws_lifecycle", "tool_dispatch_other", "peer_wait_tool",
            "persist_saves", "pregen_preflight_and_updates"]
    print(f"{'arm':22s} {'conc':>4s} {'wall':>6s} {'leased':>7s} {'busy':>7s} " + " ".join(f"{k[:12]:>12s}" for k in keys))
    for arm in ALL:
        r = results[arm]
        c = r["components_s"]
        print(f"{arm:22s} {r['concurrency'] or 0:4d} {r['wall_s']:6.0f} {r['leased_s']:7.0f} {r['busy_s']:7.0f} "
              + " ".join(f"{c.get(k, 0):12.0f}" for k in keys))
    print()
    for arm in ALL:
        r = results[arm]
        tk = r["tokens"]
        co = r["cost"]
        print(f"{arm:22s} in={tk['input']/1e6:6.2f}M cached={tk['cached_share']:.3f} out={tk['output']/1e3:6.1f}k reas={tk['reasoning']/1e3:5.1f}k "
              f"in/out={tk['in_out_ratio']:4.0f} cost list=${co['list']:7.2f} c10=${co['cached_10pct']:6.2f} c25=${co['cached_25pct']:6.2f} c50=${co['cached_50pct']:6.2f} ledger={co['ledger']}")


if __name__ == "__main__":
    main()
