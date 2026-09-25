# Original comparison-5 incident (historical, recovered)

The original comparison-5 attempt ended as an operational failure. Both root branches produced independently kernel-checked proof receipts bound to the intended target, but a workspace export then failed. The runner reported `ATTEMPT_NOT_COMPLETED`; its result cannot be counted as a completed policy comparison. The detached helper never received a model session and was operator-aborted during recovery.

The export failure came from file ordering. The guest listing emitted root `solution.lean` before nested `scratch/Check.lean`, even though the archive requires paths in one global sorted order. Sorting each directory during `os.walk` was insufficient. The operator observed the container running, with `OOMKilled=false`, 2 GiB of memory, and zero `memory.events` counters. The workspace was archived under its verified SHA-256, then the exact container was removed. The archive's contents were not read for this note.

Recovery used the public API. The failed workspace is destroyed, both uncertain reservations are settled, active workers and reserved cost are zero, and the experiment is cancelled. The conservative settled ledger retains **$5.131777** and 1,945,898 tokens. This is recorded spend, not a provider invoice estimate. The other root task completed; the export-affected root task and the unstarted helper are now failed in canonical records.

Two private messages went from the completed root branch to the detached helper branch, at 09:58:52 and 10:01:29 UTC. No message content was read. The database contains two discussion-reader records and no discussion posts or deliveries. This one failed attempt supports no general claim about policy efficiency. The previous comparison-4 result remains historical and verified, while fresh final trials use the repaired code.

I reviewed the sorting repair at `src/physharness/execution/local_docker.py:210`: the guest globally sorts the accumulated relative paths for both listing modes before export consumes them. The regression test runs the actual guest script on a temporary root containing the same root-file/nested-file shape, round-trips a canonical archive, and rejects reversed order. The focused test passed (`1 passed, 9 deselected`). This audit did not run a live VM export; the team's broader qualification covers that separately.

The companion JSON contains receipt IDs, task IDs, timestamps, ledger state, and evidence provenance without proof bodies.
