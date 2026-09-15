# Physics benchmark review packet

**Pending human review. No scientific or deployment approval is issued by this packet.**

Difficulty bands are author estimates, not measured model performance. The full packet contains evaluator-only reference solutions; do not mount it in discovery workspaces.

Review each intended claim against its formal quantifiers, domains, units/conventions, differentiability, boundary assumptions and definitions. Record an explicit decision against the exact source and benchmark revision.

## quantum.gates.hadamard_basis_exchange: Hadamard conjugation exchanges X and Z

H X H = Z as complex unitary matrices.

**Physical scope:** An ideal single-qubit basis change; multiplication applies the rightmost gate first.

**Assumptions:**

- None beyond the explicit typed domain.

**Difficulty estimate:** foundation. Elementary gate algebra; the reference composes an intertwining relation with involution. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Compose a gate intertwining lemma with involution; Track multiplication order.

**Known shortcuts:**

- `Qubit.H_mul_X_eq_Z_mul_H`: One rewrite plus H_sq solves the target; this is explicitly a foundation task.

[Exact target](cases/quantum.gates.hadamard_basis_exchange/Challenge.lean) · [Evaluator reference](cases/quantum.gates.hadamard_basis_exchange/Solution.lean)

**Decision: pending.**

## quantum.gates.pauli_commutator: Complex Pauli commutator

[Z,X] = 2 i Y.

**Physical scope:** The unscaled Pauli matrices; spin observables hbar/2 times these matrices would change the prefactor.

**Assumptions:**

- None beyond the explicit typed domain.

**Difficulty estimate:** intermediate. The domain identity is elementary; formal work crosses bundled gates, complex scalars, and matrix subtraction. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Expand operator products in a finite basis; Handle complex phases and commutator sign.

**Known shortcuts:**

- `matrix_expand`: The imported specialized matrix tactic can solve this exact finite identity; no hard reasoning claim is made.
- `Qubit.Z_X_anticomm`: Reduces the commutator to twice ZX but does not identify its phase by itself.

[Exact target](cases/quantum.gates.pauli_commutator/Challenge.lean) · [Evaluator reference](cases/quantum.gates.pauli_commutator/Solution.lean)

**Decision: pending.**

## quantum.gates.controlled_involution: Controlled involution cancels coherently

If g squared is identity, its controlled gate squared is identity, including superposed controls.

**Physical scope:** An ideal controlled unitary on a qubit tensor the target system.

**Assumptions:**

- g is a bundled unitary on a finite basis.
- g * g = 1.

**Difficulty estimate:** foundation. Two imported functoriality lemmas expose the controlled-gate structure. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Lift an algebraic invariant through a controlled construction.

**Known shortcuts:**

- `Qubit.controllize_mul`: Together with controllize_one gives a short exact solution.

[Exact target](cases/quantum.gates.controlled_involution/Challenge.lean) · [Evaluator reference](cases/quantum.gates.controlled_involution/Solution.lean)

**Decision: pending.**

## quantum.effects.binary_normalization: Binary effect probabilities are normalized

For 0 ≤ E ≤ I, the two Born probabilities of E and I-E are nonnegative and sum to one.

**Physical scope:** A two-outcome POVM; E need not be a projector.

**Assumptions:**

- rho is positive semidefinite and trace one through MState.
- E is Hermitian and lies between zero and identity in Loewner order.

**Difficulty estimate:** foundation. The physical result is elementary; the proof uses positivity, normalization, and linearity. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Translate operator positivity to Born probabilities; Use trace normalization and complement linearity.

**Known shortcuts:**

- `MState.exp_val_prob`: Directly proves the first effect lies in [0,1], but complement and total remain to compose.

[Exact target](cases/quantum.effects.binary_normalization/Challenge.lean) · [Evaluator reference](cases/quantum.effects.binary_normalization/Solution.lean)

**Decision: pending.**

## quantum.effects.observable_interval: Spectral operator bounds bound expectations

If a I ≤ A ≤ b I then a ≤ expectation(A) ≤ b.

**Physical scope:** Bounded finite-system observables in consistent units; a and b have the same units as A.

**Assumptions:**

- rho is an MState.
- A is Hermitian; a,b are real bounds in Loewner order.

**Difficulty estimate:** intermediate. Combines operator order with scalar identity expectations, rather than assuming the scalar conclusion. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Transfer Loewner bounds to measurement averages; Normalize scalar multiples of the identity.

**Known shortcuts:**

- `MState.exp_val_le_exp_val`: Applies separately to the two operator bounds; simp closes scalar identities.

[Exact target](cases/quantum.effects.observable_interval/Challenge.lean) · [Evaluator reference](cases/quantum.effects.observable_interval/Solution.lean)

**Decision: pending.**

## quantum.effects.zero_subeffect_support: A zero-probability effect excludes every subeffect

If 0 ≤ B ≤ A and expectation(A)=0, then the support of rho lies in the kernel of B.

**Physical scope:** Impossible positive measurement outcomes and their positive refinements.

**Assumptions:**

- rho is an MState.
- A,B are Hermitian with 0 ≤ B ≤ A.
- expectation(A)=0.

**Difficulty estimate:** intermediate. Uses an order sandwich and then the support/kernel characterization; no vanishing subeffect conclusion is assumed. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Infer a zero expectation by order sandwich; Convert zero expectation to a support/kernel relation.

**Known shortcuts:**

- `MState.exp_val_eq_zero_iff`: Directly solves the final conversion, but zero expectation for B must first be proved.

[Exact target](cases/quantum.effects.zero_subeffect_support/Challenge.lean) · [Evaluator reference](cases/quantum.effects.zero_subeffect_support/Solution.lean)

**Decision: pending.**

## quantum.geometry.orthogonal_projectors: Orthogonal pure-state projectors annihilate

If the ket overlap is zero, the product of their rank-one density projectors is zero.

**Physical scope:** Perfectly distinguishable pure states, with complex conjugation in the first slot.

**Assumptions:**

- psi and phi are normalized complex Kets.
- Their complex bra-ket overlap is zero.

**Difficulty estimate:** intermediate. Finite complex linear algebra requires identifying a bra-ket contraction inside a matrix product. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Contract rank-one operators; Match bra-ket overlap with dotProduct.

**Known shortcuts:**

