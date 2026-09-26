"""Offline policy and native context behavior for formal research."""

import json

import pytest
from test_execution_context import compaction_item, response, sdk_client, text_item

from physharness.execution import (
    ExecutionError,
    ModelConfig,
    ResponsesRuntime,
    RuntimeCheckpoint,
    RuntimeLimits,
    SQLiteRuntimeStore,
    ToolDispatcher,
)
from physharness.execution.context_policy import apply_context_profile
from physharness.execution.stagnation import observe, successor_state


def test_research_profile_and_explicit_stress_override():
    model = ModelConfig(model="exact-model", parameters={"reasoning": {"effort": "high"}})
    limits = RuntimeLimits(
        max_context_tokens=128000, max_output_tokens=16384, max_total_tokens=None
    )
    research = apply_context_profile(model, limits)
    assert research.parameters["context_management"] == [
        {"type": "compaction", "compact_threshold": 96000}
    ]
    assert model.parameters.get("context_management") is None
    assert (
        apply_context_profile(model, limits, "stress8192").parameters["context_management"][0][
            "compact_threshold"
        ]
        == 8192
    )
    override = model.model_copy(
        update={
            "parameters": {
                "context_management": [{"type": "compaction", "compact_threshold": 32768}]
            }
        }
    )
    assert apply_context_profile(override, limits).parameters == override.parameters


def test_small_windows_and_unsafe_overrides_fail_closed():
    model = ModelConfig(model="exact-model")
    limits = RuntimeLimits(max_context_tokens=20000, max_output_tokens=4096)
    assert (
        apply_context_profile(model, limits).parameters["context_management"][0][
            "compact_threshold"
        ]
        == 7712
    )
    with pytest.raises(ExecutionError):
        apply_context_profile(
            model, RuntimeLimits(max_context_tokens=12000, max_output_tokens=4096)
        )
    with pytest.raises(ExecutionError):
        apply_context_profile(
            ModelConfig(
                model="x",
                parameters={
                    "context_management": [{"type": "compaction", "compact_threshold": 8000}]
                },
            ),
            limits,
        )


def test_stagnation_crosses_calls_and_recovery_is_bounded():
    state = {}
    read = {"argv": ["tail", "-n", "10", "lean.log"]}
    result = {"exit_code": 0, "stdout": "same", "stderr": ""}
    assert [observe(state, "run_command", read, result) for _ in range(8)] == [
        None,
        None,
        None,
        "stagnation_warning",
        None,
        None,
        None,
        "recovery_requested",
    ]
    assert max(state["read_counts"].values()) == 8
    resumed = successor_state(state)
    assert resumed["recovery_attempted"] and not resumed["recovery_requested"]
    assert [observe(resumed, "run_command", read, result) for _ in range(8)] == [
        None,
        None,
        None,
        "stagnation_warning",
        None,
        None,
        None,
        "recovery_exhausted",
    ]
    assert observe(resumed, "run_command", read, result) is None


def test_pending_polling_and_duplicate_notes_do_not_change_progress():
    state = {}
    for _ in range(4):
        assert (
            observe(state, "wait_for_verification", {"receipt_id": "q"}, {"status": "queued"})
            is None
        )
        assert (
            observe(state, "checkpoint_research_notes", {"summary": "same"}, {"id": "same"}) is None
        )
    assert state.get("progress_epoch", 0) == 0
    assert state.get("read_counts", {}) == {}
    observe(state, "run_command", {"argv": ["tail", "log"]}, {"exit_code": 0, "stdout": "x"})
    observe(state, "write_workspace_file", {"path": "Main.lean"}, {"path": "Main.lean"})
    assert state["progress_epoch"] == 1 and state["read_counts"] == {}


