---
name: gronwall-comparison
summary: Turn a differential or integral inequality u' ≤ K u + ε into an explicit exponential bound, or compare u with the solution of a model ODE.
applies_when: You need stability, continuous dependence, uniqueness or error bounds for an evolution equation, or to close an energy estimate E' ≤ C E + F.
---
# Grönwall and comparison arguments

## When it applies
- A scalar quantity u(t) satisfies u' ≤ K u + ε, or u(t) ≤ δ + ∫ K u.
- You need continuous dependence on data, uniqueness, or an approximation error bound.
- An energy estimate gives E' ≤ C E + F and you need E(t) explicitly.

## Core steps
1. Pick the scalar quantity (norm of a difference, an energy). Derive the inequality
   with named constants K, ε, δ.
2. Choose the form: differential; right-derivative (Dini) for non-smooth u such as a
   norm; or integral.
3. Apply Grönwall: u(t) ≤ δ e^{K(t-a)} + (ε/K)(e^{K(t-a)} - 1), or δ + ε(t-a) when K = 0.
4. For nonlinear u' ≤ F(u), compare with the solution of v' = F(v), v(a) ≥ u(a).
5. Bootstrap: assume a bound on [a, T*), improve it with Grönwall, then conclude that
   T* is the whole interval by continuity.

## Pitfalls
- ‖x(t)‖ may not be differentiable where x = 0. Use right derivatives, or work with
  ‖x‖², which doubles the constant.
- The integral form needs K ≥ 0 and u continuous (or locally bounded and measurable).
- The bound grows exponentially, so it is only useful on finite intervals unless K ≤ 0.
- With only a local Lipschitz constant, first show that the solution stays in the set
  where that constant is valid.

## In Lean/Mathlib (Mathlib/Analysis/ODE/Gronwall.lean)
- `gronwallBound δ K ε x` is the explicit bound. `gronwallBound_K0` and
  `gronwallBound_of_K_ne_0` unfold it.
- `norm_le_gronwallBound_of_norm_deriv_right_le` takes continuity on `Icc a b`, right
  derivatives on `Ico a b`, `‖f a‖ ≤ δ` and `‖f' x‖ ≤ K * ‖f x‖ + ε`. It gives
  `‖f x‖ ≤ gronwallBound δ K ε (x - a)`.
- `le_gronwallBound_of_liminf_deriv_right_le` is the scalar version with a Dini hypothesis.
- `dist_le_of_approx_trajectories_ODE`: two approximate solutions of x' = v t x, with
  each `v t` K-Lipschitz, stay within `gronwallBound δ K (εf + εg) (t - a)`.
- `ODE_solution_unique` gives uniqueness under a Lipschitz right-hand side.
- `image_le_of_deriv_right_le_deriv_boundary` compares u with any boundary function B.
- Right derivatives are `HasDerivWithinAt f (f' x) (Ici x) x`. Get them from a
  two-sided derivative with `HasDerivAt.hasDerivWithinAt`.

## Numerical sanity check
- Simulate u(t) and plot it against the claimed bound. The bound should dominate with
  room to spare. If they touch, recheck the constants.
- Check that your final formula reduces correctly at K = 0 and at t = a.
