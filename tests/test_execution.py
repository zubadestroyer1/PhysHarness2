import asyncio
import sys

import pytest

from physharness.execution import (
    CommandJournal,
    CommandRequest,
    ExecutionError,
    LocalShellExecutor,
    ModelConfig,
    ResearchProgramRunner,
    RuntimeLimits,
)


async def test_local_requires_opt_in(tmp_path):
    executor = LocalShellExecutor(tmp_path)
    with pytest.raises(ExecutionError, match="development"):
        await executor.run(CommandRequest(argv=[sys.executable, "-c", "print(1)"]))


async def test_local_process_output_bounded_and_environment_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIVATE_TEST_SECRET", "do-not-leak")
    executor = LocalShellExecutor(tmp_path, allow_local_execution=True)
    result = await executor.run(
        CommandRequest(
            argv=[
                sys.executable,
                "-c",
                "import os; print(os.getenv('PRIVATE_TEST_SECRET')); print('x'*10000)",
            ],
            max_output_bytes=100,
        )
    )
    assert result.exit_code == 0
    assert result.stdout.startswith("None\n")
    assert len(result.stdout.encode()) <= 100
    assert result.stdout_truncated


async def test_local_rejects_path_escape_and_symlink(tmp_path):
    executor = LocalShellExecutor(tmp_path, allow_local_execution=True)
    (tmp_path / "escape").symlink_to(tmp_path.parent)
    for cwd in ["..", "escape", str(tmp_path.parent)]:
        with pytest.raises(ExecutionError) as error:
            await executor.run(CommandRequest(argv=["pwd"], cwd=cwd))
        assert error.value.code == "PATH_ESCAPE"


async def test_local_timeout_kills_process_group(tmp_path):
    executor = LocalShellExecutor(tmp_path, allow_local_execution=True)
    with pytest.raises(ExecutionError) as error:
        await executor.run(
            CommandRequest(
                argv=[sys.executable, "-c", "import time; time.sleep(10)"],
                timeout_seconds=0.05,
            )
        )
    assert error.value.code == "TIMEOUT"
    assert not executor.active_operations


async def test_local_cancellation_kills_descendant(tmp_path):
    executor = LocalShellExecutor(tmp_path, allow_local_execution=True)
    task = asyncio.create_task(
        executor.run(
            CommandRequest(
                operation_id="cancel-me",
                argv=[
                    sys.executable,
                    "-c",
                    "import subprocess,time; subprocess.Popen(['sleep','20']); "
                    "print('started',flush=True); time.sleep(20)",
                ],
            )
        )
    )
    for _ in range(100):
        if executor.active_operations:
            break
        await asyncio.sleep(0.01)
    assert await executor.cancel("cancel-me")
    with pytest.raises(ExecutionError) as error:
        await task
    assert error.value.code == "CANCELLED"
    assert not executor.active_operations


def test_command_journal_restart_replay_and_identity(tmp_path):
    path = tmp_path / "journal.db"
    with CommandJournal(path) as journal:
        assert journal.begin("program", "op", "search", {"q": "x"}) is None
        journal.complete("program", "op", {"papers": [1]})
    with CommandJournal(path) as journal:
        assert journal.begin("program", "op", "search", {"q": "x"}) == {"papers": [1]}
        with pytest.raises(ExecutionError) as error:
            journal.begin("program", "op", "search", {"q": "y"})
        assert error.value.code == "COMMAND_MISMATCH"
        assert journal.begin("program", "pending", "write", {}) is None
    with CommandJournal(path) as journal:
        with pytest.raises(ExecutionError) as error:
            journal.begin("program", "pending", "write", {})
        assert error.value.code == "OPERATION_UNCERTAIN"


async def test_javascript_without_vm_is_loudly_unavailable(tmp_path):
    with CommandJournal(tmp_path / "journal.db") as journal:
        runner = ResearchProgramRunner(journal)
        with pytest.raises(ExecutionError) as error:
            await runner.run("p", "return 42")
        assert error.value.code == "PROVIDER_UNAVAILABLE"


def test_model_and_limits_reject_silent_unknowns():
    with pytest.raises(ValueError):
        ModelConfig(model=" ")
    with pytest.raises(ValueError):
        RuntimeLimits(max_turns=0)


