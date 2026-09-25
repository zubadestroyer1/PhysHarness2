---
name: variational-methods
summary: Get existence, equations and uniqueness from minimizing a functional: direct method, first variation, convexity, trial-function bounds.
applies_when: You need ground states, equilibria, minimizers of an energy or action, optimal constants, or Euler-Lagrange equations.
---
# Variational methods

## When it applies
- You need a minimizer or ground state, or a critical point of an energy or action.
- You need an equation satisfied by an optimizer (Euler-Lagrange, with multipliers).
- You need upper or lower bounds on an optimal value or constant.

## Core steps
1. Set up the functional E on an admissible set: constraints, boundary conditions,
   normalization.
2. Direct method: show that E is bounded below, take a minimizing sequence, get
   compactness, and pass to the limit with lower semicontinuity.
3. First variation: for a minimizer u and admissible h, d/ds E(u + s h) = 0 at s = 0.
   This gives the Euler-Lagrange equation, with a Lagrange multiplier for each constraint.
4. Convexity: for convex E, a local minimum is global; strict convexity gives uniqueness.
5. Bound the optimum: trial functions give upper bounds; inequalities or a dual
   problem give lower bounds.

## Pitfalls
- Compactness can be lost: minimizing sequences escape to infinity, spread or
  concentrate (translation or scaling invariance). Fix it with coercivity, symmetry or
  concentration arguments.
- In infinite dimensions, bounded sequences converge only weakly, so lower
  semicontinuity must hold for the weak topology.
- The constraint set must be closed under the limit you take.
- A critical point need not be a minimizer. Saddle points need mountain-pass-type tools.
- Differentiating E in direction h needs integrability of the variation.

## In Lean/Mathlib
- Existence on a compact set: `IsCompact.exists_isMinOn` (continuous f) and
  `LowerSemicontinuousOn.exists_isMinOn` (lower semicontinuous f).
- Coercive functions: `Continuous.exists_forall_le` takes `Tendsto f (cocompact _) atTop`.
- First-order conditions: `IsLocalMin.hasDerivAt_eq_zero` (one real variable) and
  `IsLocalMin.fderiv_eq_zero` (Fréchet derivative).
- Convexity: `ConvexOn` and `StrictConvexOn`. `IsMinOn.of_isLocalMinOn_of_convexOn`
  upgrades a local minimum to a global one; `StrictConvexOn.eq_of_isMinOn` gives uniqueness.
- In a `ProperSpace`, `Metric.isCompact_iff_isClosed_bounded` gives compactness.
- Library support for weak compactness and Sobolev-space direct methods is limited.
  Check with search_library before planning such a formal proof, or reduce to finite
  dimensions.

## Numerical sanity check
- Discretize (finite differences or a small basis), minimize numerically, and compare
  the value and the shape of the minimizer with the claim. Refine to see convergence.
- Evaluate E on explicit trial functions for upper bounds on the claimed optimum.
