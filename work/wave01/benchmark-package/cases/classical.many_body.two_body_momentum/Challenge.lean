import Mathlib

open scoped BigOperators

theorem classical_target (v₁ v₂ F : ℝ → ℝ) (m₁ m₂ : ℝ) (hm₁ : 0 < m₁) (hm₂ : 0 < m₂)
    (h₁ : ∀ t, HasDerivAt v₁ (F t / m₁) t)
    (h₂ : ∀ t, HasDerivAt v₂ (-F t / m₂) t) (a b : ℝ) :
    m₁ * v₁ a + m₂ * v₂ a = m₁ * v₁ b + m₂ * v₂ b := by
  sorry
