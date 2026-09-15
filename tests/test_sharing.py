"""Canonical multi-approach visibility tests; no simulated proof qualification."""

import json

import pytest
from test_core import setup_experiment

from physharness.domain import ArtifactCreate, BranchCreate, ExperimentCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.storage import RecordRow


def approaches(lab, sharing):
    service, author, _ = lab
    original, _ = setup_experiment(lab)
    request = ExperimentCreate.model_validate(
        {k: original[k] for k in ("campaign_id", "problem_id", "models", "budget")}
    ).model_copy(update={"sharing": sharing})
    experiment = service.create_experiment(request, author, "sharing-experiment")
    service.transition_experiment(experiment["id"], "start", 1, author, "sharing-start")
    branches = [
        service.create_branch(
            experiment["id"], BranchCreate(title=name, objective=name), author, name
        )
        for name in ("alpha", "beta")
    ]
    agents = [
        Principal(
            id=name,
            role="agent",
            project_id=author.project_id,
            experiment_id=experiment["id"],
            branch_id=branch["id"],
        )
        for name, branch in zip(("worker-a", "worker-b"), branches, strict=True)
    ]
    return service, author, experiment, branches, agents


def artifact(service, actor, key, **kwargs):
    return service.create_artifact(
        ArtifactCreate(
            experiment_id=actor.experiment_id, kind="lean_source", content=key, **kwargs
        ),
        actor,
        key,
    )


@pytest.mark.parametrize("sharing", ["none", "verified"])
def test_unverified_cross_branch_records_never_enter_reads_briefs_pages_or_events(lab, sharing):
    service, author, exp, branches, (alpha, beta) = approaches(lab, sharing)
    secret = artifact(service, beta, "secret technique")
    own = artifact(service, alpha, "own technique")
    claim = service.create_claim(
        exp["id"], "secret conjecture", [], "conjecture", secret["id"], beta, "claim"
    )
    task = service.create_task(
        TaskCreate(branch_id=branches[1]["id"], objective="secret objective"), beta, "task"
    )
    receipt = service.verify_candidate(exp["id"], secret["id"], False, beta, "receipt")
    for record in (secret, claim, task, receipt):
        with pytest.raises(HarnessError):
            service.get_record(record["kind"], record["id"], alpha)
    with pytest.raises(HarnessError):
        service.artifact_content(secret["id"], alpha)
    assert [r["id"] for r in service.list_records("artifact", alpha, exp["id"], limit=1)] == [
        own["id"]
    ]
    brief = json.dumps(service.restart_brief(branches[0]["id"], alpha))
    assert "secret" not in brief
    assert secret["id"] not in json.dumps(service.events(alpha, limit=1000))
    assert service.get_record("artifact", secret["id"], author)["branch_id"] == beta.branch_id


def test_verified_policy_uses_canonical_acceptance_not_provenance(lab):
    service, author, exp, branches, (alpha, beta) = approaches(lab, "verified")
    candidate = artifact(service, beta, "candidate", provenance={"verified": True})
    receipt = service.verify_candidate(exp["id"], candidate["id"], False, beta, "submit")
    with pytest.raises(HarnessError):
        service.get_record("artifact", candidate["id"], alpha)
    # Controlled persisted acceptance fixture, explicitly not a live checker result.
    with service.db.transaction() as session:
        row = session.get(RecordRow, receipt["id"])
        service._replace(session, row, {"status": "verified", "assurance": "independent_kernel"})
    assert service.artifact_content(candidate["id"], alpha) == b"candidate"
    assert service.get_record("verification", receipt["id"], alpha)["status"] == "verified"
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, exp["id"]), {"sharing": "none"})
    with pytest.raises(HarnessError):
        service.get_record("artifact", candidate["id"], alpha)


@pytest.mark.parametrize("sharing", ["none", "verified"])
def test_cross_branch_free_text_messages_are_blocked_even_with_verified_looking_attachment(
    lab, sharing
):
    service, _, _, branches, (alpha, _) = approaches(lab, sharing)
    item = artifact(service, alpha, "not verified", provenance={"verified": True})
    with pytest.raises(HarnessError) as exc:
        service.send_message(
            branches[0]["id"], branches[1]["id"], "unverified hint", [item["id"]], alpha, "message"
        )
    assert exc.value.code == "SHARING_POLICY"


