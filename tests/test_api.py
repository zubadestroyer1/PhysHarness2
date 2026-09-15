import pytest
from fastapi.testclient import TestClient

from physharness.api import create_app
from physharness.config import Settings


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        artifact_root=tmp_path / "artifacts",
        auth_tokens={
            "research-key": {"id": "r", "project_id": "lab", "role": "researcher"},
            "review-key": {"id": "v", "project_id": "lab", "role": "reviewer"},
        },
        auto_create_schema=True,
    )
    with TestClient(create_app(settings)) as api:
        yield api


def headers(key="one", token="research-key"):
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key}


def test_private_api_requires_identity_even_in_local_mode(client):
    assert client.get("/healthz").status_code == 200
    response = client.get("/v1/campaigns")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert response.json()["error"]["operation_id"]


def test_mutations_require_command_identity(client):
    response = client.post(
        "/v1/campaigns",
        headers={"Authorization": "Bearer research-key"},
        json={"title": "A", "objective": "B", "programs": ["quantum"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_validation_failure_has_loud_safe_diagnostics(client):
    response = client.post(
        "/v1/campaigns",
        headers=headers(),
        json={
            "title": "A",
            "objective": "B",
            "programs": ["invented"],
            "secret": "do-not-echo-input",
        },
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["fields"]
    assert "do-not-echo-input" not in response.text


def test_create_read_and_duplicate_api_commands(client):
    payload = {
        "title": "Classical campaign",
        "objective": "Energy conservation",
        "programs": ["classical"],
    }
    first = client.post("/v1/campaigns", headers=headers(), json=payload)
    assert first.status_code == 201
    again = client.post("/v1/campaigns", headers=headers(), json=payload)
    assert again.json()["id"] == first.json()["id"]
    listing = client.get("/v1/campaigns", headers=headers()).json()["items"]
    assert [r["title"] for r in listing] == ["Classical campaign"]
    changed = client.post("/v1/campaigns", headers=headers(), json={**payload, "title": "Changed"})
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_status_never_claims_missing_verification_or_cloud_is_qualified(client):
    response = client.get("/v1/status", headers=headers())
    assert response.status_code == 200
    checks = {c["name"]: c["status"] for c in response.json()["checks"]}
    assert checks["verification"] == "unavailable"
    assert all(q["status"] != "qualified" for q in response.json()["qualifications"])


def test_failed_database_is_not_an_empty_success(client):
    service = client.app.state.service
    from sqlalchemy import text

    with service.db.engine.begin() as connection:
        connection.execute(text("DROP TABLE records"))
    with TestClient(client.app, raise_server_exceptions=False) as no_raise:
        response = no_raise.get("/v1/campaigns", headers=headers())
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.headers["X-Operation-ID"] == response.json()["error"]["operation_id"]
    assert "sql" not in response.text.lower()


def test_configuration_refuses_unsafe_production_defaults(tmp_path):
    with pytest.raises(ValueError):
        Settings(
            mode="production",
            database_url="sqlite:///:memory:",
            artifact_root=tmp_path,
            auth_tokens={},
        )


def test_pagination_retains_every_record_and_exposes_cursor(client):
    for i in range(3):
        assert (
            client.post(
                "/v1/campaigns",
                headers=headers(f"campaign-{i}"),
                json={"title": f"Campaign {i}", "objective": "Fixture", "programs": ["quantum"]},
            ).status_code
            == 201
        )
    found = []
    cursor = None
    while True:
        result = client.get(
            "/v1/campaigns",
            headers=headers(),
            params={"limit": 1, **({"after": cursor} if cursor else {})},
        ).json()
        found.extend(item["id"] for item in result["items"])
        cursor = result.get("next_cursor")
        if not cursor:
            break
    assert len(found) == len(set(found)) == 3


def test_error_header_correlates_with_response_body(client):
    response = client.get("/v1/campaigns")
    assert response.headers["X-Operation-ID"] == response.json()["error"]["operation_id"]
