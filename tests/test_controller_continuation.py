"""Canonical handoff with a fake provider; no paid generation or verifier."""

import json

import httpx
import pytest
from openai import AsyncOpenAI
from test_core import setup_experiment
from test_execution_context import compaction_item
from test_execution_responses import message
from test_execution_responses import response as base_response
from test_research_loop_integration import PRICES, tool_call

from physharness.continuation_lineage import LineageError, validate_terminal_lineage
from physharness.domain import ArtifactCreate, BranchCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import (
    ExecutionError,
    ModelConfig,
    ResponsesRuntime,
    RuntimeCheckpoint,
    RuntimeLimits,
)
from physharness.execution.types import RuntimeSession
from physharness.orchestration.research_worker import (
    CanonicalRuntimeStore,
    ResearchTaskExecutor,
    ResearchTeamRunner,
    TeamRunManifest,
)


def response(items, text="", response_id="resp_1"):
    native = base_response(items, text, response_id)
    native["model"] = "explicit-test-model"
    return native


@pytest.mark.asyncio
@pytest.mark.parametrize("post_issue_crash", [False, True])
async def test_new_session_consumes_exact_handoff_without_new_experiment_budget(
    lab, monkeypatch, post_issue_crash
):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, "root"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task"
    )
    generations = 0

    async def route(request):
        nonlocal generations
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        generations += 1
        if generations == 1:
            return httpx.Response(
                200,
                json=response(
                    [tool_call("request_handoff", {"reason": "continue research"}, "yield")]
                ),
            )
        assert not any(
            item.get("type") == "function_call_output"
            for item in json.loads(request.content)["input"]
        )
        return httpx.Response(
            200, json=response([message("Still unresolved.")], response_id="next")
        )

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )

    def factory(**kwargs):
        return ResponsesRuntime(client=client, **kwargs)

    executor = ResearchTaskExecutor(
        service, prices=PRICES, runtime_factory=factory, limits=RuntimeLimits(max_turns=30)
    )
    original_settle = service.settle_resources
    if post_issue_crash:

        def interrupted_finally(reservation_id, actual_cost, uncertain, actor, key, **kwargs):
            if key.startswith("slot-finished:"):
                raise RuntimeError("process died after ticket issue")
            return original_settle(reservation_id, actual_cost, uncertain, actor, key, **kwargs)

        monkeypatch.setattr(service, "settle_resources", interrupted_finally)
        with pytest.raises(RuntimeError, match="process died"):
            await executor.execute(task["id"], actor.project_id)
        monkeypatch.setattr(service, "settle_resources", original_settle)
    else:
        first = await executor.execute(task["id"], actor.project_id)
        assert first["status"] == "continuation"
    ready = service.get_record("task", task["id"], actor)["ready_continuation"]
    assert ready["ordinal"] == 1
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    controller = Principal(id="research-controller", project_id=actor.project_id, role="operator")
    crashed = service.acquire_task(task["id"], "crashed", 1, controller, "crashed-lease")
    service.consume_continuation(
        task["id"], "crashed", crashed["fence"], ready, controller, "crashed-consume"
    )
    with service.db.transaction() as session:
        from physharness.storage import LeaseRow

        session.get(LeaseRow, task["id"]).expires_at = 0
    assert service.get_record("task", task["id"], actor)["ready_continuation"] is None
    second = await executor.execute(task["id"], actor.project_id)
    assert second["status"] == "completed"
    assert generations == 2
    sessions = [
        s
        for s in service.list_records("session", actor, experiment["id"])
        if s["task_id"] == task["id"]
    ]
    assert len(sessions) == 2
    assert sorted(s["status"] for s in sessions) == ["completed", "handed_off"]
    assert service.get_record("task", task["id"], actor)["continuation_count"] == 1
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    with pytest.raises(HarnessError) as replay:
        service.consume_continuation(
            task["id"], "stale-holder", 1, ready, controller, "duplicate-consume"
        )
    assert replay.value.code == "STALE_LEASE"
    await client.close()


