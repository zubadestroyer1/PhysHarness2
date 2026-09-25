---
name: spectral-perturbation
summary: Bound eigenvalues, gaps and resolvents with Rayleigh quotients, perturbation bounds and Neumann series.
applies_when: You need energy levels, ground-state bounds, spectral gaps, eigenvalue stability, or invertibility of a perturbed operator.
---
# Spectral and perturbation arguments

## When it applies
- You need bounds on eigenvalues or energy levels of a Hermitian matrix or Hamiltonian.
- A spectral gap must survive a perturbation.
- You need invertibility of 1 - T or A + B with a resolvent bound.

## Core steps
1. Fix the setting: a finite Hermitian matrix, a bounded self-adjoint operator, or an
   unbounded operator (then domains matter).
2. Variational characterization: λ_min = inf ⟨x, Ax⟩/‖x‖² and λ_max = sup. Any trial
   vector gives an upper bound on λ_min. Use min-max for the k-th eigenvalue.
3. Perturbation: for Hermitian A and B, each ordered eigenvalue moves by at most ‖B‖
   (Weyl). A simple eigenvalue with unit eigenvector v and gap g shifts by
   ⟨v, Bv⟩ + O(‖B‖²/g) when ‖B‖ is small compared with g.
4. Neumann series: if ‖T‖ < 1, then 1 - T is invertible with inverse Σ Tⁿ, and
   ‖(1 - T)⁻¹‖ ≤ 1/(1 - ‖T‖) in a normed algebra with ‖1‖ = 1.
5. Locate the spectrum: σ(A) lies in the closed ball of radius ‖A‖. For matrices, also
   use Gershgorin discs.

## Pitfalls
- Degenerate eigenvalues: first-order theory must diagonalize B inside the eigenspace.
- Unbounded perturbations need relative bounds, ‖Bx‖ ≤ a‖Ax‖ + b‖x‖, and domain care.
- Non-Hermitian eigenvalues can be very sensitive; Weyl-type bounds fail for them.
- A variational upper bound is not a lower bound. For lower bounds, prove an operator
  inequality A ≥ c·1.
- Check the library's eigenvalue ordering and indexing before saying "the k-th eigenvalue".

## In Lean/Mathlib
- Matrices: `Matrix.IsHermitian`, `Matrix.IsHermitian.eigenvalues`,
  `Matrix.IsHermitian.eigenvectorBasis` and `Matrix.IsHermitian.spectral_theorem`.
  `Matrix.IsHermitian.eigenvalues_eq` writes an eigenvalue as the Rayleigh quotient of
  its eigenvector.
- Operators: `LinearMap.IsSymmetric`. In finite dimensions,
  `LinearMap.IsSymmetric.hasEigenvalue_iSup_of_finiteDimensional` and
  `LinearMap.IsSymmetric.hasEigenvalue_iInf_of_finiteDimensional` say the sup and inf of
  the Rayleigh quotient are eigenvalues. See also `ContinuousLinearMap.rayleighQuotient`,
  `Module.End.HasEigenvalue` and `Module.End.eigenspace`.
- Spectrum: `spectrum` and `spectrum.subset_closedBall_norm`.
- Neumann series: `Units.oneSub` and `NormedRing.inverse_one_sub` (for ‖t‖ < 1).
- General min-max and Weyl inequalities may be missing. Check with search_library,
  or prove only the case you need (often the extreme eigenvalue, via the Rayleigh quotient).

## Numerical sanity check
- Diagonalize the matrix, or a truncation or discretization, with numpy.linalg.eigh.
  Check the claimed bound over a sweep of parameters, especially where the gap nearly
  closes.
- For infinite-dimensional operators, confirm that the truncation has converged first.
