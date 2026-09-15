"""Real canonical service/Comparator path with explicitly synthetic checker transport.

These tests establish protocol behavior only, never Lean or Linux qualification.
"""

import json

import pytest
from test_authority import operator
from test_core import setup_experiment
from test_verification import configured, fake_result, sha

from physharness.domain import ArtifactCreate, CampaignCreate, ExperimentCreate, ProblemCreate
from physharness.errors import HarnessError
from physharness.storage import RecordRow


def canonical_comparator(lab, tmp_path, monkeypatch):
    service, actor, reviewer = lab
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    verifier, req = configured(bundle)
    campaign = service.create_campaign(
        CampaignCreate(title="Identity", objective="Check identity", programs=["quantum"]),
        actor,
        "campaign",
    )
    source = (bundle / "Challenge.lean").read_bytes().decode("utf-8")
    problem = service.create_problem(
        ProblemCreate(
            campaign_id=campaign["id"],
            title="Identity",
            program="quantum",
            informal_statement="Identity is reflexive",
            formal_statement=source,
            target_theorem="identity",
            environment_digest=req.environment_digest,
        ),
        actor,
        "problem",
    )
    service.review_problem(
        problem["id"], "approved", "Synthetic fixture review", reviewer, "review"
    )
    problem = service.get_record("problem", problem["id"], actor)
    experiment = service.create_experiment(
        ExperimentCreate(
            campaign_id=campaign["id"],
            problem_id=problem["id"],
            models=[{"runtime": "responses", "model": "synthetic-fixture"}],
            budget={"max_cost_usd": "1", "max_concurrency": 1, "max_runtime_seconds": 120},
        ),
        actor,
        "experiment",
    )
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    manifest.update(
        protocol="physharness-comparator-v2",
        problem_revision_id=problem["id"],
        target_digest=problem["target_digest"],
        challenge_sha256=sha(source.encode("utf-8")),
    )
    raw = json.dumps(manifest).encode()
    (bundle / "manifest.json").write_bytes(raw)
    verifier.config = verifier.config.model_copy(update={"manifest_sha256": sha(raw)})
    service.verifier = verifier
    calls = []

    def synthetic_transport(request, manifest, env, files):
        calls.append(request)
        return fake_result(request)

    monkeypatch.setattr(verifier, "_run_container", synthetic_transport)
    return service, actor, experiment, problem, bundle, calls


def submit(service, actor, experiment, source, key="candidate"):
    artifact = service.create_artifact(
        ArtifactCreate(experiment_id=experiment["id"], kind="lean_source", content=source),
        actor,
        key,
    )
    receipt = service.verify_candidate(
        experiment["id"], artifact["id"], False, actor, f"verify-{key}"
    )
    return receipt


def test_canonical_review_reaches_synthetic_comparator(lab, tmp_path, monkeypatch):
    service, actor, experiment, problem, _, calls = canonical_comparator(lab, tmp_path, monkeypatch)
    receipt = submit(service, actor, experiment, problem["formal_statement"])
    result = service.process_verification(receipt["id"], operator(actor))
    assert result["status"] == "verified", result
    assert len(calls) == 1
    assert calls[0].target_digest == problem["target_digest"]
    assert calls[0].challenge_sha256 == sha(problem["formal_statement"].encode("utf-8"))
    assert calls[0].target_digest != calls[0].challenge_sha256
    assert calls[0].target_theorem == result["target_theorem"] == "identity"
    assert result["review_id"] == problem["review_id"]


@pytest.mark.parametrize(
    "tamper", ["target_digest", "challenge_sha256", "source", "environment", "theorem", "legacy"]
)
def test_trusted_bundle_tamper_fails_closed(lab, tmp_path, monkeypatch, tamper):
    service, actor, experiment, problem, bundle, calls = canonical_comparator(
        lab, tmp_path, monkeypatch
    )
    if tamper in {"source", "environment"}:
        path = bundle / ("Challenge.lean" if tamper == "source" else "environment.json")
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        manifest = json.loads((bundle / "manifest.json").read_bytes())
        if tamper == "theorem":
            manifest["theorem_names"] = ["different_theorem"]
        elif tamper == "legacy":
            manifest.pop("challenge_sha256")
            manifest.pop("protocol")
        else:
            manifest[tamper] = "f" * 64
        raw = json.dumps(manifest).encode()
        (bundle / "manifest.json").write_bytes(raw)
        service.verifier.config = service.verifier.config.model_copy(
            update={"manifest_sha256": sha(raw)}
        )
    receipt = submit(service, actor, experiment, problem["formal_statement"])
    result = service.process_verification(receipt["id"], operator(actor))
    assert result["status"] == "blocked" and result["code"] == "trusted_bundle_invalid"
    assert calls == []
    assert service.list_records("claim", actor) == []


