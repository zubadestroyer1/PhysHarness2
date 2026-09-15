# Physics benchmark review and calibration

The Wave 0 physics inventory contains **40 positive targets and 20 altered cases**,
split equally between quantum and classical programs. The manifests are proposed
scientific inputs, not approvals. Machine checks, expert meaning review, and measured
model difficulty are separate evidence. The original tiny algebra fixtures remain in
`benchmarks/registry.json`; they are not silently relabeled as physics results.

## Selection and limitations

The targets exercise 19 families with explicit finite-dimensional, differentiability,
mass/sign and model assumptions. Eight are foundation controls, 26 intermediate and
six stretch **author estimates**. Existing theorem shortcuts are disclosed in every
task. A historically significant result can be an easy API-retrieval task in an
environment that already contains its proof. No target is claimed to be an open
problem, a calibrated SOTA challenge, or independent of pretraining data.

Quantum targets cover complex states/operators, gates, effects, tensor structure,
channels, no-cloning, dephasing, unitary invariants and a Bell marginal. Classical
targets cover oscillator formulations, force/energy balance, derivatives of finite
kinetic sums, angular/linear momentum, Hamiltonian and Lagrangian energy identities,
canonical transformations and exact integrator invariants. Infinite-dimensional
operators, continuum PDEs and field theory are outside this initial inventory.

Whole mathematical families determine 23 development and 17 holdout positives.
Altered cases inherit their parent's split. ID/family consistency, source duplicates,
parents and counts are mechanically checked. These checks cannot identify every
mathematically equivalent or closely related theorem. Reviewers must inspect overlap
between families, particularly shared energy and trace arguments. Public holdouts are
held out of a development experiment, not secret or guaranteed unseen.

Eleven altered cases expect mechanical nonacceptance, including a proof hole. Nine
deliberately compile as valid theorems but change the physical question: for example,
an inconsistent mass domain, a totalized derivative at a cusp, a circular premise, or
identity dynamics replacing general dynamics. These require a semantic hold. The
kernel checks the exact theorem; it does not approve its natural-language meaning.

## Prepare and inspect

Run commands from the repository root after `uv sync --frozen`:

```sh
uv run python tools/physics_benchmark.py inventory
uv run python tools/physics_benchmark.py prepare --output .state/physics-review-v1
uv run python tools/physics_benchmark.py export --split holdout --output .state/worker-targets.json
```

`inventory` exits 2 for an incomplete release inventory, 1 for invalid input, and 0
for structurally complete counts. Zero never grants scientific review. All writes
require a fresh destination; failed commands emit structured errors with a code and
reason. These are operator-local tools. Choose trusted directories; they are not a
sandbox against an attacker concurrently replacing the operator's filesystem.

The evaluator package contains `REVIEW.md`, exact `Challenge.lean`/`Solution.lean`
files, source assumptions and provenance in `review.json`, pinned project files,
`cases.json` for the real engineering runner, and a content-hash manifest. It includes
reference proofs and must remain outside discovery-worker storage and retrieval.
Export only the separate target file into a fresh worker environment. Excluding
reference fields from JSON alone does not enforce filesystem, network or retrieval
isolation. Do not expose the whole public checkout to a restricted-discovery worker.

## Human review procedure

1. Assign an identified quantum or classical reviewer with the appropriate domain
   expertise. Review the exact benchmark digest and sources, not a mutable task name.
2. Compare the informal claim with quantifiers, types, hypotheses and definitions.
   Check finite/infinite scope, positivity, regularity, units, derivative conventions,
   trace/tensor orientation, normalization and boundary conditions where applicable.
3. Inspect reference dependencies and shortcuts. Reject circular definitions, vacuous
   domains and hidden target assumptions. Check examples and each altered-case
   rationale; a failed candidate alone does not prove that its statement is false.
4. Record approve/revise/reject/hold decisions with reasons for every positive and
   altered case. Do not record a semantic-hold case as an approved solution to its
   parent. Changed sources form a new revision and require fresh affected evidence.
5. For an actual research run, register the selected exact target and environment
   through the existing problem/run-plan service. Use a separately issued reviewer
   identity and `phys review-target` with the inspected canonical target digest and
   rationale file. The benchmark digest identifies the collection and is **not** a
   replacement for the canonical problem's target digest.

The review packet supplies all material to make these decisions but contains no
fabricated signatures. The authoring agents' mutual mathematical reviews are AI
audits, not independent human scientific approval. See [first live run](FIRST_LIVE_RUN.md)
for canonical registration, reviewer identity and live-run preflight.

## Reference execution and evidence

Run Lean only in the isolated Linux acceptance environment. Direct Lean elaboration
is useful diagnosis but permits `sorry` warnings and does not establish acceptance.
Use the fresh image metadata and runtime observation with the acceptance runner:

```sh
uv run python infra/run_qualified_lean.py --help
```

Supply the package's `cases.json`, then run both ordinary and independent-kernel
modes. Preserve failures and logs. After both complete, assess exact observations:

```sh
uv run python tools/physics_benchmark.py assess \
  --bundle .state/physics-review-v1 \
  --image-metadata PATH_TO_IMAGE_METADATA \
  --kernel-report PATH_TO_KERNEL_REPORT \
  --independent-report PATH_TO_INDEPENDENT_REPORT \
  --output .state/physics-assessment-v1.json
```

Assessment checks all expected cases, source/target/environment hashes, checker
versions and execution pins, assurance, causal failure diagnostics and confirmed
cleanup. A challenge-construction error cannot stand in for the intended candidate
failure. Semantic holds remain pending even when both kernels accept their proofs.
The checks establish consistency of operator-supplied evidence; hashes do not
authenticate a malicious collector or turn JSON into an authoritative receipt.
Deployment qualification uses its separate [scope and review packet](VERIFIER_QUALIFICATION.md).

## Fair model calibration

Freeze the benchmark, environment, model/runtime, allowed information, tool limits,
budget and scoring rule before evaluation. Keep an open-library track for legitimate
theorem reuse and a separately audited restricted-discovery track. Do not report an
imported proof as new derivation. If excluding a theorem would require rebuilding
the dependency environment, do that explicitly and rerun reference qualification;
name filtering alone cannot remove proof information from imports.

Start with the direct loop and independent repeated attempts. Compare policies at
both equal recorded cost and equal wall time, counting verification, retries,
retrieval, warm caches and coordination. Report per-family outcomes, uncertainty,
time to accepted solution, review effort and infrastructure failure rates. Preserve
predeclared treatment of failures and timeouts; never drop expensive failed runs.

Measure whether each estimate produces useful differentiation. Keep easy controls
for regression diagnosis, and add harder expert-authored tasks where results saturate.
Do not tune methods on holdout failures and continue advertising that same holdout as
untouched. Revision and family membership must flow into future training/contamination
records. This inventory alone cannot demonstrate open-problem solving or scalable
scientific throughput.
