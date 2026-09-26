# Next physics problem: exponential energy decay for general damping

**Status:** mathematically checked recommendation; the new target has **not** been elaborated, proved, or calibrated in Lean. No new theorem-verification or paid model trial was started for this recommendation. The root briefly inspected library signatures in the VM while it was running for the separate source-tool repair. In the prior four-arm pilot, both targets reached first verified proof in 67–93 seconds, with no compaction and no communication in the collaborating arms (`../parallel-pilot-2026-09-24/REPORT.md`). The old results do not predict this target's difficulty.

## Primary target

For arbitrary real constants `m>0`, `k>0`, `γ>0`, suppose global trajectories `q,v : ℝ → ℝ` satisfy `q'(t)=v(t)` and `v'(t)=(-k q(t)-γ v(t))/m` at every real time. Define the physical energy `E(t)=(m v(t)²+k q(t)²)/2` and rate `ε=min(γ/(2m), k/(2γ))`. Prove `ε>0` and, for all `a≤b`,

`E(b) ≤ 4 exp(-ε(b-a)) E(a)`.

This covers underdamped, critically damped, and overdamped parameter regimes with one explicit bound. The factor four is meaningful: `E'=-γv²`, so with `q(a)≠0` and `v(a)=0`, energy initially has zero derivative and cannot generally satisfy the same positive-rate exponential bound with prefactor one. The statement is conditional on global solutions; it claims neither existence nor an optimal rate.

### Uncompiled Lean statement sketch

```lean
import Mathlib

private def physicalEnergy (q v : ℝ → ℝ) (m k t : ℝ) : ℝ :=
  (m * v t ^ 2 + k * q t ^ 2) / 2

private def decayRate (m k γ : ℝ) : ℝ :=
  min (γ / (2 * m)) (k / (2 * γ))

theorem physics_target (q v : ℝ → ℝ) (m k γ : ℝ)
    (hm : 0 < m) (hk : 0 < k) (hγ : 0 < γ)
    (hq : ∀ t, HasDerivAt q (v t) t)
    (hv : ∀ t, HasDerivAt v ((-k * q t - γ * v t) / m) t) :
    0 < decayRate m k γ ∧
      ∀ a b : ℝ, a ≤ b →
        physicalEnergy q v m k b ≤
          4 * Real.exp (-decayRate m k γ * (b-a)) *
            physicalEnergy q v m k a := by
  sorry
```

The auxiliary construction below belongs only in a withheld reference. It must not be included in the worker challenge or prompt. A compact statement is deliberate: adding conjuncts did not make the last pilot hard.

## Feasibility argument to verify privately

Set `V=E+εm qv+(εγ/2)q²`. The rate bounds imply `εm≤γ/2`, `εγ≤k/2`, and `ε²m≤k/4`. Direct differentiation yields

`V'=-(γ-εm)v²-εkq²`.

Completing squares with `m(v/2+εq)²` and `m(v/2-εq)²` gives `E/2≤V≤2E`. Moreover, after dividing positive `ε` out of `-(V'+εV)`, the expression is

`(γ/ε-3m/2)v² + ((k-εγ)/2)q² - εm qv`.

The first coefficient is at least `m/2`, the second at least `k/4`, and `m v²/4-εm qv+ε²m q²=m(v/2-εq)²≥0` with `ε²m≤k/4`. Thus `V'≤-εV`. Differentiating `exp(εt)V(t)` shows it is nonincreasing. For `a≤b`, `V(b)≤exp(-ε(b-a))V(a)` and the two energy comparisons give the factor-four target. These algebraic checks establish the real-variable route, **not a compiled Lean reference**. A direct imported theorem or a shorter proof remains legitimate and would change the observed difficulty.

## Candidate comparison

