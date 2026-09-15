import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

theorem physics_target (ρ : MState d) :
    ∃ ψ : Ket (d × d), (MState.pure ψ).traceRight = ρ ∧
      (MState.pure ψ).purity = 1 := by
  sorry
