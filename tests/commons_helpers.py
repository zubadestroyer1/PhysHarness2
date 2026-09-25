"""Shared fixtures for society experiments: a started commons with two agent branches."""

from test_core import setup_experiment

from physharness.domain import BranchCreate, ExperimentCreate, Principal, SocietyPolicy, new_id
from physharness.storage import RecordRow


def society_lab(lab, *, models=1, prefix="society", **policy):
    """Mirror ``approaches(lab, "ideas")`` with a society policy.

    ``models`` > 1 records distinct model configurations and spreads the branches over them.
    ``prefix`` keeps command keys and agent ids distinct when a test needs two experiments.
    """
    service, author, _ = lab
    original, _ = setup_experiment(lab)
    configurations = [
        {**original["models"][0], "model": original["models"][0]["model"] + (f"-{i}" if i else "")}
        for i in range(models)
    ]
    request = ExperimentCreate.model_validate(
        {
            **{k: original[k] for k in ("campaign_id", "problem_id", "budget")},
            "models": configurations,
            "sharing": "ideas",
            "society": SocietyPolicy(**policy),
        }
    )
    experiment = service.create_experiment(request, author, f"{prefix}-experiment")
    service.transition_experiment(experiment["id"], "start", 1, author, f"{prefix}-start")
    branches = [
        service.create_branch(
            experiment["id"],
            BranchCreate(
                title=name, objective=name, model_index=i % models if models > 1 else None
            ),
            author,
            f"{prefix}-{name}",
        )
        for i, name in enumerate(("alpha", "beta"))
    ]
    agents = [
        Principal(
            id=f"{prefix}-{name}",
            role="agent",
            project_id=author.project_id,
            experiment_id=experiment["id"],
            branch_id=branch["id"],
        )
        for name, branch in zip(("worker-a", "worker-b"), branches, strict=True)
    ]
    return service, author, experiment, branches, agents


def set_status(service, node_id, *statuses, reason="platform test"):
    """Drive the platform-only ladder the way referee/verifier code will."""
    record = None
    for status in statuses:
        with service.db.transaction() as session:
            record = service._set_node_status(
                session,
                session.get(RecordRow, node_id),
                status,
                reason=reason,
                evidence={"fixture": True},
                op=new_id(),
            )
    return record
