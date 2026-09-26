"""Versioned client. Transport failures preserve uncertain mutation identity for reconciliation."""

from typing import Any

import httpx

from .discussion_models import DiscussionCreate, DiscussionPostCreate
from .errors import HarnessError
from .workforce_models import (
    ConfigureWorkforceRequest,
    JoinResearchTeamRequest,
    PublishResearchProfileRequest,
    RecruitResearcherRequest,
    RequestResearchCapacityRequest,
    SeedPortfolioRequest,
)


class HarnessClient:
    def __init__(self, base_url: str, token: str, *, transport=None, timeout: float = 30):
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            transport=transport,
        )

    def close(self):
        self.http.close()

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        key: str | None = None,
        params: dict | None = None,
    ) -> Any:
        if method.upper() != "GET" and not key:
            raise HarnessError(
                "IDEMPOTENCY_KEY_REQUIRED",
                "Client mutations require a stable command key.",
                status=422,
            )
        if params:
            # httpx sends None as an empty value; an absent cursor must be omitted.
            params = {name: value for name, value in params.items() if value is not None}
        try:
            response = self.http.request(
                method,
                path,
                json=body,
                params=params or None,
                headers={"Idempotency-Key": key} if key else {},
            )
        except httpx.TransportError as error:
            raise HarnessError(
                "TRANSPORT_UNCERTAIN",
                "The service response could not be obtained.",
                status=503,
                operation_id=key,
                remediation=(
                    "Inspect the server and repeat the same command key and "
                    "inputs; do not invent a replacement key."
                ),
            ) from error
        try:
            result = response.json()
        except ValueError as error:
            raise HarnessError(
                "INVALID_SERVER_RESPONSE", "Service returned a non-JSON response.", status=502
            ) from error
        if response.is_error:
            failure = result.get("error", {})
            raise HarnessError(
                failure.get("code", "REMOTE_FAILURE"),
                failure.get("message", "The service rejected the request."),
                status=response.status_code,
                operation_id=failure.get("operation_id"),
                remediation=failure.get("remediation"),
                retryable=failure.get("retryable", False),
                details=failure.get("details", {}),
            )
        return result

    def status(self):
        return self.request("GET", "/v1/status")

    def configure_workforce(self, experiment_id: str, body: ConfigureWorkforceRequest, *, key: str):
        return self.request(
            "POST",
            f"/v1/experiments/{experiment_id}/workforce",
            body.model_dump(mode="json"),
            key=key,
        )

    def seed_portfolio(self, experiment_id: str, body: SeedPortfolioRequest, *, key: str):
        return self.request(
            "POST",
            f"/v1/experiments/{experiment_id}/portfolio",
            body.model_dump(mode="json"),
            key=key,
        )

    def recruit_researcher(self, experiment_id: str, body: RecruitResearcherRequest, *, key: str):
        return self.request(
            "POST",
            f"/v1/experiments/{experiment_id}/recruit",
            body.model_dump(mode="json"),
            key=key,
        )

    def publish_research_profile(
        self, experiment_id: str, body: PublishResearchProfileRequest, *, key: str
    ):
        return self.request(
            "POST",
            f"/v1/experiments/{experiment_id}/research-profile",
            body.model_dump(mode="json"),
            key=key,
        )

    def research_directory(self, experiment_id: str, *, after: str | None = None, limit: int = 20):
        return self.request(
            "GET",
            f"/v1/experiments/{experiment_id}/research-directory",
            params={"after": after, "limit": limit},
        )

    def join_research_team(self, experiment_id: str, body: JoinResearchTeamRequest, *, key: str):
        return self.request(
            "POST",
            f"/v1/experiments/{experiment_id}/research-team",
            body.model_dump(mode="json"),
            key=key,
        )

    def research_capacity(self, experiment_id: str):
        return self.request("GET", f"/v1/experiments/{experiment_id}/research-capacity")

    def request_research_capacity(
        self, experiment_id: str, body: RequestResearchCapacityRequest, *, key: str
    ):
        return self.request(
            "POST",
            f"/v1/experiments/{experiment_id}/research-capacity-requests",
            body.model_dump(mode="json"),
            key=key,
        )

    def schedule_research_synthesis(self, experiment_id: str, *, key: str):
        return self.request("POST", f"/v1/experiments/{experiment_id}/schedule-synthesis", key=key)

    def create_discussion(self, experiment_id: str, body: DiscussionCreate, *, key: str):
        return self.request(
            "POST",
            f"/v1/experiments/{experiment_id}/discussions",
            body.model_dump(mode="json"),
            key=key,
        )

    def discussion_page(self, experiment_id: str, *, after: int | None = None, limit: int = 20):
        return self.request(
            "GET",
            f"/v1/experiments/{experiment_id}/discussions",
            params={"after": after, "limit": limit},
        )

    def post_discussion(self, topic_id: str, body: DiscussionPostCreate, *, key: str):
        return self.request(
            "POST", f"/v1/discussions/{topic_id}/posts", body.model_dump(mode="json"), key=key
        )

    def discussion_posts(self, topic_id: str, *, after: int | None = None, limit: int = 20):
        return self.request(
            "GET", f"/v1/discussions/{topic_id}/posts", params={"after": after, "limit": limit}
        )

    def read_discussion_post(self, post_id: str):
        return self.request("GET", f"/v1/discussion-posts/{post_id}")

    def read_research_message(self, message_id: str):
        return self.request("GET", f"/v1/research-messages/{message_id}")

    def subscribe_discussion(self, topic_id: str, subscribed: bool, *, key: str):
        return self.request(
            "POST", f"/v1/discussions/{topic_id}/subscription", {"subscribed": subscribed}, key=key
        )

    def discussion_updates(self, experiment_id: str, *, after: int | None = None, limit: int = 10):
        return self.request(
            "GET",
            f"/v1/experiments/{experiment_id}/discussion-updates",
            params={"after": after, "limit": limit},
        )

    def acknowledge_discussion_updates(self, experiment_id: str, delivery_id: str, *, key: str):
        return self.request(
            "POST", f"/v1/experiments/{experiment_id}/discussion-updates/{delivery_id}/ack", key=key
        )

    def working_context(self, branch_id: str, *, task_id: str | None = None):
        return self.request(
            "GET",
            f"/v1/branches/{branch_id}/working-context",
            params={"task_id": task_id} if task_id else None,
        )

    def handoff_notes(self, branch_id: str, *, task_id: str | None = None):
        return self.request(
            "GET",
            f"/v1/branches/{branch_id}/handoff-notes",
            params={"task_id": task_id} if task_id else None,
        )

    def checkpoint_research_notes(
        self,
        branch_id: str,
        *,
        approach: str,
        unresolved_obligations: list[str],
        key: str,
        summary: str | None = None,
        evidence_ids: list[str] | None = None,
        task_id: str | None = None,
        holder: str | None = None,
        fence: int | None = None,
    ):
        return self.request(
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
            key=key,
        )

    def mailbox_page(self, branch_id: str, *, after: str | None = None):
        return self.request(
            "GET",
            f"/v1/branches/{branch_id}/mailbox",
            params={"after": after} if after else None,
        )

    def joined_results(self, task_id: str):
        return self.request("GET", f"/v1/tasks/{task_id}/joined-results")

    def index_page(self, branch_id: str, index: str, *, limit: int = 50, after: str | None = None):
        return self.request(
            "GET",
            f"/v1/branches/{branch_id}/index",
            params={"index": index, "limit": limit, "after": after},
        )

    def history_page(self, branch_id: str, kind: str, *, limit: int = 50, after: str | None = None):
        return self.request(
            "GET",
            f"/v1/branches/{branch_id}/history",
            params={"kind": kind, "limit": limit, "after": after},
        )

    def research_graph_page(self, branch_id: str, *, limit: int = 50, after: str | None = None):
        return self.request(
            "GET",
            f"/v1/branches/{branch_id}/research-graph",
            params={"limit": limit, "after": after},
        )

    def read_scientific_record(self, branch_id: str, kind: str, identifier: str):
        return self.request("GET", f"/v1/branches/{branch_id}/records/{kind}/{identifier}")

    def read_artifact_chunk(self, branch_id: str, artifact_id: str, *, offset: int = 0):
        return self.request(
            "GET",
            f"/v1/branches/{branch_id}/artifacts/{artifact_id}/chunk",
            params={"offset": offset},
        )

    def submit_candidate_source(self, experiment_id: str, source: str, *, key: str):
        return self.request(
            "POST", f"/v1/experiments/{experiment_id}/submit-candidate", {"source": source}, key=key
        )

    def list(self, collection: str, *, experiment_id=None):
        allowed = {
            "campaigns",
            "problems",
            "experiments",
            "branches",
            "tasks",
            "claims",
            "artifacts",
            "reviews",
            "sessions",
            "programs",
            "verifications",
            "messages",
        }
        if collection not in allowed:
            raise ValueError("Unknown collection")
        return self.request(
            "GET",
            f"/v1/{collection}",
            params={"experiment_id": experiment_id} if experiment_id else None,
        )
