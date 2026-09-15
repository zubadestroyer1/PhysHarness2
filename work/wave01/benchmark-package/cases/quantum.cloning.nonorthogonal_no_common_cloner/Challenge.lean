import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

open scoped MState InnerProductSpace

theorem physics_target (ψ φ b : Ket d) (hpos : 0 < ‖Braket.dot ψ φ‖)
    (hlt : ‖Braket.dot ψ φ‖ < 1) :
    ¬ ∃ U : 𝐔[d × d],
      (MState.pure (ψ.prod b)).uConj U = MState.pure (ψ.prod ψ) ∧
      (MState.pure (φ.prod b)).uConj U = MState.pure (φ.prod φ) := by
  sorry
