---
name: fixed-point-compactness
summary: Prove existence (and uniqueness) as a fixed point u = T(u) by contraction, or as a limit of approximations extracted by compactness.
applies_when: You need existence for a nonlinear, integral, ODE or PDE equation, or a self-consistent field equation, or a limit of approximate solutions.
---
# Fixed-point and compactness arguments

## When it applies
- You need existence, and perhaps uniqueness, for a nonlinear equation you can write
  as u = T(u): an integral equation, local ODE or PDE existence, a self-consistent field.
- You can build approximate solutions (truncations, regularizations, time steps) and
  need a limit.

## Core steps
1. Recast as u = T(u) on a complete metric space: for example C([0, τ]) with the sup
   norm, or a closed ball in a Banach space.
2. Contraction route: show that T maps a closed set S into itself and that
   d(Tu, Tv) ≤ K d(u, v) with K < 1 (shrink τ or the ball if needed). You get a unique
   fixed point, geometric convergence of the iterates, and d(x, x*) ≤ d(x, Tx)/(1 - K).
3. Compactness route: build approximations u_n and prove uniform bounds (energy
   estimates) and equicontinuity. Extract a convergent subsequence (Bolzano-Weierstrass,
   Arzelà-Ascoli) and pass to the limit in the equation.
4. Topological fixed-point theorems (Brouwer, Schauder) need a convex compact set and a
   continuous T.
5. Uniqueness usually needs a separate argument: Grönwall, monotonicity, or a
   contraction in a weaker norm.

## Pitfalls
- The self-map T(S) ⊆ S is often the hard part. Check it first with explicit constants.
- Completeness depends on the metric: C([0, τ]) with the L² norm is not complete.
- Nonlinear terms need strong convergence. Weak limits of products are not products of
  weak limits.
- Limits of subsequences need not be unique. Do not claim convergence of the whole
  sequence without uniqueness.
- A contraction on a short interval gives only local existence. Global existence
  needs an a-priori bound.

## In Lean/Mathlib
- `ContractingWith K f` means K < 1 and f is K-Lipschitz. With `[CompleteSpace α]` and
  `[Nonempty α]`, use `ContractingWith.fixedPoint`, `ContractingWith.fixedPoint_isFixedPt`,
  `ContractingWith.fixedPoint_unique`, `ContractingWith.dist_fixedPoint_le`,
  `ContractingWith.apriori_dist_iterate_fixedPoint_le` and
  `ContractingWith.tendsto_iterate_fixedPoint`. For a closed ball, work on the subtype.
- ODE existence: `IsPicardLindelof` packages the Picard-Lindelöf hypotheses. Find the
  matching existence theorem with search_library.
- Compactness: `IsCompact.tendsto_subseq`, `tendsto_subseq_of_bounded`
  (Bolzano-Weierstrass in a `ProperSpace`), `Metric.isCompact_iff_isClosed_bounded` and
  `BoundedContinuousFunction.arzela_ascoli`.
- Check with search_library whether a Brouwer or Schauder theorem is available before
  relying on one. Otherwise prefer the contraction route or a finite-dimensional argument.

## Numerical sanity check
- Iterate T from several starting points. Estimate the contraction factor from
  d(T²x, Tx)/d(Tx, x). A ratio near or above 1 means the claim fails on that set.
- For compactness arguments, compute approximations at increasing resolution and check
  the claimed uniform bounds numerically.
