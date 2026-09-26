# Persistent swarm hardening

Approved scope: apply the four retrospective fix groups with GPT-6 Sol implementation and root design/audit. Preserve existing work; no commits, publishing, paid model runs, or new spending authority. Keep proof acceptance independent. This plan makes no new wave/fleet qualification claim.

## Design and implementation units

1. Coordination and research resilience: explicit FIFO within round-robin root scheduling; revision-checked queued objective amendment; fresh assignment context at lease; component ownership/evidence references without proof promotion; peer availability with honest delivery states; durable permission-scoped peer waits that release worker capacity; exact-target completion notification and bounded drain; bounded root continuation/replanning distinct from helper completion. Preserve resource and lease fences, sharing policies, idempotency and uncertain external outcomes. Optional strategy descriptions support diversity without prescribing mathematics.
2. Durable execution knowledge: content-addressed chunks and versioned small manifests for native checkpoints, retaining every existing safety checkpoint. Reconstruct and verify exact RuntimeCheckpoint state; support historical full snapshots, compaction, handoff, export and restoration. Fail loudly on missing/tampered chunks. Dependencies must remain private, retained and exportable. No delta chains requiring unbounded history traversal.
3. Efficient artifact transfer and reusable knowledge: bounded workspace file promotion to immutable artifact/candidate under live lease, exact byte hash and current target, using unchanged independent verification. Improve honest search diagnostics and test known-premise retrieval/reuse, incompatible assumptions/environment, discovery isolation and corrupted artifacts. Provide compact authorized accepted-result summaries rather than exposing private native state.
4. Integrated resilience verification: deterministic repeated compaction and fresh-session handoff with evidence/assumption preservation; scheduling and resume/crash/cancellation regressions; no mock evidence described as live qualification. Run focused checks, then full Python suite and relevant API contracts/lint. Use VM only if necessary for provider qualification, shut down afterwards.

## Work ownership

- Sol coordination implementer: research_network scheduling, coordination models/services, runner/executor lifecycle after CanonicalRuntimeStore, associated tests.
- Sol persistence implementer: new checkpoint encoding module, CanonicalRuntimeStore methods only within research_worker.py, checkpoint consumers/exports and associated tests. Coordinate shared file edits at method boundaries.
- Sol knowledge implementer: research.py, workspace_tools.py/workspaces.py, file promotion and retrieval services/tools/tests. Shared research_worker tool registrations only by agreed boundary.
- Root: specification, cross-interface review, independent test execution and final audit. Agents report exact changed paths, tests, limitations and red/green evidence. No extra agent spawning by implementers.

## Acceptance and audit gates

- Queue order does not depend on UUID, amendments fence against leases/revisions, and superseded work is explicit.
- Storage test demonstrates subquadratic retained payload growth for append-only histories, exact old/new restoration, crash and missing/tampered dependency rejection, privacy and complete export closure.
- File promotion cannot truncate silently, read outside workspace, cross branches or turn local compiler success into verified status; retry/uncertainty remains honest.
- Canonical verified evidence alone closes exact target; no helper final response, unrelated receipt or partial report can count as root proof. Continuations are bounded by configured envelope and explicit finite policy.
- Waiting releases capacity and wakes only on permitted evidence or timeout/cancellation. Failed recipient delivery is distinguishable from read/acknowledged.
- Scientific memory retains exact target assumptions and evidence status across repeated context transitions.
- Root audits integration and all new trust-boundary changes; regressions repaired and rechecked before delivery.

## Progress

Implemented; local suite 1,258 passed / 16 skipped, ruff clean. Results and outstanding limits are recorded in work/swarm-hardening-2026-09-25/DELIVERY.md.
