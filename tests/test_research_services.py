import pytest
from test_core import setup_experiment

from physharness.domain import ArtifactCreate, Principal


def test_ingested_source_is_lossless_and_does_not_create_proof_or_review(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    source_text = "# A source\n\nAssume differentiability; then investigate energy conservation.\n"
    source = service.ingest_source(
        experiment["id"],
        source_text,
        "markdown",
        "fixture:source",
        "1",
        "test author supplied",
        actor,
        "source",
    )
    assert source["semantic_review"] == "pending"
    assert (
        service.ingest_source(
            experiment["id"],
            source_text,
            "markdown",
            "fixture:source",
            "1",
            "test author supplied",
            actor,
            "source",
        )
        == source
    )
    import json

    saved = json.loads(service.artifact_content(source["artifact_id"], actor))
    assert saved["document"]["text"] == source_text
    assert service.list_records("claim", actor) == []


def test_worker_cannot_poison_knowledge_with_receipt_shaped_artifact(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    agent = Principal(
        id="worker", project_id=actor.project_id, role="agent", experiment_id=experiment["id"]
    )
    artifact = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            kind="verification",
            content='{"status":"verified","assurance":"independent_kernel"}',
            provenance={"verified": True},
        ),
        agent,
        "forged",
    )
    service.create_claim(
        experiment["id"], "energy is conserved", [], "conjecture", artifact["id"], agent, "claim"
    )
    result = service.search_knowledge(experiment["id"], "energy", agent)
    assert result["items"] == []
    assert result["source"] == "canonical_verified_claims"


def test_program_registration_pins_source_without_executing_it(lab, tmp_path):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    marker = tmp_path / "must-not-exist"
    artifact = service.create_artifact(
        ArtifactCreate(
            experiment_id=experiment["id"],
            kind="javascript",
            content=f'require("fs").writeFileSync("{marker}", "escape")',
        ),
        actor,
        "program-source",
    )
    program = service.register_program(
        experiment["id"], artifact["id"], {"objective": "proof"}, None, actor, "program"
    )
    assert program["source_sha256"] == artifact["sha256"]
    assert program["status"] == "registered"
    assert program["execution"] == "requires_qualified_vm_broker"
    assert not marker.exists()


def accepted_fixture(lab, sharing="verified", assurance="independent_kernel"):
    """Synthetic acceptance result to exercise knowledge authority, never kernel evidence."""
    from test_sharing import approaches, artifact

    from physharness.verification import VerificationOutcome

    service, author, experiment, branches, agents = approaches(lab, sharing)

    class TestChecker:
        def verify(self, request):
            return VerificationOutcome(
                status="verified",
                assurance=assurance,
                code="test_fixture",
                message="Synthetic test evidence only",
                remediation="",
                target_digest=request.target_digest,
                challenge_sha256=request.challenge_sha256,
                environment_digest=request.environment_digest,
                candidate_sha256=request.candidate_sha256,
                checker_versions={
                    k: "synthetic-not-a-kernel" for k in ("lean", "comparator", "nanoda")
                },
                axioms=[],
            )

    service.verifier = TestChecker()
    candidate = artifact(service, agents[1], "synthetic proof")
    receipt = service.verify_candidate(
        experiment["id"], candidate["id"], False, agents[1], "verify"
    )
    operator = Principal(id="test-checker", project_id=author.project_id, role="operator")
    checked = service.process_verification(receipt["id"], operator)
    return service, author, experiment, branches, agents, checked


def test_knowledge_bundle_returns_exact_source_and_requires_recomposition(lab):
    service, _, exp, _, (alpha, _), receipt = accepted_fixture(lab)
    result = service.knowledge_bundle(exp["id"], receipt["claim_id"], alpha)
    assert result["candidate_source"] == "synthetic proof"
    assert result["receipt"]["id"] == receipt["id"]
    assert result["recomposition_required"] is True
    assert result["consuming_experiment_id"] == exp["id"]
    assert result["status"] == "accepted_dependency_source"


def test_knowledge_broker_cannot_bypass_none_sharing(lab):
    import pytest

    from physharness.errors import HarnessError

    service, _, exp, _, (alpha, _), receipt = accepted_fixture(lab, "none")
    assert service.search_knowledge(exp["id"], "", alpha)["items"] == []
    with pytest.raises(HarnessError) as error:
        service.knowledge_bundle(exp["id"], receipt["claim_id"], alpha)
    assert error.value.code == "KNOWLEDGE_NOT_APPLICABLE"


