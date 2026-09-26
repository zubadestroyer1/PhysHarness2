"""Reassemble final native checkpoints per session; measure state composition and save CPU cost.

Read-only. Offline CPU timing of the per-save work (build digest + deepcopy, verify, encode
with an in-memory put) on the reconstructed final state of each session.
Usage: PYTHONPATH=src .venv/bin/python .superpowers/live-run/audit/scripts/timecost_checkpoints.py [arm ...]
"""

import collections
import hashlib
import json
import sys
import time

sys.path.insert(0, ".superpowers/live-run/audit/scripts")
from timecost_extract import Content  # noqa: E402
from timecost_lib import COMPLETED, OUT, load  # noqa: E402

from physharness.domain import canonical_json  # noqa: E402
from physharness.execution.checkpoint_chunks import decode, encode  # noqa: E402
from physharness.execution.types import RuntimeCheckpoint  # noqa: E402


def blen(x):
    return len(json.dumps(x, ensure_ascii=False).encode("utf-8"))


def composition(state):
    comp = collections.Counter()
    counts = collections.Counter()
    for item in state.get("input", []):
        t = item.get("type") or item.get("role") or "?"
        if t == "message":
            t = f"message:{item.get('role')}"
        comp[t] += blen(item)
        counts[t] += 1
    return comp, counts


def main():
    arms = sys.argv[1:] or COMPLETED
    results = {}
    for arm in arms:
        d = load(arm)
        content = Content(arm)
        rows = []
        for native, mans in d["manifests"].items():
            if not mans:
                continue
            t, size, aid, sha = sorted(mans)[-1]
            raw = content.read(sha)
            if raw is None:
                continue

            def read(ref):
                return content.read(ref["sha256"])

            try:
                cp = decode(raw, read)
            except Exception as exc:  # pragma: no cover - audit tooling
                rows.append({"session": native, "error": str(exc)[:200]})
                continue
            state = cp.native_state
            full = canonical_json(cp.model_dump(mode="json")).encode("utf-8")
            comp, counts = composition(state)
            responses_b = blen(state.get("responses", []))
            enc_reason = 0
            for r in state.get("responses", []):
                for o in r.get("output", []):
                    if o.get("type") == "reasoning":
                        enc_reason += len(o.get("encrypted_content") or "")
            tool_results_b = blen(state.get("tool_results", {}))
            # per-save CPU: build (digest+deepcopy) + verify + encode(verify + size + nodes)
            t0 = time.perf_counter()
            cp2 = RuntimeCheckpoint.build(cp.session, state)
            t1 = time.perf_counter()
            cp2.verify()
            t2 = time.perf_counter()
            store = {}

            def put(c):
                h = hashlib.sha256(c.encode("utf-8")).hexdigest()
                store[h] = c
                return {"id": h, "sha256": h}

            encode(cp2, put)
            t3 = time.perf_counter()
            rows.append({
                "session": native, "bytes": len(full), "input_items": len(state.get("input", [])),
                "input_bytes": blen(state.get("input", [])), "responses_bytes": responses_b,
                "encrypted_reasoning_chars_in_responses": enc_reason,
                "tool_results_bytes": tool_results_b,
                "composition": dict(comp), "counts": dict(counts),
                "turns": cp.session.turns, "input_tokens": cp.session.input_tokens,
                "output_tokens": cp.session.output_tokens,
                "cpu_build_s": t1 - t0, "cpu_verify_s": t2 - t1, "cpu_encode_s": t3 - t2,
                "encode_nodes": len(store),
                "compactions": state.get("provider_compaction_count", 0),
            })
        results[arm] = rows
        tot = sum(r.get("bytes", 0) for r in rows)
        print(arm, len(rows), "sessions; final state bytes total", tot)
    with open(f"{OUT}/checkpoints.json", "w") as f:
        json.dump(results, f)


if __name__ == "__main__":
    main()
