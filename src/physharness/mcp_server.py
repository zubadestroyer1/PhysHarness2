"""MCP tools backed by the same authenticated HTTP application services."""

import os

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


@mcp.tool()
def inspect_experiment(experiment_id: str) -> dict:
    """Read the pinned target, current experiment state and model/resource configuration."""
    return call("GET", f"/v1/experiments/{experiment_id}")


@mcp.tool()
def restart_brief(branch_id: str) -> dict:
    """Retrieve assumptions, evidence status, open obligations and history references."""
    return call("GET", f"/v1/branches/{branch_id}/restart-brief")


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
    branch_id: str, objective: str, dependency_ids: list[str], operation_id: str
) -> dict:
    """Queue an optional subproblem; dependencies express scheduling, not proof of implication."""
    return call(
        "POST",
        "/v1/tasks",
        {"branch_id": branch_id, "objective": objective, "dependency_ids": dependency_ids},
        operation_id,
    )


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
def inspect_artifact(artifact_id: str) -> dict:
    """Read hash-checked artifact text within the current identity's scope."""
    return call("GET", f"/v1/artifacts/{artifact_id}/content")


@mcp.tool()
def read_dependency_bundle(experiment_id: str, claim_id: str) -> dict:
    """Get accepted source and provenance under the consuming experiment's information policy."""
    return call("GET", f"/v1/experiments/{experiment_id}/knowledge/{claim_id}/bundle")


def main():
    mcp.run()
