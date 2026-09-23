# Bounded fairness audit of the frozen physics benchmark

This is an AI review of both frozen collections and `docs/PHYSICS_BENCHMARK_REVIEW.md`. It is not human scientific approval, a model evaluation, or a difficulty calibration. No task, reference proof, manifest, documentation, Lean environment, or Docker state was changed. The audit identifies evaluation controls; no frozen-source change is required for the current reference/verifier runs.

The suite can support a bounded comparison of proof construction and theorem reuse on these public, hand-selected finite physics targets, under identical disclosed resources and information access. It cannot by itself establish novel derivation, unseen-family generalization, broad mathematical-physics competence, open-problem solving, or scalable scientific throughput. The documentation already makes most of these limits explicit. Its main remaining protocol gap is an explicit separation of model proof-solving scores from the altered-case and semantic-review denominators.

## Inventory and scoring denominators

Counts were independently recomputed from the frozen JSON, not inferred from successful proof-checker outputs.

| Cohort | Quantum | Classical | Total | Development | Holdout |
| --- | ---: | ---: | ---: | ---: | ---: |
| Positive proof targets | 20 | 20 | 40 | 23 | 17 |
| Mechanical nonacceptance controls | 5 | 6 | 11 | 8 | 3 |
| Valid semantic-hold controls | 5 | 4 | 9 | 6 | 3 |
| All engineering cases | 30 | 30 | 60 | 37 | 23 |

The 19 named families comprise nine development families and ten holdout families. The author estimates are eight foundation, 26 intermediate, and six stretch. These counts agree with the documentation.

Required reporting separation:

1. **Positive proof solving:** the denominator is 40 for the full set or 17 for the predefined holdout; also report quantum/classical denominators separately. A success means the submitted proof for the exact positive target satisfies the predeclared acceptance mode within its budget. A 60/60 engineering expected-outcome result is not 60 model-solved physics problems. Nor should all 49 expected accepted cases—40 positives plus nine semantic controls—be counted as positive proof solutions.
2. **Mechanical nonacceptance:** report 11/11 fixed altered proof attempts separately, with the expected causal diagnostic and corresponding positive control. Ten are false mathematical mutations; `classical.altered.proof_hole` is an incomplete proof of an unchanged, valid target. Therefore this cohort must not be labeled eleven false statements. A failure of the submitted proof is not a general proof of the proposition's falsity.
3. **Valid-control proof acceptance:** report whether the checker accepts the nine supplied mathematically valid semantic-control proofs. Rejection of a valid control is a mechanical failure, not successful semantic discrimination.
4. **Semantic fidelity:** separately assess whether a reviewer/model detects that each of those nine claims is unsuitable as a solution to its intended parent. The expected pair is **proof accepted, semantic substitution held**. Include a false-hold rate on matched positive parent claims, otherwise an always-hold classifier appears perfect. These nine cases cover only eight distinct parent tasks because two quantum dephasing mutations share a parent. Treat that dependence explicitly. Model review recommendations remain recommendations; they do not create the missing human approval records.

For repeated attempts, predeclare whether the measure is one-attempt success, target solved at least once within a fixed total budget, or a multi-attempt probability estimate. Do not count retries as additional benchmark problems or select the best run after inspecting results. Keep failures, resource exhaustion, and timeouts in the predeclared denominator. A separately labeled infrastructure-adjusted measure may be useful, but dropping failed cases from the headline score after the fact would bias comparisons.

The current `assess` workflow is an engineering expected-outcome assessor, not a model leaderboard or a semantic classifier. Its fixed pending-review status must not be used as the model's semantic prediction. Labels such as `expected_outcome`, `category`, `rationale`, `semantic_change`, revealing `altered_*` IDs, and supplied candidate proofs should be hidden from a blind model-review exercise except where that exercise explicitly requires a proof. Provide the parent intended claim and the proposed formal claim as the review input, with anonymized neutral IDs. The current target-only discovery export contains positives; it is not yet a blind semantic-control export.

## Concrete mathematical overlap across family splits

Family membership is internally consistent, but the following shared proof patterns cross the named development/holdout boundaries. These are generally useful transfer tasks, not invalid statements or exact duplicate targets. They limit what “held out” can mean.

