"""Deterministic MOCK provider integration. No live API, Lean, or scientific review evidence.

These tests use the real OpenAI SDK over MockTransport and the canonical service,
leases, memory, ledger, artifact store, and worker. setup_experiment's reviewer is
an explicit synthetic test actor; its fixture approval is not real expert review.
"""

import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI
from test_core import setup_experiment
from test_execution_responses import message, response

from physharness.domain import BranchCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.execution import ExecutionError, ResponsesRuntime, RuntimeLimits
from physharness.orchestration import research_worker
from physharness.storage import LeaseRow

PRICES = {
    "explicit-test-model": {
        "input_usd_per_million": "1",
        "output_usd_per_million": "2",
        "source": "mock-test",
    }
}


def campaign(lab, concurrency=2):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab, concurrency=concurrency)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Explore"), actor, "root"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Research"), actor, "task"
    )
    return experiment, branch, task


def mock_executor(service, handler):
    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        return await handler(request)

    client = AsyncOpenAI(
        api_key="mock-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )

    def factory(**kwargs):
        return ResponsesRuntime(client=client, **kwargs)

    return research_worker.ResearchTaskExecutor(
        service, prices=PRICES, runtime_factory=factory, limits=RuntimeLimits(max_turns=30)
    ), client


def tool_call(name, arguments, call_id):
    return {
        "id": "fc_" + call_id,
        "type": "function_call",
        "name": name,
        "arguments": json.dumps(arguments),
        "call_id": call_id,
        "status": "completed",
    }


async def test_mock_single_worker_runs_to_canonical_output_and_replay_is_noop(lab):
    service, actor, _ = lab
    experiment, _, task = campaign(lab)
    calls = []

    async def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=response([message("Unresolved finite-dimensional case.")]))

    executor, client = mock_executor(service, handler)
    manifest = research_worker.TeamRunManifest(
        experiment_id=experiment["id"],
        project_id=actor.project_id,
        mode="replay",
        task_ids=[task["id"]],
        max_concurrency=1,
    )
    runner = research_worker.ResearchTeamRunner(service, executor=executor)
    result = await runner.run(manifest)
    repeated = await runner.run(manifest)
    assert result["status"] == repeated["status"] == "completed"
    assert result["mode"] == "replay" and result["evidence_level"] == "mock_provider"
    assert len(calls) == 1
    assert service.get_record("task", task["id"], actor)["status"] == "completed"
    assert result["ledger"]["tokens_spent"] == 15
    assert result["ledger"]["active_workers"] == 0
    assert service.list_records("claim", actor) == []
    assert service.list_records("verification", actor) == []
    await client.close()


async def test_mock_two_workers_overlap_and_share_one_envelope(lab):
    service, actor, _ = lab
    experiment, branch, task = campaign(lab)
    child = service.create_branch(
        experiment["id"],
        BranchCreate(
            title="Alternative",
            objective="Independent method",
            parent_id=branch["id"],
            relation="competing",
        ),
        actor,
        "child",
    )
    second = service.create_task(
        TaskCreate(branch_id=child["id"], objective="Alternative"), actor, "second"
    )
    entered, peak = 0, 0
    both = asyncio.Event()

    async def handler(request):
        nonlocal entered, peak
        entered += 1
        peak = max(peak, service.ledger(experiment["id"], actor)["active_workers"])
        if entered == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 2)
        return httpx.Response(
            200,
            json=response([message("Method remains unresolved.")], response_id=f"resp_{entered}"),
        )

    executor, client = mock_executor(service, handler)
    result = await research_worker.ResearchTeamRunner(service, executor=executor).run(
        research_worker.TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=actor.project_id,
            mode="replay",
            task_ids=[task["id"], second["id"]],
            max_concurrency=2,
        )
    )
    assert result["status"] == "completed" and peak == 2
    assert result["ledger"]["tokens_spent"] == 30
    assert result["ledger"]["active_workers"] == 0
    assert len(service.list_records("session", actor)) == 2
    assert service.list_records("claim", actor) == []
    await client.close()


