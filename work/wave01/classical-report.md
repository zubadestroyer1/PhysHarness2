# Classical benchmark author and peer-review report

Status: authored; all twenty positive references passed contained Linux elaboration against their current source hashes. Final Comparator/nanoda boundary runs remain with the root agent. Scientific meaning, new definitions and deployment qualification remain pending human review. This report and the peer review below cannot supply that approval.

The version-1 collection in `benchmarks/physics/classical.json` contains 20 positive targets and 10 altered cases. It preserves the preexisting algebra controls elsewhere. Each positive contains exact self-contained Lean Challenge and Reference source, assumptions, interpretation, a proof outline, primary provenance and known shortcuts. Each altered case contains exact target and candidate source and an explicit distinction between intended mechanical nonacceptance and a valid but semantically inappropriate replacement.

## Scope and composition

| Family | Targets | Split | Main capability |
| --- | ---: | --- | --- |
| oscillator_formulations | 4 | development | Physlib Newton/variational/Hamiltonian bridges and global energy composition |
| work_energy | 3 | development | Potential chain rule, applied power, viscous loss and global nonincrease |
| finite_power | 1 | holdout | Differentiation of a finite kinetic-energy sum |
| central_force | 2 | holdout | Local torque cancellation and global angular momentum |
| many_body | 2 | development | Opposite pair forces and arbitrary finite antisymmetric force arrays |
| exact_oscillator | 1 | development | Verification of an explicit trajectory and its acceleration |
| hamiltonian_flow | 1 | holdout | General finite-dimensional canonical chain rule |
| lagrangian_energy | 2 | holdout | Autonomous Euler–Lagrange energy and finite quadratic Legendre identity |
| canonical_maps | 2 | development | Alternating-form preservation, composition and nondegeneracy |
| discrete_oscillator | 2 | holdout | Iterated modified energy and midpoint physical energy |

All targets within each family share a split. Twelve targets are development and eight holdout. Shared mathematical notions and public library lemmas cross family boundaries, so these are family-level evaluation partitions, not a claim of conceptual isolation or that public material is unseen by models.

Difficulty is explicitly provisional: four foundation, twelve intermediate and four stretch. These are author estimates, not measured solve rates. The exact Physlib Hamilton-equation equivalence was downgraded to foundation after peer review because the library supplies the whole result. Finite kinetic power, local Lagrangian energy and the supplied discrete invariant are intermediate because short generic calculus or algebra compositions suffice. Intended physical reasoning and actual Lean API effort are described separately. No live-model calibration or new scientific discovery is claimed.

The collection includes four explicit Physlib API/formulation controls. Most other proofs require composing derivative certificates, equations of motion, finite sums or a discrete update rule. The algebraic canonical and discrete tasks are retained because they concern actual mechanics maps and invariants; they are not represented as hard proof-discovery problems.

## Mathematical assumptions and limits

- The Physlib oscillator structure enforces positive mass and stiffness. Its variational and Hamiltonian bridges require `ContDiff ℝ ∞` on all Physlib `Time`. The off-shell Hamiltonian/energy identity explicitly explains the totalized derivative and makes no regularity or conservation claim.
- Local calculus targets use `HasDerivAt` or `HasFDerivAt` at the relevant evaluation points. Global constancy or nonincrease requires the displayed derivative equations at every real time and invokes the connected-domain mean-value theorem. No existence theorem is smuggled into these conditional results.
- The central-force family assumes a common radial acceleration coefficient. It does not claim a collision-safe global theorem for singular gravitational forces. The finite particle power and momentum targets concern instantaneous force data when only a local result is stated.
- The general Hamiltonian target allows nonseparable autonomous functions on finite `ℝⁿ × ℝⁿ`; a full differential certificate specifies both partial gradients for all variations. The Lagrangian target identifies canonical momentum as the velocity partial derivative and assumes the Euler–Lagrange momentum equation. Neither assumes energy conservation itself.
- The finite Legendre task differentiates each diagonal kinetic term with other velocity terms held constant. It covers a natural Lagrangian with constant diagonal mass matrix, not arbitrary velocity-dependent interactions.
- Canonical maps act on one coordinate/momentum pair with an explicitly defined alternating form. The composition theorem also derives injectivity from nondegeneracy. No general manifold or nonlinear symplectic-map theorem is asserted.
- The kick-then-drift symplectic Euler invariant is `q²+p²−hqp`, twice a modified Hamiltonian. Its invariance holds for arbitrary fixed step but does not imply positivity or stability at arbitrary step. The separate midpoint task preserves actual quadratic oscillator energy conditional on satisfying the implicit update.

