# Withheld exponential-energy reference qualification

The exact challenge and a complete withheld proof are in `.state/exponential-pilot-2026-09-24/evaluator/base/`. Their theorem statements match byte for byte up to `:= by`. The proof establishes the stated envelope for every positive `m`, `k`, and `γ` and every global solution of the two given derivative equations. No statement restriction by damping regime was introduced.

## Pinned compiler checks

Image: `sha256:48e4f60a07c289baf846c0ff6fa2624870c59547c2a00971db0510e767161be0` on dedicated `physharness-pilot` Docker socket. All runs were network-isolated, user `65532:65532`, with `--memory 4g --cpus 2`. The disposable `exponential-ref-compile` container was removed after checks. No image or persistent cache was modified.

- `lean /work/Challenge.lean`: exit 0, only expected warning `declaration uses sorry`.
- `lean /work/Solution.lean`: exit 0, no errors or warnings.
- `#print axioms physics_target`: `[propext, Classical.choice, Quot.sound]`; no `sorryAx`.
- Text scan of `Solution.lean` finds no `sorry`, `admit`, `unsafe`, or introduced `axiom` (the `#print axioms` command is the only match).

`LEAN_PATH` was set to the colon-joined `*/.lake/build/lib/lean` directories under `/opt/sources` in the pinned image. The first challenge elaboration detected that both real-valued helper definitions needed `noncomputable`; this was corrected in both exact-statement files before the final checks. Initial reference attempts had routine elaboration goals in derivative conversion and exponential algebra; the final proof closes all of them.

## Fixture

`qualification-cases.json` uses the prior engineering-smoke schema, with a positive case and a `sorryAx` hole control. Its three project lock files are byte copies of the prior private evaluator project. Comparator and independent kernel acceptance are delegated to the root task; successful direct Lean compilation and axiom print alone are not a claim that this pipeline has passed.

SHA-256:

- `Challenge.lean`: `20df4f3dbfac2b36ec05ac14110df793bc84e7121a7855e9ef28ad4655023aa5`
- `Solution.lean`: `1c3d49e069403ab61554e6430935a4531c0e2263ae54c73e65452e10f6b0ad09`
- `qualification-cases.json`: `1d08578a7a644514c0d609479c8788b052bf30ae814236126218edfe8e10f6ef`

## Qualification correction

The first independent Comparator run rejected the otherwise compiling positive reference because `private` helper definitions were qualified under different source modules (`Challenge` versus `Solution`). The original files and this report's first version are preserved under `evaluator/base/attempt-private-defs/`. The two helper definitions are now stable, non-private `noncomputable def`s in both base files. This changes no numerical or physical conclusion. The repaired solution and challenge compile directly in the pinned image, and the theorem's axiom print remains `[propext, Classical.choice, Quot.sound]`. Root requalification passed in `target-independent-02.json`: Comparator, Lean kernel and Nanoda accepted the repaired reference; the incomplete candidate was rejected for `sorryAx`. The adversarial statement-binding fixture is `evaluator/controls-cases.json`.

The additional statement controls passed in `target-controls-independent-02.json`: the reference was accepted again, and both the weakened conclusion and changed prefactor were rejected for exact theorem-statement mismatch. The first controls-only invocation was rejected by the suite validator because it requires a positive control alongside negative cases; the combined fixture retains all controls. These reports qualify the private test environment, not a public production deployment or expert novelty review.