@pytest.mark.parametrize("lease_state", ["stale", "cancelled"])
async def test_research_tool_rejects_lost_lease_or_cancelled_campaign_before_effect(
    lab, lease_state
):
    service, actor, _ = lab
    experiment, branch, task = campaign(lab)
    controller = Principal(id="controller", project_id=actor.project_id, role="operator")
    lease = service.acquire_task(task["id"], "worker", 60, controller, "lease")
    agent = Principal(
        id="worker",
        project_id=actor.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=branch["id"],
    )
    if lease_state == "stale":
        with service.db.transaction() as session:
            session.get(LeaseRow, task["id"]).expires_at = 0
    else:
        service.transition_experiment(experiment["id"], "cancel", 2, actor, "cancel")
    dispatcher = research_worker.research_tools(
        service,
        agent,
        branch["id"],
        task_context={"task_id": task["id"], "holder": "worker", "fence": lease["fence"]},
    )
    before = len(service.list_records("artifact", actor))
    with pytest.raises(ExecutionError) as error:
        await dispatcher.dispatch("store_artifact", {"kind": "idea", "content": "late"}, "late")
    assert error.value.code in {"STALE_LEASE", "EXPERIMENT_NOT_ACTIVE"}
    assert len(service.list_records("artifact", actor)) == before


async def test_mock_parent_loss_retains_compactions_and_child_finishes_independently(lab):
    service, actor, _ = lab
    experiment, branch, task = campaign(lab)
    parent_step, restored, child_calls = 0, None, 0

    async def handler(request):
        nonlocal parent_step, restored, child_calls
        payload = json.loads(request.content)
        prompt = json.loads(payload["input"][0]["content"])
        if prompt["objective"] == "Independent child":
            child_calls += 1
            assert prompt["research_brief"]["assumptions"] == ["Finite-dimensional setting"]
            return httpx.Response(
                200,
                json=response(
                    [message("Child method still needs proof.")], response_id="child-response"
                ),
            )
        results = [
            json.loads(item["output"])
            for item in payload["input"]
            if item.get("type") == "function_call_output"
        ]
        checkpoint_args = {
            "approach": "Explore spectral reasoning",
            "unresolved_obligations": ["Prove convergence"],
            "summary": "Unverified working idea",
            "previous_checkpoint_id": None,
            "evidence_ids": [],
            "max_bytes": 65536,
            "max_estimated_tokens": 16384,
        }
        step = parent_step
        parent_step += 1
        if step == 0:
            item = tool_call("checkpoint_context", checkpoint_args, "compact-1")
        elif step == 1:
            item = tool_call(
                "checkpoint_context",
                {**checkpoint_args, "previous_checkpoint_id": results[-1]["id"]},
                "compact-2",
            )
        elif step == 2:
            item = tool_call("restore_context", {"checkpoint_id": results[-1]["id"]}, "restore")
        elif step == 3:
            restored = results[-1]
            item = tool_call(
                "fork_branch",
                {
                    "title": "Helper",
                    "objective": "Independent child",
                    "relation": "helper",
                    "model_index": None,
                },
                "fork",
            )
        elif step == 4:
            item = tool_call(
                "delegate",
                {
                    "branch_id": results[-1]["id"],
                    "objective": "Independent child",
                    "dependency_ids": [],
                },
                "delegate",
            )
        else:
            raise httpx.ReadError("mock response lost after request transmission", request=request)
        return httpx.Response(200, json=response([item], response_id=f"parent-{step}"))

    executor, client = mock_executor(service, handler)
    result = await research_worker.ResearchTeamRunner(service, executor=executor).run(
        research_worker.TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=actor.project_id,
            mode="replay",
            task_ids=[task["id"]],
            max_concurrency=2,
            max_tasks=3,
        )
    )
    assert result["status"] == "blocked" and child_calls == 1
    assert sorted(outcome["status"] for outcome in result["outcomes"]) == ["blocked", "completed"]
    assert restored["lineage"]["generation"] == 2
    assert restored["scientific_core"]["target"]["assumptions"] == ["Finite-dimensional setting"]
    assert restored["unresolved_obligations"]["items"] == ["Prove convergence"]
    assert restored["summary"]["evidence_status"] == "unverified"
    assert result["ledger"]["uncertain_operations"] == 1
    assert result["ledger"]["tokens_reserved"] > 0 and result["ledger"]["active_workers"] == 0
    assert (
        len(
            [
                a
                for a in service.list_records("artifact", actor)
                if a["artifact_kind"] == "checkpoint"
            ]
        )
        == 2
    )
    assert service.list_records("claim", actor) == []
    assert (await executor.execute(task["id"], actor.project_id))["status"] == "blocked"
    assert parent_step == 6  # No request retry, including after a repeated canonical dispatch.
    await client.close()


