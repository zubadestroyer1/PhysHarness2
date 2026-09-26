# Driven oscillator fallback: bounded feasibility proposal

**Status:** mathematically derived, Lean target and proof outline drafted privately, not compiled or Comparator-qualified. No experiment, worker run, or manifest was changed. This is a fallback for root scientific review if the unforced calibration is too easy.

The target uses arbitrary `m,k,γ>0`, `F≥0`, global real trajectories satisfying `q'=v` and `v'=(-kq-γv+f)/m`, and an interval-local bound `|f(t)|≤F` for every `t∈[a,b]` with `a≤b`. It claims `ε>0`, where `ε=min(γ/(2m),k/(2γ))`, and

`E(b) ≤ 4 exp(-(ε/2)(b-a)) E(a) + 16(1/m+ε²/k)F²/ε²`, with `E=(mv²+kq²)/2`.

The interval-local assumption is essential to the stated scope; no forcing bound outside `[a,b]` is needed. Differentiability of `f` is not assumed.

## Derivation

The already compiled unforced reference supplies `ε>0`, `εm≤γ/2`, `εγ≤k/2`, and `E/2≤V≤2E` for `V=E+εmqv+εγq²/2`. With forcing,

`V'=-(γ-εm)v²-εkq²+f(v+εq) ≤ -2εE+fv+εfq`.

For any `t∈[a,b]`, completing squares gives

`fv ≤ εm v²/4 + f²/(εm)` and `εfq ≤ εk q²/4 + εf²/k`.

Since `f²≤F²`, their sum is at most `εE/2 + (1/(εm)+ε/k)F²`. Also `(ε/2)V≤εE`, so

`V'+(ε/2)V ≤ (1/m+ε²/k)F²/ε` on `[a,b]`.

Let `D=2(1/m+ε²/k)F²/ε²`. The derivative of `exp(εt/2)(V(t)-D)` is nonpositive on the interval. Consequently,

`V(b) ≤ exp(-(ε/2)(b-a))V(a) + D(1-exp(-(ε/2)(b-a)))`.

The exponential factor lies in `(0,1]`, and `D≥0`. Using `E≤2V` and `V≤2E` yields the **stronger** bound with additive coefficient `4` in place of the proposed `16`; hence the proposed statement is valid with ample algebraic slack. For `F=0`, the rate is half the unforced rate, as expected from absorbing the forcing term. The units of both additive summands are energy.

## Lean feasibility and remaining work

The private [Challenge.lean](../../.state/exponential-pilot-2026-09-24/evaluator/fallback/Challenge.lean) uses non-private helper definitions so the Comparator can bind matching source modules. The private [Solution.lean](../../.state/exponential-pilot-2026-09-24/evaluator/fallback/Solution.lean) is an explicit **unproved draft with `sorry`**. It must not be admitted as a reference or exposed to workers. The main additional formal step beyond the unforced reference is `antitoneOn_of_deriv_nonpos` on `Set.Icc a b`, with derivative nonpositivity only on the interval. The [Mathlib documentation](https://leanprover-community.github.io/mathlib4_docs/Mathlib/Analysis/Calculus/Deriv/MeanValue.html) gives this theorem with convexity, continuity on the set, differentiability on its interior, and derivative sign on its interior; exact availability and spelling in the pinned Mathlib revision remain to be checked. The Young inequalities and final exponential algebra also need pinned Lean compilation.

Do not use this fallback in calibration until root scientific review, full proof, Comparator statement binding, and independent kernel acceptance pass.
