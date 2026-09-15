import Mathlib

open scoped BigOperators

theorem classical_target (n : ℕ) (m : Fin n → ℝ) (F : Fin n → Fin n → ℝ)
    (v : Fin n → ℝ → ℝ) (t : ℝ) (hm : ∀ i, 0 < m i)
    (hF : ∀ i j, F i j = F j i)
    (hv : ∀ i, HasDerivAt (v i) ((∑ j, F i j) / m i) t) :
    HasDerivAt (fun s => ∑ i, m i * v i s) 0 t := by
  have hs : (∑ i, ∑ j, F i j) = -(∑ i, ∑ j, F i j) := by
    calc
      (∑ i, ∑ j, F i j) = ∑ i, ∑ j, -F j i := by
        apply Finset.sum_congr rfl
        intro i hi
        apply Finset.sum_congr rfl
        intro j hj
        exact hF i j
      _ = -(∑ i, ∑ j, F j i) := by simp only [Finset.sum_neg_distrib]
      _ = -(∑ i, ∑ j, F i j) := by rw [Finset.sum_comm]
  have hz : (∑ i, ∑ j, F i j) = 0 := by linarith
  rw [← hz]
  apply HasDerivAt.fun_sum
  intro i hi
  convert! (hv i).const_mul (m i) using 1 <;>
    field_simp [ne_of_gt (hm i)]
