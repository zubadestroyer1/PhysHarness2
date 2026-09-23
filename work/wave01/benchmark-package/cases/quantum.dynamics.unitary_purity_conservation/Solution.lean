import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

theorem physics_target (ρ : MState d) (U : 𝐔[d]) :
    (ρ.uConj U).purity = ρ.purity ∧
    ((∃ ψ, ρ.uConj U = MState.pure ψ) ↔ (∃ φ, ρ = MState.pure φ)) := by
  have hp : (ρ.uConj U).purity = ρ.purity := by
    exact MState.inner_uConj ρ ρ U
  refine ⟨hp, ?_⟩
  rw [MState.pure_iff_purity_one, MState.pure_iff_purity_one, hp]
