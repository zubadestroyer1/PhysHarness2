import Mathlib

open scoped BigOperators

theorem classical_target (q v : ℝ → ℝ) (m k γ : ℝ) (hm : 0 < m) (hk : 0 < k) (hγ : 0 ≤ γ)
    (hq : ∀ t, HasDerivAt q (v t) t)
    (hv : ∀ t, HasDerivAt v ((-k * q t - γ * v t) / m) t) :
    Antitone (fun t => m / 2 * (v t)^2 + k / 2 * (q t)^2) := by
  have hd : ∀ t, HasDerivAt (fun s => m / 2 * (v s)^2 + k / 2 * (q s)^2)
      (-γ * (v t)^2) t := by
    intro t
    have h := (((hv t).pow 2).const_mul (m / 2)).add
      (((hq t).pow 2).const_mul (k / 2))
    convert! h using 1 <;> field_simp [ne_of_gt hm] <;> ring
  apply antitone_of_deriv_nonpos (fun t => (hd t).differentiableAt)
  intro t
  rw [(hd t).deriv]
  exact mul_nonpos_of_nonpos_of_nonneg (neg_nonpos.mpr hγ) (sq_nonneg _)
