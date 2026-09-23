import Mathlib

open scoped BigOperators

theorem classical_target (n : ℕ) (m v : Fin n → ℝ) (U : ℝ) (hm : ∀ i, 0 < m i) :
    (∑ i, deriv (fun w : ℝ => m i / 2 * w^2 - U) (v i) * v i) -
      ((∑ i, m i / 2 * (v i)^2) - U) =
      (∑ i, m i / 2 * (v i)^2) + U := by
  sorry