def test_exact_candidate_limit_reaches_checker(lab, tmp_path, monkeypatch):
    service, actor, experiment, _, _, calls = canonical_comparator(lab, tmp_path, monkeypatch)
    receipt = submit(service, actor, experiment, "é" * 2_000_000)
    result = service.process_verification(receipt["id"], operator(actor))
    assert result["status"] == "verified", result
    assert len(calls[0].candidate_source) == 2_000_000


def test_oversized_candidate_is_rejected_before_queue(lab):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    with pytest.raises(HarnessError) as failure:
        submit(service, actor, experiment, " " * 2_000_001)
    assert failure.value.code == "CANDIDATE_TOO_LARGE"
    assert service.list_records("verification", actor) == []


@pytest.mark.parametrize("fault", ["legacy_oversized", "artifact_read", "legacy_receipt"])
def test_processing_fault_persists_terminal_diagnostic(lab, monkeypatch, fault):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    receipt = submit(service, actor, experiment, "proof")
    if fault == "legacy_oversized":
        large = service.create_artifact(
            ArtifactCreate(
                experiment_id=experiment["id"], kind="lean_source", content=" " * 2_000_001
            ),
            actor,
            "legacy-large",
        )
        with service.db.transaction() as session:
            service._replace(
                session,
                session.get(RecordRow, receipt["id"]),
                {
                    "artifact_id": large["id"],
                    "candidate_sha256": large["sha256"],
                },
            )
        expected = "candidate_too_large"
    elif fault == "legacy_receipt":
        with service.db.transaction() as session:
            row = session.get(RecordRow, receipt["id"])
            payload = dict(row.payload)
            for field in ("challenge_sha256", "review_id", "target_theorem"):
                payload.pop(field, None)
            row.payload = payload
        expected = "verification_receipt_incompatible"
    else:

        def unavailable(*args):
            raise OSError("synthetic artifact read fault")

        monkeypatch.setattr(service, "artifact_content", unavailable)
        expected = "candidate_unavailable"
    try:
        result = service.process_verification(receipt["id"], operator(actor))
    except Exception as exc:
        pytest.fail(f"processing escaped instead of blocking receipt: {type(exc).__name__}")
    assert result["status"] == "blocked"
    assert result["code"] == expected
    assert result["remediation"]
    assert service.get_record("verification", receipt["id"], actor)["status"] == "blocked"
    assert service.list_records("claim", actor) == []


@pytest.mark.parametrize(
    "field",
    ["review_id", "target_theorem", "formal_statement", "target_digest", "environment_digest"],
)
@pytest.mark.parametrize("timing", ["before", "during"])
def test_review_and_source_pins_survive_processing(lab, tmp_path, monkeypatch, field, timing):
    service, actor, experiment, problem, _, calls = canonical_comparator(lab, tmp_path, monkeypatch)
    receipt = submit(service, actor, experiment, problem["formal_statement"])

    def tamper():
        with service.db.transaction() as session:
            service._replace(
                session,
                session.get(RecordRow, problem["id"]),
                {
                    field: "f" * 64 if field.endswith("digest") else "changed",
                },
            )

    if timing == "before":
        tamper()
    else:

        def synthetic_transport(request, *args):
            calls.append(request)
            tamper()
            return fake_result(request)

        monkeypatch.setattr(service.verifier, "_run_container", synthetic_transport)
    result = service.process_verification(receipt["id"], operator(actor))
    assert result["status"] == "blocked" and result["code"] == "review_changed"
    assert result["remediation"]
    if timing == "before":
        assert calls == []
    assert service.list_records("claim", actor) == []


@pytest.mark.parametrize(
    "field", ["target_digest", "challenge_sha256", "candidate_sha256", "environment_digest"]
)
def test_acceptance_rejects_checker_identity_mismatch(lab, tmp_path, monkeypatch, field):
    from physharness.verification.boundary import outcome

    service, actor, experiment, problem, _, _ = canonical_comparator(lab, tmp_path, monkeypatch)
    receipt = submit(service, actor, experiment, problem["formal_statement"])

    class SyntheticVerifier:
        def verify(self, request):
            return outcome(
                request,
                "verified",
                "synthetic",
                "Synthetic response",
                "",
                assurance="kernel",
                checker_versions={"lean": "synthetic", "comparator": "synthetic"},
            ).model_copy(update={field: "f" * 64})

    service.verifier = SyntheticVerifier()
    result = service.process_verification(receipt["id"], operator(actor))
    assert result["status"] == "blocked" and result["code"] == "checker_identity_mismatch"
    assert result["remediation"]
    assert service.list_records("claim", actor) == []


def test_replacing_approved_review_record_blocks_acceptance(lab, tmp_path, monkeypatch):
    service, actor, experiment, problem, _, calls = canonical_comparator(lab, tmp_path, monkeypatch)
    receipt = submit(service, actor, experiment, problem["formal_statement"])
    with service.db.transaction() as session:
        service._replace(
            session, session.get(RecordRow, problem["review_id"]), {"decision": "rejected"}
        )
    result = service.process_verification(receipt["id"], operator(actor))
    assert result["status"] == "blocked" and result["code"] == "review_invalid"
    assert calls == []
