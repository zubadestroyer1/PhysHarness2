# Portfolio evaluation and learning primitives

These modules provide executable offline planning, canonical evidence validation, comparison,
dataset export and a fitted retrieval baseline. They make no model requests, start no workers,
apply no production promotion and claim no completed wave qualification. All included experiments
are synthetic unit tests; real benchmark campaigns, expert review and live outcome qualification
remain outstanding.

## Trust and canonical evidence

`CanonicalEvidence(records, snapshot_id=...)` takes a snapshot already authenticated and authorized
by the application. It copies records, rejects duplicate ids and hashes the snapshot. It cannot
turn worker-created dictionaries into canonical records. Load it only from trusted application
exports/storage, never a public JSON request. Snapshot identity is provenance, not authentication.

`validate(problem_id, receipt_id, target_digest=..., environment_digest=..., experiment_id=...)`
requires all of the following from that snapshot:

- Problem and verification record kinds, same exact target revision and environment.
- An approved current target review record matching target digest, reviewer and project.
- Concrete reviewed definitions with no definition holes.
- A real canonical verified receipt consistent with the existing verification outcome contract.
- The receipt's Lean artifact and candidate SHA256, experiment and project identities.
- Independent-kernel assurance when the canonical receipt is for publication.

The module does not rerun a kernel and does not accept source regexes, model claims, numerical
results, or unreviewed claims as solved evidence. Missing or invalid evidence receives an explicit
reason. The upstream acceptance service and independently configured verifier remain authoritative.

## Portfolio manifests and reservations

`EvaluationManifest` records exact target/environment/family/split identities, runtime and model
identifiers, model parameters, named approaches, mode (`live`, `replay`, `synthetic`), deterministic
seed, sharing/information policy, repetitions and explicit cost/token/wall/concurrency envelope.
A family cannot occur in both development and holdout partitions. The experiment id and full
manifest contents are hashed in result provenance.

`PortfolioPlanner(manifest).plan()` creates deterministic independent attempt identities, seeds,
exact model configurations and per-attempt reservations. `policy="uniform"` is the baseline:
each target/model/approach gets the configured repetitions. It neither performs those attempts
nor claims a provider honors seeds. The execution adapter must create fresh sessions and enforce
reservations. Seeds distinguish planned attempts and enable reproducible orchestration; they do
not establish statistical independence between model outputs.

`protected_per_arm` reserves deep attempts, with a longer `deep_attempt_seconds` allowance.
The planner rejects configurations that cannot fund all protected attempts and the declared
capacity. Its wall reservation conservatively assumes serial execution instead of promising
parallel speedup. `max_concurrency` bounds the number of reported running attempts selected at once.
The `cancellable` helper excludes protected attempts from adaptive preemption; explicit user
cancellation still belongs to the execution control plane.

For `policy="adaptive"`, `plan()` returns a candidate pool larger than the funded capacity.
**Do not launch every candidate in this pool.** Call `select_next(plans, history, evidence)` after
trusted observations; it enforces the fixed funded capacity and selects reserved deep attempts
first. Then it uses an upper-confidence exploration index from observed receipt outcomes:
empirical successes divided by completed attempts plus `sqrt(2 log(total) / attempts)`.
An unexplored arm reports `None` for its empirical rate and uncertainty. This index is not a
predicted success probability, calibrated confidence interval, or model-written estimated success.
Repeated use of one receipt cannot credit multiple attempts. The method may allocate remaining
capacity unevenly among arms/targets. It does not cancel workers or create durable programs.

`AttemptObservation` records exact observed model, terminal/running status, measured cost, tokens,
wall time, experiment identity and optional receipt and trace digest. Model substitution, duplicate
attempt ids, reused trace ids and breached reservations invalidate evaluation. `live` observations
require a canonical runtime trace digest. The caller must obtain measurements and trace artifacts
from the execution/ledger layer; this module cannot authenticate invented telemetry.

## Information access and sharing

`InformationAccess` specifies discovery versus literature-assisted access, allowed source ids,
additional hidden problem ids and an optional digest of a curated leakage manifest. The curated
index must enumerate leaking descendants, transformed copies and protected benchmark sources.
The module filters supplied context items; it does not discover semantic leakage or enforce a
worker's network/filesystem access.

`shared_context` returns nothing for `sharing="none"`. The `verified` policy admits only exact
proof text whose SHA256 matches a validated canonical receipt. `attributed_ideas` additionally
admits ideas with an author while preserving `unverified_idea` labels. All sources must be allowed.
Discovery mode automatically hides every evaluated target id; explicit hidden ids cover leaking
descendants and holdout material. Context lineage/source metadata must come from a trusted index,
not worker assertions that a copied proof is unrelated. The executor must apply the same policy
across tools, retrieval, mailboxes, sessions and exported context.