- `Matrix.vecMulVec_mul_vecMulVec`: Reduces the result to the zero-overlap assumption in one algebraic step.

[Exact target](cases/quantum.geometry.orthogonal_projectors/Challenge.lean) · [Evaluator reference](cases/quantum.geometry.orthogonal_projectors/Solution.lean)

**Decision: pending.**

## quantum.geometry.global_phase_measurement: Global phase leaves all observable expectations invariant

Normalized kets differing by a unit-modulus complex phase have equal expectations for every Hermitian observable.

**Physical scope:** Global phase, not a relative phase between basis amplitudes.

**Assumptions:**

- psi and phi are normalized complex Kets.
- z has complex norm one and psi.vec = z times phi.vec.
- A is any Hermitian observable.

**Difficulty estimate:** intermediate. Joins phase equivalence of kets with the density-operator measurement representation. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Use physical equivalence under global phase; Transport equality through the Born expectation map.

**Known shortcuts:**

- `MState.pure_eq_pure_iff`: This supplies the core domain theorem; the target only composes it with measurement.

[Exact target](cases/quantum.geometry.global_phase_measurement/Challenge.lean) · [Evaluator reference](cases/quantum.geometry.global_phase_measurement/Solution.lean)

**Decision: pending.**

## quantum.composites.product_pure_iff: A product density operator is pure exactly when both factors are pure

A product density state has a ket representative iff each of its factors does.

**Physical scope:** Tensor products of independent preparations; no claim that every bipartite state factorizes.

**Assumptions:**

- rho and sigma are positive trace-one density states on finite bases.

**Difficulty estimate:** intermediate. Composes multiplicativity with the endpoint arithmetic of probabilities and the density characterization of purity. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Relate ket representability to purity; Use tensor multiplicativity and probability endpoints.

**Known shortcuts:**

- `MState.purity_prod`: Supplies multiplicativity.
- `MState.pure_iff_purity_one`: Supplies the rank-one characterization; the equivalence is a short composition.

[Exact target](cases/quantum.composites.product_pure_iff/Challenge.lean) · [Evaluator reference](cases/quantum.composites.product_pure_iff/Solution.lean)

**Decision: pending.**

## quantum.composites.entanglement_reduced_purity: Pure-state entanglement is detected by reduced-state impurity

A bipartite ket is entangled iff its right marginal has purity different from one.

**Physical scope:** The global state is pure. Reduced impurity does not characterize entanglement for arbitrary mixed global states.

**Assumptions:**

- psi is a normalized bipartite complex Ket.

**Difficulty estimate:** intermediate. The domain theorem is substantial upstream; this target tests composing separability and purity equivalences, with that shortcut disclosed. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Distinguish pure-state from mixed-state entanglement; Compose separability, product-ket, and reduced-purity equivalences.

**Known shortcuts:**

- `MState.pure_separable_iff_traceLeft_pure`: The core entanglement theorem is imported; target is API composition rather than a fresh Schmidt proof.

[Exact target](cases/quantum.composites.entanglement_reduced_purity/Challenge.lean) · [Evaluator reference](cases/quantum.composites.entanglement_reduced_purity/Solution.lean)

**Decision: pending.**

## quantum.composites.purification_with_pure_global: Every mixed state has a pure extension

There exists a bipartite ket whose left marginal equals rho and whose global density purity is one.

**Physical scope:** Ancilla dimension equals system dimension; this is existence, not minimal ancilla size or uniqueness.

**Assumptions:**

- rho is an MState on a finite complex basis.

**Difficulty estimate:** foundation. Purification is a major domain result, but the library gives a direct witness and purity characterization. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Construct an extension using spectral purification; Certify the extension is globally pure.

**Known shortcuts:**

- `MState.purifyX`: Immediately gives the witness and marginal equation.
- `MState.pure_iff_purity_one`: Immediately adds the global-purity certificate.

[Exact target](cases/quantum.composites.purification_with_pure_global/Challenge.lean) · [Evaluator reference](cases/quantum.composites.purification_with_pure_global/Solution.lean)

**Decision: pending.**

## quantum.cloning.nonorthogonal_no_common_cloner: Nonorthogonal distinct pure states have no common perfect cloner

Two normalized kets with overlap norm strictly between zero and one cannot both be perfectly cloned by one unitary with the same blank ket.

**Physical scope:** Deterministic perfect cloning of two pure-state rays; no claim about approximate, probabilistic, or state-dependent cloners.

**Assumptions:**

- psi, phi, and blank are normalized complex Kets.
- 0 < norm of overlap < 1.
- A putative cloner is unitary on system tensor blank and must clone both density states exactly.

**Difficulty estimate:** intermediate. No-cloning is a major physical obstruction, but an imported theorem supplies its hard step; the task adds existence negation and overlap conversion. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Exclude simultaneous unitary cloning; Translate Hilbert-Schmidt pure-state overlap to squared bra-ket norm; Use strict bounds to contradict zero overlap.

**Known shortcuts:**

- `MState.no_cloning`: Directly supplies the impossibility core once overlap bounds are translated; no fresh no-cloning discovery is claimed.

[Exact target](cases/quantum.cloning.nonorthogonal_no_common_cloner/Challenge.lean) · [Evaluator reference](cases/quantum.cloning.nonorthogonal_no_common_cloner/Solution.lean)

**Decision: pending.**

## quantum.channels.sequential_heisenberg: Sequential channels reverse order in the Heisenberg picture

Expectation after Phi then Psi equals the initial-state expectation of Phi-dual applied to Psi-dual of the observable.

**Physical scope:** Exact Schrodinger/Heisenberg equivalence for two channels; exp_val_ℂ retains complex traces for arbitrary A.

**Assumptions:**

- Phi and Psi are composable finite-dimensional CPTP maps.
- rho is an input density state.
- A is an output matrix; its Hermitian specialization is an observable.

**Difficulty estimate:** intermediate. Requires two duality applications with careful trace cycling and type flow between three spaces. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Track composable input and output Hilbert spaces; Cycle the trace; Apply dual maps in reverse temporal order.

**Known shortcuts:**

- `MatrixMap.Dual.trace_eq`: Two uses plus trace cyclicity solve the target; all CPTP-specific properties are stronger than this algebraic identity requires.

