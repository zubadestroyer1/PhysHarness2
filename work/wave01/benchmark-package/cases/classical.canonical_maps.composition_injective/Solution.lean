import Mathlib

open scoped BigOperators

def canonicalForm (u v : ℝ × ℝ) : ℝ := u.1 * v.2 - u.2 * v.1

def driftShear (h : ℝ) (u : ℝ × ℝ) : ℝ × ℝ := (u.1 + h * u.2, u.2)

theorem classical_target (S T : (ℝ × ℝ) →ₗ[ℝ] (ℝ × ℝ))
    (hS : ∀ u v, canonicalForm (S u) (S v) = canonicalForm u v)
    (hT : ∀ u v, canonicalForm (T u) (T v) = canonicalForm u v) :
    (∀ u v, canonicalForm ((S.comp T) u) ((S.comp T) v) = canonicalForm u v) ∧
      Function.Injective (S.comp T) := by
  have hc : ∀ u v, canonicalForm ((S.comp T) u) ((S.comp T) v) = canonicalForm u v := by
    intro u v
    exact (hS (T u) (T v)).trans (hT u v)
  refine ⟨hc, ?_⟩
  intro u v huv
  apply Prod.ext
  · have hu := hc u (0, 1)
    have hv := hc v (0, 1)
    rw [huv] at hu
    simpa [canonicalForm] using hu.symm.trans hv
  · have hu := hc u (1, 0)
    have hv := hc v (1, 0)
    rw [huv] at hu
    have he := hu.symm.trans hv
    dsimp [canonicalForm] at he
    linarith
