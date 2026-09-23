import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

theorem physics_target  : (Ket.MES Qubit).IsEntangled ∧
    (MState.pure (Ket.MES Qubit)).traceRight.m =
      (1 : ℂ) • (1 : Matrix Qubit Qubit ℂ) := by
  constructor
  · exact Ket.MES_isEntangled
  · matrix_expand [MState.traceRight, MState.m, HermitianMat.traceRight,
      Matrix.traceRight, MState.pure, Ket.MES, Ket.apply,
      Matrix.vecMulVec_apply, Bra.eq_conj]
