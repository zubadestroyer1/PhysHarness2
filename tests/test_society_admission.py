"""Society admission is by remaining dollars; referees run in their own slot pool (S1 #16)."""

import asyncio
import json
from collections import Counter
from contextlib import suppress
from decimal import Decimal

import httpx
import pytest
from commons_helpers import society_lab
from pydantic import ValidationError
from test_execution_responses import message
from test_research_loop_integration import response, tool_call
from test_research_workforce import started
from test_society_tools import (
    VERDICT,
    lemma_args,
    run_manifest,
    scripted_society_route,
    society_runner,
)

from physharness import mcp_server
from physharness.bootstrap import build_service
from physharness.commons_models import NodeCreate
from physharness.config import Settings
from physharness.domain import BranchCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.orchestration.research_worker import TeamRunManifest
from physharness.service import HarnessService
from physharness.workforce_models import ConfigureWorkforceRequest, RecruitResearcherRequest

OPERATOR = Principal(id="operator", project_id="lab", role="operator")


def helper_request(parent, title="Helper"):
    return RecruitResearcherRequest(
        parent_branch_id=parent.branch_id, title=title, objective="Help.", detached=True
    )


def priced(lab, output_rates):
    """``lab`` on a service that records these output prices (USD per million tokens)."""
    service, researcher, reviewer = lab
    prices = {
        model: {"input_usd_per_million": "1", "output_usd_per_million": rate}
        for model, rate in output_rates.items()
    }
    return HarnessService(service.db, service.artifacts, model_prices=prices), researcher, reviewer


