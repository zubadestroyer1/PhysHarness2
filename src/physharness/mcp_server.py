"""MCP tools backed by the same authenticated HTTP application services."""

import os
from urllib.parse import urlencode

from mcp.server.fastmcp import FastMCP

from .client import HarnessClient

mcp = FastMCP("PhysHarnessV2")


def call(method, path, body=None, operation_id=None):
    token = os.environ.get("PHYSHARNESS_TOKEN")
    if not token:
        raise RuntimeError(
            "PHYSHARNESS_TOKEN is required; no anonymous or privileged fallback exists"
        )
    connection = HarnessClient(os.environ.get("PHYSHARNESS_URL", "http://127.0.0.1:8000"), token)
    try:
        return connection.request(method, path, body, key=operation_id)
    finally:
        connection.close()


def _page(path, after=None, limit=20):
    return call(
        "GET",
        path + "?" + urlencode({"limit": limit, **({"after": after} if after is not None else {})}),
    )


@mcp.tool()
def configure_workforce(
    experiment_id: str,
    max_total_tasks: int,
    max_pending_tasks: int,
    operation_id: str,
    expected_revision: int | None = None,
    synthesis_interval_posts: int = 0,
) -> dict:
    """Set operator task caps and optional synthesis cadence within the experiment envelope."""
    return call(
        "POST",
        f"/v1/experiments/{experiment_id}/workforce",
        {
            "max_total_tasks": max_total_tasks,
            "max_pending_tasks": max_pending_tasks,
            "expected_revision": expected_revision,
            "synthesis_interval_posts": synthesis_interval_posts,
        },
        operation_id,
    )


@mcp.tool()
def seed_portfolio(experiment_id: str, roots: list[dict], operation_id: str) -> dict:
    """Atomically seed a bounded diverse root portfolio."""
    return call(
        "POST", f"/v1/experiments/{experiment_id}/portfolio", {"roots": roots}, operation_id
    )


@mcp.tool()
def recruit_researcher(
    experiment_id: str,
    parent_branch_id: str,
    title: str,
    objective: str,
    operation_id: str,
    relation: str = "collaborator",
    model_index: int | None = None,
    discussion_refs: list[str] | None = None,
    synthesis: bool = False,
    detached: bool = False,
    public_summary: str | None = None,
) -> dict:
    """Recruit a colleague or ordinary synthesis task under the original budget."""
    return call(
        "POST",
        f"/v1/experiments/{experiment_id}/recruit",
        {
            "parent_branch_id": parent_branch_id,
            "title": title,
            "objective": objective,
            "relation": relation,
            "model_index": model_index,
            "discussion_refs": discussion_refs or [],
            "synthesis": synthesis,
            "detached": detached,
            "public_summary": public_summary,
        },
        operation_id,
    )


@mcp.tool()
def publish_research_profile(
    experiment_id: str,
    branch_id: str,
    published: bool,
    operation_id: str,
    summary: str = "",
    interests: list[str] | None = None,
    assignment: str = "",
) -> dict:
    """Publish or withdraw a bounded opt-in research directory entry."""
    return call(
        "POST",
        f"/v1/experiments/{experiment_id}/research-profile",
        {
            "branch_id": branch_id,
            "published": published,
            "summary": summary,
            "interests": interests or [],
            "assignment": assignment,
        },
        operation_id,
    )


@mcp.tool()
def research_directory(experiment_id: str, after: str | None = None, limit: int = 20) -> dict:
    """Page explicitly published researcher summaries."""
    return _page(f"/v1/experiments/{experiment_id}/research-directory", after, limit)


@mcp.tool()
def join_research_team(
    experiment_id: str, branch_id: str, team: str, operation_id: str, joined: bool = True
) -> dict:
    """Join or leave a voluntary team label without changing data access."""
    return call(
        "POST",
        f"/v1/experiments/{experiment_id}/research-team",
        {"branch_id": branch_id, "team": team, "joined": joined},
        operation_id,
    )


@mcp.tool()
def research_capacity(experiment_id: str) -> dict:
    """Inspect queued work and current task caps."""
    return call("GET", f"/v1/experiments/{experiment_id}/research-capacity")


@mcp.tool()
def request_research_capacity(
    experiment_id: str, branch_id: str, requested_workers: int, rationale: str, operation_id: str
) -> dict:
    """Record a demand signal; it does not grant workers or funding."""
    return call(
        "POST",
        f"/v1/experiments/{experiment_id}/research-capacity-requests",
        {"branch_id": branch_id, "requested_workers": requested_workers, "rationale": rationale},
        operation_id,
    )


