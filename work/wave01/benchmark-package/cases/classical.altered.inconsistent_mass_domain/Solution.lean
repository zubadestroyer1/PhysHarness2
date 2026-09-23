import Physlib.ClassicalMechanics.HarmonicOscillator.Basic

open ClassicalMechanics Time
open scoped ContDiff

theorem classical_target (S : HarmonicOscillator) (hbad : S.m ≤ 0) : S.m = 0 := by
  exfalso
  exact (not_le_of_gt S.m_pos) hbad