def test_society_admission_is_by_dollars_and_caps_ignore_referees(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    service.configure_workforce(
        exp["id"], ConfigureWorkforceRequest(admission_floor_usd="1000000"), OPERATOR, "floor"
    )
    helper = RecruitResearcherRequest(
        parent_branch_id=alpha.branch_id, title="Helper", objective="Help.", detached=True
    )
    with pytest.raises(HarnessError) as refused:
        service.recruit_researcher(exp["id"], helper, alpha, "recruit")
    error = refused.value
    assert error.code == "ADMISSION_BUDGET" and error.message.startswith("Budget, not input:")
    assert Decimal(error.details["floor_usd"]) == Decimal("1000000") and not error.retryable
    assert error.details["reserved_usd"] == "0" and error.remediation.startswith("Do not retry")
    caps = ConfigureWorkforceRequest(
        max_total_tasks=1, max_pending_tasks=1, admission_floor_usd="0.01", expected_revision=1
    )
    service.configure_workforce(exp["id"], caps, OPERATOR, "caps")
    service.recruit_researcher(exp["id"], helper, alpha, "recruit-ok")
    node = service.create_node(
        exp["id"], NodeCreate(node_type="lemma", title="L", statement="L."), alpha, "l"
    )
    # Outside the caps.
    assert service.request_review(node["id"], beta, "review")["review_task_id"]
    with pytest.raises(HarnessError) as capped:
        service.recruit_researcher(
            exp["id"], helper.model_copy(update={"title": "Two"}), alpha, "recruit-2"
        )
    assert capped.value.code == "TASK_TOTAL_CAP"


@pytest.mark.parametrize(
    ("cap", "code"),
    [("max_total_tasks", "TASK_TOTAL_CAP"), ("max_pending_tasks", "TASK_PENDING_CAP")],
)
def test_research_caps_do_not_count_existing_referees(lab, cap, code):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(
        exp["id"], NodeCreate(node_type="lemma", title="L", statement="L."), alpha, "l"
    )
    service.request_review(node["id"], beta, "review")  # a queued referee task
    service.configure_workforce(exp["id"], ConfigureWorkforceRequest(**{cap: 1}), OPERATOR, "cap")
    service.recruit_researcher(exp["id"], helper_request(alpha), alpha, "recruit")
    with pytest.raises(HarnessError) as capped:
        service.recruit_researcher(exp["id"], helper_request(alpha, "Two"), alpha, "recruit-2")
    assert capped.value.code == code


def test_society_admits_only_while_one_output_reservation_fits(lab):
    # One turn's output reservation (4,096 tokens) costs exactly the $1.00 envelope.
    lab = priced(lab, {"explicit-test-model": "244.140625"})
    service, _, exp, _, (alpha, _) = society_lab(lab)
    service.recruit_researcher(exp["id"], helper_request(alpha), alpha, "exactly-enough")
    service.reserve_resources(exp["id"], "0.000001", 0, OPERATOR, "hold")
    with pytest.raises(HarnessError) as refused:
        service.recruit_researcher(exp["id"], helper_request(alpha, "Two"), alpha, "short")
    error = refused.value
    assert error.code == "ADMISSION_BUDGET" and error.message.startswith("Budget, not input:")
    assert error.details == {
        "remaining_usd": "0.999999",
        "reserved_usd": "0.000001",
        "floor_usd": "0",
        "minimum_reservation_usd": "1",
        "count": 1,
    }
    # Running work usually settles below its reservation, so this refusal can clear.
    assert error.retryable and "retry once running work settles" in error.remediation
    # Unless the floor leaves too little even with every reservation released.
    service.configure_workforce(
        exp["id"], ConfigureWorkforceRequest(admission_floor_usd="0.5"), OPERATOR, "floor"
    )
    with pytest.raises(HarnessError) as floored:
        service.recruit_researcher(exp["id"], helper_request(alpha, "Three"), alpha, "floored")
    error = floored.value
    assert error.details["reserved_usd"] == "0.000001" and not error.retryable
    assert error.remediation.startswith("Do not retry")


def test_unpriced_admission_needs_dollars_left_above_the_floor(lab):
    """Merge audit: without a recorded price the first reservation reads as $0, yet nothing is
    admitted once no dollar remains above the floor."""
    service, _, exp, _, (alpha, _) = society_lab(lab)
    assert service.model_prices == {}
    service.recruit_researcher(exp["id"], helper_request(alpha), alpha, "while-funded")
    service.reserve_resources(exp["id"], "0.999999", 0, OPERATOR, "hold")
    service.recruit_researcher(exp["id"], helper_request(alpha, "Two"), alpha, "last-micro")
    service.reserve_resources(exp["id"], "0.000001", 0, OPERATOR, "hold-rest")
    with pytest.raises(HarnessError) as refused:
        service.recruit_researcher(exp["id"], helper_request(alpha, "Three"), alpha, "spent")
    error = refused.value
    assert error.code == "ADMISSION_BUDGET"
    assert error.message == "Budget, not input: $0 remains and new work needs more than $0."
    assert (error.details["remaining_usd"], error.details["minimum_reservation_usd"]) == ("0", "0")
    assert error.retryable  # the reservations may settle for less


def test_admission_prices_the_model_the_task_runs_with(lab):
    # Alpha runs on the cheap model, beta on one whose output reservation exceeds $1.00.
    lab = priced(lab, {"explicit-test-model": "1", "explicit-test-model-1": "1000"})
    service, _, exp, _, (alpha, beta) = society_lab(lab, models=2)
    service.recruit_researcher(exp["id"], helper_request(alpha), alpha, "inherits-cheap")
    dear = helper_request(alpha, "Dear").model_copy(update={"model_index": 1})
    for request, agent in ((dear, alpha), (helper_request(beta), beta)):
        with pytest.raises(HarnessError) as refused:
            service.recruit_researcher(exp["id"], request, agent, f"dear-{agent.id}")
        assert refused.value.details["minimum_reservation_usd"] == "4.096"


def test_the_service_prices_admission_with_the_worker_price_table(tmp_path):
    price = {"input_usd_per_million": "1", "output_usd_per_million": "2"}
    settings = Settings(
        auth_file=tmp_path / "absent-auth",
        database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
        artifact_root=tmp_path / "artifacts",
        model_prices={"priced-model": price},
    )
    rate = build_service(settings).model_prices["priced-model"].output_usd_per_million
    assert rate == Decimal("2")


def test_configure_workforce_accepts_only_a_floor(lab, monkeypatch):
    assert ConfigureWorkforceRequest(admission_floor_usd="0.5").max_total_tasks is None
    assert ConfigureWorkforceRequest(max_pending_tasks=5).max_total_tasks is None
    with pytest.raises(ValidationError):
        ConfigureWorkforceRequest(max_total_tasks=1, max_pending_tasks=2)
    service, _, exp, _, _ = society_lab(lab)

    def policy():
        (record,) = service.list_records("workforce_policy", OPERATOR, exp["id"])
        return record

    service.configure_workforce(exp["id"], ConfigureWorkforceRequest(), OPERATOR, "none")
    assert "admission_floor_usd" not in policy()
    floor = ConfigureWorkforceRequest(admission_floor_usd="0.5", expected_revision=1)
    service.configure_workforce(exp["id"], floor, OPERATOR, "floor")
    assert Decimal(policy()["admission_floor_usd"]) == Decimal("0.5")
    capacity = service.research_capacity(exp["id"], OPERATOR)
    assert capacity["max_total_tasks"] is None and capacity["max_pending_tasks"] is None
    # Reconfiguring without a floor removes it: None reads as no floor.
    cleared = ConfigureWorkforceRequest(expected_revision=2)
    service.configure_workforce(exp["id"], cleared, OPERATOR, "cleared")
    assert policy().get("admission_floor_usd") is None
    calls = []
    monkeypatch.setattr(mcp_server, "call", lambda *args: calls.append(args) or {})
    mcp_server.configure_workforce("experiment", "op-1")
    mcp_server.configure_workforce("experiment", "op-2", admission_floor_usd="0.25")
    assert "admission_floor_usd" not in calls[0][2]
    assert calls[1][2]["admission_floor_usd"] == "0.25"


def test_legacy_admission_keeps_count_caps_and_refuses_a_floor(lab):
    service, researcher, operator, experiment = started(lab)
    only_floor = ConfigureWorkforceRequest(admission_floor_usd="1000000")
    with pytest.raises(HarnessError) as refused:
        service.configure_workforce(experiment["id"], only_floor, operator, "floor")
    error = refused.value
    assert (error.code, error.status) == ("ADMISSION_FLOOR_REQUIRES_SOCIETY", 422)
    assert "admission_floor_usd" in error.message
    assert service.list_records("workforce_policy", operator, experiment["id"]) == []
    capacity = service.research_capacity(experiment["id"], operator)
    assert (capacity["max_total_tasks"], capacity["max_pending_tasks"]) == (10_000, 10_000)
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Root"), researcher, "branch"
    )
    service.create_task(TaskCreate(branch_id=branch["id"], objective="Root"), researcher, "task")
    caps = ConfigureWorkforceRequest(max_total_tasks=1, max_pending_tasks=1)
    service.configure_workforce(experiment["id"], caps, operator, "caps")
    with pytest.raises(HarnessError) as capped:
        service.create_task(TaskCreate(branch_id=branch["id"], objective="Two"), researcher, "two")
    assert capped.value.code == "TASK_TOTAL_CAP"


