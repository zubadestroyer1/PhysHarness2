import hashlib
import importlib.util

import pytest


def api():
    assert importlib.util.find_spec("physharness.knowledge"), "knowledge is not implemented"
    from physharness import knowledge

    return knowledge


def test_ingestion_preserves_unicode_crlf_and_exact_spans():
    text = "# Energy\r\n\r\nΔE = 0.\r\nSecond line.\r\n"
    source = api().ingest_text(
        text, format="markdown", uri="local:energy", revision="r1", chunk_chars=14
    )
    assert source.document.content_sha256 == hashlib.sha256(text.encode()).hexdigest()
    assert "".join(s.text for s in source.spans) == text
    assert all(text[s.start : s.end] == s.text for s in source.spans)
    assert source.spans[-1].end_line == 4


def test_latex_ingestion_does_not_execute_commands(tmp_path):
    marker = tmp_path / "must-not-exist"
    text = "\\write18{touch " + str(marker) + "}\n\\section{Identity}\nx=x\n"
    out = api().ingest_text(text, format="latex", uri="local:latex", revision="r1")
    assert out.spans[0].text == text
    assert not marker.exists()


def test_pdf_and_invalid_utf8_have_actionable_errors():
    k = api()
    for content, format, code in [
        (b"%PDF-", "pdf", "pdf_ingestion_unavailable"),
        (b"\xff", "markdown", "invalid_source_encoding"),
    ]:
        with pytest.raises(Exception) as err:
            k.ingest_bytes(content, format=format, uri="local:file", revision="r1")
        assert err.value.code == code and err.value.remediation


def lemma(id, **overrides):
    values = dict(
        id=id,
        revision="r1",
        environment_digest="a" * 64,
        target_digest="b" * 64,
        statement="Translation composition on Nat",
        type_signature="Nat → Nat",
        status="verified",
        receipt_id="receipt-" + id,
        provenance_uri="local:reviewed-library",
        dependencies=[],
        source_spans=[],
    )
    values.update(overrides)
    return api().LemmaRecord(**values)


def test_retrieval_filters_before_ranking_and_preserves_revisions():
    index = api().LemmaIndex(
        [
            lemma("ok"),
            lemma("old", revision="r0"),
            lemma("other-env", environment_digest="c" * 64),
            lemma("guess", status="conjecture", receipt_id=None),
            lemma("unrelated", statement="Bounded energy", type_signature="Rat"),
        ]
    )
    hits = index.search(
        "translation",
        environment_digest="a" * 64,
        revisions={"ok": "r1", "old": "r1", "guess": "r1", "unrelated": "r1"},
    )
    assert [h.lemma.id for h in hits] == ["ok"]
    assert hits[0].lemma.provenance_uri == "local:reviewed-library"


def test_type_and_dependency_queries_return_exact_revision_edges():
    ref = api().LemmaRef(id="base", revision="r2")
    index = api().LemmaIndex([lemma("uses", dependencies=[ref]), lemma("unused")])
    hits = index.search("", environment_digest="a" * 64, type_query="Nat", requires=[ref])
    assert [h.lemma.id for h in hits] == ["uses"]
    assert (
        index.search(
            "", environment_digest="a" * 64, requires=[api().LemmaRef(id="base", revision="r1")]
        )
        == []
    )


def test_revision_conflict_and_unreceipted_verified_records_are_rejected():
    with pytest.raises(ValueError):
        api().LemmaIndex([lemma("same"), lemma("same", statement="changed")])
    with pytest.raises(ValueError):
        lemma("forged", receipt_id=None)


def test_correspondence_binds_exact_span_and_requires_review():
    k = api()
    source = k.ingest_text(
        "Conservation of energy.", format="markdown", uri="local:paper", revision="r1"
    )
    span = source.spans[0]
    correspondence = k.SourceCorrespondence(
        problem_revision_id="p1",
        target_digest="b" * 64,
        source_span=span,
        interpretation="Energy is constant under the listed assumptions.",
        assumptions=["closed system"],
    )
    assert correspondence.review_status == "pending"
    with pytest.raises(ValueError):
        k.SourceSpan(**{**span.model_dump(), "text": "a changed claim"})


def test_failed_approach_stays_scoped_and_cannot_become_a_lemma():
    k = api()
    failure = k.FailedApproach(
        problem_revision_id="p1",
        environment_digest="a" * 64,
        method="floating point search",
        observation="No witness found in sampled grid.",
        limitations=["Finite grid is incomplete"],
        artifact_sha256="b" * 64,
    )
    assert failure.evidence_kind == "failed_approach"
    with pytest.raises(ValueError):
        k.LemmaRecord.model_validate(failure.model_dump())


def test_search_results_do_not_mutate_canonical_index_and_provenance_is_filtered():
    index = api().LemmaIndex([lemma("first"), lemma("second", provenance_uri="local:other")])
    results = index.search(
        "", environment_digest="a" * 64, provenance_uris=["local:reviewed-library"]
    )
    assert [h.lemma.id for h in results] == ["first"]
    results[0].lemma.assumptions.append("forged assumption")
    fresh = index.search("", environment_digest="a" * 64)
    assert all(not hit.lemma.assumptions for hit in fresh)
