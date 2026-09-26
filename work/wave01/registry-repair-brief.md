# Registry resource-source repair

Work only in `<repo>`.
User requires GPT-6 Sol implementation; root plans and controls all execution/evidence.
Base HEAD is `3e507e4`. Read `final-integration-audit.md` for the exact P2 finding.

Ruling: make registry startup verify actual profile bytes, matching single-bundle
startup, instead of relying on an operator-declared source hash. This makes the
source identity claim consistent. It is not a proof-forgery exploit or authority
escalation. Cost: existing registry configurations need an explicit profile path.

Small repair: add an explicit resource-profile file path to each RegistryEntry;
require an absolute path for stable meaning; in registry initialization read bounded
non-symlink bytes once, parse the strict existing profile format, and compare raw
SHA and canonical content against BOTH config and qualification. Put validation in
the shared constructor path so direct construction cannot bypass file verification.
Preserve current policy-source, bundle, selector and manifest checks. Do not add a
new service, approval mechanism or generalized configuration framework.

Test real temporary files: valid registry; missing legacy path; whitespace-only
file modification with unchanged canonical values; value mismatch; symlink source;
missing/oversized/duplicate-key input with loud failure before any verifier route is
exposed. Reuse current tests where possible; ensure direct construction and from_file
use the same boundary. Update narrow operator docs and qualification matrix with
the specific new source-binding regression. Preserve existing evidence and fixtures.

FROZEN image inputs: Dockerfile, tools/formal_environment.py, driver, policy,
all Lean/project sources. Also do not modify boundary.py or infra/run_qualified_lean.py
without first telling root why; real checker runs are active. No Docker/Lean/GitHub,
no subagents. Do not modify evaluator REVIEW.md (frozen package bytes); the reported
trailing blank line is nonfunctional and retained rather than invalidate the package.

Cover changes with narrow tests, Ruff checks and then the ordinary suite if the
configuration fixtures need broad edits. Report exact commands/outcomes, touched
files and limitations in `work/wave01/registry-repair-report.md`. Do not commit.
Root independently reviews and commits through GitHub MCP.
