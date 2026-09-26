"""Scoped research-network tools and durable Responses update hooks."""

from __future__ import annotations

from pydantic import ValidationError

from ..discussion_models import DiscussionCreate, DiscussionPostCreate
from ..errors import HarnessError
from ..worker_authority import worker_effects
from ..workforce_models import (
    JoinResearchTeamRequest,
    PublishResearchProfileRequest,
    RecruitResearcherRequest,
    RequestResearchCapacityRequest,
)

STRING = {"type": "string"}
NULLABLE_STRING = {"type": ["string", "null"]}
STRING_LIST = {"type": "array", "items": STRING}
DISCUSSION_PAGE = {
    "after": {"type": ["integer", "null"], "minimum": 0},
    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
}
UPDATE_PAGE = {
    "after": {"type": ["integer", "null"], "minimum": 0},
    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
}
DIRECTORY_PAGE = {
    "after": NULLABLE_STRING,
    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
}
TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "blocked"})


def root_lineage(branch_id: str, parents: dict[str, str | None]) -> str:
    """Find a stable exploration root; malformed ancestry fails closed."""
    visited = set()
    current = branch_id
    while True:
        if current in visited or current not in parents:
            raise ValueError("Branch ancestry is missing or cyclic")
        visited.add(current)
        parent = parents[current]
        if parent is None:
            return current
        current = parent


def _task_age(task):
    # Canonical task pages sort by UUID. Their order is unrelated to age.
    # Equal timestamps break by task ID; older in-memory callers without
    # timestamps retain their input order.
    created_at = task.get("created_at")
    return (created_at, task["id"]) if created_at else ("", "")


def fair_ready_order(tasks: list[dict], parents: dict[str, str | None], last_lineage=None):
    """Round robin over roots, FIFO by creation time within each root.

    Only ready tasks take a turn. Settled tasks lead so callers can record
    them, and tasks with an unfinished listed dependency trail, so neither a
    long history nor blocked work pushes a root's oldest ready task back.
    """
    states = {task["id"]: task.get("status") for task in tasks}
    settled, blocked, groups = [], [], {}
    for task in sorted(tasks, key=_task_age):
        # Every root keeps its rotation position, even with no ready task now.
        group = groups.setdefault(root_lineage(task["branch_id"], parents), [])
        if task.get("status") in TERMINAL_TASK_STATUSES:
            settled.append(task)
        elif any(
            dependency in states and states[dependency] != "completed"
            for dependency in task.get("dependency_ids", [])
        ):
            blocked.append(task)
        else:
            group.append(task)
    lineages = sorted(groups)
    if last_lineage in lineages:
        pivot = lineages.index(last_lineage) + 1
        lineages = lineages[pivot:] + lineages[:pivot]
    ordered = settled
    while any(groups.values()):
        for lineage in lineages:
            if groups[lineage]:
                ordered.append(groups[lineage].pop(0))
    return ordered + blocked


def _tool_request(model, args):
    """Model-supplied out-of-bounds fields are a recoverable tool rejection, not a failed call."""
    try:
        return model(**args)
    except ValidationError as error:
        fields = [
            {"location": list(item["loc"]), "type": item["type"], "message": item["msg"][:200]}
            for item in error.errors(include_url=False, include_input=False)[:10]
        ]
        raise HarnessError(
            "VALIDATION_ERROR",
            "The tool arguments do not match the request contract.",
            status=422,
            details={"fields": fields},
            remediation="Correct the listed fields within their documented bounds.",
        ) from None