@mcp.tool()
def schedule_research_synthesis(experiment_id: str, operation_id: str) -> dict:
    """Ask the central scheduler for one eligible, attributed synthesis task."""
    return call(
        "POST", f"/v1/experiments/{experiment_id}/schedule-synthesis", operation_id=operation_id
    )


@mcp.tool()
def create_discussion(
    experiment_id: str, title: str, summary: str, operation_id: str, branch_id: str | None = None
) -> dict:
    """Open a scoped attributed research topic."""
    return call(
        "POST",
        f"/v1/experiments/{experiment_id}/discussions",
        {"title": title, "summary": summary, "branch_id": branch_id},
        operation_id,
    )


@mcp.tool()
def discussion_page(experiment_id: str, after: int | None = None, limit: int = 20) -> dict:
    """Page visible research topics."""
    return _page(f"/v1/experiments/{experiment_id}/discussions", after, limit)


@mcp.tool()
def post_discussion(
    topic_id: str,
    kind: str,
    content: str,
    operation_id: str,
    reply_to_post_id: str | None = None,
    artifact_ids: list[str] | None = None,
    reference_post_ids: list[str] | None = None,
) -> dict:
    """Post an unverified finding, question, objection or synthesis with references."""
    return call(
        "POST",
        f"/v1/discussions/{topic_id}/posts",
        {
            "kind": kind,
            "content": content,
            "reply_to_post_id": reply_to_post_id,
            "artifact_ids": artifact_ids or [],
            "reference_post_ids": reference_post_ids or [],
        },
        operation_id,
    )


@mcp.tool()
def discussion_posts(topic_id: str, after: int | None = None, limit: int = 20) -> dict:
    """Page exact posts and objections in a research topic."""
    return _page(f"/v1/discussions/{topic_id}/posts", after, limit)


@mcp.tool()
def read_discussion_post(post_id: str) -> dict:
    """Retrieve exact source text behind a delivery excerpt or synthesis reference."""
    return call("GET", f"/v1/discussion-posts/{post_id}")


@mcp.tool()
def read_research_message(message_id: str) -> dict:
    """Retrieve an exact addressed message behind a bounded delivery excerpt."""
    return call("GET", f"/v1/research-messages/{message_id}")


@mcp.tool()
def subscribe_discussion(topic_id: str, subscribed: bool, operation_id: str) -> dict:
    """Opt in or out of peer updates without changing access rights."""
    return call(
        "POST", f"/v1/discussions/{topic_id}/subscription", {"subscribed": subscribed}, operation_id
    )


@mcp.tool()
def discussion_updates(experiment_id: str, after: int | None = None, limit: int = 10) -> dict:
    """Read one durable bounded delivery, retried until acknowledged."""
    return _page(f"/v1/experiments/{experiment_id}/discussion-updates", after, limit)


@mcp.tool()
def acknowledge_discussion_updates(experiment_id: str, delivery_id: str, operation_id: str) -> dict:
    """Acknowledge a delivery after its content is durably retained."""
    return call(
        "POST",
        f"/v1/experiments/{experiment_id}/discussion-updates/{delivery_id}/ack",
        operation_id=operation_id,
    )


@mcp.tool()
def inspect_experiment(experiment_id: str) -> dict:
    """Read the pinned target, current experiment state and model/resource configuration."""
    return call("GET", f"/v1/experiments/{experiment_id}")


@mcp.tool()
def restart_brief(branch_id: str) -> dict:
    """Retrieve assumptions, evidence status, open obligations and history references."""
    return call("GET", f"/v1/branches/{branch_id}/restart-brief")


@mcp.tool()
def working_context(branch_id: str, task_id: str | None = None) -> dict:
    """Rebuild bounded canonical scientific context with paginated omissions."""
    return call(
        "GET",
        f"/v1/branches/{branch_id}/working-context" + (f"?task_id={task_id}" if task_id else ""),
    )


@mcp.tool()
def handoff_notes(branch_id: str, task_id: str | None = None) -> dict | None:
    """Read the latest attributed, unverified handoff notes for this branch and task."""
    return call(
        "GET",
        f"/v1/branches/{branch_id}/handoff-notes"
        + ("?" + urlencode({"task_id": task_id}) if task_id else ""),
    )


@mcp.tool()
def checkpoint_research_notes(
    branch_id: str,
    approach: str,
    unresolved_obligations: list[str],
    operation_id: str,
    summary: str | None = None,
    evidence_ids: list[str] | None = None,
    task_id: str | None = None,
    holder: str | None = None,
    fence: int | None = None,
) -> dict:
    """Persist bounded unverified scientific approach notes under a current task fence."""
    return call(
        "POST",
        f"/v1/branches/{branch_id}/research-notes",
        {
            "approach": approach,
            "unresolved_obligations": unresolved_obligations,
            "summary": summary,
            "evidence_ids": evidence_ids or [],
            "task_id": task_id,
            "holder": holder,
            "fence": fence,
        },
        operation_id,
    )


