"""A real fitted TF-IDF retrieval baseline and conservative offline promotion gate.

Fitting learns document frequencies and IDF weights from training records only. This is
not an LLM fine-tune, policy optimization, scientific discovery, or RL success claim.
"""

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field

from physharness.evaluation.evidence import canonical_digest
from physharness.evaluation.portfolio import Contract, Digest
from physharness.evaluation.statistics import paired_bootstrap


class RankedDocument(Contract):
    document_id: str
    score: float


class RetrieverState(Contract):
    algorithm: Literal["tfidf-cosine-v1"] = "tfidf-cosine-v1"
    include_proof: bool = True
    dataset_digest: Digest
    training_ids: list[str]
    training_families: list[str]
    vocabulary: dict[str, float]
    vectors: dict[str, dict[str, float]]
    mode: str


def terms(text):
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


def vector(text, vocabulary):
    counts = Counter(terms(text))
    values = {
        word: (1 + math.log(count)) * vocabulary[word]
        for word, count in counts.items()
        if word in vocabulary
    }
    norm = math.sqrt(sum(value * value for value in values.values()))
    return {word: value / norm for word, value in values.items()} if norm else {}


class TfidfRetriever:
    def __init__(self, state: RetrieverState):
        self.state = RetrieverState.model_validate(state.model_dump())
        if set(self.state.vectors) != set(self.state.training_ids):
            raise ValueError("model training identity mismatch")
        if any(
            word not in self.state.vocabulary for v in self.state.vectors.values() for word in v
        ):
            raise ValueError("model vector vocabulary mismatch")
        self.model_digest = canonical_digest(self.state.model_dump())

    @property
    def training_ids(self):
        return list(self.state.training_ids)

    @property
    def vocabulary(self):
        return dict(self.state.vocabulary)

    @classmethod
    def fit(cls, dataset, *, include_proof=True):
        raw = b"".join(
            (
                json.dumps(item.model_dump(), sort_keys=True, ensure_ascii=False, allow_nan=False)
                + "\n"
            ).encode()
            for item in dataset.records
        )
        if hashlib.sha256(raw).hexdigest() != dataset.manifest.records_sha256:
            raise ValueError("dataset digest mismatch")
        training = [item for item in dataset.records if item.split == "train"]
        if not training:
            raise ValueError("retriever requires training records")
        if {r.family_id for r in training}.intersection(
            r.family_id for r in dataset.records if r.split != "train"
        ):
            raise ValueError("training family overlaps holdout")
        texts = {
            row.problem_id: row.statement + ("\n" + row.proof if include_proof else "")
            for row in training
        }
        counts = Counter(word for text in texts.values() for word in set(terms(text)))
        if not counts:
            raise ValueError("training corpus has no terms")
        vocabulary = {
            word: math.log((1 + len(texts)) / (1 + count)) + 1
            for word, count in sorted(counts.items())
        }
        return cls(
            RetrieverState(
                include_proof=include_proof,
                dataset_digest=canonical_digest(dataset.manifest.model_dump()),
                training_ids=sorted(texts),
                training_families=sorted({r.family_id for r in training}),
                vocabulary=vocabulary,
                vectors={key: vector(texts[key], vocabulary) for key in sorted(texts)},
                mode=dataset.manifest.mode,
            )
        )

    def _check_integrity(self):
        if canonical_digest(self.state.model_dump()) != self.model_digest:
            raise ValueError("fitted model integrity mismatch")

    def rank(self, query: str, *, k: int = 10) -> list[RankedDocument]:
        self._check_integrity()
        if k <= 0:
            raise ValueError("ranking k must be positive")
        query_vector = vector(query, self.state.vocabulary)
        scores = [
            (key, sum(value * doc.get(word, 0) for word, value in query_vector.items()))
            for key, doc in self.state.vectors.items()
        ]
        return [
            RankedDocument(document_id=key, score=score)
            for key, score in sorted(scores, key=lambda item: (-item[1], item[0]))[:k]
        ]

    def save(self, path):
        self._check_integrity()
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(
                {"model_digest": self.model_digest, "state": self.state.model_dump()},
                sort_keys=True,
                allow_nan=False,
            )
        )
        destination.chmod(0o600)

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        if set(data) != {"model_digest", "state"}:
            raise ValueError("invalid retriever artifact")
        if canonical_digest(data["state"]) != data["model_digest"]:
            raise ValueError("retriever digest mismatch")
        return cls(RetrieverState.model_validate(data["state"]))