async def test_mock_campaign_cancellation_interrupts_inflight_request_and_retains_budget(lab):
    service, actor, _ = lab
    experiment, _, task = campaign(lab)
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.Event().wait()

    executor, client = mock_executor(service, handler)
    running = asyncio.create_task(
        research_worker.ResearchTeamRunner(service, executor=executor).run(
            research_worker.TeamRunManifest(
                experiment_id=experiment["id"],
                project_id=actor.project_id,
                mode="replay",
                task_ids=[task["id"]],
                max_concurrency=1,
            )
        )
    )
    await asyncio.wait_for(entered.wait(), 2)
    service.transition_experiment(experiment["id"], "cancel", 2, actor, "cancel")
    result = await asyncio.wait_for(running, 2)
    assert result["status"] == "blocked" and result["stop_reason"] == "EXPERIMENT_NOT_ACTIVE"
    assert result["ledger"]["uncertain_operations"] == 1
    assert result["ledger"]["tokens_reserved"] > 0
    assert result["ledger"]["active_workers"] == 0
    assert service.list_records("session", actor)[0]["status"] == "uncertain"
    assert not any(
        a["artifact_kind"] == "research_output" for a in service.list_records("artifact", actor)
    )
    await client.close()


async def test_mock_team_timeout_is_finite_and_leaves_unconfirmed_generation_reserved(lab):
    service, actor, _ = lab
    experiment, _, task = campaign(lab)

    async def handler(request):
        await asyncio.Event().wait()

    executor, client = mock_executor(service, handler)
    result = await asyncio.wait_for(
        research_worker.ResearchTeamRunner(service, executor=executor).run(
            research_worker.TeamRunManifest(
                experiment_id=experiment["id"],
                project_id=actor.project_id,
                mode="replay",
                task_ids=[task["id"]],
                timeout_seconds=0.1,
            )
        ),
        2,
    )
    assert result["stop_reason"] == "TEAM_TIMEOUT"
    assert result["ledger"]["uncertain_operations"] == 1
    assert service.get_record("task", task["id"], actor)["status"] == "blocked"
    await client.close()


async def test_live_and_replay_modes_cannot_silently_substitute_providers(lab, monkeypatch):
    service, actor, _ = lab
    experiment, _, task = campaign(lab)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    executor = research_worker.ResearchTaskExecutor(service, prices=PRICES)
    for mode, code in [("live", "LIVE_PROVIDER_REQUIRED"), ("replay", "REPLAY_PROVIDER_REQUIRED")]:
        with pytest.raises(HarnessError) as error:
            await research_worker.ResearchTeamRunner(service, executor=executor).run(
                research_worker.TeamRunManifest(
                    experiment_id=experiment["id"],
                    project_id=actor.project_id,
                    mode=mode,
                    task_ids=[task["id"]],
                )
            )
        assert error.value.code == code
    assert service.list_records("session", actor) == []
    assert service.ledger(experiment["id"], actor)["tokens_reserved"] == 0


