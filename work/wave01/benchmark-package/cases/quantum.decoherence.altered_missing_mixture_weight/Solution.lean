import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

noncomputable def dephase (R : Matrix Qubit Qubit ℂ) : Matrix Qubit Qubit ℂ :=
  (1 : ℂ) • (R + (Qubit.Z : Matrix Qubit Qubit ℂ) * R *
    (Qubit.Z : Matrix Qubit Qubit ℂ))

theorem physics_target (ρ : MState Qubit) :
    dephase ρ.m = Matrix.diagonal (fun i => ρ.m i i) ∧
    dephase (dephase ρ.m) = dephase ρ.m := by
  have hdiag (R : Matrix Qubit Qubit ℂ) :
      dephase R = Matrix.diagonal (fun i => R i i) := by
    matrix_expand [dephase, Qubit.Z, Matrix.diagonal, Matrix.vecMul, dotProduct]
  constructor
  · exact hdiag ρ.m
  · rw [hdiag, hdiag]
    ext i j
    simp