@mcp.tool()
def history_page(branch_id: str, kind: str, limit: int = 50, after: str | None = None) -> dict:
    """Page exact scoped record history with a bounded page size."""
    return call(
        "GET",
        f"/v1/branches/{branch_id}/history?"
        + urlencode({"kind": kind, "limit": limit, **({"after": after} if after else {})}),
    )


@mcp.tool()
def index_page(branch_id: str, index: str, limit: int = 50, after: str | None = None) -> dict:
    """Page one filtered scientific index, such as open tasks or failed attempts."""
    return call(
        "GET",
        f"/v1/branches/{branch_id}/index?"
        + urlencode({"index": index, "limit": limit, **({"after": after} if after else {})}),
    )


@mcp.tool()
def research_graph_page(branch_id: str, limit: int = 50, after: str | None = None) -> dict:
    """Page scoped explicit research relationships without inferring proof status."""
    return call(
        "GET",
        f"/v1/branches/{branch_id}/research-graph?"
        + urlencode({"limit": limit, **({"after": after} if after else {})}),
    )


@mcp.tool()
def read_scientific_record(branch_id: str, kind: str, identifier: str) -> dict:
    """Read one exact scoped scientific record."""
    return call("GET", f"/v1/branches/{branch_id}/records/{kind}/{identifier}")


@mcp.tool()
def read_artifact_chunk(branch_id: str, artifact_id: str, offset: int = 0) -> dict:
    """Read a bounded hash-checked artifact chunk."""
    return call("GET", f"/v1/branches/{branch_id}/artifacts/{artifact_id}/chunk?offset={offset}")


@mcp.tool()
def mailbox_page(branch_id: str, after: str | None = None) -> dict:
    """Read messages addressed to one branch; ideas remain unverified."""
    return call("GET", f"/v1/branches/{branch_id}/mailbox" + (f"?after={after}" if after else ""))


@mcp.tool()
def spawn_research(
    experiment_id: str,
    title: str,
    objective: str,
    relation: str,
    parent_id: str | None,
    operation_id: str,
) -> dict:
    """Create a helper, collaborator or competing branch."""
    return call(
        "POST",
        f"/v1/experiments/{experiment_id}/branches",
        {"title": title, "objective": objective, "relation": relation, "parent_id": parent_id},
        operation_id,
    )


@mcp.tool()
def delegate_task(
    branch_id: str,
    objective: str,
    dependency_ids: list[str],
    operation_id: str,
    detached: bool = False,
) -> dict:
    """Queue a joined subproblem, or explicitly detach independent work."""
    return call(
        "POST",
        "/v1/tasks",
        {
            "branch_id": branch_id,
            "objective": objective,
            "dependency_ids": dependency_ids,
            "detached": detached,
        },
        operation_id,
    )


@mcp.tool()
def joined_results(task_id: str) -> dict:
    """Read direct child outcomes with proof status separate from execution status."""
    return call("GET", f"/v1/tasks/{task_id}/joined-results")


@mcp.tool()
def publish_candidate(experiment_id: str, source: str, provenance: dict, operation_id: str) -> dict:
    """Store immutable Lean source. Publication here does not confer accepted proof status."""
    return call(
        "POST",
        "/v1/artifacts",
        {
            "experiment_id": experiment_id,
            "kind": "lean_source",
            "content": source,
            "provenance": provenance,
        },
        operation_id,
    )


@mcp.tool()
def submit_verification(experiment_id: str, artifact_id: str, operation_id: str) -> dict:
    """Queue independent checking of the exact reviewed target."""
    return call(
        "POST",
        f"/v1/experiments/{experiment_id}/verify",
        {"artifact_id": artifact_id, "publication": False},
        operation_id,
    )


@mcp.tool()
def submit_candidate_source(experiment_id: str, source: str, operation_id: str) -> dict:
    """Store exact Lean source and queue independent checking under one stable key."""
    return call(
        "POST",
        f"/v1/experiments/{experiment_id}/submit-candidate",
        {"source": source},
        operation_id,
    )


@mcp.tool()
def inspect_artifact(artifact_id: str) -> dict:
    """Read hash-checked artifact text within the current identity's scope."""
    return call("GET", f"/v1/artifacts/{artifact_id}/content")


@mcp.tool()
def read_dependency_bundle(experiment_id: str, claim_id: str) -> dict:
    """Get accepted source and provenance under the consuming experiment's information policy."""
    return call("GET", f"/v1/experiments/{experiment_id}/knowledge/{claim_id}/bundle")


def main():
    mcp.run()
