"""Service acceptance authority with controlled checker transports, never Lean qualification."""

from types import SimpleNamespace

import pytest
from test_core import setup_experiment

from physharness.domain import ArtifactCreate, Principal
from physharness.verification import VerificationOutcome


def queued(lab, *, approved=True, publication=False):
    service, actor, _ = lab
    experiment, problem = setup_experiment(lab, approved=approved)
    artifact = service.create_artifact(
        ArtifactCreate(experiment_id=experiment["id"], kind="lean_source", content="proof"),
        actor,
        "candidate",
    )
    receipt = service.verify_candidate(
        experiment["id"], artifact["id"], publication, actor, "submit"
    )
    operator = Principal(id="acceptance", project_id=actor.project_id, role="operator")
    return service, actor, problem, receipt, operator


def accepted(request, **changes):
    fields = dict(
        status="verified",
        assurance="independent_kernel",
        code="kernel_checked",
        message="Controlled transport for acceptance integration tests",
        remediation="",
        challenge_sha256=request.challenge_sha256,
        target_digest=request.target_digest,
        environment_digest=request.environment_digest,
        candidate_sha256=request.candidate_sha256,
        axioms=[],
        checker_versions={"lean": "test-pin", "comparator": "test-pin", "nanoda": "test-pin"},
    )
    fields.update(changes)
    return VerificationOutcome(**fields)


def mutate_problem(service, problem, operator, **fields):
    with service.db.transaction() as session:
        row = service._get(session, "problem", problem["id"], operator)
        service._replace(session, row, fields)


def test_acceptance_enforces_semantic_review_before_calling_checker(lab):
    service, actor, _, receipt, operator = queued(lab, approved=False)
    service.verifier = SimpleNamespace(verify=accepted)
    result = service.process_verification(receipt["id"], operator)
    assert (result["status"], result["code"]) == ("blocked", "semantic_review_required")
    assert service.list_records("claim", actor) == []


def test_review_replacement_after_submission_requires_fresh_verification(lab):
    service, actor, problem, receipt, operator = queued(lab)
    service.review_problem(problem["id"], "approved", "New expert review", lab[2], "rereview")
    service.verifier = SimpleNamespace(verify=accepted)
    result = service.process_verification(receipt["id"], operator)
    assert (result["status"], result["code"]) == ("blocked", "review_changed")
    assert service.list_records("claim", actor) == []


def test_environment_change_during_checker_run_cannot_publish_claim(lab):
    service, actor, problem, receipt, operator = queued(lab)

    def verify(request):
        mutate_problem(service, problem, operator, environment_digest="f" * 64)
        return accepted(request)

    service.verifier = SimpleNamespace(verify=verify)
    result = service.process_verification(receipt["id"], operator)
    assert (result["status"], result["code"]) == ("blocked", "review_changed")
    assert service.list_records("claim", actor) == []


@pytest.mark.parametrize(
    "field", ["target_digest", "challenge_sha256", "candidate_sha256", "environment_digest"]
)
def test_mismatched_checker_identity_has_stable_diagnostic_code(lab, field):
    service, actor, _, receipt, operator = queued(lab)
    service.verifier = SimpleNamespace(
        verify=lambda request: accepted(request, **{field: "f" * 64})
    )
    result = service.process_verification(receipt["id"], operator)
    assert (result["status"], result["code"]) == ("blocked", "checker_identity_mismatch")
    assert service.list_records("claim", actor) == []


def test_failed_candidate_read_is_persisted_as_blocked_receipt(lab, monkeypatch):
    service, actor, _, receipt, operator = queued(lab)

    def corrupt_read(*args):
        raise OSError("Artifact storage unavailable")

    monkeypatch.setattr(service, "artifact_content", corrupt_read)
    result = service.process_verification(receipt["id"], operator)
    assert (result["status"], result["code"]) == ("blocked", "candidate_unavailable")
    assert service.get_record("verification", receipt["id"], actor)["status"] == "blocked"
    assert service.list_records("claim", actor) == []


def test_successful_receipt_and_claim_are_atomic_and_repeatable(lab):
    service, actor, problem, receipt, operator = queued(lab, publication=True)
    service.verifier = SimpleNamespace(verify=accepted)
    result = service.process_verification(receipt["id"], operator)
    assert result["status"] == "verified"
    assert result["review_id"] == service.get_record("problem", problem["id"], actor)["review_id"]
    assert service.process_verification(receipt["id"], operator) == result
    claims = service.list_records("claim", actor)
    assert len(claims) == 1
    assert claims[0]["verification_id"] == receipt["id"]


def test_publication_downgrade_keeps_a_typed_blocked_receipt(lab):
    service, actor, _, receipt, operator = queued(lab, publication=True)
    service.verifier = SimpleNamespace(verify=lambda request: accepted(request, assurance="kernel"))
    result = service.process_verification(receipt["id"], operator)
    assert (result["status"], result["code"]) == ("blocked", "assurance_downgrade")
    assert service.list_records("claim", actor) == []


