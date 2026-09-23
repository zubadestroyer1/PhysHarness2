import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

noncomputable def dephase (R : Matrix Qubit Qubit ℂ) : Matrix Qubit Qubit ℂ :=
  (1 / 2 : ℂ) • (R + (Qubit.Z : Matrix Qubit Qubit ℂ) * R *
    (Qubit.Z : Matrix Qubit Qubit ℂ))

theorem physics_target (ρ : MState Qubit) :
    (ρ.m * ρ.m).trace - (dephase ρ.m * dephase ρ.m).trace =
      (2 : ℂ) * (Complex.normSq (ρ.m 0 1) : ℂ) := by
  have hc : ρ.m 1 0 = conj (ρ.m 0 1) := by
    have h := congrFun (congrFun ρ.Hermitian 0) 1
    simpa [Matrix.conjTranspose_apply] using congrArg conj h
  simp [dephase, Qubit.Z, Matrix.trace, Matrix.mul_apply, Fin.sum_univ_two,
    hc, Complex.normSq_eq_conj_mul_self, Matrix.vecMul, dotProduct]
  ring
