import Physlib.ClassicalMechanics.HarmonicOscillator.Basic

open ClassicalMechanics Time
open scoped ContDiff

theorem classical_target (S : HarmonicOscillator) (q : Time → EuclideanSpace ℝ (Fin 1))
    (hq : ContDiff ℝ ∞ q) :
    S.EquationOfMotion q ↔
      S.hamiltonEqOp (fun t => S.toCanonicalMomentum t (q t) (Time.deriv q t)) q = 0 := by
  exact S.equationOfMotion_iff_hamiltonEqOp_eq_zero q hq
