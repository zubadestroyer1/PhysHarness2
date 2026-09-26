---
name: operator-inequalities-quantum
summary: Prove matrix and operator inequalities for quantum information with positivity, congruence, spectral decomposition and convexity.
applies_when: A claim involves density matrices, Loewner order, trace inequalities, entropy, fidelity, channels or uncertainty relations in finite dimensions.
---
# Operator inequalities and convexity in quantum information

## When it applies
- You need positivity (A ≥ 0) or Loewner order (A ≤ B) of matrices or operators.
- You need bounds on expectations tr(ρA), trace distance, fidelity or entropies.
- You need convexity or concavity of a function of density matrices.

## Core steps
1. Fix conventions: finite dimension; a density matrix ρ is positive semidefinite with
   tr ρ = 1; A ≤ B means B - A ≥ 0.
2. Reduce to building blocks: positivity is preserved by congruence (Bᴴ A B ≥ 0), sums
   and tensor products; Aᴴ A ≥ 0; the trace of a PSD matrix is nonnegative;
   tr(AB) ≥ 0 when A, B ≥ 0.
3. Diagonalize one operator. In its eigenbasis, some scalar inequalities lift to
   operator ones, but only when the other operators are handled correctly.
4. Use convexity: Jensen over eigenvalues or probability weights, and joint convexity
   where it is known.
5. For operator-monotone or operator-convex functions (log, x^p with 0 < p ≤ 1), cite
   the exact theorem. Scalar monotonicity does not imply operator monotonicity.

## Pitfalls
- Non-commutativity: A ≤ B does not imply A² ≤ B²; e^{A+B} ≠ e^A e^B in general; the
  trace is only cyclic, so tr(ABC) ≠ tr(BAC) in general.
- Positive semidefinite includes Hermitian; do not drop that part of the definition.
- Fix the index conventions for partial traces and tensor orderings before computing.
- Entropies with zero eigenvalues need the 0 log 0 = 0 convention and care with supports.

## In Lean/Mathlib
- Positivity: `Matrix.PosSemidef`, `Matrix.PosDef`, `Matrix.PosSemidef.add`,
  `Matrix.PosSemidef.conjTranspose_mul_mul_same` (Bᴴ A B),
  `Matrix.posSemidef_conjTranspose_mul_self` (Aᴴ A), `Matrix.PosSemidef.trace_nonneg`
  and `Matrix.PosSemidef.eigenvalues_nonneg`.
- Hermitian structure: `Matrix.IsHermitian`, `Matrix.IsHermitian.eigenvalues`,
  `IsSelfAdjoint`. On Hilbert spaces: `ContinuousLinearMap.IsPositive`.
- Traces and tensors: `Matrix.trace`, `Matrix.trace_mul_comm`, `Matrix.kronecker` and
  `Matrix.kroneckerMap`.
- Convexity: `ConvexOn` and `ConvexOn.map_sum_le` (Jensen for finite sums).
- Cauchy-Schwarz: `norm_inner_le_norm` and `abs_real_inner_le_norm`.
- Check with search_library (Mathlib and Physlib) before assuming that von Neumann
  entropy or an operator-monotonicity result exists.

## Numerical sanity check
- In dimension 2 to 4, sample random density matrices (G Gᴴ / tr(G Gᴴ) with complex
  Gaussian G), including low-rank and nearly pure states. Test the inequality with
  eigenvalue-based computations; violations usually appear at rank-deficient states.