def test_failed_receipt_and_same_source_alternation_cannot_evade_recovery():
    state = {}
    failures = [
        {"id": "a", "status": "blocked", "diagnostics": "same failed artifact"},
        {"id": "b", "status": "rejected", "diagnostics": "same failed artifact"},
    ]
    signals = []
    for index in range(16):
        signals.append(
            observe(
                state,
                "inspect_verification",
                {"receipt_id": failures[index % 2]["id"]},
                {
                    **failures[index % 2],
                    "operation_id": f"read-{index}",
                },
            )
        )
        observe(state, "checkpoint_research_notes", {"summary": "same"}, {"id": "notes"})
        observe(
            state,
            "submit_candidate",
            {"source": "same failed artifact"},
            {"id": f"candidate-{index}"},
        )
        observe(
            state,
            "write_workspace_file",
            {"path": f"Main{index}.lean", "content": "same failed artifact"},
            {"path": f"Main{index}.lean"},
        )
    assert signals.count("stagnation_warning") == 1
    assert signals.count("recovery_requested") == 1
    assert state["recovery_requested"] is True
    assert state["progress_epoch"] == 2
    assert (
        observe(
            state,
            "write_workspace_file",
            {"path": "Main.lean", "content": "a new source"},
            {"id": "fresh"},
        )
        is None
    )
    assert state["progress_epoch"] == 3 and state["read_counts"] == {}


def test_general_shell_noops_do_not_reset_repeated_terminal_reads():
    state, signals = {}, []
    for index in range(8):
        signals.append(
            observe(
                state,
                "run_command",
                {"argv": ["tail", "log"]},
                {"exit_code": 0, "stdout": "unchanged", "operation_id": f"read-{index}"},
            )
        )
        observe(
            state,
            "run_command",
            {"argv": ["sh", "-lc", f"echo {index}"]},
            {"exit_code": 0, "stdout": str(index), "operation_id": f"echo-{index}"},
        )
    assert signals.count("stagnation_warning") == 1
    assert signals.count("recovery_requested") == 1
    assert state.get("progress_epoch", 0) == 0


def test_distinct_terminal_targets_with_identical_content_do_not_pool():
    state = {}
    signals = [
        observe(
            state,
            "run_command",
            {"argv": ["cat", f"file-{index}.txt"]},
            {"exit_code": 0, "stdout": "same", "operation_id": f"read-{index}"},
        )
        for index in range(8)
    ]
    assert signals == [None] * 8
    assert len(state["read_counts"]) == 8
    receipts = {}
    for index in range(8):
        assert (
            observe(
                receipts,
                "inspect_verification",
                {"receipt_id": f"receipt-{index}"},
                {"status": "blocked", "diagnostics": "same"},
            )
            is None
        )
    assert len(receipts["read_counts"]) == 8


@pytest.mark.parametrize(
    "name,arguments,result",
    [
        (
            "read_workspace_file",
            {"path": "Main.lean", "offset": 0, "length": 1024},
            {
                "path": "Main.lean",
                "offset": 0,
                "text": "theorem t : True := by trivial",
                "exact_base64": "dA==",
                "size_bytes": 708,
                "remaining_bytes": 0,
            },
        ),
        (
            "search_library_source",
            {"query": "trace"},
            {
                "hits": [{"path": "mathlib/LinearAlgebra.lean", "line": 4, "snippet": "trace"}],
                "reason_code": None,
                "mechanism": "lexical_source_scan",
            },
        ),
        (
            "lookup_library_source",
            {"path": "mathlib/LinearAlgebra.lean"},
            {
                "path": "/opt/sources/mathlib/LinearAlgebra.lean",
                "sha256": "a" * 64,
                "text": "#check trace",
                "reason_code": None,
            },
        ),
        (
            "lookup_library_declaration",
            {"name": "LinearMap.trace", "imports": ["Mathlib"]},
            {
                "name": "LinearMap.trace",
                "mechanism": "lean_elaborated_declaration_lookup",
                "diagnostics": {"exit_code": 0, "stdout": "type"},
            },
        ),
        (
            "check_lean_type",
            {"expression": "Nat", "imports": ["Mathlib"]},
            {
                "expression": "Nat",
                "mechanism": "lean_elaboration",
                "reason_code": None,
                "diagnostics": {"exit_code": 0, "stdout": "Nat : Type"},
            },
        ),
        (
            "joined_children",
            {},
            {
                "task_id": "parent",
                "children": [{"task_id": "child", "status": "completed"}],
                "pending_ids": [],
            },
        ),
    ],
)
def test_new_read_tools_warn_and_recover_at_four_and_eight(name, arguments, result):
    state = {}
    signals = [
        observe(state, name, arguments, {**result, "operation_id": f"read-{index}"})
        for index in range(8)
    ]
    assert signals == [
        None,
        None,
        None,
        "stagnation_warning",
        None,
        None,
        None,
        "recovery_requested",
    ]
    assert state.get("progress_epoch", 0) == 0


