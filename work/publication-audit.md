# Bounded repository publication audit

Reviewed 2026-09-15 UTC. Read-only review of candidate source/configuration,
dependency locks, Docker inputs, GitHub workflows, documentation and reports.
Only this report was written. No commit, staging change, remote publication,
model call, VM allocation, proof execution or cloud action was performed.

**No credential exposure or new publication-blocking source/configuration defect
was reproduced.** Both documentation hygiene findings below were fixed and
independently rechecked. This is a
bounded exposure/honesty review, not a claim that all possible secrets are absent
or that dependencies and infrastructure are security-qualified.

## P3 — Historical audit status is ambiguous — fixed

**Files/categories:** `work/acceptance-audit.md` — historical acceptance findings;
`work/platform-audit.md` — historical lifecycle regressions.

The acceptance report still introduces its original P1/P2 findings without a
prominent indication that subsequent fixes were independently rechecked. The
platform report retains a regression labeled pending correction even though the
later integration audit records it fixed. Publishing these together without
navigation makes current remediation status needlessly ambiguous.

**Recommendation:** retain the historical evidence, but add a clear superseded/
historical-status banner linking to the subsequent rechecks in
`work/core-audit.md` and `work/integration-audit.md`. This does not convert local
tests into actual Linux containment or kernel qualification.

**Recheck:** both historical reports now have prominent status banners. Their
follow-up links resolve to the recorded corrections/rechecks, and the banners
retain the distinction between code fixes and outstanding live qualification.

## P3 — Public status documentation includes transient operator context — fixed

**File/category:** `docs/IMPLEMENTATION_STATUS.md` — operator handoff and
connector/reconnection state.

The environmental/publication section includes conversation-specific operator
and connector status. These are not credentials, but they are transient handoff
details rather than durable project evidence and can become stale independently
of the source tree.

**Recommendation:** keep transient connector/reconnection details in excluded
handoff notes. Retain durable qualification limits and actual publication outcomes
in project documentation without implying an unobserved remote commit or PR.

**Recheck:** the transient operator/connector paragraph was removed. The public
ledger retains durable environmental and scientific qualification limits.

## Exposure checks

- Examined the 193 tracked/untracked candidate files visible at the initial scan,
  after applying the parent's explicit exclusions for `work/*-brief.md` and
  `work/*.diff`. The publication audit itself was created afterward. No candidate
  symlink, binary artifact, database, private-key bundle or signed credential URL
  was found.
- Credential-like matches were classified as synthetic tests, deployment
  placeholders, generated-value code, or disposable CI database configuration.
  The report deliberately includes no matching values.
- `infra/certs/rds-global-bundle.pem` is the public CA bundle, with corresponding
  digest/source metadata. It is not a private key. No other PEM/key archive was
  present in the candidate list.
- `.state/`, environment files, local caches, Python bytecode, installed
  dependencies, frontend output, Terraform provider binaries/state/plans and
  related transient directories are ignored and absent from the candidate list.
  Briefs and review diffs remain excluded by the parent's explicit staging plan;
  they are not assumed safe merely because they are untracked.
- `uv.lock` contains public-registry package sources and the expected editable
  project source. No credential-bearing, host-local or private repository
  dependency source was found. The frontend lock uses public registry URLs.
- Docker input exclusions cover local state, environments, private-key forms,
  Terraform state, work reports and generated research output. Dockerfile copies
  explicit application inputs and the public CA bundle; credentials are not
  embedded. The image is configured to run as a nonroot user.

The parent will explicitly stage candidate files. This scan is not an assertion
about files introduced after the scan or an authorization to stage excluded data.

## Qualification and workflow honesty

- README and the implementation ledger explicitly distinguish a development
  implementation from scientific/production qualification. At audit start the
  parent reported an aggregate dependency conflict under repair; the original
  aggregate number was explicitly historical. The parent subsequently reported
  successful final validation and updated the ledger. This auditor inspected that
  update but did not independently rerun the full aggregate, console, Temporal,
  Terraform or Compose checks listed in the final handoff below.
- `formal/qualification.json` remains blocked with review/kernel work unperformed.
  Self-hosting qualification remains unqualified and scale trials remain not run.
  Image metadata pins are labeled metadata-only.
- `work/ledger-replay-128.json` explicitly labels local SQLite replay and records
  zero live model calls/VM allocations, with live-fleet and scientific-throughput
  qualifications false. It does not substantiate a live worker-capacity claim.
- Temporal evidence is labeled a real local engine test with scripted activities,
  rather than hosted-model, cloud, kernel or scientific success. Runtime, browser,
  science and evaluation reports identify controlled/synthetic test evidence and
  retain their material limits.
- Pull-request CI has read-only default permissions, pinned external action
  references and no configured deployment/publishing secrets. Disposable database
  settings are confined to the CI service. Container CI builds/imports an image
  without publishing it.
- The final publication metadata additions, `.github/CODEOWNERS`, the pull-request
  template, contribution guidance and CI format check were read and scanned.
  They contain no credential/private-key/signature-token pattern matches.
  Contribution guidance explicitly states that repository administrators must
  enable branch protection and required independent review separately; checked-in
  ownership/workflow files do not turn those controls on.
- The proof workflow is manual, targets a separately administered qualified runner
  and protected environment, and requires operator-owned pinned inputs. Its
  presence is not treated as evidence that external protection rules exist or
  that any proof run occurred. Deployment docs explicitly require those controls
  before enabling the runner.
- Production deployment, actual model/VM behavior, independent kernel acceptance,
  expert review, dependency vulnerability coverage and live scale are not qualified
  by this publication review.

## Scoped validation

```text
.venv/bin/python infra/validate_metadata.py
Deployment metadata valid; no live infrastructure or proof qualification implied.

.venv/bin/python -m pytest tests/test_infrastructure.py -q
12 passed, 1 skipped in 0.22s
```

The skip is the unconfigured dedicated PostgreSQL endpoint. Secret-pattern,
special-file, source-URL and candidate-file checks were read-only local scans.
They did not print credential values. Metadata validation was rerun after the
final publication-file changes and passed again.

## Final handoff and evidence attribution

The parent reported the following final checks after fixing the aggregate
dependency conflict: 368 Python tests passed with two explicit infrastructure
skips and 21 upstream warnings; lint and formatting passed for 93 files; one real
local Temporal integration test passed; ten console tests and its production build
passed; the actual AWS Terraform module validated; and all Compose profiles passed
configuration validation. These are **parent-reported results**, not independent
executions by this publication auditor. The updated public ledger records their
limits and still marks every research/production wave unqualified.

This auditor independently performed the candidate exposure scans, publication
source/configuration/document review, both documentation-remediation rechecks,
the static metadata checks and the 12-test infrastructure selection above. No
broader engine review was added. There are no open findings from this bounded
publication audit. Explicit staging must continue to exclude the transient/private
categories identified in the agreed candidate selection.
