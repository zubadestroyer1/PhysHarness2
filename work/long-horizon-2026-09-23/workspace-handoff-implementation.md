# Workspace handoff implementation report

Implemented in `orchestration/workspace_tools.py` and `orchestration/workspaces.py`, with `tests/test_workspace_handoff.py`. No VM or paid provider calls were made.

`WorkspaceTools.prepare_handoff(operation_id)` returns `None` when no VM was provisioned. Otherwise it archives bounded regular workspace files through the existing fenced broker export and returns a small ticket: artifact ID and SHA256, source execution ID, exact environment and qualification digests, template ID, and workspace policy digest. The controller must bind this ticket to the canonical continuation before closing the source VM.

`WorkspaceTools.restore_handoff(ticket, operation_id)` validates ticket shape and exact configured policy, verifies the artifact belongs to the same task/branch/experiment and source VM with matching hash, then allocates a new VM under the successor lease and shared resource envelope. It rejects source execution ID reuse and journals the restore as an idempotent broker operation. The workspace record retains restored artifact/hash/source metadata. The archived bytes are validated before any new VM allocation; provider restore ambiguity retains the existing reconciliation behavior.

Verification: workspace handoff/service/worker VM suite **43 passed**; focused Ruff and `git diff --check` passed. The new fake-provider test exports a Lean file from one VM, closes it, acquires a new fenced task lease, restores into a distinct execution ID, and re-exports byte-identical content. A policy mismatch test proves no VM allocation occurs.

Integration dependency: controller owner must call export before close, persist the ticket in the continuation, and call restore before successor model generation. Workspace archives contain regular files within the configured upload/checkpoint root; they are not a full VM memory snapshot.
