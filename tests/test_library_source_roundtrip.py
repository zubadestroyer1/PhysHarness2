"""Search results remain usable as exact, bounded library lookup arguments."""

import hashlib
import os
import subprocess
import sys

import pytest

from physharness.errors import HarnessError
from physharness.orchestration.workspace_tools import WorkspacePolicy, WorkspaceTools


class LocalSourceBroker:
    """Run the generated VM scripts over a temporary stand-in for /opt/sources."""

    def __init__(self, source_root):
        self.source_root = source_root
        self.calls = 0

    async def run(self, workspace_id, *, expected_execution_id, request):
        assert workspace_id == "test-workspace"
        assert expected_execution_id == "test-execution"
        assert request.argv[:2] == ["python3", "-c"]
        self.calls += 1
        script = request.argv[2].replace("/opt/sources", str(self.source_root))
        args = [arg.replace("/opt/sources", str(self.source_root)) for arg in request.argv[3:]]
        completed = subprocess.run(
            [sys.executable, "-c", script, *args],
            capture_output=True,
            text=True,
            timeout=request.timeout_seconds,
            check=False,
        )
        return {
            "exit_code": completed.returncode,
            "stdout": completed.stdout.replace(str(self.source_root), "/opt/sources"),
            "stderr": completed.stderr,
        }


@pytest.fixture
def source_tools(tmp_path):
    broker = LocalSourceBroker(tmp_path)
    tools = WorkspaceTools.__new__(WorkspaceTools)
    tools.broker = broker
    tools.workspace = {"id": "test-workspace", "execution_id": "test-execution"}
    tools.policy = WorkspacePolicy(
        template_id="test-template",
        environment_digest="b" * 64,
        qualification_report_sha256="c" * 64,
        timeout_seconds=60,
        cost_bound_usd="0",
        cost_source="local_no_external_invoice",
    )
    return tools, broker, tmp_path


@pytest.mark.parametrize(
    ("path", "text", "query"),
    [
        ("physlib/QuantumInfo/States/Example.lean", "def rarePhysSymbol := 7\n", "rarePhysSymbol"),
        (
            "mathlib/Mathlib/Analysis/Example.lean",
            "theorem rareMathSymbol : True := trivial\n",
            "rareMathSymbol",
        ),
    ],
)
async def test_search_hit_path_roundtrips_through_lookup(source_tools, path, text, query):
    tools, _, source_root = source_tools
    file = source_root / path
    file.parent.mkdir(parents=True)
    file.write_text(text)

    search = await tools.search_library({"query": query}, "search")
    assert search["reason_code"] is None
    assert search["hits"] == [
        {"path": path, "guest_path": "/opt/sources/" + path, "line": 1, "snippet": text}
    ]
    hit = search["hits"][0]
    first = await tools.lookup_library_source({"path": hit["path"]}, "lookup-1")
    again = await tools.lookup_library_source({"path": first["path"]}, "lookup-2")
    for result in (first, again):
        assert result["reason_code"] is None
        assert result["path"] == path
        assert result["guest_path"] == "/opt/sources/" + path
        assert result["text"] == text
        assert result["size_bytes"] == len(text.encode())
        assert result["sha256"] == hashlib.sha256(text.encode()).hexdigest()


async def test_missing_file_preserves_canonical_lookup_path(source_tools):
    tools, _, _ = source_tools
    path = "mathlib/Mathlib/Missing.lean"
    result = await tools.lookup_library_source({"path": path}, "missing")
    assert result["reason_code"] == "source_unavailable"
    assert result["path"] == path
    assert result["guest_path"] == "/opt/sources/" + path


async def test_no_matches_returns_no_hits(source_tools):
    tools, _, source_root = source_tools
    (source_root / "mathlib").mkdir()
    result = await tools.search_library({"query": "absentSymbol"}, "no-match")
    assert result["hits"] == []
    assert result["reason_code"] == "no_lexical_match"


@pytest.mark.parametrize(
    "path",
    [
        "/opt/sources/mathlib/Mathlib/A.lean",
        "/etc/passwd.lean",
        "mathlib/../physlib/A.lean",
        "physlib//A.lean",
        "physlib/./A.lean",
        "Mathlib/A.lean",
        "physlib/A.txt",
        "physlib/A\x00.lean",
    ],
)
async def test_lookup_rejects_unsafe_or_noncanonical_paths_without_running(source_tools, path):
    tools, broker, _ = source_tools
    with pytest.raises(HarnessError) as error:
        await tools.lookup_library_source({"path": path}, "unsafe")
    assert error.value.code == "UNSAFE_PATH"
    assert broker.calls == 0


@pytest.mark.integration
async def test_real_pinned_image_search_lookup_roundtrip():
    """Opt-in contract check over both pinned source trees, without a model call."""
    host = os.environ.get("PHYSHARNESS_WORKBENCH_DOCKER_HOST")
    image = os.environ.get("PHYSHARNESS_WORKBENCH_IMAGE_DIGEST")
    if not host or not image:
        pytest.skip("Dedicated workbench endpoint and image digest are required")

    from physharness.execution.local_docker import LocalDockerWorkspaceProvider

    provider = LocalDockerWorkspaceProvider(
        docker_host=host, image_digest=image, timeout_seconds=180
    )

    class ProviderBroker:
        async def run(self, workspace_id, *, expected_execution_id, request):
            assert workspace_id == provider.execution_id
            assert expected_execution_id == provider.execution_id
            return (await provider.run(request)).model_dump()

    try:
        await provider.create()
        tools = WorkspaceTools.__new__(WorkspaceTools)
        tools.broker = ProviderBroker()
        tools.workspace = {"id": provider.execution_id, "execution_id": provider.execution_id}
        tools.policy = WorkspacePolicy(
            template_id=image,
            environment_digest="b" * 64,
            qualification_report_sha256="c" * 64,
            timeout_seconds=180,
            cost_bound_usd="0",
            cost_source="local_no_external_invoice",
        )
        for root, query in (
            ("physlib", "energy_conservation_of_equationOfMotion"),
            ("mathlib", "antitone_of_deriv_nonpos"),
        ):
            search = await tools.search_library({"query": query}, f"search-{root}")
            hits = [hit for hit in search["hits"] if hit["path"].startswith(root + "/")]
            assert hits, search
            hit = hits[0]
            first = await tools.lookup_library_source({"path": hit["path"]}, f"lookup-{root}")
            again = await tools.lookup_library_source({"path": first["path"]}, f"repeat-{root}")
            assert first["reason_code"] is None
            assert first["guest_path"] == hit["guest_path"]
            assert first["sha256"] == again["sha256"]
            assert first["text"] == again["text"]
            if not first["truncated"]:
                assert query in first["text"]
                assert first["sha256"] == hashlib.sha256(first["text"].encode()).hexdigest()
    finally:
        await provider.close()
