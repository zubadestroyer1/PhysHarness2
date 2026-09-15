"""Offline experiment design and receipt-backed evaluation, without provider calls."""

from .evidence import CanonicalEvidence, EvidenceValidation
from .portfolio import (
    ArmSpec,
    AttemptObservation,
    AttemptPlan,
    Budget,
    EvaluationManifest,
    InformationAccess,
    PortfolioPlanner,
    SharedItem,
    TargetSpec,
    shared_context,
)
from .statistics import compare, paired_bootstrap, summarize, wilson_interval

__all__ = [
    "CanonicalEvidence",
    "EvidenceValidation",
    "ArmSpec",
    "AttemptObservation",
    "AttemptPlan",
    "Budget",
    "EvaluationManifest",
    "InformationAccess",
    "PortfolioPlanner",
    "SharedItem",
    "TargetSpec",
    "shared_context",
    "compare",
    "paired_bootstrap",
    "summarize",
    "wilson_interval",
]
