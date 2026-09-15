import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d₁ d₂ : Type*} [Fintype d₁] [Fintype d₂]
  [DecidableEq d₁] [DecidableEq d₂]

theorem physics_target (ρ : MState d₁) (σ : MState d₂) :
    (∃ ψ, ρ.prod σ = MState.pure ψ) ↔
    (∃ ψ, ρ = MState.pure ψ) ∧ (∃ φ, σ = MState.pure φ) := by
  rw [MState.pure_iff_purity_one, MState.purity_prod, Prob.mul_eq_one_iff]
  rw [MState.pure_iff_purity_one, MState.pure_iff_purity_one]
