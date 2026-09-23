import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

noncomputable def dephase (R : Matrix Qubit Qubit ℂ) : Matrix Qubit Qubit ℂ :=
  (1 / 2 : ℂ) • (R + (Qubit.Z : Matrix Qubit Qubit ℂ) * R *
    (Qubit.Z : Matrix Qubit Qubit ℂ))

theorem physics_target (R : Matrix Qubit Qubit ℂ) :
    dephase R = Matrix.diagonal (fun i => R i i) ∧
    dephase (dephase R) = dephase R := by
  have hdiag (A : Matrix Qubit Qubit ℂ) :
      dephase A = Matrix.diagonal (fun i => A i i) := by
    matrix_expand [dephase, Qubit.Z, Matrix.diagonal, Matrix.vecMul, dotProduct]
  constructor
  · exact hdiag R
  · rw [hdiag, hdiag]
    ext i j
    simp
