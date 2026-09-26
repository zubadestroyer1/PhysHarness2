# Assistant target review and strengthened pilot design

The user explicitly delegated this test's target review to the root assistant on 2026-09-24. Record that fact in review rationale; do not describe this as independent human/expert review or publication approval.

The previous Bell conjunction is rejected for this pilot's difficulty objective: one direct theorem and matrix_expand solve it. The previous scalar energy monotonicity remains useful, but add quantitative consequences requiring the model to connect calculus and inequalities.

## Quantum: arbitrary finite-dimensional dephasing purity loss

For an arbitrary natural dimension n and a normalized density state rho : MState (Fin n), define D to keep exactly its diagonal in the fixed orthonormal basis. Prove the complex trace difference tr(rho*rho)-tr(D*D) equals the real sum of squared magnitudes of all off-diagonal entries, cast to complex, AND that the real part of this trace difference is nonnegative. Include all ordered pairs i,j with i != j (no erroneous extra factor two). This covers arbitrary mixed states; diagonal dephasing preserves populations and removes coherences. All dimensions are finite. The n=0 case has no normalized density state and does not make the universal theorem vacuous for n>=1. Hermiticity supplies the conjugate pair relation, and no imported dephasing-specific theorem is needed. No entropy/entanglement/infinite-dimensional claim.

Target shape:
```
noncomputable def pilotDiagonal (R : Matrix (Fin n) (Fin n) ℂ) := Matrix.diagonal (fun i => R i i)
-- n implicit or explicit consistently
theorem physics_target (n : ℕ) (ρ : MState (Fin n)) :
  (ρ.m * ρ.m).trace - (pilotDiagonal ρ.m * pilotDiagonal ρ.m).trace =
    (((∑ i, ∑ j ∈ Finset.univ.erase i, Complex.normSq (ρ.m i j)) : ℝ) : ℂ) ∧
  0 ≤ ((ρ.m * ρ.m).trace - (pilotDiagonal ρ.m * pilotDiagonal ρ.m).trace).re := by
  sorry
```
Use import QuantumInfo.States.Pure.Qubit only to match pinned library environment; no exact target theorem exists there. Root will inspect exact final target and reference before approving.

## Classical: damped oscillator energy and uniform trajectory bounds

Use the existing arbitrary m>0,k>0,gamma>=0 and global real differentiable solutions q'=v, v'=(-kq-gamma v)/m. Prove the conjunction of energy antitonicity AND, for every a<=b, both
`m*(v b)^2 <= m*(v a)^2+k*(q a)^2` and
`k*(q b)^2 <= m*(v a)^2+k*(q a)^2`.
These are separate velocity/displacement energy bounds, with dimensions consistent. No strict damping, convergence, existence, forcing, or uniformity over varying parameters is claimed. A zero trajectory shows consistency. Nontrivial smooth solutions exist for positive parameters but existence is outside this conditional theorem.

Both are known results and still pilot-scale. General finite sums/Hermiticity and calculus/global order/positivity require multiple proof components but do not guarantee a difficult experience for the model. Short solutions remain valid; if agents finish without delegation/compaction the relevant behavior is untested, not a failure. Do not artificially hide legitimate Mathlib lemmas or require a proof length.

No solutions, reference outlines, or root review notes enter worker context. Fresh evaluator artifacts remain private. These are new pilot targets, not untouched benchmark holdouts or open problems.
