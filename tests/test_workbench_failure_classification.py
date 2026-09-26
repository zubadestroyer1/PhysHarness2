"""Side-effect-free workbench failures stay model-visible and never wedge or destroy a VM.

The Docker transport is replaced by the real guest helper running against a temporary
root, so refusals, links and isolation flags exercise the shipped helper bytes.
"""

import asyncio
import hashlib
import json
import os
import subprocess
import sys

import pytest
from test_workspace_promotion import _capture
from test_workspace_service import setup

import physharness.execution.local_docker as local_docker
from physharness.domain import Principal
from physharness.errors import HarnessError
from physharness.execution.e2b import E2BSandboxProvider
from physharness.execution.local_docker import _GUEST, LocalDockerWorkspaceProvider
from physharness.execution.types import CommandRequest, ExecutionError
from physharness.execution.workspace_archive import checked_path
from physharness.orchestration.research_worker import research_tools
from physharness.orchestration.workspace_tools import WorkspacePolicy, WorkspaceTools
from physharness.orchestration.workspaces import WorkspaceBroker

IMAGE = "sha256:" + "a" * 64
HOST = "unix:///tmp/physharness-failure-classification/docker.sock"


def local_guest(root):
    # macOS has no /proc; omit only the VM process enumeration, as other guest tests do.
    return _GUEST.replace("root='/work'", f"root={str(root)!r}").replace(
        "for item in os.listdir('/proc'):", "for item in ():"
    )


class GuestDocker:
    """Dedicated-socket transport double that executes the real guest helper."""

    def __init__(self, root, *, resource=None, commands=None, quiescent=True, oversized=()):
        self.root = root
        self.guest = local_guest(root)
        self.resource = resource
        self.commands = commands or {}
        self.quiescent = quiescent
        self.oversized = set(oversized)
        self.calls = []

    async def __call__(self, argv, *, input_data=b"", timeout=30, max_output=65536):
        args = argv[3:]
        self.calls.append(args)
        if args[0] == "image":
            return 0, (IMAGE + "\n").encode(), b""
        if args[0] == "run":
            return 0, b"container-abcdef\n", b""
        if args[0] in {"ps", "rm"}:
            return 0, b"", b""
        assert args[0] == "exec"
        if _GUEST not in args:
            # exec --workdir <cwd> <container> argv...; bounded like the real transport.
            output = self.commands.get(args[4], b"ok\n")
            return 0, output[: max_output + 1], b""
        index = args.index(_GUEST)
        action = args[index + 1]
        if action == "resource" and self.resource is not None:
            return 0, json.dumps(self.resource).encode(), b""
        if action == "quiescent" and not self.quiescent:
            return 1, b"", b"AssertionError: Checkpoint requires a quiescent workspace"
        if action in self.oversized:
            return 0, b"x" * (max_output + 1), b""
        flags = args[args.index("/usr/bin/python3") + 1 : index - 1]
        done = subprocess.run(
            [sys.executable, *flags, "-c", self.guest, *args[index + 1 :]],
            input=input_data,
            capture_output=True,
            cwd=self.root,  # docker exec starts in the image WORKDIR, /work.
        )
        return done.returncode, done.stdout[: max_output + 1], done.stderr[: max_output + 1]

    def removed(self):
        return any(call[0] == "rm" for call in self.calls)


def local_broker(lab, tmp_path, **transport):
    _, service, experiment, _, _, args = setup(lab)
    root = tmp_path / "work"
    root.mkdir()
    runner = GuestDocker(root, **transport)
    made = []

    def factory(*, journal, timeout_seconds):
        provider = LocalDockerWorkspaceProvider(
            docker_host=HOST,
            image_digest=IMAGE,
            timeout_seconds=timeout_seconds,
            runner=runner,
            journal=journal,
        )
        made.append(provider)
        return provider

    args = {
        **args,
        "provider_factory": factory,
        "provider_spec": {"provider": "local_docker", "template_id": IMAGE, "timeout_seconds": 60},
    }
    return WorkspaceBroker(service, **args), service, experiment, runner, root, made


def assert_available(broker, service, experiment, workspace, runner):
    assert broker.inspect(workspace["id"])["status"] == "ready"
    assert broker.inspect(workspace["id"])["active_operation_id"] is None
    assert service.ledger(experiment["id"], broker.actor)["uncertain_operations"] == 0
    assert not runner.removed()


# Defect: command output above the bound destroyed the local workbench.


