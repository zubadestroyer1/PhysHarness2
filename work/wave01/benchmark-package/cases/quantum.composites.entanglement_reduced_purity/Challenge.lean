import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d₁ d₂ : Type*} [Fintype d₁] [Fintype d₂]
  [DecidableEq d₁] [DecidableEq d₂]

theorem physics_target (ψ : Ket (d₁ × d₂)) :
    ψ.IsEntangled ↔ (MState.pure ψ).traceLeft.purity ≠ 1 := by
  sorry
