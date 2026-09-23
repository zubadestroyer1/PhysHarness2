import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d₁ d₂ d₃ : Type*} [Fintype d₁] [Fintype d₂] [Fintype d₃]
  [DecidableEq d₁] [DecidableEq d₂] [DecidableEq d₃]

theorem physics_target [Nonempty d₁] [Nonempty d₂] (Φ : CPTPMap d₁ d₂) (σ : MState d₃) :
    CPTPMap.compose (CPTPMap.replacement (dIn := d₂) σ) Φ =
      CPTPMap.replacement (dIn := d₁) σ := by
  apply CPTPMap.funext
  intro ρ
  simp [CPTPMap.compose_eq, CPTPMap.replacement_apply]
