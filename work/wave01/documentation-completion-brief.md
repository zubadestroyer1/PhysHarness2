# Task: align operator documentation with current Wave0/1 engineering

Use only <repo>
Root plans and owns actual execution; you are a GPT-5.6 Sol documentation implementer.
Do not spawn agents, run Docker/Lean, change implementation, commit, or use GitHub.

Update docs/VERIFICATION.md, docs/VERIFIER_QUALIFICATION.md, docs/FORMAL_ENVIRONMENT.md,
formal/README.md, docs/IMPLEMENTATION_STATUS.md and docs/ROADMAP.md only as relevant.
Preserve other files and all historical reports. Read resource-completion-report.md,
formal/verifier-resources.json and current relevant CLI --help/source for accurate commands.

Requirements:
- Current bounded resource profile is8GiB/4CPU/600s/one local checker slot. Distinguish
  canonical profile hash, raw profile-file hash and shared policy-source hash. Explain
  old qualification pins fail closed and changing resources requires relevant reruns.
- Single-bundle override is PHYSHARNESS_VERIFICATION_RESOURCES; registry entries have
  explicit resources. Never imply that a global override silently changes all entries.
- Slot locking applies to same serviceUID and lock path only; it is not fleet admission.
- Explain OOM must have counter/state evidence;137 alone is not enough. Failures stay
  blocked and do not count as a false-theorem rejection.
- Earlier2GiB runs are historical in work/wave01/evidence; new evidence-8g does not yet
  exist. Root is currently rebuilding; do not claim new runs or full qualification.
- Wave0 now has40 proposed real physics targets+20altered cases, separate from tiny
  algebra controls. References elaborated historically; human review/calibration pending.
- Wave1 code and limited control evidence exist; complete current-image benchmark and
  deployment/human gates remain pending until actual reports arrive.
- Default future VM provisioning must put COLIMA_HOME in persistent user-owned storage,
  e.g.$HOME/.local/share/physharness-colima, not /private/tmp. Existing historical commands
  and evidence still identify the old dedicated VM; do not migrate or recreate it.
  Explain why colima status alone was misleading after temporary metadata vanished;
  actual Docker endpoint/host-agent checks are needed for this recovery incident.
- Keep docs concise and avoid new frameworks, duplicate workflows, or invented approval.

Write work/wave01/documentation-completion-report.md with files/changes, consistency
checks and unresolved facts. Leave DELIVERY.md/progress.md/RESUME-2026-09-22.md to root.