## Altered-case design

Six cases expect boundary nonacceptance: a candidate proof hole, restoring-force sign reversal, reversed damping monotonicity, anisotropic force presented as central, symmetric pair forces presented as action–reaction, and reversal of Hamilton's momentum sign. The latter five are mathematically false in general; their explicit candidate proof attempts are expected to fail for specified diagnostic classes. Failure of a particular proof attempt is not itself an independent proof that the proposition is false.

Four cases intentionally remain kernel-provable and require a semantic hold:

1. `deriv |·| 0 = 0` exploits the totalized derivative of a nondifferentiable cusp; it is not a classical velocity certificate.
2. Removing nonnegative damping leaves the power identity true but permits active energy injection.
3. Calling a modified invariant `physicalEnergy` changes its label without changing its step-dependent cross term.
4. Adding nonpositive mass to Physlib's positive-mass structure creates an empty hypothesis domain.

Semantic-hold cases have no fabricated textual compiler diagnostic requirements. Their success is precisely what makes separate scientific review necessary. The proof-hole case requires the acceptance boundary's illegal-axiom diagnostic: ordinary Lean elaboration may accept a source containing `sorry` with a warning.

## Provenance research

Pinned Physlib source was read directly from `/tmp/physharness-formal-sources/physlib`, including `Physlib/ClassicalMechanics/HarmonicOscillator/Basic.lean`. The exact source pin is `405848179db6375f814021e804a37dc0dda66d91`. Mathlib derivative and finite-sum APIs were checked directly at `db584cd6d46c92f209a44c0f1c829460d327499d`. Only the already selected oscillator Basic root and the built Mathlib closure are imported; no new Physlib root is needed.

Primary physics references were checked with the web tool on 2026-09-15:

