import Mathlib

open scoped BigOperators

theorem classical_target (Lagr : ℝ × ℝ → ℝ) (D : (ℝ × ℝ) →L[ℝ] ℝ)
    (q v p : ℝ → ℝ) (Lq a t : ℝ)
    (hL : HasFDerivAt Lagr D (q t, v t))
    (hD : ∀ dq dv, D (dq, dv) = Lq * dq + p t * dv)
    (hq : HasDerivAt q (v t) t) (hv : HasDerivAt v a t)
    (hEL : HasDerivAt p Lq t) :
    HasDerivAt (fun s => p s * v s - Lagr (q s, v s)) 0 t := by
  have hc := hL.comp_hasDerivAt t (hq.prodMk hv)
  have h := (hEL.mul hv).sub hc
  have hz : Lq * v t + p t * a - D (v t, a) = 0 := by rw [hD]; ring
  simpa only [Function.comp_def, hz] using! h
