import Mathlib

open scoped BigOperators

theorem classical_target : deriv (fun t : ℝ => |t|) 0 = 0 := by
  exact deriv_abs_zero
