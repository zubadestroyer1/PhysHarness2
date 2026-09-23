import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

theorem physics_target : Qubit.H * Qubit.X * Qubit.H = Qubit.Z := by
  sorry
