# Current verifier control evidence audit

This is an independent, read-only audit of the completed `work/wave01/evidence-8g` control set. The qualification API returned **`satisfied` for its mechanical requirements**: all 10 checks were `observed`, with none missing or invalid. The packet still says `deployment_approval: pending`, `scientific_review: not_provided`, and `production_qualified: false`. This audit is neither a proof receipt nor approval of a target or deployment.

## Commands and method

From `/Users/kieranpi/Desktop/Projects/PhysHarnessV2/.worktrees/formal-research-loop`, I read the final scope, image and runtime metadata, build inputs, four suite reports, fixed boundary report, regression JSON/XML, matrix, and selected declaration audit. I used `PYTHONPATH=src .venv/bin/python` with `DeploymentScope.model_validate`, `EvidenceFile`, `SuiteEvidence`, `BoundaryEvidence`, `RegressionEvidence`, and the actual `assess_qualification(root, scope=..., evidence=..., boundary=..., regressions=...)` API. Each evidence reference used the SHA-256 of the file read. Separate `python3` parsing and `hashlib.sha256` checks compared current source and build-context files, expected case IDs/outcomes/diagnostic substrings, resource pins, cgroup observations, cleanup identities, JUnit test identities, and image identities. No verifier, Docker, Lean, test suite, GitHub action, or process-exit probe was run for this audit.

## Identities and source binding

- Canonical scope SHA-256: `e8f8c011e29242aa16f7464522b061545ac189f392c729655c57183a578ddb42`. Raw `scope-final.json` file SHA-256: `8f05e496f6fe43917935314088e85d3c8aeb84bcbfa53ecc1f661b81508cb1f3`. These differ because the former hashes canonical scope data.
- All 61 scoped current input files matched their recorded SHA-256 values. All 37 build-context source files matched their recorded values. The captured build-context tar SHA-256 was `db82224b2e58c39c39766cdb93ca049a8ed82b39b1a7404204e788816f4b43e4`; the captured build log SHA-256 was `812df266cf8abfa090592f4a3caf26267ca4b1e6ed254acc4fa4995bc678d419`; both current files matched.
- Scope, build inputs, image metadata, and reports identify the same image, `sha256:84deccc518a7aa5ce916d15236dac5ae416a5288449bd8620a2c8bb374c24b67`. Runtime metadata records Ubuntu 24.04.4 LTS, Linux aarch64, cgroup v2, and a non-production engineering observation. The image metadata, runtime metadata, and resource-profile file hashes matched the scope references.
- Resource profile SHA-256: `c85c68cc4329b1c622c2909b9fd99ea5c029fe04cbed120036d15893d5afc6d4`; policy source SHA-256: `10f33fbd312fc8dbdbcdd508f88720a5ead8ec96720645178aaa8946745a02bd`. The reports bind the recorded 8 GiB, 4 CPU, 600-second comparator timeout, 256,000-byte output cap, and one checker slot. Launcher, driver, and seccomp hashes were checked by the assessment against the current scope.
- The selected `declarations-kernel.txt` contains 27 declaration/axiom entries, including the selected classical energy-conservation, `Qubit.X_sq`, and `MState.purify_spec` declarations. The printed dependencies are the expected Lean axioms (`propext`, `Classical.choice`, `Quot.sound`) for these selections. This is a selected declaration inspection, not a semantic review or a proof of every declaration in the image.

## Actual observations

| Suite and requested mode | Cases | Verified | Blocked | Report SHA-256 |
| --- | ---: | ---: | ---: | --- |
| Core, kernel | 9 | 2 | 7 | `a5ae1de8dfc9f11d7228f12f84b234340d796f39dc2d4efc9af0d7d0c980b1e2` |
| Core, independent kernel | 9 | 2 | 7 | `e9173af4201763e4d87cefb1e7d6f7961b7386e06ea133d55597adab2d20c0b5` |
| Library, kernel | 3 | 2 | 1 | `4582dcea1b98f4dd9e1e3c5a1c2a0898e9769822e992551ad871a9aa7a47d672` |
| Library, independent kernel | 3 | 2 | 1 | `b278150fc00314918211371ffd9f0d0ef849fd8ec39b7529ad870084408b063c` |

The four run IDs were distinct. All 24 required case identities appeared exactly once in their respective reports. Eight positive cases had `verified/kernel_checked` with the requested assurance mode; 16 adversarial cases had `blocked/comparator_failed`. All 18 required diagnostic substrings appeared in the captured comparator output, including illegal-axiom, forged-receipt, denied-write, changed-dependency, and native-decision markers. The report statuses, codes, comparator exit codes, source fixture hashes, and causal observations matched the matrix. All 48 before/after case cgroup-memory samples were `observed` with no OOM kill increment. All 24 case containers and the fixed boundary container have distinct names and recorded successful `removed` cleanup.

The fixed boundary report SHA-256 is `7cfe33b7795cfabb34a3ede71935cdeb914c4b64388cebad6f56b05b9f588170`. Its 16 required checks were true, including nonroot execution, restricted privileges, seccomp, socket denials, canary integrity, denied protected writes, writable controls, no Docker socket, container configuration, and readable cgroup events. The boundary sample reported zero memory events; this does not exercise resource exhaustion.

The regression report SHA-256 is `0ed30019f796740b385d6c1dd8c53cabda59fad7e1092a80ae3bb7def7642482`, and its pinned JUnit XML SHA-256 is `869eebdb7d8cb3ad0e4965725464277f3a25732e5c031d58da717cdac5185ed6`. The recorded pytest exit code was 0. XML contains 225 test cases: 224 passed, no failures or errors, and one skipped. All 56 exact identities required by the four matrix groups were present and passed. The skipped `tests/test_acceptance_integration.py::test_postgresql_review_update_cannot_cross_acceptance_commit` is outside those required identities; current PostgreSQL race coverage remains a gap. Host protocol and synthetic transport tests are distinct from the real Linux suite and boundary observations.

## Limits and gates

These are engineering observations for one captured image/runtime and input snapshot. File hashes establish identity but do not authenticate the collector or prove that the recorded command produced the JUnit file. The required human gates remain deployment authority, scientific semantics, and fresh-environment review of the consolidated build/recovery recipe. The matrix also retains process-exit, host-containment, runtime-resource-stress, database-review-race, and resource-capacity gaps. The optional process-exit probe remains excluded after its security filter and was not retried. Historical 2 GiB OOM observations and prior PostgreSQL evidence do not become current 8 GiB or database concurrency evidence. No physics full-suite report was read or assessed here.
