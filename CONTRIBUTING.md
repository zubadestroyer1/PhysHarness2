# Contributing to PhysHarnessV2

Contributions should make physics research more capable, reproducible, and easy to inspect.
Start with the [roadmap](docs/ROADMAP.md), the [implementation evidence ledger](docs/IMPLEMENTATION_STATUS.md),
and the [approved plan](docs/IMPLEMENTATION_PLAN.md). Implemented code and qualified capability
are different milestones; every implementation wave currently remains unqualified.

## Choose a contribution

- Fix a reproducible fault, improve diagnostics, or strengthen an adapter contract.
- Help qualify the Lean environment, acceptance boundary, or durable execution path.
- Propose a precisely stated physics target, audit library declarations, or review assumptions.
- Improve documentation, accessibility, retrieval, or experiment evaluation.

Use the repository's issue forms for bugs, engineering work, research targets, and qualification
evidence. For a small correction, a pull request with a clear explanation is sufficient.
Discuss changes to public contracts, scientific assumptions, trust boundaries, or deployment
architecture in an issue before undertaking a large implementation. Record significant decisions
and alternatives in a versioned design document under `docs/` and link it from the issue.

The [project-management guide](docs/PROJECT_MANAGEMENT.md) explains labels, wave milestones,
triage, and review. A `good first issue` should identify a bounded change and how to validate it.
Do not assume an unassigned issue has no active investigation; leave a short comment before
starting substantial work.

## Set up and validate

Use Python 3.12 and the versions pinned in the lockfiles. From the repository root:

```sh
uv sync --locked --all-extras
uv run ruff check src tests tools infra migrations
uv run ruff format --check src tests tools infra migrations
uv run pytest -m "not integration and not lean" -q
uv run python infra/validate_metadata.py
```

For console changes, use a supported Node version from `console/package.json`:

```sh
cd console
npm ci
npm test
npm run build
```

The build includes TypeScript checking. Run focused tests while developing, then the relevant
repository checks before requesting review. Infrastructure and Lean checks have separate
requirements; consult [deployment](docs/DEPLOYMENT.md), [operations](docs/OPERATIONS.md),
and [verification](docs/VERIFICATION.md). The local Temporal integration suite is enabled with
`PHYSHARNESS_RUN_TEMPORAL_TESTS=1`; report it separately from scripted transport tests.
Report unavailable prerequisites and skipped tests explicitly. Do not turn a missing service,
credential, kernel, or dependency into a passing fixture.

Live experiments require an explicit manifest, exact model identifiers, configured prices, and
a resource envelope. Routine CI must not incur hosted-model or cloud-experiment spending.

## Make a reviewable pull request

1. Link the issue and state the specific behavior being added or corrected.
2. Create a branch such as `codex/42-verifier-timeout-diagnostics`. Keep unrelated work separate.
3. Make small, coherent commits with descriptive messages, for example
   `fix: preserve operation IDs in verifier timeouts`.
4. Add meaningful regression coverage when behavior warrants it. Update contracts, migration
   guidance, and documentation affected by the change.
5. Open a draft PR early for substantial work. Include checks actually run, explicit limitations,
   and any schema, workflow, environment, or API compatibility effects.
6. Request the relevant review when ready. Resolve failures and review findings before merging.

Use `Closes #…` only when the PR completes that issue's acceptance criteria. Use `Refs #…`
for partial progress or wave tracking. A merged implementation PR does not qualify a wave.
Never merge a wave-tracking issue through a closing keyword unless its evidence gate is met.

## Review and scientific integrity

Acceptance logic, trusted definitions, credential boundaries, and result-promotion rules require
independent human review. Substantial runtime and coordination changes also need a reviewer
other than the implementer. Automated and model-assisted reviews supplement that review.
An author cannot provide their own independent approval. If no suitable reviewer is available,
keep the affected PR pending and identify the missing review instead of bypassing it.

Expert judgments about target meaning and novelty must identify the actual reviewer and scope.
Formal proof status, reviewed meaning, assumptions, numerical evidence, and novelty remain
separate. A Python certificate check, a successful compilation, or a simulated verifier response
does not establish independent proof acceptance. Preserve the distinction in code, UI, tests,
PR descriptions, and reports.

Errors should carry an operation identifier, a useful diagnosis, and a remediation. Preserve
tracebacks in appropriate private logs. Infrastructure failure must not become proof rejection,
an empty success, or a fabricated result. See [operations](docs/OPERATIONS.md) for incident handling.

## Keep public contributions safe to reuse

Keep credentials, private transcripts, unreviewed novelty claims, generated caches, and live
research workspaces out of Git and public issues. Use small synthetic reproductions and redacted
diagnostics. Follow [SECURITY.md](SECURITY.md) and use
[private vulnerability reporting](https://github.com/zubadestroyer1/PhysHarness2/security/advisories/new)
for security reports; do not post exploit details or secrets in a public bug report.

New project code uses Apache-2.0. Preserve upstream licenses and attribution. Record provenance
and permitted use before adding papers, benchmark examples, proof artifacts, or training data.
Only curated, reviewed scientific exports belong in the public repository.

Repository settings are configured separately from checked-in templates. `CODEOWNERS` routes
review requests but does not enable branch protection, supply independent reviewers, or verify
scientific claims. Release and qualification records must describe the settings and evidence
actually observed.
