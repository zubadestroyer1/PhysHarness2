# Next collaboration test: preparation and readiness audit

**Preparation completed; the proposed two-worker parallel test is not ready to launch.**
The real local provider rejects a second simultaneous workbench with `WORKSPACE_CAPACITY`.
The ordinary launch preflight does not currently check requested team size against that
physical limit. This is a material correction to the earlier general readiness answer:
the tested single-workbench loop and mocked multi-agent wiring do not qualify two
simultaneous Lean workers.

No runtime code was changed in this preparation. All 157 source hashes from the previous
implementation snapshot still match. No paid research model calls were made; all four
new experiments remain `created`, with no sessions, tasks or verification receipts.
The dedicated VM was stopped after testing.

## Selected problems

| Target | Why it is useful now | Limitation |
|---|---|---|
| Bell-state entanglement and maximally mixed local state | Combines a joint-state property with a normalized partial-trace calculation. Separate subresults make collaboration possible. | Entanglement has a direct library theorem, and finite-matrix automation may make the rest easy. |
| Damped oscillator energy is nonincreasing | Requires deriving an energy derivative from the equations of motion and turning its sign into a global statement. Extends the previous quantum-only live tests into classical analysis. | Conditional on a global differentiable solution; does not establish existence, strict decay or convergence. |

These are known-result, step-up calibration candidates. Their stretch labels are author
estimates, not measured model difficulty. The previous purity-loss task was also labeled
stretch but was solved cheaply, so the label alone is not evidence of a hard test.
Neither new problem is open. Library reuse is permitted and documented. Do not impose
artificial role assignments or force delegation if the model finds a short proof.

The [review packet](REVIEW.md) contains the exact statements, assumptions, source hashes,
canonical problem identities and disclosed shortcuts. Human review is pending; passing
the reference proof does not approve the intended physics. The Bell family retains its
original holdout label; using it in this pilot must be recorded before future training
or claims of untouched holdout evaluation. Published tasks may already be familiar to models.

## Prepared experiment

The [proposal](experiment-proposal.json) specifies four runs: each problem with independent
attempts and with a communicating team. Each run proposes a $25 shared envelope, two root
agents, up to two active workers, up to 16 tasks, and a two-hour experiment deadline. The
maximum proposed allocation is $100, not a spend already made or a reuse of the previous
two-trial authorization. Native research compaction is retained; there is no cumulative
token cap. Session turn/output limits and the dollar/time envelopes still apply.

All arms use the same recorded GPT-6 Sol configuration, installed libraries and acceptance
policy. Automatic synthesis is initially disabled to avoid adding another experimental
factor. The comparison assesses the combined independent-versus-collaborating system,
not the isolated causal effect of any individual communication feature. One observation
per cell is calibration, not a reliable policy ranking.

Primary observations are an independently accepted exact-target proof, time to its first
receipt, and cost. Also retain total spending, work after first acceptance, failures,
recruitment, source retrieval, message exchange, lemma reuse, compaction/handoff use and
memory pressure. Agent/task completion is not proof acceptance. A short direct solution
is a valid success but leaves collaboration and long-horizon effectiveness untested.

Run arms sequentially and retain failures without granting a new budget on restart.
Use fresh experiment workspaces and no prior transcripts, reference proofs or results
from another arm. The clean worker exports are [quantum-target.json](quantum-target.json)
and [classical-target.json](classical-target.json). Evaluator proofs remain only under
the private, git-ignored preparation directory. Normal installed-library knowledge is
available; pretraining contamination cannot be excluded.

## Completed checks

- **46 fresh pipeline tests passed**, including launch controls, workbench admission,
  communication, joined delegation and recovery; [log](pipeline-tests.log).
- **8/8 expected target outcomes**: both references accepted in Lean and the independent
  kernel, with matching proof-hole candidates rejected in both modes;
  [hash-bound summary](target-checks.json). These are evaluator controls, not agent solutions.
- Canonical bundles for the two exact problem revisions and the proposed verifier registry
  passed structural validation. The current ten-check mechanical verifier packet was
  reproduced against unchanged source; [bundle validation](bundle-validation.json).
- The actual VM accepted one workbench and rejected the second as expected. Both were
  cleaned up; [physical-capacity.json](physical-capacity.json).
- All four canonical preflights were run with the proposed registry and real workbench
  probe. They correctly held for target review and for a key not loaded into this
  preparation process; [canonical-preflights.json](canonical-preflights.json). This does
  not establish that the saved key is missing or invalid. No external authentication,
  billing, current-price or new-tool-schema API probe was performed in this preparation.
- Four experiments remain unstarted. Reviewer/operator identities were prepared with
  private file permissions. No review was fabricated. Worker exports exclude reference
  fields; [preparation-invariants.json](preparation-invariants.json).
- The VM is **Stopped**, with zero active test containers before shutdown;
  [shutdown.json](shutdown.json).

The first registry preparation attempt correctly rejected serialized Path strings passed
to the strict Python validator. Using the existing JSON registry input contract fixed the
operator preparation; no runtime patch or validation bypass was introduced.

## Required before the parallel launch

1. **Qualify two physical workbenches.** Add a bounded explicit capacity setting to the
   local provider and preserve atomic admission across processes. Fail before paid work
   if the requested team cannot fit. The current limit of one must remain the default
   for existing configurations.
2. **Check combined memory requirements.** Two 2 GiB workbenches plus an 8 GiB verifier
   consume the entire present 12 GiB VM allocation before system overhead. A proposed
   16 GiB VM provides headroom on this observed 64 GiB host, but needs a measured concurrent
   workbench-plus-verifier test. Increasing RAM alone does not remove the code limit.
3. **Bind launch preflight to capacity.** Compare requested runner concurrency with the
   provider limit and available VM resources before model calls. Test that two are admitted,
   a third is refused, cancellation releases capacity, crashes retain uncertainty, and
   stale workers cannot release another worker's allocation. Recheck the actual CLI path.
4. **Review the new targets.** Use [REVIEW.md](REVIEW.md) and the separately issued reviewer
   identity. Record decisions against the displayed canonical hashes. The prior approvals
   for the dephasing problems do not cover these different statements.
5. **Complete launch inputs.** Load the existing API key privately, revalidate the recorded
   prices/model access and full tool schemas, approve the intended new run allocation, and
   activate the exact registry only for the approved local boundary. Refresh affected
   environment evidence after capacity changes.

Use the general `phys run-team`/`ResearchTeamRunner` path against the new private database.
The historical `research-effectiveness/.../pilot_ops.py` helper is hard-coded to the old
quantum target IDs and is not the launcher for these problems. Use one controller for
this database; do not also drain it with a separate Temporal worker during the finite run.
Configure shared task limits before starting execution. Attach the monitor at launch,
keep private transcripts out of public status, and shut the VM down after cleanup.

A single-active-worker, time-sliced collaboration pilot is an alternative after target
review and normal launch checks, but must be labeled accordingly. It would not validate
parallel proof-workbench execution. The recommended next engineering step is the bounded
capacity/preflight patch above, followed by the proposed parallel pilot.

Private state: `.state/collaboration-pilot-preparation-2026-09-23/` contains the database,
artifacts, plans, reference fixtures, bundles and inactive registry. Public safe metadata
is in [prepared-records.json](prepared-records.json) and [READINESS.json](READINESS.json).
