import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

noncomputable def dephase (R : Matrix Qubit Qubit ℂ) : Matrix Qubit Qubit ℂ := R

theorem physics_target (ρ : MState Qubit) :
    dephase (dephase ρ.m) = dephase ρ.m := by
  rfl
