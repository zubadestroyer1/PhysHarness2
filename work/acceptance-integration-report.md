# Acceptance integration report

The real isolated acceptance transport is runnable. Final engineering suites passed 9/9 expected cases under the Lean kernel and 9/9 with independent nanoda replay. Exact reports and pins are in [acceptance-evidence/index.json](acceptance-evidence/index.json). These results are engineering evidence; expert review and production sandbox qualification remain absent.

## Correctness changes

- Separated the canonical scientific `target_digest` from exact `challenge_sha256`. The old service hashed all problem metadata while the verifier compared that digest against source bytes, making real service/bundle integration impossible. Manifest and transport protocol v2 bind both identities explicitly; v1 inputs fail closed.
- Bound scientific bundle theorem selection to the reviewed `ProblemCreate.target_theorem`. A bundle cannot select another convenient theorem from the same source. Engineering selection stays explicit in its fixture manifest.
- Captured the submission's review ID, source digest and theorem selector. Replacement review or changed target/environment/source before or during checking blocks promotion.
- Enforced semantic review and definition-hole preflight in the acceptance service, even for a configured verifier implementation. It validates the actual stored review's target, scope and decision.
- Preserved typed checker-identity, artifact-read and assurance-downgrade faults as blocked receipts. Verified receipt and claim persist in one transaction; failure leaves both unaccepted and supports retry.
- Added an exclusive trusted-bundle builder and deployment preflight. Preflight never executes candidates or returns assurance.
- Added a separate engineering API requiring execution pins but no fake review or circular qualification-report reference. It cannot be attached as a scientific verifier or mistaken for a receipt.
- Reworked the engineering runner to require exact status/code and real Comparator exit evidence. Ambiguous upstream exit 1 remains blocked. Startup failure, missing Docker and candidate hash rejection cannot pass as attacks. Reports always record no expert review and no production qualification.

## Real evidence

| Fixture | Lean mode | Independent mode | Observed checker diagnostic |
| --- | --- | --- | --- |
| Translation composition | kernel success | Lean + nanoda success | Both kernels accepted the exported proof |
| Bit-flip involution | kernel success | Lean + nanoda success | Both kernels accepted the exported proof |
| `sorry` | blocked | blocked | Illegal `sorryAx` |
| Extra axiom | blocked | blocked | Illegal transitive `shortcut` axiom |
| Forged stdout JSON | blocked | blocked | Forged text remained diagnostics; `sorryAx` rejected |
| Target overwrite | blocked | blocked | Read-only filesystem |
| Config overwrite | blocked | blocked | Permission denied |
| Changed dependency | blocked | blocked | `neutral` constant differs from challenge |
| Native decision | blocked | blocked | Extra native-decision axiom |

The final reports bind image `sha256:cadb65787cb75657516379dc91f3870c6c473e3df11b907428f522ceff360eca`, current driver/host launcher/seccomp hashes and all six executable hashes. Actual runtime was Linux 6.8.0-117-generic, aarch64, Docker 29.5.2 and runc v1.3.5. Eighteen named verifier containers were explicitly removed. No generated Lean ran directly on macOS.

The full upstream `Main.lean` and axiom traversal were inspected at Comparator commit `3927ad383f208ae977c340a91c48ac9b497d2097`. The driver uses its actual JSON/env protocol, real Landrun, dependency comparison, transitive axiom enforcement and fresh kernel replay. Nonzero exits cannot reliably distinguish proof failure from environment failure, so the adapter does not label these outcomes mathematical refutations.

## Regression validation

Before the fixes, nine acceptance tests failed on review bypass, queued-review replacement, environment race, lost typed provenance faults, candidate-read failure and missing review binding. Additional failing regressions demonstrated the metadata/source digest mismatch, wrong selected theorem and publication preflight omission. The targeted verification and acceptance integration suite now passes 67 tests, including atomic receipt/claim rollback, checkpoint failure, forged transport fields, cleanup failure, exact source and environment pins, readonly umask handling and engineering/scientific type separation.

See [VERIFICATION.md](../docs/VERIFICATION.md) for runnable commands, schemas and migration instructions.

## Remaining limits

The engineering fixtures do not constitute domain-expert approval or a new scientific result. Production qualification still needs an independent assessment of the actual kernel/runtime/Landrun/seccomp attack surface and deployment controls. The reported axiom list is the enforced allowed-set upper bound, not a measured minimal closure. No report or code path fabricates those missing authorities. The production verifier remains unavailable until its approved configuration is supplied. Genuine Physlib/QuantumInfo declaration/import work belongs to the formal-environment report and its separate library image.

## Subsequent integration audit

The reviewer/acceptance commit race was reproduced using two real PostgreSQL transactions in a temporary pinned PostgreSQL 16.15 container. Before the fix, the reviewer committed while acceptance prepared a verified receipt. The commit now locks and refreshes the problem row; the reviewer encounters the expected row-lock timeout, then can successfully review after acceptance commits. Acceptance integration and the live migration check passed 16 tests. Container, ephemeral volumes, isolated network and dedicated SSH tunnel were removed afterward; [the database regression record](acceptance-evidence/postgres-lock-regression.json) preserves the details.

Added an operator-owned exact-revision verifier registry and canonical environment/bundle preparation helpers. Distinct targets can share the same environment bytes, but routes cannot duplicate revision IDs, fall back to another revision, select an engineering checker, or mix registry and single-bundle settings. Preparation verifies source, metadata, environment and project file pins before/after writing and leaves pending reviews unchanged. See the multiple-target section of the verification documentation for signatures and configuration.

Final registry/preparation checks pass all 10 tests. An independent agent reviewed these helpers, routing, configuration and bootstrap; a 30-test registry/CLI/run-control run passed. Its mutation sweep confirmed that revision swaps, changed semantic/source/environment digests and theorem-selector changes all block without assurance, as do unreviewed targets and definition holes. No additional actionable finding remained. The final broader acceptance/configuration/authority/infrastructure selection passed 109 tests; two PostgreSQL checks skip without the deliberately removed temporary endpoint, and the real PostgreSQL execution is recorded separately above. Lint and `git diff --check` pass. No commits or pushes were made.


## Offline causal diagnostic audit

A subsequent optional process-exit probe exposed a reporting weakness: generic `blocked/comparator_failed` accepted an unrelated Lean syntax error as an exercised attack. That optional probe was stopped and remains blocked/incomplete; it is not counted as passing coverage. No additional candidate execution occurred during the fix.

Nine pure regressions first failed against the old runner. Every negative fixture now requires nonempty `required_diagnostic_substrings`, all of which must appear in the observed Comparator output before a suite can pass. Invalid expectations fail before execution; a diagnostic mismatch preserves the current observed result in a blocked report. The existing exact-code regression was updated to satisfy this new fixture precondition. The library Sorry fixture requires the specific illegal-`sorryAx` diagnostic; the formal-environment agent was notified before using the changed schema.

The [offline audit report](acceptance-evidence/offline-diagnostic-audit.json) confirms all 18 original archived outcomes satisfy the stronger checks, including 14 negative observations and four positive controls. It verifies their exact challenge/candidate source hashes, reconstructs the original fixture manifest by removing only the added diagnostic expectations, and confirms every original evidence/index hash plus the current launcher and driver. The optional initializer syntax result fails its expected execution marker automatically. This audit performed zero candidate executions and grants no production qualification or expert review. Final owned/adjacent validation passed 122 tests with two deliberately unavailable PostgreSQL checks skipped; the separately recorded live PostgreSQL result remains unchanged. Lint and `git diff --check` pass.