# Runner slot pools ----------------------------------------------------------------------------


def roots(service, author, experiment, branches, count):
    """``count`` root tasks, one per branch (adding branches beyond the lab's two)."""
    branches = [
        *branches,
        *(
            service.create_branch(
                experiment["id"],
                BranchCreate(title=f"Extra {index}", objective="Extra"),
                author,
                f"extra-branch-{index}",
            )
            for index in range(count - len(branches))
        ),
    ]
    return [
        service.create_task(
            TaskCreate(branch_id=branch["id"], objective=f"Root {index}"), author, f"root-{index}"
        )
        for index, branch in enumerate(branches[:count])
    ]


def slot_route(service, author, experiment, *, hold_seconds):
    """The first root to call the model requests a review of its node; every root then holds
    its slot until the referee starts (or ``hold_seconds`` pass). Each task's first model
    call records its name and how many research tasks the platform then shows running."""
    starts, referee_started, phases = [], asyncio.Event(), Counter()

    def running_research():
        return sum(
            task["status"] == "running" and not task.get("review_assignment")
            for task in service.list_records("task", author, experiment["id"])
        )

    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        payload = json.loads(request.content)
        prompt = json.loads(payload["input"][0]["content"])
        referee = str(prompt.get("instructions", "")).startswith("Research society referee")
        name = "referee" if referee else prompt["objective"]
        phase = phases[name]
        phases[name] += 1
        if phase == 0:
            starts.append((name, running_research()))
        outputs = [
            json.loads(item["output"])
            for item in payload["input"]
            if item.get("type") == "function_call_output"
        ]
        requester = starts[0][0]
        if name == "referee":
            referee_started.set()
            items = (
                [tool_call("submit_review", VERDICT, "verdict-1")]
                if phase == 0
                else [message("Reviewed.")]
            )
        elif name == requester and phase == 0:
            items = [tool_call("commons_node", lemma_args(), "create-1")]
        elif name == requester and phase == 1:
            review = {"action": "request_review", "node_id": outputs[0]["id"]}
            items = [tool_call("commons_node", review, "review-1")]
        else:
            with suppress(TimeoutError):
                await asyncio.wait_for(referee_started.wait(), hold_seconds)
            items = [message("Done.")]
        return httpx.Response(200, json=response(items, response_id=f"{name}-{phase}"))

    return route, starts