async def test_mock_model_waits_for_real_service_receipt_and_reuses_fixture_lemma(lab):
    """Synthetic checker injected at the verifier boundary; NOT Lean/scientific evidence."""
    from physharness.verification import VerificationOutcome

    service, actor, _ = lab
    experiment, _, task = campaign(lab)

    class ExplicitSyntheticChecker:
        def verify(self, request):
            return VerificationOutcome(
                status="verified",
                assurance="independent_kernel",
                code="mock_checker_fixture",
                message="Synthetic test, not kernel evidence",
                remediation="",
                target_digest=request.target_digest,
                challenge_sha256=request.challenge_sha256,
                environment_digest=request.environment_digest,
                candidate_sha256=request.candidate_sha256,
                checker_versions={name: "mock-only" for name in ("lean", "comparator", "nanoda")},
                axioms=[],
            )

    service.verifier = ExplicitSyntheticChecker()
    step, bundle = 0, None

    async def handler(request):
        nonlocal step, bundle
        payload = json.loads(request.content)
        results = [
            json.loads(item["output"])
            for item in payload["input"]
            if item.get("type") == "function_call_output"
        ]
        current = step
        step += 1
        if current == 0:
            item = tool_call(
                "store_artifact",
                {"kind": "lean_source", "content": "theorem target : (1 : Nat) = 1 := by rfl"},
                "candidate",
            )
        elif current == 1:
            item = tool_call("verify_candidate", {"artifact_id": results[-1]["id"]}, "verify")
        elif current == 2:
            item = tool_call(
                "wait_for_verification",
                {"receipt_id": results[-1]["id"], "timeout_seconds": 2},
                "wait",
            )
        elif current == 3:
            assert results[-1]["status"] == "verified"
            item = tool_call(
                "read_dependency_bundle", {"claim_id": results[-1]["claim_id"]}, "reuse"
            )
        else:
            bundle = results[-1]
            return httpx.Response(
                200,
                json=response(
                    [message("Fixture dependency requires recomposition.")], response_id="last"
                ),
            )
        return httpx.Response(200, json=response([item], response_id=f"verify-step-{current}"))

    executor, client = mock_executor(service, handler)
    result = await research_worker.ResearchTeamRunner(service, executor=executor).run(
        research_worker.TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=actor.project_id,
            mode="replay",
            task_ids=[task["id"]],
        )
    )
    assert result["status"] == "completed"
    assert result["evidence_level"] == "mock_provider"
    assert result["verification_receipts"][0]["code"] == "mock_checker_fixture"
    assert bundle["recomposition_required"] is True
    assert bundle["receipt"]["id"] == service.list_records("verification", actor)[0]["id"]
    assert bundle["candidate_source"] == "theorem target : (1 : Nat) = 1 := by rfl"
    assert bundle["claim"]["assumptions"] == ["Finite-dimensional setting"]
    await client.close()


async def test_mock_verifier_timeout_reports_worker_still_running_and_pending_receipt(lab):
    import threading

    from physharness.domain import ArtifactCreate
    from physharness.verification import UnavailableVerifier

    service, actor, _ = lab
    experiment, branch, task = campaign(lab)
    entered, release = threading.Event(), threading.Event()

    class SlowUnavailableChecker:
        def verify(self, request):
            entered.set()
            assert release.wait(5)
            return UnavailableVerifier().verify(request)

    service.verifier = SlowUnavailableChecker()
    candidate = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            branch_id=branch["id"],
            kind="lean_source",
            content="theorem target : True := by trivial",
        ),
        actor,
        "slow-candidate",
    )
    receipt = service.verify_candidate(
        experiment["id"], candidate["id"], False, actor, "slow-verify"
    )

    async def handler(request):
        return httpx.Response(200, json=response([message("Check remains pending.")]))

    executor, client = mock_executor(service, handler)
    runner = research_worker.ResearchTeamRunner(service, executor=executor)
    try:
        result = await asyncio.wait_for(
            runner.run(
                research_worker.TeamRunManifest(
                    experiment_id=experiment["id"],
                    project_id=actor.project_id,
                    mode="replay",
                    task_ids=[task["id"]],
                    timeout_seconds=0.2,
                )
            ),
            2,
        )
        assert entered.is_set()
        assert result["stop_reason"] == "TEAM_TIMEOUT"
        assert result["pending_verification_ids"] == [receipt["id"]]
        assert result["verification_worker_continues"] is True
        assert service.get_record("verification", receipt["id"], actor)["status"] == "queued"
    finally:
        release.set()
        await asyncio.gather(*runner._verification_tasks)
        await client.close()
    assert service.get_record("verification", receipt["id"], actor)["status"] == "blocked"
    assert service.list_records("claim", actor) == []


