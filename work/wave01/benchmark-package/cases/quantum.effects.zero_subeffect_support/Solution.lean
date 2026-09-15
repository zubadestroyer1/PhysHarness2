import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

theorem physics_target (ρ : MState d) (A B : HermitianMat d ℂ)
    (hB : 0 ≤ B) (hBA : B ≤ A) (hA : ρ.exp_val A = 0) :
    ρ.M.support ≤ B.ker := by
  apply (ρ.exp_val_eq_zero_iff hB).mp
  apply le_antisymm
  · simpa [hA] using ρ.exp_val_le_exp_val hBA
  · exact ρ.exp_val_nonneg hB
