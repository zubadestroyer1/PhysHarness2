# Task: finish interrupted verifier resource integration

Work only in <repo>
Implementer is GPT-5.6 Sol. Root controls planning, Docker/VM/Lean execution and GitHub.
Do not spawn agents, commit, push, run Docker, or execute Lean on the host.

Read existing dirty diff and these files first: verification/resource_policy.py,
boundary.py, container_driver.py, qualification.py; infra/run_qualified_lean.py and
probe_verifier_boundary.py; formal/verifier-resources.json and qualification-matrix.json.
The implementation was interrupted. Finish it rather than replacing its design.

Required behavior:
- One typed, bounded profile (currently 8GiB,4CPU,600s,one slot) drives actual limits,
  request/response bindings, runner/probe and qualification. Profile JSON source hash,
  canonical profile hash and policy implementation hash must not be confused.
- No hidden 110-second cap or contradictory legacy host timeout/output setting.
- Capture cgroup memory.events around checker execution and sanitized Docker State
  before cleanup where available. Confirmed OOM needs positive evidence; exit137 alone
  is uncertain. Timeouts/output overflow/transport failures are distinct blocked codes.
- Cleanup still runs and is confirmed; failure diagnostics survive cleanup. Never accept
  worker-controlled success files or fields. Preserve all existing isolation/axiom checks.
- Reject stale/mixed/missing resource pins in startup, runner, probe, benchmark assessment
  and qualification. Existing historical evidence stays unchanged and unqualified now.
- Slot lock claims only its actual local scope, not fleet scheduling.
- Keep changes focused; no new framework or generalized scheduler.

Root already added config/bootstrap optional PHYSHARNESS_VERIFICATION_RESOURCES and
benchmark assessment resource binding; include those in call-site compatibility checks.
Run focused tests first, fix actual integration failures with meaningful regression tests,
then run full ordinary Python suite once. Initial baseline log is
.state/wave01/resume-baseline-tests.log (root owns that process).
Existing .venv Python3.12 is available; no dependency upgrades are requested.

You own corrections in affected verifier/runner/probe/tests/docs (including root-added
bootstrap and benchmark compatibility if necessary). Mathematical manifests and generated
reference package are frozen. Do not modify work/wave01/evidence or old image metadata.

Report exact tests/exit results, files changed, unresolved concerns and image-input hashes
to work/wave01/resource-completion-report.md. Tell root when Dockerfile/driver/policy are
stable enough for the expensive real image build. Separate synthetic checks from real
execution. Independent human review and production qualification remain pending.