@pytest.mark.asyncio
async def test_three_handoffs_record_exact_per_ordinal_successors(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start-three")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, "root-three"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task-three"
    )
    generations = 0

    async def route(request):
        nonlocal generations
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        generations += 1
        if generations <= 3 or generations == 5:
            return httpx.Response(
                200,
                json=response(
                    [
                        compaction_item(f"handoff-{generations}"),
                        tool_call(
                            "request_handoff",
                            {"reason": "continue research"},
                            f"yield-{generations}",
                        ),
                    ],
                    response_id=f"handoff-{generations}",
                ),
            )
        return httpx.Response(
            200, json=response([message("Completed.")], response_id="completed-four")
        )

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=lambda **kwargs: ResponsesRuntime(client=client, **kwargs),
        limits=RuntimeLimits(max_turns=30),
    )
    for ordinal in range(1, 4):
        assert (await executor.execute(task["id"], actor.project_id))[
            "continuation_count"
        ] == ordinal
    assert (await executor.execute(task["id"], actor.project_id))["status"] == "completed"
    assert generations == 4
    tasks = service.list_records("task", actor, experiment["id"])
    sessions = service.list_records("session", actor, experiment["id"])
    links = service.list_records("continuation_link", actor, experiment["id"])
    artifacts = {
        artifact["id"]: artifact
        for artifact in service.list_records("artifact", actor, experiment["id"])
    }
    problem = service.get_record("problem", experiment["problem_id"], actor)
    assert len(links) == 3
    assert [link["status"] for link in sorted(links, key=lambda link: link["ordinal"])] == [
        "started"
    ] * 3
    assert validate_terminal_lineage(
        tasks,
        sessions,
        links,
        artifacts,
        lambda artifact_id: service.artifact_content(artifact_id, actor),
        experiment["id"],
        {
            "target_digest": experiment["target_digest"],
            "review_id": problem.get("review_id"),
            "environment_digest": problem["environment_digest"],
        },
    )
    # Every provider compaction remains an exact private checkpoint through
    # three fresh-session handoffs; proof status stays tied to canonical records.
    checkpoints = [
        service.load_native_checkpoint(row["checkpoint_artifact_id"], actor)
        for row in sorted(sessions, key=lambda row: row["created_at"])
    ]
    assert [cp.native_state.get("active_input_epoch", 0) for cp in checkpoints] == [1, 1, 1, 0]
    assert [len(cp.native_state.get("archives", [])) for cp in checkpoints] == [1, 1, 1, 0]
    assert all(cp.native_state["input"] for cp in checkpoints)
    assert problem["assumptions"] == ["Finite-dimensional setting"]
    assert all(
        experiment["target_digest"] in json.dumps(cp.native_state["input"]) for cp in checkpoints
    )
    assert all(
        "Finite-dimensional setting" in json.dumps(cp.native_state["input"]) for cp in checkpoints
    )
    assert all(
        f"opaque-handoff-{i}" in json.dumps(cp.native_state["input"])
        for i, cp in enumerate(checkpoints[:3], start=1)
    )
    assert all(
        link["source_checkpoint_digest"] == checkpoints[i].state_digest
        for i, link in enumerate(sorted(links, key=lambda link: link["ordinal"]))
    )
    assert not service.list_records("verification", actor, experiment["id"])
    scope = {
        "target_digest": experiment["target_digest"],
        "review_id": problem.get("review_id"),
        "environment_digest": problem["environment_digest"],
    }
    altered = [dict(link) for link in links]
    altered[0]["successor_record_id"] = altered[1]["successor_record_id"]
    with pytest.raises(LineageError, match="CONTINUATION_LINK_MISMATCH"):
        validate_terminal_lineage(
            tasks,
            sessions,
            altered,
            artifacts,
            lambda artifact_id: service.artifact_content(artifact_id, actor),
            experiment["id"],
            scope,
        )
    with pytest.raises(LineageError, match="INCOMPLETE_CONTINUATION_CHAIN"):
        validate_terminal_lineage(
            tasks,
            sessions,
            links[:-1],
            artifacts,
            lambda artifact_id: service.artifact_content(artifact_id, actor),
            experiment["id"],
            scope,
        )
    extra = {
        **sessions[0],
        "id": "unused-extra-session",
        "native_record_id": "unused-native-session",
    }
    with pytest.raises(LineageError, match="INCOMPLETE_CONTINUATION_CHAIN"):
        validate_terminal_lineage(
            tasks,
            [*sessions, extra],
            links,
            artifacts,
            lambda artifact_id: service.artifact_content(artifact_id, actor),
            experiment["id"],
            scope,
        )
    cycled = [dict(link) for link in links]
    cycled[1]["source_session_record_id"] = cycled[0]["source_session_record_id"]
    with pytest.raises(LineageError):
        validate_terminal_lineage(
            tasks,
            sessions,
            cycled,
            artifacts,
            lambda artifact_id: service.artifact_content(artifact_id, actor),
            experiment["id"],
            scope,
        )
    for field, value in (
        ("holder", "unrelated-holder"),
        ("fence", max(links, key=lambda link: link["ordinal"])["fence"] + 1),
        ("consumed_at", "2099-01-01T00:00:00+00:00"),
        ("successor_runtime", "unrelated-runtime"),
    ):
        changed = [dict(link) for link in links]
        latest_index = max(range(len(links)), key=lambda index: links[index]["ordinal"])
        changed[latest_index][field] = value
        with pytest.raises(LineageError):
            validate_terminal_lineage(
                tasks,
                sessions,
                changed,
                artifacts,
                lambda artifact_id: service.artifact_content(artifact_id, actor),
                experiment["id"],
                scope,
            )
    bad_fence = [dict(link) for link in links]
    bad_fence[0]["fence"] = 0
    with pytest.raises(LineageError, match="CONTINUATION_LINK_MISMATCH"):
        validate_terminal_lineage(
            tasks,
            sessions,
            bad_fence,
            artifacts,
            lambda artifact_id: service.artifact_content(artifact_id, actor),
            experiment["id"],
            scope,
        )
    with pytest.raises(LineageError, match="MISSING_CONTINUATION_LINKS"):
        validate_terminal_lineage(
            tasks,
            sessions,
            [],
            artifacts,
            lambda artifact_id: service.artifact_content(artifact_id, actor),
            experiment["id"],
            scope,
        )
    final_session = next(item for item in sessions if item["status"] == "completed")
    standalone_task = {
        **tasks[0],
        "continuation_count": 0,
        "continuation_link_protocol": None,
    }
    corrupted = {
        **artifacts,
        final_session["checkpoint_artifact_id"]: {
            **artifacts[final_session["checkpoint_artifact_id"]],
            "sha256": "0" * 64,
        },
    }
    with pytest.raises(LineageError, match="CHECKPOINT_SCOPE_MISMATCH"):
        validate_terminal_lineage(
            [standalone_task],
            [final_session],
            [],
            corrupted,
            lambda artifact_id: service.artifact_content(artifact_id, actor),
            experiment["id"],
            scope,
        )
    worker = Principal(
        id="untrusted-worker",
        project_id=actor.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=branch["id"],
    )
    with pytest.raises(HarnessError) as private_link:
        service.get_record("continuation_link", links[0]["id"], worker)
    assert private_link.value.code == "NOT_FOUND"
    peer_branch = service.create_branch(
        experiment["id"],
        BranchCreate(title="Peer", objective="Independent research"),
        actor,
        "peer-branch-three",
    )
    peer_task = service.create_task(
        TaskCreate(branch_id=peer_branch["id"], objective="Peer research"),
        actor,
        "peer-task-three",
    )
    assert (await executor.execute(peer_task["id"], actor.project_id))["continuation_count"] == 1
    assert (await executor.execute(peer_task["id"], actor.project_id))["status"] == "completed"
    all_tasks = service.list_records("task", actor, experiment["id"])
    all_sessions = service.list_records("session", actor, experiment["id"])
    all_links = service.list_records("continuation_link", actor, experiment["id"])
    all_artifacts = {
        artifact["id"]: artifact
        for artifact in service.list_records("artifact", actor, experiment["id"])
    }
    assert len(all_links) == 4
    assert validate_terminal_lineage(
        all_tasks,
        all_sessions,
        all_links,
        all_artifacts,
        lambda artifact_id: service.artifact_content(artifact_id, actor),
        experiment["id"],
        scope,
    )
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    await client.close()


