import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

theorem physics_target (ρ : MState d) (A : HermitianMat d ℂ) (a b : ℝ)
    (ha : a • (1 : HermitianMat d ℂ) ≤ A)
    (hb : A ≤ b • (1 : HermitianMat d ℂ)) :
    a ≤ ρ.exp_val A ∧ ρ.exp_val A ≤ b := by
  sorry
