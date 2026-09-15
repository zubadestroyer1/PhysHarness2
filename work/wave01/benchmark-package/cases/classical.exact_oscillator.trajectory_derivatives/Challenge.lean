import Mathlib

open scoped BigOperators

theorem classical_target (A B ω t : ℝ) (hω : 0 < ω) :
    HasDerivAt (fun s => A * Real.cos (ω * s) + B * Real.sin (ω * s))
      (-A * ω * Real.sin (ω * t) + B * ω * Real.cos (ω * t)) t ∧
    HasDerivAt (fun s => -A * ω * Real.sin (ω * s) + B * ω * Real.cos (ω * s))
      (-ω^2 * (A * Real.cos (ω * t) + B * Real.sin (ω * t))) t := by
  sorry
