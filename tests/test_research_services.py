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


def accepted_fixture(
    lab, sharing="verified", assurance="independent_kernel", source="synthetic proof"
):
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
    candidate = artifact(service, agents[1], source)
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


@pytest.mark.integration
async def test_opt_in_known_premise_recomposes_under_pinned_lean(lab):
    """The fixture's acceptance is synthetic; this checks real Lean reuse only."""
    import os

    from physharness.execution.local_docker import LocalDockerWorkspaceProvider
    from physharness.execution.types import CommandRequest

    host = os.environ.get("PHYSHARNESS_WORKBENCH_DOCKER_HOST")
    image = os.environ.get("PHYSHARNESS_WORKBENCH_IMAGE_DIGEST")
    if not host or not image:
        pytest.skip("Dedicated workbench endpoint and pinned image digest are required")
    source = "import Mathlib\ntheorem known_true : True := by trivial\n"
    service, _, experiment, _, (reader, _), receipt = accepted_fixture(lab, source=source)
    hits = service.search_knowledge(experiment["id"], "Nat", reader)["items"]
    assert any(hit["lemma"]["id"] == receipt["claim_id"] for hit in hits)
    bundle = service.knowledge_bundle(experiment["id"], receipt["claim_id"], reader)
    assert bundle["candidate_source"] == source
    provider = LocalDockerWorkspaceProvider(
        docker_host=host, image_digest=image, timeout_seconds=180
    )
    try:
        await provider.create()
        await provider.upload_file(
            "consumer.lean",
            (
                bundle["candidate_source"] + "theorem use_known : True := by exact known_true\n"
            ).encode(),
            expected_execution_id=provider.execution_id,
        )
        result = await provider.run(
            CommandRequest(
                operation_id="reuse-known",
                argv=["lake", "--offline", "env", "lean", "/work/consumer.lean"],
                cwd="/opt/sources/physlib",
                timeout_seconds=120,
                max_output_bytes=65536,
            )
        )
        assert result.exit_code == 0, result.stderr
    finally:
        await provider.close()


