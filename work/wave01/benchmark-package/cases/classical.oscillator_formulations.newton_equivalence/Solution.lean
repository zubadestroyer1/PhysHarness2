import Physlib.ClassicalMechanics.HarmonicOscillator.Basic

open ClassicalMechanics Time
open scoped ContDiff

theorem classical_target (S : HarmonicOscillator) (q : Time → EuclideanSpace ℝ (Fin 1))
    (hq : ContDiff ℝ ∞ q) :
    S.EquationOfMotion q ↔ ∀ t, S.m • Time.deriv (Time.deriv q) t = S.force (q t) := by
  exact S.equationOfMotion_iff_newtons_2nd_law q hq
