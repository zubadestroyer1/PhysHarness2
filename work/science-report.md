# Knowledge, exact science, and benchmark implementation

Approved scope: `docs/IMPLEMENTATION_PLAN.md` waves 0, 5, and 7; independent modules
only, without service persistence or acceptance authority.

## Implementation plan

1. Write failing behavior tests for source offset/provenance integrity, revision and
   environment-filtered retrieval, correspondence integrity, and failed approaches.
   Implement `knowledge/sources.py`, `knowledge/index.py`, and their public imports.
2. Write failing tests for exact polynomial expansion and rational matrix products,
   malformed/resource-heavy certificates, uncompiled Lean obligations, and numerical
   provenance/error metadata. Implement `science/certificates.py` and `science/records.py`.
3. Write failing registry tests for 20 quantum/20 classical candidates and 20 altered
   cases, family holdout separation, discovery masking, and pending qualification
   refusal. Implement `science/benchmarks.py` plus original local benchmark artifacts.
4. Run scoped tests and lint, inspect exported interfaces, document concrete usage,
   limitations, and test evidence. No source compilation or review is inferred.

## Evidence

1. Wrote tests before creating either module. The scoped test command produced
   **25 failed in 0.07s**, all on explicit missing knowledge/science implementation
   assertions. No Lean or external transport was involved.
2. Implemented lossless ingestion and record retrieval: **8 tests passed**.
3. Implemented exact rational certificates and numerical evidence contracts:
   **13 science tests passed**.
4. Added all benchmark artifacts and registry/gate/export support: initial full
   scoped suite produced **25 passed**.
5. Added adversarial/independent checks for malformed expression tags, cyclic input,
   nonzero polynomials that vanish at sampled points, negative rational distribution,
   provenance filtering/copy isolation, benchmark family leakage and missing evidence.
   This exposed a real unhashable-operation error: **1 failed, 30 passed**.
6. Rejected non-string operation tags explicitly. Final scoped command:

   `.venv/bin/python -m pytest tests/test_knowledge.py tests/test_science.py tests/test_benchmarks.py -q`

   **31 passed in 0.08s**. Scoped `ruff check` also passed.
7. Regenerated `benchmarks/registry.json` and `benchmarks/sources.md` through the
   checked-in generator and compared both before/after SHA256 digests: identical.
   The loaded registry contains 20 quantum/20 classical candidates plus 10 altered
   cases in each program. Development has 24 candidates/12 altered cases; holdout
   has 16 candidates/8 altered cases. The qualification gate blocked all 60.
8. Executed the documented exact rational matrix example. Labels were
   `checked_computation`, `not_lean_proof`, `uncompiled`, as required.

## Delivered interfaces

`physharness.knowledge` exports:

- `ingest_text(text, *, format, uri, revision, chunk_chars=2000)` and
  `ingest_bytes(content, *, format, uri, revision, chunk_chars=2000)`.
- `SourceDocument`, `SourceSpan`, `IngestedSource`, `SourceCorrespondence`,
  `FailedApproach`.
- `LemmaRef`, `LemmaRecord`, `SearchHit`, `LemmaIndex(records)` with
  `search(query, *, environment_digest, statuses=("verified",), revisions=None,
  type_query="", requires=(), provenance_uris=None, limit=20)`.

`physharness.science` exports:

- `check_polynomial_identity(variables, left, right)` and
  `check_matrix_factorization(target, left, right)`.
- `ComputationResult`, `LeanObligation`, `NumericalRecord`.
- `BenchmarkTask`, `BenchmarkRegistry`, `load_benchmarks(path)`;
  registry methods `discovery_tasks(split)` and `require_qualified()`.

Implementation files are split between knowledge source ingestion/indexing and
science certificates/evidence records/benchmark contracts. Tests are confined to
the three assigned test files. `docs/SCIENCE.md` documents use, bounds and limits;
`benchmarks/README.md`, `build_registry.py`, `sources.md`, and `registry.json`
provide reproducible original local benchmark artifacts.

## Scientific and trust limits

- No service/core/API files, dependencies or formal smoke files were changed.
  No commits, child agents, external science APIs or paid calls were used.
- Knowledge accepts caller-supplied canonical snapshots. The caller must authenticate
  and scope them. A receipt ID is not independently authenticated by this local
  index. The module cannot issue acceptance or expert-review decisions.
- Text ingestion preserves source bytes through UTF-8 and exact character spans;
  LaTeX is never executed. PDF returns an actionable unavailable error. OCR, page
  extraction, embeddings, semantic type unification and premise applicability are
  not implemented. Dependency retrieval filters direct revision-specific edges.
- Correspondences remain pending review. Failed approaches retain mandatory
  limitations. Retrieval never changes a record's evidence status.
- Exact arithmetic certifies only the submitted rational polynomial equality or
  matrix product within this Python implementation. It is checked computation,
  not a Lean proof or independent scientific truth. Malformed/oversized inputs
  block; mismatches retain exact residuals or unequal matrix entries.
- Generated Lean obligations use Mathlib `ring`/`norm_num`, fixed safe variable names,
  and exact rational expressions. They contain no invented acceptance, axiom, sorry
  or native-computation instruction. All remain **uncompiled**; compatible pinned
  Lean/Mathlib and independent verification are not provisioned by these modules.
  Current primary Mathlib tactic module documentation was inspected, not used as
  evidence that these generated sources compiled.
- Numerical records retain precision, error interpretation, assumptions and complete
  input/environment/tool provenance. They neither run a simulator nor certify a
  producer's claimed numerical error bound.
- All 60 benchmark entries are original local, tiny algebra/component prerequisites.
  None is labeled reviewed, compiled, accepted or scientifically novel. Proposed
  reference outcomes are hypotheses for qualification. Some families share basic
  algebra; a family split alone does not establish statistical independence.
- The registry's gate requires trusted review/compilation/evidence references and
  refuses every shipped pending entry. Those references must be supplied by trusted
  services; this library is not an authorization or cryptographic attestation system.
  For negative cases, qualification evidence must show the expected failure on a
  functioning verifier; general verifier unavailability is not qualification.
- Discovery export omits reference candidates/outcomes and returns only positive
  candidate targets. A deployment must also isolate the full registry, reference
  artifacts and leaking descendants from worker-accessible storage.
