# Independent final control evidence audit

Worktree: `<repo>`.
Read `work/wave01/evidence-8g/scope-final.json`, image/runtime metadata, build-inputs,
the four core/library `*-final.json` reports, fixed-boundary-final.json, and
regressions-final.json/XML. Root has completed these real Linux runs. They are
immutable input to this audit. Physics full-suite reports are still active; leave
those and preliminary files outside this task until root explicitly says complete.

Independently verify source/evidence hashes, exact outcomes and causal markers,
requested assurance modes, resource/policy pins, cgroup observations, unique cleanup
records, and required regression identities. Call the actual assess_qualification
API read-only with scope-final and the final files; its expected current source
scope is e8f8c011e29242aa16f7464522b061545ac189f392c729655c57183a578ddb42.
The reviewer is free to report any discrepancy; the expected value is not approval.
Inspect the selected declaration audit and captured image identity consistency.

Report actual counts and limitations precisely. Core has nine controls; library
has three; both modes are required. Host pytest/synthetic coverage differs from real
Linux execution. Engineering reports cannot approve targets or deployment. The
optional process-exit probe remains excluded after a security filter and MUST NOT
be retried. All existing coverage gaps and human gates remain visible.

No code changes, Docker/Lean, GitHub, subagents, test-suite reruns, or mutations of
evidence files. Small host parsing/hashing/assessment scripts are allowed. Write
`work/wave01/current-evidence-audit.md`, with commands, results, hash identities and
limits. No arbitrary tool output is an approval or canonical proof receipt.
