from fastapi.testclient import TestClient
from test_core import setup_experiment

from physharness import mcp_server
from physharness.api import create_app
from physharness.client import HarnessClient
from physharness.config import Settings
from physharness.domain import ArtifactCreate, BranchCreate, Principal, TaskCreate


def test_context_uses_same_api_authority_and_idempotency(lab, tmp_path):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="A", objective="Study target"), actor, "branch"
    )
    settings = Settings(auth_tokens={"test-token": actor}, auth_file=tmp_path / "absent")
    with TestClient(create_app(settings, service)) as client:
        url = f"/v1/branches/{branch['id']}/context"
        headers = {"Authorization": "Bearer test-token", "Idempotency-Key": "context"}
        request = {"approach": "Try an energy identity", "unresolved_obligations": ["Prove target"]}
        saved = client.post(url, json=request, headers=headers)
        assert saved.status_code == 201
        assert client.post(url, json=request, headers=headers).json() == saved.json()
        restored = client.get(f"{url}/{saved.json()['id']}", headers=headers)
        assert restored.status_code == 200
        assert restored.json()["scientific_core"]["target"]["id"] == experiment["problem_id"]
        assert restored.json()["unresolved_obligations"]["evidence_status"] == "unverified"
        assert (
            client.post(
                url, json={**request, "proof_status": "verified"}, headers=headers
            ).status_code
            == 422
        )


def test_bounded_notes_graph_and_pages_are_scoped_api_surfaces(lab, tmp_path):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="A", objective="Study target"), actor, "branch"
    )
    settings = Settings(auth_tokens={"test-token": actor}, auth_file=tmp_path / "absent")
    base = f"/v1/branches/{branch['id']}"
    auth = {"Authorization": "Bearer test-token"}
    with TestClient(create_app(settings, service)) as client:
        notes = client.post(
            f"{base}/research-notes",
            json={"approach": "Try components", "unresolved_obligations": ["Prove equality"]},
            headers={**auth, "Idempotency-Key": "notes"},
        )
        assert notes.status_code == 201
        handoff = client.get(f"{base}/handoff-notes", headers=auth)
        assert handoff.status_code == 200
        assert handoff.json()["approach"]["evidence_status"] == "unverified"
        assert client.get(f"{base}/working-context", headers=auth).status_code == 200
        assert client.get(f"{base}/research-graph?limit=1", headers=auth).status_code == 200
        assert client.get(f"{base}/history?kind=task&limit=1", headers=auth).status_code == 200
        assert client.get(f"{base}/index?index=open_tasks&limit=1", headers=auth).status_code == 200
        assert client.get(f"{base}/history?kind=task&limit=101", headers=auth).status_code == 422
        assert client.get(f"{base}/handoff-notes").status_code == 401


def test_client_and_mcp_forward_bounded_retrieval_paths(monkeypatch):
    observed = []

    def request(self, method, path, body=None, *, key=None, params=None):
        observed.append((method, path, body, key, params))
        return {}

    monkeypatch.setattr(HarnessClient, "request", request)
    client = HarnessClient("http://test", "token")
    try:
        client.history_page("branch", "task", limit=2)
        client.research_graph_page("branch", limit=3)
        client.checkpoint_research_notes(
            "branch", approach="a", unresolved_obligations=["b"], key="notes"
        )
    finally:
        client.close()
    assert observed[0][1:] == (
        "/v1/branches/branch/history",
        None,
        None,
        {"kind": "task", "limit": 2, "after": None},
    )
    assert observed[1][1] == "/v1/branches/branch/research-graph"
    assert observed[2][1] == "/v1/branches/branch/research-notes"
    assert observed[2][3] == "notes"

    mcp_calls = []
    monkeypatch.setattr(mcp_server, "call", lambda *args: mcp_calls.append(args) or {})
    mcp_server.history_page("branch", "task", limit=2)
    mcp_server.research_graph_page("branch", limit=3)
    assert mcp_calls[0][1].startswith("/v1/branches/branch/history?")
    assert mcp_calls[1][1].startswith("/v1/branches/branch/research-graph?")


def test_generic_api_hides_native_artifacts_from_own_branch_agent(lab, tmp_path):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    service.transition_experiment(experiment["id"], "start", 1, actor, "start")
    branch = service.create_branch(
        experiment["id"], BranchCreate(title="A", objective="Study target"), actor, "branch"
    )
    agent = Principal(
        id="own-branch-agent",
        project_id=actor.project_id,
        role="agent",
        experiment_id=experiment["id"],
        branch_id=branch["id"],
    )
    native = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            branch_id=branch["id"],
            kind="native_checkpoint",
            content="opaque native state",
        ),
        actor.model_copy(update={"role": "operator"}),
        "native-artifact",
    )
    task = service.create_task(
        TaskCreate(branch_id=branch["id"], objective="Own-branch task"), actor, "task"
    )
    with service.db.transaction() as session:
        native_session = service._insert(
            session,
            "session",
            actor,
            {
                "experiment_id": experiment["id"],
                "branch_id": branch["id"],
                "task_id": task["id"],
                "native_record_id": "opaque-native-session",
                "status": "ready",
            },
        )
    settings = Settings(
        auth_tokens={"agent-token": agent, "operator-token": actor},
        auth_file=tmp_path / "absent",
    )
    with TestClient(create_app(settings, service)) as client:
        auth = {"Authorization": "Bearer agent-token"}
        assert client.get(f"/v1/artifacts/{native['id']}", headers=auth).status_code == 404
        assert client.get(f"/v1/artifacts/{native['id']}/content", headers=auth).status_code == 404
        listing = client.get(
            f"/v1/artifacts?experiment_id={experiment['id']}", headers=auth
        ).json()["items"]
        assert native["id"] not in {item["id"] for item in listing}
        assert client.get(f"/v1/sessions/{native_session['id']}", headers=auth).status_code == 404
        session_items = client.get(
            f"/v1/sessions?experiment_id={experiment['id']}", headers=auth
        ).json()["items"]
        assert native_session["id"] not in {item["id"] for item in session_items}
        assert (
            client.get(
                f"/v1/branches/{branch['id']}/records/artifact/{native['id']}", headers=auth
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"/v1/artifacts/{native['id']}",
                headers={"Authorization": "Bearer operator-token"},
            ).status_code
            == 200
        )
