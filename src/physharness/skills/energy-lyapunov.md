---
name: energy-lyapunov
summary: Prove boundedness, stability, global existence or decay with a quantity that is conserved or nonincreasing along solutions.
applies_when: An ODE, PDE, gradient flow, Hamiltonian system or iteration needs boundedness, no blow-up, stability or a decay rate.
---
# Energy and Lyapunov methods

## When it applies
- You need boundedness, global existence, stability or decay of solutions.
- A physical quantity (energy, a norm, entropy, free energy) is conserved or dissipated.
- Local existence is known and blow-up must be ruled out.

## Core steps
1. Guess the functional V: total energy (kinetic plus potential), ‖x‖², a weighted
   norm, or xᵀPx for a linear system (solve AᵀP + PA = -Q with Q positive definite).
2. Differentiate along trajectories: d/dt V(x(t)) = ⟨∇V(x), f(x)⟩. Substitute the
   equation; for PDEs integrate by parts and use the boundary conditions.
3. Show dV/dt = 0 (conservation), ≤ 0 (stability) or ≤ -cV (exponential decay, closed
   with Grönwall; see gronwall-comparison).
4. Convert to the target: coercivity V(x) ≥ c‖x‖² turns bounds on V into bounds on x;
   bounded sublevel sets rule out blow-up.
5. For convergence when only dV/dt ≤ 0, use an invariance (LaSalle-type) argument or
   add a small cross term (for damped oscillators, ε⟨x, v⟩) to get a strict decrease.

## Pitfalls
- dV/dt ≤ 0 gives stability, not convergence.
- Energy identities need regularity: they can fail for weak solutions. State what you use.
- Global statements need radial unboundedness: V → ∞ as ‖x‖ → ∞.
- Integration by parts leaves boundary terms; check that the boundary conditions kill them.
- Discrete time needs V(x_{n+1}) - V(x_n) ≤ 0, a different computation from dV/dt.

## In Lean/Mathlib
- Build derivatives with `HasDerivAt.add`, `HasDerivAt.mul`, `HasDerivAt.const_mul`,
  `HasDerivAt.pow` and `HasDerivAt.comp`.
- `HasDerivAt.norm_sq` gives the derivative of ‖f t‖² as 2⟪f t, f'⟫.
- `real_inner_self_eq_norm_sq` rewrites ⟪x, x⟫_ℝ as ‖x‖ ^ 2.
- `antitoneOn_of_deriv_nonpos` and `monotoneOn_of_deriv_nonneg` need a convex domain D,
  continuity on D, and differentiability plus the derivative sign on `interior D`.
- `is_const_of_deriv_eq_zero` proves conservation for a function differentiable everywhere.
- `image_le_of_deriv_right_le_deriv_boundary` compares V with an explicit bound.
- Once dV/dt is expanded, `nlinarith`, `positivity` and `ring_nf` settle its sign.
- Use search_library for existing energy definitions in Physlib before writing new ones.

## Numerical sanity check
- Integrate a few trajectories (RK4, or a symplectic method for Hamiltonian systems)
  and plot V(t). It should be flat or nonincreasing. If a "conserved" quantity drifts
  more than the integrator error, the identity or a sign is wrong.
- Try adversarial initial data: large amplitude, or near the edge of the claimed region.
