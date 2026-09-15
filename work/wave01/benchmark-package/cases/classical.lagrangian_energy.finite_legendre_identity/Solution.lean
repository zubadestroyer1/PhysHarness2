import Mathlib

open scoped BigOperators

theorem classical_target (n : ℕ) (m v : Fin n → ℝ) (U : ℝ) (hm : ∀ i, 0 < m i) :
    (∑ i, deriv (fun w : ℝ => m i / 2 * w^2 - U) (v i) * v i) -
      ((∑ i, m i / 2 * (v i)^2) - U) =
      (∑ i, m i / 2 * (v i)^2) + U := by
  have hp : ∀ i, deriv (fun w : ℝ => m i / 2 * w^2 - U) (v i) = m i * v i := by
    intro i
    have h := ((hasDerivAt_pow 2 (v i)).const_mul (m i / 2)).sub_const U
    convert! h.deriv using 1 <;> ring
  simp only [hp]
  have hs : (∑ i, m i * v i * v i) = 2 * ∑ i, m i / 2 * (v i)^2 := by
    rw [Finset.mul_sum]
    apply Finset.sum_congr rfl
    intro i hi
    ring
  rw [hs]
  ring
