---
name: sos-certificates
summary: Prove polynomial inequalities with exact sum-of-squares certificates found numerically, then rationalized and checked exactly.
applies_when: A claim is a polynomial inequality on R^n or on a semialgebraic set, or nonnegativity of a quadratic form or finite-dimensional Hamiltonian.
---
# Sum-of-squares certificates

## When it applies
- You need p(x) ≥ 0 on ℝⁿ, or on a set given by constraints g_i(x) ≥ 0.
- You need nonnegativity of a quadratic form or a finite-dimensional Hamiltonian.
- You want to rule out a region with a Positivstellensatz-style certificate.

## Core steps
1. Normalize the degree. With constraints, look for p = σ₀ + Σ σ_i g_i where each σ is
   a sum of squares (SOS).
2. Pick a monomial vector z(x) of half the degree, and look for a positive semidefinite
   Gram matrix Q with p = z(x)ᵀ Q z(x).
3. Find Q numerically. Use an SDP solver if one is installed. Otherwise solve the
   linear constraints on Q exactly with sympy and choose the free parameters with
   scipy.optimize to maximize the smallest eigenvalue of Q.
4. Round Q to rationals, restore the exact identity by solving the linear constraints
   exactly, and check Q ⪰ 0 exactly (a rational LDLᵀ with nonnegative pivots).
5. Expand Q = Σ λ_k l_k(x)² with λ_k ≥ 0. These explicit squares are the certificate.

## Pitfalls
- A numerical Gram matrix is not a proof: floating error breaks the exact identity.
  Always rationalize and check exactly.
- Not every nonnegative polynomial is SOS (Motzkin). Try multiplying by
  (1 + Σ x_i²)^k, or add constraint multipliers.
- If the optimal Q is singular, rounding can make it indefinite. Perturb p slightly,
  or work on the face where Q is singular.
- The SDP size grows quickly with degree. Use symmetry and sparsity to shrink z(x).

## In Lean/Mathlib
- Pass the certificate's squares to `nlinarith` as hints, for example
  `nlinarith [sq_nonneg (x - y), sq_nonneg (x + y), mul_self_nonneg z]`.
- Or prove the identity p = Σ λ_k l_k² with `ring` or `linear_combination`, then close
  the inequality with `positivity`.
- Useful lemmas: `sq_nonneg`, `mul_self_nonneg`, `add_sq`, `sub_sq` and
  `two_mul_le_add_sq`.
- `polyrith` is no longer supported (its external service was shut down). Supply the
  coefficients yourself with `linear_combination`.

## Numerical sanity check
- Before any certificate search, evaluate p at random points and at local minima
  (scipy.optimize.minimize from many starts). A negative value refutes the claim.
- After rationalizing, expand p - Σ λ_k l_k² with sympy and confirm it is exactly zero.