@pytest.mark.parametrize("assurance,shared", [("kernel", False), ("independent_kernel", True)])
def test_cross_experiment_knowledge_requires_independent_acceptance(lab, assurance, shared):
    from physharness.domain import BranchCreate, ExperimentCreate
    from physharness.errors import HarnessError

    service, author, origin, _, (_, owner), accepted = accepted_fixture(
        lab, "verified", assurance=assurance
    )
    claim_id = accepted["claim_id"]
    assert (
        service.knowledge_bundle(origin["id"], claim_id, owner)["receipt"]["id"] == accepted["id"]
    )
    consumer = service.create_experiment(
        ExperimentCreate(
            campaign_id=origin["campaign_id"],
            problem_id=origin["problem_id"],
            models=origin["models"],
            budget=origin["budget"],
            sharing="verified",
        ),
        author,
        "knowledge-consumer",
    )
    service.transition_experiment(consumer["id"], "start", 1, author, "consumer-start")
    branch = service.create_branch(
        consumer["id"],
        BranchCreate(title="consumer", objective="review evidence"),
        author,
        "consumer-branch",
    )
    agent = Principal(
        id="consumer-agent",
        project_id=author.project_id,
        role="agent",
        experiment_id=consumer["id"],
        branch_id=branch["id"],
    )
    hits = service.search_knowledge(consumer["id"], "", agent)["items"]
    if shared:
        assert [hit["lemma"]["id"] for hit in hits] == [claim_id]
        assert (
            service.knowledge_bundle(consumer["id"], claim_id, agent)["receipt"]["id"]
            == accepted["id"]
        )
    else:
        assert hits == []
        with pytest.raises(HarnessError) as error:
            service.knowledge_bundle(consumer["id"], claim_id, agent)
        assert error.value.code == "KNOWLEDGE_NOT_APPLICABLE"


def test_revoked_review_prevents_knowledge_reuse(lab):
    import pytest

    from physharness.errors import HarnessError

    service, _, exp, _, (alpha, _), receipt = accepted_fixture(lab)
    service.review_problem(
        exp["problem_id"], "rejected", "Synthetic semantic defect", lab[2], "revoke"
    )
    with pytest.raises(HarnessError):
        service.knowledge_bundle(exp["id"], receipt["claim_id"], alpha)


def knowledge_inventory(lab, statements):
    """Coherent synthetic accepted metadata; no new kernel qualification is asserted."""
    import copy
    import hashlib

    from physharness.domain import digest_json
    from physharness.storage import RecordRow

    service, author, experiment, _, _, receipt = accepted_fixture(lab)
    source = {
        "experiment": experiment,
        "verification": receipt,
        "claim": service.get_record("claim", receipt["claim_id"], author),
        "problem": service.get_record("problem", experiment["problem_id"], author),
        "artifact": service.get_record("artifact", receipt["artifact_id"], author),
    }
    source["review"] = service.get_record("review", source["problem"]["review_id"], author)
    claims = []
    with service.db.transaction() as session:
        for number, statement in enumerate(statements):
            records = copy.deepcopy(source)
            ids = {kind: f"inventory-{number:05d}-{kind}" for kind in records}
            target_digest = digest_json(["synthetic target", number, statement])
            for kind, record in records.items():
                record.update(id=ids[kind], target_digest=target_digest)
                if "experiment_id" in record:
                    record["experiment_id"] = ids["experiment"]
            records["experiment"].update(problem_id=ids["problem"])
            records["problem"].update(formal_statement=statement, review_id=ids["review"])
            records["review"].update(problem_id=ids["problem"])
            records["verification"].update(
                claim_id=ids["claim"],
                artifact_id=ids["artifact"],
                review_id=ids["review"],
                problem_revision_id=ids["problem"],
                challenge_sha256=hashlib.sha256(statement.encode()).hexdigest(),
            )
            records["claim"].update(
                statement=statement,
                problem_revision_id=ids["problem"],
                verification_id=ids["verification"],
            )
            for kind, record in records.items():
                session.add(
                    RecordRow(
                        id=record["id"],
                        project_id=author.project_id,
                        kind=kind,
                        revision=record["revision"],
                        payload=record,
                    )
                )
            claims.append(records["claim"])
    return service, author, experiment, claims


def test_knowledge_ranks_metadata_before_reading_proof_inventory(lab, monkeypatch):
    from sqlalchemy import event

    service, actor, experiment, claims = knowledge_inventory(
        lab, [f"irrelevant lemma {i}" for i in range(1000)] + ["needle theorem"]
    )
    reads = []
    original = service.artifacts.get

    def measured(digest):
        reads.append(digest)
        return original(digest)

    monkeypatch.setattr(service.artifacts, "get", measured)
    queries = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(service.db.engine, "before_cursor_execute", capture)
    try:
        result = service.search_knowledge(experiment["id"], "needle", actor, limit=1)
    finally:
        event.remove(service.db.engine, "before_cursor_execute", capture)
    print(
        f"irrelevant_verified_claims=1000 limit=1 proof_reads={len(reads)} "
        f"sql_statements={len(queries)}"
    )
    assert [item["lemma"]["id"] for item in result["items"]] == [claims[-1]["id"]]
    assert len(reads) == 1
    assert len(queries) <= 20