[Exact target](cases/quantum.channels.sequential_heisenberg/Challenge.lean) · [Evaluator reference](cases/quantum.channels.sequential_heisenberg/Solution.lean)

**Decision: pending.**

## quantum.channels.replacement_absorbs_history: A replacement channel erases the preceding channel

Replacing a state by fixed sigma after any channel equals the replacement channel itself.

**Physical scope:** Complete erasure to a fixed preparation; no preservation of classical labels or correlations is asserted.

**Assumptions:**

- Phi is a CPTP map.
- sigma is a fixed output MState.
- Input and intermediate bases are nonempty.

**Difficulty estimate:** intermediate. Uses channel extensionality to lift equality on all density inputs; elementary domain content. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Prove equality of channels by action on every density state; Compose deterministic erasure with arbitrary prior processing.

**Known shortcuts:**

- `CPTPMap.replacement_apply`: Combined with compose_eq and funext makes a short exact proof.

[Exact target](cases/quantum.channels.replacement_absorbs_history/Challenge.lean) · [Evaluator reference](cases/quantum.channels.replacement_absorbs_history/Solution.lean)

**Decision: pending.**

## quantum.channels.independent_outputs_marginal: Independent local channels preserve product preparation and its marginal

Local channels acting on a product input produce a separable output whose right marginal depends only on the right channel and input.

**Physical scope:** Independent preparations only. This restricted result does not establish no-signalling on entangled inputs.

**Assumptions:**

- Phi and Psi are CPTP maps.
- The joint input is explicitly the product rho tensor sigma.

**Difficulty estimate:** intermediate. Composes the tensor channel action, separability of product states, and partial trace. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Preserve product structure under local channel tensor products; Certify separability; Compute the marginal after local processing.

**Known shortcuts:**

- `CPTPMap.prod_apply_prod`: One rewrite exposes both direct library conclusions; this is not a hard channel theorem.

[Exact target](cases/quantum.channels.independent_outputs_marginal/Challenge.lean) · [Evaluator reference](cases/quantum.channels.independent_outputs_marginal/Solution.lean)

**Decision: pending.**

## quantum.decoherence.complete_dephasing_projection: Complete Z dephasing removes coherences and is idempotent

A fifty-fifty average of identity and Z conjugation deletes off-diagonal entries and applying it twice has no further effect.

**Physical scope:** Nonselective computational-basis dephasing on density matrices. The definition returns a matrix; this target does not separately bundle its CPTP certificate.

**Assumptions:**

- rho is an MState on a qubit.
- dephase is exactly the equal mixture of the identity and Pauli-Z unitary actions.

**Difficulty estimate:** intermediate. The proof unfolds a physically motivated average of two unitary conjugations and computes all complex matrix entries. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Translate random unitary conjugation into a matrix formula; Compute retained populations and removed coherences; Prove idempotence of a measurement channel.

**Known shortcuts:**

- `matrix_expand`: Can prove the generic diagonalization formula directly; no exact dephase declaration was found in the selected sources.

[Exact target](cases/quantum.decoherence.complete_dephasing_projection/Challenge.lean) · [Evaluator reference](cases/quantum.decoherence.complete_dephasing_projection/Solution.lean)

**Decision: pending.**

## quantum.decoherence.purity_loss: Qubit dephasing loses exactly twice the coherence magnitude squared

Tr(rho squared) minus Tr(dephase(rho) squared) equals 2 times normSq(rho_01).

**Physical scope:** The equality uses complex traces with a real right-hand side embedded into complex numbers; it implies nonincrease of the usual real purity.

**Assumptions:**

- rho is a normalized positive semidefinite Hermitian qubit density matrix.
- dephase is the equal identity/Z mixture.

**Difficulty estimate:** stretch. Requires Hermiticity to relate off-diagonal complex entries, expands trace squares, and connects complex products to a real nonnegative coherence measure. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Extract conjugate symmetry from density-matrix Hermiticity; Expand quadratic matrix traces; Isolate lost coherence as a squared complex magnitude.

**Known shortcuts:**

- `matrix_expand`: May shorten the component algebra, but a Hermiticity/coherence argument is still necessary.

[Exact target](cases/quantum.decoherence.purity_loss/Challenge.lean) · [Evaluator reference](cases/quantum.decoherence.purity_loss/Solution.lean)

**Decision: pending.**

## quantum.dynamics.commuting_energy_conservation: A commuting unitary preserves the energy expectation

If the evolution unitary commutes with the Hermitian Hamiltonian, its action preserves the energy expectation.

**Physical scope:** A finite closed-system evolution step commuting with a fixed Hamiltonian. This is not a derivation of U from the Schrodinger equation.

**Assumptions:**

- rho is an MState.
- H is Hermitian.
- U is unitary and U H = H U.

**Difficulty estimate:** intermediate. A short but order-sensitive composition of trace cyclicity, commutation, and unitarity; independent AI review suggested intermediate rather than stretch. This is an author estimate only, with domain difficulty and Lean/API effort uncalibrated on models.

**Reference outline:** Translate a commuting symmetry into conservation; Cycle a trace without commuting arbitrary factors; Cancel U-adjoint U.

**Known shortcuts:**

- `Matrix.trace_mul_comm`: Together with associativity and unitarity supplies the algebraic mechanism; no exact conservation theorem was found in the selected source.

[Exact target](cases/quantum.dynamics.commuting_energy_conservation/Challenge.lean) · [Evaluator reference](cases/quantum.dynamics.commuting_energy_conservation/Solution.lean)

**Decision: pending.**

## quantum.dynamics.unitary_purity_conservation: Unitary evolution preserves purity and pure-state representability

Unitary conjugation preserves density purity and preserves whether a state is representable by a single ket.

**Physical scope:** Finite closed-system evolution; a general CPTP channel need not preserve purity.

**Assumptions:**

- rho is an MState.
- U is unitary.

**Difficulty estimate:** intermediate. The imported overlap invariant makes purity preservation short; the second conclusion requires transporting the purity characterization. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Relate purity to self-overlap; Use unitary invariance; Transport the pure-state characterization.

**Known shortcuts:**

- `MState.inner_uConj`: The direct imported overlap invariant supplies the core conclusion.

