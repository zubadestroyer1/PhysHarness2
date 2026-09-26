# Final Wave 0/1 integration audit

Worktree: `<repo>`.
Review current HEAD `3e507e4`, based on research-loop `470a286`.
Read `.state/wave01/final-wave01-review.diff` and prior reports
`resource-independent-audit.md`, `benchmark-audit.md`, `qualification-audit.md` in
this directory. The task is a final cross-component review; do not repeat closed
per-task reviews or their broad test suites without a new reason.

Required behavior: target-only exports do not contain evaluator proofs; scientific
approval cannot come from manifests or engineering reports; exact source, image,
runtime, resource and policy identities bind the qualification assessment; negative
cases require their actual causal failure; resource/transport failures remain loud
and cannot count as mathematical rejection; all required modes and cases are covered.
Assess the composition of these boundaries and the actual CLI/API paths, including
the canonical service's integration with the changed verifier configuration.

The default profile is 8 GiB, 4 CPUs, 600 seconds and one local lock slot. Its raw
file hash, canonical content hash and policy implementation hash are distinct.
The slot is only local to a shared lock path/namespace and compatible UID.
Do not claim VM/fleet admission control or qualified production deployment.

40 positive physics tasks and 20 altered controls are frozen. The controls are 11
mechanical nonacceptance attempts and nine valid proofs of semantically altered
statements. No model difficulty calibration or human approval exists. Current real
Linux reports are being collected by root in `evidence-8g`; historical 2 GiB reports
must not be applied to current source. Do not assess incomplete live files as final.

Read-only review. No code changes, Docker/Lean, GitHub, subagents or broad repeated
tests. A narrowly justified host reproduction is allowed if a concrete defect is
found. Record severity, exact paths/lines, reproduction and smallest necessary fix.
Write `work/wave01/final-integration-audit.md`; include both specification and code
quality verdicts and precise verification limits. Root owns all fixes and dispatch.
