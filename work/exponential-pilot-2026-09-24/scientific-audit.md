# Exponential-decay pilot: independent scientific audit

**Status (2026-09-24):** The proposed statement is mathematically supported by the real-variable argument below. This audit does not constitute a compiled Lean reference, accepted proof, or empirical difficulty measurement. The exact source scan described below found useful near results and no exact envelope in the most relevant modules; it cannot certify global absence of a shortcut.

## Statement and mathematical checks

For `m,k,γ>0`, set `ε=min(γ/(2m),k/(2γ))`. Both arguments of `min` are strictly positive, so `ε>0`. The differential assumptions imply `E'=-γv²` for `E=(mv²+kq²)/2`. The units of both rate terms are inverse time. The `a≤b` restriction matters when integrating the differential inequality.

The recommendation's modified energy `V=E+εm qv+(εγ/2)q²` differentiates to `V'=-(γ-εm)v²-εkq²`. The rate bounds give `εm≤γ/2`, `εγ≤k/2`, and `ε²m≤k/4` (the last follows by multiplying the first two bounds). Completing squares yields `E/2≤V≤2E` and `V'≤-εV`. Hence `E(b)≤2V(b)≤2 exp(-ε(b-a))V(a)≤4 exp(-ε(b-a))E(a)`. This is a conditional estimate for any global solution; it does not assert solution existence or optimal rate. In particular, ordinary energy dissipation alone does not prove the exponential estimate because `E'=0` whenever `v=0`.

## Exact semantic negative controls

**Prefactor one is false even with positive damping.** Take `m=k=1`, `γ=2`, `q(t)=(1+t) exp(-t)`, and `v(t)=-t exp(-t)` for all real `t`. Then `q'=v` and `v'=(-q-2v)`, and the challenge rate is `ε=min(1,1/4)=1/4`. At `a=0`, `E(0)=1/2` and `E(t)=((1+t)²+t²) exp(-2t)/2`. The proposed prefactor-one inequality at `b=t` would require `R(t)=((1+t)²+t²) exp(-7t/4)≤1`. But `R(0)=1` and `R'(0)=1/4>0`, so every sufficiently small positive `t` violates it. A checked Lean negative should instantiate this trajectory and prove the *negation* of the altered universal statement, or give a concrete positive rational time with a verified exponential inequality. Merely failing to construct a proof is not a semantic negative.

**Removing positive damping:** with `m=k=1`, `γ=0`, `q(t)=cos t`, `v(t)=-sin t`, energy is constantly `1/2`. For any externally prescribed `r>0`, the altered envelope `E(b)≤4 exp(-r(b-a))E(a)` fails at sufficiently large `b-a`. If the altered statement instead keeps the exact definition `ε=min(γ/(2m),k/(2γ))` and simply drops `γ>0`, then Lean's real division at zero makes `ε=0`; the *positive-rate conjunct* is false, while the factor-four envelope at rate zero remains true. The negative control must say which alteration it tests.

The positive target and both false alterations must pass through the same exact-target acceptance boundary. A rejected candidate because of an import error, timeout, bad tactic, or missing lemma is not evidence that the altered statement is false.

## Pinned library scan and shortcut risk

I inspected the actual pinned formal image (`physharness-formal:wave01-final`) in a disposable container with `--read-only --network none --memory 1g`. The lock pins Mathlib `db584cd6d46c92f209a44c0f1c829460d327499d` and Physlib `405848179db6375f814021e804a37dc0dda66d91`. A content scan covered 8,894 `.lean` files under their `Mathlib` and `Physlib` trees. A path-only search would have missed the strongest near results:

- `Physlib/ClassicalMechanics/DampedHarmonicOscillator/Basic.lean:185` proves the damped mechanical-energy derivative, and line 306 proves positivity of that module's decay rate `γ/(2m)`.
- `Physlib/ClassicalMechanics/DampedHarmonicOscillator/Solution.lean:138–155` defines explicit trajectories in all three damping regimes; lines 524 and 548 give smooth-solution uniqueness. These are in `Time → EuclideanSpace ℝ (Fin 1)` with a stronger smoothness premise than the scalar `HasDerivAt` challenge. They do not directly state the desired physical-energy envelope, but a solver may use them after bridging representations or may borrow their methods.
- `Mathlib/Analysis/ODE/Gronwall.lean:112` has a generic scalar comparison theorem. Its displayed signature imposes no `K≥0` premise, so `K=-ε` is plausible after discharging the one-sided derivative conditions. The elementary weighted-energy/antitonicity route may be shorter.