[Exact target](cases/quantum.dynamics.unitary_purity_conservation/Challenge.lean) · [Evaluator reference](cases/quantum.dynamics.unitary_purity_conservation/Solution.lean)

**Decision: pending.**

## quantum.bell.entangled_with_mixed_marginal: The Bell state is entangled while its local density is maximally mixed

The canonical two-qubit Bell ket is entangled and its left marginal is I/2.

**Physical scope:** The Bell state (|00>+|11>)/sqrt(2); partial trace removes the right factor and yields the left qubit state.

**Assumptions:**

- Ket.MES Qubit is the normalized all-positive maximally entangled ket.

**Difficulty estimate:** stretch. Combines a general entanglement theorem with an explicit finite partial trace calculation involving square roots and complex conjugation. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

**Reference outline:** Distinguish joint entanglement from locally mixed statistics; Compute a partial trace with explicit normalization; Control basis ordering in a tensor product.

**Known shortcuts:**

- `Ket.MES_isEntangled`: Directly proves entanglement; the maximally mixed marginal still requires a matrix calculation.
- `matrix_expand`: The specialized tactic can automate much of the finite partial trace calculation.

[Exact target](cases/quantum.bell.entangled_with_mixed_marginal/Challenge.lean) · [Evaluator reference](cases/quantum.bell.entangled_with_mixed_marginal/Solution.lean)

**Decision: pending.**

## classical.oscillator_formulations.newton_equivalence: Variational oscillator equation equals Newton dynamics

For every smooth oscillator trajectory, the variational equation is equivalent to mass times acceleration equaling the restoring force.

**Physical scope:** One-dimensional Euclidean configuration space; autonomous ideal spring without damping.

**Assumptions:**

- The Physlib structure enforces m > 0 and k > 0.
- The trajectory is C∞ on all Physlib Time.

**Difficulty estimate:** foundation. Provisional author estimate; no live calibration. Physical reasoning is formulation recognition; Lean work can be one exact library invocation.

**Reference outline:** connect variational and Newtonian formulations; preserve smoothness and model assumptions

**Known shortcuts:**

- `ClassicalMechanics.HarmonicOscillator.equationOfMotion_iff_newtons_2nd_law`: Exact target shortcut; this is an API/formulation control, not evidence of deriving the variational theorem.

[Exact target](cases/classical.oscillator_formulations.newton_equivalence/Challenge.lean) · [Evaluator reference](cases/classical.oscillator_formulations.newton_equivalence/Solution.lean)

**Decision: pending.**

## classical.oscillator_formulations.legendre_energy_bridge: Oscillator Hamiltonian equals trajectory energy

Evaluating the Legendre Hamiltonian on canonical momentum agrees pointwise with kinetic plus potential energy.

**Physical scope:** One oscillator; an off-shell identity, which becomes a velocity-energy interpretation on differentiable trajectories.

**Assumptions:**

- m > 0 and k > 0 are in S.
- No trajectory differentiability is needed for this algebraic identity; both sides use the same totalized Time.deriv.

**Difficulty estimate:** foundation. Provisional author estimate; no live calibration. Physical reasoning is a Legendre-transform bridge; Lean API effort is small.

**Reference outline:** identify canonical momentum substitution; extract a pointwise identity from function equality

**Known shortcuts:**

- `ClassicalMechanics.HarmonicOscillator.hamiltonian_eq_energy`: Exact function equality; congrFun supplies the pointwise target.

[Exact target](cases/classical.oscillator_formulations.legendre_energy_bridge/Challenge.lean) · [Evaluator reference](cases/classical.oscillator_formulations.legendre_energy_bridge/Solution.lean)

**Decision: pending.**

## classical.oscillator_formulations.hamilton_equivalence: Variational oscillator equation equals Hamilton equations

The variational oscillator equation is equivalent to vanishing of the Hamilton equation operator after canonical momentum substitution.

**Physical scope:** The pinned one-dimensional oscillator, with canonical momentum p = m q̇ and its library sign convention.

**Assumptions:**

- m > 0 and k > 0 are in S.
- q is C∞ on Time.

**Difficulty estimate:** foundation. Provisional author estimate; no live calibration. The formulation involves a nontrivial Legendre correspondence; exact upstream theorem makes the reference short.

**Reference outline:** connect Lagrangian and Hamiltonian dynamics; track canonical momentum and phase-space convention

**Known shortcuts:**

- `ClassicalMechanics.HarmonicOscillator.equationOfMotion_iff_hamiltonEqOp_eq_zero`: Exact shortcut; intended physics sophistication exceeds reference Lean effort.

[Exact target](cases/classical.oscillator_formulations.hamilton_equivalence/Challenge.lean) · [Evaluator reference](cases/classical.oscillator_formulations.hamilton_equivalence/Solution.lean)

**Decision: pending.**

## classical.oscillator_formulations.newton_energy_two_times: Newton oscillator dynamics conserve energy between any times

A smooth trajectory satisfying the explicit restoring-force Newton law has equal energy at any two times.

**Physical scope:** Global smooth solutions of the unforced positive spring oscillator; existence of such a solution is not proved here.

**Assumptions:**

- m > 0 and k > 0 are in S.
- q is C∞ on all Time.
- At every t, m q̈ = −k q.

**Difficulty estimate:** intermediate. Provisional author estimate; no live calibration. Intended capability is theorem composition across formulations; Lean effort is modest.

**Reference outline:** translate explicit force law to variational dynamics; compose energy conservation at two arbitrary times

**Known shortcuts:**

- `ClassicalMechanics.HarmonicOscillator.energy_conservation_of_equationOfMotion'`: Conservation shortcut still requires the Newton-to-variational bridge.
- `ClassicalMechanics.HarmonicOscillator.equationOfMotion_iff_newtons_2nd_law`: Converts the dynamical hypothesis after force normalization.

[Exact target](cases/classical.oscillator_formulations.newton_energy_two_times/Challenge.lean) · [Evaluator reference](cases/classical.oscillator_formulations.newton_energy_two_times/Solution.lean)

**Decision: pending.**

## classical.work_energy.conservative_power: Local mechanical energy conservation for a differentiable potential

If q̇ = v, v̇ = a, U′(q) = g and m a = −g, then the derivative of m v²/2 + U(q) is zero.

**Physical scope:** One-dimensional constant-mass particle in a time-independent potential; local statement at t.

