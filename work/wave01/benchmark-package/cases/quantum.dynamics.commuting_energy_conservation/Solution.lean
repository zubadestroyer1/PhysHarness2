import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

theorem physics_target (ρ : MState d) (H : HermitianMat d ℂ) (U : 𝐔[d])
    (hcomm : (U : Matrix d d ℂ) * H.mat = H.mat * (U : Matrix d d ℂ)) :
    ((U : Matrix d d ℂ) * ρ.m * star (U : Matrix d d ℂ) * H.mat).trace =
      (ρ.m * H.mat).trace := by
  have hU : star (U : Matrix d d ℂ) * (U : Matrix d d ℂ) = 1 := U.2.1
  calc
    ((U : Matrix d d ℂ) * ρ.m * star (U : Matrix d d ℂ) * H.mat).trace =
        (ρ.m * (star (U : Matrix d d ℂ) * H.mat * (U : Matrix d d ℂ))).trace := by
      rw [Matrix.mul_assoc, Matrix.mul_assoc, Matrix.trace_mul_comm]
      simp only [Matrix.mul_assoc]
    _ = (ρ.m * H.mat).trace := by
      rw [Matrix.mul_assoc (star (U : Matrix d d ℂ)), ← hcomm,
        ← Matrix.mul_assoc (star (U : Matrix d d ℂ)), hU, Matrix.one_mul]
