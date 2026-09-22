"""Source ingestion and provenance-preserving retrieval; no acceptance authority."""

from .index import LemmaIndex, LemmaRecord, LemmaRef, SearchHit
from .sources import (
    FailedApproach,
    IngestedSource,
    SourceCorrespondence,
    SourceDocument,
    SourceSpan,
    ingest_bytes,
    ingest_text,
)

__all__ = [
    "FailedApproach",
    "IngestedSource",
    "LemmaIndex",
    "LemmaRecord",
    "LemmaRef",
    "SearchHit",
    "SourceCorrespondence",
    "SourceDocument",
    "SourceSpan",
    "ingest_bytes",
    "ingest_text",
]
