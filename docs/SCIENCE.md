# Source knowledge and scientific computation

## Canonical knowledge search costs and exclusions

The service loads verified claim metadata in indexed batches of at most 256, applies lexical and
type-token matching, and ranks those candidates before fetching any proof bytes. It validates ranked
candidates in order and stops after collecting the requested number of eligible results. A missing
or invalid metadata dependency does not consume the result limit. Current branch/sharing and
discovery restrictions, approved assumptions and review, exact theorem/challenge source, environment,
claim/receipt identity, and artifact digest bindings still apply before source retrieval.

An otherwise eligible candidate with missing, corrupt, or unsafe local source storage is omitted;
search continues and returns its claim ID and error code in `rejected_candidates`. Candidates failing
visibility or acceptance metadata checks expose neither their source nor rejection details. Other
storage failures, including unavailable remote storage, remain explicit errors. The direct dependency
bundle endpoint still fails explicitly on corrupt source and reads its source only once.

This is not a database full-text index: metadata matching remains linear in scoped claim inventory,
and sorting uses memory/time proportional to matching metadata. Invalid high-ranked candidates add
validation work and potentially storage reads. `limit=1` therefore does not promise one read in every
case; it avoids reading all irrelevant proofs and stops after the first eligible result. Local
regressions with 1,000 irrelevant verified claims return one result with one proof-store read. They
do not qualify PostgreSQL fleet latency, remote artifact-store throughput, or production scale.

These independent Python modules operate on passed records and data. They do not
write service receipts, review decisions, or canonical storage. The application must
authenticate and scope canonical inputs before passing them in. A receipt identifier
or digest is a provenance reference, not proof that a worker supplied true data.

## Lossless source ingestion

```python
from physharness.knowledge import ingest_text

source = ingest_text(
    "# Translation\n\nTranslate by a, then b, equals translation by a+b.\n",
    format="markdown", uri="local:notes/translation", revision="r1",
)
span = source.spans[0]
assert source.document.text[span.start:span.end] == span.text
```

`ingest_text` supports Markdown and LaTeX as inert text. It never expands LaTeX,
executes `write18`, renders HTML, follows links, or downloads a source. `ingest_bytes`
accepts UTF-8 bytes; invalid encoding produces an actionable `HarnessError`.
PDF ingestion returns `pdf_ingestion_unavailable`; no PDF extraction is installed or
implied. An external reviewed extraction workflow must preserve the original PDF
digest, page references and extracted-text provenance before using these text APIs.

Offsets are zero-based Python Unicode character offsets with an exclusive end.
Lines are one-based and separated by LF; CRLF bytes and Unicode are preserved.
Each span binds its text hash, full document hash, URI, revision, offsets and lines.
`IngestedSource` validates a contiguous, exact cover of the original document.
Chunk boundaries are deterministic character boundaries, not inferred semantic claims.
The default chunk is 2000 characters; maximum input is two million characters/eight
million encoded bytes, with at most 20000 spans. The returned Pydantic contracts are
frozen at field level; callers should treat their nested collections as immutable.

`SourceCorrespondence` connects a span to an immutable problem revision and target
digest, an interpretation, assumptions and limitations. It always starts and remains
`review_status="pending"` in this module. Expert approval belongs to the canonical
review service. `FailedApproach` records scoped observations with mandatory limitations
and an artifact digest; it cannot be promoted into a lemma by this module.

## Lemma retrieval

```python
from physharness.knowledge import LemmaIndex, LemmaRecord, LemmaRef

# records are snapshots fetched by the trusted application service.
index = LemmaIndex(records)
hits = index.search(
    "translation composition", environment_digest=environment_digest,
    revisions={"lemma-1": "r2"}, statuses=["verified"], type_query="Nat",
    requires=[LemmaRef(id="addition", revision="r3")],
    provenance_uris=["local:reviewed-library"], limit=20,
)
```

Records retain lemma/revision identity, target/environment digests, statement/type
text, evidence status, assumptions, limitations, exact dependency revision edges,
source spans and provenance URI. Verified record snapshots require a receipt reference;
this does not authenticate that receipt. Never build this index directly from a public
worker payload. Conflicting records for one lemma/revision are rejected. Returned
records are deep copies, so callers cannot mutate the indexed snapshot through a hit.

Environment is mandatory. Optional exact revision, status, provenance and direct
dependency filters run before ranking. Only `verified` status is searched by default;
`conditional`, `conjecture` and `rejected` records require explicit inclusion. Results
retain all evidence labels. Ranking uses deterministic token overlap, with statement
matches weighted twice type matches. The type query is a token filter, not Lean
unification or a claim that a premise applies. Dependency filtering is for direct
edges. No embedding service, vector index, graph closure or semantic applicability
checker is provisioned here. Discovery-mode source masking remains the caller's duty.

## Exact certificates and Lean candidates

