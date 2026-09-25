import asyncio
import hashlib
import os
import sys
from types import SimpleNamespace

import pytest

from physharness.execution.local_docker import LocalDockerWorkspaceProvider
from physharness.execution.types import CommandRequest, ExecutionError


class DockerTranscript:
    def __init__(self, image_digest="sha256:" + "a" * 64):
        self.commands = []
        self.files = {}
        self.image_digest = image_digest

    async def __call__(self, argv, *, input_data=b"", timeout=30, max_output=65536):
        self.commands.append((argv, input_data, timeout, max_output))
        if "run" in argv:
            return (0, b"container-id\n", b"")
        if "inspect" in argv:
            return (0, (self.image_digest + "\n").encode(), b"")
        if "ps" in argv:
            return (0, b"", b"")
        if "exec" in argv:
            return (0, b"ok", b"")
        return (0, b"", b"")


@pytest.mark.asyncio
async def test_provider_requires_explicit_dedicated_socket_and_pinned_image():
    with pytest.raises(ValueError):
        LocalDockerWorkspaceProvider(
            docker_host="unix:///var/run/docker.sock", image_digest="sha256:" + "a" * 64
        )
    with pytest.raises(ValueError):
        LocalDockerWorkspaceProvider(
            docker_host="unix:///tmp/physharness/docker.sock", image_digest="latest"
        )


@pytest.mark.asyncio
async def test_container_launch_isolation_and_command_budgets():
    transport = DockerTranscript()
    provider = LocalDockerWorkspaceProvider(
        docker_host="unix:///tmp/physharness-pilot/docker.sock",
        image_digest="sha256:" + "a" * 64,
        timeout_seconds=120,
        runner=transport,
    )
    await provider.create()
    run = next(argv for argv, *_ in transport.commands if "run" in argv)
    for required in [
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--pids-limit",
        "128",
        "--memory",
        "2g",
        "--cpus",
        "2",
        "--user",
        "65532:65532",
    ]:
        assert required in run
    assert not any(
        token.startswith("--volume") or token.startswith("--mount=type=bind") for token in run
    )
    assert provider.execution_id == "container-id"
    result = await provider.run(
        CommandRequest(
            operation_id="op",
            argv=["python3", "--version"],
            cwd=".",
            timeout_seconds=5,
            max_output_bytes=32,
        )
    )
    assert result.stdout == "ok" and result.execution_id == "container-id"
    executed = next(
        call for call in transport.commands if "exec" in call[0] and "--version" in call[0]
    )
    assert executed[2] == 5
    await provider.close()
    assert any("rm" in argv for argv, *_ in transport.commands)


def test_command_validation_allows_only_exact_pinned_source_cwds():
    provider = LocalDockerWorkspaceProvider(
        docker_host="unix:///tmp/physharness-pilot/docker.sock",
        image_digest="sha256:" + "a" * 64,
        timeout_seconds=300,
        runner=DockerTranscript(),
    )
    assert (
        provider.validate_command(
            CommandRequest(
                operation_id="mathlib",
                argv=["lake", "env", "lean", "Main.lean"],
                cwd="/opt/sources/mathlib",
                timeout_seconds=240,
            )
        )
        == "/opt/sources/mathlib"
    )
    for cwd in ("/opt/sources/mathlib/..", "/opt/sources/other", "bad\x00path"):
        with pytest.raises(ExecutionError):
            provider.validate_command(
                CommandRequest(
                    operation_id="bad",
                    argv=["true"],
                    cwd=cwd,
                )
            )
    for request in (
        CommandRequest(operation_id="env", argv=["true"], env={"X": "1"}),
        CommandRequest(operation_id="timeout", argv=["true"], timeout_seconds=301),
    ):
        with pytest.raises(ExecutionError):
            provider.validate_command(request)


