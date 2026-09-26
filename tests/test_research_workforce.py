"""Synthetic service contracts for bounded research workforce commands."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from test_core import setup_experiment

from physharness.discussion_models import DiscussionCreate, DiscussionPostCreate
from physharness.domain import ArtifactCreate, BranchCreate, ExperimentCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.storage import LeaseRow
from physharness.worker_authority import worker_effects
from physharness.workforce_models import (
    ConfigureWorkforceRequest,
    JoinResearchTeamRequest,
    PortfolioRoot,
    PublishResearchProfileRequest,
    RecruitResearcherRequest,
    RequestResearchCapacityRequest,
    SeedPortfolioRequest,
)


def started(lab, sharing=None):
    service, researcher, _ = lab
    experiment, _ = setup_experiment(lab)
    if sharing:
        request = ExperimentCreate.model_validate(
            {k: experiment[k] for k in ("campaign_id", "problem_id", "models", "budget")}
        ).model_copy(update={"sharing": sharing})
        experiment = service.create_experiment(request, researcher, f"{sharing}-experiment")
    service.transition_experiment(experiment["id"], "start", 1, researcher, "start")
    operator = Principal(id="operator", project_id=researcher.project_id, role="operator")
    return service, researcher, operator, experiment


def test_queued_objective_amendment_is_revision_fenced_and_closes_on_lease(lab):
    service, researcher, operator, experiment = started(lab)
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Original"), researcher, "branch"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Original"), researcher, "task"
    )
    changed = service.amend_queued_task_objective(
        task["id"], task["revision"], "Current objective", operator, "amend"
    )
    assert changed["objective"] == "Current objective"
    assert changed["superseded_objectives"] == [
        {"revision": task["revision"], "objective": "Original"}
    ]
    assert (
        service.amend_queued_task_objective(
            task["id"], task["revision"], "Current objective", operator, "amend"
        )
        == changed
    )
    with pytest.raises(HarnessError) as stale:
        service.amend_queued_task_objective(
            task["id"], task["revision"], "Stale", operator, "stale"
        )
    assert stale.value.code == "REVISION_CONFLICT"
    service.acquire_task(task["id"], "worker", 60, operator, "lease")
    with pytest.raises(HarnessError) as leased:
        service.amend_queued_task_objective(
            task["id"], changed["revision"], "Too late", operator, "leased"
        )
    assert leased.value.code == "TASK_NOT_QUEUED"


def test_parent_worker_can_pivot_queued_private_child_without_result_access(lab):
    service, researcher, operator, experiment = started(lab)
    parent = service.create_branch(
        experiment["id"], BranchCreate(title="Parent", objective="Root"), researcher, "parent"
    )
    parent_task = service.create_task(
        TaskCreate(branch_id=parent["id"], objective="Root"), researcher, "parent-task"
    )
    child = service.create_branch(
        experiment["id"],
        BranchCreate(title="Child", objective="Old", parent_id=parent["id"]),
        researcher,
        "child",
    )
    lease = service.acquire_task(parent_task["id"], "holder", 60, operator, "lease-parent")
    agent = Principal(
        id="holder",
        project_id=researcher.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=parent["id"],
    )
    with worker_effects(agent, parent_task["id"], "holder", lease["fence"]):
        child_task = service.create_task(
            TaskCreate(branch_id=child["id"], objective="Old"), agent, "child-task"
        )
        with pytest.raises(HarnessError):
            service.get_record("task", child_task["id"], agent)
        changed = service.amend_queued_task_objective(
            child_task["id"], child_task["revision"], "Fresh", agent, "pivot"
        )
    assert changed["objective"] == "Fresh"
    assert "return_result" not in changed
    assert service.get_record("task", child_task["id"], operator)["objective"] == "Fresh"


def test_root_replan_limit_is_finite_and_cannot_be_attached_to_helper(lab):
    service, researcher, operator, experiment = started(lab)
    root = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Target"), researcher, "root"
    )
    root_task = service.create_task(
        TaskCreate(branch_id=root["id"], objective="Target"), researcher, "root-task"
    )
    configured = service.configure_root_replans(root_task["id"], 2, operator, "policy")
    assert configured["root_replan_limit"] == 2
    assert service.configure_root_replans(root_task["id"], 2, operator, "policy") == configured
    with pytest.raises(HarnessError) as changed:
        service.configure_root_replans(root_task["id"], 3, operator, "policy-changed")
    assert changed.value.code == "ROOT_REPLAN_POLICY_CONFLICT"
    helper = service.create_branch(
        experiment["id"],
        BranchCreate(title="Helper", objective="Part", parent_id=root["id"]),
        researcher,
        "helper",
    )
    child_task = service.create_task(
        TaskCreate(branch_id=helper["id"], objective="Part"), researcher, "helper-task"
    )
    with pytest.raises(HarnessError) as not_root:
        service.configure_root_replans(child_task["id"], 1, operator, "helper-policy")
    assert not_root.value.code == "ROOT_TASK_REQUIRED"


def test_verified_target_retires_only_queued_unleased_task(lab):
    service, researcher, operator, experiment = started(lab)
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="Root", objective="Target"), researcher, "root"
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Target"), researcher, "task"
    )
    with pytest.raises(HarnessError) as absent:
        service.retire_queued_after_verified(task["id"], "not-a-receipt", operator, "retire")
    assert absent.value.code == "TARGET_NOT_VERIFIED"
    assert service.get_record("task", task["id"], operator)["status"] == "queued"


def test_seed_is_atomic_idempotent_and_legacy_task_path_obeys_cap(lab):
    service, researcher, operator, experiment = started(lab)
    service.configure_workforce(
        experiment["id"],
        ConfigureWorkforceRequest(
            max_total_tasks=2,
            max_pending_tasks=2,
        ),
        operator,
        "configure",
    )
    roots = SeedPortfolioRequest(
        roots=[
            PortfolioRoot(title="A", objective="Try A", public_summary="Exploring A"),
            PortfolioRoot(title="B", objective="Try B", public_summary="Exploring B"),
        ]
    )
    first = service.seed_portfolio(experiment["id"], roots, operator, "seed")
    assert service.seed_portfolio(experiment["id"], roots, operator, "seed") == first
    assert len(first["roots"]) == 2
    assert service.research_capacity(experiment["id"], operator)["queued_tasks"] == 2
    with pytest.raises(HarnessError) as error:
        service.seed_portfolio(
            experiment["id"],
            SeedPortfolioRequest(
                roots=[
                    PortfolioRoot(title="Changed", objective="Changed"),
                ]
            ),
            operator,
            "seed",
        )
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(HarnessError) as error:
        service.create_task(
            TaskCreate(
                branch_id=first["roots"][0]["branch"]["id"],
                objective="Overflow",
            ),
            researcher,
            "overflow",
        )
    assert error.value.code == "TASK_TOTAL_CAP"
    assert len(service.list_records("task", operator, experiment["id"])) == 2


def test_invalid_second_root_rolls_back_first_root_and_task(lab):
    service, _, operator, experiment = started(lab)
    with pytest.raises(HarnessError) as error:
        service.seed_portfolio(
            experiment["id"],
            SeedPortfolioRequest(
                roots=[
                    PortfolioRoot(title="Valid", objective="Valid"),
                    PortfolioRoot(title="Invalid", objective="Invalid", model_index=1),
                ]
            ),
            operator,
            "bad-seed",
        )
    assert error.value.code == "MODEL_NOT_ALLOWED"
    assert service.list_records("branch", operator, experiment["id"]) == []
    assert service.list_records("task", operator, experiment["id"]) == []


def test_recruit_directory_teams_and_capacity_demand_are_scoped(lab):
    # Cross-branch directory discovery exists only under ideas sharing.
    service, _, operator, experiment = started(lab, "ideas")
    roots = service.seed_portfolio(
        experiment["id"],
        SeedPortfolioRequest(
            roots=[
                PortfolioRoot(
                    title="Private objective",
                    objective="Private objective",
                    public_summary="Published interests",
                ),
                PortfolioRoot(title="Other private", objective="Other private"),
            ],
        ),
        operator,
        "seed",
    )["roots"]
    root = roots[0]
    branch_id = root["branch"]["id"]
    agent = Principal(
        id="agent",
        project_id=operator.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=branch_id,
    )
    page = service.research_directory(experiment["id"], agent)
    assert page["items"][0]["summary"] == "Published interests"
    assert "Private objective" not in str(page)
    service.join_research_team(
        experiment["id"],
        JoinResearchTeamRequest(
            branch_id=branch_id,
            team="geometry",
        ),
        agent,
        "join",
    )
    directory = service.research_directory(experiment["id"], agent)
    assert directory["items"][0]["teams"] == ["geometry"]
    assert directory["teams"] == [{"name": "geometry", "member_count": 1}]
    service.join_research_team(
        experiment["id"],
        JoinResearchTeamRequest(
            branch_id=branch_id,
            team="geometry",
            joined=False,
        ),
        agent,
        "leave",
    )
    assert service.research_directory(experiment["id"], agent)["items"][0]["teams"] == []
    assert service.research_directory(experiment["id"], agent)["teams"] == []
    demand = service.request_research_capacity(
        experiment["id"],
        RequestResearchCapacityRequest(
            branch_id=branch_id, requested_workers=8, rationale="More independent checks"
        ),
        agent,
        "demand",
    )
    assert demand["granted_workers"] == 0
    capacity = service.research_capacity(experiment["id"], agent)
    assert capacity["active_workers"] == 0
    assert capacity["max_concurrency"] == 2
    assert capacity["requests"][0]["requested_workers"] == 8
    other = Principal(
        id="other",
        project_id=operator.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=roots[1]["branch"]["id"],
    )
    assert (
        service.research_directory(experiment["id"], other)["items"][0]["summary"]
        == "Published interests"
    )
    assert service.research_capacity(experiment["id"], other)["requests"] == []
    for kind, identifier in (
        ("workforce_capacity_request", demand["id"]),
        ("workforce_profile", page["items"][0]["profile_id"]),
    ):
        with pytest.raises(HarnessError) as error:
            service.get_record(kind, identifier, other)
        assert error.value.code == "NOT_FOUND"


def test_recruit_preserves_parent_and_publication_is_opt_in(lab):
    service, _, operator, experiment = started(lab, "ideas")
    root = service.seed_portfolio(
        experiment["id"],
        SeedPortfolioRequest(
            roots=[
                PortfolioRoot(title="Root", objective="Root private objective"),
            ]
        ),
        operator,
        "seed",
    )["roots"][0]
    agent = Principal(
        id="agent",
        project_id=operator.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=root["branch"]["id"],
    )
    assert service.research_directory(experiment["id"], agent)["items"] == []
    service.publish_research_profile(
        experiment["id"],
        PublishResearchProfileRequest(
            branch_id=agent.branch_id,
            published=True,
            summary="Open to collaboration",
        ),
        agent,
        "publish",
    )
    child = service.recruit_researcher(
        experiment["id"],
        RecruitResearcherRequest(
            parent_branch_id=agent.branch_id,
            title="Child",
            objective="Child objective",
            public_summary="Help with a subproblem",
            detached=True,
        ),
        agent,
        "recruit",
    )
    assert child["branch"]["parent_id"] == agent.branch_id
    assert child["task"]["branch_id"] == child["branch"]["id"]
    page = service.research_directory(experiment["id"], agent)
    assert {item["summary"] for item in page["items"]} == {
        "Open to collaboration",
        "Help with a subproblem",
    }
    assert "Child objective" not in str(page)


def test_cross_topic_synthesis_queues_ordinary_task_once(lab):
    service, researcher, operator, original = started(lab)
    request = ExperimentCreate.model_validate(
        {k: original[k] for k in ("campaign_id", "problem_id", "models", "budget")}
    ).model_copy(update={"sharing": "ideas"})
    experiment = service.create_experiment(request, researcher, "ideas-experiment")
    service.transition_experiment(experiment["id"], "start", 1, researcher, "ideas-start")
    roots = service.seed_portfolio(
        experiment["id"],
        SeedPortfolioRequest(
            roots=[
                PortfolioRoot(title="A", objective="Approach A"),
                PortfolioRoot(title="B", objective="Approach B"),
            ]
        ),
        operator,
        "ideas-seed",
    )["roots"]
    service.configure_workforce(
        experiment["id"],
        ConfigureWorkforceRequest(
            max_total_tasks=4,
            max_pending_tasks=4,
            synthesis_interval_posts=4,
        ),
        operator,
        "ideas-configure",
    )
    agents = [
        Principal(
            id=f"agent-{index}",
            project_id=operator.project_id,
            role="agent",
            experiment_id=experiment["id"],
            branch_id=root["branch"]["id"],
        )
        for index, root in enumerate(roots)
    ]
    topics = [
        service.create_discussion(
            experiment["id"],
            DiscussionCreate(title=f"Topic {index}", summary="Public research question"),
            agent,
            f"topic-{index}",
        )
        for index, agent in enumerate(agents)
    ]
    for index in range(4):
        service.post_discussion(
            topics[index % 2]["id"],
            DiscussionPostCreate(
                kind="finding" if index < 2 else "objection",
                content=f"Post {index}",
            ),
            agents[index % 2],
            f"post-{index}",
        )
    result = service.schedule_research_synthesis(experiment["id"], operator, "synthesize")
    assert result["scheduled"] is True
    assert len(result["source_post_ids"]) == 4
    assert len(result["source_topic_ids"]) == 2
    assert result["task"]["synthesis"] is True
    assert result["task"]["status"] == "queued"
    assert result["task"]["discussion_refs"] == result["source_post_ids"]
    assert result["branch"]["parent_id"] in {root["branch"]["id"] for root in roots}
    assert service.schedule_research_synthesis(experiment["id"], operator, "synthesize") == result
    pending = service.schedule_research_synthesis(experiment["id"], operator, "synthesize-next")
    assert pending == {"scheduled": False, "reason": "outstanding", "task_id": result["task"]["id"]}


def test_profile_withdrawal_hides_directory_entry(lab):
    service, _, operator, experiment = started(lab)
    branch = service.seed_portfolio(
        experiment["id"],
        SeedPortfolioRequest(
            roots=[
                PortfolioRoot(title="Root", objective="Objective", public_summary="Public"),
            ]
        ),
        operator,
        "seed",
    )["roots"][0]["branch"]
    service.publish_research_profile(
        experiment["id"],
        PublishResearchProfileRequest(
            branch_id=branch["id"],
            published=False,
        ),
        operator,
        "withdraw",
    )
    assert service.research_directory(experiment["id"], operator)["items"] == []


def test_concurrent_last_slot_and_same_key_are_serialized(lab):
    service, _, operator, experiment = started(lab)
    service.configure_workforce(
        experiment["id"],
        ConfigureWorkforceRequest(
            max_total_tasks=2,
            max_pending_tasks=2,
        ),
        operator,
        "cap",
    )
    root = service.seed_portfolio(
        experiment["id"],
        SeedPortfolioRequest(
            roots=[
                PortfolioRoot(title="First", objective="First"),
            ]
        ),
        operator,
        "seed",
    )["roots"][0]
    request = RecruitResearcherRequest(
        parent_branch_id=root["branch"]["id"], title="Next", objective="Next"
    )

    def attempt(key):
        try:
            return service.recruit_researcher(experiment["id"], request, operator, key)
        except HarnessError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["one", "two"]))
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    assert "TASK_TOTAL_CAP" in outcomes
    assert len(service.list_records("task", operator, experiment["id"])) == 2
    winner_key = "one" if isinstance(outcomes[0], dict) else "two"
    with ThreadPoolExecutor(max_workers=2) as pool:
        duplicate = list(pool.map(attempt, [winner_key, winner_key]))
    assert duplicate[0] == duplicate[1] == outcomes[0 if winner_key == "one" else 1]


def test_recruited_children_preserve_join_and_detached_lineage_and_fence(lab):
    service, _, operator, experiment = started(lab)
    root = service.seed_portfolio(
        experiment["id"],
        SeedPortfolioRequest(
            roots=[
                PortfolioRoot(title="Parent", objective="Parent"),
            ]
        ),
        operator,
        "seed",
    )["roots"][0]
    lease = service.acquire_task(root["task"]["id"], "holder", 60, operator, "lease")
    agent = Principal(
        id="holder",
        project_id=operator.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=root["branch"]["id"],
    )
    with worker_effects(agent, root["task"]["id"], "holder", lease["fence"]):
        joined = service.recruit_researcher(
            experiment["id"],
            RecruitResearcherRequest(
                parent_branch_id=agent.branch_id,
                title="Joined",
                objective="Joined",
            ),
            agent,
            "joined",
        )
        detached = service.recruit_researcher(
            experiment["id"],
            RecruitResearcherRequest(
                parent_branch_id=agent.branch_id,
                title="Detached",
                objective="Detached",
                detached=True,
            ),
            agent,
            "detached",
        )
    assert joined["task"]["reply_to_parent_task_id"] == root["task"]["id"]
    assert joined["task"]["delegated_from_task_id"] == root["task"]["id"]
    assert detached["task"]["reply_to_parent_task_id"] is None
    assert detached["task"]["delegated_from_task_id"] == root["task"]["id"]
    with service.db.transaction() as session:
        session.get(LeaseRow, root["task"]["id"]).expires_at = 0
    replacement = service.acquire_task(root["task"]["id"], "next", 60, operator, "next-lease")
    assert replacement["fence"] > lease["fence"]
    with worker_effects(agent, root["task"]["id"], "holder", lease["fence"]):
        with pytest.raises(HarnessError) as error:
            service.recruit_researcher(
                experiment["id"],
                RecruitResearcherRequest(
                    parent_branch_id=agent.branch_id,
                    title="Stale",
                    objective="Stale",
                ),
                agent,
                "stale",
            )
    assert error.value.code == "STALE_LEASE"
    assert len(service.list_records("branch", operator, experiment["id"])) == 3


def test_cross_experiment_discussion_reference_is_rejected(lab):
    service, researcher, operator, original = started(lab)
    parent = service.seed_portfolio(
        original["id"],
        SeedPortfolioRequest(
            roots=[
                PortfolioRoot(title="Parent", objective="Parent"),
            ]
        ),
        operator,
        "seed",
    )["roots"][0]
    request = ExperimentCreate.model_validate(
        {k: original[k] for k in ("campaign_id", "problem_id", "models", "budget")}
    ).model_copy(update={"sharing": "ideas"})
    other = service.create_experiment(request, researcher, "other-experiment")
    service.transition_experiment(other["id"], "start", 1, researcher, "other-start")
    topic = service.create_discussion(
        other["id"],
        DiscussionCreate(title="Other", summary="Other experiment"),
        researcher,
        "other-topic",
    )
    post = service.post_discussion(
        topic["id"],
        DiscussionPostCreate(kind="finding", content="Other source"),
        researcher,
        "other-post",
    )
    with pytest.raises(HarnessError) as error:
        service.recruit_researcher(
            original["id"],
            RecruitResearcherRequest(
                parent_branch_id=parent["branch"]["id"],
                title="Bad",
                objective="Bad",
                discussion_refs=[post["id"]],
                synthesis=True,
            ),
            operator,
            "bad-reference",
        )
    assert error.value.code == "DISCUSSION_SCOPE"
    assert len(service.list_records("task", operator, original["id"])) == 1


def test_synthesis_scans_long_single_topic_backlog_without_losing_dissent(lab):
    service, researcher, operator, original = started(lab)
    request = ExperimentCreate.model_validate(
        {k: original[k] for k in ("campaign_id", "problem_id", "models", "budget")}
    ).model_copy(update={"sharing": "ideas"})
    experiment = service.create_experiment(request, researcher, "backlog-experiment")
    service.transition_experiment(experiment["id"], "start", 1, researcher, "backlog-start")
    branches = service.seed_portfolio(
        experiment["id"],
        SeedPortfolioRequest(
            roots=[
                PortfolioRoot(title="A", objective="A"),
                PortfolioRoot(title="B", objective="B"),
            ]
        ),
        operator,
        "backlog-seed",
    )["roots"]
    service.configure_workforce(
        experiment["id"],
        ConfigureWorkforceRequest(
            max_total_tasks=4,
            max_pending_tasks=4,
            synthesis_interval_posts=4,
        ),
        operator,
        "backlog-policy",
    )
    agents = [
        Principal(
            id=f"backlog-{index}",
            project_id=operator.project_id,
            role="agent",
            experiment_id=experiment["id"],
            branch_id=branch["branch"]["id"],
        )
        for index, branch in enumerate(branches)
    ]
    topics = [
        service.create_discussion(
            experiment["id"],
            DiscussionCreate(title=f"Backlog {index}", summary="Research topic"),
            agent,
            f"backlog-topic-{index}",
        )
        for index, agent in enumerate(agents)
    ]
    for index in range(105):
        service.post_discussion(
            topics[0]["id"],
            DiscussionPostCreate(kind="finding", content=f"Same topic {index}"),
            agents[0],
            f"backlog-{index}",
        )
    first = service.schedule_research_synthesis(experiment["id"], operator, "scan-1")
    assert first["scheduled"] is False
    assert first["reason"] == "single_topic"
    assert first["eligible_posts"] == 100
    service.post_discussion(
        topics[1]["id"],
        DiscussionPostCreate(kind="objection", content="Dissenting interpretation"),
        agents[1],
        "dissent",
    )
    second = service.schedule_research_synthesis(experiment["id"], operator, "scan-2")
    assert second["scheduled"] is True
    assert second["eligible_post_count"] == 106
    assert second["sampled_post_count"] == 20
    assert second["task"]["synthesis_scope"] == {
        "coverage": "bounded_sample",
        "eligible_post_count": 106,
        "sampled_post_count": 20,
        "through_sequence": second["through_sequence"],
    }
    assert second["source_topic_ids"] == sorted([topic["id"] for topic in topics])
    assert service.schedule_research_synthesis(experiment["id"], operator, "scan-2") == second


def test_direct_message_rejects_attachment_recipient_cannot_read(lab):
    from test_sharing import approaches

    service, author, experiment, branches, (alpha, beta) = approaches(lab, "ideas")
    secret = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            kind="checkpoint",
            content="private state",
        ),
        alpha,
        "private-checkpoint",
    )
    with pytest.raises(HarnessError) as error:
        service.send_message(
            branches[0]["id"], branches[1]["id"], "Try this", [secret["id"]], alpha, "poison"
        )
    assert error.value.code == "MESSAGE_ATTACHMENT_INACCESSIBLE"
    assert secret["id"] not in str(error.value)
    assert service.list_records("message", author, experiment["id"]) == []
    assert service.discussion_updates(experiment["id"], beta)["items"] == []


def test_auto_return_omits_private_attachment_without_poisoning_parent(lab):
    from test_sharing import approaches

    service, author, experiment, branches, (parent_agent, _) = approaches(lab, "ideas")
    controller = Principal(id="controller", project_id=author.project_id, role="operator")
    parent = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Parent"), author, "parent-task"
    )
    parent_lease = service.acquire_task(
        parent["id"], "parent-holder", 60, controller, "parent-lease"
    )
    with worker_effects(parent_agent, parent["id"], "parent-holder", parent_lease["fence"]):
        child_branch = service.create_branch(
            experiment["id"],
            BranchCreate(
                title="Child",
                objective="Child",
                parent_id=branches[0]["id"],
            ),
            parent_agent,
            "child-branch",
        )
        child = service.create_task(
            TaskCreate(branch_id=child_branch["id"], objective="Child"), parent_agent, "child-task"
        )
    child_agent = Principal(
        id="child-holder",
        project_id=author.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=child_branch["id"],
    )
    private = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            kind="checkpoint",
            content="private state",
        ),
        child_agent,
        "child-checkpoint",
    )
    child_lease = service.acquire_task(child["id"], "child-holder", 60, controller, "child-lease")
    service.finish_task(
        child["id"],
        "child-holder",
        child_lease["fence"],
        [private["id"]],
        "completed",
        controller,
        "finish-child",
    )
    messages = service.list_records("message", controller, experiment["id"])
    assert len(messages) == 1
    assert messages[0]["artifact_ids"] == []
    assert private["id"] not in messages[0]["content"]
    assert "attachments_omitted_for_recipient" in messages[0]["content"]
    updates = service.discussion_updates(experiment["id"], parent_agent)
    assert updates["items"]


@pytest.mark.parametrize("sharing", ["none", "verified"])
def test_directory_profiles_and_teams_stay_in_branch_without_ideas_sharing(lab, sharing):
    from test_sharing import approaches

    service, author, experiment, _, (alpha, beta) = approaches(lab, sharing)
    operator = Principal(id="operator", project_id=author.project_id, role="operator")
    secret = "Key step: use Gronwall on E(t); energy_bound closes goal 3"
    service.publish_research_profile(
        experiment["id"],
        PublishResearchProfileRequest(
            branch_id=alpha.branch_id,
            published=True,
            summary=secret,
            interests=["energy estimates"],
            assignment="Close goal 3",
        ),
        alpha,
        "publish",
    )
    service.join_research_team(
        experiment["id"],
        JoinResearchTeamRequest(branch_id=alpha.branch_id, team="hint: try Gronwall"),
        alpha,
        "alpha-team",
    )
    service.join_research_team(
        experiment["id"],
        JoinResearchTeamRequest(branch_id=beta.branch_id, team="analysis"),
        beta,
        "beta-team",
    )
    peer = service.research_directory(experiment["id"], beta)
    assert peer["items"] == []
    assert peer["teams"] == [{"name": "analysis", "member_count": 1}]
    assert "Gronwall" not in str(peer) and "goal 3" not in str(peer)
    own = service.research_directory(experiment["id"], alpha)
    assert [item["summary"] for item in own["items"]] == [secret]
    assert own["items"][0]["teams"] == ["hint: try Gronwall"]
    assert own["teams"] == [{"name": "hint: try Gronwall", "member_count": 1}]
    project = service.research_directory(experiment["id"], operator)
    assert [item["summary"] for item in project["items"]] == [secret]
    assert {team["name"] for team in project["teams"]} == {"analysis", "hint: try Gronwall"}


def test_branchless_first_post_does_not_stall_automatic_synthesis(lab):
    from test_sharing import approaches

    service, author, experiment, _, (alpha, beta) = approaches(lab, "ideas")
    operator = Principal(id="operator", project_id=author.project_id, role="operator")
    service.configure_workforce(
        experiment["id"],
        ConfigureWorkforceRequest(
            max_total_tasks=10, max_pending_tasks=10, synthesis_interval_posts=4
        ),
        operator,
        "policy",
    )
    kickoff = service.create_discussion(
        experiment["id"], DiscussionCreate(title="Kickoff", summary="Welcome"), operator, "k"
    )
    welcome = service.post_discussion(
        kickoff["id"], DiscussionPostCreate(kind="update", content="Welcome all"), operator, "kp"
    )
    assert welcome["branch_id"] is None
    topics = [
        service.create_discussion(
            experiment["id"], DiscussionCreate(title=name, summary=name), agent, name
        )
        for name, agent in (("A", alpha), ("B", beta))
    ]
    for index in range(4):
        service.post_discussion(
            topics[index % 2]["id"],
            DiscussionPostCreate(kind="finding", content=f"Post {index}"),
            (alpha, beta)[index % 2],
            f"post-{index}",
        )
    result = service.schedule_research_synthesis(experiment["id"], operator, "tick-1")
    assert result["scheduled"] is True
    assert result["parent_branch_id"] == alpha.branch_id
    assert welcome["id"] not in result["source_post_ids"]
    assert result["branch"]["parent_id"] == alpha.branch_id


def test_branchless_posts_alone_advance_synthesis_watermark(lab):
    from test_sharing import approaches

    service, author, experiment, _, (alpha, beta) = approaches(lab, "ideas")
    operator = Principal(id="operator", project_id=author.project_id, role="operator")
    service.configure_workforce(
        experiment["id"],
        ConfigureWorkforceRequest(
            max_total_tasks=10, max_pending_tasks=10, synthesis_interval_posts=4
        ),
        operator,
        "policy",
    )
    topics = [
        service.create_discussion(
            experiment["id"], DiscussionCreate(title=name, summary=name), operator, name
        )
        for name in ("Kickoff", "Logistics")
    ]
    for index in range(20):
        service.post_discussion(
            topics[index % 2]["id"],
            DiscussionPostCreate(kind="update", content=f"Notice {index}"),
            operator,
            f"notice-{index}",
        )
    first = service.schedule_research_synthesis(experiment["id"], operator, "tick-1")
    assert first["scheduled"] is False
    agent_topic = service.create_discussion(
        experiment["id"], DiscussionCreate(title="A", summary="A"), alpha, "a"
    )
    other_topic = service.create_discussion(
        experiment["id"], DiscussionCreate(title="B", summary="B"), beta, "b"
    )
    for index in range(4):
        service.post_discussion(
            (agent_topic, other_topic)[index % 2]["id"],
            DiscussionPostCreate(kind="finding", content=f"Post {index}"),
            (alpha, beta)[index % 2],
            f"post-{index}",
        )
    second = service.schedule_research_synthesis(experiment["id"], operator, "tick-2")
    assert second["scheduled"] is True
    assert second["eligible_post_count"] == 4
    assert second["through_sequence"] > first["through_sequence"]
