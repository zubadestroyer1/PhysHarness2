import Physlib.ClassicalMechanics.HarmonicOscillator.Basic

open ClassicalMechanics Time
open scoped ContDiff

theorem classical_target (S : HarmonicOscillator) (x : EuclideanSpace ℝ (Fin 1)) :
    S.force x = S.k • x := by
  sorry