def _briefs(value):
    """Decoded working-context prompts carried in exact native input."""
    if isinstance(value, str) and value.startswith("{"):
        try:
            decoded = json.loads(value)
        except ValueError:
            return []
        brief = decoded.get("research_brief") or decoded.get("working_context")
        return [brief] if isinstance(brief, dict) else []
    if isinstance(value, dict):
        return [brief for item in value.values() for brief in _briefs(item)]
    if isinstance(value, list):
        return [brief for item in value for brief in _briefs(item)]
    return []


@pytest.mark.asyncio
async def test_lemma_receipt_status_survives_three_handoffs_unchanged(lab):
    from physharness.verification import VerificationOutcome

    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start-evidence")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, "root-evidence"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task-evidence"
    )
    generations = 0

    async def route(request):
        nonlocal generations
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        generations += 1
        if generations <= 3:
            return httpx.Response(
                200,
                json=response(
                    [
                        compaction_item(f"evidence-{generations}"),
                        tool_call(
                            "request_handoff", {"reason": "continue"}, f"yield-{generations}"
                        ),
                    ],
                    response_id=f"evidence-{generations}",
                ),
            )
        return httpx.Response(200, json=response([message("Done.")], response_id="evidence-done"))

    class LemmaChecker:
        """Synthetic outcomes only; never kernel evidence."""

        def verify(self, request):
            ok = "good" in request.candidate_source
            return VerificationOutcome(
                status="verified" if ok else "rejected",
                assurance="kernel" if ok else "none",
                code="test_fixture",
                message="Synthetic lemma outcome",
                remediation="",
                target_digest=request.target_digest,
                challenge_sha256=request.challenge_sha256,
                environment_digest=request.environment_digest,
                candidate_sha256=request.candidate_sha256,
                checker_versions={k: "synthetic" for k in ("lean", "comparator", "nanoda")},
                axioms=[],
            )

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=lambda **kwargs: ResponsesRuntime(client=client, **kwargs),
        limits=RuntimeLimits(max_turns=30),
    )
    assert (await executor.execute(task["id"], actor.project_id))["continuation_count"] == 1
    service.verifier = LemmaChecker()
    checker = Principal(id="test-checker", project_id=actor.project_id, role="operator")
    receipts = {}
    for label in ("bad", "good"):  # The verified receipt is the latest diagnostic.
        candidate = service.create_artifact(
            ArtifactCreate(
                experiment_id=experiment["id"],
                kind="lean_source",
                content=f"{label} lemma",
                branch_id=branch["id"],
            ),
            actor,
            f"lemma-{label}",
        )
        queued = service.verify_candidate(
            experiment["id"], candidate["id"], False, actor, f"verify-{label}"
        )
        receipts[label] = service.process_verification(queued["id"], checker)
    assert receipts["good"]["status"] == "verified"
    assert receipts["bad"]["status"] == "rejected"
    assert service.verified_target_receipt(experiment["id"], actor) is None
    for ordinal in (2, 3):
        assert (await executor.execute(task["id"], actor.project_id))[
            "continuation_count"
        ] == ordinal
    assert (await executor.execute(task["id"], actor.project_id))["status"] == "completed"
    await client.close()

    def evidence(brief):
        latest = brief["readable_work"]["last_diagnostics"]
        failed = {
            item["id"]: item["evidence_status"]["status"]
            for item in brief["indices"]["failed_attempts"]["items"]
        }
        return (latest["reference"], latest["record"]["id"], latest["record"]["status"], failed)

    expected = (receipts["good"]["id"], "verified", {receipts["bad"]["id"]: "rejected"})
    agent = Principal(
        id="evidence-reader",
        project_id=actor.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=branch["id"],
    )
    from physharness.memory import PortableMemory

    memory = evidence(PortableMemory(service).working_context(branch["id"], agent))
    assert memory[1:] == expected
    sessions = sorted(
        service.list_records("session", actor, experiment["id"]),
        key=lambda row: row["created_at"],
    )
    checkpoints = [
        service.load_native_checkpoint(row["checkpoint_artifact_id"], actor) for row in sessions
    ]
    assert len(checkpoints) == 4
    assert receipts["good"]["id"] not in json.dumps(checkpoints[0].native_state)
    # Each later transition carries the same exact receipt identities and statuses.
    for checkpoint in checkpoints[1:]:
        observed = evidence(_briefs(checkpoint.native_state["input"])[-1])
        assert observed == memory
    for label, receipt in receipts.items():
        assert service.get_record("verification", receipt["id"], actor) == receipt, label


