# Sharing enforcement implementation report

Implemented only the assigned paths: `src/physharness/domain.py`, `src/physharness/service.py`, `src/physharness/collaboration.py`, `src/physharness/orchestration/research_worker.py`, `tests/test_sharing.py`, `docs/COLLABORATION.md`, and this report. No commits, child agents, model calls, or cloud operations.

## Delivered behavior

- Added trusted identity `branch_id` and explicit `agent_orchestrator` authority. Workers receive branch-scoped identities. Legacy experiment-only agents see their own authored records and trusted inputs; explicit orchestrators may control topology without gaining private artifact access.
- Added canonical artifact `branch_id`, explicit trusted-input designation, server attribution, and validated task/source linkage for records including verification receipts, accepted claims, sessions, sources, and programs. Worker provenance cannot forge ownership or promote an input to trusted status.
- Applied sharing policy centrally to direct metadata access, content bytes, paginated listings, restart briefs, and event visibility. Hidden rows are filtered before pagination and scanned in bounded chunks. `none` denies other branches' results; `verified` requires exact reviewed-target canonical independent-kernel evidence; `ideas` permits attributed research content.
- Enforced sender ownership and cross-branch message policy. Free text requires `ideas`, even if an attachment is verified. Verification and publication status remain separate and unchanged.
- Kept native sessions/checkpoints, branch checkpoints, runtime events, and failure artifacts private across branches even with `ideas`.
- Preserved parent delegation into fresh child identities within the same experiment envelope, without granting parents access to child result artifacts or allowing foreign branch impersonation.
- Included new branch/orchestrator authority in idempotency fingerprints.

## Additional reproduced bypasses fixed

1. A controller-created branch checkpoint previously embedded an unrestricted restart brief, then made that history available through the destination branch's checkpoint. A red regression demonstrated another branch's artifact ID inside the checkpoint. Checkpoint generation now constructs a branch-scoped reader and validates native artifact visibility in that scope.
2. `CanonicalRuntimeStore.load` previously accepted any native session ID from the experiment while running under its operator actor. A red regression loaded another task's session. Native loads now require the exact task; saves reject an existing session assigned to a different task or experiment.

## Integration coordination

Parent was notified before implementation to apply service visibility to same-experiment claims accessed by `ResearchMixin.search_knowledge`'s privileged broker, and to propagate any branch/orchestrator fields through trusted API identity construction. Parent confirmed ownership of these changes; this subtask did not edit research.py, API, worker.py, runtime adapters, or infrastructure. See the parent's integration results for verification of those paths.

## Tests and qualifications

Tests were written and observed failing before implementation. Additional checkpoint and native-load regressions were independently observed failing before their fixes.

Executed:

```
.venv/bin/ruff check src/physharness/domain.py src/physharness/service.py src/physharness/collaboration.py src/physharness/orchestration/research_worker.py tests/test_sharing.py
.venv/bin/pytest -q tests/test_sharing.py tests/test_authority.py tests/test_orchestration.py tests/test_research_services.py tests/test_core.py
```

Result: Ruff clean; **49 passed**, including **19 sharing tests**. Coverage includes the actual worker executor prompt and ToolDispatcher path, canonical native session/output association, policy distinctions, forged attribution, invalid acceptance bindings, legacy and explicit controller behavior, delegation, and unchanged existing authority/accounting tests.

These are authorization/protocol tests using controlled canonical acceptance fixtures and a scripted runtime. They are not Linux containment qualification, Lean/nanoda proof evidence, live provider experiments, or measured collaborative success. Full wave qualification remains unqualified until the required real experiments and infrastructure checks run.

## Practical limits

- Trusted operators/reviewers remain outside branch isolation and can inspect canonical project data. Trusted common inputs are explicit controller choices.
- Parent-created task objectives can intentionally transmit chosen context to children; automatic inheritance of private parent history is absent. Fresh competing branches should be seeded by the controller when independence from parent ideas is required.
- Existing legacy records lacking canonical branch association fail closed for other branch workers; no data migration or provenance-based retroactive trust was introduced.
- The sharing filter scans bounded batches and checks canonical receipts, prioritizing correctness. It has not been performance-qualified on a large production dataset.
