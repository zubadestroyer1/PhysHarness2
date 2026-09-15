import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d₁ d₂ d₃ : Type*} [Fintype d₁] [Fintype d₂] [Fintype d₃]
  [DecidableEq d₁] [DecidableEq d₂] [DecidableEq d₃]

theorem physics_target (Φ : CPTPMap d₁ d₁) (Ψ : CPTPMap d₂ d₂)
    (ρ : MState d₁) (σ : MState d₂) :
    MState.IsSeparable ((CPTPMap.prod Φ Ψ) (ρ.prod σ)) ∧
    ((CPTPMap.prod Φ Ψ) (ρ.prod σ)).traceLeft = Ψ σ := by
  rw [CPTPMap.prod_apply_prod]
  exact ⟨MState.IsSeparable_prod _ _, MState.traceLeft_prod_eq _ _⟩
