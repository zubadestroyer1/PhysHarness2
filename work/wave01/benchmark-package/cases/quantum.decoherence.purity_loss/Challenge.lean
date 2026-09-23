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
  sorry
