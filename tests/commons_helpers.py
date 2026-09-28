"""Shared fixtures for society experiments: a started commons with two agent branches."""

from test_core import setup_experiment

from physharness.domain import (
    ArtifactCreate,
    BranchCreate,
    ExperimentCreate,
    Principal,
    SocietyPolicy,
    new_id,
)
from physharness.storage import RecordRow


def society_lab(lab, *, models=1, configurations=None, prefix="society", concurrency=2, **policy):
    """Mirror ``approaches(lab, "ideas")`` with a society policy.

    ``models`` > 1 records distinct model configurations and spreads the branches over them.
    ``configurations`` records exactly these model configurations instead (same spreading).
    ``prefix`` keeps command keys and agent ids distinct when a test needs two experiments.
    ``concurrency`` is the experiment envelope's ``max_concurrency``.
    """
    service, author, _ = lab
    original, _ = setup_experiment(lab, concurrency=concurrency)
    if configurations is None:
        configurations = [
            {
                **original["models"][0],
                "model": original["models"][0]["model"] + (f"-{i}" if i else ""),
            }
            for i in range(models)
        ]
    models = len(configurations)
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
    """Move a node the way platform code does (acceptance, refutation or abandonment)."""
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


PASSED_CHECK = {"ok": True, "reason": None, "axioms": ["propext"]}
ELABORATED = {"ok": True, "backend": "lean-repl", "diagnostics_sha256": "e" * 64}


def state_lean(service, node_id, agent, key="lean", statement=": (1 : Nat) + 1 = 2"):
    """Give the node an elaborated Lean statement; returns the digest a source of it records."""
    stated = service.set_lean_statement(
        node_id, "import Mathlib", "trace_add", statement, ELABORATED, agent, key
    )
    return stated["lean_statement_sha256"]


def publish(service, node_id, agent, rank, key, content="theorem x : True := trivial", **record):
    """Publish ``content`` as the node's source at ``rank``, as ``lean_check`` does; a
    verified rank carries a passing statement check unless ``record`` says otherwise."""
    artifact = service.create_artifact(
        ArtifactCreate(
            experiment_id=agent.experiment_id,
            branch_id=agent.branch_id,
            kind="lean_source",
            content=content,
        ),
        agent,
        key + ":a",
    )
    return service.record_lean_source(
        node_id,
        artifact["id"],
        {
            "rank": rank,
            "bytes": len(content),
            "statement_check": PASSED_CHECK if rank == "verified" else None,
            "lean_statement_sha256": None,
            "imports": [],
            **record,
        },
        agent,
        key,
    )