@pytest.mark.asyncio
async def test_no_prior_session_is_replayed_without_ready_continuation(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, "root"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task"
    )
    calls = 0

    async def route(request):
        nonlocal calls
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        calls += 1
        return httpx.Response(200, json=response([message("Unresolved")]))

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    executor = ResearchTaskExecutor(
        service, prices=PRICES, runtime_factory=lambda **kw: ResponsesRuntime(client=client, **kw)
    )
    assert (await executor.execute(task["id"], actor.project_id))["status"] == "completed"
    assert (await executor.execute(task["id"], actor.project_id))["status"] == "completed"
    assert calls == 1
    await client.close()


@pytest.mark.asyncio
async def test_one_slot_parent_yields_for_child_and_resumes(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, "root"
    )
    parent = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Parent research"), actor, "parent"
    )
    parent_step, child_calls = 0, 0
    note_seen = False

    async def route(request):
        nonlocal parent_step, child_calls, note_seen
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        payload = json.loads(request.content)
        prompt = json.loads(
            next(
                item["content"] for item in reversed(payload["input"]) if item.get("role") == "user"
            )
        )
        if prompt["objective"] == "Child research":
            child_calls += 1
            return httpx.Response(200, json=response([message("Child result is provisional.")]))
        outputs = [
            json.loads(item["output"])
            for item in payload["input"]
            if item.get("type") == "function_call_output"
        ]
        step = parent_step
        parent_step += 1
        if step == 0:
            item = tool_call(
                "checkpoint_research_notes",
                {
                    "approach": "Try matrix components first",
                    "unresolved_obligations": ["Show diagonal equality"],
                    "summary": "Unverified component plan",
                    "evidence_ids": [],
                },
                "notes",
            )
        elif step == 1:
            item = tool_call(
                "fork_branch",
                {
                    "title": "Helper",
                    "objective": "Child research",
                    "relation": "helper",
                    "model_index": None,
                },
                "fork",
            )
        elif step == 2:
            item = tool_call(
                "delegate",
                {
                    "branch_id": outputs[-1]["id"],
                    "objective": "Child research",
                    "dependency_ids": [],
                },
                "delegate",
            )
        elif step == 3:
            item = tool_call("wait_for_tasks", {"task_ids": [outputs[-1]["id"]]}, "wait")
        else:
            notes = prompt["handoff_notes"]
            note_seen = notes["approach"]["text"] == "Try matrix components first"
            assert notes["unresolved_obligations"]["items"] == ["Show diagonal equality"]
            assert notes["approach"]["evidence_status"] == "unverified"
            return httpx.Response(200, json=response([message("Parent resumed after child.")]))
        return httpx.Response(200, json=response([item], response_id=f"step-{step}"))

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=lambda **kw: ResponsesRuntime(client=client, **kw),
        limits=RuntimeLimits(max_turns=30),
    )
    report = await ResearchTeamRunner(service, executor=executor).run(
        TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=actor.project_id,
            mode="replay",
            task_ids=[parent["id"]],
            max_concurrency=1,
            max_tasks=2,
            timeout_seconds=10,
        )
    )
    assert report["status"] == "completed"
    assert report["attempted_tasks"] == 2
    assert child_calls == 1
    assert note_seen
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    assert service.get_record("task", parent["id"], actor)["continuation_count"] == 1
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("settled, expected_calls", [(True, 1), (False, 0)])
@pytest.mark.parametrize("source_status", ["interrupted", "running"])
async def test_first_session_recovery_requires_settled_native_boundary(
    lab, settled, expected_calls, source_status
):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, "root"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task"
    )
    controller = Principal(id="research-controller", project_id=actor.project_id, role="operator")
    slot = service.reserve_resources(experiment["id"], "0", 1, controller, "crashed-slot")
    lease = service.acquire_task(task["id"], "crashed", 1, controller, "initial-lease")

    def bind_slot(session, op):
        row = service._get(session, "task", task["id"], controller)
        return service._replace(session, row, {"worker_slot_id": slot["id"]})

    service._execute(
        controller, "bind-crashed-slot", "task.bind-slot", {"slot": slot["id"]}, bind_slot
    )
    store = CanonicalRuntimeStore(
        service, controller, experiment["id"], task["id"], "crashed", lease["fence"]
    )
    runtime_session = RuntimeSession(
        runtime="openai_responses",
        model=ModelConfig(model="explicit-test-model"),
        limits=RuntimeLimits(),
        status=source_status,
    )
    await store.save(
        RuntimeCheckpoint.build(
            runtime_session,
            {
                "input": [],
                "responses": [],
                "pending_operation": None,
                "settled_boundary": settled,
            },
        )
    )
    with service.db.transaction() as session:
        from physharness.storage import LeaseRow

        session.get(LeaseRow, task["id"]).expires_at = 0
    calls = 0

    async def route(request):
        nonlocal calls
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        calls += 1
        return httpx.Response(200, json=response([message("Safe continuation.")]))

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    executor = ResearchTaskExecutor(
        service, prices=PRICES, runtime_factory=lambda **kw: ResponsesRuntime(client=client, **kw)
    )
    if settled:
        assert (await executor.execute(task["id"], actor.project_id))["status"] == "completed"
        assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    else:
        with pytest.raises(HarnessError) as blocked:
            await executor.execute(task["id"], actor.project_id)
        assert blocked.value.code == "RECOVERY_RECONCILIATION_REQUIRED"
    assert calls == expected_calls
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("preexisting_output", [False, True])
async def test_completed_native_checkpoint_finalizes_after_worker_death_without_provider_call(
    lab, preexisting_output
):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, "root"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task"
    )
    controller = Principal(id="research-controller", project_id=actor.project_id, role="operator")
    slot = service.reserve_resources(experiment["id"], "0", 1, controller, "crashed-slot")
    lease = service.acquire_task(task["id"], "crashed", 1, controller, "initial-lease")

    def bind_slot(session, op):
        row = service._get(session, "task", task["id"], controller)
        return service._replace(session, row, {"worker_slot_id": slot["id"]})

    service._execute(
        controller, "bind-crashed-slot", "task.bind-slot", {"slot": slot["id"]}, bind_slot
    )
    store = CanonicalRuntimeStore(
        service, controller, experiment["id"], task["id"], "crashed", lease["fence"]
    )
    native = response([message("Saved terminal reasoning.")])
    native["model"] = "explicit-test-model"
    runtime_session = RuntimeSession(
        runtime="openai_responses",
        model=ModelConfig(model="explicit-test-model"),
        limits=RuntimeLimits(),
        status="completed",
        native_session_id=native["id"],
        turns=1,
        input_tokens=10,
        output_tokens=5,
    )
    await store.save(
        RuntimeCheckpoint.build(
            runtime_session,
            {
                "input": native["output"],
                "responses": [native],
                "pending_operation": None,
                "settled_boundary": True,
            },
        )
    )
    existing_artifact = None
    if preexisting_output:
        existing_artifact = service.create_artifact(
            ArtifactCreate(
                experiment_id=experiment["id"],
                branch_id=branch["id"],
                kind="research_output",
                content="Saved terminal reasoning.",
                provenance={
                    "task_id": task["id"],
                    "session_id": runtime_session.id,
                    "model": experiment["models"][0],
                },
            ),
            controller,
            f"task-output:{task['id']}:{runtime_session.id}",
        )
    with service.db.transaction() as session:
        from physharness.storage import LeaseRow

        session.get(LeaseRow, task["id"]).expires_at = 0

    async def forbidden_provider(request):
        raise AssertionError("completed checkpoint must not call the provider")

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(forbidden_provider)),
    )
    executor = ResearchTaskExecutor(
        service, prices=PRICES, runtime_factory=lambda **kw: ResponsesRuntime(client=client, **kw)
    )
    result = await executor.execute(task["id"], actor.project_id)
    assert result["status"] == "completed"
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    assert service.get_record("task", task["id"], actor)["evidence_ids"] == [result["artifact_id"]]
    if existing_artifact:
        assert result["artifact_id"] == existing_artifact["id"]
    assert service.artifact_content(result["artifact_id"], actor) == b"Saved terminal reasoning."
    assert (
        len(
            [
                row
                for row in service.list_records("session", actor, experiment["id"])
                if row["task_id"] == task["id"]
            ]
        )
        == 1
    )
    await client.close()


