import Physlib.ClassicalMechanics.HarmonicOscillator.Basic

theorem library_target (S : ClassicalMechanics.HarmonicOscillator) :
    S.ω ^ 2 = S.k / S.m := by
  exact S.ω_sq