def load_qualification_runner():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "infra/run_qualified_lean.py"
    spec = importlib.util.spec_from_file_location("qualified_integration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_engineering_case_does_not_count_preflight_failure_as_an_attack():
    runner = load_qualification_runner()
    assert hasattr(runner, "check_case_outcome"), "case provenance validation missing"
    from physharness.verification import EngineeringRequest
    from physharness.verification.boundary import outcome

    req = EngineeringRequest(
        problem_revision_id="engineering",
        target_digest="a" * 64,
        challenge_sha256="b" * 64,
        environment_digest="c" * 64,
        candidate_sha256="d" * 64,
        candidate_source="bad",
    )
    result = outcome(req, "rejected", "candidate_digest_mismatch", "bad bytes", "repair")
    with pytest.raises(ValueError, match="comparator"):
        runner.check_case_outcome(
            {
                "id": "attack",
                "expected_status": "rejected",
                "expected_code": "candidate_digest_mismatch",
            },
            result,
        )


def test_engineering_case_checks_exact_code_even_when_status_matches():
    runner = load_qualification_runner()
    assert hasattr(runner, "check_case_outcome"), "case result validation missing"
    from physharness.verification import EngineeringRequest
    from physharness.verification.boundary import outcome

    req = EngineeringRequest(
        problem_revision_id="engineering",
        target_digest="a" * 64,
        challenge_sha256="b" * 64,
        environment_digest="c" * 64,
        candidate_sha256="d" * 64,
        candidate_source="bad",
    )
    result = outcome(req, "blocked", "container_failed", "daemon unavailable", "repair")
    with pytest.raises(RuntimeError, match="match"):
        runner.check_case_outcome(
            {
                "id": "attack",
                "expected_status": "blocked",
                "expected_code": "comparator_failed",
                "required_diagnostic_substrings": ["Illegal axiom detected: 'sorryAx'"],
            },
            result,
        )


def test_checkpoint_failure_cannot_leave_a_passing_current_run(tmp_path, monkeypatch):
    import json

    runner = load_qualification_runner()
    destination = tmp_path / "report.json"
    destination.write_text('{"status":"passed","run_id":"stale"}')
    write = runner._write_report
    writes = 0

    def fail_second_checkpoint(output, report):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("Simulated checkpoint fsync failure")
        write(output, report)

    def progress_then_fail(output, report):
        report["results"].append({"id": "partial", "outcome": "observed"})
        runner._write_report(output, report)

    monkeypatch.setattr(runner, "_write_report", fail_second_checkpoint)
    monkeypatch.setattr(runner, "_run_cases", progress_then_fail)
    with pytest.raises(OSError, match="checkpoint"):
        runner.run_from_environment(destination)
    current = json.loads(destination.read_bytes())
    assert current["status"] == "blocked"
    assert current["run_id"] != "stale"
    assert current["production_qualified"] is False
    assert current["results"] == [{"id": "partial", "outcome": "observed"}]
    assert not list(tmp_path.glob(".qualification-*"))


def test_acceptance_commit_failure_rolls_back_claim_and_receipt_together(lab, monkeypatch):
    service, actor, _, receipt, operator = queued(lab)
    service.verifier = SimpleNamespace(verify=accepted)
    event = service._event

    def fail_event(session, event_actor, op, kind, aggregate, payload, **kwargs):
        if kind == "verification.verified":
            raise OSError("Simulated receipt checkpoint failure")
        return event(session, event_actor, op, kind, aggregate, payload, **kwargs)

    monkeypatch.setattr(service, "_event", fail_event)
    with pytest.raises(OSError, match="checkpoint"):
        service.process_verification(receipt["id"], operator)
    assert service.get_record("verification", receipt["id"], actor)["status"] == "queued"
    assert service.list_records("claim", actor) == []
    monkeypatch.setattr(service, "_event", event)
    assert service.process_verification(receipt["id"], operator)["status"] == "verified"
    assert len(service.list_records("claim", actor)) == 1


@pytest.mark.integration
def test_postgresql_review_update_cannot_cross_acceptance_commit(tmp_path, monkeypatch):
    """Use two real transactions; SQLite's global write lock cannot exercise this race."""
    import os
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4

    from sqlalchemy import create_engine, event
    from sqlalchemy.exc import DBAPIError

    from physharness.artifacts import LocalArtifactStore
    from physharness.service import HarnessService
    from physharness.storage import Database

    url = os.environ.get("PHYSHARNESS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("No dedicated PostgreSQL endpoint for acceptance lock regression")
    schema = "acceptance_lock_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    db = Database(url)

    @event.listens_for(db.engine, "connect")
    def configure(connection, record):
        # Connection settings must survive the deliberately rolled-back lock timeout.
        previous = connection.autocommit
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{schema}"')
                cursor.execute("SET lock_timeout TO '250ms'")
        finally:
            connection.autocommit = previous

    try:
        db.create_schema()
        service = HarnessService(db, LocalArtifactStore(tmp_path / "artifacts"))
        actor = Principal(id="researcher", project_id="lock-test", role="researcher")
        reviewer = Principal(id="reviewer", project_id="lock-test", role="reviewer")
        lab = service, actor, reviewer
        service, actor, problem, receipt, operator = queued(lab)
        service.verifier = SimpleNamespace(verify=accepted)
        replace = service._replace
        review_was_locked = []

        def concurrent_review():
            try:
                service.review_problem(
                    problem["id"], "approved", "Concurrent review", reviewer, "concurrent-review"
                )
            except DBAPIError as error:
                assert error.orig.sqlstate == "55P03", str(error)
                return True
            return False

        with ThreadPoolExecutor(max_workers=1) as pool:

            def at_receipt_write(session, row, values, *args, **kwargs):
                if row.kind == "verification" and values.get("status") == "verified":
                    review_was_locked.append(pool.submit(concurrent_review).result(timeout=5))
                return replace(session, row, values, *args, **kwargs)

            monkeypatch.setattr(service, "_replace", at_receipt_write)
            result = service.process_verification(receipt["id"], operator)
        assert review_was_locked == [True]
        assert result["status"] == "verified"
        # The lock ends with acceptance; a later review is a distinct successful revision.
        changed = service.review_problem(
            problem["id"], "approved", "Later review", reviewer, "later-review"
        )
        assert changed["id"] != result["review_id"]
    finally:
        db.engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()
