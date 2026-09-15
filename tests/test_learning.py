"""Synthetic local dataset/ranker tests; these are not research improvement evidence."""

import pytest
from test_evaluation import evidence, records, sha


def api():
    from physharness import learning

    assert hasattr(learning, "export_dataset"), "learning primitives are absent"
    return learning


def learning_records():
    rows = records("p1", "quantum amplitude") + records("p2", "classical translation")
    for row in rows:
        if row["kind"] == "artifact":
            row["sha256"] = sha(
                "quantum proof" if row["id"] == "artifact-p1" else "classical proof"
            )
        elif row["kind"] == "verification":
            row["candidate_sha256"] = sha(
                "quantum proof" if row["id"] == "receipt-p1" else "classical proof"
            )
    return rows


def dataset(tmp_path):
    v = api()
    store = evidence(learning_records())
    selections = [
        v.DatasetSelection(problem_id="p1", receipt_id="receipt-p1", family_id="f1", split="train"),
        v.DatasetSelection(
            problem_id="p2", receipt_id="receipt-p2", family_id="f2", split="holdout"
        ),
    ]
    grants = [
        v.LicenseGrant(
            artifact_sha256=sha(text),
            license_id="MIT",
            approved_by="curator",
            attribution="Synthetic fixture",
            training_allowed=True,
        )
        for text in ("quantum proof", "classical proof")
    ]
    return v.export_dataset(
        store,
        selections,
        grants,
        {sha(text): text.encode() for text in ("quantum proof", "classical proof")},
        tmp_path,
        mode="synthetic",
    )


def test_export_requires_licenses_and_preserves_provenance(tmp_path):
    v = api()
    result = dataset(tmp_path)
    assert result.manifest.record_count == 2
    assert result.manifest.snapshot_digest == evidence(learning_records()).snapshot_digest
    assert result.records[0].receipt_id == "receipt-p1"
    assert result.records[0].license_id == "MIT"
    with pytest.raises(ValueError, match="license"):
        v.export_dataset(
            evidence(),
            [
                v.DatasetSelection(
                    problem_id="p1", receipt_id="receipt-p1", family_id="f1", split="train"
                )
            ],
            [],
            {sha("proof"): b"proof"},
            tmp_path / "bad",
        )


def test_export_rejects_invalid_receipts_and_changed_proof_bytes(tmp_path):
    v = api()
    grant = v.LicenseGrant(
        artifact_sha256=sha("proof"),
        license_id="MIT",
        approved_by="curator",
        attribution="Fixture",
        training_allowed=True,
    )
    selection = v.DatasetSelection(
        problem_id="p1", receipt_id="receipt-p1", family_id="f1", split="train"
    )
    with pytest.raises(ValueError, match="digest"):
        v.export_dataset(evidence(), [selection], [grant], {sha("proof"): b"changed"}, tmp_path)
    rows = records()
    rows[-1]["status"] = "rejected"
    with pytest.raises(ValueError, match="receipt"):
        v.export_dataset(evidence(rows), [selection], [grant], {sha("proof"): b"proof"}, tmp_path)


def test_ranker_fits_only_training_partition_and_roundtrips(tmp_path):
    v = api()
    result = dataset(tmp_path / "dataset")
    ranker = v.TfidfRetriever.fit(result)
    assert ranker.training_ids == ["p1"] and "translation" not in ranker.vocabulary
    assert ranker.rank("quantum amplitude", k=1)[0].document_id == "p1"
    path = tmp_path / "ranker.json"
    ranker.save(path)
    assert v.TfidfRetriever.load(path).rank("quantum") == ranker.rank("quantum")
    assert ranker.model_digest == v.TfidfRetriever.fit(result).model_digest


def test_ranker_load_rejects_tampering(tmp_path):
    v = api()
    ranker = v.TfidfRetriever.fit(dataset(tmp_path / "data"))
    path = tmp_path / "ranker.json"
    ranker.save(path)
    path.write_text(path.read_text().replace("quantum", "tainted"))
    with pytest.raises(ValueError, match="digest"):
        v.TfidfRetriever.load(path)


def test_gate_blocks_training_family_leakage_and_small_samples(tmp_path):
    v = api()
    ranker = v.TfidfRetriever.fit(dataset(tmp_path / "dataset"))
    query = v.RetrievalCase(
        id="q1",
        family_id="f1",
        query="quantum",
        relevant_ids=["p1"],
        split="holdout",
        annotation_source="synthetic-fixture",
    )
    with pytest.raises(ValueError, match="family"):
        v.evaluate_retriever(ranker, [query])
    clean = query.model_copy(update={"family_id": "unseen"})
    score = v.evaluate_retriever(ranker, [clean])
    decision = v.promotion_gate(score, score, min_cases=20)
    assert decision.status == "blocked" and decision.reason == "insufficient_holdout"


