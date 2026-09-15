import Physlib.ClassicalMechanics.HarmonicOscillator.Basic

open ClassicalMechanics Time
open scoped ContDiff

theorem classical_target (S : HarmonicOscillator) (q : Time → EuclideanSpace ℝ (Fin 1))
    (hq : ContDiff ℝ ∞ q)
    (hN : ∀ t, S.m • Time.deriv (Time.deriv q) t = -S.k • q t)
    (a b : Time) : S.energy q a = S.energy q b := by
  have heom : S.EquationOfMotion q :=
    (S.equationOfMotion_iff_newtons_2nd_law q hq).2 (by
      intro t
      simpa only [HarmonicOscillator.force_eq_linear] using hN t)
  exact (S.energy_conservation_of_equationOfMotion' q hq heom a).trans
    (S.energy_conservation_of_equationOfMotion' q hq heom b).symm
