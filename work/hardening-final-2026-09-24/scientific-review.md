# Root scientific review — nonlinear coupled forced network

This is a known-type stability/robustness result for a finite mechanical system, authored as a development benchmark. It is not an open-problem or novelty claim. Reference qualification and empirical model difficulty are separate gates, both still pending at creation of this note.

For n>=1, let q_i,v_i,f_i be real trajectories. Positive masses satisfy 0<m_i<=M, damping satisfies 0<delta<=gamma_i<=Gamma, and kappa_i>=0. K is symmetric and coercive: x^T K x>=alpha sum_i x_i^2 for all real vectors x, with alpha>0. The physical dynamics are q_i'=v_i and m_i v_i'=-(Kq)_i-kappa_i q_i^3-gamma_i v_i+f_i. Assume sum_i f_i(t)^2<=F^2 at all times with F>=0. Global differentiability in the ODE hypotheses is explicit; the theorem is conditional on a solution and asserts neither existence nor optimal constants.

Physical energy is E=(sum_i m_i v_i^2)/2+(q^T K q)/2+(sum_i kappa_i q_i^4)/4. Set epsilon=min(delta/(2M), alpha/(2Gamma)). The reviewed claim is epsilon>0 and, for every a<=b,

E(b) <= 4 exp(-(epsilon/2)(b-a)) E(a) + (4/(epsilon delta)+2/alpha) F^2.

The forcing remainder has energy units: epsilon is inverse time, delta is damping, alpha is stiffness, and F is force. The two terms 1/(epsilon delta) and 1/alpha both have inverse stiffness units. The decay estimate is exact for the specified mathematical model, not a numerical or asymptotic approximation.

## Independent derivation checks

For V=E+epsilon sum_i m_i q_i v_i+(epsilon/2)sum_i gamma_i q_i^2, the parameter bounds give epsilon M<=delta/2, epsilon Gamma<=alpha/2 and epsilon^2 M<=alpha/4. A weighted square inequality bounds the cross term in absolute value by E/2; the additional displacement term is between zero and E/2. Hence E/2<=V<=2E.

Symmetry of K is essential in differentiating the quadratic potential. Exact ODE substitution cancels its work term and the quartic-force term. The resulting derivative is

V'=-sum_i(gamma_i-epsilon m_i)v_i^2-epsilon q^T K q-epsilon sum_i kappa_i q_i^4+sum_i v_i f_i+epsilon sum_i q_i f_i.

The two Young bounds absorb delta/4 of the velocity square and epsilon alpha/2 of the position square, leaving at most (1/delta+epsilon/(2alpha))F^2. Thus V'<=-epsilon E+C F^2<=-(epsilon/2)V+C F^2. Integration and E<=2V give the stated bound. These derivation details belong to the evaluator side and must not be copied into worker prompts, libraries, artifacts or retrieval.

## Nonvacuity and interpretation

A concrete nontrivial equilibrium satisfies the assumptions: n=2; masses (1,2), damping (1,2), M=2, delta=1, Gamma=2, alpha=1; K=[[2,-1],[-1,2]]; kappa=(1,2); q=(1,1), v=(0,0), f=(2,3), F=4. Coercivity follows from x^T K x=sum_i x_i^2+(x_1-x_2)^2. Force norm squared is 13<=16, and energy is 7/4. This shows that the assumptions permit nonzero energy, forcing, quartic potential and off-diagonal coupling simultaneously. It is an algebraic interpretation check, not yet a machine-checked fixture.

The target combines symmetry/finite-sum identities, a nonlinear energy derivative, explicit parameter inequalities, a coercive modified-energy comparison and a forced differential inequality. It offers natural independent subproblems without prescribing any decomposition to the model. No Lyapunov bounds or final decay statements may appear among its assumptions. Worker access to ordinary pinned library lemmas is allowed, but evaluator proof files and these derivation notes are withheld.

## Acceptance gates

- Inspect actual compiled Challenge declarations and quantifiers against this statement.
- Accept a complete reference only under pinned Comparator and independent kernel replay with the approved axiom closure.
- Reject source holes and changed target/definition controls; record exact outcomes, not just Lean compilation success.
- Keep lack of human expert review and publication approval explicit.
- Calibrate actual time/cost and retained obligations. If solved quickly, say the difficulty goal was not met; never pad work or weaken tools to force duration.

## Root observed qualification

The frozen reference passed `target-independent-01.json` with independent-kernel assurance; the intentional hole control was rejected with Comparator evidence. Root awaited exit code 0 and inspected both outcomes. Source hashes: Challenge `9b356ee2f2ea86fa860a332bb7d93bafd2d8ed49ced2941732147cb5c6304dc8`, Solution `20dbdc81c6079cde460c269bf40681968f0309576c008c3c2674601d496e6987`. The author separately measured the complete reference under the worker limits: 2 GiB/2 CPU, 120-second allowance, exit 0 in 8 seconds, peak cgroup memory 1,029,541,888 bytes, no OOM. Actual discovery difficulty remains unmeasured. Altered-statement controls are being checked separately.
