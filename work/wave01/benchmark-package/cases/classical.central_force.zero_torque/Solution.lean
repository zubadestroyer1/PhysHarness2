import Mathlib

open scoped BigOperators

theorem classical_target (x y u v : ℝ → ℝ) (m c t : ℝ) (hm : 0 < m)
    (hx : HasDerivAt x (u t) t) (hy : HasDerivAt y (v t) t)
    (hu : HasDerivAt u (c * x t) t) (hv : HasDerivAt v (c * y t) t) :
    HasDerivAt (fun s => m * (x s * v s - y s * u s)) 0 t := by
  have h := ((hx.mul hv).sub (hy.mul hu)).const_mul m
  convert! h using 1 <;> ring
