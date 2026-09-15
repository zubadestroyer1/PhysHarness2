import Mathlib

open scoped BigOperators

theorem classical_target (n : ℕ) (H : ((Fin n → ℝ) × (Fin n → ℝ)) → ℝ)
    (L : ((Fin n → ℝ) × (Fin n → ℝ)) →L[ℝ] ℝ)
    (q p : ℝ → Fin n → ℝ) (gq gp : Fin n → ℝ) (t : ℝ)
    (hH : HasFDerivAt H L (q t, p t))
    (hL : ∀ dq dp, L (dq, dp) = ∑ i, (gq i * dq i + gp i * dp i))
    (hq : HasDerivAt q gp t) (hp : HasDerivAt p (fun i => -gq i) t) :
    HasDerivAt (fun s => H (q s, p s)) 0 t := by
  have h := hH.comp_hasDerivAt t (hq.prodMk hp)
  have hz : L (gp, fun i => -gq i) = 0 := by
    rw [hL]
    apply Finset.sum_eq_zero
    intro i hi
    ring
  simpa only [Function.comp_def, hz] using! h
