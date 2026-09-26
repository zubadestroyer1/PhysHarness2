# Live cooperative audit (read-only)

Observed the isolated cooperative attempt through canonical records and artifact
metadata. Times below are UTC on 2026-09-24. This note excludes model reasoning
transcripts, private reference material, credentials, and candidate proof source.

At the 23:10 snapshot, the two independent roots started at 23:08:50. Each launched
a detached helper by about 23:08:58, so all four workers were active concurrently;
a third detached helper queued at 23:09:05. This directly exercises the two spare
worker slots while both roots remain active. It does not by itself establish useful
collaboration.

The canonical idea exchange happened before any verification submission. Root A
messaged root B at 23:09:35 with a Lyapunov route. Helper A sent an explicit
constant/algebra approach to its root at 23:09:39 and a summary to the other root
at 23:09:43. Root B replied to root A at 23:09:46 that it was developing an
abstract scalar comparison while others worked on derivative/algebra steps.
Canonical delivery rows show the messages to root B acknowledged by 23:09:46,
and the messages to root A acknowledged by 23:10:00. No independent verification
request or receipt existed at that snapshot. These are attributed ideas, not
accepted proofs; their effect on a later submission remains to be assessed.

At the same snapshot there was no recorded task handoff or native compaction.
The attempt was running with four active workers, one queued task, no budget
uncertainty, and no verification receipts. Later status and scientific outcome
require a fresh read of the canonical attempt.

At 23:10:20, one root task was blocked and its native session marked uncertain.
The canonical failure artifact gives `UNSAFE_PATH`. The last native tool call was
`run_command` with `cwd="/work"`, although the tool contract says to use `cwd="."`
for the same directory. The provider rejected the path in `validate_command`
before Docker dispatch; the root workspace was then destroyed. The ledger still
reported zero uncertain billing operations. This is a tool argument mistake with
a disproportionate terminal effect on that root, not an OOM or a scientific
disproof. Four other tasks, including the other root and helpers, continued.

At 23:12:30, the blocked root's detached helper had completed; the other root
and two helpers were still running. There were 18 direct messages and nine
acknowledged delivery records. Several messages addressed to the blocked root
after 23:10:20 were not acknowledged; its last observed delivery acknowledgement
was at 23:10:00. The directory did not prevent sending to that unavailable peer,
so those messages should not be credited as received collaboration. The other
root did receive helper messages before any proof submission. There were still
zero verification requests or receipts.

Across the attempt at that snapshot, 61 workspace commands had completed: 32
exited zero, 28 exited one during development, and one shell command exited 127
because of a PATH error. All 61 reported zero OOM events. The early mathematical
messages and many Lean iterations show active work, but those counts do not
establish an accepted theorem or a specific scientific obstruction.

At 23:13:27, a different helper called `read_workspace_file` with an absolute
`/work/...` path. The provider requires a path relative to `/work`; this call
left its `read_range` workspace operation and zero-cost reservation marked
`reconciliation_required`/`uncertain`. The ledger's `uncertain_operations=1`
therefore refers to local workspace accounting, not an unresolved model charge.
The current `read_workspace_file` tool description does not state the relative
path rule. This is a second instance of the same path-contract confusion, with
a more serious lifecycle consequence because validation occurred after an
operation reservation. No live code or state was altered for this audit.

By 23:14:55 that helper's task had also become blocked. At the 23:15:50
snapshot, the ledger listed two uncertain local reservations: the zero-cost
`read_range` operation (zero workers) and its zero-cost held worker slot (one
worker). These are consequences of the same invalid path/lifecycle failure,
not two uncertain model charges. The other root and one helper were still
running; one helper had completed. There were 31 messages, 18 acknowledged
delivery records, no verification receipt, and no recorded handoff or native
compaction. Settled model spend was $13.914376 at that snapshot.

The exchange then produced more concrete components. A helper reported a
no-`sorry`, locally Lean-compiled source artifact for energy, cross, and
damping-potential derivatives to the surviving root at 23:15:39; its delivery
was acknowledged at 23:15:45. Another helper had reported a locally compiled
finite-sum `E/2 ≤ L ≤ 2E` comparison before it blocked. The surviving root
reported a locally compiled acceleration/cross identity at 23:16:47 and was
working to combine these pieces. The derivative artifact was manually copied
from a workspace file, so the final submitted bytes require their own check.
These helper reports are useful candidate lemmas, not independent target proof
receipts.

The surviving root continued with concrete local Lean checks and new source
artifacts. At 23:20:42 it delegated a fresh detached helper to attempt full
assembly from the shared pieces; this helper began running. The root's largest
observed native input at that point was about 112,000 tokens, below the
183,808-token compaction threshold. There was still no verification submission,
handoff, or native compaction. Cooperative spend reached $27.266722 by the
23:21:52 snapshot; the remaining new-pilot allowance after calibration was
about $23.263148 before any subsequent spending.

