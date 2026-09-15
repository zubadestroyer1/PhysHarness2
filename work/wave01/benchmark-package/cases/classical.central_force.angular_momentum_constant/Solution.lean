import Mathlib

open scoped BigOperators

theorem classical_target (x y u v c : ℝ → ℝ) (m : ℝ) (hm : 0 < m)
    (hx : ∀ t, HasDerivAt x (u t) t) (hy : ∀ t, HasDerivAt y (v t) t)
    (hu : ∀ t, HasDerivAt u (c t * x t) t)
    (hv : ∀ t, HasDerivAt v (c t * y t) t) (a b : ℝ) :
    m * (x a * v a - y a * u a) = m * (x b * v b - y b * u b) := by
  have hd : ∀ t, HasDerivAt (fun s => m * (x s * v s - y s * u s)) 0 t := by
    intro t
    have h := (((hx t).mul (hv t)).sub ((hy t).mul (hu t))).const_mul m
    convert! h using 1 <;> ring
  exact is_const_of_deriv_eq_zero (fun t => (hd t).differentiableAt)
    (fun t => (hd t).deriv) a b
