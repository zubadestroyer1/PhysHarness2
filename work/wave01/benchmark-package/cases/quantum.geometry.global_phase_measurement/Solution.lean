import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d : Type*} [Fintype d] [DecidableEq d]

theorem physics_target (ψ φ : Ket d) (z : ℂ) (hz : ‖z‖ = 1)
    (hψ : ψ.vec = z • φ.vec) (A : HermitianMat d ℂ) :
    (MState.pure ψ).exp_val A = (MState.pure φ).exp_val A := by
  have heq : MState.pure ψ = MState.pure φ :=
    (MState.pure_eq_pure_iff ψ φ).mpr ⟨z, hz, hψ⟩
  rw [heq]