async def test_runner_reserves_referee_slots(lab):
    service, author, exp, branches, _ = society_lab(lab, concurrency=3, referee_slots=1)
    tasks = roots(service, author, exp, branches, 3)
    route, starts = slot_route(service, author, exp, hold_seconds=5)
    runner, client = society_runner(service, route)
    manifest = TeamRunManifest(
        experiment_id=exp["id"],
        project_id=author.project_id,
        mode="replay",
        task_ids=[task["id"] for task in tasks],
        max_concurrency=3,
        max_tasks=4,
        timeout_seconds=30,
    )
    try:
        report = await runner.run(manifest)
    finally:
        await client.close()
    assert report["status"] == "completed"
    # Two research slots and one referee slot: the third root waits for a research slot,
    # while the referee starts beside the two running roots.
    assert sorted(name for name, _ in starts) == ["Root 0", "Root 1", "Root 2", "referee"]
    assert dict(starts)["referee"] == 2
    assert max(running for _, running in starts) <= 2


@pytest.mark.parametrize(("concurrency", "referee_slots"), [(1, 2), (2, 0)])
async def test_referee_slots_zero_or_concurrency_one_keep_the_shared_pool(
    lab, concurrency, referee_slots
):
    service, author, exp, branches, _ = society_lab(lab, referee_slots=referee_slots)
    tasks = roots(service, author, exp, branches, concurrency)
    route, starts = slot_route(service, author, exp, hold_seconds=0.3)
    runner, client = society_runner(service, route)
    manifest = run_manifest(exp, author, tasks[0]).model_copy(
        update={"task_ids": [task["id"] for task in tasks], "max_concurrency": concurrency}
    )
    try:
        report = await runner.run(manifest)
    finally:
        await client.close()
    assert report["status"] == "completed"
    # Roots fill every slot, so the referee starts only once one of them has ended.
    assert starts[-1][0] == "referee" and len(starts) == concurrency + 1
    assert dict(starts)["referee"] < concurrency


async def test_runner_task_limit_ignores_referee_attempts(lab):
    service, author, exp, branches, _ = society_lab(lab)
    (root,) = roots(service, author, exp, branches, 1)

    def root_steps(phase, outputs):
        if phase == 0:
            return [tool_call("commons_node", lemma_args(), "create-1")]
        if phase == 1:
            request = {"action": "request_review", "node_id": outputs[0]["id"]}
            return [tool_call("commons_node", request, "review-1")]
        return [message("Root done.")]

    route, phases = scripted_society_route(root_steps)
    runner, client = society_runner(service, route)
    try:
        report = await runner.run(
            run_manifest(exp, author, root).model_copy(update={"max_tasks": 1})
        )
    finally:
        await client.close()
    assert phases == {"root": 3, "referee": 2}
    assert report["status"] == "completed" and report["stop_reason"] is None
    (referee,) = [
        task
        for task in service.list_records("task", author, exp["id"])
        if task.get("review_assignment")
    ]
    assert referee["status"] == "completed"