| Candidate | Genuine burden | Shortcut or gap | Decision |
|---|---|---|---|
| General damped oscillator exponential envelope | Find a coercive modified energy, prove its differential decay, and transfer the exponential estimate back to physical energy | A direct theorem or concise tactic proof may exist; exact target untested | **Primary** |
| Two-dimensional harmonic orbit with nonzero angular momentum and upper/lower radius bounds | Energy and angular-momentum invariants plus Lagrange identity | Prior repository benchmark already proves angular-momentum conservation; remaining steps may be routine | Development rung only |
| Bipartite pure-state equality of reduced purities | Partial traces and matrix/tensor rearrangement | Existing Physlib lemma may settle it immediately; representation audit needed | Reserve quantum option |

If the primary has an exact library shortcut or every direct development attempt finishes in under five minutes, consider a **driven** damped-oscillator input-to-state bound as a fallback, after separately choosing and checking its exact forcing norm and reference proof. No unverified forcing formula is asserted here. Do not increase apparent difficulty by hiding useful library results or requiring a proof length.

## Library status and calibration gate

`formal/environment.lock.json` pins [Mathlib `db584cd6`](https://github.com/leanprover-community/mathlib4/tree/db584cd6d46c92f209a44c0f1c829460d327499d) and [Physlib `40584817`](https://github.com/leanprover-community/physlib/tree/405848179db6375f814021e804a37dc0dda66d91). The Linux image holds their sources at `/opt/sources`; they are unavailable on this host. The prior benchmark used `antitone_of_deriv_nonpos` for ordinary energy monotonicity. A **read-only check of the actual pinned image** found `Mathlib/Analysis/ODE/Gronwall.lean` and `le_gronwallBound_of_liminf_deriv_right_le` (recorded in `work/source-lookup-fix-2026-09-24/pinned-gronwall-{declarations,signatures}.txt`). That theorem's displayed signature does not require `K≥0`, so `K=-ε` is syntactically plausible, but its one-sided derivative premise needs work. The simpler exponential-weight derivative and antitone route should also be checked in a small pinned scratch file. Neither route has yet compiled for the new target. Current online Mathlib documents [exponential differentiation](https://leanprover-community.github.io/mathlib4_docs/Mathlib/Analysis/SpecialFunctions/ExpDeriv.html) and [derivative-based antitonicity](https://leanprover-community.github.io/mathlib4_docs/Mathlib/Analysis/Calculus/Deriv/MeanValue.html); online declarations may differ from this pin.

Before qualification, search the pinned sources for an exact or near-exact theorem, elaborate the exact target, construct a withheld reference proof, and independently kernel-check its theorem and axiom closure. Worker access must exclude that reference, this rationale, and historical benchmark solutions. The pilot's source-search/read round-trip defect is now fixed and passed an actual pinned-VM regression; see `../source-lookup-fix-2026-09-24/DELIVERY.md`.

Use explicit semantic negatives: without damping, a nonzero harmonic trajectory retains positive energy and violates any positive-rate envelope at late times; prefactor one fails at small positive times from data with `q(a)≠0`, `v(a)=0`. Verify the chosen counterexamples against the precise altered statements, then send controls through the same acceptance pipeline. A previous proposed annulus negative control based on weakening `ω>0` was invalid because its cross-multiplied inequalities use `ω²`; that control is withdrawn.

After proof feasibility, run a small **development** direct single-agent calibration with matched model/environment/spend limits and predeclared stopping. An operational target is at least two accepted proofs in three attempts within 45 minutes, with median first verified proof above ten minutes. These thresholds are guesses, not estimated from the pilot. If all are fast, revise the problem; if none succeeds, diagnose theorem and tool feasibility. A development problem is not a holdout. Any later collaboration comparison needs separately frozen targets, repeated matched arms and an explicitly authorized live protocol and budget. No collaboration or compaction benefit is claimed now.

## Root review

The root independently checked the modified-energy derivative, the two energy comparisons, the positive rate and its units, and the time-order restriction. All positive damping regimes are included; the estimate is intentionally conservative and not asserted optimal. This is the selected next development candidate, replacing the easier annulus proposal. The frozen challenge must include the physical equation, energy and rate only, not the auxiliary modified energy or this proof outline. This review is assistant-led, not human-expert or publication approval. Compiled-reference qualification and empirical calibration remain outstanding; no new paid run is authorized by this recommendation.
