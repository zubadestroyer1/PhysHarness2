# Integration contract (v1)

The live `/openapi.json` schema is generated from the installed application; the notes below
explain authority and recovery semantics beyond the field schema. All `/v1` requests require a
project-scoped bearer identity. `/healthz` is an unauthenticated process probe only.

Mutations require `Idempotency-Key`. Reusing a key with changed intent or authority fails. Updates
such as experiment transitions also require `expected_revision`; stale versions fail. Long
operations return canonical identifiers. Worker completion is never proof acceptance.

Errors have `{error: {code, message, operation_id, retryable, remediation, details}}` and a matching
`X-Operation-ID` header. Unexpected faults log a correlated traceback and return `INTERNAL_ERROR`.
Validation errors identify fields without echoing submitted secret values. Missing providers
remain unavailable; no client supplies fabricated data after an error.

Datetimes are UTC ISO 8601, money is a decimal USD string, identifiers are stable UUID strings,
and content hashes are SHA-256 hex. Records contain `id`, `project_id`, `revision`, and `created_at`.
Scientific revisions are immutable; mutable execution state uses explicit revisions.

## Collections and history

GET collection routes exist for `campaigns`, `problems`, `experiments`, `branches`, `tasks`,
`claims`, `artifacts`, `reviews`, `sessions`, `programs`, `verifications`, `messages`, `sources`
and `workspaces`. GET `/v1/{collection}/{id}` returns one record. Unknown or out-of-scope objects
return `NOT_FOUND`. Execution collections accept an `experiment_id` filter.

Collections return `items` and `next_cursor`. Use `limit` (default 500, maximum 5,000) and pass the
returned cursor as `after` until it is null. Rows use stable ID order rather than implying
chronological order. Project and branch visibility filters apply before returning data; a cursor
does not grant access. Do not assume a first page is a complete export.

Each collection request examines at most `max(100, limit)` metadata records in its indexed scope,
plus one unexamined lookahead record. It stops sooner when it has `limit` authorized items.
Invisible records consume the scan budget, so `items` can be empty while `next_cursor` is non-null.
The cursor is the last examined record ID, including when that record was invisible. Continue until
the cursor is null; internal full readers follow the same rule. Authorization still applies to every
returned item, and cursors never reveal record content or grant read authority. These pages are
keyset reads of current state, not a transactionally frozen export across multiple requests.

Ordered indexes cover project/kind/ID, experiment scope, and agent review-target scope. Accepted
cross-branch artifacts use an indexed artifact/current-review receipt lookup with the existing exact
source, theorem, environment and target bindings; only one matching receipt is materialized. Receipt
lookup can still examine multiple entries for the same artifact/review when their other bindings
differ. The scan budget bounds collection metadata, not proof-checker execution or wall-clock latency.

GET `/v1/events` accepts `after` (sequence), `limit` (default 100, maximum 1,000), and `tail`.
The default scans forward; `tail=true` requests the latest visible window for an activity panel.
Responses include `items`, `next_cursor`, `has_more`, `window`, and `scan_limited`. A bounded scan
may yield an empty page with a cursor when hidden events occupy the window. Continue using that
cursor. Each event includes sequence, kind, aggregate ID, operation ID, payload and creation time.

## Research mutations

| Route | Inputs and resulting behavior |
|---|---|
| POST `/v1/campaigns` | Title, objective and quantum/classical program membership. |
| POST `/v1/problems` | Campaign, original and formal statements, assumptions, definitions, source, exact environment digest and target declaration. `parent_revision_id` records an amendment. Semantic review starts pending; definition holes remain explicit. |
| POST `/v1/problems/{id}/reviews` | Reviewer decision and rationale, bound to this exact target digest. |
| POST `/v1/experiments` | Campaign/problem, exact runtime/model/parameter configurations, resource envelope, policy, mode, sharing and runtime limits. No default model substitution. |
| POST `/v1/experiments/{id}/transition` | Start/pause/resume/cancel plus expected revision. |
| POST `/v1/experiments/{id}/branches` | Objective, title, optional parent/checkpoint and helper/collaborator/competing relationship. `model_index` chooses only an already-recorded experiment configuration; omission inherits parent or first model. |
| POST `/v1/tasks` | Assigned branch, objective, dependency task IDs. Delegation shares the central envelope. |
| POST `/v1/artifacts` | UTF-8 content, type, media type, experiment/branch and attributed provenance. Server computes hash. Only authorized researchers designate trusted input. |
| POST `/v1/experiments/{id}/claims` | Statement, assumptions and conjecture/numerical/conditional evidence; clients cannot submit verified status. |
| POST `/v1/experiments/{id}/verify` | Artifact and requested publication assurance; independent worker constructs and checks a canonical request. |
| POST `/v1/messages` | Sender branch, recipient branch, attributed content and optional artifact IDs, subject to sharing policy. |
| POST `/v1/sources` | Markdown/LaTeX text, source URI/revision/license and experiment; preserves source spans and pending semantic status. |
| POST `/v1/programs` | Immutable JavaScript artifact, inputs and optional parent program. Registration alone does not execute the program. |

