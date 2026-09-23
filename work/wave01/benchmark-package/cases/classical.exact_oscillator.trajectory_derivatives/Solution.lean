import Mathlib

open scoped BigOperators

theorem classical_target (A B ω t : ℝ) (hω : 0 < ω) :
    HasDerivAt (fun s => A * Real.cos (ω * s) + B * Real.sin (ω * s))
      (-A * ω * Real.sin (ω * t) + B * ω * Real.cos (ω * t)) t ∧
    HasDerivAt (fun s => -A * ω * Real.sin (ω * s) + B * ω * Real.cos (ω * s))
      (-ω^2 * (A * Real.cos (ω * t) + B * Real.sin (ω * t))) t := by
  have ha : HasDerivAt (fun s : ℝ => ω * s) ω t := hasDerivAt_const_mul ω
  constructor
  · convert! (ha.cos.const_mul A).add (ha.sin.const_mul B) using 1 <;> ring
  · convert! (ha.sin.const_mul (-A * ω)).add (ha.cos.const_mul (B * ω)) using 1 <;> ring
