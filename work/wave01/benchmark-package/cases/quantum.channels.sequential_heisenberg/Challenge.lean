import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d₁ d₂ d₃ : Type*} [Fintype d₁] [Fintype d₂] [Fintype d₃]
  [DecidableEq d₁] [DecidableEq d₂] [DecidableEq d₃]

theorem physics_target (Φ : CPTPMap d₁ d₂) (Ψ : CPTPMap d₂ d₃)
    (ρ : MState d₁) (A : Matrix d₃ d₃ ℂ) :
    (Ψ (Φ ρ)).exp_val_ℂ A = ρ.exp_val_ℂ (Φ.map.dual (Ψ.map.dual A)) := by
  sorry