By 23:24:52, the new assembly helper and surviving root each reported local
Lean compilation of full-target *glue* using temporary axiom stubs. The root
identified two remaining stubs, for the Lyapunov derivative and finite
comparison, and planned to replace them with the earlier helper artifacts.
Compilation with axiom stubs is a useful interface check but is not a valid
proof or an independent receipt. The needed full source had not yet been
assembled and submitted. Cooperative spend was about $33.21, leaving about
$17.32 of the new $52 ceiling after calibration for a fresh attempt if this
faulted run were stopped then.

I checked actual transfer into the surviving root's workspace using canonical
`write_workspace_file` arguments and matching broker upload hashes. Its two
derivative files closely match the helper source artifacts and contain the
energy, cross, and forced Lyapunov derivative lemmas; separate local Lean runs
on those files exited zero. A third uploaded file contains the helper's finite
comparison lemma in a trimmed/rewritten form. These three uploaded files scan
free of `sorry`, `axiom`, and `admit`. This establishes real source copying and
adaptation, beyond message claims, but still does not establish a monolithic
target proof or independent verification.

The transfer check used the root's native `write_workspace_file` arguments,
computed each content SHA-256, and matched that digest to a completed broker
upload in the root's workspace. `deriv_part.lean` uploaded with digest prefix
`7e729f974ba4` and corresponds closely to helper artifact `9a8ba53f`;
`deriv_part2.lean` uploaded with `7b51860953de` and corresponds closely to
helper artifact `5ae560ea`. `finite_part.lean` uploaded with `5f79b090bee0`
and contains `lyap_finite_comparison` from helper artifact `7fa5b115` in a
shorter form. The root's next local run after each of these three uploads
exited zero. Lexical checks for holes/axioms and the local compiler exits are
separate observations; none substitutes for verification of the final combined
source.

The final submitted candidate was **independently verified**. The surviving
root queued verification at 23:29:38; canonical verification became `verified`
at 23:30:11 with `kernel_checked` and `independent_kernel` assurance. The
26,418-byte submitted source has SHA-256 prefix `693bc59c88b1`, contains the
exact reviewed `physics_target`, and has no lexical `sorry`, `axiom`, or
`admit`. The accepted source contains every substantive normalized line of
derivative helper artifacts `9a8ba53f` (94/94 lines) and `5ae560ea` (30/30
lines), plus the needed finite-comparison lemma from artifact `7fa5b115`.
This establishes actual reuse in the accepted proof. It does not establish
the counterfactual claim that the root could not have proved the target alone.

The accepted proof followed one **actual provider-native compaction**. At
23:28:08, the root's native checkpoint held 113 responses in epoch 0. By
23:28:09 it recorded provider compaction count one, an archived prior epoch,
a non-null compaction ID, and zero current-epoch responses. The root then
continued and submitted the accepted proof in epoch 1. Its terminal session
records 119 total turns and six current-epoch responses. No task handoff was
observed, so this trial tests native compaction continuity but not repeated
handoff recovery.

The experiment's workflow gate remained **blocked** after the scientific
acceptance: two tasks were blocked by the earlier workspace path faults, one
native session remained uncertain, and one local workspace required
reconciliation. The supervisor status was `ATTEMPT_NOT_COMPLETED`, even though
the canonical verification record was `verified`. The final cooperative
ledger showed $41.733125 settled spend, zero reserved model cost or tokens,
and two zero-dollar uncertain local reservations (read operation and held
worker slot). Together with $1.47013 calibration spend, this new pilot used
$43.203255 of its $52 allowance, leaving $8.796745 before operator recovery.
The remaining uncertainty is local lifecycle accounting, not an unresolved
model invoice. All 136 completed workspace runs reported zero OOM events.
There were 60 direct messages and 30 acknowledged delivery batches overall;
those counts include late messages to blocked peers, so they are not a measure
of useful exchange by themselves.

After the live run, the operator preserved the blocked helper workspace archive,
recorded an observation naming all six canonical workspace/container identities
and confirming their absence on the dedicated Docker host, then used the scoped
retirement API for the failed `read_range` operation. The resulting canonical
ledger has **zero uncertain operations, zero active workers, zero reserved cost,
and zero reserved tokens**; the two zero-cost read/worker-slot reservations were
settled once. Settled model spend remains **$41.733125**, with no inferred refund.
The helper task is `failed` and its already completed native session remains
completed. The original root's pre-dispatch failure remains a distinct blocked
task and uncertain native session, explicitly abandoned for this retry; the
reconciliation did not relabel it as successful or resume it.

The operator's private export passed content-hash integrity validation for
**2,676 unique artifacts**. Its audit summary reconciles **280 settled native
responses**, 16,138,254 input tokens and 138,742 output tokens to the ledger.
These checks establish export integrity and usage accounting, not independent
kernel replay or publication approval. The accepted verification receipt and
source-reuse evidence described above remain scientific evidence separate from
the blocked overall workflow status. The retry retirement review binds the
two exact abandoned calls, their checkpoint identities, the operator absence
observation, and the prior manifest/source freeze; a separate decision approves
only that exact retirement for fresh isolated retry preparation.
