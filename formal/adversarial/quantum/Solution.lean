def bitFlip {Scalar : Type} (v : Bool → Scalar) : Bool → Scalar :=
  fun b => v (!b)

theorem bitFlip_twice {Scalar : Type} (v : Bool → Scalar) : bitFlip (bitFlip v) = v := by
  funext b
  cases b <;> rfl