**Assumptions:**

- m > 0.
- HasDerivAt supplies q̇, v̇ and U′ at the exact evaluation points.
- Newton force balance m a = −g.

**Difficulty estimate:** intermediate. Provisional author estimate; no live calibration. Physical reasoning is the work-energy cancellation; Lean effort is composing derivative certificates.

**Reference outline:** apply product and chain rules; substitute Newton force balance

**Known shortcuts:**

- `HasDerivAt.pow`: Generic calculus rule, not the physics conclusion.
- `HasDerivAt.comp`: Generic potential chain rule; force balance must still cancel terms.

[Exact target](cases/classical.work_energy.conservative_power/Challenge.lean) · [Evaluator reference](cases/classical.work_energy.conservative_power/Solution.lean)

**Decision: pending.**

## classical.work_energy.forced_damped_power: External work minus viscous dissipation

For m v̇ = F − γv − U′(q), mechanical energy has derivative Fv − γv².

**Physical scope:** A local scalar particle model with linear viscous damping and arbitrary instantaneous applied force F.

**Assumptions:**

- m > 0 and γ ≥ 0.
- HasDerivAt gives q̇ = v, v̇ = a, and U′(q) = g at t.
- m a = F − γ v(t) − g.

**Difficulty estimate:** intermediate. Provisional author estimate; no live calibration. Requires the sign of damping and the distinction between energy rate and force; API effort resembles the conservative family case.

**Reference outline:** differentiate kinetic and potential energy; separate supplied power from nonnegative dissipation

**Known shortcuts:**

- `HasDerivAt.pow`: Calculus automation leaves the force and power convention to the author.
- `HasDerivAt.comp`: Generic chain rule only.

[Exact target](cases/classical.work_energy.forced_damped_power/Challenge.lean) · [Evaluator reference](cases/classical.work_energy.forced_damped_power/Solution.lean)

**Decision: pending.**

## classical.work_energy.damped_energy_antitone: Damped oscillator energy never increases

Every global differentiable solution of q̇ = v and m v̇ = −kq − γv has antitone mechanical energy.

**Physical scope:** Unforced scalar viscously damped harmonic oscillator on all ℝ. The theorem is conditional on a global solution.

**Assumptions:**

- m > 0, k > 0, γ ≥ 0.
- The two HasDerivAt equations hold at every real time.

**Difficulty estimate:** stretch. Provisional author estimate; no live calibration. Physical reasoning combines dissipation with a global argument; Lean work includes rational normalization and the mean-value API.

**Reference outline:** derive the dissipative energy rate from the ODE; lift a derivative sign to a global order property

**Known shortcuts:**

- `antitone_of_deriv_nonpos`: Mean-value theorem supplies global monotonicity after the energy rate is proved.

[Exact target](cases/classical.work_energy.damped_energy_antitone/Challenge.lean) · [Evaluator reference](cases/classical.work_energy.damped_energy_antitone/Solution.lean)

**Decision: pending.**

## classical.finite_power.kinetic_work: Finite-coordinate kinetic energy obeys the power law

For finitely many velocity components with mᵢ v̇ᵢ = Fᵢ, the derivative of summed kinetic energy is summed force times velocity.

**Physical scope:** Finite collection of scalar degrees of freedom, equally usable for coordinates or particles; no continuum limit.

**Assumptions:**

- n is arbitrary, including zero.
- Every mᵢ > 0 is constant.
- Every velocity component has derivative Fᵢ/mᵢ at t.

**Difficulty estimate:** intermediate. Provisional author estimate; no live calibration. Reasoning is a finite-dimensional work theorem; Lean effort is coordinating sums, derivative certificates and mass division.

**Reference outline:** differentiate a finite energy sum; use coordinatewise Newton equations with nonzero masses

**Known shortcuts:**

- `HasDerivAt.fun_sum`: Finite sum derivative rule; no direct library statement of this physics target.

[Exact target](cases/classical.finite_power.kinetic_work/Challenge.lean) · [Evaluator reference](cases/classical.finite_power.kinetic_work/Solution.lean)

**Decision: pending.**

## classical.central_force.zero_torque: Radial acceleration gives zero angular-momentum rate

If planar acceleration is a scalar multiple of position, the out-of-plane angular momentum has zero derivative.

**Physical scope:** Planar central acceleration about a fixed origin. c can have either sign; no singular force law or collision domain is asserted.

**Assumptions:**

- m > 0 is constant.
- Position derivatives are the two velocity components.
- Acceleration components are c x and c y with the same real c at t.

**Difficulty estimate:** intermediate. Provisional author estimate; no live calibration. Physical reasoning identifies torque cancellation; Lean effort is local differential algebra.

**Reference outline:** differentiate angular momentum by the product rule; cancel the torque for radial acceleration

**Known shortcuts:**

- `HasDerivAt.mul`: Generic product rule; radial torque cancellation remains to be proved.

[Exact target](cases/classical.central_force.zero_torque/Challenge.lean) · [Evaluator reference](cases/classical.central_force.zero_torque/Solution.lean)

**Decision: pending.**

## classical.central_force.angular_momentum_constant: Central-force angular momentum is a global invariant

A planar trajectory with radial acceleration at every real time has the same angular momentum at any two times.

**Physical scope:** Global planar trajectories under a central acceleration, conditional on the displayed derivative equations.

**Assumptions:**

- m > 0 is constant.
- ẋ = u and ẏ = v everywhere.
- u̇ = c(t)x and v̇ = c(t)y everywhere; c need not itself be differentiable.

**Difficulty estimate:** stretch. Provisional author estimate; no live calibration. Adds quantifier discipline and a global mean-value argument to local torque cancellation.

**Reference outline:** derive the local angular-momentum rate; use connected real time to obtain a global invariant

**Known shortcuts:**

- `is_const_of_deriv_eq_zero`: Global calculus shortcut requires both differentiability and the locally derived zero derivative.

[Exact target](cases/classical.central_force.angular_momentum_constant/Challenge.lean) · [Evaluator reference](cases/classical.central_force.angular_momentum_constant/Solution.lean)

**Decision: pending.**

## classical.many_body.two_body_momentum: Action and reaction conserve two-body momentum

Two constant positive masses experiencing opposite internal forces have constant total momentum.

