# Forced nonlinear coupled oscillator network

The selected development target combines arbitrary finite coupled degrees of freedom, a symmetric coercive stiffness matrix, heterogeneous positive masses and damping, coordinatewise nonnegative cubic restoring forces, and bounded vector forcing. It asks for an explicit uniform energy input-to-state estimate. The exact machine-readable statement is in the private evaluator's `Challenge.lean` and `target-metadata.json`; the worker-facing description must contain only the physical equations and assumptions, never the withheld reference argument.

This is materially harder than the completed scalar unforced oscillator pilot because the proof must handle a double-sum coupling cancellation, uniform coercivity across all finite dimensions, quartic energy terms, and forcing in a differential comparison. A numerical time-to-proof target cannot be guaranteed without calibration. The problem is a known type of stability estimate, not an open result.

The mathematical constants were independently checked by an assistant before formalization. A withheld Lean proof and independent-kernel/Comparator controls are required before any live worker trial. Assistant review is not human-expert or publication approval.

The hypotheses have a concrete two-coordinate equilibrium. Take `K=[[2,-1],[-1,2]]`, `q(t)=(1,1)`, `v(t)=(0,0)`, `m=(1,2)`, `gamma=(1,2)`, `kappa=(1,2)`, and constant `f=(2,3)`, with `M=2`, `delta=1`, `Gamma=2`, `alpha=1`, and `F=4`. Here `K q=(1,1)` and `kappa_i q_i^3=(1,2)`, so the forcing balances the restoring terms. For any `x`, `xᵀKx=x₁²+x₂²+(x₁-x₂)²`, which proves the required coercivity, and `∑f_i²=13≤16`. This is an algebraic nonvacuity check, not an additional formal certificate.