def test_ideas_attribution_does_not_expose_native_history_or_allow_sender_forgery(lab):
    service, _, exp, branches, (alpha, beta) = approaches(lab, "ideas")
    item = artifact(service, alpha, "attributed idea")
    message = service.send_message(
        branches[0]["id"], branches[1]["id"], "try symmetry", [item["id"]], alpha, "message"
    )
    assert service.get_record("message", message["id"], beta)["attributed_to"] == alpha.id
    assert service.get_record("artifact", item["id"], beta)["origin_actor_id"] == alpha.id
    private = service.create_artifact(
        ArtifactCreate(
            experiment_id=exp["id"], kind="native_checkpoint", content="private context"
        ),
        alpha,
        "private",
    )
    with pytest.raises(HarnessError):
        service.artifact_content(private["id"], beta)
    with pytest.raises(HarnessError):
        service.send_message(
            branches[1]["id"], branches[0]["id"], "forged sender", [], alpha, "forged"
        )


@pytest.mark.parametrize("field", ["branch_id", "provenance", "trusted_input"])
def test_agent_cannot_forge_authority_metadata(lab, field):
    service, _, _, branches, (alpha, _) = approaches(lab, "none")
    value = {
        "branch_id": branches[1]["id"],
        "provenance": {"branch_id": branches[1]["id"]},
        "trusted_input": True,
    }[field]
    with pytest.raises(HarnessError):
        artifact(service, alpha, "forged", **{field: value})


def test_trusted_inputs_are_explicit_and_legacy_unscoped_agents_are_not_global_readers(lab):
    service, author, exp, _, (alpha, beta) = approaches(lab, "none")
    public = service.create_artifact(
        ArtifactCreate(
            experiment_id=exp["id"], kind="source", content="supplied input", trusted_input=True
        ),
        author,
        "input",
    )
    secret = artifact(service, beta, "secret")
    legacy = Principal(
        id="legacy", role="agent", project_id=author.project_id, experiment_id=exp["id"]
    )
    own = artifact(service, legacy, "legacy own")
    assert service.artifact_content(public["id"], alpha) == b"supplied input"
    assert service.artifact_content(own["id"], legacy) == b"legacy own"
    with pytest.raises(HarnessError):
        service.artifact_content(secret["id"], legacy)
    with pytest.raises(HarnessError):
        service.artifact_content(own["id"], alpha)


def test_idempotency_rejects_changed_branch_or_orchestrator_authority(lab):
    service, _, _, _, (alpha, beta) = approaches(lab, "none")
    artifact(service, alpha, "same command")
    for replacement in (
        alpha.model_copy(update={"branch_id": beta.branch_id}),
        alpha.model_copy(update={"branch_id": None, "agent_orchestrator": True}),
    ):
        with pytest.raises(HarnessError) as exc:
            artifact(service, replacement, "same command")
        assert exc.value.code == "IDEMPOTENCY_CONFLICT"


def test_nested_delegation_creates_distinct_branch_and_keeps_results_private(lab):
    service, _, exp, branches, (alpha, _) = approaches(lab, "none")
    child = service.create_branch(
        exp["id"],
        BranchCreate(
            title="helper", objective="derive lemma", parent_id=alpha.branch_id, relation="helper"
        ),
        alpha,
        "child",
    )
    task = service.create_task(
        TaskCreate(branch_id=child["id"], objective="derive lemma"), alpha, "delegation"
    )
    assert task["branch_id"] == child["id"]
    assert child["execution_identity"] != branches[0]["execution_identity"]
    child_agent = Principal(
        id=child["execution_identity"],
        project_id=alpha.project_id,
        role="agent",
        experiment_id=exp["id"],
        branch_id=child["id"],
    )
    result = artifact(service, child_agent, "child private")
    with pytest.raises(HarnessError):
        service.artifact_content(result["id"], alpha)
    with pytest.raises(HarnessError):
        service.create_task(
            TaskCreate(branch_id=branches[1]["id"], objective="intrusion"), alpha, "intrusion"
        )


@pytest.mark.parametrize(
    "tamper",
    [
        {"assurance": "none"},
        {"target_digest": "b" * 64},
        {"candidate_sha256": "b" * 64},
        {"environment_digest": "b" * 64},
    ],
)
def test_accepted_label_without_matching_authoritative_binding_does_not_share(lab, tamper):
    service, _, exp, _, (alpha, beta) = approaches(lab, "verified")
    item = artifact(service, beta, "candidate")
    receipt = service.verify_candidate(exp["id"], item["id"], False, beta, "submit")
    with service.db.transaction() as session:
        service._replace(
            session,
            session.get(RecordRow, receipt["id"]),
            {"status": "verified", "assurance": "independent_kernel", **tamper},
        )
    assert service.list_records("artifact", alpha) == []
    assert service.list_records("verification", alpha) == []