async def test_broker_replays_after_restart_without_repeating_side_effect(tmp_path):
    from physharness.execution import ToolDispatcher

    counter = tmp_path / "count"
    dispatcher = ToolDispatcher()

    async def increment(arguments, operation_id):
        current = int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(current + 1))
        return {"count": current + 1}

    dispatcher.register(
        "increment", {"type": "object", "properties": {}, "additionalProperties": False}, increment
    )
    with CommandJournal(tmp_path / "journal.db") as journal:
        runner = ResearchProgramRunner(journal, dispatcher=dispatcher)
        assert await runner.command("p", "one", "increment", {}) == {"count": 1}
    with CommandJournal(tmp_path / "journal.db") as journal:
        runner = ResearchProgramRunner(journal, dispatcher=dispatcher)
        assert await runner.command("p", "one", "increment", {}) == {"count": 1}
    assert counter.read_text() == "1"


def test_journal_rejects_nonobject_results(tmp_path):
    with CommandJournal(tmp_path / "journal.db") as journal:
        journal.begin("p", "op", "test", {})
        with pytest.raises(ExecutionError) as error:
            journal.complete("p", "op", None)
        assert error.value.code == "INVALID_TOOL_RESULT"


async def test_local_invalid_utf8_still_respects_output_byte_limit(tmp_path):
    executor = LocalShellExecutor(tmp_path, allow_local_execution=True)
    result = await executor.run(
        CommandRequest(
            argv=[sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes([255])*10)"],
            max_output_bytes=10,
        )
    )
    assert len(result.stdout.encode()) <= 10


async def test_local_same_operation_cannot_start_twice(tmp_path):
    executor = LocalShellExecutor(tmp_path, allow_local_execution=True)
    request = CommandRequest(
        operation_id="same", argv=[sys.executable, "-c", "import time; time.sleep(.1)"]
    )
    results = await asyncio.gather(
        executor.run(request), executor.run(request), return_exceptions=True
    )
    assert (
        sum(
            isinstance(result, ExecutionError) and result.code == "OPERATION_CONFLICT"
            for result in results
        )
        == 1
    )


async def test_process_group_cancel_stops_spawned_child(tmp_path):
    import os

    executor = LocalShellExecutor(tmp_path, allow_local_execution=True)
    script = (
        "import subprocess,time,pathlib; "
        "p=subprocess.Popen(['sleep','20']); pathlib.Path('child.pid').write_text(str(p.pid)); "
        "time.sleep(20)"
    )
    task = asyncio.create_task(
        executor.run(CommandRequest(operation_id="tree", argv=[sys.executable, "-c", script]))
    )
    for _ in range(200):
        if (tmp_path / "child.pid").exists():
            break
        await asyncio.sleep(0.01)
    child_pid = int((tmp_path / "child.pid").read_text())
    await executor.cancel("tree")
    with pytest.raises(ExecutionError):
        await task
    for _ in range(200):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("Spawned child was not reaped after cancellation")


async def test_javascript_broker_wrapper_real_node_replay(tmp_path):
    import json
    import shutil

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    executor = LocalShellExecutor(tmp_path, allow_local_execution=True)
    source = 'const x = await host("one", "add", {value: 2}); return x.value + 1;'
    result = await executor.run(
        CommandRequest(
            argv=[node, "--input-type=module", "-e", ResearchProgramRunner._wrapper(source, [])]
        )
    )
    assert json.loads(result.stdout) == {
        "kind": "command",
        "operation_id": "one",
        "name": "add",
        "arguments": {"value": 2},
    }
    records = [
        {"operation_id": "one", "command": "add", "arguments": {"value": 2}, "result": {"value": 4}}
    ]
    result = await executor.run(
        CommandRequest(
            argv=[
                node,
                "--input-type=module",
                "-e",
                ResearchProgramRunner._wrapper(source, records),
            ]
        )
    )
    assert json.loads(result.stdout) == {"kind": "result", "value": 5}
    records[0]["arguments"] = {"value": 99}
    result = await executor.run(
        CommandRequest(
            argv=[
                node,
                "--input-type=module",
                "-e",
                ResearchProgramRunner._wrapper(source, records),
            ]
        )
    )
    assert result.exit_code != 0
    assert "COMMAND_MISMATCH" in result.stdout


async def test_javascript_runner_refuses_local_process_as_security_boundary(tmp_path):
    with CommandJournal(tmp_path / "j.db") as journal:
        runner = ResearchProgramRunner(
            journal, executor=LocalShellExecutor(tmp_path, allow_local_execution=True)
        )
        with pytest.raises(ExecutionError) as error:
            await runner.run("p", "return 1")
        assert error.value.code == "UNSAFE_RUNTIME"


def test_javascript_wrapper_data_cannot_corrupt_source_injection():
    source = "return 1;"
    records = [{"operation_id": "op", "command": "x", "arguments": {}, "result": {"x": "SOURCE"}}]
    wrapper = ResearchProgramRunner._wrapper(source, records)
    assert '"x": "SOURCE"' in wrapper
    assert 'const source = "return 1;";' in wrapper
