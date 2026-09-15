import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d₁ d₂ d₃ : Type*} [Fintype d₁] [Fintype d₂] [Fintype d₃]
  [DecidableEq d₁] [DecidableEq d₂] [DecidableEq d₃]

theorem physics_target (Φ : CPTPMap d₁ d₂) (Ψ : CPTPMap d₂ d₃)
    (ρ : MState d₁) (A : Matrix d₃ d₃ ℂ) :
    (Ψ (Φ ρ)).exp_val_ℂ A = ρ.exp_val_ℂ (Φ.map.dual (Ψ.map.dual A)) := by
  simp only [MState.exp_val_ℂ, CPTPMap.mat_coe_eq_apply_mat]
  calc
    (A * Ψ.map (Φ.map ρ.m)).trace = (Ψ.map (Φ.map ρ.m) * A).trace :=
      Matrix.trace_mul_comm _ _
    _ = (Φ.map ρ.m * Ψ.map.dual A).trace := MatrixMap.Dual.trace_eq _ _ _
    _ = (ρ.m * Φ.map.dual (Ψ.map.dual A)).trace := MatrixMap.Dual.trace_eq _ _ _
    _ = (Φ.map.dual (Ψ.map.dual A) * ρ.m).trace := Matrix.trace_mul_comm _ _