def test_new_reads_and_failed_diagnostics_cannot_reset_terminal_receipt_loop():
    state, signals = {}, []
    for index in range(8):
        signals.append(
            observe(
                state,
                "inspect_verification",
                {"receipt_id": "failed"},
                {
                    "status": "rejected",
                    "diagnostics": "same error",
                    "operation_id": f"receipt-{index}",
                },
            )
        )
        observe(
            state,
            "read_workspace_file",
            {"path": f"different-{index}.lean", "offset": 0, "length": 1024},
            {"error": {"code": "FILE_MISSING", "operation_id": f"read-{index}"}},
        )
        observe(
            state,
            "check_lean_type",
            {"expression": f"Unknown{index}", "imports": ["Mathlib"]},
            {
                "reason_code": "lean_elaboration_failed",
                "diagnostics": {"exit_code": 1, "stderr": "unknown constant"},
            },
        )
    assert signals.count("stagnation_warning") == 1
    assert signals.count("recovery_requested") == 1
    assert state.get("progress_epoch", 0) == 0


def test_pending_joined_polling_exempt_and_distinct_type_queries_do_not_pool():
    state = {}
    for index in range(8):
        assert (
            observe(
                state,
                "joined_children",
                {},
                {
                    "task_id": "parent",
                    "children": [{"task_id": "child", "status": "running"}],
                    "pending_ids": ["child"],
                },
            )
            is None
        )
        assert (
            observe(
                state,
                "child_task_status",
                {"task_ids": ["child"]},
                {
                    "task_id": "parent",
                    "children": [{"task_id": "child", "status": "queued"}],
                    "all_terminal": False,
                },
            )
            is None
        )
        assert (
            observe(
                state,
                "check_lean_type",
                {"expression": f"Expr{index}", "imports": ["Mathlib"]},
                {
                    "expression": f"Expr{index}",
                    "diagnostics": {"exit_code": 1, "stderr": "unknown"},
                },
            )
            is None
        )
    assert state.get("progress_epoch", 0) == 0
    assert len(state["read_counts"]) == 8


@pytest.mark.asyncio
async def test_terminal_multiple_compactions_counted_and_result_recoverable(tmp_path):
    requests, events = [], []
    client = sdk_client(
        [response([compaction_item("a"), compaction_item("b"), text_item("done")], "r1")], requests
    )
    store = SQLiteRuntimeStore(tmp_path / "runtime.db")

    async def emit(event):
        events.append(event)

    runtime = ResponsesRuntime(store=store, client=client, event_sink=emit)
    result = await runtime.start(
        "exact target", ModelConfig(model="exact-model"), RuntimeLimits(max_total_tokens=None)
    )
    checkpoint = await runtime.checkpoint(result.session.id)
    assert checkpoint.native_state["provider_compaction_count"] == 2
    assert [
        event.payload["count"] for event in events if event.kind == "provider_compaction_items"
    ] == [2]
    assert len([event for event in events if event.kind == "compaction"]) == 0
    assert ResponsesRuntime.completed_result(checkpoint).output_text == "done"
    await client.close()
    store.close()


@pytest.mark.asyncio
async def test_terminal_boundary_hook_preserves_exact_final_output(tmp_path):
    requests = []
    client = sdk_client([response([text_item("parent finished")], "r1")], requests)
    store = SQLiteRuntimeStore(tmp_path / "runtime.db")

    async def boundary(checkpoint):
        assert checkpoint.session.status == "running"
        assert checkpoint.native_state["settled_boundary"] is True
        return {"reason": "joined_children_pending"}

    runtime = ResponsesRuntime(store=store, client=client, boundary_hook=boundary)
    result = await runtime.start("target", ModelConfig(model="exact-model"), RuntimeLimits())
    assert result.session.status == "handed_off"
    assert result.output_text == "parent finished"
    assert result.artifacts[0].content == "parent finished"
    assert result.continuation["reason"] == "joined_children_pending"
    assert (await runtime.checkpoint(result.session.id)).native_state["responses"][-1]["id"] == "r1"
    await client.close()
    store.close()


