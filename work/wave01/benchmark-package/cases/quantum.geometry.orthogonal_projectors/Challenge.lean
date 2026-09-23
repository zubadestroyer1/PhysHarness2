import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

theorem physics_target (ψ φ : Ket d) (h : Braket.dot ψ φ = 0) :
    (MState.pure ψ).m * (MState.pure φ).m = 0 := by
  sorry