- [David Tong, Newtonian Mechanics](https://www.damtp.cam.ac.uk/user/tong/dynamics/one.pdf), sections 1.2–1.3, for energy, damping, central force and many-particle laws. Search returned the relevant source passages; some direct fetches timed out. Target mathematics is an original scalar/finite-coordinate formalization.
- [David Tong, Lagrangian Formalism](https://davidtong.org/pdfs/teaching/classical-dynamics/clas2.pdf), section 2.4, equations 2.47–2.50, for canonical energy and Euler–Lagrange identities. The author's current PDF appeared in search after an older Cambridge chapter link failed.
- [David Tong, Hamiltonian Formalism](https://www.damtp.cam.ac.uk/user/tong/dynamics/dynhtml/S4.html), sections 4.1 and 4.4, for canonical signs, Legendre transform, conservation and canonical transformations. Relevant passages were available through search despite intermittent direct-fetch errors.
- [Ernst Hairer, Challenges in Geometric Numerical Integration](https://www.unige.ch/~hairer/preprints/hairer-pisa.pdf), section 2, for canonical flow and the two symplectic Euler update orders. The full primary PDF was fetched. The exact unit-oscillator modified quadratic invariant and midpoint energy identity here are direct original calculations, not claims that the paper states these exact Lean targets.

## Checks and observed failures

Author commands, run from the isolated worktree on macOS, performed source reading and JSON generation only:

```sh
python3 /tmp/build_classical_manifest.py
```

The temporary authoring script assembles self-contained source strings and writes only the owned manifest. It is not required to consume the final manifest. Inline Python validation checked exactly 20 positives and 10 altered cases, unique IDs, valid parent links, one split per family, no `sorry` in any positive reference, one target proof hole per positive Challenge, and consistent `classical_target` names. Those static checks passed. No Lean executable was run on macOS. VM lifecycle, images and the acceptance driver were not changed by this author.

Root-owned engineering evidence is retained under `.state/wave01/`:

- `classical-draft-2.json` and its log record an early Comparator draft attempt. The off-shell Hamiltonian/energy bridge passed; three other initial Physlib Challenge sources failed because the `∞` notation scope was absent. The batch was interrupted during resource contention. These partial results do not qualify the collection.
- `classical-elaboration-1.jsonl` and the exact source snapshots in `classical-compile-1/` record a contained direct-Lean diagnostic pass, not an acceptance receipt. Seven references passed; three failures used stale pre-scope-fix sources. The remaining failures exposed instance-transparency diamonds in generic derivative conversions and normalization details.
- The notation failure was traced to `scoped[ContDiff]` notation in Mathlib `Analysis/Calculus/ContDiff/FTaylorSeries.lean`; the Physlib source preambles now open that scope. Derivative proof conversions were updated to the pinned library's `convert!`/`using!` style. Changed source hashes require fresh evidence.

The root agent owns exact container commands, source snapshots, measured image identity, subsequent elaboration and final Comparator/nanoda qualification evidence. Final results must bind the current manifest source hashes; earlier passes must not be reported as current after a source edit.

The root subsequently delegated bounded classical draft retries using its fixed `compile_references.py`, while retaining ownership of VM lifecycle, images and final qualification. Retry 2 did not reach Docker: the macOS sandbox denied access to the dedicated VM's socket. This failure is retained in `classical-elaboration-2.err`; it was not a Lean failure or a cleanup claim. The explicitly authorized retry 3 received sandbox escalation and completed all 30 sources.

The author invoked:

```sh
python3 /tmp/run_classical_draft.py 3
```

Its complete executed argument list is archived at `.state/wave01/classical-compile-3/command.json`. The temporary wrapper only snapshots exact sources/hashes, invokes the fixed runner and records named-container cleanup. The underlying command was:

```sh
docker --host unix:///private/tmp/physharness-colima/default/docker.sock run --rm \
  --name physharness-classical-elaboration-3 --network none --read-only \
  --user 65532:65532 --cap-drop ALL --security-opt no-new-privileges \
  --security-opt seccomp=/Users/kieranpi/Desktop/Projects/PhysHarnessV2/.worktrees/formal-research-loop/.state/wave01/classical-compile-3/seccomp.json \
  --cpus 1 --memory 2g --pids-limit 128 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=256m \
  --mount type=bind,source=/Users/kieranpi/Desktop/Projects/PhysHarnessV2/.worktrees/formal-research-loop/.state/wave01/classical-compile-3,target=/input,readonly \
  --workdir /opt/sources/physlib --entrypoint python3 \
  physharness-formal:physics433-final /input/compile_references.py
```

The fixed runner used `lake --offline env /opt/lean/bin/lean /input/caseN.lean`, with a 90-second bound per source. No candidate olean cache was reused. The run used the existing `physics433-final` image, measured by the environment evidence as `sha256:6179eb7308aaba0ee8287f24857cd122efede0fb9acf8b9fa217ed030e386a68`; final deployment/image qualification remains separate.

Fresh results in `.state/wave01/classical-elaboration-3.jsonl`:

| Source category | Result |
| --- | --- |
| Positive references | 20/20 exit zero |
| Semantic-hold candidates | 4/4 exit zero |
| False altered candidates | 5/5 exit nonzero with all required diagnostic substrings |
| Proof-hole candidate | Exit zero with `sorry` warning; final Comparator `sorryAx` rejection still required |

All 30 source SHA256 values in that log were compared to the current manifest and matched. The five expected false-case diagnostics were `Type mismatch`, the `antitone_of_deriv_nonpos` application failure, or residual `unsolved goals`, as specified per case. The named-container inspection returned `No such container: physharness-classical-elaboration-3` after successful `--rm` exit; `.state/wave01/classical-compile-3/cleanup.json` retains that daemon response. Source snapshots, the unchanged runner copy, seccomp policy and exact task/hash map are retained in the same directory.

The manifest SHA256 at author handoff is `c381f3cb04f821262d5392503b9a4447873f3b6c0fb7cf68c4a25edb2ad3762e`. These are elaboration diagnostics, not Comparator acceptance, nanoda replay, human semantic approval or production qualification. The root was asked to schedule final serial boundary runs for all references and altered cases, including the proof-hole rejection.

## Independent AI review

The quantum agent reviewed all twenty classical positive sources and all ten altered sources. It found no mathematical scope mismatch and checked the modified-energy counterexample explicitly. It recommended more conservative difficulty labels and correcting a rationale that said the invariant was selected when the target already supplied it; those changes were made. Its review explicitly leaves compiler/API validity to real executions and human scientific approval pending.

This author independently reviewed all twenty quantum positives and ten altered cases, checking partial-trace orientation against the pinned definitions, no-cloning scope, pure-global entanglement assumptions, product-state channel limitations, dephasing Hermiticity, altered-case examples, shortcut disclosure and consistent family splits. No mathematical findings were identified. A provisional calibration suggestion was sent for the short trace/commutation energy-conservation proof. This is an AI engineering review of the manifests, not a scientist's approval.
