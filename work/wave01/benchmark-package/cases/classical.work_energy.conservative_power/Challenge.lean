import Mathlib

open scoped BigOperators

theorem classical_target (q v U : ℝ → ℝ) (m a g t : ℝ) (hm : 0 < m)
    (hq : HasDerivAt q (v t) t) (hv : HasDerivAt v a t)
    (hU : HasDerivAt U g (q t)) (hN : m * a = -g) :
    HasDerivAt (fun s => m / 2 * (v s)^2 + U (q s)) 0 t := by
  sorry
