"""Society tool profile and worker wiring; the legacy 63-tool profile stays byte-identical."""

import hashlib
import json
import re
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI
from test_execution_responses import message
from test_research_loop_integration import PRICES, response
from test_sharing import approaches

from physharness.domain import TaskCreate, digest_json
from physharness.execution import ResponsesRuntime, RuntimeLimits
from physharness.orchestration.research_worker import ResearchTaskExecutor, research_tools

# Recorded from the pre-change code (research_worker.research_tools before Task 9).
LEGACY_DIGESTS = {
    ("none", False): (39, "21c2ee9fc8e970cd21fc40f47a19e47ba649591cfacadcc0c11e043de25746dc"),
    ("none", True): (45, "a2583c05fd08f3b0f069237269e12098a1f0dd738126737f0162ea97b35187e8"),
    ("ideas", False): (42, "31ec1a1fd866f34407f7402d2bc52b9e4d4f59162ca9c2d83aa29c8da3127b73"),
    ("ideas", True): (49, "b5996d03a7abf3e580abcb891c1e75f111eb9522996352573afb8f0ae3e3b77e"),
}
# Normalized worker-level provider payload and compaction anchor, recorded pre-change.
LEGACY_WORKER = {
    "ideas": {
        "payload": "ed509e1a19e1231d496eb908034883fa834b274074c62c5c9b75aac1e82a1577",
        "anchor": "6dd324753188f6a54a340b4162283ef8232bffcb07647d1f1d4e5b384870c089",
    },
    "verified": {
        "payload": "393bd7b9391913fa510b14535e8724ea827b7192d4c32a942fc9801e635a2dc0",
        "anchor": "0c68979c84bb49e5252182222282dab076653e731b1f9228974452a5eeb01385",
    },
}
LEGACY_RUNTIME_KWARGS = [
    "boundary_hook",
    "context_anchor",
    "dispatcher",
    "event_sink",
    "pre_generation_guard",
    "stagnation_state",
    "store",
    "update_ack",
    "update_source",
]
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")
HEX64 = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")


def normalized_digest(value):
    """Digest with record ids, timestamps and id-derived hashes masked."""
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    text = HEX64.sub("<sha256>", STAMP.sub("<time>", UUID.sub("<id>", text)))
    return hashlib.sha256(text.encode()).hexdigest()


class CatalogOnlyService:
    """Registration reads only; any handler call fails the test."""

    def __init__(self, sharing, task=None):
        self.sharing, self.task = sharing, task or {"reply_to_parent_task_id": None}

    def get_record(self, kind, identifier, actor):
        if kind == "experiment":
            return {"sharing": self.sharing}
        if kind == "task":
            return self.task
        raise AssertionError(f"unexpected read of {kind}")


@pytest.mark.parametrize("sharing", ["none", "ideas"])
@pytest.mark.parametrize("with_task", [False, True])
def test_legacy_catalog_unchanged(sharing, with_task):
    context = {"task_id": "t", "holder": "h", "fence": 1} if with_task else None
    dispatcher = research_tools(
        CatalogOnlyService(sharing), SimpleNamespace(experiment_id="e"), "b", task_context=context
    )
    count, digest = LEGACY_DIGESTS[(sharing, with_task)]
    assert len(dispatcher.definitions) == count
    assert digest_json(dispatcher.definitions) == digest


def mock_client(route):
    return AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )


async def run_worker(service, author, task_id, script=None, *, workspace_factory=None):
    """Run one task through the real worker with a scripted Responses provider.

    ``script(phase, payload)`` returns the provider's output items; the default ends at once.
    Each request also records the runtime's compaction anchor, read under the live lease.
    """
    seen = {"payloads": [], "anchors": [], "kwargs": None}

    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        payload = json.loads(request.content)
        phase = len(seen["payloads"])
        seen["payloads"].append(payload)
        seen["anchors"].append(await seen["kwargs"]["context_anchor"]())
        items = script(phase, payload) if script else [message("done")]
        return httpx.Response(200, json=response(items, response_id=f"resp_{phase}"))

    client = mock_client(route)

    def factory(**kwargs):
        seen["kwargs"] = kwargs
        return ResponsesRuntime(client=client, **kwargs)

    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=factory,
        limits=RuntimeLimits(max_turns=30),
        workspace_factory=workspace_factory,
    )
    try:
        result = await executor.execute(task_id, author.project_id)
    finally:
        await client.close()
    return result, seen


@pytest.mark.parametrize("sharing", ["ideas", "verified"])
async def test_worker_legacy_prompt_unchanged(lab, sharing):
    service, author, _experiment, branches, _agents = approaches(lab, sharing)
    task = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Legacy objective"), author, "task"
    )
    result, seen = await run_worker(service, author, task["id"])
    assert result["status"] == "completed"
    expected = LEGACY_WORKER[sharing]
    assert {
        "payload": normalized_digest(seen["payloads"][0]),
        "anchor": normalized_digest(seen["anchors"][0]),
    } == expected
    assert sorted(seen["kwargs"]) == LEGACY_RUNTIME_KWARGS