@pytest.mark.asyncio
async def test_terminal_hook_failure_recovers_saved_text_without_second_model_call(tmp_path):
    requests = []
    client = sdk_client([response([text_item("final proof text")], "r1")], requests)
    store = SQLiteRuntimeStore(tmp_path / "runtime.db")

    async def broken(_checkpoint):
        raise RuntimeError("controller temporarily unavailable")

    runtime = ResponsesRuntime(store=store, client=client, boundary_hook=broken)
    with pytest.raises(ExecutionError):
        await runtime.start("target", ModelConfig(model="exact-model"), RuntimeLimits())
    saved = store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0]
    checkpoint = RuntimeCheckpoint.model_validate_json(saved)
    assert checkpoint.session.status == "failed"
    assert checkpoint.native_state["terminal_response_pending"] is True
    with pytest.raises(ExecutionError) as error:
        await runtime.continue_session(checkpoint.session.id, "do more")
    assert error.value.code == "TERMINAL_SETTLEMENT_REQUIRED"

    async def joined(_checkpoint):
        return {"reason": "joined_children"}

    recovery = ResponsesRuntime(store=store, client=client, boundary_hook=joined)
    result = await recovery.recover_terminal(checkpoint)
    assert result.session.status == "handed_off"
    assert result.output_text == "final proof text"
    assert result.artifacts[0].content == "final proof text"
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 1
    with pytest.raises(ExecutionError):
        await recovery.recover_terminal(checkpoint)
    await client.close()
    store.close()


@pytest.mark.asyncio
async def test_running_terminal_checkpoint_settles_after_crash(tmp_path):
    requests = []
    client = sdk_client([response([text_item("saved result")], "r1")], requests)
    store = SQLiteRuntimeStore(tmp_path / "runtime.db")

    async def broken(_checkpoint):
        raise RuntimeError("process crashed")

    first = ResponsesRuntime(store=store, client=client, boundary_hook=broken)
    with pytest.raises(ExecutionError):
        await first.start("target", ModelConfig(model="exact-model"), RuntimeLimits())
    stored = RuntimeCheckpoint.model_validate_json(
        store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0]
    )
    running = RuntimeCheckpoint.build(
        stored.session.model_copy(update={"status": "running"}), stored.native_state
    )
    await store.save(running)
    recovery = ResponsesRuntime(store=store, client=client)
    result = await recovery.recover_terminal(running)
    assert result.session.status == "completed"
    assert result.output_text == "saved result"
    assert (
        ResponsesRuntime.completed_result(await recovery.checkpoint(result.session.id)).output_text
        == "saved result"
    )
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 1
    await client.close()
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_output", ["tool", "text"])
async def test_foreign_provider_model_is_quarantined_before_output_or_tools(
    tmp_path, foreign_output
):
    requests, effects = [], []
    item = (
        {
            "id": "call-1",
            "type": "function_call",
            "call_id": "c1",
            "name": "effect",
            "arguments": "{}",
            "status": "completed",
        }
        if foreign_output == "tool"
        else text_item("foreign answer")
    )
    foreign = response([item], "r1")
    foreign["model"] = "unrelated-foreign-model"
    client = sdk_client([foreign], requests)
    store = SQLiteRuntimeStore(tmp_path / "runtime.db")
    dispatcher = ToolDispatcher()

    async def effect(_arguments, _operation_id):
        effects.append(1)
        return {"done": True}

    dispatcher.register(
        "effect",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        effect,
    )
    runtime = ResponsesRuntime(store=store, client=client, dispatcher=dispatcher)
    with pytest.raises(ExecutionError) as error:
        await runtime.start("target", ModelConfig(model="exact-model"), RuntimeLimits())
    assert error.value.code == "PROVIDER_MODEL_MISMATCH"
    assert effects == []
    saved = RuntimeCheckpoint.model_validate_json(
        store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0]
    )
    assert saved.session.status == "uncertain"
    assert saved.native_state["responses"][-1]["model"] == "unrelated-foreign-model"
    assert not any(item.get("type") == "function_call" for item in saved.native_state["input"])
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 1
    await client.close()
    store.close()