@pytest.mark.asyncio
async def test_provider_fails_closed_on_wrong_image_and_oversized_output():
    transport = DockerTranscript("sha256:abc")
    provider = LocalDockerWorkspaceProvider(
        docker_host="unix:///tmp/physharness-pilot/docker.sock",
        image_digest="sha256:" + "a" * 64,
        runner=transport,
    )
    with pytest.raises(ExecutionError) as err:
        await provider.create()
    assert err.value.code == "PROVIDER_POLICY_MISMATCH"
    assert not any("run" in argv for argv, *_ in transport.commands)


def test_archive_hash_is_full_content_hash():
    from physharness.execution.workspace_archive import WorkspaceArchive

    payload = b"n" * 100_000
    archive = WorkspaceArchive.build({"scratch/notes.txt": payload})
    assert archive.sha256 == hashlib.sha256(archive.to_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_commands_on_one_provider_run_serially():
    class DelayedDocker(DockerTranscript):
        def __init__(self):
            super().__init__()
            self.active = 0
            self.peak = 0

        async def __call__(self, argv, **kwargs):
            if "--version" in argv:
                self.active += 1
                self.peak = max(self.peak, self.active)
                await asyncio.sleep(0.02)
                self.active -= 1
            return await super().__call__(argv, **kwargs)

    docker = DelayedDocker()
    provider = LocalDockerWorkspaceProvider(
        docker_host="unix:///tmp/physharness-pilot/docker.sock",
        image_digest="sha256:" + "a" * 64,
        runner=docker,
    )
    provider._container_id = "container-one"
    await asyncio.gather(
        *(
            provider.run(
                CommandRequest(
                    operation_id=str(i),
                    argv=["python3", "--version"],
                    cwd=".",
                    timeout_seconds=5,
                    max_output_bytes=32,
                )
            )
            for i in range(2)
        )
    )
    assert docker.peak == 1
    await provider.close()


@pytest.mark.asyncio
async def test_capacity_two_allows_two_commands_to_run_at_once():
    class DelayedDocker(DockerTranscript):
        def __init__(self):
            super().__init__()
            self.active = 0
            self.peak = 0

        async def __call__(self, argv, **kwargs):
            if "--version" in argv:
                self.active += 1
                self.peak = max(self.peak, self.active)
                await asyncio.sleep(0.02)
                self.active -= 1
            return await super().__call__(argv, **kwargs)

    docker = DelayedDocker()
    providers = [
        LocalDockerWorkspaceProvider(
            docker_host="unix:///tmp/physharness-pilot/docker.sock",
            image_digest="sha256:" + "a" * 64,
            max_active_workspaces=2,
            runner=docker,
        )
        for _ in range(2)
    ]
    for i, provider in enumerate(providers):
        provider._container_id = f"container-{i}"
    await asyncio.gather(
        *(
            provider.run(
                CommandRequest(
                    operation_id=str(i),
                    argv=["python3", "--version"],
                    cwd=".",
                    timeout_seconds=5,
                    max_output_bytes=32,
                )
            )
            for i, provider in enumerate(providers)
        )
    )
    assert docker.peak == 2
    await asyncio.gather(*(provider.close() for provider in providers))


@pytest.mark.asyncio
async def test_second_active_workbench_is_rejected_at_capacity():
    class OccupiedDocker(DockerTranscript):
        async def __call__(self, argv, **kwargs):
            if "ps" in argv:
                return (0, b"already-active\n", b"")
            return await super().__call__(argv, **kwargs)

    provider = LocalDockerWorkspaceProvider(
        docker_host="unix:///tmp/physharness-pilot/docker.sock",
        image_digest="sha256:" + "a" * 64,
        runner=OccupiedDocker(),
    )
    with pytest.raises(ExecutionError) as err:
        await provider.create()
    assert err.value.code == "WORKSPACE_CAPACITY"
    probe = await provider.probe_capacity()
    assert probe["capacity_policy_conflict"] is False
    assert probe["active_workspaces"] == 1


@pytest.mark.asyncio
async def test_docker_empty_capacity_label_is_legacy_default_one():
    class LegacyDocker(DockerTranscript):
        async def __call__(self, argv, **kwargs):
            if "ps" in argv:
                return (0, b"legacy-id\t\n", b"")
            return await super().__call__(argv, **kwargs)

    provider = LocalDockerWorkspaceProvider(
        docker_host="unix:///tmp/physharness-pilot/docker.sock",
        image_digest="sha256:" + "a" * 64,
        runner=LegacyDocker(),
    )
    assert (await provider.probe_capacity())["capacity_policy_conflict"] is False
    with pytest.raises(ExecutionError) as error:
        await provider.create()
    assert error.value.code == "WORKSPACE_CAPACITY"


@pytest.mark.asyncio
async def test_concurrent_create_admits_only_one_container():
    class CapacityDocker(DockerTranscript):
        def __init__(self):
            super().__init__()
            self.active = False
            self.runs = 0

        async def __call__(self, argv, **kwargs):
            if "ps" in argv:
                return (0, b"active\n" if self.active else b"", b"")
            if "run" in argv:
                await asyncio.sleep(0.02)
                self.active = True
                self.runs += 1
            if "rm" in argv:
                self.active = False
            return await super().__call__(argv, **kwargs)

    docker = CapacityDocker()
    providers = [
        LocalDockerWorkspaceProvider(
            docker_host="unix:///tmp/physharness-pilot/docker.sock",
            image_digest="sha256:" + "a" * 64,
            runner=docker,
        )
        for _ in range(2)
    ]
    outcomes = await asyncio.gather(*(p.create() for p in providers), return_exceptions=True)
    assert docker.runs == 1
    assert (
        sum(
            isinstance(value, ExecutionError) and value.code == "WORKSPACE_CAPACITY"
            for value in outcomes
        )
        == 1
    )
    assert sum(value is provider for value in outcomes for provider in providers) == 1
    assert all(not provider._quarantined for provider in providers)
    await asyncio.gather(*(p.close() for p in providers))


def test_capacity_must_be_a_bounded_positive_integer():
    for capacity in (False, 0, -1, 101, 1.5, "2", None):
        with pytest.raises(ValueError):
            LocalDockerWorkspaceProvider(
                docker_host="unix:///tmp/physharness-pilot/docker.sock",
                image_digest="sha256:" + "a" * 64,
                max_active_workspaces=capacity,
            )


@pytest.mark.asyncio
async def test_capacity_two_admits_two_parallel_workbenches_and_refuses_third():
    class CapacityDocker(DockerTranscript):
        def __init__(self):
            super().__init__()
            self.active = {}
            self.peak = 0

        async def __call__(self, argv, **kwargs):
            if "ps" in argv:
                return (
                    0,
                    "".join(
                        f"{name}\t{capacity}\n" for name, capacity in self.active.items()
                    ).encode(),
                    b"",
                )
            if "run" in argv:
                await asyncio.sleep(0.02)
                name = argv[argv.index("--name") + 1]
                capacity = next(
                    token.split("=", 1)[1]
                    for token in argv
                    if token.startswith("physharness.capacity=")
                )
                self.active[name] = capacity
                self.peak = max(self.peak, len(self.active))
                return (0, (name + "\n").encode(), b"")
            if "rm" in argv:
                self.active.pop(argv[-1], None)
            return await super().__call__(argv, **kwargs)

    docker = CapacityDocker()
    providers = [
        LocalDockerWorkspaceProvider(
            docker_host="unix:///tmp/physharness-pilot/docker.sock",
            image_digest="sha256:" + "a" * 64,
            max_active_workspaces=2,
            runner=docker,
        )
        for _ in range(3)
    ]
    outcomes = await asyncio.gather(
        *(provider.create() for provider in providers), return_exceptions=True
    )
    assert sum(value is provider for value in outcomes for provider in providers) == 2
    assert (
        sum(
            isinstance(value, ExecutionError) and value.code == "WORKSPACE_CAPACITY"
            for value in outcomes
        )
        == 1
    )
    assert docker.peak == 2
    assert len(docker.active) == 2
    probe = await providers[0].probe_capacity()
    assert probe["active_workspaces"] == 2
    assert probe["available_slots"] == 0
    assert probe["memory_per_workspace_bytes"] == 2 * 1024**3
    assert probe["cpus_per_workspace"] == 2
    await asyncio.gather(*(provider.close() for provider in providers))
    assert docker.active == {}


@pytest.mark.asyncio
async def test_conflicting_active_capacity_fails_closed_without_removing_another_owner():
    class OccupiedDocker(DockerTranscript):
        async def __call__(self, argv, **kwargs):
            if "ps" in argv:
                return (0, b"other-owner\t1\n", b"")
            return await super().__call__(argv, **kwargs)

    docker = OccupiedDocker()
    provider = LocalDockerWorkspaceProvider(
        docker_host="unix:///tmp/physharness-pilot/docker.sock",
        image_digest="sha256:" + "a" * 64,
        max_active_workspaces=2,
        runner=docker,
    )
    with pytest.raises(ExecutionError) as err:
        await provider.create()
    assert err.value.code == "PROVIDER_POLICY_MISMATCH"
    assert not any("run" in argv or "rm" in argv for argv, *_ in docker.commands)


@pytest.mark.asyncio
async def test_cancelled_create_removes_only_its_own_container_before_returning():
    started = asyncio.Event()

    class CancelledDocker(DockerTranscript):
        def __init__(self):
            super().__init__()
            self.active = {"other-owner": "2"}

        async def __call__(self, argv, **kwargs):
            if "ps" in argv:
                return (
                    0,
                    "".join(
                        f"{name}\t{capacity}\n" for name, capacity in self.active.items()
                    ).encode(),
                    b"",
                )
            if "run" in argv:
                name = argv[argv.index("--name") + 1]
                self.active[name] = "2"
                started.set()
                await asyncio.sleep(3600)
            if "rm" in argv:
                await asyncio.sleep(0.01)
                self.active.pop(argv[-1], None)
            return await super().__call__(argv, **kwargs)

    docker = CancelledDocker()
    provider = LocalDockerWorkspaceProvider(
        docker_host="unix:///tmp/physharness-pilot/docker.sock",
        image_digest="sha256:" + "a" * 64,
        max_active_workspaces=2,
        runner=docker,
    )
    task = asyncio.create_task(provider.create())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert docker.active == {"other-owner": "2"}


@pytest.mark.asyncio
async def test_same_provider_cannot_create_twice_concurrently():
    class SlowDocker(DockerTranscript):
        def __init__(self):
            super().__init__()
            self.runs = 0

        async def __call__(self, argv, **kwargs):
            if "run" in argv:
                self.runs += 1
                await asyncio.sleep(0.02)
            return await super().__call__(argv, **kwargs)

    docker = SlowDocker()
    provider = LocalDockerWorkspaceProvider(
        docker_host="unix:///tmp/physharness-pilot/docker.sock",
        image_digest="sha256:" + "a" * 64,
        max_active_workspaces=2,
        runner=docker,
    )
    results = await asyncio.gather(provider.create(), provider.create(), return_exceptions=True)
    assert sum(result is provider for result in results) == 1
    assert (
        sum(
            isinstance(result, ExecutionError) and result.code == "OPERATION_CONFLICT"
            for result in results
        )
        == 1
    )
    assert docker.runs == 1
    await provider.close()


@pytest.mark.asyncio
async def test_concurrent_different_capacity_policies_cannot_both_launch():
    class SharedDocker(DockerTranscript):
        def __init__(self):
            super().__init__()
            self.active = {}

        async def __call__(self, argv, **kwargs):
            if "ps" in argv:
                return (
                    0,
                    "".join(
                        f"{name}\t{capacity}\n" for name, capacity in self.active.items()
                    ).encode(),
                    b"",
                )
            if "run" in argv:
                await asyncio.sleep(0.02)
                name = argv[argv.index("--name") + 1]
                capacity = next(
                    token.split("=", 1)[1]
                    for token in argv
                    if token.startswith("physharness.capacity=")
                )
                self.active[name] = capacity
                return (0, (name + "\n").encode(), b"")
            if "rm" in argv:
                self.active.pop(argv[-1], None)
            return await super().__call__(argv, **kwargs)

    docker = SharedDocker()
    providers = [
        LocalDockerWorkspaceProvider(
            docker_host="unix:///tmp/physharness-pilot/docker.sock",
            image_digest="sha256:" + "a" * 64,
            max_active_workspaces=capacity,
            runner=docker,
        )
        for capacity in (1, 2)
    ]
    results = await asyncio.gather(
        *(provider.create() for provider in providers), return_exceptions=True
    )
    assert sum(result is provider for result in results for provider in providers) == 1
    assert (
        sum(
            isinstance(result, ExecutionError) and result.code == "PROVIDER_POLICY_MISMATCH"
            for result in results
        )
        == 1
    )
    assert len(docker.active) == 1
    await asyncio.gather(*(provider.close() for provider in providers))


@pytest.mark.asyncio
async def test_create_waits_for_cross_process_lock_with_different_tmpdir(tmp_path):
    docker = DockerTranscript()
    provider = LocalDockerWorkspaceProvider(
        docker_host="unix:///tmp/physharness-pilot/docker.sock",
        image_digest="sha256:" + "a" * 64,
        runner=docker,
    )
    holder = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import fcntl, os, sys; fd=os.open(sys.argv[1], os.O_CREAT|os.O_RDWR, 0o600); "
        "fcntl.flock(fd, fcntl.LOCK_EX); print('locked', flush=True); sys.stdin.read(1)",
        provider._lock_path,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        env={**os.environ, "TMPDIR": str(tmp_path)},
    )
    try:
        assert await asyncio.wait_for(holder.stdout.readline(), 2) == b"locked\n"
        create = asyncio.create_task(provider.create())
        await asyncio.sleep(0.1)
        assert not any("run" in argv for argv, *_ in docker.commands)
        holder.stdin.write(b"x")
        await holder.stdin.drain()
        assert await asyncio.wait_for(holder.wait(), 2) == 0
        assert await asyncio.wait_for(create, 2) is provider
    finally:
        if holder.returncode is None:
            holder.kill()
            await holder.wait()
        await provider.close()


