# Fresh cooperative retry: live read-only audit

This note records canonical metadata from the isolated retry attempt. It does
not include model transcripts, source, credentials, or private proof content.
The operator controls the live run and all provider/VM actions.

At the first read-only snapshot shortly after 23:52 UTC, the fresh experiment
had two active roots and two active detached helpers; two further detached
helpers were queued. All four native sessions were running, and two local
workspaces were ready. Six direct messages already existed, including one
helper addressing both its parent root and the other opted-in root. One
discussion delivery had been acknowledged. There was no verification record,
handoff, terminal session, or recorded workspace failure at this snapshot.
The latest status file showed $0.057445 settled model spend, $2.56 reserved,
22,051 spent tokens, 640,000 reserved tokens, three active worker slots, and
zero uncertain operations. Pending workspace operations are ordinary while
in flight and do not by themselves indicate a fault.

The launch gate isolated this attempt in a fresh private database with an
$8.796745 ceiling after exact prior settled spend. Scientific success requires
an actual accepted verification receipt; task completion or a local Lean exit
alone will not establish it.

At 23:54:27 UTC, all four worker slots held two roots and two helpers, with
two further helpers queued. There were eight direct messages and four
acknowledged delivery events, including helper-to-root, root-to-helper, and
root-to-root routes. Four local workspaces were ready. Canonical operations
showed 54 completed workspace runs and 41 completed uploads, with no failed
or reconciliation-required broker operation. Of the runs, 28 exited zero and
26 exited one; those nonzero local commands may be ordinary Lean development
errors, and are not evidence of provider failure. No target verification or
handoff was recorded. The ledger showed $3.335332 settled, $5.12 reserved,
and zero uncertain operations. This snapshot does not establish proof progress
from command counts alone.

At 23:56:54 UTC the canonical ceiling was still $8.796745. Settled cost was
$6.827092 with $1.28 reserved, leaving $0.689653 unreserved; four workers
were active, no receipt existed, and the ledger still had zero uncertainty.
The user subsequently authorized the operator to raise the ceiling for this
current retry to $100 total for this retry. That authorization does not itself
alter the canonical budget; later snapshots must distinguish its actual
operator-applied amendment from the older ceiling. The operator was alerted
that the next standard model reservation might be blocked before amendment.

The operator applied the authorized amendment at 23:56:59 UTC. The canonical
experiment and budget ceiling changed from $8.796745 to **$100 for this retry**,
with experiment revision 2→3. The recorded before/after ledger preserves
$6.94434 settled spend, $1.28 reserved cost, four active workers, 2,622,531
spent tokens, 320,000 reserved tokens, and zero uncertain operations. The
original launch manifest remains a historical record of the earlier ceiling;
the live canonical budget and its explicit operator event govern subsequent
reservations. Earlier attempts remain separately accounted, not reset or
silently folded into this new authorization.

At 23:59:18 UTC, all four workers remained active with no uncertain ledger
operation; settled cost was $13.986053 and reservations $5.12 under the new
$100 ceiling. Canonical messages had grown to at least 23, with helper→root,
root→helper, and root→root routes; 16 messages then attached artifacts and
there were 16 delivery acknowledgments. The broker had 178 completed workspace
operations and one ordinary pending operation, with no failed or
reconciliation-required operation. Four completed local commands exited 127
because `lake` was unavailable under `bash -lc` login-shell PATH semantics.
Direct `lake --offline` commands and explicit `/opt/lean/bin/lake` commands
succeeded in the same workspaces, so this was a shell invocation issue rather
than a missing Lean tool or provider uncertainty; agents continued
subsequent local runs. No verification receipt or continuation link had yet
appeared, and there was no native archive artifact to establish compaction.

A later single-transaction count reconciled 28 direct messages exactly:
12 helper→root, eight root→helper, and eight root→root. The earlier message
total and route breakdown were queried separately while messages were being
created, so no category sum is inferred from that non-atomic snapshot.

At 00:02:32 UTC, one detached helper had completed with one canonical evidence
artifact; a queued helper had started. Two roots and two helpers remained
active, with one further helper queued. There were 234 completed workspace
operations, four ready workspaces and one destroyed workspace, with no failed
operation or ledger uncertainty. At least 35 direct messages and 25
acknowledged deliveries existed. Settled spend was $24.793496 with $3.84
reserved under the live $100 ceiling. There was still no verification receipt,
handoff link, or native archive artifact. The completed helper's evidence is
an intermediate contribution, not a proof of the target.

