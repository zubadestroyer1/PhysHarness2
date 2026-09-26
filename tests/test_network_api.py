"""Public research network routes use strict typed inputs and stable keys."""

import httpx
from fastapi.testclient import TestClient
from test_sharing import approaches

from physharness.api import create_app
from physharness.client import HarnessClient
from physharness.config import Settings
from physharness.discussion_models import DiscussionCreate
from physharness.workforce_models import SeedPortfolioRequest


def test_network_routes_reject_extra_fields_before_service(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        artifact_root=tmp_path / "artifacts",
        auth_tokens={"token": {"id": "op", "project_id": "lab", "role": "operator"}},
        auto_create_schema=True,
    )
    with TestClient(create_app(settings)) as api:
        headers = {"Authorization": "Bearer token", "Idempotency-Key": "op-1"}
        response = api.post(
            "/v1/experiments/exp/portfolio",
            headers=headers,
            json={"roots": [{"title": "A", "objective": "Try", "secret": "private"}]},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert "private" not in response.text


def test_client_sends_idempotent_typed_portfolio_to_shared_route():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"roots": []})

    client = HarnessClient("https://test", "token", transport=httpx.MockTransport(handle))
    request = SeedPortfolioRequest(roots=[{"title": "A", "objective": "Try"}])
    assert client.seed_portfolio("exp", request, key="stable") == {"roots": []}
    assert seen[0].url.path == "/v1/experiments/exp/portfolio"
    assert seen[0].headers["Idempotency-Key"] == "stable"
    assert seen[0].read().decode().count('"title"') == 1
    client.close()


def test_http_discussion_delivery_ack_and_exact_source_share_service(lab, tmp_path):
    service, _, experiment, _, (alpha, beta) = approaches(lab, "ideas")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'unused.db'}",
        artifact_root=tmp_path / "unused-artifacts",
        auth_tokens={
            "alpha": alpha.model_dump(mode="json"),
            "beta": beta.model_dump(mode="json"),
        },
        auto_create_schema=True,
    )
    with TestClient(create_app(settings, service=service)) as api:
        alpha_headers = {"Authorization": "Bearer alpha", "Idempotency-Key": "topic"}
        topic = api.post(
            f"/v1/experiments/{experiment['id']}/discussions",
            headers=alpha_headers,
            json={"title": "HTTP topic", "summary": "Scope", "branch_id": alpha.branch_id},
        )
        assert topic.status_code == 201
        topic_id = topic.json()["id"]
        subscribed = api.post(
            f"/v1/discussions/{topic_id}/subscription",
            headers={"Authorization": "Bearer beta", "Idempotency-Key": "subscribe"},
            json={"subscribed": True},
        )
        assert subscribed.status_code == 200
        post = api.post(
            f"/v1/discussions/{topic_id}/posts",
            headers={"Authorization": "Bearer alpha", "Idempotency-Key": "post"},
            json={"kind": "finding", "content": "Exact HTTP idea"},
        )
        assert post.status_code == 201
        inbox = api.get(
            f"/v1/experiments/{experiment['id']}/discussion-updates",
            headers={"Authorization": "Bearer beta"},
        )
        assert inbox.status_code == 200
        delivery = inbox.json()
        assert delivery["items"][0]["retrieval_id"] == post.json()["id"]
        exact = api.get(
            f"/v1/discussion-posts/{post.json()['id']}",
            headers={"Authorization": "Bearer beta"},
        )
        assert exact.json()["content"] == "Exact HTTP idea"
        ack = api.post(
            f"/v1/experiments/{experiment['id']}/discussion-updates/{delivery['delivery_id']}/ack",
            headers={"Authorization": "Bearer beta", "Idempotency-Key": "ack"},
        )
        assert ack.status_code == 200
        assert (
            api.get(
                f"/v1/experiments/{experiment['id']}/discussion-updates",
                headers={"Authorization": "Bearer beta"},
            ).json()["items"]
            == []
        )


def test_client_omits_absent_page_cursors_from_queries():
    seen = []

    def handle(request):
        seen.append(request.url)
        return httpx.Response(200, json={"items": [], "next_cursor": None})

    client = HarnessClient("https://test", "token", transport=httpx.MockTransport(handle))
    client.discussion_page("exp")
    client.discussion_posts("topic")
    client.discussion_updates("exp")
    client.research_directory("exp")
    client.index_page("branch", "claims")
    client.history_page("branch", "claim")
    client.research_graph_page("branch")
    assert len(seen) == 7
    assert all("after" not in url.params for url in seen), [str(url) for url in seen]
    client.discussion_updates("exp", after=7)
    assert seen[-1].params["after"] == "7"
    client.close()


def test_client_first_pages_are_accepted_by_the_service(lab, tmp_path):
    service, _, experiment, _, (alpha, beta) = approaches(lab, "ideas")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'unused.db'}",
        artifact_root=tmp_path / "unused-artifacts",
        auth_tokens={"beta": beta.model_dump(mode="json")},
        auto_create_schema=True,
    )
    topic = service.create_discussion(
        experiment["id"], DiscussionCreate(title="Paging", summary="First page"), alpha, "topic"
    )
    with TestClient(create_app(settings, service=service)) as api:
        client = HarnessClient("http://testserver", "beta", transport=api._transport)
        assert client.discussion_page(experiment["id"])["items"][0]["id"] == topic["id"]
        assert client.discussion_posts(topic["id"])["items"] == []
        assert client.discussion_updates(experiment["id"])["items"] == []
        assert client.research_directory(experiment["id"])["items"] == []
        assert "items" in client.research_graph_page(beta.branch_id)
        client.close()