def test_rollback_manifest_preserves_previous_model(tmp_path):
    v = api()
    ranker = v.TfidfRetriever.fit(dataset(tmp_path / "dataset"))
    query = v.RetrievalCase(
        id="q1",
        family_id="unseen",
        query="quantum",
        relevant_ids=["p1"],
        split="holdout",
        annotation_source="synthetic-fixture",
    )
    score = v.evaluate_retriever(ranker, [query])
    decision = v.promotion_gate(score, score, min_cases=1)
    assert decision.status == "rejected"
    rollback = v.rollback_manifest(
        previous_model_digest=ranker.model_digest,
        candidate_model_digest=ranker.model_digest,
        decision=decision,
    )
    assert rollback.active_model_digest == ranker.model_digest
    assert rollback.rollback_model_digest == ranker.model_digest


def test_mutated_fitted_state_cannot_keep_old_model_identity(tmp_path):
    v = api()
    ranker = v.TfidfRetriever.fit(dataset(tmp_path))
    ranker.state.vocabulary["quantum"] = 999.0
    with pytest.raises(ValueError, match="integrity"):
        ranker.rank("quantum")


def test_rollback_requires_baseline_identity(tmp_path):
    v = api()
    ranker = v.TfidfRetriever.fit(dataset(tmp_path))
    query = v.RetrievalCase(
        id="q1",
        family_id="new",
        query="quantum",
        relevant_ids=["p1"],
        split="holdout",
        annotation_source="synthetic",
    )
    score = v.evaluate_retriever(ranker, [query])
    gate = v.promotion_gate(score, score, min_cases=1)
    with pytest.raises(ValueError, match="baseline"):
        v.rollback_manifest(
            previous_model_digest="a" * 64,
            candidate_model_digest=ranker.model_digest,
            decision=gate,
        )


def test_real_fitted_variants_can_improve_heldout_retrieval(tmp_path):
    v = api()
    rows = learning_records()
    contents = {
        "p1": b"classical translation classical translation classical translation",
        "p2": b"quantum amplitude quantum amplitude quantum amplitude",
    }
    for row in rows:
        if row["kind"] == "artifact":
            row["sha256"] = sha(contents[row["id"].removeprefix("artifact-")].decode())
        if row["kind"] == "verification":
            row["candidate_sha256"] = sha(contents[row["problem_revision_id"]].decode())
    grants = [
        v.LicenseGrant(
            artifact_sha256=sha(content.decode()),
            license_id="MIT",
            approved_by="curator",
            attribution="Synthetic test",
            training_allowed=True,
        )
        for content in contents.values()
    ]
    selections = [
        v.DatasetSelection(
            problem_id=p, receipt_id=f"receipt-{p}", family_id=f"train-{p}", split="train"
        )
        for p in contents
    ]
    bundle = v.export_dataset(
        evidence(rows),
        selections,
        grants,
        {sha(content.decode()): content for content in contents.values()},
        tmp_path,
        mode="synthetic",
    )
    baseline = v.TfidfRetriever.fit(bundle)
    candidate = v.TfidfRetriever.fit(bundle, include_proof=False)
    cases = [
        v.RetrievalCase(
            id=f"q{i}",
            family_id=f"heldout-{i}",
            query=query,
            relevant_ids=[p],
            split="holdout",
            annotation_source="synthetic-test",
        )
        for i, (p, query) in enumerate(
            [("p1", "quantum amplitude"), ("p2", "classical translation")]
        )
    ]
    candidate_score = v.evaluate_retriever(candidate, cases)
    baseline_score = v.evaluate_retriever(baseline, cases)
    gate = v.promotion_gate(candidate_score, baseline_score, min_cases=2, seed=23)
    assert gate.status == "approved" and gate.interval_low > 0
    assert gate.production_qualified is False and gate.mode == "synthetic"


def test_same_proof_content_cannot_cross_holdout_partition(tmp_path):
    v = api()
    rows = records("p1", "first") + records("p2", "second")
    grant = v.LicenseGrant(
        artifact_sha256=sha("proof"),
        license_id="MIT",
        approved_by="curator",
        attribution="Synthetic",
        training_allowed=True,
    )
    selections = [
        v.DatasetSelection(problem_id="p1", receipt_id="receipt-p1", family_id="f1", split="train"),
        v.DatasetSelection(
            problem_id="p2", receipt_id="receipt-p2", family_id="f2", split="holdout"
        ),
    ]
    with pytest.raises(ValueError, match="content crosses"):
        v.export_dataset(evidence(rows), selections, [grant], {sha("proof"): b"proof"}, tmp_path)
