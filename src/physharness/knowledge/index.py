"""Deterministic retrieval over caller-supplied canonical record snapshots.

Receipt IDs are provenance references, not authenticated proof receipts. The caller
must obtain these records from the trusted application service, never worker payloads.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import Field, model_validator

from .sources import Digest, Record, SourceSpan

Status = Literal["verified", "conditional", "conjecture", "rejected"]


class LemmaRef(Record):
    id: str = Field(min_length=1)
    revision: str = Field(min_length=1)


class LemmaRecord(LemmaRef):
    environment_digest: Digest
    target_digest: Digest
    statement: str = Field(min_length=1, max_length=100_000)
    type_signature: str = Field(min_length=1, max_length=100_000)
    status: Status
    receipt_id: str | None = None
    provenance_uri: str = Field(min_length=1)
    dependencies: list[LemmaRef] = Field(default_factory=list, max_length=1000)
    source_spans: list[SourceSpan] = Field(default_factory=list, max_length=1000)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def acceptance_reference(self):
        if self.status == "verified" and not self.receipt_id:
            raise ValueError("verified canonical records require a receipt reference")
        return self


class SearchHit(Record):
    lemma: LemmaRecord
    score: float
    matched_terms: list[str]


def tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


class LemmaIndex:
    def __init__(self, records: Iterable[LemmaRecord | dict]):
        self._records = {}
        for raw in records:
            record = LemmaRecord.model_validate(raw).model_copy(deep=True)
            key = (record.id, record.revision)
            if key in self._records and self._records[key] != record:
                raise ValueError("conflicting canonical records for one lemma revision")
            self._records[key] = record

    def search(
        self,
        query: str,
        *,
        environment_digest: str,
        statuses: Iterable[Status] = ("verified",),
        revisions: Mapping[str, str] | None = None,
        type_query: str | None = None,
        lexical_type_filter: str | None = None,
        requires: Iterable[LemmaRef] = (),
        provenance_uris: Iterable[str] | None = None,
        limit: int = 20,
    ) -> list[SearchHit]:
        if not re.fullmatch(r"[0-9a-f]{64}", environment_digest):
            raise ValueError("an exact environment digest is required")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be from 1 to 1000")
        statuses = set(statuses)
        if not statuses <= {"verified", "conditional", "conjecture", "rejected"}:
            raise ValueError("unknown knowledge status")
        refs = {(r.id, r.revision) for r in requires}
        provenance = set(provenance_uris) if provenance_uris is not None else None
        if type_query and lexical_type_filter:
            raise ValueError("Use one lexical type filter")
        # type_query is a legacy lexical alias. New callers name this filter honestly.
        terms, type_terms = tokens(query), tokens(lexical_type_filter or type_query or "")
        hits = []
        for lemma in self._records.values():
            if lemma.environment_digest != environment_digest or lemma.status not in statuses:
                continue
            if revisions is not None and revisions.get(lemma.id) != lemma.revision:
                continue
            if provenance is not None and lemma.provenance_uri not in provenance:
                continue
            if not refs <= {(r.id, r.revision) for r in lemma.dependencies}:
                continue
            type_tokens = tokens(lemma.type_signature)
            if not type_terms <= type_tokens:
                continue
            statement_tokens = tokens(lemma.statement)
            matches = terms & (statement_tokens | type_tokens)
            if terms and not matches:
                continue
            score = float(2 * len(terms & statement_tokens) + len(terms & type_tokens))
            hits.append(
                SearchHit(
                    lemma=lemma.model_copy(deep=True), score=score, matched_terms=sorted(matches)
                )
            )
        return sorted(hits, key=lambda h: (-h.score, h.lemma.id, h.lemma.revision))[:limit]

    def search_with_diagnostics(self, query: str, **filters) -> dict:
        hits = self.search(query, **filters)
        return {
            "hits": hits,
            "reason_code": None if hits else "no_lexical_match",
            "mechanism": "lexical_accepted_result_search",
            "environment_digest": filters["environment_digest"],
            "lexical_type_filter": filters.get("lexical_type_filter") or filters.get("type_query"),
        }

    def search_type(self, expression: str, *, environment_digest: str) -> list[SearchHit]:
        """Type-directed retrieval needs Lean elaboration in the exact pinned image."""
        raise ValueError(
            "Lean elaboration is required for type-directed search; use check_lean_type "
            "in the pinned workbench before interpreting lexical hits"
        )
