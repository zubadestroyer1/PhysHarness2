# Wave 0 benchmark and Wave 1 verifier implementation plan

> For agentic workers: use subagent-driven development, scoped independent reviews, and fresh verification evidence.

Goal: deliver a reproducible, scientifically meaningful 40-target physics suite with 20 altered cases, a usable review queue, and scoped verifier qualification evidence. Human scientific and deployment approval remain pending until an authorized reviewer supplies them.
Architecture: keep the original algebra controls, add versioned physics manifests and evaluator-only reference artifacts, connect mechanical evidence to exact input hashes, and separate scientific review from engineering observations. Qualify one pinned Linux deployment, never infer fleet capacity or universal soundness.
Tech stack: existing Python 3.12/Pydantic/CLI services, Lean4.33.0/Mathlib/Physlib/QuantumInfo/Comparator/nanoda, dedicated Colima Linux builder.
Spec: docs/IMPLEMENTATION_PLAN.md Waves0–1 and the approved Wave0/Wave1 workstreams in this conversation.

## Global constraints

- No fabricated expert approval, production qualification, minimal axiom-closure claim, live-model result or difficulty calibration.
- Original algebra fixtures remain explicitly distinct from the new physics benchmark.
- Forty positive targets: twenty quantum and twenty classical. Twenty altered cases: ten per program. Task quality and faithful assumptions take priority over filling a count with near-duplicates.
- Difficulty is an author estimate until measured. Record direct-library shortcuts and intended capabilities. Use family-level holdouts and target-only discovery exports; published material cannot be claimed unseen by models.
- Every task has exact Lean source, reference source, interpretation, assumptions, proof outline and provenance. Negative cases distinguish mechanical nonacceptance from mathematically valid but semantically altered claims.
- New semantic concepts and scientific meanings require explicit human review. Generated reports and model votes cannot issue approval.
- Candidate Lean runs only inside the dedicated isolated Linux VM, never directly on macOS. Keep trusted imports read-only and preserve the existing independent acceptance boundary.
- No paid model API calls or cloud deployment. Root owns VM start/stop, image build/export and test scheduling. Shut the VM down as soon as Linux work and preservation finish.
- Preserve existing evidence, observed failures and exact recipes. Do not retry the previously security-filtered optional process-exit probe or conceal its uncompleted coverage.
- GitHub writes use the user's MCP for commits on codex/benchmark-verifier-qualification, stacked on PR20; never merge or bypass review protections.

## Tasks and acceptance

- [ ] Task1: quantum target collection. Owner quantum agent. Files benchmarks/physics/quantum.json and work/wave01/quantum-report.md. Research pinned source and primary references, design twenty genuinely distinct targets plus ten justified altered cases, write Lean reference sources, and state proof shortcuts and difficulty limitations. Root schedules contained compilation. Independent classical/whole-suite review checks faithfulness and representativeness.
- [ ] Task2: classical target collection. Owner classical agent. Files benchmarks/physics/classical.json and work/wave01/classical-report.md. Same deliverables, emphasizing actual dynamics, differentiation assumptions, conservation/dissipation, Hamiltonian/Lagrangian identities and invariants rather than disconnected rational algebra.
- [ ] Task3: verifier qualification matrix and regression hardening. Owner verifier agent. Files src/physharness/verification/qualification.py, tests/test_verifier_qualification.py, formal/qualification-matrix.json, docs/VERIFIER_QUALIFICATION.md, work/wave01/verifier-report.md. Define testable required coverage, validate evidence identities/positive controls/causal failures/cleanup and human-review distinction, audit relevant existing boundary code, add meaningful regressions, and propose isolated engineering executions. Coordinate any shared infra/driver edits with root first.
- [ ] Task4: benchmark schema, review/export/evidence workflow. Owner root. Files src/physharness/science/physics_benchmarks.py, tools/physics_benchmark.py, tests/test_physics_benchmarks.py, docs/PHYSICS_BENCHMARK_REVIEW.md. Test malformed identities, family leakage, changed sources/stale evidence, shortcut/evaluation labels, semantic-negative handling, target-only exports and pending approvals before implementing. Consume program manifests below and emit reproducible evaluator manifests plus readable review packets.
- [ ] Task5: real build and reference/qualification runs. Owner root, physics agents assist only through scheduled isolated invocations. Rebuild final consolidated image from pinned sources, verify fresh-environment recovery (no candidate caches), run all valid references and justified altered cases, expand ordinary boundary/failure controls, retain exact reports and fix genuine failures. Report missing capabilities loudly rather than altering expectations to pass.
- [ ] Task6: independent audits, final regression checks, public evidence and GitHub PR. Cross-review mathematical sets and code via exact diff packages, fix findings/recheck, run complete applicable CI/local checks, export built images, verify archive and stop VM. Prepare concrete pending human review packages and explain remaining gates explicitly.

## Program manifest contract (version1)

Each collection: {"version":1,"program":"quantum"|"classical","tasks":[...],"negative_cases":[...]}.
Each positive: id, family, split(development|holdout), title, difficulty_band(foundation|intermediate|stretch), difficulty_rationale, capabilities(list of strings), statement, assumptions(list), physical_scope, provenance(list of {uri,locator,note}), target_theorem, target_source, reference_source, reference_outline, known_shortcuts(list of {declaration,note}), limitations(list).
Each negative: id, parent_id, category, expected_outcome(kernel_nonacceptance|semantic_hold), target_source, candidate_source, rationale, required_diagnostics(list), semantic_change(string). A semantic_hold case intentionally can pass the kernel for the wrong intended meaning; do not require kernel rejection. Definitions/assumptions whose meanings are not reviewed stay pending.
Use unique task IDs program.family.slug; all positive tasks in one family share a split. Negative split is inherited. All review/compiler status is supplied by separate real evidence, never by task authors.

## Coordination and validation

Task1/2 produce disjoint manifests consumed by Task4. Schema changes are coordinated before edits. Task3 and Task4 share only hashes and the existing engineering outcome/report contract; no direct imports are needed until stable. Root alone changes VM state. Each implementer records exact commands/results and unresolved findings; reviewers receive a full scoped diff and brief. Baseline is60e8254c02e8cbfce08201bac1ff2b7ce2224a1c. Working directory remains the existing isolated formal-research-loop worktree to retain the expensive image/cache and mount identity.
