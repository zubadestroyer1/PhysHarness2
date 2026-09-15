import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

theorem physics_target (ρ : MState d) (U : 𝐔[d]) :
    (ρ.uConj U).purity = ρ.purity ∧
    ((∃ ψ, ρ.uConj U = MState.pure ψ) ↔ (∃ φ, ρ = MState.pure φ)) := by
  sorry
