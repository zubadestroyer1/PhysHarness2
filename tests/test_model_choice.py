import pytest
from test_core import setup_experiment

from physharness.domain import BranchCreate, ExperimentCreate, Principal
from physharness.errors import HarnessError


def test_models_can_select_only_recorded_collaborator_configuration(lab):
    service, author, _ = lab
    original, _ = setup_experiment(lab)
    request = {k: original[k] for k in ("campaign_id", "problem_id", "models", "budget")}
    request["models"] = [
        *request["models"],
        {"runtime": "responses", "model": "second-explicit-model", "parameters": {}},
    ]
    exp = service.create_experiment(ExperimentCreate.model_validate(request), author, "mixed")
    parent = service.create_branch(
        exp["id"], BranchCreate(title="Parent", objective="Explore"), author, "p"
    )
    agent = Principal(
        id="agent",
        project_id=author.project_id,
        role="agent",
        experiment_id=exp["id"],
        branch_id=parent["id"],
    )
    child = service.create_branch(
        exp["id"],
        BranchCreate(
            title="Child",
            objective="Alternate",
            parent_id=parent["id"],
            relation="collaborator",
            model_index=1,
        ),
        agent,
        "child",
    )
    assert child["model_configuration"] == request["models"][1]
    assert (
        service.ledger(exp["id"], author)["max_concurrency"]
        == original["budget"]["max_concurrency"]
    )
    with pytest.raises(HarnessError) as error:
        service.create_branch(
            exp["id"],
            BranchCreate(
                title="Invalid", objective="Alternate", parent_id=parent["id"], model_index=2
            ),
            agent,
            "invalid",
        )
    assert error.value.code == "MODEL_NOT_ALLOWED"
