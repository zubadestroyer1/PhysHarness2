# Four-arm physics pilot — 2026-09-24

The authorized test completed all four runs. Both physics targets were proved in both sharing configurations. Nine candidate submissions received exact-target, independent-kernel verification receipts. There were no observed model/worker crashes, incomplete responses, output-cap hits, uncertain charges, or unresolved reservations. The conservative model-cost total, including the access/schema probe, was **$3.658018 against $100 authorized**. This is an accounting upper estimate, not an invoice or a valuation of local compute/development time.

The important negative result is that these targets were **too quick to qualify sustained collaboration or long-horizon reasoning**. Their first accepted proofs arrived in 67–93 seconds. Enabling communication did not cause either communicating pair to exchange messages or delegate work. This trial does not establish that collaboration improves solving, that compaction preserves long proofs, or that larger swarms scale successfully.

## Preparation and engineering changes

GPT-6 Sol subagents implemented the bounded changes; the root assistant planned, reviewed the statements, audited code and evidence, and controlled launch. Independent work on capacity, preflight/launch tooling, and budget behavior ran in parallel. The four live experimental arms ran sequentially to retain one qualified two-worker VM envelope; each arm allowed two workers simultaneously.

- Local Docker admission now supports explicitly configured concurrent workbenches with atomic admission, stable host locking, policy labels, and instance-specific command locks. Two proof workers actually ran concurrently with verification during qualification; a third worker was rejected at the two-worker limit.
- Preflight compares requested concurrency with provider capacity, pinned images and VM resource requirements. The dedicated VM was raised to 16 GiB and 8 CPUs. Each worker retained its 2 GiB limit and isolation; the verifier retained its separate allowance.
- Resource admission waits for confirmed sibling reservations when total remaining dollars suffice. Actual overages remain recorded and block new allocations for reconciliation. This does not promise that an external provider can never incur an overrun.
- Launch is one-shot, validates all four exact experiments and their aggregate envelope, retains private tracebacks/results, and exposes safe progress records. No model credential or acceptance authority is provided to generated scientific code.
- Runtime settings were 256,000 active-context tokens, 64,000 output tokens per response, compaction threshold 184,000, and **no cumulative experiment token ceiling**. A 24-hour deadline, 1,000 native-session turns with existing continuation support, and 128-task/verifier supervisor bounds remained explicit safeguards. None stopped these runs.
- Full-context cost reservation is deliberately conservative: a future run near exhaustion can leave up to $1.28 unusable for a new full-capacity response. This was not a limiting factor here.

## Target review and test honesty

The root assistant rejected the earlier short Bell-state conjunction and selected stronger, precisely stated known results:

1. **Quantum dephasing:** for arbitrary finite matrix dimension, show that the purity removed by deleting off-diagonal entries equals the sum of squared off-diagonal magnitudes, and is nonnegative.
2. **Damped oscillator:** under explicit positive mass/stiffness, nonnegative damping, and global differential equations, prove energy is nonincreasing and derive bounds for both velocity and displacement.

The exact targets, sanity cases and withheld reference checks are recorded in `target-design.md` and `assistant-target-reviews.json`. Review was explicitly delegated to the assistant by the user; it is **not independent human expert review, a novelty judgment, or publication approval**. The reference solutions remained outside worker access. Workers had pinned installed libraries and no network access; known-result or pretraining contamination cannot be excluded. These are reproduction tests, not open-problem discovery benchmarks.

Both targets required several mathematical steps in the withheld references. The live outcomes nevertheless show that they were not difficult enough for the intended long-horizon behavioral test. That selection limitation should guide the next benchmark, rather than interpreting quick success as evidence of hard-problem readiness.

## Observed results

Each arm used GPT-6 Sol with high reasoning, two starting agents, the same pinned environment and a $24.95 shared envelope. Communication was enabled only in the collaborating arms. One access/schema probe had a separate $0.20 allowance and incurred a conservative $0.006090.

| Arm | Accepted candidates | First verified proof | Settled upper cost at first proof | Whole-arm upper cost | Delegated tasks |
|---|---:|---:|---:|---:|---:|
| Quantum, independent | 3 | 81.84 s | $0.560625 | $1.710032 | 1 |
| Quantum, collaborating | 2 | 93.00 s | $0.736272 | $0.940908 | 0 |
| Classical, independent | 2 | 83.95 s | $0.469365 | $0.549200 | 0 |
| Classical, collaborating | 2 | 67.29 s | $0.309111 | $0.451788 | 0 |

First-proof timing uses the canonical `verification.verified` event, not receipt creation or a model's success claim. Costs at that event count already settled calls; concurrent in-flight work can settle afterward. Several accepted candidates prove the same target and are not separate scientific discoveries. There is only one observation per cell, with possible warm-cache and ordering effects; no causal policy ranking is justified.

Complete-arm durations to the final task completion were 238.70 seconds (quantum independent), 124.93 seconds (quantum collaborating), 115.53 seconds (classical independent), and 102.14 seconds (classical collaborating). These are distinct from time to first accepted proof.

