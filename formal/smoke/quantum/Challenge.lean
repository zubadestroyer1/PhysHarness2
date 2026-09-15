-- UNREVIEWED: algebraic smoke test only; no physics validation is claimed.
-- A two-basis amplitude vector over an arbitrary scalar type.
def bitFlip {Scalar : Type} (v : Bool → Scalar) : Bool → Scalar :=
  fun b => v (!b)

theorem bitFlip_twice {Scalar : Type} (v : Bool → Scalar) : bitFlip (bitFlip v) = v := by
  sorry
