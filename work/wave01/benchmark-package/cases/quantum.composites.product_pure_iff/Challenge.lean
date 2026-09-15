import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d₁ d₂ : Type*} [Fintype d₁] [Fintype d₂]
  [DecidableEq d₁] [DecidableEq d₂]

theorem physics_target (ρ : MState d₁) (σ : MState d₂) :
    (∃ ψ, ρ.prod σ = MState.pure ψ) ↔
    (∃ ψ, ρ = MState.pure ψ) ∧ (∃ φ, σ = MState.pure φ) := by
  sorry