The four arms consumed 114 settled model responses: 1,319,519 input tokens and 35,310 output tokens. Input counts include repeated/cached context, not that many distinct mathematical tokens. All paid responses were reconciled against immutable runtime usage. Per-response and native-history cap-hit counts were zero. Compactions and cross-session handoffs were zero. Completed retrieval calls were 31, including rejected source-read attempts; this is not a retrieval success rate.

All nine receipts specify independent-kernel assurance and only the allowed logical axioms `propext`, `Quot.sound`, and `Classical.choice`. Candidate bytes, target revision/digest, reviewed statement, environment and review bindings are checked in the final evaluator. Lean/kernel acceptance does not by itself establish the physical meaning or novelty of a theorem.

## Faults and inefficiencies found

1. **Source-search/read mismatch remains to fix.** Ten `lookup_library_source` calls returned `UNSAFE_PATH`. Six reused exact absolute source paths returned by search, while lookup accepts only `mathlib/…` or `physlib/…`. This is an interface defect, not a mathematical failure. Source lookup should consume a canonical, bounded identifier produced by search, with round-trip tests and traversal rejection. The agents could still inspect declarations and run Lean. See `source-lookup-audit.md` for attribution and the proposed repair.
2. **Detached helper used the wrong return tool.** One `RETURN_RESULT_SCOPE` rejection was correct: the helper was detached and had no parent return channel. A separate independent-arm peer-message attempt was correctly rejected by `SHARING_POLICY`. Clearer tool affordances would reduce these wasted calls.
3. **Extra work continued after the first proof.** Quantum independent incurred another $1.149407 in conservative settled cost after its first accepted receipt. Other roots and a detached helper completed and produced additional valid receipts. This was authorized finite work, not an observed runaway loop. A configurable first-solution stop/drain policy would avoid some cost in success-only evaluations while allowing continued research when desired.
4. **Live delegation counter missed a child.** The status helper used a nonexistent field. After all runs completed, it was corrected to count `delegated_from_task_id` or `reply_to_parent_task_id`, with a regression test. Canonical records were correct throughout. The final evaluation uses those canonical records; the reporting correction was not part of the frozen live experiment.

No production source was changed during the live comparison or its analysis. The launch manifest is preserved, with exact original launcher source archived as `pilot_ops.launch.py.txt`. The status-helper correction is the sole post-run difference among manifest-listed files. Evaluation/report files were added afterward.

## Validation and evidence

- Frozen prelaunch full Python suite: **1,080 passed, seven explicit opt-in skips**, 21 upstream warnings. The seven skipped checks were covered by separate PostgreSQL and real-VM runs: 30 and 14 passes respectively. These overlapping follow-up suites are not added as unique tests.
- Fresh verifier packet: ten mechanical checks satisfied, 24 expected core/library kernel outcomes, 16 boundary attack checks, and eight expected outcomes for the two new targets and invalid controls across kernel modes. Qualification is for the explicitly reviewed private pilot; the packet does not claim production/fleet approval.
- Real capacity qualification: two concurrent workbenches, third-worker rejection, simultaneous verification, cancellation/replacement, no observed OOM, and no remaining containers. A process-crash orphan was identified by its journal label and explicitly reconciled; universal automatic orphan recovery is not claimed.
- Post-run reporting regression: eight helper tests passed. Four final evaluator tests also passed (12 combined reporting/evaluation tests); Ruff and `git diff --check` passed. The root reran the final read-only evaluator successfully and independently checked all nine receipt bindings/axiom lists. Results are in `output.json`.
- Four private exports passed artifact integrity checks (459, 179, 283 and 199 unique artifacts by launch order). Export checking verifies stored bytes; it does not repeat kernel replay or grant publication approval. Live receipts already record the independent checks performed during the run.
- All four experiments were paused after completion, with zero active workers, outstanding reservations or uncertain operations. Docker had no remaining containers. Colima confirmed the dedicated `physharness-pilot` VM was **Stopped**, and the monitor was **PAUSED**.

Primary files: `output.json`, `export-integrity.json`, `shutdown.json`, `source-manifest.json`, `worker-qualification.json`, `final-preflights.json`, `OPERATOR_DECISIONS.md`, and the retained test logs. Native traces, proof bodies, credentials and full private exports remain in the private state directory. Nothing was pushed or published.

## Recommended next experiment

Fix the source-search/read round trip first. Then construct a difficulty ladder and calibrate direct single-agent attempts on a small development subset. Choose withheld problems that remain solvable in the pinned environment but require enough independent obligations or sustained reasoning to exercise collaboration; do not force collaboration merely to inflate delegation counts. Pre-register separate first-solution and continued-research stopping policies. Run multiple independent/collaborating observations at matched budgets and record actual messages, reused results, handoffs and compactions. Qualify continuation/recovery with dedicated controlled tests as well as natural long runs; a short proof cannot measure them.

Do not spend the remaining authorization merely to exhaust the budget. This four-arm protocol is finished; the next live protocol should be chosen explicitly from the evidence above.