def test_explicit_orchestrator_reads_topology_without_private_results(lab):
    service, _, exp, branches, (_, beta) = approaches(lab, "none")
    controller = Principal(
        id="orchestration-agent",
        project_id=beta.project_id,
        role="agent",
        experiment_id=exp["id"],
        agent_orchestrator=True,
    )
    item = artifact(service, beta, "private")
    assert len(service.list_records("branch", controller)) == 2
    task = service.create_task(
        TaskCreate(branch_id=branches[1]["id"], objective="bounded attempt"), controller, "task"
    )
    assert task["branch_id"] == beta.branch_id
    with pytest.raises(HarnessError):
        service.artifact_content(item["id"], controller)


def test_controller_checkpoint_cannot_smuggle_other_branch_history(lab):
    service, author, _, branches, (alpha, beta) = approaches(lab, "none")
    secret = artifact(service, beta, "private-other-branch")
    checkpoint = service.checkpoint_branch(
        branches[0]["id"], 1, "own approach", "b" * 64, "a" * 64, None, author, "checkpoint"
    )
    encoded = service.artifact_content(checkpoint["checkpoint_id"], alpha).decode()
    assert secret["id"] not in encoded
    assert "private-other-branch" not in encoded


@pytest.mark.asyncio
async def test_worker_prompt_tools_sessions_and_outputs_obey_same_branch(lab):
    from physharness.execution import RuntimeCheckpoint, RuntimeResult, RuntimeSession
    from physharness.orchestration.research_worker import ResearchTaskExecutor

    service, author, exp, branches, (alpha, beta) = approaches(lab, "none")
    secret = artifact(service, beta, "worker must never see this")
    task = service.create_task(
        TaskCreate(branch_id=alpha.branch_id, objective="derive own lemma"), author, "task"
    )
    seen = []

    class ProtocolRuntime:
        def __init__(self, store, dispatcher, event_sink):
            self.store, self.dispatcher = store, dispatcher

        async def start(self, prompt, model, limits):
            assert secret["id"] not in prompt
            assert "worker must never see this" not in prompt
            result = await self.dispatcher.dispatch(
                "read_artifact", {"artifact_id": secret["id"]}, "read-secret"
            )
            assert result["error"]["code"] == "NOT_FOUND"
            state = RuntimeSession(runtime="responses", model=model, limits=limits)
            await self.store.save(RuntimeCheckpoint.build(state, {"history": "alpha native"}))
            seen.append(state.id)
            return RuntimeResult(session=state, output_text="own unresolved result")

    executor = ResearchTaskExecutor(
        service,
        prices={
            "explicit-test-model": {"input_usd_per_million": "1", "output_usd_per_million": "1"}
        },
        runtime_factory=ProtocolRuntime,
    )
    result = await executor.execute(task["id"], author.project_id)
    output = service.get_record("artifact", result["artifact_id"], alpha)
    session = service.list_records("session", alpha)[0]
    assert output["branch_id"] == session["branch_id"] == alpha.branch_id
    assert session["native_record_id"] == seen[0]
    assert service.list_records("session", beta) == []
    with pytest.raises(HarnessError):
        service.artifact_content(session["checkpoint_artifact_id"], beta)
    from physharness.orchestration.research_worker import CanonicalRuntimeStore

    other_store = CanonicalRuntimeStore(service, author, exp["id"], "different-task", "holder", 1)
    with pytest.raises(HarnessError):
        await other_store.load(seen[0])


@pytest.mark.parametrize(
    "field,value",
    [("challenge_sha256", "f" * 64), ("review_id", "stale"), ("target_theorem", "other")],
)
def test_sharing_requires_current_source_review_and_theorem(lab, field, value):
    service, _, exp, _, (alpha, beta) = approaches(lab, "verified")
    item = artifact(service, beta, "candidate")
    receipt = service.verify_candidate(exp["id"], item["id"], False, beta, "submit")
    with service.db.transaction() as session:
        service._replace(
            session,
            session.get(RecordRow, receipt["id"]),
            {
                "status": "verified",
                "assurance": "independent_kernel",
                field: value,
            },
        )
    assert service.list_records("artifact", alpha) == []
    assert service.list_records("verification", alpha) == []
