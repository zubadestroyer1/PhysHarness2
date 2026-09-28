"""Offline check that the runtime's input-reservation bound held on recorded turns (G4, P1).

Usage: python tools/reservation_bound.py DATA_DIR [--threshold 183808] [--margin 8192]
       [--margin-floor 2048] [--margin-percent 2]

DATA_DIR has one directory per arm with the audit extraction's turns.jsonl and messages.jsonl.
For consecutive completed turns of a session whose first response had no compaction, the
runtime bounds the second request's input by the first request's billed input plus the
canonical UTF-8 bytes of every request element that differs from the element at the same
position in the first request, plus a margin of max(floor, percent of that sum). The extraction
cannot see re-rendered instructions or tools, or items replaced in place (S1 had none), so the
changed elements here are the items appended since, that response's output included. It keeps
characters, not item bytes, so this sums ``chars`` + ``encrypted_chars``: item JSON contains
those strings and more, and UTF-8 has at least one byte per character, so this never exceeds
the runtime's bound. The gate is the raw ratio of actual to bound, without the margin, which
must stay <= 1. The ratio with the margin (expected <= 0.98) is reported, never enforced.
Prints JSON; exits 1 when a raw ratio exceeds 1. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def check(
    data_dir: Path,
    *,
    threshold: int,
    margin: int,
    margin_floor: int = 2_048,
    margin_percent: int = 2,
) -> dict:
    pairs = []
    for arm in sorted(path for path in data_dir.iterdir() if path.is_dir()):
        appended: dict = defaultdict(int)  # (session, turn) -> chars first sent that turn
        produced: dict = defaultdict(int)  # (session, turn) -> chars of that turn's output
        for entry in _rows(arm / "messages.jsonl"):
            if entry.get("inherited") or entry.get("turn") is None:
                continue
            target = appended if entry["direction"] == "model_input" else produced
            target[(entry["session_id"], entry["turn"])] += (entry.get("chars") or 0) + (
                entry.get("encrypted_chars") or 0
            )
        turns = {(row["session_id"], row["turn"]): row for row in _rows(arm / "turns.jsonl")}
        for (session, number), row in sorted(turns.items()):
            nxt = turns.get((session, number + 1))
            if (
                not row["completed"]
                or nxt is None
                or not nxt["completed"]
                or "compaction" in (row.get("output_item_types") or [])
                or row.get("compaction_events")
            ):
                continue
            raw = (
                row["input_tokens"] + produced[(session, number)] + appended[(session, number + 1)]
            )
            bound = raw + max(margin_floor, (raw * margin_percent + 99) // 100)  # as the runtime
            pairs.append(
                {
                    "arm": arm.name,
                    "session": session[:8],
                    "turn": number + 1,
                    "input_tokens": nxt["input_tokens"],
                    "bound_raw": raw,
                    "bound": bound,
                    "ratio_raw": nxt["input_tokens"] / raw,
                    "ratio": nxt["input_tokens"] / bound,
                    "reserved_by_bound": bound + margin <= threshold,
                }
            )
    raws, ratios = [pair["ratio_raw"] for pair in pairs], [pair["ratio"] for pair in pairs]
    max_ratio, max_ratio_raw = max(ratios, default=0.0), max(raws, default=0.0)
    return {
        "pairs": len(pairs),
        "max_ratio": max_ratio,
        "max_ratio_raw": max_ratio_raw,
        "median_ratio": statistics.median(ratios) if ratios else None,
        "violations": sum(ratio > 1 for ratio in raws),
        "reserved_by_bound": sum(pair["reserved_by_bound"] for pair in pairs),
        "margin_expected_met": max_ratio <= 0.98,
        "worst": sorted(pairs, key=lambda pair: pair["ratio_raw"], reverse=True)[:5],
        "passed": bool(pairs) and max_ratio_raw <= 1.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--threshold", type=int, default=183_808)
    parser.add_argument("--margin", type=int, default=8_192)
    parser.add_argument("--margin-floor", type=int, default=2_048)
    parser.add_argument("--margin-percent", type=int, default=2)
    args = parser.parse_args(argv)
    report = check(
        args.data_dir,
        threshold=args.threshold,
        margin=args.margin,
        margin_floor=args.margin_floor,
        margin_percent=args.margin_percent,
    )
    json.dump(report, sys.stdout, indent=1)
    print()
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
