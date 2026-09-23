import Mathlib

open scoped BigOperators

theorem classical_target (q v U : ℝ → ℝ) (m γ F a g t : ℝ) (hm : 0 < m)
    (hq : HasDerivAt q (v t) t) (hv : HasDerivAt v a t)
    (hU : HasDerivAt U g (q t)) (hN : m * a = F - γ * v t - g) :
    HasDerivAt (fun s => m / 2 * (v s)^2 + U (q s))
      (F * v t - γ * (v t)^2) t := by
  have h := ((hv.pow 2).const_mul (m / 2)).add (hU.comp t hq)
  convert! h using 1 <;> nlinarith [congrArg (fun z : ℝ => z * v t) hN]
