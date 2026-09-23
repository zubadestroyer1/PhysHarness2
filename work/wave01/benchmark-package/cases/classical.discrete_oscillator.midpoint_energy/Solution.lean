import Mathlib

open scoped BigOperators

theorem classical_target (m k h q₀ q₁ p₀ p₁ : ℝ) (hm : 0 < m) (hk : 0 < k)
    (hq : m * (q₁ - q₀) = h * (p₁ + p₀) / 2)
    (hp : p₁ - p₀ = -h * k * (q₁ + q₀) / 2) :
    p₁^2 / (2*m) + k / 2 * q₁^2 = p₀^2 / (2*m) + k / 2 * q₀^2 := by
  have h₁ := congrArg (fun z : ℝ => z * k * (q₁ + q₀)) hq
  have h₂ := congrArg (fun z : ℝ => z * (p₁ + p₀)) hp
  field_simp [ne_of_gt hm]
  nlinarith [h₁, h₂]