def test_empty_accessible_knowledge_corpus_is_not_called_lexical_miss(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    result = service.search_knowledge(experiment["id"], "energy", actor)
    assert result["items"] == []
    assert result["reason_code"] == "empty_accessible_corpus"


def test_accepted_summary_is_compact_and_permission_checked(lab):
    service, _, experiment, _, (reader, _), receipt = accepted_fixture(lab)
    summary = service.accepted_proof_summary(experiment["id"], receipt["claim_id"], reader)
    assert summary["status"] == "verified"
    assert summary["receipt_id"] == receipt["id"]
    assert summary["recomposition_required"] is True
    assert "candidate_source" not in summary
    assert "native_checkpoint" not in str(summary)


def test_accepted_summary_does_not_release_private_peer_result(lab):
    from physharness.errors import HarnessError

    service, _, private, _, (outsider, _), private_receipt = accepted_fixture(lab, "none")
    with pytest.raises(HarnessError) as error:
        service.accepted_proof_summary(private["id"], private_receipt["claim_id"], outsider)
    assert error.value.code == "KNOWLEDGE_NOT_APPLICABLE"


def test_hidden_verified_claim_does_not_change_empty_search_diagnostics(lab):
    from physharness.storage import RecordRow

    service, _, experiment, _, (reader, _), receipt = accepted_fixture(lab, "none")
    with_hidden = service.search_knowledge(experiment["id"], "synthetic proof", reader)
    with service.db.transaction() as session:
        session.delete(session.get(RecordRow, receipt["claim_id"]))
    without_hidden = service.search_knowledge(experiment["id"], "synthetic proof", reader)
    assert with_hidden["items"] == without_hidden["items"] == []
    assert with_hidden["reason_code"] == without_hidden["reason_code"]


def test_corrupt_cross_experiment_proof_does_not_disclose_candidate(lab):
    from physharness.domain import BranchCreate, ExperimentCreate
    from physharness.storage import RecordRow

    service, author, origin, _, _, receipt = accepted_fixture(lab, "verified")
    consumer = service.create_experiment(
        ExperimentCreate(
            campaign_id=origin["campaign_id"],
            problem_id=origin["problem_id"],
            models=origin["models"],
            budget=origin["budget"],
            sharing="verified",
        ),
        author,
        "corrupt-consumer",
    )
    service.transition_experiment(consumer["id"], "start", 1, author, "corrupt-start")
    branch = service.create_branch(
        consumer["id"], BranchCreate(title="consumer", objective="review"), author, "branch"
    )
    reader = Principal(
        id="consumer-reader",
        project_id=author.project_id,
        role="agent",
        experiment_id=consumer["id"],
        branch_id=branch["id"],
    )
    candidate = service.get_record("artifact", receipt["artifact_id"], author)
    service.artifacts.path_for(candidate["sha256"]).write_bytes(b"corrupted")
    with_corrupt = service.search_knowledge(consumer["id"], "Nat", reader)
    with service.db.transaction() as session:
        session.delete(session.get(RecordRow, receipt["claim_id"]))
    without_claim = service.search_knowledge(consumer["id"], "Nat", reader)
    assert with_corrupt["items"] == without_claim["items"] == []
    assert with_corrupt["rejected_candidates"] == without_claim["rejected_candidates"] == []
    assert with_corrupt["reason_code"] == without_claim["reason_code"]


def test_accepted_summary_bounds_long_assumption_text(lab):
    from physharness.storage import RecordRow

    service, author, experiment, _, (reader, _), receipt = accepted_fixture(lab)
    claim = service.get_record("claim", receipt["claim_id"], author)
    with service.db.transaction() as session:
        for _kind, identifier in (
            ("claim", claim["id"]),
            ("problem", claim["problem_revision_id"]),
        ):
            row = session.get(RecordRow, identifier)
            service._replace(session, row, {"assumptions": ["A" * 100_000]})
    summary = service.accepted_proof_summary(experiment["id"], claim["id"], reader)
    assert len(summary["assumptions"][0]) <= 512
    assert summary["assumptions_truncated"] is True


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
    search = service.search_knowledge(consumer["id"], "Nat", agent)
    hits = search["items"]
    if shared:
        assert [hit["lemma"]["id"] for hit in hits] == [claim_id]
        assert (
            service.knowledge_bundle(consumer["id"], claim_id, agent)["receipt"]["id"]
            == accepted["id"]
        )
    else:
        assert hits == []
        assert search["reason_code"] == "empty_accessible_corpus"
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
        "missing_origin",
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
        elif tamper == "missing_origin":
            service._replace(session, claim, {"experiment_id": "nonexistent-origin"})
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


def _knowledge_consumer(service, author, origin, key):
    from physharness.domain import BranchCreate, ExperimentCreate

    consumer = service.create_experiment(
        ExperimentCreate(
            campaign_id=origin["campaign_id"],
            problem_id=origin["problem_id"],
            models=origin["models"],
            budget=origin["budget"],
            sharing="verified",
        ),
        author,
        f"{key}-consumer",
    )
    service.transition_experiment(consumer["id"], "start", 1, author, f"{key}-start")
    branch = service.create_branch(
        consumer["id"], BranchCreate(title="consumer", objective="review"), author, f"{key}-b"
    )
    return consumer, Principal(
        id=f"{key}-agent",
        project_id=author.project_id,
        role="agent",
        experiment_id=consumer["id"],
        branch_id=branch["id"],
    )


def test_ineligible_cross_experiment_claim_does_not_change_search_diagnostics(lab):
    import json

    from physharness.storage import RecordRow

    service, author, origin, _, _, receipt = accepted_fixture(lab, "verified", "kernel")
    consumer, agent = _knowledge_consumer(service, author, origin, "k1")
    with_claim = service.search_knowledge(consumer["id"], "Nat", agent)
    with service.db.transaction() as session:
        session.delete(session.get(RecordRow, receipt["claim_id"]))
    without_claim = service.search_knowledge(consumer["id"], "Nat", agent)
    assert with_claim == without_claim
    assert with_claim["reason_code"] == "empty_accessible_corpus"
    assert receipt["claim_id"] not in json.dumps(with_claim)


def test_claim_with_dangling_origin_experiment_is_skipped(lab):
    from physharness.storage import RecordRow

    service, author, origin, _, _, receipt = accepted_fixture(lab, "verified")
    consumer, agent = _knowledge_consumer(service, author, origin, "dangling")
    with service.db.transaction() as session:
        row = session.get(RecordRow, receipt["claim_id"])
        service._replace(session, row, {"experiment_id": "missing-experiment"})
    result = service.search_knowledge(consumer["id"], "Nat", agent)
    assert result["items"] == [] and result["rejected_candidates"] == []
    assert result["reason_code"] == "empty_accessible_corpus"
    assert receipt["claim_id"] not in str(result)


def test_verified_target_check_ignores_unrelated_receipts_without_loading_them(lab, monkeypatch):
    from physharness.storage import RecordRow

    service, author, experiment, _, _, receipt = accepted_fixture(lab)
    with service.db.transaction() as session:
        for i in range(1000):
            service._insert(
                session,
                "verification",
                author,
                {
                    "experiment_id": experiment["id"],
                    "status": "verified",
                    "assurance": "independent_kernel" if i % 2 else "kernel",
                    "target_digest": f"old-target-{i}",
                    "problem_revision_id": experiment["problem_id"],
                },
            )
    checked = []
    original = service._accepted_evidence
    monkeypatch.setattr(
        service, "_accepted_evidence", lambda *a, **k: checked.append(1) or original(*a, **k)
    )
    found = service.verified_target_receipt(experiment["id"], author)
    assert found["receipt_id"] == receipt["id"] and len(checked) == 1
    with service.db.transaction() as session:
        session.delete(session.get(RecordRow, receipt["id"]))
    assert service.verified_target_receipt(experiment["id"], author) is None
    assert len(checked) == 1
