import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

theorem physics_target (ρ : MState d) (E : HermitianMat d ℂ) (h0 : 0 ≤ E) (h1 : E ≤ 1) :
    0 ≤ ρ.exp_val E ∧ 0 ≤ ρ.exp_val (1 - E) ∧
    ρ.exp_val E + ρ.exp_val (1 - E) = 1 := by
  have hp := ρ.exp_val_nonneg h0
  have hu := ρ.exp_val_le_one h1
  rw [ρ.exp_val_sub, ρ.exp_val_one]
  exact ⟨hp, sub_nonneg.mpr hu, by ring⟩
