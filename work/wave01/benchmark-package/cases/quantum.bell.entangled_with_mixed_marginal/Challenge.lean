import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

theorem physics_target  : (Ket.MES Qubit).IsEntangled ∧
    (MState.pure (Ket.MES Qubit)).traceRight.m =
      (1 / 2 : ℂ) • (1 : Matrix Qubit Qubit ℂ) := by
  sorry
