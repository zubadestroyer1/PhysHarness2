import Mathlib

open scoped BigOperators

theorem classical_target (v₁ v₂ F : ℝ → ℝ) (m₁ m₂ : ℝ) (hm₁ : 0 < m₁) (hm₂ : 0 < m₂)
    (h₁ : ∀ t, HasDerivAt v₁ (F t / m₁) t)
    (h₂ : ∀ t, HasDerivAt v₂ (-F t / m₂) t) (a b : ℝ) :
    m₁ * v₁ a + m₂ * v₂ a = m₁ * v₁ b + m₂ * v₂ b := by
  have hd : ∀ t, HasDerivAt (fun s => m₁ * v₁ s + m₂ * v₂ s) 0 t := by
    intro t
    have h := ((h₁ t).const_mul m₁).add ((h₂ t).const_mul m₂)
    convert! h using 1 <;> field_simp [ne_of_gt hm₁, ne_of_gt hm₂] <;> ring
  exact is_const_of_deriv_eq_zero (fun t => (hd t).differentiableAt)
    (fun t => (hd t).deriv) a b
