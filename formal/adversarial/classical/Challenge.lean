-- UNREVIEWED: discrete translation composition, a classical kinematic prerequisite.
def translate (displacement position : Nat) : Nat := position + displacement

theorem translate_compose (x a b : Nat) :
    translate b (translate a x) = translate (a + b) x := by
  sorry
