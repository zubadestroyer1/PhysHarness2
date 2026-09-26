# Selected target review

**Pending human decision. Reference proof checks do not approve the scientific interpretation.**

## The Bell state is entangled while its local density is maximally mixed

The canonical two-qubit Bell ket is entangled and its left marginal is I/2.

Problem revision: `333dc961-edaa-4c39-aed9-36672dd5b4ff`
Target digest: `2351da4df3dc2431e4b8c2d055c0f22e20b546e02503955de371ee557257a756`
Source SHA-256: `a03e56af6476d3361abef8b6df9663dd418408e9c70f5536b5ca301f72540aac`

**Assumptions and scope**

- Ket.MES Qubit is the normalized all-positive maximally entangled ket.
- The Bell state (|00>+|11>)/sqrt(2); partial trace removes the right factor and yields the left qubit state.

**Exact formal target**

```lean
import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

theorem physics_target  : (Ket.MES Qubit).IsEntangled ∧
    (MState.pure (Ket.MES Qubit)).traceRight.m =
      (1 / 2 : ℂ) • (1 : Matrix Qubit Qubit ℂ) := by
  sorry
```

**Difficulty and known shortcuts**

Combines a general entanglement theorem with an explicit finite partial trace calculation involving square roots and complex conjugation. Author estimate only; neither domain difficulty nor Lean/API effort has been calibrated on models.

- Ket.MES_isEntangled: Directly proves entanglement; the maximally mixed marginal still requires a matrix calculation.
- matrix_expand: The specialized tactic can automate much of the finite partial trace calculation.

**Review questions**

- Is this the intended all-positive two-qubit Bell state?
- Is tracing out the right subsystem and identifying the remaining matrix with I/2 the intended claim?
- Is using the existing general entanglement theorem permitted? This proposal allows normal library reuse.

No decision or rationale has been recorded. Use the separately issued reviewer identity only after the exact statement is approved.

## Damped oscillator energy never increases

Every global differentiable solution of q̇ = v and m v̇ = −kq − γv has antitone mechanical energy.

Problem revision: `1eeb1a8e-3687-4d83-8339-63e924a30669`
Target digest: `302959ccfb930fccab3d7df43e254266b3a2f1d8ef9fd86a7d4c983c7ef68f1d`
Source SHA-256: `461e43f341b8010cac3e76aa868b19a105f368d7a372794e4e79b720a6cafcd4`

**Assumptions and scope**

- m > 0, k > 0, γ ≥ 0.
- The two HasDerivAt equations hold at every real time.
- Unforced scalar viscously damped harmonic oscillator on all ℝ. The theorem is conditional on a global solution.

**Exact formal target**

```lean
import Mathlib

open scoped BigOperators

theorem classical_target (q v : ℝ → ℝ) (m k γ : ℝ) (hm : 0 < m) (hk : 0 < k) (hγ : 0 ≤ γ)
    (hq : ∀ t, HasDerivAt q (v t) t)
    (hv : ∀ t, HasDerivAt v ((-k * q t - γ * v t) / m) t) :
    Antitone (fun t => m / 2 * (v t)^2 + k / 2 * (q t)^2) := by
  sorry
```

**Difficulty and known shortcuts**

Provisional author estimate; no live calibration. Physical reasoning combines dissipation with a global argument; Lean work includes rational normalization and the mean-value API.

- antitone_of_deriv_nonpos: Mean-value theorem supplies global monotonicity after the energy rate is proved.

**Review questions**

- Are positive constant mass/stiffness, nonnegative damping and a global solution on all real times acceptable assumptions?
- Is nonincreasing energy the intended claim? This does not assert strict decay, convergence, or existence of a global solution.

No decision or rationale has been recorded. Use the separately issued reviewer identity only after the exact statement is approved.

