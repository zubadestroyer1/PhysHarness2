import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

theorem physics_target (ρ : MState d) (H : HermitianMat d ℂ) (U : 𝐔[d])
    (hidentity : U = 1)
    (hcomm : (U : Matrix d d ℂ) * H.mat = H.mat * (U : Matrix d d ℂ)) :
    ((U : Matrix d d ℂ) * ρ.m * star (U : Matrix d d ℂ) * H.mat).trace =
      (ρ.m * H.mat).trace := by
  sorry