@pytest.mark.asyncio
async def test_poisoned_terminal_checkpoint_rejects_foreign_model(tmp_path):
    requests = []
    client = sdk_client([response([text_item("exact final")], "r1")], requests)
    store = SQLiteRuntimeStore(tmp_path / "runtime.db")

    async def broken(_checkpoint):
        raise RuntimeError("controller down")

    runtime = ResponsesRuntime(store=store, client=client, boundary_hook=broken)
    with pytest.raises(ExecutionError):
        await runtime.start("target", ModelConfig(model="exact-model"), RuntimeLimits())
    saved = RuntimeCheckpoint.model_validate_json(
        store.db.execute("SELECT data FROM runtime_sessions").fetchone()[0]
    )
    poisoned = saved.model_copy(deep=True)
    poisoned.native_state["responses"][-1]["model"] = "unrelated-foreign-model"
    poisoned = RuntimeCheckpoint.build(poisoned.session, poisoned.native_state)
    await store.save(poisoned)
    recovery = ResponsesRuntime(store=store, client=client)
    with pytest.raises(ExecutionError) as error:
        await recovery.recover_terminal(poisoned)
    assert error.value.code == "COMPLETED_RESULT_INVALID"
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 1
    await client.close()
    store.close()


@pytest.mark.asyncio
async def test_stagnation_signals_survive_native_handoff(tmp_path):
    def call(index):
        return {
            "id": f"fc-{index}",
            "type": "function_call",
            "call_id": f"c{index}",
            "name": "run_command",
            "arguments": '{"argv":["tail","log"]}',
            "status": "completed",
        }

    dispatcher = ToolDispatcher()

    async def read(_arguments, _operation_id):
        return {"exit_code": 0, "stdout": "unchanged", "stderr": ""}

    dispatcher.register(
        "run_command",
        {
            "type": "object",
            "properties": {"argv": {"type": "array", "items": {"type": "string"}}},
            "required": ["argv"],
            "additionalProperties": False,
        },
        read,
    )
    requests, events = [], []
    client = sdk_client([response([call(i)], f"r{i}") for i in range(8)], requests)
    store = SQLiteRuntimeStore(tmp_path / "first.db")

    async def emit(event):
        events.append(event)

    async def boundary(checkpoint):
        if checkpoint.native_state["stagnation"].get("recovery_requested"):
            return {"reason": "bounded_recovery"}
        return None

    first = ResponsesRuntime(
        store=store,
        client=client,
        dispatcher=dispatcher,
        event_sink=emit,
        boundary_hook=boundary,
    )
    result = await first.start(
        "work", ModelConfig(model="exact-model"), RuntimeLimits(max_turns=10)
    )
    assert result.session.status == "handed_off"
    assert [
        event.kind for event in events if "stagnation" in event.kind or "recovery" in event.kind
    ] == ["stagnation_warning", "recovery_requested"]
    durable = (await first.checkpoint(result.session.id)).native_state["stagnation"]
    assert max(durable["read_counts"].values()) == 8
    outputs = [
        json.loads(item["output"])
        for item in (await first.checkpoint(result.session.id)).native_state["input"]
        if item.get("type") == "function_call_output"
    ]
    assert outputs[3]["_research_runtime_signal"]["kind"] == "stagnation_warning"
    await client.close()
    store.close()

    requests2, events2 = [], []
    client2 = sdk_client([response([call(i)], f"next{i}") for i in range(8)], requests2)
    store2 = SQLiteRuntimeStore(tmp_path / "second.db")

    async def emit2(event):
        events2.append(event)

    async def boundary2(checkpoint):
        if checkpoint.native_state["stagnation"].get("exhausted"):
            return {"reason": "park_branch"}
        return None

    second = ResponsesRuntime(
        store=store2,
        client=client2,
        dispatcher=dispatcher,
        event_sink=emit2,
        boundary_hook=boundary2,
        stagnation_state=durable,
    )
    after = await second.start("fresh recovery", ModelConfig(model="exact-model"), RuntimeLimits())
    assert after.session.status == "handed_off"
    assert [event.kind for event in events2 if event.kind == "recovery_exhausted"] == [
        "recovery_exhausted"
    ]
    await client2.close()
    store2.close()