## Metrics and matched comparisons

`summarize(manifest, plans, observations, evidence, elapsed_seconds=...)` counts each reviewed
exact target solved at most once. Failed, blocked, missing, foreign-experiment or repeated receipts
cannot inflate successes. All observed attempt costs count, including failures. Summaries retain
invalid-evidence reasons, planned/completed attempt counts, actual spending, elapsed wall time,
tokens, snapshot digest, target families and explicit live/replay/synthetic mode. Running attempts
prevent finalization.

Solved-fraction uncertainty uses the Wilson 95% interval. This is a descriptive binomial interval
whose independence assumption may not hold for related targets. `compare` instead computes paired
family-average solved differences and a deterministic family-cluster percentile bootstrap, with
seed and sample count recorded. Families receive equal weight. Few independent families or
repeated policy selection can invalidate confirmatory interpretation; these helpers do not
establish statistical qualification or correct for multiple/adaptive comparisons.

`compare(left, right)` requires matched target revisions, family partitions, budgets, information
access and mode, and **equal actual spending and wall exposure**. `matching="envelope"` instead
allows different actual usage under equal allocated envelopes and labels that distinction in its
output. Actual cost/wall differences are always reported. Policy, sharing treatment, model and
approach may intentionally differ. Live and replay results cannot be combined as matched trials.
Post-hoc comparisons are exploratory; pre-register splits, budgets and stopping rules for real runs.

## Licensed datasets

`export_dataset(evidence, selections, license_grants, artifact_bytes, output_directory, mode=...)`
validates every receipt before writing `records.jsonl` and `manifest.json`. Every row retains exact
statement and proof, target/environment/artifact digests, receipt and review ids, checker versions,
assurance, family/split and licensing attribution. Proof bytes must match the receipt SHA256.
Families, identical target digests and identical proof bytes cannot cross dataset partitions.
Duplicate targets, empty selections, missing licenses and changed existing output fail explicitly.
Files use private permissions. The export is a local file artifact, not a durable database commit.

`LicenseGrant` is an explicit administrative decision with artifact digest, license id, approving
curator, attribution and training permission. The curator must confirm rights for the complete
exported statement/proof record and its source material; the module does not infer permission from
model-generated provenance or legal boilerplate. It stores the decisions and selection digests for
audit. Default export mode is `unqualified`; tests set `synthetic`. No license or expert approval is
manufactured by the exporter.

## Fitted retrieval and heldout gates

`TfidfRetriever.fit(dataset, include_proof=True)` actually fits document frequencies and smoothed
inverse-document-frequency weights from **training records only**, then normalizes term-frequency
vectors. Tokenization, ordering and tie breaks are deterministic. The statement-only variant
`include_proof=False` is separately identified in model provenance. Holdout text never contributes
to vocabulary or weights. This is a modest lexical retrieval baseline, not an LLM fine-tune or RL.

`rank(query, k=...)` returns document ids and cosine scores. Saving writes a content-addressed JSON
model; loading checks its digest. Runtime integrity checks detect mutation of fitted state while
retaining an old model identity. Model hashes provide integrity, not a signature from a trusted
model registry.

`evaluate_retriever` uses heldout queries with curator-supplied relevance labels and annotation
provenance. Heldout families cannot have appeared in training; relevant ids must refer to available
training premises. It reports reciprocal rank and case/family/model/dataset hashes. It does not
infer semantic relevance from textual overlap or pretend that retrieval success is proof success.

`promotion_gate(candidate, baseline)` requires matched heldout cases, corpus, mode and retrieval
cutoff. It blocks fewer than 20 independent heldout families by default, performs paired family
bootstrap resampling, and approves only when the lower improvement bound exceeds the configured
threshold. Thresholds, seed and evaluation digest are recorded. Gate input must be trusted evaluator
output; a worker must not supply a handcrafted score object. Reusing the same holdout for repeated
tuning is not protected automatically and requires a campaign-level holdout registry.

Every decision retains `production_qualified=False`. A synthetic test exercises genuinely fitted
retriever variants and a positive offline gate; it is explicitly not evidence of scientific
improvement. `rollback_manifest` binds the candidate and previous model to the gate's exact model
identities and retains the previous digest. It produces an unapplied proposal (`applied=False`),
not a deployment. The execution/model-registry service must authorize and apply any change.

## Outstanding qualification

No canonical production snapshot, live physics benchmark, heldout relevance collection, licensed
public research dataset, cloud worker run, learned proof policy, RL experiment, or production
promotion was created in this implementation. Persistence, scheduler integration, spend enforcement,
network/tool access enforcement, trusted snapshot loading, licensing administration, holdout-use
tracking and registry deployment remain responsibilities of their separate application components.
