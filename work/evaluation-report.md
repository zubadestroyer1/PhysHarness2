# Evaluation and learning implementation report

Implemented only the assigned evaluation/learning modules, two test files, `docs/EVALUATION.md`,
and this report. No API/schema/core/execution edits, dependency installation, cloud/model calls,
subagents or commits were used. All full-wave qualification remains unqualified.

## Delivered files and interfaces

`src/physharness/evaluation/`:

- `evidence.py`: copied canonical snapshot with content digest, record lookup, and relational
  receipt validation against exact problem/target/environment, reviewed concrete definitions,
  current expert-review record, artifact SHA256, project and experiment identity. Existing
  `VerificationOutcome` invariants validate kernel assurance; publication requires independent
  kernel. Caller authenticity is a trusted canonical-loader prerequisite, not inferred from JSON.
- `portfolio.py`: strict manifest/arm/target/budget/attempt/observation contracts; uniform repeated
  independent attempt plans; exact model/parameter and deterministic seed provenance; protected
  deep-attempt reservations; optional UCB allocation using observed receipt outcomes and explicit
  uncertainty; funded capacity/concurrency checks; cancellation eligibility; source/holdout
  filtering with exact-byte verified sharing and attributed unverified ideas.
- `statistics.py`: target-deduplicated solved metrics, all-attempt cost accounting, Wilson
  intervals, reproducible family-cluster paired bootstrap, strict actual-cost/wall matching by
  default, explicitly labeled equal-envelope comparisons, and live/replay/synthetic separation.

`src/physharness/learning/`:

- `datasets.py`: receipt-validated export of licensed canonical records and actual proof bytes,
  preserving target/environment/artifact/receipt/review/checker/licensing/family provenance;
  family and duplicate target/proof separation across train/development/holdout; deterministic
  JSONL and manifest digests; explicit unqualified/live/replay/synthetic labels.
- `retrieval.py`: actually fitted deterministic TF-IDF/cosine retriever, statement/proof and
  statement-only variants, train-only vocabulary/weights, JSON persistence/digest verification,
  runtime model integrity checks, heldout relevance evaluation, conservative paired family
  bootstrap gate and baseline/candidate-bound unapplied rollback manifests.

Both packages export the public contracts/functions documented in `docs/EVALUATION.md`.
These primitives are directly callable Python APIs. They do not pretend to be wired into the
separate durable orchestration, application API or model registry.

## Test-first and validation evidence

1. Initial test suite ran before implementation: **15 failed** with explicit missing
   evaluation/learning primitive assertions.
2. First implementation: **15 passed**.
3. Six hardening regressions failed before fixes: forged text labeled verified using an unrelated
   receipt; unmatched actual spending accepted as matched; missing live trace provenance;
   mutable fitted state preserving an old digest; rollback unrelated to evaluated baseline;
   and absence of a separately fitted statement-only retrieval variant.
4. Fixes produced **21 passed**. The positive variant test actually fits two rankers and measures
   different heldout rankings; its mode remains synthetic and production qualification false.
5. A duplicate-receipt reward regression then failed before deduplicated credit was implemented.
   Duplicate proof content across holdout partitions is also tested. Final suite: **23 passed**.

Final validation command:

```text
.venv/bin/python -m pytest tests/test_evaluation.py tests/test_learning.py -q
23 passed in 0.09s
```

The suite exercises deterministic seed/model diversity, budget rejection, protected/adaptive
allocation, invalid receipt and semantic-review bindings, duplicate target success accounting,
exact-model enforcement, foreign-experiment evidence, matched cost/mode, reproducible intervals,
holdout family isolation, source sharing/attribution, proof-byte binding, licensing requirements,
dataset content integrity, actual TF-IDF fitting, heldout exclusion, model persistence/tampering,
small-sample gates, positive and negative synthetic ranking gates, and rollback identity.
All test records, expert labels and receipts are explicitly synthetic test fixtures, never inserted
into the application or represented as live scientific results.

## Limitations and honest qualification status

- No real model attempt, benchmark campaign, kernel acceptance, human semantic review, licensed
  public dataset or production promotion occurred. `production_qualified` remains false for
  learning gates and rollback proposals.
- Canonical snapshot/telemetry/context-index/evaluator/administrative licensing inputs are trusted
  service boundaries. These classes validate integrity and relationships, not caller authority.
  They must not be exposed directly to worker JSON.
- Planning is offline; actual session isolation, provider seed behavior, reservation enforcement,
  cancellation, durable histories and network/tool information restrictions belong to execution.
  Adaptive candidate pools exceed funded capacity intentionally; only `select_next` may allocate.
- UCB is an exploration heuristic over observed verified-outcome frequency, not a calibrated model
  success estimator. Protected attempts are reserved before adaptive spending. Seeds do not prove
  probabilistic independence. Duplicate receipt credit is prevented.
- Discovery filtering relies on curator-maintained source/descendant lineage; semantic leakage
  detection and cross-tool access control are not implemented here.
- Wilson intervals assume independent target outcomes. Comparative/gate bootstrap averages within
  families and weights families equally; small samples and adaptive/multiple comparisons are not
  confirmatory evidence. Pre-registration and holdout-use tracking remain operational obligations.
- Licensing approval must cover the complete exported record and underlying source rights. The
  exporter records administrative grants; it does not infer rights or offer automated legal review.
- TF-IDF is a real learned lexical retrieval baseline with no external dependencies, not learned
  proof search, policy optimization, a neural ranker, LLM fine-tuning or RL. Relevance labels are
  supplied separately by a trusted evaluator. Retrieval improvement does not imply solved physics.
- File exports/model saves are local artifacts, not transactional canonical database storage.
  Rollback manifests are identity-bound proposals with `applied=False`; registry integration and
  production deployment are outside this owned scope.