async def test_mock_delegated_child_remains_queued_at_finite_task_limit(lab):
    service, actor, _ = lab
    experiment, branch, task = campaign(lab)
    child = service.create_branch(
        experiment["id"],
        BranchCreate(
            title="Collaborator",
            objective="Try a different method",
            parent_id=branch["id"],
            relation="collaborator",
        ),
        actor,
        "limited-child",
    )
    child_task = service.create_task(
        TaskCreate(branch_id=child["id"], objective="Later", dependency_ids=[task["id"]]),
        actor,
        "limited-task",
    )
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response([message("Unresolved.")]))

    executor, client = mock_executor(service, handler)
    result = await research_worker.ResearchTeamRunner(service, executor=executor).run(
        research_worker.TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=actor.project_id,
            mode="replay",
            task_ids=[task["id"]],
            max_tasks=1,
        )
    )
    assert result["stop_reason"] == "TEAM_TASK_LIMIT" and len(calls) == 1
    assert result["remaining_task_ids"] == [child_task["id"]]
    assert service.get_record("task", child_task["id"], actor)["status"] == "queued"
    await client.close()


async def test_duplicate_worker_dispatch_cannot_enter_provider_twice(lab):
    service, actor, _ = lab
    _, _, task = campaign(lab)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def handler(request):
        calls.append(request)
        entered.set()
        await release.wait()
        return httpx.Response(200, json=response([message("Unresolved.")]))

    executor, client = mock_executor(service, handler)
    first = asyncio.create_task(executor.execute(task["id"], actor.project_id))
    await asyncio.wait_for(entered.wait(), 2)
    try:
        with pytest.raises(HarnessError) as error:
            await executor.execute(task["id"], actor.project_id)
        assert error.value.code == "RECOVERY_RECONCILIATION_REQUIRED"
        assert len(calls) == 1
    finally:
        release.set()
        await first
        await client.close()


async def test_verifier_dispatch_failure_does_not_fabricate_a_blocked_receipt(lab, monkeypatch):
    from physharness.domain import ArtifactCreate

    service, actor, _ = lab
    experiment, branch, task = campaign(lab)
    candidate = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            branch_id=branch["id"],
            kind="lean_source",
            content="theorem target : True := by trivial",
        ),
        actor,
        "candidate",
    )
    receipt = service.verify_candidate(experiment["id"], candidate["id"], False, actor, "receipt")

    def failed_dispatch(*args):
        raise OSError("mock database unavailable")

    monkeypatch.setattr(service, "process_verification", failed_dispatch)

    async def handler(request):
        return httpx.Response(200, json=response([message("No proof established.")]))

    executor, client = mock_executor(service, handler)
    result = await research_worker.ResearchTeamRunner(service, executor=executor).run(
        research_worker.TeamRunManifest(
            experiment_id=experiment["id"],
            project_id=actor.project_id,
            mode="replay",
            task_ids=[task["id"]],
        )
    )
    assert result["verification_receipts"][0]["status"] == "queued"
    assert result["verification_errors"] == [
        {"receipt_id": receipt["id"], "code": "VERIFICATION_FAILED"}
    ]
    assert result["pending_verification_ids"] == [receipt["id"]]
    await client.close()


async def test_model_candidate_requests_independent_replay_and_missing_checker_cannot_accept(lab):
    service, actor, _ = lab
    experiment, branch, _ = campaign(lab)
    agent = Principal(
        id="model-worker",
        project_id=actor.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=branch["id"],
    )
    dispatcher = research_worker.research_tools(service, agent, branch["id"])
    candidate = await dispatcher.dispatch(
        "store_artifact",
        {"kind": "lean_source", "content": "theorem target : (1 : Nat) = 1 := by rfl"},
        "source",
    )
    queued = await dispatcher.dispatch(
        "verify_candidate", {"artifact_id": candidate["id"]}, "verify"
    )
    assert queued["publication"] is True
    verifier = Principal(id="unconfigured-checker", project_id=actor.project_id, role="verifier")
    checked = service.process_verification(queued["id"], verifier)
    assert checked["status"] == "blocked" and checked["assurance"] == "none"
    assert service.list_records("claim", actor) == []
    assert service.search_knowledge(experiment["id"], "", agent)["items"] == []