async def test_docker_transport_truncates_and_drains_oversized_output(monkeypatch, tmp_path):
    real = asyncio.create_subprocess_exec
    script = tmp_path / "chatty.py"
    script.write_text("import sys\nsys.stdout.write('w' * 300000)\nsys.stderr.write('e' * 9)\n")

    async def spawn(executable, *args, **kwargs):
        kwargs.pop("env", None)
        return await real(sys.executable, str(script), **kwargs)

    monkeypatch.setattr(local_docker.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(local_docker.asyncio, "create_subprocess_exec", spawn)
    async with asyncio.timeout(20):  # An undrained killed pipe used to hang wait().
        code, out, err = await local_docker._docker(["docker", "exec"], max_output=65536)
    # The command ran to completion; the caller learns of truncation from one extra byte.
    assert code == 0
    assert out == b"w" * 65537
    assert err == b"e" * 9


async def test_oversized_command_output_is_truncated_without_destroying_workspace(
    lab, monkeypatch, tmp_path
):
    real = asyncio.create_subprocess_exec
    emulator = tmp_path / "docker_emulator.py"
    emulator.write_text(
        "import sys\n"
        "args = sys.argv[3:]\n"
        "if args[0] == 'image': print('" + IMAGE + "')\n"
        "elif args[0] == 'run': print('container-abcdef')\n"
        "elif args[0] == 'exec' and 'resource' in args:\n"
        '    print(\'{"current_bytes":1,"peak_bytes":1,"events":{"oom":0}}\')\n'
        "elif args[0] == 'exec' and 'big' in args: sys.stdout.write('w' * 100000)\n"
        "elif args[0] == 'exec': print('ok')\n"
    )
    subcommands = []

    async def spawn(executable, *args, **kwargs):
        subcommands.append(args[2])
        kwargs.pop("env", None)
        return await real(sys.executable, str(emulator), *args, **kwargs)

    monkeypatch.setattr(local_docker.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(local_docker.asyncio, "create_subprocess_exec", spawn)
    _, service, experiment, _, _, args = setup(lab)

    def factory(*, journal, timeout_seconds):
        return LocalDockerWorkspaceProvider(
            docker_host=HOST, image_digest=IMAGE, timeout_seconds=timeout_seconds, journal=journal
        )

    broker = WorkspaceBroker(
        service,
        **{
            **args,
            "provider_factory": factory,
            "provider_spec": {
                "provider": "local_docker",
                "template_id": IMAGE,
                "timeout_seconds": 60,
            },
        },
    )
    workspace = await broker.provision(cost_bound_usd="0", operation_id="p")
    result = await broker.run(
        workspace["id"],
        expected_execution_id=workspace["execution_id"],
        request=CommandRequest(
            operation_id="big", argv=["big"], timeout_seconds=5, max_output_bytes=65536
        ),
    )
    assert result["exit_code"] == 0
    assert result["stdout"] == "w" * 65536
    assert result["stdout_truncated"] is True and result["stderr_truncated"] is False
    assert broker.inspect(workspace["id"])["status"] == "ready"
    assert "rm" not in subcommands
    after = await broker.run(
        workspace["id"],
        expected_execution_id=workspace["execution_id"],
        request=CommandRequest(operation_id="next", argv=["true"], timeout_seconds=5),
    )
    assert after["stdout"] == "ok\n" and after["stdout_truncated"] is False


async def test_oversized_read_only_guest_response_is_a_definite_refusal(lab, tmp_path):
    broker, service, experiment, runner, root, made = local_broker(
        lab, tmp_path, oversized={"slice"}
    )
    workspace = await broker.provision(cost_bound_usd="0", operation_id="p")
    (root / "notes.txt").write_bytes(b"notes")
    with pytest.raises(HarnessError) as error:
        await broker.read_workspace_range(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            path="notes.txt",
            offset=0,
            length=10,
            operation_id="oversized-read",
        )
    assert error.value.code == "WORKSPACE_TRANSFER_REJECTED"
    assert_available(broker, service, experiment, workspace, runner)
    assert made[0]._quarantined is False


# Defect: provably side-effect-free failures became reconciliation_required.


async def test_missing_file_read_is_model_visible_and_workspace_stays_usable(lab, tmp_path):
    broker, service, experiment, runner, root, _ = local_broker(lab, tmp_path)
    workspace = await broker.provision(cost_bound_usd="0", operation_id="p")
    for _ in range(2):  # The refusal is durable and replays without another dispatch.
        with pytest.raises(HarnessError) as error:
            await broker.read_workspace_range(
                workspace["id"],
                expected_execution_id=workspace["execution_id"],
                path="scratch/Missing.lean",
                offset=0,
                length=100,
                operation_id="read-missing",
            )
        assert error.value.code == "WORKSPACE_TRANSFER_REJECTED"
    assert sum("slice" in call for call in runner.calls) == 1
    assert_available(broker, service, experiment, workspace, runner)
    await broker.upload_file(
        workspace["id"],
        expected_execution_id=workspace["execution_id"],
        path="scratch/Missing.lean",
        data=b"theorem x : True := trivial\n",
        operation_id="later",
    )
    assert (root / "scratch" / "Missing.lean").read_bytes() == b"theorem x : True := trivial\n"


async def test_upload_below_regular_file_is_refused_without_leftovers(lab, tmp_path):
    broker, service, experiment, runner, root, _ = local_broker(lab, tmp_path)
    workspace = await broker.provision(cost_bound_usd="0", operation_id="p")
    await broker.upload_file(
        workspace["id"],
        expected_execution_id=workspace["execution_id"],
        path="notes",
        data=b"x",
        operation_id="u1",
    )
    with pytest.raises(HarnessError) as error:
        await broker.upload_file(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            path="notes/Proof.lean",
            data=b"y",
            operation_id="u2",
        )
    assert error.value.code == "WORKSPACE_TRANSFER_REJECTED"
    assert sorted(os.listdir(root)) == ["notes"]
    assert (root / "notes").read_bytes() == b"x"
    assert_available(broker, service, experiment, workspace, runner)


def test_guest_write_refusal_undoes_directories_it_created(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    (root / "kept").mkdir()
    done = subprocess.run(
        [sys.executable, "-I", "-c", local_guest(root), "write", "kept/fresh/deeper/" + "x" * 300],
        input=b"data",
        capture_output=True,
        cwd=root,
    )
    assert done.returncode == 3
    assert done.stderr.startswith(b"physharness-refused:")
    assert os.listdir(root / "kept") == []


def test_guest_write_still_succeeds_under_isolated_python(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    done = subprocess.run(
        [sys.executable, "-I", "-c", local_guest(root), "write", "Proof.lean"],
        input=b"data",
        capture_output=True,
        cwd=root,
    )
    assert done.returncode == 0 and done.stdout == b"ok\n"
    assert (root / "Proof.lean").read_bytes() == b"data"


async def test_long_path_component_is_a_pure_predispatch_rejection(lab, tmp_path):
    broker, service, experiment, runner, root, _ = local_broker(lab, tmp_path)
    workspace = await broker.provision(cost_bound_usd="0", operation_id="p")
    with pytest.raises(HarnessError) as error:
        await broker.upload_file(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            path="scratch/" + "x" * 300 + ".lean",
            data=b"x",
            operation_id="long",
        )
    assert error.value.code == "UNSAFE_PATH"
    assert not any("write" in call for call in runner.calls)
    assert_available(broker, service, experiment, workspace, runner)
    for validate in (checked_path, E2BSandboxProvider.validate_workspace_path):
        with pytest.raises(ExecutionError) as rejected:
            validate("x" * 256)
        assert rejected.value.code == "UNSAFE_PATH"
        assert validate("x" * 255) == "x" * 255


async def test_e2b_read_range_helper_refusal_is_definite(lab):
    broker, service, experiment, _, made, _ = setup(lab)
    workspace = await broker.provision(cost_bound_usd="0.2", operation_id="p")

    async def download_file(path, **kwargs):
        # What E2BSandboxProvider raises when its read-only helper exits nonzero.
        raise ExecutionError("WORKSPACE_TRANSFER_REJECTED", "helper completed unsuccessfully")

    made[0].download_file = download_file
    with pytest.raises(HarnessError) as error:
        await broker.read_workspace_range(
            workspace["id"],
            expected_execution_id="vm-123",
            path="missing.lean",
            offset=0,
            length=10,
            operation_id="r",
        )
    assert error.value.code == "WORKSPACE_TRANSFER_REJECTED"
    assert broker.inspect(workspace["id"])["status"] == "ready"
    assert service.ledger(experiment["id"], broker.actor)["uncertain_operations"] == 0


@pytest.mark.parametrize("kind", ["symlink", "directory_symlink", "hardlink", "fifo", "git"])
async def test_links_special_files_and_secret_names_are_excluded_on_record(lab, tmp_path, kind):
    broker, service, experiment, runner, root, _ = local_broker(lab, tmp_path)
    workspace = await broker.provision(cost_bound_usd="0", operation_id="p")
    await broker.upload_file(
        workspace["id"],
        expected_execution_id=workspace["execution_id"],
        path="Proof.lean",
        data=b"theorem x : True := trivial\n",
        operation_id="u",
    )
    # What an agent's run_command could leave behind in /work.
    expected = {
        "symlink": ["Alias.lean"],
        "directory_symlink": ["physlib"],
        "hardlink": ["Copy.lean", "Proof.lean"],
        "fifo": ["pipe"],
        "git": [".git"],
    }[kind]
    if kind == "symlink":
        os.symlink("Proof.lean", root / "Alias.lean")
    elif kind == "directory_symlink":
        os.symlink(tmp_path, root / "physlib")
    elif kind == "hardlink":
        os.link(root / "Proof.lean", root / "Copy.lean")
    elif kind == "fifo":
        os.mkfifo(root / "pipe")
    else:
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text("[core]\n")
    exported = await broker.export_workspace(
        workspace["id"], expected_execution_id=workspace["execution_id"], operation_id="x"
    )
    archive = broker.load_handoff_archive(
        exported["artifact"]["id"], exported["archive_sha256"], workspace["execution_id"]
    )
    files = [entry["path"] for entry in archive.manifest["files"]]
    assert archive.manifest["excluded_paths"] == expected
    assert files == ([] if kind == "hardlink" else ["Proof.lean"])
    assert_available(broker, service, experiment, workspace, runner)


def workspace_tools(broker, service, experiment):
    problem = service.get_record("problem", experiment["problem_id"], broker.actor)
    return WorkspaceTools(
        broker,
        WorkspacePolicy(
            template_id=IMAGE,
            environment_digest=problem["environment_digest"],
            qualification_report_sha256="a" * 64,
            timeout_seconds=60,
            cost_bound_usd="0",
            cost_source="local_no_external_invoice",
        ),
    )


async def test_close_checkpoints_around_agent_symlink_then_tears_down(lab, tmp_path):
    broker, service, experiment, runner, root, _ = local_broker(lab, tmp_path)
    tools = workspace_tools(broker, service, experiment)
    await tools.write({"path": "Proof.lean", "content": "theorem x : True := trivial\n"}, "w1")
    os.symlink("Proof.lean", root / "Alias.lean")  # e.g. `ln -s Proof.lean Alias.lean`
    await tools.close()
    closed = broker.inspect(tools.workspace["id"])
    assert closed["status"] == "destroyed" and runner.removed()
    assert service.ledger(experiment["id"], broker.actor)["active_workers"] == 0
    archive = broker.load_handoff_archive(
        closed["checkpoint_artifact_id"],
        service.get_record("artifact", closed["checkpoint_artifact_id"], broker.actor)["sha256"],
        closed["execution_id"],
    )
    assert [entry["path"] for entry in archive.manifest["files"]] == ["Proof.lean"]
    assert archive.manifest["excluded_paths"] == ["Alias.lean"]


async def test_close_tears_down_after_definitely_refused_final_checkpoint(lab, tmp_path):
    broker, service, experiment, runner, root, _ = local_broker(lab, tmp_path)
    tools = workspace_tools(broker, service, experiment)
    await tools.write({"path": "Proof.lean", "content": "theorem x : True := trivial\n"}, "w1")
    (root / "back\\slash.lean").write_bytes(b"not a portable workspace name")
    await tools.close()
    closed = broker.inspect(tools.workspace["id"])
    assert closed["status"] == "destroyed" and runner.removed()
    assert service.ledger(experiment["id"], broker.actor)["active_workers"] == 0
    exports = [
        row
        for row in service.list_records("workspace_operation", broker.actor, experiment["id"])
        if row["command"] == "export"
    ]
    # The refused final checkpoint is the durable note that no archive was taken.
    assert [row["status"] for row in exports] == ["rejected"]
    assert exports[0]["result"]["code"] == "WORKSPACE_TRANSFER_REJECTED"


# Defect: an unsafe promotion path escaped the tool envelope as ExecutionError.


@pytest.mark.parametrize(
    "tool", ["store_workspace_artifact", "submit_workspace_candidate", "read_workspace_file"]
)
async def test_unsafe_workspace_paths_stay_inside_the_tool_envelope(lab, tool):
    broker, service, experiment, calls, made, _ = setup(lab)
    workspace = await broker.provision(cost_bound_usd="0.2", operation_id="p")
    source = b"theorem example : True := by trivial\n"
    made[0].files["proof.lean"] = source
    made[0].capture_file = lambda path, **kw: _capture(made[0], calls, path, **kw)
    task = service.get_record("task", broker.task_id, broker.actor)
    agent = Principal(
        id="proof-agent",
        project_id=broker.actor.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=task["branch_id"],
    )
    tools = WorkspaceTools.__new__(WorkspaceTools)
    problem = service.get_record("problem", experiment["problem_id"], broker.actor)
    tools.broker, tools.workspace = broker, workspace
    tools.policy = WorkspacePolicy(
        template_id="qualified-template",
        environment_digest=problem["environment_digest"],
        qualification_report_sha256="a" * 64,
        timeout_seconds=60,
        cost_bound_usd="0.2",
        cost_source="test",
    )
    dispatcher = research_tools(service, agent, task["branch_id"], workspace_tools=tools)
    arguments = (
        {"path": "/work/proof.lean", "offset": 0, "length": 10}
        if tool == "read_workspace_file"
        else {
            "path": "/work/proof.lean",
            "sha256": hashlib.sha256(source).hexdigest(),
            "target_digest": experiment["target_digest"],
        }
    )
    envelope = await dispatcher.dispatch(tool, arguments, "call-1")
    assert envelope["error"]["code"] == "UNSAFE_PATH"
    assert "capture" not in calls
    assert broker.inspect(workspace["id"])["status"] == "ready"


# Defect: agent files could replace the guest helper's stdlib modules.


async def test_guest_helper_ignores_agent_modules_in_the_workspace(lab, tmp_path):
    broker, service, experiment, runner, root, made = local_broker(lab, tmp_path)
    workspace = await broker.provision(cost_bound_usd="0", operation_id="p")
    (root / "Proof.lean").write_bytes(b"real bytes")
    (root / "base64.py").write_text(
        "import sys\n"
        "if sys.argv[1:2] == ['capture']:\n"
        "    sys.stdout.buffer.write(b'Oforged by agent module'); sys.exit(0)\n"
    )
    provider = made[0]
    captured = await provider.capture_file(
        "Proof.lean", expected_execution_id=workspace["execution_id"], max_bytes=100
    )
    assert captured == b"real bytes"
    helper_calls = [call for call in runner.calls if _GUEST in call]
    assert helper_calls
    for call in helper_calls:
        python = call.index("/usr/bin/python3")
        assert call[python + 1 : python + 3] == ["-I", "-c"]


def test_resource_diagnostics_tolerate_malformed_reports():
    diagnose = LocalDockerWorkspaceProvider._diagnostics
    for before, after in [
        ({"events": {"oom": "x"}}, {"events": {"oom": "x"}}),
        ([1], "text"),
        ({"events": ["oom"]}, {"events": {"oom": None}}),
        ({"events": {"oom": 1}}, {"events": {"oom": 3}}),
    ]:
        observed = diagnose(before, after, "completed")
        assert observed["oom_delta"] in {None, 2}
    assert diagnose({"events": {"oom": 1}}, {"events": {"oom": 3}}, "x")["oom_delta"] == 2


async def test_malformed_resource_report_does_not_block_command_or_cleanup(lab, tmp_path):
    forged = {"current_bytes": 1, "peak_bytes": 1, "events": {"oom": "x"}}
    broker, service, experiment, runner, root, made = local_broker(lab, tmp_path, resource=forged)
    workspace = await broker.provision(cost_bound_usd="0", operation_id="p")
    result = await broker.run(
        workspace["id"],
        expected_execution_id=workspace["execution_id"],
        request=CommandRequest(operation_id="r", argv=["true"], timeout_seconds=5),
    )
    assert result["exit_code"] == 0 and result["diagnostics"]["oom_delta"] is None
    runner.quiescent = False  # A lingering process after the command is still destructive.
    with pytest.raises(HarnessError) as error:
        await broker.run(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            request=CommandRequest(operation_id="lingers", argv=["true"], timeout_seconds=5),
        )
    assert error.value.code == "WORKSPACE_COMMAND_FAILED"
    assert made[0]._quarantined is True and runner.removed()
    assert broker.inspect(workspace["id"])["status"] == "destroyed"


async def test_e2b_read_only_helper_refusals_create_no_directories(tmp_path):
    from test_execution_e2b_durable import provider as e2b_provider

    provider = e2b_provider(tmp_path)
    root = tmp_path / "workspace"
    root.mkdir()
    for read in (
        lambda: provider.download_file("a/b/Missing.lean", expected_execution_id="vm-source"),
        lambda: provider.capture_file(
            "c/d/Missing.lean", expected_execution_id="vm-source", max_bytes=100
        ),
    ):
        with pytest.raises(ExecutionError) as error:
            await read()
        assert error.value.code == "WORKSPACE_TRANSFER_REJECTED"
    assert os.listdir(root) == []
    await provider.upload_file("e/f/New.lean", b"x", expected_execution_id="vm-source")
    assert (root / "e" / "f" / "New.lean").read_bytes() == b"x"