def test_model_reservation_and_task_binding_commit_atomically(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, "root"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task"
    )
    controller = Principal(id="controller", project_id=actor.project_id, role="operator")
    lease = service.acquire_task(task["id"], "holder", 60, controller, "lease")
    before = service.ledger(experiment["id"], actor)
    with pytest.raises(HarnessError) as stale:
        service.reserve_resources(
            experiment["id"],
            "0.001",
            0,
            controller,
            "stale-model",
            tokens=15,
            model_task_binding=(task["id"], "holder", lease["fence"] + 1),
        )
    assert stale.value.code == "STALE_LEASE"
    assert service.ledger(experiment["id"], actor) == before
    reservation = service.reserve_resources(
        experiment["id"],
        "0.001",
        0,
        controller,
        "model",
        tokens=15,
        model_task_binding=(task["id"], "holder", lease["fence"]),
    )
    assert not service.task_model_effects_settled(task["id"], controller)
    service.settle_resources(
        reservation["id"], "0.0005", False, controller, "settle", actual_tokens=8
    )
    service.reconcile_model_reservations(task["id"], controller, "reconcile")
    assert service.task_model_effects_settled(task["id"], controller)


class _WorkerDied(Exception):
    """Simulated process death: the dead worker makes no later canonical write."""


def _worker_dies_at(monkeypatch, service, name, *, committed):
    """Kill the worker at one service call, either before or after that call commits."""
    dead = False
    originals = {}

    def guarded(method):
        original = originals[method] = getattr(service, method)

        def call(*args, **kwargs):
            nonlocal dead
            if dead:
                raise _WorkerDied(method)
            if method != name:
                return original(*args, **kwargs)
            dead = True
            if committed:
                original(*args, **kwargs)
            raise _WorkerDied(method)

        return call

    # Failure evidence, blocking and slot settlement never run in a dead process.
    for method in {
        name,
        "create_artifact",
        "finish_task",
        "requeue_settled_terminal",
        "settle_resources",
    }:
        monkeypatch.setattr(service, method, guarded(method))

    def revive():
        for method, original in originals.items():
            monkeypatch.setattr(service, method, original)

    return revive


