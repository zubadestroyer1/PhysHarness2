import Mathlib

open scoped BigOperators

theorem classical_target (n : ℕ) (m F : Fin n → ℝ) (v : Fin n → ℝ → ℝ) (t : ℝ)
    (hm : ∀ i, 0 < m i)
    (hv : ∀ i, HasDerivAt (v i) (F i / m i) t) :
    HasDerivAt (fun s => ∑ i, m i / 2 * (v i s)^2)
      (∑ i, F i * v i t) t := by
  sorry