I found no exact exponential physical-energy envelope among the declarations in the two pinned Physlib damped-oscillator modules. The full-tree keyword scan also found no obvious exact match, but equivalent statements under other names or formulations remain possible. This is a qualified source finding, not a novelty or no-shortcut certificate.

## Controlled-comparison limits and safeguards

Separate project/database/artifact stores per run are warranted. The `search_knowledge` implementation queries verified claims with `RecordRow.project_id == actor.project_id` (`src/physharness/research.py:78–100`), and `knowledge_bundle` can release accepted candidate source when sharing and evidence conditions pass. Thus reusing one project across repeats could let a later arm retrieve an earlier accepted proof. A new experiment within the same project is insufficient when sharing permits cross-experiment accepted dependencies. Also keep worker-visible filesystem/context free of calibration attempts, withheld reference, review rationale, negative controls, and prior trial transcripts. Project isolation addresses canonical retrieval, not possible model pretraining or leakage through an operator's reused prompt.

Calibration attempts on the exact target are development data, not an independent holdout. If the identical target is then compared under `none` versus `ideas`, both arms inherit target-selection bias from calibration; later arms can additionally benefit from operator learning, VM caches, or source familiarity. Counterbalanced run order (`none/ideas/ideas/none`) helps diagnose order effects but does not erase these risks, especially without a fresh target. Record order, start and first-verification timestamps, VM/cache state, and any worker messages or retrieved sources.

Three single-agent calibration attempts and four two-agent runs (two per sharing policy) are small samples. A `2/3` success gate is a pragmatic go/no-go rule, not a stable success-probability estimate; two repeats per policy cannot support a precise collaboration effect or rare-failure claim. Report each observation, paired run order, uncertainty, and actual communication. If communication is enabled but no messages are exchanged, the comparison measures a configuration difference rather than demonstrated collaboration.

Predeclare first verified proof as the primary success/time endpoint and distinguish its *settled cost at that event* from whole-arm cost after concurrent calls drain. Stop/drain policy must be identical across arms. Report whole-arm time/cost as secondary. Concurrent in-flight charges may settle after first proof, so neither cost measure should be substituted for the other. The remaining ceiling is `100 - 3.658018 = 96.341982` dollars before any new probe or calibration charges, while the proposed new global ceiling of 92 dollars is stricter. Track the actual total and conservative unsettled reservations before each launch.

## Bounded fallback if every direct calibration finishes under five minutes

Stop calibrating this target under the predeclared rule. A candidate next development problem is the following driven-oscillator bound, which adds a real forcing term `f` and a uniform forcing bound on the measured interval. For `m,k,γ>0`, `ε=min(γ/(2m),k/(2γ))`, `F≥0`, `a≤b`, `q'=v`, `v'=(-kq-γv+f)/m`, and `|f(t)|≤F` for every `t∈[a,b]`, prove

`E(b) ≤ 4 exp(-(ε/2)(b-a)) E(a) + [16(1/m+ε²/k)/ε²] F²`.

The formula is valid: the same `V` satisfies `E/2≤V≤2E` and `V'≤-εV+f(v+εq)`. From `v²≤4V/m`, `q²≤4V/k`, and Young's inequality, `f(v+εq)≤(ε/2)V+[4(1/m+ε²/k)/ε]F²`. Integrating `V'≤-(ε/2)V+CF²` gives the stated constant after converting back to `E`. This is a mathematical derivation, not a compiled reference or evidence of adequate difficulty. Construct and kernel-check a separate withheld reference, check a true semantic negative, and run a bounded pilot before promoting it. Do not continue changing targets without a new explicit gate.