def _expire_lease(service, task_id):
    from physharness.storage import LeaseRow

    with service.db.transaction() as session:
        session.get(LeaseRow, task_id).expires_at = 0


def _handoff_lab(lab, tag, handoffs, limits=None, step=None):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=1)
    service.transition_experiment(experiment["id"], "start", 1, actor, f"start-{tag}")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, f"root-{tag}"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, f"task-{tag}"
    )
    calls = []

    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        calls.append(request)
        n = len(calls)
        if step is not None:
            item = step(n)
        elif n <= handoffs:
            item = tool_call("request_handoff", {"reason": "continue research"}, f"yield-{n}")
        else:
            item = message("Completed.")
        return httpx.Response(200, json=response([item], response_id=f"{tag}-{n}"))

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    executor = ResearchTaskExecutor(
        service,
        prices=PRICES,
        runtime_factory=lambda **kw: ResponsesRuntime(client=client, **kw),
        limits=limits or RuntimeLimits(max_turns=30),
    )
    return service, actor, experiment, task, executor, calls, client


async def _run_to_terminal(executor, task, actor, bound=8):
    for _ in range(bound):
        result = await executor.execute(task["id"], actor.project_id)
        if result["status"] != "continuation":
            return result
    raise AssertionError("task did not reach a terminal state")