The budget covers cost, concurrency, lifetime and optional cumulative tokens. The integrated
worker currently runs direct/independent Responses policies; unsupported runtime/policy selections
fail explicitly. Runtime-specific limits do not imply every native SDK can enforce hard tokens.

## Verification identity and recovery

The `/v1` API remains unchanged: submission selects only the candidate artifact and publication
flag. The server builds the verification request from canonical records. `target_digest` remains
the complete reviewed problem metadata identity. `challenge_sha256` is computed from the exact
UTF-8 `formal_statement`, without newline normalization; ProblemCreate has no additional source
hash input. A receipt also pins `review_id` and `target_theorem`, checked before verification and
again before receipt/claim commit. Current review, source hash and theorem bindings are required
for accepted sharing and evidence retrieval.

Candidates support at most 2,000,000 Unicode characters. A larger candidate fails submission
with HTTP 422 `CANDIDATE_TOO_LARGE` before queueing. A persisted oversized candidate, unreadable
artifact or request-construction fault receives a terminal `blocked` receipt with code and
remediation. Old receipts lacking source/review/theorem pins block with
`verification_receipt_incompatible` and require fresh submission. Trusted manifests and driver
responses use `physharness-comparator-v2`; old ambiguous manifests are rejected. Operators must
regenerate/repin manifests and requalify changed launcher/driver/image bytes. See
[verification](VERIFICATION.md) for the complete private verifier contract.

## Evidence, context and retrieval

- GET `/v1/artifacts/{id}/content` returns authorized UTF-8 artifact content after a hash check.
- GET `/v1/branches/{id}/restart-brief` assembles the target and current scientific records.
- POST `/v1/branches/{id}/context` creates a portable checkpoint from approach, unresolved
  obligations, optional attributed summary, selected evidence, predecessor and size bounds.
- GET `/v1/branches/{id}/context/{checkpoint_id}` validates canonical issuance, lineage, exact
  current target/review/policy and evidence freshness. Stale context fails explicitly.
- GET `/v1/branches/{id}/history?kind=...` pages retained portable scientific history.
- GET `/v1/experiments/{id}/knowledge?query=...&type_query=...` searches canonically applicable
  accepted claims under the target environment and information policy.
- GET `/v1/experiments/{id}/knowledge/{claim_id}/bundle` returns hash-checked source and acceptance
  bindings. Clean recomposition is required; a bundle does not automatically install trusted code.
- GET `/v1/experiments/{id}/ledger` returns actual/reserved/uncertain usage and held concurrency.
- GET `/v1/experiments/{id}/export` produces one database-snapshot manifest with scoped records,
  exact review and artifact hashes. `phys export` downloads privately with integrity checking;
  `phys validate-export` checks local bytes. Neither claims independent kernel replay/publication.
- GET `/v1/status` separates responding services, configuration and unqualified wave gates.

Model identities are issued by the controller for an exact experiment/branch. `none`, `verified`
and `ideas` sharing modes govern records, mail and retrieval; private native session/checkpoint
state remains private even under broader sharing. An explicitly configured orchestrator may
inspect topology without automatically reading private competing work. See
[collaboration](COLLABORATION.md), [memory](MEMORY.md), and [workspace](VM_WORKSPACES.md) contracts.

The console must present proof status, specification review, assumptions, numerical evidence and
novelty independently. Model completion or compilation alone cannot produce a solved indicator.
