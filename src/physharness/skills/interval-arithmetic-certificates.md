---
name: interval-arithmetic-certificates
summary: Certify finitely many numerical inequalities with outward-rounded interval enclosures, subdivision and exact rational checks.
applies_when: A proof reduces to numeric facts, such as bounds on constants, the sign of a function on an interval, or a computed step that must be rigorous.
---
# Interval arithmetic certificates

## When it applies
- A proof reduces to finitely many numerical inequalities.
- You need rigorous bounds on π, e, logarithms, special-function values, or on a
  function over a box.

## Core steps
1. State the numerical claim cleanly, with rational endpoints: for example f(x) > 0 for
   x in [a, b].
2. Enclose f on the box with outward-rounded interval arithmetic (for example mpmath's
   iv context, which ships with sympy) or exact rationals. If the lower bound is > 0,
   that box is done.
3. Otherwise bisect and recurse. The certificate is the final list of boxes with their
   enclosures.
4. Near tight spots, use monotonicity on subintervals, or a Taylor bound with an
   explicit remainder.
5. Replace floating constants with rationals in the final argument, and check every
   step exactly (sympy Rational or Lean `norm_num`).

## Pitfalls
- A floating-point evaluation is not a proof: rounding, cancellation and inexact
  library functions all matter.
- Dependency problem: naive interval evaluation of x - x is not 0. Rewrite in centered
  or factored forms to reduce overestimation.
- A zero or tangency (f = 0 at a point) cannot be certified by strict enclosures;
  handle it analytically.
- Unbounded domains need an analytic tail bound before you subdivide.
- Transcendental functions need rigorous bounds (series with remainders), not
  approximations.

## In Lean/Mathlib
- Tactics: `norm_num` (exact rational arithmetic), `positivity`, `linarith`, `nlinarith`,
  `gcongr` (monotone substitution) and `interval_cases` (finitely many integer cases).
- Constants: `Real.pi_gt_three`, `Real.exp_one_lt_d9` and `Real.exp_one_gt_d9`. Sharper
  decimal bounds on π exist; find the current names with search_library.
- Elementary bounds: `Real.add_one_le_exp` (x + 1 ≤ exp x), `Real.log_le_sub_one_of_pos`,
  `Real.exp_le_exp`, `Real.exp_pos` and `Real.sqrt_le_sqrt`.
- Split intervals explicitly (for example `rcases le_or_gt x c with h | h`) and prove
  each piece with a monotonicity bound and `norm_num`.

## Numerical sanity check
- Before certifying, evaluate f on a fine grid at high precision to find near-zeros;
  put the subdivisions there.
- Rerun the certificate at a second precision; the verdict must not change.
