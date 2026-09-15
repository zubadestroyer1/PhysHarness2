import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

theorem physics_target (ψ φ : Ket d) (h : Braket.dot ψ φ = 0) :
    (MState.pure ψ).m * (MState.pure φ).m = 0 := by
  change Matrix.vecMulVec (ψ : d → ℂ) ((ψ : Bra d) : d → ℂ) *
    Matrix.vecMulVec (φ : d → ℂ) ((φ : Bra d) : d → ℂ) = 0
  rw [Matrix.vecMulVec_mul_vecMulVec]
  rw [← Braket.dot_eq_dotProduct, h, zero_smul]
  simp
