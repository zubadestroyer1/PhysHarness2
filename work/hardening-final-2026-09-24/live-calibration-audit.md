# Live calibration audit (read-only)

Observed the isolated calibration database, artifact metadata, final research output,
and status snapshot after completion on 2026-09-24. This note contains no private
reference proof, model reasoning transcript, credentials, or candidate source.

The single root task and native session completed after about 4 minutes 35 seconds.
The model's final statement explicitly said the reviewed Lean theorem remained
**unverified**: it had an informal Lyapunov argument and a locally checked auxiliary
scalar lemma, but had not submitted a complete proof or received an independent
verification receipt. It identified finite-sum differentiation and the Lyapunov
inequalities as remaining formalization work. Task completion is therefore a
terminal workflow status, not scientific acceptance. Canonical records contain zero
verification receipts and no pending verification request.

The run settled at **$1.47013**, with zero reserved cost, active workers, or uncertain
operations. Its 23 native responses and 22 completed tool calls included 18 workspace
commands and eight Lean-source uploads. Ten commands exited zero; seven exited one
while iterating Lean work. One `bash -lc` command exited 127 because that login shell
could not find `lake`; direct `lake` commands in the same workspace worked, so this
isolated command error does not explain the early stop. All 18 command diagnostics
reported zero OOM events. The workspace was exported and destroyed, and the task
and native session reached completed status.

There is no evidence of native compaction: the 23 settled responses have no
compaction output item, and the largest response input was 37,885 tokens, below the
configured 183,808-token compaction threshold. The cumulative input of 537,030
tokens is billing across responses, not a single context length. This run does not
exercise continuation recovery or helper collaboration; calibration allowed one
worker and sharing `none`.

The model chose a partial research report despite substantial unused time and budget.
The seeded objective, “Investigate the reviewed target independently,” permits such
an outcome and does not demand a finished formal proof. A cooperative-only change to
that objective would confound the paired comparison. Keep the two arms' frozen
objective identical and report this early-stop limitation; a later proof-deliverable
prompt should be evaluated in both arms as a separate, matched experiment.