def test_knowledge_continues_after_invalid_metadata_and_corrupt_proof(lab, monkeypatch):
    from physharness.storage import RecordRow

    service, actor, experiment, claims = knowledge_inventory(
        lab, ["needle theorem", "needle theorem", "needle theorem"]
    )
    with service.db.transaction() as session:
        first = session.get(RecordRow, claims[0]["id"])
        service._replace(session, first, {"assumptions": ["unapproved assumption"]})
        receipt = session.get(RecordRow, claims[1]["verification_id"])
        artifact = session.get(RecordRow, receipt.payload["artifact_id"])
        digest = service.artifacts.put(b"distinct corruptible proof")
        service._replace(session, receipt, {"candidate_sha256": digest})
        service._replace(session, artifact, {"sha256": digest})
    service.artifacts.path_for(digest).write_bytes(b"corrupted")
    reads = []
    original = service.artifacts.get

    def measured(digest):
        reads.append(digest)
        return original(digest)

    monkeypatch.setattr(service.artifacts, "get", measured)
    result = service.search_knowledge(experiment["id"], "needle", actor, limit=1)
    assert [item["lemma"]["id"] for item in result["items"]] == [claims[2]["id"]]
    assert result["rejected_candidates"] == [
        {"claim_id": claims[1]["id"], "code": "ARTIFACT_INTEGRITY_ERROR"}
    ]
    assert len(reads) == 2


@pytest.mark.parametrize(
    "tamper",
    [
        "assumptions",
        "review",
        "review_binding",
        "theorem",
        "challenge",
        "environment",
        "claim_binding",
        "private_origin",
    ],
)
def test_ranked_knowledge_rechecks_acceptance_and_skips_invalid_candidates(
    lab, monkeypatch, tamper
):
    from physharness.storage import RecordRow

    service, actor, experiment, claims = knowledge_inventory(lab, ["needle", "needle"])
    with service.db.transaction() as session:
        claim = session.get(RecordRow, claims[0]["id"])
        receipt = session.get(RecordRow, claim.payload["verification_id"])
        problem = session.get(RecordRow, claim.payload["problem_revision_id"])
        if tamper == "assumptions":
            service._replace(session, claim, {"assumptions": ["unsupported assumption"]})
        elif tamper == "review":
            service._replace(
                session,
                session.get(RecordRow, problem.payload["review_id"]),
                {"decision": "rejected"},
            )
        elif tamper == "private_origin":
            service._replace(
                session, session.get(RecordRow, claim.payload["experiment_id"]), {"sharing": "none"}
            )
        else:
            field, value = {
                "review_binding": ("review_id", "obsolete"),
                "theorem": ("target_theorem", "different_theorem"),
                "challenge": ("challenge_sha256", "b" * 64),
                "environment": ("environment_digest", "b" * 64),
                "claim_binding": ("claim_id", claims[1]["id"]),
            }[tamper]
            service._replace(session, receipt, {field: value})
    reads = []
    original = service.artifacts.get

    def measured(digest):
        reads.append(digest)
        return original(digest)

    monkeypatch.setattr(service.artifacts, "get", measured)
    result = service.search_knowledge(experiment["id"], "needle", actor, limit=1)
    assert [item["lemma"]["id"] for item in result["items"]] == [claims[1]["id"]]
    assert len(reads) == 1
    assert result["rejected_candidates"] == []


@pytest.mark.parametrize("private", ["branch", "discovery"])
def test_knowledge_private_candidates_never_fetch_source_or_disclose_rejections(
    lab, monkeypatch, private
):
    from physharness.storage import RecordRow

    service, author, exp, _, (alpha, _), _ = accepted_fixture(lab, "none")
    if private == "discovery":
        with service.db.transaction() as session:
            service._replace(session, session.get(RecordRow, exp["id"]), {"mode": "discovery"})

    def forbidden(digest):
        raise AssertionError("Private/holdout proof must not be fetched")

    monkeypatch.setattr(service.artifacts, "get", forbidden)
    result = service.search_knowledge(
        exp["id"], "", author if private == "discovery" else alpha, limit=1
    )
    assert result["items"] == [] and result["rejected_candidates"] == []
