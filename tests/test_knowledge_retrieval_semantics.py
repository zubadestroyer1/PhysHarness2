import pytest

from physharness.knowledge import LemmaIndex, LemmaRecord


def _lemma(id, signature):
    return LemmaRecord(
        id=id,
        revision="r1",
        environment_digest="a" * 64,
        target_digest="b" * 64,
        statement="translation theorem",
        type_signature=signature,
        status="verified",
        receipt_id="receipt-" + id,
        provenance_uri="physharness:accepted:" + id,
    )


def test_explicit_lexical_filter_and_empty_reason_are_reported():
    index = LemmaIndex([_lemma("nat", "Nat -> Nat")])
    result = index.search_with_diagnostics(
        "translation", environment_digest="a" * 64, lexical_type_filter="Real"
    )
    assert result["hits"] == []
    assert result["reason_code"] == "no_lexical_match"
    assert result["mechanism"] == "lexical_accepted_result_search"
    assert result["environment_digest"] == "a" * 64


def test_unelaborated_type_query_is_explicitly_unavailable():
    index = LemmaIndex([_lemma("nat", "Nat -> Nat")])
    with pytest.raises(ValueError, match="Lean elaboration"):
        index.search_type("Nat -> Nat", environment_digest="a" * 64)
