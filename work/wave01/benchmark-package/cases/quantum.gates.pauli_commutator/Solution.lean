import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

theorem physics_target : (Qubit.Z : Matrix Qubit Qubit ℂ) * (Qubit.X : Matrix Qubit Qubit ℂ) -
    (Qubit.X : Matrix Qubit Qubit ℂ) * (Qubit.Z : Matrix Qubit Qubit ℂ) =
    (2 * Complex.I) • (Qubit.Y : Matrix Qubit Qubit ℂ) := by
  matrix_expand [Qubit.Z, Qubit.X, Qubit.Y]
