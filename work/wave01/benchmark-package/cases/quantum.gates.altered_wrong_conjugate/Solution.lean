import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

theorem physics_target : Qubit.H * Qubit.X * Qubit.H = Qubit.X := by
  rw [Qubit.H_mul_X_eq_Z_mul_H, mul_assoc, Qubit.H_sq, mul_one]
  matrix_expand [Qubit.X, Qubit.Z]