**Physical scope:** One Cartesian component of an isolated two-body Newtonian system; F can depend arbitrarily on time along the solution.

**Assumptions:**

- m₁ > 0 and m₂ > 0.
- At every real time, v̇₁ = F/m₁ and v̇₂ = −F/m₂.
- There are no external-force terms.

**Difficulty estimate:** intermediate. Provisional author estimate; no live calibration. Action/reaction cancellation and a global invariant are the reasoning target; Lean effort includes nonzero mass divisions.

**Reference outline:** differentiate total momentum; cancel internal forces; obtain global constancy

**Known shortcuts:**

- `is_const_of_deriv_eq_zero`: Handles the final connected-domain calculus step, not force cancellation.

[Exact target](cases/classical.many_body.two_body_momentum/Challenge.lean) · [Evaluator reference](cases/classical.many_body.two_body_momentum/Solution.lean)

**Decision: pending.**

## classical.many_body.finite_internal_force: Antisymmetric pair forces give zero total momentum rate

For arbitrary finite n, antisymmetric pair forces and Newton component equations imply zero derivative of total momentum.

**Physical scope:** One Cartesian component of n interacting particles without external forces; instantaneous pair-force data.

**Assumptions:**

- All constant masses mᵢ are positive.
- Fᵢⱼ = −Fⱼᵢ, including the consequent zero diagonal.
- v̇ᵢ(t) = (Σⱼ Fᵢⱼ)/mᵢ at the specified time.

**Difficulty estimate:** stretch. Provisional author estimate; no live calibration. Reasoning connects Newton equations, antisymmetry, and summation; Lean work requires a double-sum transpose and derivative normalization.

**Reference outline:** differentiate total momentum as a finite sum; cancel pair forces using index interchange

**Known shortcuts:**

- `Finset.sum_comm`: Reindexing shortcut exposes antisymmetry; the force cancellation is not supplied as a hypothesis.
- `HasDerivAt.fun_sum`: Generic calculus over finite sums.

[Exact target](cases/classical.many_body.finite_internal_force/Challenge.lean) · [Evaluator reference](cases/classical.many_body.finite_internal_force/Solution.lean)

**Decision: pending.**

## classical.exact_oscillator.trajectory_derivatives: Trigonometric oscillator trajectory solves the first-order system

q(t) = A cos(ωt) + B sin(ωt), with its explicit velocity, satisfies q̇ = v and v̇ = −ω²q.

**Physical scope:** Scalar harmonic oscillator with angular frequency ω; corresponding k/m = ω². This verifies the displayed solution, not uniqueness.

**Assumptions:**

- ω > 0.
- A, B and the evaluation time are arbitrary real numbers.

**Difficulty estimate:** intermediate. Provisional author estimate; no live calibration. Physical reasoning checks a proposed solution; Lean work combines trigonometric chain rules and polynomial normalization.

**Reference outline:** differentiate an explicit trajectory twice; verify both first-order oscillator equations

**Known shortcuts:**

- `HasDerivAt.sin`: Generic trigonometric chain rule.
- `HasDerivAt.cos`: Generic trigonometric chain rule; coefficient signs and frequency powers still matter.

[Exact target](cases/classical.exact_oscillator.trajectory_derivatives/Challenge.lean) · [Evaluator reference](cases/classical.exact_oscillator.trajectory_derivatives/Solution.lean)

**Decision: pending.**

## classical.hamiltonian_flow.finite_energy_rate: General finite-dimensional autonomous Hamiltonian energy rate

For any finite-dimensional Hamiltonian with the displayed Fréchet differential, Hamilton equations imply zero derivative of H along the trajectory.

**Physical scope:** Arbitrary autonomous C1-at-the-point canonical Hamiltonian on ℝⁿ × ℝⁿ, including nonseparable Hamiltonians; local in time.

**Assumptions:**

- n is finite.
- H has no explicit time argument.
- HasFDerivAt H L identifies the full differential at (q(t), p(t)).
- L(δq,δp) = Σᵢ(gqᵢ δqᵢ + gpᵢ δpᵢ) for all variations.
- q̇ = gp and ṗ = −gq at t.

**Difficulty estimate:** stretch. Provisional author estimate; no live calibration. The reasoning is general canonical energy conservation; Lean API effort concerns products, finite spaces, and a Fréchet derivative certificate.

**Reference outline:** apply the full phase-space chain rule; use canonical Hamiltonian signs; cancel a finite contraction

**Known shortcuts:**

- `HasFDerivAt.comp_hasDerivAt`: Generic Fréchet-to-trajectory chain rule, not a Hamiltonian conservation theorem.

[Exact target](cases/classical.hamiltonian_flow.finite_energy_rate/Challenge.lean) · [Evaluator reference](cases/classical.hamiltonian_flow.finite_energy_rate/Solution.lean)

**Decision: pending.**

## classical.lagrangian_energy.autonomous_energy_rate: Euler–Lagrange dynamics give the autonomous energy rate

For a time-independent one-coordinate Lagrangian, the Euler–Lagrange momentum equation makes d(pv − L)/dt vanish.

**Physical scope:** Local autonomous finite-dimensional Lagrangian mechanics with one coordinate. No regular Legendre inverse is required for this energy-rate identity.

**Assumptions:**

- Lagr : ℝ × ℝ → ℝ is differentiable at (q(t),v(t)), with full differential D.
- D(dq,dv) = Lq*dq + p(t)*dv for all variations, identifying canonical momentum.
- q̇ = v, v̇ = a and ṗ = Lq at t.

**Difficulty estimate:** intermediate. Provisional author estimate; no live calibration. Physical reasoning distinguishes energy from Lagrangian and canonical momentum from velocity; Lean effort is composing differential certificates.

**Reference outline:** identify canonical momentum from the Lagrangian differential; combine Euler–Lagrange and chain rules; cancel the energy rate

**Known shortcuts:**

- `HasFDerivAt.comp_hasDerivAt`: Generic chain rule; Euler–Lagrange cancellation remains explicit.

[Exact target](cases/classical.lagrangian_energy.autonomous_energy_rate/Challenge.lean) · [Evaluator reference](cases/classical.lagrangian_energy.autonomous_energy_rate/Solution.lean)

**Decision: pending.**

