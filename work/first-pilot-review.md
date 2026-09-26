# First pilot: proposed quantum dephasing pair

Status: **prepared only**. Both targets are pending scientific review; no model calls, proof receipts, or reviewer approvals have been created. The proposed paid envelope is **$5 per experiment, $10 total**, subject to the user's acceptance before launch.

## Exact targets for human review

Both targets come from the **development** split of `benchmarks/physics/quantum.json`, family `decoherence`, and import `QuantumInfo.States.Pure.Qubit` from the pinned physics image. The byte-for-byte source files are [first challenge](../.state/runs/first-pilot/dephase-projection/Challenge.lean) and [second challenge](../.state/runs/first-pilot/dephase-purity-loss/Challenge.lean). The selected theorem is the top-level `physics_target` in each file. The only hole is its proof; `dephase` is fully defined.

The shared definition is:

```lean
noncomputable def dephase (R : Matrix Qubit Qubit ℂ) : Matrix Qubit Qubit ℂ :=
  (1 / 2 : ℂ) • (R + (Qubit.Z : Matrix Qubit Qubit ℂ) * R *
    (Qubit.Z : Matrix Qubit Qubit ℂ))
```

The first target, `quantum.decoherence.complete_dephasing_projection` (author estimate: intermediate), says that a half identity/half Z-conjugation removes the off-diagonal entries of a qubit density matrix, and a second application changes nothing:

```lean
theorem physics_target (ρ : MState Qubit) :
    dephase ρ.m = Matrix.diagonal (fun i => ρ.m i i) ∧
    dephase (dephase ρ.m) = dephase ρ.m := by
  sorry
```

The second target, `quantum.decoherence.purity_loss` (author estimate: stretch), says that loss of trace-squared purity is exactly twice the squared magnitude of the 0,1 coherence:

```lean
theorem physics_target (ρ : MState Qubit) :
    (ρ.m * ρ.m).trace - (dephase ρ.m * dephase ρ.m).trace =
      (2 : ℂ) * (Complex.normSq (ρ.m 0 1) : ℂ) := by
  sorry
```

`MState Qubit` supplies a normalized, positive, Hermitian density matrix, whose `.m` is a complex two-by-two matrix. `Qubit.Z` uses the pinned computational basis and phase convention. The first target concerns matrix equality and idempotence; the definition alone does not include a CPTP certificate. The second equality is in `ℂ`; `Complex.normSq` is real and explicitly coerced to `ℂ`. The corresponding nonincrease of real purity is an interpretation of the equality, not the formal conclusion. These statements cover finite-dimensional qubits only.

The first theorem's diagonalization conjunct can replace `dephase ρ.m` in the second target and thus offers a real compositional route. The two challenges independently declare `dephase` and `physics_target`; retrieved accepted source must be adapted into the second candidate, avoiding duplicate declarations. The second theorem also admits a direct component calculation, so success alone does **not** establish reuse. Inspect the second attempt's retrieval calls, submitted source, cited claim/receipt and final receipt to determine whether the accepted first lemma was actually used. It must be rechecked as part of the complete second proof.

## Provenance and contamination

