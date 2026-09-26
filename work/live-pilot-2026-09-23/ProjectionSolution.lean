import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

noncomputable def dephase (R : Matrix Qubit Qubit ℂ) : Matrix Qubit Qubit ℂ :=
  (1 / 2 : ℂ) • (R + (Qubit.Z : Matrix Qubit Qubit ℂ) * R *
    (Qubit.Z : Matrix Qubit Qubit ℂ))

theorem physics_target (ρ : MState Qubit) :
    dephase ρ.m = Matrix.diagonal (fun i => ρ.m i i) ∧
    dephase (dephase ρ.m) = dephase ρ.m := by
  have h (R : Matrix Qubit Qubit ℂ) :
      dephase R = Matrix.diagonal (fun i => R i i) := by
    ext i j
    fin_cases i <;> fin_cases j <;>
      norm_num [dephase, Qubit.Z, Matrix.mul_apply, Matrix.vecMul,
        Matrix.vecHead, Matrix.vecTail, Fin.sum_univ_succ] <;> ring
  constructor
  · exact h ρ.m
  · rw [h (dephase ρ.m), h ρ.m]
    simp
