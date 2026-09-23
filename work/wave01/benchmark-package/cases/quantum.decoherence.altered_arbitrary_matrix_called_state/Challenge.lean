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
  sorry