At 00:03:58 UTC, two detached helpers had completed with one evidence artifact
each. Two roots and two other helpers remained active. The ledger had
$31.13277 settled and $3.84 reserved, with zero uncertainty; there were
45 direct messages and 36 acknowledged deliveries, but still no verification
receipt, handoff link, or native archive.

There is concrete source-transfer evidence. Helper task `30a79ff3` created a
no-hole `lean_source` artifact `d46bf931` at 23:53:40 and attached it to a
message for root `bf2a1a5d` at 23:53:45. The root's canonical
`write_workspace_file` content matched a completed broker upload of
`scratch/DerivativePieces.lean` at 00:02:27. That uploaded content contains
26 of the helper artifact's 28 substantive normalized lines. Three later
local runs referencing that file exited zero (00:03:09, 00:03:20, 00:03:46).
This establishes actual helper-source reuse and local compilation, without
claiming it completed the target or was independently accepted.

At 00:07:36 UTC, a root submitted the retry's first candidate to independent
verification. The canonical receipt was still `queued` at the 00:08:04
snapshot, so this is a submission, not acceptance. Three helpers had
completed, while both roots and one helper remained active. The ledger showed
$42.367154 settled, no reserved model cost at that instant, and zero
uncertain operations; 298 workspace operations were complete. There were
55 direct messages and 44 acknowledged deliveries, with no handoff or native
compaction yet recorded.

The first submitted candidate **was independently verified** at
00:08:14.375 UTC, 17 minutes 2.623 seconds after the canonical experiment
start at 23:51:11.752. Receipt `9c834332` has status `verified`, code
`kernel_checked`, assurance `independent_kernel`, and `publication=true` for
that verifier tier. The receipt's problem revision, approved review ID,
target digest, formal challenge SHA-256, environment digest, candidate digest,
and `physics_target` selector all match the fresh canonical problem and the
27,321-byte submitted artifact `a61e050f` (SHA-256 `d54ff7f2…`). The source
has one target theorem declaration and no lexical `sorry`, `axiom`, or
`admit`; the independent receipt, rather than that lexical scan, is the
proof-acceptance evidence. Its listed axioms are a policy upper bound, not a
measurement of the exact used-axiom closure. `publication=true` does not
signify expert publication approval.

The accepted candidate contains substantial exact normalized lines from
several earlier helper `lean_source` artifacts: `690fd188` 57/57,
`692601d3` 24/24, `80c9bc4e` 55/55, and `d46bf931` 27/28. These helper
artifacts were created and shared before candidate submission. Together with
the earlier root upload and local compilation of `d46bf931` material, this
establishes actual collaboration in the accepted proof. It cannot establish
how the root would have performed without helpers.

The supervisor later completed cleanly. All six tasks and six native sessions
are `completed`; all six local workspaces are destroyed; all 315 workspace
operations are completed; the single receipt remains `verified`. The final
canonical ledger has $49.102475 settled spend under the live $100 ceiling,
zero reserved cost or tokens, zero active workers, and zero uncertain
operations. The operator paused the experiment after completion. All six
terminal native checkpoints verify and record zero provider compactions:
none has a compaction ID or positive compaction count, and there is no
`native_archive` artifact. There are zero continuation links. This retry
therefore demonstrates parallel helper reuse and an accepted proof, while
providing no live evidence about native compaction or repeated handoff
recovery. Private export and artifact-integrity audit are separate operator
steps and are not inferred from supervisor completion.

The operator subsequently exported the completed attempt. A separate
read-only `validate_export` check reports `artifact_integrity_checked` for
**3,246 unique artifacts**, with manifest SHA-256 prefix `81d1b150`.
The operator audit reconciles 338 settled native responses: 19,019,962 input
and 155,248 output tokens sum to the canonical 19,175,210 spent tokens.
It records six completed tasks, six completed sessions, 60 direct messages,
and 47 acknowledged delivery batches. Export integrity checks hashes and
accounting; it did not rerun the independent kernel or supply expert
publication approval. The live canonical verification receipt remains the
independent proof evidence.