def register_network_tools(register, service, agent, branch_id):
    """All handlers share the canonical service, scope and command journal."""
    experiment_id = agent.experiment_id

    register(
        "create_discussion",
        {"title": STRING, "summary": STRING, "branch_id": NULLABLE_STRING},
        lambda a, k: service.create_discussion(
            experiment_id, _tool_request(DiscussionCreate, a), agent, k
        ),
        "Open an attributed research topic. Only explicitly shared ideas are visible.",
    )
    register(
        "post_discussion",
        {
            "topic_id": STRING,
            "kind": {
                "type": "string",
                "enum": ["question", "finding", "objection", "help", "update", "synthesis"],
            },
            "content": STRING,
            "reply_to_post_id": NULLABLE_STRING,
            "artifact_ids": STRING_LIST,
            "reference_post_ids": STRING_LIST,
        },
        lambda a, k: service.post_discussion(
            a["topic_id"],
            _tool_request(
                DiscussionPostCreate, {key: value for key, value in a.items() if key != "topic_id"}
            ),
            agent,
            k,
        ),
        "Post an unverified finding, question or objection with exact evidence references.",
    )
    register(
        "discussion_page",
        DISCUSSION_PAGE,
        lambda a, k: service.discussion_page(experiment_id, agent, **a),
        "Discover visible topics with stable pagination.",
    )
    register(
        "discussion_posts",
        {"topic_id": STRING, **DISCUSSION_PAGE},
        lambda a, k: service.discussion_posts(
            a["topic_id"], agent, after=a["after"], limit=a["limit"]
        ),
        "Read exact attributed posts and objections before using a summary.",
    )
    register(
        "read_discussion_post",
        {"post_id": STRING},
        lambda a, k: service.read_discussion_post(a["post_id"], agent),
        "Retrieve the exact full post behind a bounded delivery excerpt or synthesis reference.",
    )
    register(
        "read_research_message",
        {"message_id": STRING},
        lambda a, k: service.read_research_message(a["message_id"], agent),
        "Retrieve the exact addressed message behind a bounded delivery excerpt.",
    )
    register(
        "subscribe_discussion",
        {"topic_id": STRING, "subscribed": {"type": "boolean"}},
        lambda a, k: service.subscribe_discussion(a["topic_id"], a["subscribed"], agent, k),
        "Opt in or out of bounded peer updates; subscription gives no extra access.",
    )
    register(
        "discussion_updates",
        UPDATE_PAGE,
        lambda a, k: service.discussion_updates(experiment_id, agent, **a),
        "Read a bounded durable delivery. Exact post IDs remain available.",
    )
    register(
        "acknowledge_discussion_updates",
        {"delivery_id": STRING},
        lambda a, k: service.acknowledge_discussion_updates(
            experiment_id, a["delivery_id"], agent, k
        ),
        "Acknowledge a delivery only after its content has been read.",
    )
    register(
        "recruit_researcher",
        {
            "parent_branch_id": STRING,
            "title": STRING,
            "objective": STRING,
            "relation": {"type": "string", "enum": ["helper", "collaborator", "competing"]},
            "model_index": {"type": ["integer", "null"], "minimum": 0, "maximum": 99},
            "discussion_refs": STRING_LIST,
            "synthesis": {"type": "boolean"},
            "detached": {"type": "boolean"},
            "public_summary": NULLABLE_STRING,
        },
        lambda a, k: service.recruit_researcher(
            experiment_id, _tool_request(RecruitResearcherRequest, a), agent, k
        ),
        "Queue an optional colleague or attributed synthesis under the original budget. "
        "No fixed mathematical role is required.",
    )
    register(
        "publish_research_profile",
        {
            "branch_id": STRING,
            "published": {"type": "boolean"},
            "summary": STRING,
            "interests": STRING_LIST,
            "assignment": STRING,
        },
        lambda a, k: service.publish_research_profile(
            experiment_id, _tool_request(PublishResearchProfileRequest, a), agent, k
        ),
        "Opt in to a bounded public directory summary; private task data stays private.",
    )
    register(
        "research_directory",
        DIRECTORY_PAGE,
        lambda a, k: service.research_directory(experiment_id, agent, **a),
        "Discover opted-in researchers and public interests.",
    )
    register(
        "register_component",
        {
            "component_key": STRING,
            "statement": STRING,
            "owner_task_id": STRING,
            "artifact_ids": STRING_LIST,
            "expected_revision": {"type": ["integer", "null"], "minimum": 1},
        },
        lambda a, k: service.register_component(
            experiment_id,
            a["component_key"],
            a["statement"],
            a["owner_task_id"],
            a["artifact_ids"],
            agent,
            k,
            expected_revision=a["expected_revision"],
        ),
        "Publish a bounded component statement, owner and evidence references so peers can "
        "see overlap. This registry does not certify proof.",
    )
    register(
        "component_directory",
        DIRECTORY_PAGE,
        lambda a, k: service.component_directory(experiment_id, agent, **a),
        "See overlapping component owners and whether their tasks are queued, running or stale.",
    )
    register(
        "join_research_team",
        {"branch_id": STRING, "team": STRING, "joined": {"type": "boolean"}},
        lambda a, k: service.join_research_team(
            experiment_id, _tool_request(JoinResearchTeamRequest, a), agent, k
        ),
        "Join or leave a voluntary team label. It grants no access or proof authority.",
    )
    register(
        "research_capacity",
        {},
        lambda a, k: service.research_capacity(experiment_id, agent),
        "Inspect queued work and available capacity under the existing envelope.",
    )
    register(
        "request_research_capacity",
        {
            "branch_id": STRING,
            "requested_workers": {"type": "integer", "minimum": 1},
            "rationale": STRING,
        },
        lambda a, k: service.request_research_capacity(
            experiment_id, _tool_request(RequestResearchCapacityRequest, a), agent, k
        ),
        "Record a demand signal for the scheduler; this does not grant workers or money.",
    )


def discussion_delivery_hooks(service, agent, task_id, holder, fence):
    """The runtime persists each returned batch before calling the acknowledgement."""

    def check_fence():
        with service.db.sessions() as session:
            service._active(session, agent.experiment_id, agent)
            service._fenced(session, task_id, holder, fence)

    async def source(checkpoint):
        check_fence()
        with worker_effects(agent, task_id, holder, fence):
            return service.discussion_updates(agent.experiment_id, agent, limit=10)

    async def acknowledge(delivery_id):
        check_fence()
        with worker_effects(agent, task_id, holder, fence):
            service.acknowledge_discussion_updates(
                agent.experiment_id,
                delivery_id,
                agent,
                f"native-update-ack:{task_id}:{delivery_id}",
            )

    return source, acknowledge