@pytest.mark.asyncio
async def test_failed_create_with_same_journal_never_removes_existing_owner():
    class FailingDocker(DockerTranscript):
        def __init__(self):
            super().__init__()
            self.active = {}
            self.runs = 0

        async def __call__(self, argv, **kwargs):
            if "ps" in argv:
                rows = "".join(f"{name}\t2\n" for name in self.active)
                return (0, rows.encode(), b"")
            if "run" in argv:
                self.runs += 1
                name = argv[argv.index("--name") + 1]
                self.active[name] = True
                if self.runs == 2:
                    return (1, b"", b"launch failed")
                return (0, (name + "\n").encode(), b"")
            if "rm" in argv:
                self.active.pop(argv[-1], None)
            return await super().__call__(argv, **kwargs)

    docker = FailingDocker()
    journal = SimpleNamespace(workspace_id="same-workspace")
    providers = [
        LocalDockerWorkspaceProvider(
            docker_host="unix:///tmp/physharness-pilot/docker.sock",
            image_digest="sha256:" + "a" * 64,
            max_active_workspaces=2,
            journal=journal,
            runner=docker,
        )
        for _ in range(2)
    ]
    await providers[0].create()
    with pytest.raises(ExecutionError):
        await providers[1].create()
    assert docker.active == {providers[0]._planned_name: True}
    assert providers[0]._planned_name != providers[1]._planned_name
    assert providers[0]._workspace_label == providers[1]._workspace_label == "same-workspace"
    await providers[0].close()