@pytest.mark.asyncio
async def test_native_handoff_preserves_input_and_cumulative_token_guard(tmp_path):
    requests = []
    client = sdk_client([response([text_item("first")], "r1")], requests)
    store = SQLiteRuntimeStore(tmp_path / "handoff.db")

    async def boundary(_checkpoint):
        return {"reason": "joined_children_pending"}

    limits = RuntimeLimits(max_total_tokens=20)
    first = ResponsesRuntime(store=store, client=client, boundary_hook=boundary)
    source = await first.start("target", ModelConfig(model="exact-model"), limits)
    source_checkpoint = await first.checkpoint(source.session.id)
    assert source.session.status == "handed_off"
    await client.close()

    next_requests = []
    next_client = sdk_client([], next_requests)
    next_runtime = ResponsesRuntime(store=store, client=next_client)
    with pytest.raises(ExecutionError) as error:
        await next_runtime.start_from_handoff(
            source_checkpoint, "child findings", ModelConfig(model="exact-model"), limits
        )
    assert error.value.code == "BUDGET_EXHAUSTED"
    assert not [path for path, _ in next_requests if path.endswith("/responses")]
    successor_rows = store.db.execute("SELECT data FROM runtime_sessions").fetchall()
    assert len(successor_rows) == 2
    assert any("child findings" in row[0] for row in successor_rows)
    await next_client.close()
    store.close()


@pytest.mark.asyncio
async def test_native_handoff_rejects_incompatible_model(tmp_path):
    requests = []
    client = sdk_client([response([text_item("first")], "r1")], requests)
    store = SQLiteRuntimeStore(tmp_path / "handoff.db")

    async def boundary(_checkpoint):
        return {"reason": "continue"}

    runtime = ResponsesRuntime(store=store, client=client, boundary_hook=boundary)
    source = await runtime.start("target", ModelConfig(model="exact-model"), RuntimeLimits())
    with pytest.raises(ExecutionError) as error:
        await runtime.start_from_handoff(
            await runtime.checkpoint(source.session.id),
            "prompt",
            ModelConfig(model="other-model"),
            RuntimeLimits(),
        )
    assert error.value.code == "HANDOFF_MISMATCH"
    await client.close()
    store.close()


@pytest.mark.asyncio
async def test_native_handoff_carries_exact_provider_items_into_successor(tmp_path):
    requests = []
    client = sdk_client(
        [
            response([text_item("first")], "r1"),
            response([text_item("second")], "r2"),
        ],
        requests,
    )
    store = SQLiteRuntimeStore(tmp_path / "handoff.db")
    calls = 0

    async def boundary(_checkpoint):
        nonlocal calls
        calls += 1
        return {"reason": "continue"} if calls == 1 else None

    limits = RuntimeLimits(max_total_tokens=None)
    runtime = ResponsesRuntime(store=store, client=client, boundary_hook=boundary)
    source = await runtime.start("target", ModelConfig(model="exact-model"), limits)
    successor = await runtime.start_from_handoff(
        await runtime.checkpoint(source.session.id),
        "child findings",
        ModelConfig(model="exact-model"),
        limits,
    )
    assert successor.session.id != source.session.id
    assert successor.session.status == "completed"
    assert successor.output_text == "second"
    creates = [payload for path, payload in requests if path.endswith("/responses")]
    assert creates[1]["input"] == [
        {"role": "user", "content": "target"},
        text_item("first"),
        {"role": "user", "content": "child findings"},
    ]
    assert (
        ResponsesRuntime.completed_result(
            await runtime.checkpoint(successor.session.id)
        ).output_text
        == "second"
    )
    await client.close()
    store.close()
