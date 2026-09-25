---
name: symmetry-invariants
summary: Use symmetries and invariants to reduce dimension, force cancellations, get conserved quantities, or prove that a target is unreachable.
applies_when: The problem is invariant under rotations, translations, reflections, permutations, gauge or time reversal, or some quantity never changes.
---
# Symmetry arguments and invariants

## When it applies
- The equations, domain and data are invariant under a group of transformations.
- You want to reduce dimension (radial functions, separation of variables, an
  invariant subspace).
- You expect a quantity to vanish (odd integrands, selection rules) or to be conserved.

## Core steps
1. Write each symmetry as an explicit map g : X → X, and write how it acts on every
   object: functions, states, operators, boundary data.
2. Check that the equation, domain, boundary conditions and functional are invariant.
3. Exploit the symmetry:
   - Uniqueness: a unique solution inherits the symmetry.
   - Invariant subspace: restrict the problem to symmetric functions or states.
   - Averaging: for convex problems, averaging a minimizer over the group gives a
     symmetric minimizer.
   - Noether: a continuous symmetry gives a conserved quantity.
4. Discrete symmetries: an odd function integrates to zero over a symmetric domain;
   terms paired by an involution cancel.
5. Impossibility: find an invariant that every move or the dynamics preserve and
   that differs between the start and the target.

## Pitfalls
- A symmetric problem can have asymmetric solutions (symmetry breaking). You need
  uniqueness or an averaging argument.
- Boundary conditions, constraints or dissipation can break the symmetry.
- Apply the action consistently: a rotation acts on positions and on derivatives.
- A conserved quantity requires the symmetry of the actual dynamics, not an idealization.

## In Lean/Mathlib
- Group actions: `MulAction.orbit` and `MulAction.stabilizer`.
- Parity and periodicity: `Function.Even`, `Function.Odd` and `Function.Periodic`.
- `intervalIntegral.integral_comp_neg` substitutes x ↦ -x in an interval integral.
- `is_const_of_deriv_eq_zero` shows a quantity with zero derivative is constant.
- For reindexing or pairing terms in a finite sum, `exact?` and search_library find the
  `Finset` bijection and involution lemmas that match your statement.

## Numerical sanity check
- Apply the symmetry to a computed solution and measure the difference, which should be
  at the level of discretization error.
- Evaluate a claimed invariant along a simulated trajectory, or over random move
  sequences.