## classical.lagrangian_energy.finite_legendre_identity: Differentiated quadratic momenta give the Legendre energy

For finitely many diagonal quadratic kinetic terms, deriving each canonical momentum and taking Σpᵢvᵢ − L yields kinetic plus potential energy.

**Physical scope:** Natural Lagrangian with diagonal constant positive mass matrix at a fixed configuration; a finite-dimensional velocity-side identity.

**Assumptions:**

- Every constant diagonal mass mᵢ is positive.
- U is a real potential value held fixed during each velocity derivative.
- The configuration has n finite velocity coordinates.

**Difficulty estimate:** intermediate. Provisional author estimate; no live calibration. Reasoning links velocity derivatives to a Legendre transform; Lean work requires differentiation and finite-sum normalization.

**Reference outline:** compute canonical momenta by differentiation; assemble a finite Legendre energy identity

**Known shortcuts:**

- `hasDerivAt_pow`: Power derivative computes momenta, leaving the Legendre sum algebra.
- `Finset.mul_sum`: Distributes the energy factor through the finite sum.

[Exact target](cases/classical.lagrangian_energy.finite_legendre_identity/Challenge.lean) · [Evaluator reference](cases/classical.lagrangian_energy.finite_legendre_identity/Solution.lean)

**Decision: pending.**

## classical.canonical_maps.drift_shear: Free drift preserves the canonical alternating form

The linear phase-space shear (q,p) ↦ (q+hp,p) preserves dq∧dp on all vector pairs.

**Physical scope:** One canonical degree of freedom; h absorbs the time step divided by mass for free drift.

**Assumptions:**

- h and all vector components are arbitrary real numbers.
- canonicalForm is the explicit bilinear alternating form q₁p₂ − p₁q₂.

**Difficulty estimate:** foundation. Provisional author estimate; no live calibration. Physical reasoning identifies a canonical shear; Lean proof reduces to exact polynomial algebra.

**Reference outline:** evaluate a phase-space map on tangent vectors; prove preservation of the canonical alternating form

**Known shortcuts:**

- `ring`: Complete polynomial shortcut after definitions unfold; this is a transparent foundation control.

[Exact target](cases/classical.canonical_maps.drift_shear/Challenge.lean) · [Evaluator reference](cases/classical.canonical_maps.drift_shear/Solution.lean)

**Decision: pending.**

## classical.canonical_maps.composition_injective: Canonical linear compositions preserve form and are injective

The composition of two linear maps preserving the canonical alternating form preserves that form and is injective.

**Physical scope:** Composition law and nondegeneracy consequence for one-degree-of-freedom linear canonical transformations.

**Assumptions:**

- S and T are real linear maps on ℝ².
- Each preserves canonicalForm for all vector pairs.

**Difficulty estimate:** intermediate. Provisional author estimate; no live calibration. Composition alone is easy; recovering injectivity from the alternating form adds the meaningful reasoning step.

**Reference outline:** compose preservation identities; exploit nondegeneracy with canonical basis vectors

**Known shortcuts:**

- `LinearMap.comp_apply`: The composition identity is definitional; injectivity still requires nondegeneracy.

[Exact target](cases/classical.canonical_maps.composition_injective/Challenge.lean) · [Evaluator reference](cases/classical.canonical_maps.composition_injective/Solution.lean)

**Decision: pending.**

## classical.discrete_oscillator.modified_energy_iterates: Symplectic Euler preserves its modified quadratic invariant

Every iterate of kick-then-drift symplectic Euler preserves q²+p²−hqp for the unit oscillator.

**Physical scope:** Nondimensional unit-mass, unit-stiffness oscillator under a discrete integrator, not the exact continuous flow.

**Assumptions:**

- h is a fixed real step throughout the iteration.
- The map is exactly p′=p−hq, q′=q+hp′.
- n is any nonnegative integer.

**Difficulty estimate:** intermediate. Provisional author estimate; no live calibration. The intended reasoning is recognizing and proving the supplied modified invariant, then iterating it; Lean effort is polynomial algebra plus induction.

**Reference outline:** derive a modified invariant from the actual update map; propagate a one-step identity to all iterates

**Known shortcuts:**

- `ring`: Proves the one-step polynomial invariant once the correct modified energy is chosen.
- `Function.iterate_succ_apply'`: Iteration recursion makes the induction short.

[Exact target](cases/classical.discrete_oscillator.modified_energy_iterates/Challenge.lean) · [Evaluator reference](cases/classical.discrete_oscillator.modified_energy_iterates/Solution.lean)

**Decision: pending.**

## classical.discrete_oscillator.midpoint_energy: Implicit midpoint preserves physical oscillator energy

Any pair of states satisfying the implicit midpoint update for a positive-mass positive-spring oscillator have exactly equal physical energy.

**Physical scope:** One step of implicit midpoint for the scalar harmonic oscillator, with canonical momentum p=mq̇.

**Assumptions:**

- m > 0 and k > 0.
- The step h is arbitrary real.
- m(q₁−q₀)=h(p₁+p₀)/2 and p₁−p₀=−hk(q₁+q₀)/2.

**Difficulty estimate:** intermediate. Provisional author estimate; no live calibration. The reasoning is a discrete work-energy identity; Lean effort is algebra with nonzero mass and the two update equations.

**Reference outline:** use midpoint update equations; factor differences of quadratic energies; cancel position and momentum work

**Known shortcuts:**

- `nlinarith`: After denominator clearing, the energy identity follows from weighted update equations.

[Exact target](cases/classical.discrete_oscillator.midpoint_energy/Challenge.lean) · [Evaluator reference](cases/classical.discrete_oscillator.midpoint_energy/Solution.lean)

**Decision: pending.**

## Altered cases

A semantic-hold case may be a valid theorem for the wrong intended question. Kernel acceptance cannot approve its scientific interpretation.

### quantum.gates.altered_commutator_sign

Reversing the commutator phase gives the negative of the actual matrix. The (0,1) entry witnesses the discrepancy. The component proof must not certify this source.

**Expected review:** confirm_negative_case_rationale

**Change:** Changes [Z,X] from +2 i Y to -2 i Y.

### quantum.gates.altered_wrong_conjugate

Hadamard swaps X and Z. Claiming it leaves X invariant is false, as the diagonal entries show.