def _assert_linear_lineage(service, actor, experiment):
    problem = service.get_record("problem", experiment["problem_id"], actor)
    assert validate_terminal_lineage(
        service.list_records("task", actor, experiment["id"]),
        service.list_records("session", actor, experiment["id"]),
        service.list_records("continuation_link", actor, experiment["id"]),
        {a["id"]: a for a in service.list_records("artifact", actor, experiment["id"])},
        lambda artifact_id: service.artifact_content(artifact_id, actor),
        experiment["id"],
        {
            "target_digest": experiment["target_digest"],
            "review_id": problem.get("review_id"),
            "environment_digest": problem["environment_digest"],
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("deaths", [1, 2])
async def test_worker_death_after_consuming_ticket_restores_and_reconsumes_it(
    lab, monkeypatch, deaths
):
    service, actor, experiment, task, executor, calls, client = _handoff_lab(
        lab, "consume-death", handoffs=1
    )
    assert (await executor.execute(task["id"], actor.project_id))["continuation_count"] == 1
    for _ in range(deaths):
        # The executor's own consume commits; the successor never saves a checkpoint.
        revive = _worker_dies_at(monkeypatch, service, "consume_continuation", committed=True)
        with pytest.raises(_WorkerDied):
            await executor.execute(task["id"], actor.project_id)
        revive()
        _expire_lease(service, task["id"])
        stranded = service.get_record("task", task["id"], actor)
        assert stranded["ready_continuation"] is None
        assert stranded["consumed_continuation"]["ordinal"] == 1
    assert (await executor.execute(task["id"], actor.project_id))["status"] == "completed"
    assert len(calls) == 2
    assert service.get_record("task", task["id"], actor)["continuation_count"] == 1
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    _assert_linear_lineage(service, actor, experiment)
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("dead_ordinal", [0, 1])
async def test_worker_death_before_ticket_issue_reissues_from_handed_off_source(
    lab, monkeypatch, dead_ordinal
):
    service, actor, experiment, task, executor, calls, client = _handoff_lab(
        lab, "issue-death", handoffs=3
    )
    for ordinal in range(1, dead_ordinal + 1):
        assert (await executor.execute(task["id"], actor.project_id))[
            "continuation_count"
        ] == ordinal
    # The source session is saved handed_off, then the worker dies before issue commits.
    revive = _worker_dies_at(monkeypatch, service, "issue_continuation", committed=False)
    with pytest.raises(_WorkerDied):
        await executor.execute(task["id"], actor.project_id)
    revive()
    _expire_lease(service, task["id"])
    handed_off = [
        row["status"]
        for row in service.list_records("session", actor, experiment["id"])
        if row["task_id"] == task["id"]
    ]
    assert handed_off == ["handed_off"] * (dead_ordinal + 1)
    recovered = await executor.execute(task["id"], actor.project_id)
    assert recovered["continuation_count"] == dead_ordinal + 2
    assert (await _run_to_terminal(executor, task, actor))["status"] == "completed"
    # No settled provider response is replayed during recovery.
    assert len(calls) == 4
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    _assert_linear_lineage(service, actor, experiment)
    await client.close()


@pytest.mark.asyncio
async def test_handoff_from_superseded_source_is_rejected_without_forking(lab, monkeypatch):
    service, actor, experiment, task, executor, calls, client = _handoff_lab(
        lab, "fork", handoffs=3
    )
    assert (await executor.execute(task["id"], actor.project_id))["continuation_count"] == 1
    (first_link,) = service.list_records("continuation_link", actor, experiment["id"])
    original = service.issue_continuation

    def stale_source(task_id, holder, fence, source_id, digest, reason, issuer, key, **kwargs):
        return original(
            task_id,
            holder,
            fence,
            first_link["source_session_id"],
            first_link["source_checkpoint_digest"],
            reason,
            issuer,
            key,
            **kwargs,
        )

    monkeypatch.setattr(service, "issue_continuation", stale_source)
    with pytest.raises(HarnessError) as forked:
        await executor.execute(task["id"], actor.project_id)
    assert forked.value.code == "HANDOFF_SOURCE_NOT_HEAD"
    monkeypatch.setattr(service, "issue_continuation", original)
    links = service.list_records("continuation_link", actor, experiment["id"])
    assert [link["ordinal"] for link in links] == [1]
    assert service.get_record("task", task["id"], actor)["ready_continuation"] is None
    _expire_lease(service, task["id"])
    assert (await _run_to_terminal(executor, task, actor))["status"] == "completed"
    assert len(calls) == 4
    _assert_linear_lineage(service, actor, experiment)
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("handoff", ["model_request", "token_pressure"])
async def test_task_token_guard_is_cumulative_across_portable_continuations(lab, handoff):
    def step(n):
        if handoff == "model_request":
            return tool_call("request_handoff", {"reason": "continue research"}, f"yield-{n}")
        return tool_call("working_context", {}, f"context-{n}")

    limits = RuntimeLimits(max_turns=30, max_total_tokens=100, max_output_tokens=10)
    service, actor, experiment, task, executor, calls, client = _handoff_lab(
        lab, f"tokens-{handoff}", handoffs=0, limits=limits, step=step
    )
    with pytest.raises(ExecutionError) as exhausted:
        await _run_to_terminal(executor, task, actor, bound=12)
    assert exhausted.value.code == "BUDGET_EXHAUSTED"
    sessions = [
        row
        for row in service.list_records("session", actor, experiment["id"])
        if row["task_id"] == task["id"]
    ]
    # Each mock generation uses 15 tokens; a sixth would exceed the 100-token task guard.
    assert sum(row["input_tokens"] + row["output_tokens"] for row in sessions) == 90
    assert len(calls) == 6
    final = service.get_record("task", task["id"], actor)
    assert final["status"] == "blocked"
    assert final.get("continuation_count", 0) == (6 if handoff == "model_request" else 0)
    assert service.ledger(experiment["id"], actor)["active_workers"] == 0
    await client.close()
