import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

theorem physics_target (g : 𝐔[d]) (hg : g * g = 1) :
    Qubit.controllize g * Qubit.controllize g = 1 := by
  sorry
