import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

theorem physics_target (ρ : MState d) :
    ∃ ψ : Ket (d × d), (MState.pure ψ).traceRight = ρ ∧
      (MState.pure ψ).purity = 1 := by
  refine ⟨ρ.purify, ρ.purify_spec, ?_⟩
  exact (MState.pure_iff_purity_one _).mp ⟨ρ.purify, rfl⟩