The definitions and task descriptions come from the two development records in `benchmarks/physics/quantum.json`. Their `Challenge.lean` files were copied without edits. Pinned Physlib source: [`Qubit.lean` at 4058481](https://github.com/leanprover-community/physlib/blob/405848179db6375f814021e804a37dc0dda66d91/QuantumInfo/States/Pure/Qubit.lean) fixes `Z`; [`MState.lean` at 4058481](https://github.com/leanprover-community/physlib/blob/405848179db6375f814021e804a37dc0dda66d91/QuantumInfo/States/Mixed/MState.lean) defines the density-state structure and Hermiticity. [Watrous, *The Theory of Quantum Information*, §2.2.3](https://cs.uwaterloo.ca/~watrous/TQI/TQI.pdf) provides physical background. The exact formal claims and added `dephase` definition are benchmark author constructions and still require independent scientific review.

Reference proofs exist in this repository for these development cases. The agent-visible plan, source challenge, target record and preparation artifacts contain **no reference proof or proof outline**. The runner's initial prompt uses the canonical target and research brief; the private project bundle contains only trusted Lake files and the challenge. This is an engineering pilot with known results, not a novelty or uncontaminated model benchmark. The two difficulty labels are author estimates, uncalibrated on this model.

## Prepared identities and limits

| Item | First: projection | Second: purity loss |
| --- | --- | --- |
| Run ID | `first-pilot-v2-dephase-projection` | `first-pilot-v2-dephase-purity-loss` |
| Problem ID | `b3817784-8d0e-4961-9903-c3c0feef1b58` | `215b5024-4285-4aa4-baed-05cf37363291` |
| Experiment ID | `f2214f34-d2b0-4035-9be8-75857cd8cb2f` | `346e6d5e-4d40-4a30-a28d-c93236f45714` |
| Target digest | `789a2c8a03a2028338200e44c97a8e337b0e57ed21971467f0a308db6d7946b4` | `29911b3b68ad42081eb7bb8ba3f6290f4be2efa4d7243b3cc71a4199f543e54d` |
| Challenge SHA-256 | `b9a6382b1ebe426f4c580d11c743a6a89968fcf5ea756ccc329ba975497a2667` | `9d67036429d2fa386e403b21d35ad2839115267f4fb2281f511d6d54d27417ba` |
| Plan SHA-256 | `a3e72229fbe73b918c88ed670577042446e25a1f57039caeb51b7a3b064e6fc9` | `6e940e4bbfc0e3918742d01354823e58991fd8799eb0704af175ecf216ff15e9` |
| Bundle manifest SHA-256 | `5dc1775da5a0e9ccdf33651c72b79d94006b0d13b2bff8d30f073ad38eda3985` | `e945065f8a8a877d623b20e4e7eb45b00bd985a3d449464e4cc1a955962f8ffd` |

Both active v2 plans use the exact `gpt-6-sol` model ID with Responses reasoning effort `high`, policy `direct`, one model, verified sharing, one concurrent worker, a $5 central cost ceiling, 1,800-second runtime ceiling, 96,000 total token ceiling, 24 turns, and 16,384 maximum output tokens per response. The high reasoning setting can consume substantial output tokens, so the 16,384 per-response cap and 96,000 aggregate cap are deliberate. [OpenAI's current model page](https://developers.openai.com/api/docs/models/gpt-6-sol) lists Standard text rates of $2 per million input tokens and $10 per million output tokens for prompts at or below 272,000 input tokens; the [local price configuration](../.state/runs/first-pilot/model-prices.json) records this source. The operator must confirm applicable rates and processing mode at launch. Each experiment should run with `--concurrency 1 --max-tasks 1 --timeout-seconds 1800`. The second should be launched only after the first has an accepted independent-kernel receipt and retrievable source, if reuse is the objective.

The shared environment SHA-256 is `0c46de2450bd5a9b2584d513d3ad02a963a300c3b0e3510a3a22efbc5a11341f`. It pins physics image `sha256:84deccc518a7aa5ce916d15236dac5ae416a5288449bd8620a2c8bb374c24b67` from `work/wave01/evidence-8g/image-metadata.json` (metadata file SHA-256 `fe7095a9c8a4fdd864925654af0edd03dac7106314bc2bf80c81e26b2a3c9442`). The [project](../.state/runs/first-pilot/project) contains exactly the physics Lake configuration, lock manifest and Lean toolchain. These are immutable inputs for this target revision; changing them calls for a new preparation and review.

The active [first v2 plan](../.state/runs/first-pilot/dephase-projection.v2.plan.json), [second v2 plan](../.state/runs/first-pilot/dephase-purity-loss.v2.plan.json), [environment](../.state/runs/first-pilot/environment.json), [first v2 bundle](../.state/runs/first-pilot/bundles/v2-dephase-projection) and [second v2 bundle](../.state/runs/first-pilot/bundles/v2-dephase-purity-loss) live under the isolated pilot directory. Its `private/` directory contains the pilot-only SQLite database, role token files and artifact store. Keep that directory private; never copy tokens into model inputs or reports. The [operator environment helper](../.state/runs/first-pilot/operator-env.sh) sets isolated paths, recorded prices, the dedicated Colima endpoint and a worktree temporary directory; it exposes functions to load a role identity and, only at authorized launch, the API key. It does not load credentials when sourced. The earlier v1 plans and bundles remain for audit, but both v1 experiments were canonically cancelled when v2 superseded them. Pilot role tokens were rotated after an accidental tool-output exposure of the original set; no old token remains in the active authentication store. Preparation returned zero model calls.

The private engineering fixture at `.state/pilot-qualification/selected-targets/fixtures.json` contains known reference solutions for these exact two challenge byte strings plus a malformed-mixture-weight negative control. Its fixture SHA-256 is `32d532f8244e91af72ed64c7a047c5c62c72703ed5c14323f620a50fa6a1a076`. It is reserved for Linux verifier testing by the operator and is not model output or part of either experiment's agent-visible inputs.

The fresh [scoped qualification packet](pilot-qualification-2026-09-23/attempt-01/QUALIFICATION_REVIEW.md) reports ten mechanical checks satisfied, while deployment approval remains pending. Its canonical scope digest is `f13defb821a8043a16978a83058abd1e6f7cbed8a60bd36549fb647efe3cd70f` (raw `scope.json` SHA-256 `91bbf4d606fe3d7849eb84d6471a2e8a67654eb82dd8a7f5671d764d2126d6a5`); `qualification-review.json` SHA-256 is `04b3664adb79f6e67b5edce30602592728cbce57ad5aa2d64181852714bb7675`. The [proposed two-route verifier registry](../.state/runs/first-pilot/verifier-registry.proposed.json) has SHA-256 `747a86088e7611c7cac0c59c56481db27417483d778dd4bad1b3b834f180472b`. Schema and startup bundle checks pass without candidate execution. It has **not** been activated. The [drafting script](../.state/runs/first-pilot/draft_registry.py) recaptures all 61 current scoped input hashes and reruns the exact four suite, regression and boundary assessment against the frozen packet before a new proposal; this is a freshness check, not approval. The [decision template](../.state/runs/first-pilot/deployment-decision.template.md) identifies the exact evidence and signature route. The selected-target engineering check is separate from the scoped matrix and should be inspected before any deployment decision.

## Human decisions and launch sequence

1. A physics/Lean reviewer inspects both exact challenges, library definitions, assumptions, formal-to-physical interpretation, source provenance and target digests above. They write a separate rationale per target. From the checkout, they can source `.state/runs/first-pilot/operator-env.sh`, invoke `pilot_role reviewer`, then record decisions with `phys review-target b3817784-8d0e-4961-9903-c3c0feef1b58 --target-digest 789a2c8a03a2028338200e44c97a8e337b0e57ed21971467f0a308db6d7946b4 --rationale-file PATH_TO_FIRST_WRITTEN_RATIONALE --idempotency-key first-pilot-v2-projection-review` and `phys review-target 215b5024-4285-4aa4-baed-05cf37363291 --target-digest 29911b3b68ad42081eb7bb8ba3f6290f4be2efa4d7243b3cc71a4199f543e54d --rationale-file PATH_TO_SECOND_WRITTEN_RATIONALE --idempotency-key first-pilot-v2-purity-review`. No approval has been recorded.
2. An authorized deployment reviewer inspects the exact scope, JSON review packet, runtime provenance, selected-target engineering report, gaps and proposed registry. They record an explicit, signed approve/decline decision in a **new** file using the template above. Only a positive decision permits the operator to copy the inspected proposed registry to an active operator-owned file and configure `PHYSHARNESS_VERIFICATION_REGISTRY` for the pilot; the proposal itself is not authority. The operator confirms applicable `gpt-6-sol` rates, loads the recorded price setting and supplies `OPENAI_API_KEY` privately from the designated operator key source. The dedicated image must be available to the selected Docker endpoint.
3. The user accepts the proposed **maximum $10 for the pair** before paid launch. Run `phys check-run` for each experiment in the isolated DB/environment and resolve every reported blocker. Run the first with the bounded supervisor; inspect its candidate and independent-kernel receipt. Only then run the second and audit whether the first accepted source was retrieved and genuinely incorporated. Failed or blocked first proof means there is no verified lemma-reuse claim to test.

The saved [first key-loaded preflight](../.state/runs/first-pilot/dephase-projection.v2.key-loaded.preflight.json) and [second key-loaded preflight](../.state/runs/first-pilot/dephase-purity-loss.v2.key-loaded.preflight.json) each return only `TARGET_REVIEW_REQUIRED` and `VERIFIER_REQUIRED`. The key itself was never copied into these reports. There is no live model result, scientific approval or proof receipt.