**Expected review:** confirm_negative_case_rationale

**Change:** Changes the observable after the basis change from Z to X.

### quantum.effects.altered_duplicate_outcome

E and E are not a normalized binary POVM in general: E=0 makes their total probability zero. Positivity and E≤I alone do not imply E=I/2.

**Expected review:** confirm_negative_case_rationale

**Change:** Duplicates E instead of using the complementary effect I-E.

### quantum.decoherence.altered_missing_mixture_weight

Omitting the half-weight doubles diagonal populations, doubles trace, and destroys idempotence. A computational-basis pure state is a counterexample.

**Expected review:** confirm_negative_case_rationale

**Change:** Replaces the equal probabilistic mixture by the unnormalized sum of the two unitary branches.

### quantum.bell.altered_unnormalized_marginal

The Bell marginal has trace one and equals I/2. The identity has trace two on a qubit, so it cannot be this reduced MState.

**Expected review:** confirm_negative_case_rationale

**Change:** Drops the factor 1/2 from the purported Bell reduced density matrix.

### quantum.geometry.altered_only_equal_kets

The theorem is valid, but exact equality of kets removes the global-phase equivalence that the parent measures. It cannot substitute for the parent even when its proof is accepted.

**Expected review:** hold_for_semantic_review

**Change:** Replaces phase equivalence with equality of vector representatives.

### quantum.dynamics.altered_identity_evolution_only

Identity evolution preserves energy, but adding this assumption removes every nontrivial commuting evolution from the claim. Kernel acceptance cannot certify the intended conservation scope.

**Expected review:** hold_for_semantic_review

**Change:** Restricts the permitted evolution unitary to the identity.

### quantum.effects.altered_circular_support_premise

The support-containment conclusion has been inserted as an extra premise. This is logically valid and mathematically circular as a replacement for the intended deduction.

**Expected review:** hold_for_semantic_review

**Change:** Assumes exactly the support/kernel containment that the task is meant to derive.

### quantum.decoherence.altered_arbitrary_matrix_called_state

This algebraic statement is true for every complex matrix. It does not make every input a physical density state: for example -I lacks positivity and trace normalization. It is held when substituted under the parent physical-state interpretation; it could be a valid separately reviewed algebra task.

**Expected review:** hold_for_semantic_review

**Change:** Replaces the PSD trace-one MState domain with unrestricted matrices while retaining a physical-state interpretation.

### quantum.decoherence.altered_identity_named_dephasing

The identity map is idempotent but preserves all coherences. Renaming it dephase and retaining only idempotence can pass the kernel while failing the intended computational-basis decoherence claim.

**Expected review:** hold_for_semantic_review

**Change:** Changes the channel definition to identity and removes the diagonalization conclusion.

### classical.altered.proof_hole

The physical target is unchanged but the candidate leaves a proof hole. Target-side sorry is permitted only to declare the challenge; candidate-side sorry must not be accepted.

**Expected review:** confirm_negative_case_rationale

**Change:** No statement change; a proof hole is substituted for the reference proof.

### classical.altered.restoring_force_sign

For positive stiffness, a nonzero displacement experiences force −kx. The candidate tries to reuse that theorem to assert +kx; an exact-type mismatch is expected.

**Expected review:** confirm_negative_case_rationale

**Change:** The restoring force is changed into a repulsive force without changing the positive-spring model.

### classical.altered.totalized_cusp_derivative

Mathlib deliberately sets deriv to zero where differentiability fails. The real absolute-value trajectory has a cusp at zero, so this valid equality cannot certify a classical velocity or a stationary trajectory. The parent uses HasDerivAt specifically to avoid this interpretation.

**Expected review:** hold_for_semantic_review

**Change:** Replace the genuine derivative certificate with a bare totalized derivative equality at a nondifferentiable point.

### classical.altered.unrestricted_damping

The power identity remains mathematically true for negative γ, but calling γv² dissipated power is then wrong: the velocity force supplies energy. The kernel should not enforce a scientific sign interpretation absent from the proposition.

**Expected review:** hold_for_semantic_review

**Change:** Remove γ ≥ 0 while keeping the physical interpretation of γ as dissipative damping.

### classical.altered.damping_monotonicity_reversed

The unchanged unforced dissipative dynamics give nonincreasing energy. Reversing the order predicate does not follow; the candidate still invokes the antitone theorem.

**Expected review:** confirm_negative_case_rationale

**Change:** Change nonincreasing mechanical energy into nondecreasing energy.

### classical.altered.anisotropic_force_zero_torque

Two independent radial coefficients describe an anisotropic linear force. The angular-momentum derivative contains m(d−c)xy and is not identically zero.

**Expected review:** confirm_negative_case_rationale

**Change:** Replace the common radial coefficient c by independent x and y coefficients while asserting zero torque.

### classical.altered.reaction_sign_removed

Equal pair forces need not cancel. The proof attempts to use the altered symmetric-force hypothesis where a negative transpose is required.

**Expected review:** confirm_negative_case_rationale

**Change:** Replace Newton action–reaction antisymmetry by symmetric pair forces.

### classical.altered.hamilton_momentum_sign

With ṗ = +∂H/∂q, the chain-rule rate generally equals twice the coordinate/momentum-gradient contraction. The original proof computes zero for the negative vector and cannot apply it to this altered trajectory.

**Expected review:** confirm_negative_case_rationale

**Change:** Reverse the canonical momentum equation sign while asserting unchanged autonomous energy conservation.

### classical.altered.modified_as_physical_energy

Renaming q²+p²−hqp to physicalEnergy does not make it physical oscillator energy. The valid theorem preserves a step-dependent modified quantity; at h=1 and (q,p)=(1,1), the update (1,0) changes physical q²+p² from 2 to 1 while the modified quantity stays 1.

**Expected review:** hold_for_semantic_review

**Change:** Relabel the step-dependent modified invariant as physical energy without changing its definition.

### classical.altered.inconsistent_mass_domain

The oscillator structure requires positive mass. Adding nonpositive mass makes the domain empty, so arbitrary conclusions become provable. This is a logically valid implication requiring scientific rejection as a model of a realizable oscillator.

**Expected review:** hold_for_semantic_review

**Change:** Introduce an assumption contradicting the model’s positive-mass field, yielding a vacuous theorem.