| Development material | Holdout material | Shared mathematics and honest interpretation |
| --- | --- | --- |
| `classical.work_energy.conservative_power`, `classical.work_energy.forced_damped_power`, and `classical.many_body.finite_internal_force` | `classical.finite_power.kinetic_work` | Development exposes the differentiated quadratic kinetic term, mass cancellation, and `HasDerivAt.fun_sum`. The holdout recombines those ingredients into summed work. It tests finite-sum transfer, not an unseen work-energy concept. |
| `classical.many_body.two_body_momentum` and `classical.oscillator_formulations.newton_energy_two_times` | `classical.central_force.angular_momentum_constant` | Both sides turn a locally derived zero time derivative into a two-time invariant. In particular, the first development task already uses `is_const_of_deriv_eq_zero`, which is also the global step of the holdout. The new part is the torque cancellation. |
| `classical.oscillator_formulations.legendre_energy_bridge` | `classical.lagrangian_energy.finite_legendre_identity` | Both identify a quadratic-kinetic Legendre energy with kinetic plus potential energy. The holdout adds finite sums and explicit differentiation, while the development task supplies a direct library bridge. This is a representation/scale transfer within the same physical construction. |
| `classical.work_energy.conservative_power` and `classical.oscillator_formulations.newton_energy_two_times` | `classical.hamiltonian_flow.finite_energy_rate`, `classical.lagrangian_energy.autonomous_energy_rate` | Autonomous energy conservation is shared. The holdouts change formal derivative representations and cancellation mechanisms; their differential/gradient certificates and equations of motion are already hypotheses. They do not ask the model to discover a Hamiltonian, derive the equations, or establish flow existence. |
| `classical.canonical_maps.drift_shear`, `classical.canonical_maps.composition_injective` | `classical.discrete_oscillator.modified_energy_iterates`, `classical.discrete_oscillator.midpoint_energy` | The development set exposes elementary canonical maps; the holdout integrators use related phase-space structure and quadratic identities. The modified invariant is supplied by definition, so proving it is not discovering a new invariant. |
| `quantum.composites.product_pure_iff`, `quantum.composites.entanglement_reduced_purity`, `quantum.composites.purification_with_pure_global` | `quantum.bell.entangled_with_mixed_marginal` | Pure density operators, marginal traces, purity and entanglement already appear in development. The Bell target is a concrete normalized matrix/partial-trace calculation plus an imported entanglement theorem, not a completely withheld entanglement topic. |
| `quantum.composites.product_pure_iff` and `quantum.composites.purification_with_pure_global` | `quantum.dynamics.unitary_purity_conservation` | `MState.pure_iff_purity_one` is used in both cohorts. The holdout adds a unitary overlap invariant and transports the same purity characterization. |
| `quantum.composites.product_pure_iff` and `quantum.effects.binary_normalization` | `quantum.channels.independent_outputs_marginal`, `quantum.channels.sequential_heisenberg` | Product states and expectation/normalization language transfer into channel tasks. The required channel and dual-map lemmas add real API composition; this is related finite operator theory rather than unrelated mathematics. |
| `quantum.gates.pauli_commutator` and `quantum.decoherence.complete_dephasing_projection` | `quantum.bell.entangled_with_mixed_marginal` | `matrix_expand` and small complex-matrix normalization are exposed in development and automate much of the Bell reference. The physics meaning differs while the available proof automation is shared. |

Within the holdout itself, `classical.central_force.zero_torque` is the local component of `classical.central_force.angular_momentum_constant`. Likewise several quantum holdouts share purity and unitary APIs. Evaluating all holdouts in one persistent conversation with earlier solutions and feedback available changes the task into cross-task learning. For a static comparison, reset solver state between targets, isolate retrieval, and predeclare whether successful earlier holdout proofs become available. If continual learning is the intended track, use an identical predeclared order/policy across methods and report it as such.

There is also broad cross-program overlap in invariant reasoning, polynomial simplification, and translating local identities into physical conservation statements. This does not make the real derivative and complex trace tasks equivalent. It does mean the 40 targets are not 40 independent samples of all mathematical physics.

For a future stronger family-generalization experiment, group the linked topics into larger dependency clusters or construct genuinely new expert-reviewed families. Do not relabel or repartition the frozen set after seeing holdout performance and continue calling it untouched. For the present suite, describe the result as transfer among related publicly specified families and publish this overlap map.

## Difficulty versus available shortcuts

The estimates and disclosure language are appropriately provisional. Reference length alone does not establish empirical difficulty, but the following cases particularly constrain claims about deep derivation:

- `classical.oscillator_formulations.newton_equivalence` and `classical.oscillator_formulations.hamilton_equivalence` are exact imported-theorem applications. `classical.oscillator_formulations.legendre_energy_bridge` is a pointwise use of an imported function equality. Their foundation labels are appropriate controls under the declared imports.
- `quantum.composites.purification_with_pure_global` supplies an existing purification witness. `quantum.cloning.nonorthogonal_no_common_cloner` invokes the imported no-cloning theorem after overlap conversion. The former foundation and latter intermediate labels acknowledge this; successful proofs would not be fresh derivations of purification or no-cloning.
- `quantum.geometry.global_phase_measurement`, `quantum.dynamics.unitary_purity_conservation`, `quantum.channels.replacement_absorbs_history`, and `quantum.channels.independent_outputs_marginal` have short imported-lemma compositions. If a model saturates them, preserve them as controls rather than advertising their historical physics content as model difficulty.
- `quantum.gates.pauli_commutator` is solved by the specialized matrix tactic. The stretch `quantum.bell.entangled_with_mixed_marginal` also uses that tactic for the finite marginal calculation, and its entanglement half is imported. The stretch estimate could empirically collapse to an API/automation task.
- `quantum.decoherence.purity_loss` adds a Hermiticity-to-coherence conversion before component algebra. `classical.many_body.finite_internal_force` adds antisymmetric double-sum cancellation. These are meaningful compositions but do not establish a hard frontier without measured differentiation.
- `classical.work_energy.damped_energy_antitone`, `classical.central_force.angular_momentum_constant`, and `classical.hamiltonian_flow.finite_energy_rate` combine derivative certificates and generic calculus rules. Their stretch estimates concern formal composition; the force/gradient data are explicit inputs. The local autonomous Lagrangian-energy target is correctly intermediate rather than being presented as a new variational derivation.

Publish separate outcomes for direct theorem retrieval, short lemma composition, and more explicit calculation, using a predeclared evaluator-side taxonomy. Do not replace the frozen estimates using post hoc labels chosen to favor a model. Calibration should measure actual success rates, attempts, time and cost; it may reveal that the initial suite is too easy for a particular comparison.

## Information and comparison controls

The documentation correctly distinguishes target-only files from genuine storage/network isolation and describes the public holdout as nonsecret. All quantum targets import `QuantumInfo.States.Pure.Qubit`, whose transitive closure contains many relevant finished theorems; the classical tasks use the declared Physlib or Mathlib environment. Hiding evaluator `Solution.lean` files does not remove those imported proofs or their names from the allowed mathematical environment.

Before claiming a model comparison, freeze and publish the exact benchmark and environment digests; model/version and sampling settings; prompt and retrieval policy; allowed tactics/tools/imports; solver-memory reset policy; per-target and total budget; concurrency and hardware; timeout treatment; and chosen scoring denominators. Both methods must receive the same information track. An open-library result measures legitimate proof reuse and composition. A restricted derivation result requires an independently audited information restriction; a declaration-name blacklist does not remove imported proof information. Rebuilding a restricted environment is a new qualification exercise, not a setting to change midway through this frozen run.

Report per-program, per-family, and target-micro results. The equal 20/20 program counts balance a full-suite target micro-average, but families range from one to four targets; the 17-target holdout contains nine quantum and eight classical targets. A single pooled number can therefore change with family weighting. Use paired comparisons on the same targets/seeds where appropriate, disclose the uncertainty method, and acknowledge correlations and the very small number of families. Nine semantic controls and 11 rejection controls are especially too small and related to justify broad reliability claims from a perfect score alone.

The documentation's equal-recorded-cost and equal-wall-time comparisons are useful separate views. Include verification calls, retries, retrieval, coordination and warm-cache effects consistently. An architecture that obtains more attempts, more retrieved proofs, or more concurrent verifier resources is not an equal-resource comparison merely because its model label is the same. None of these future controls has been demonstrated by author reference proofs or by synthetic validator tests.

## Final assessment and needed actions

No mathematical error or mandatory frozen-source revision was identified in this bounded fairness pass. Before any model-performance publication, specify the positive/control/semantic denominators and blind review protocol above, record the shared-pattern overlap, and predeclare information/budget/cache/reset policies. Human reviewers must still decide the scientific labels against the exact frozen revision; this AI audit cannot supply that authority.

The defensible eventual statement is of the form: “Under the disclosed open-library environment and fixed resource policy, method A produced accepted proofs for x of the 17 held-out positive targets in this public finite suite,” accompanied by the separate control and semantic-fidelity results. Whether any method achieves that result remains unmeasured here. Claims of newly solving quantum no-cloning, discovering a supplied invariant, solving 60 physics problems, validating semantic correctness by kernel acceptance alone, or proving broad scientific throughput would exceed the evidence.

## Audited immutable inputs

| Input | SHA-256 |
| --- | --- |
| `benchmarks/physics/quantum.json` | `7b76cb2bffccf598e9be03d37ab785f8bc19e76a5ed5612f5b06a4f5a5fef497` |
| `benchmarks/physics/classical.json` | `c381f3cb04f821262d5392503b9a4447873f3b6c0fb7cf68c4a25edb2ad3762e` |
| `docs/PHYSICS_BENCHMARK_REVIEW.md` | `47f90e19f5ed6808d96fe7c1b368fbd5ba148009ce20eb529afff2aa4a29bafa` |

Verification during this pass consisted of read-only source review and host Python parsing/counting/hashing. No Lean, Docker, model inference, proof acceptance or scientific review was executed.
