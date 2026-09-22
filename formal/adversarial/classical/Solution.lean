def translate (displacement position : Nat) : Nat := position + displacement

theorem translate_compose (x a b : Nat) :
    translate b (translate a x) = translate (a + b) x := by
  exact Nat.add_assoc x a b
