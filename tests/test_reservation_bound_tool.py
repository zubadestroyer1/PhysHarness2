"""tools/reservation_bound.py on synthetic audit data (the S1 data is private)."""

import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "reservation_bound_tool", Path(__file__).resolve().parents[1] / "tools/reservation_bound.py"
)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def turn(session, number, tokens, *, completed=True, items=("reasoning", "function_call")):
    return {
        "session_id": session,
        "turn": number,
        "completed": completed,
        "input_tokens": tokens,
        "output_item_types": list(items),
        "compaction_events": [],
    }


def item(session, number, direction, chars, encrypted=None):
    return {
        "session_id": session,
        "turn": number,
        "direction": direction,
        "inherited": False,
        "chars": chars,
        "encrypted_chars": encrypted,
    }


def write(arm, turns, messages):
    arm.mkdir(parents=True)
    (arm / "turns.jsonl").write_text("".join(json.dumps(r) + "\n" for r in turns))
    (arm / "messages.jsonl").write_text("".join(json.dumps(r) + "\n" for r in messages))


def test_bound_passes_when_growth_fits_the_appended_bytes(tmp_path):
    write(
        tmp_path / "A",
        [turn("s", 1, 1000), turn("s", 2, 1100)],
        [
            item("s", 1, "model_input", 4000),
            item("s", 1, "model_output", 20, 300),
            item("s", 2, "model_input", 200),
        ],
    )
    report = tool.check(tmp_path, threshold=183_808, margin=8_192)
    assert (report["pairs"], report["violations"], report["passed"]) == (1, 0, True)
    assert report["max_ratio_raw"] == 1100 / (1000 + 320 + 200)
    assert report["max_ratio"] == 1100 / (1520 + 2048)  # the 2,048 floor exceeds 2% of 1,520
    assert report["margin_expected_met"] and report["reserved_by_bound"] == 1


def test_gate_passes_on_the_raw_ratio_and_only_reports_the_margin_ratio(tmp_path):
    write(
        tmp_path / "A",
        [turn("s", 1, 199_000), turn("s", 2, 199_990)],
        [item("s", 2, "model_input", 1_000)],
    )
    report = tool.check(tmp_path, threshold=183_808, margin=8_192)
    assert (report["passed"], report["margin_expected_met"], report["reserved_by_bound"]) == (
        True,
        False,
        0,
    )
    assert report["max_ratio"] == 199_990 / (200_000 + 4_000)  # above 0.98, recorded, not a failure
    assert tool.main([str(tmp_path)]) == 0


def test_bound_reports_violations_and_skips_compaction_and_failed_turns(tmp_path):
    write(
        tmp_path / "A",
        [
            turn("s", 1, 1000),
            turn("s", 2, 5000),
            turn("t", 1, 1000, items=("compaction",)),
            turn("t", 2, 10),
            turn("u", 1, 1000, completed=False),
            turn("u", 2, 9000),
        ],
        [item("s", 1, "model_output", 10), item("s", 2, "model_input", 10)],
    )
    report = tool.check(tmp_path, threshold=183_808, margin=8_192)
    assert (report["pairs"], report["violations"], report["passed"]) == (1, 1, False)
    assert tool.main([str(tmp_path)]) == 1


def test_tool_defaults_match_the_runtime_bound():
    """The G4 gate must check the margins the runtime reserves, so its defaults cannot drift."""
    import inspect

    from physharness.execution import responses
    from physharness.execution.context_policy import CONTEXT_MARGIN

    source = inspect.getsource(tool.main)
    assert f'"--margin", type=int, default={CONTEXT_MARGIN:_}' in source
    assert f'"--margin-floor", type=int, default={responses.BOUND_MARGIN_FLOOR:_}' in source
    assert f'"--margin-percent", type=int, default={responses.BOUND_MARGIN_PERCENT}' in source
    check = inspect.signature(tool.check).parameters
    assert check["margin_floor"].default == responses.BOUND_MARGIN_FLOOR
    assert check["margin_percent"].default == responses.BOUND_MARGIN_PERCENT