class RetrievalCase(Contract):
    id: str
    family_id: str
    query: str
    relevant_ids: list[str] = Field(min_length=1)
    split: Literal["holdout"]
    annotation_source: str = Field(min_length=1)


class RetrievalEvaluation(Contract):
    model_digest: Digest
    dataset_digest: Digest
    case_digest: Digest
    mode: str
    reciprocal_ranks: dict[str, float]
    case_families: dict[str, str]
    mean_reciprocal_rank: float
    k: int


def evaluate_retriever(ranker, cases: list[RetrievalCase], *, k=10):
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError("heldout cases must be nonempty and uniquely identified")
    values = {}
    for case in cases:
        if case.family_id in ranker.state.training_families:
            raise ValueError("heldout family appeared during training")
        if set(case.relevant_ids) - set(ranker.training_ids):
            raise ValueError("relevance labels must refer to available training premises")
        ranked = ranker.rank(case.query, k=k)
        values[case.id] = next(
            (
                1 / position
                for position, row in enumerate(ranked, 1)
                if row.document_id in case.relevant_ids
            ),
            0.0,
        )
    return RetrievalEvaluation(
        model_digest=ranker.model_digest,
        dataset_digest=ranker.state.dataset_digest,
        case_digest=canonical_digest(
            sorted([c.model_dump() for c in cases], key=lambda c: c["id"])
        ),
        mode=ranker.state.mode,
        reciprocal_ranks=values,
        case_families={c.id: c.family_id for c in cases},
        mean_reciprocal_rank=sum(values.values()) / len(values),
        k=k,
    )


class PromotionDecision(Contract):
    status: Literal["approved", "rejected", "blocked"]
    reason: str
    candidate_model_digest: Digest
    baseline_model_digest: Digest
    evaluation_digest: Digest
    mode: str
    improvement: float
    interval_low: float | None = None
    interval_high: float | None = None
    seed: int
    min_cases: int
    required_improvement: float
    production_qualified: Literal[False] = False


def promotion_gate(
    candidate, baseline, *, min_cases=20, required_improvement=0.0, seed=0, samples=2000
):
    if min_cases < 1 or not math.isfinite(required_improvement) or required_improvement < 0:
        raise ValueError("invalid promotion gate thresholds")
    if (
        candidate.case_digest != baseline.case_digest
        or candidate.dataset_digest != baseline.dataset_digest
        or candidate.mode != baseline.mode
        or candidate.k != baseline.k
    ):
        raise ValueError("promotion requires matched heldout cases, corpus, access and mode")
    if candidate.reciprocal_ranks.keys() != baseline.reciprocal_ranks.keys():
        raise ValueError("heldout case identity mismatch")
    families = {}
    for identifier, score in candidate.reciprocal_ranks.items():
        families.setdefault(candidate.case_families[identifier], []).append(
            score - baseline.reciprocal_ranks[identifier]
        )
    differences = [sum(values) / len(values) for values in families.values()]
    improvement = sum(differences) / len(differences)
    common = dict(
        candidate_model_digest=candidate.model_digest,
        baseline_model_digest=baseline.model_digest,
        evaluation_digest=canonical_digest([candidate.model_dump(), baseline.model_dump()]),
        mode=candidate.mode,
        improvement=improvement,
        seed=seed,
        min_cases=min_cases,
        required_improvement=required_improvement,
    )
    if len(families) < min_cases:
        return PromotionDecision(status="blocked", reason="insufficient_holdout", **common)
    low, high = paired_bootstrap(differences, seed=seed, samples=samples)
    accepted = low > required_improvement
    return PromotionDecision(
        status="approved" if accepted else "rejected",
        reason="heldout_retrieval_improved" if accepted else "improvement_not_established",
        interval_low=low,
        interval_high=high,
        **common,
    )


class RollbackManifest(Contract):
    active_model_digest: Digest
    rollback_model_digest: Digest
    candidate_model_digest: Digest
    gate_digest: Digest
    applied: Literal[False] = False
    production_qualified: Literal[False] = False


def rollback_manifest(*, previous_model_digest, candidate_model_digest, decision):
    if decision.baseline_model_digest != previous_model_digest:
        raise ValueError("previous model does not match the evaluated baseline")
    if decision.candidate_model_digest != candidate_model_digest:
        raise ValueError("candidate digest does not match gate")
    return RollbackManifest(
        active_model_digest=candidate_model_digest
        if decision.status == "approved"
        else previous_model_digest,
        rollback_model_digest=previous_model_digest,
        candidate_model_digest=candidate_model_digest,
        gate_digest=canonical_digest(decision.model_dump()),
    )
