import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

theorem physics_target (ρ : MState d) (A B : HermitianMat d ℂ)
    (hB : 0 ≤ B) (hBA : B ≤ A) (hA : ρ.exp_val A = 0) :
    ρ.M.support ≤ B.ker := by
  sorry
