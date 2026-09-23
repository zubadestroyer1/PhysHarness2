import Physlib.ClassicalMechanics.HarmonicOscillator.Basic

open ClassicalMechanics Time
open scoped ContDiff

theorem classical_target (S : HarmonicOscillator) (q : Time → EuclideanSpace ℝ (Fin 1))
    (hq : ContDiff ℝ ∞ q)
    (hN : ∀ t, S.m • Time.deriv (Time.deriv q) t = -S.k • q t)
    (a b : Time) : S.energy q a = S.energy q b := by
  sorry
