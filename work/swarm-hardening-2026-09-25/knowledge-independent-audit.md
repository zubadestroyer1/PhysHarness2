# Independent read-only audit: knowledge and file promotion

Compared the live implementation with the saved baseline under `work/swarm-hardening-2026-09-25/baseline/`. Reviewed `research.py`, `workspace_tools.py`, `workspaces.py`, local Docker and E2B capture helpers, and the new focused tests. No source edits or paid/provider calls were made by this review.

## Finding: lexical diagnostics disclose an ineligible cross-experiment claim (P2)

`search_knowledge` in `src/physharness/research.py` adds a lexical match to `ranked` after checking only that the origin experiment has a sharing mode other than `none` (roughly lines 207–220). `_applicable_knowledge` later requires `independent_kernel` assurance for cross-experiment reuse. If that later check rejects the claim, the final `reason_code` still uses the nonempty `ranked` list and returns `ineligible_or_unavailable_candidate`. A consumer agent can compare this with `empty_accessible_corpus` and learn that a claim matching its query exists, despite being unable to read or reuse it.

Reproduced with a temporary SQLite service fixture: a verified origin claim had `sharing="verified"` and `assurance="kernel"`; a consumer agent searched `Nat`. With that claim, the result was `items=[]`, `reason_code="ineligible_or_unavailable_candidate"`. After deleting the claim, the same search returned `items=[]`, `reason_code="empty_accessible_corpus"`. This is a metadata existence leak; no proof bytes or native state were returned. Suggested fix: compute diagnostics from claims that have passed the same disclosure and acceptance gates as results, or use a common no-match reason for ineligible cross-experiment candidates. Add a regression comparing with/without an independently ineligible matching claim.

## Other boundaries reviewed

- Promotion validates agent experiment and branch in `WorkspaceTools`, then broker `_guard` checks active task, lease/fence, execution identity and worker slot before dispatch and before canonical artifact publication. The target digest is checked both before capture and in the publication transaction.
- Local Docker's guest helper opens a regular, single-link file with `O_NOFOLLOW`, rejects size above 4 MB and checks metadata around the read; broker checks the caller supplied whole-file SHA-256. The Docker subprocess reader raises on output beyond its bound, so a large result cannot silently truncate into an artifact.
- E2B's helper reads bounded slices from a regular, single-link file with `O_NOFOLLOW`, reports whole-file digest and size on each slice; the host checks consistency, exact lengths and final digest. This is more expensive than a one-pass capture but bounded at 4 MB.
- Promotion archives exact bytes as a `lean_source` artifact with `proof_status="not_accepted"`; `submit_workspace_candidate` queues the existing verifier. It does not promote local compiler diagnostics into accepted proof status.
- The knowledge path checks current review, exact claim statement/assumptions, receipt bindings, environment and candidate content before releasing a bundle/summary. Source bytes are read only after metadata eligibility; the 1,000 irrelevant-claim test bounds SQL queries and proof reads for that case. Queries matching a large fraction of the project may still require many metadata reads; this is a scaling limit, not a demonstrated trust violation.

This audit did not run the opt-in Docker or E2B integration tests and does not qualify a live provider or checker.
