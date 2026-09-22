from fastapi.testclient import TestClient
from test_core import setup_experiment

from physharness.api import create_app
from physharness.config import Settings
from physharness.domain import BranchCreate


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
