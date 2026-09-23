import QuantumInfo.States.Pure.Qubit

open scoped Matrix
open ComplexConjugate
open BigOperators

variable {d₁ d₂ : Type*} [Fintype d₁] [Fintype d₂]
  [DecidableEq d₁] [DecidableEq d₂]

theorem physics_target (ψ : Ket (d₁ × d₂)) :
    ψ.IsEntangled ↔ (MState.pure ψ).traceLeft.purity ≠ 1 := by
  have hs := MState.pure_separable_iff_IsProd ψ
  have ht := MState.pure_separable_iff_traceLeft_pure ψ
  have hp := MState.pure_iff_purity_one (MState.pure ψ).traceLeft
  simp only [Ket.IsEntangled]
  constructor
  · intro hn hpur
    obtain ⟨φ, hφ⟩ := hp.mpr hpur
    exact hn (hs.mp (ht.mpr ⟨φ, hφ.symm⟩))
  · intro hn hprod
    obtain ⟨φ, hφ⟩ := ht.mp (hs.mpr hprod)
    exact hn (hp.mp ⟨φ, hφ.symm⟩)