```python
from physharness.science import check_polynomial_identity, check_matrix_factorization

x = {"op": "var", "name": "x"}
result = check_polynomial_identity(
    ["x"],
    {"op": "mul", "args": [x, {"op": "const", "value": "1/2"}]},
    {"op": "mul", "args": [{"op": "const", "value": "1/2"}, x]},
)
assert result.status == "checked_computation"
assert result.proof_status == "not_lean_proof"
assert result.obligation.status == "uncompiled"

matrix_result = check_matrix_factorization(
    [["2", "1/3"], ["6", "2"]],
    [["1/2", "1/3"], ["0", "2"]],
    [["2", "0"], ["3", "1"]],
)
```

Polynomial expressions are a small data language: `const/value`, `var/name`,
`add/args`, `mul/args`, and `pow/base/exponent`. Unknown fields and operations fail.
Coefficients are integers or exact fraction strings; floats, booleans, NaN and zero
denominators are rejected. Normalization expands multivariate rational polynomials
with `fractions.Fraction` and compares every coefficient. It does not sample points.
Limits include 16 variables, 512 nodes, depth 32, exponent 64, degree 128, 4096 terms,
100000 coefficient operations, and bounded coefficient sizes.

Matrix factorization checks `target = left × right` entry by entry with exact rational
arithmetic. Matrices must be nonempty, rectangular, dimension-compatible and at most
16 by 16. A mismatch reports the first unequal entry and its exact rational values.
The checker does not infer positivity, complex conjugation, units or physical meaning.

Results distinguish `checked_computation`, `refuted`, and `blocked`. A refutation is
limited to the submitted rational identity/product, not an independently interpreted
scientific claim. Results bind the certificate's canonical JSON digest where possible.
Malformed or oversized inputs return blocked status and remediation.

The same validated expression tree generates a Lean candidate using fixed variable
names and explicit rational arithmetic. Polynomial candidates use `ring`; matrix
candidates state every scalar product equality and use `norm_num`. No `sorry`, new
axiom, native computation or claimed receipt is added to these generated candidates.
Mathlib documents the corresponding [ring](https://leanprover-community.github.io/mathlib4_docs/Mathlib/Tactic/Ring.html)
and [norm_num](https://leanprover-community.github.io/mathlib4_docs/Mathlib/Tactic/NormNum.html)
modules. These links establish available tactic modules, not compilation of our output.

**All generated Lean is uncompiled.** It requires `import Mathlib`, an independently
pinned compatible Mathlib/Lean environment, expert review of its correspondence to
the intended target, and execution through the qualified verification service.
The root `formal/` smoke fixtures do not provision Mathlib. The Python certificate
checker and its source generator are not a substitute for kernel acceptance.

## Numerical evidence

`NumericalRecord` requires quantity/value, finite decimal error metadata, precision
in bits, method, explicit seed or `None`, input/environment digests, tool versions
and assumptions. Units and error interpretation are retained; the default error
interpretation is an estimate. A reported bound is the producer's claim and is not
validated by this record type. Its evidence kind is always `numerical_observation`.
This module supplies reproducible metadata contracts, not a numerical simulator or
an error-bound certifier. Numerical values never become proof receipts.

## Benchmark registry

`benchmarks/registry.json` contains 20 quantum-program algebra prerequisites,
20 classical-program algebra prerequisites, and 20 altered/invalid cases. Their
original local source is `benchmarks/sources.md`, with full digest and line provenance.
`benchmarks/build_registry.py` reproduces both files without compiling any source.
It can be run with `.venv/bin/python benchmarks/build_registry.py`.

The quantum families cover bit permutations, phase components, basis projectors,
two-component norm algebra and binary weights. Classical families cover translations,
kinetic algebra, affine maps, quadratic energy and discrete differences. These are
small rational/component prerequisites; they are not validated physics benchmarks,
novel results, or claims about complex Hilbert spaces or dynamical systems.

Family assignments put 24 candidates/12 altered cases in development and 16
candidates/8 altered cases in holdout. Variants and their attacks stay within one
family/split. This prevents explicit family overlap; it does not establish statistical
independence or a difficult generalization benchmark. Many tasks share basic algebra.

Negative cases cover incomplete proofs, changed definitions/statements, unapproved
axioms, native computation trust, forged stdout, missing targets, malformed Lean and
invalid proof terms. Each includes a reference expectation and rationale, not a real
observed checker result. Pinned challenge files intentionally use `sorry` as Comparator
target holes; those target holes are not submitted as accepted reference proofs.

```python
from pathlib import Path
from physharness.science import load_benchmarks

registry = load_benchmarks(Path("benchmarks/registry.json"))
worker_tasks = registry.discovery_tasks("holdout")
registry.require_qualified()  # raises benchmark_qualification_pending for all 60 cases
```

Discovery export contains target-only candidate tasks. Keep the full registry,
reference candidates, local sources, descendants and evaluation outcomes out of a
discovery worker's accessible storage. This export alone cannot enforce storage isolation.

The qualification gate requires recorded expert review, successful trusted target
compilation, an archived qualification receipt/report digest, environment digest and
checker versions for every case. For altered cases the report must document the
expected negative outcome on a functioning verifier; an unavailable verifier does
not qualify the case. These references must come from trusted services, since this
local library does not authenticate reviewers or issue verification receipts.
All shipped cases say `pending`/`not_run` and contain no fabricated evidence references.
No benchmark family is qualified until the actual review and checker work is complete.
