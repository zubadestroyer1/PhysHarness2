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
  sorry
