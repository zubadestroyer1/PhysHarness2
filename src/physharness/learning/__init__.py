"""Licensed canonical dataset export, fitted lexical retrieval, and held-out gates."""

from .datasets import DatasetSelection, LicenseGrant, export_dataset
from .retrieval import (
    RetrievalCase,
    TfidfRetriever,
    evaluate_retriever,
    promotion_gate,
    rollback_manifest,
)

__all__ = [
    "DatasetSelection",
    "LicenseGrant",
    "export_dataset",
    "RetrievalCase",
    "TfidfRetriever",
    "evaluate_retriever",
    "promotion_gate",
    "rollback_manifest",
]
