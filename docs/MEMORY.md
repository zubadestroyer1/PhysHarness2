# Portable scientific context

`physharness.memory.PortableMemory` creates immutable, versioned context checkpoints through the real canonical service. It preserves scientific authority while allowing a worker to use a shorter, selected history. It does not call a model, train a summarizer, edit claims, accept proofs, or delete historical records.

```python
from physharness.domain import canonical_json
from physharness.memory import PortableMemory

memory = PortableMemory(service)
page = memory.history_page(branch_id, worker, kind="artifact", limit=50)
checkpoint = memory.checkpoint(
    branch_id,
    worker,
    "checkpoint-command-17",
    approach="Compare the two representations under the stated assumptions.",
    unresolved_obligations=["Justify exchanging the two limits."],
    summary="The first approach stalled at the uniform bound.",
    evidence_ids=[item["id"] for item in page["items"]],
    previous_checkpoint_id=None,
    max_bytes=65536,
    max_estimated_tokens=16384,
)
portable = memory.restore(checkpoint["id"], worker, expected_branch_id=branch_id)
prompt_context = canonical_json(portable)
```

Pass a prior checkpoint ID on later calls to build hash-bound lineage. New calls require new idempotency keys; replaying the same key and intent returns the original checkpoint rather than capturing changed live context. Changed intent or branch/orchestrator authority conflicts with that key. A replay is not a freshness check: call `restore` before using a checkpoint.

## Scientific core and annotations

Every checkpoint contains the complete canonical target record, including its revision, exact formal and informal statements, definitions, assumptions, environment digest, target digest, and review identity. Its matching review record is included. The context also retains the assigned branch/experiment identity and information/sharing policy.

Mandatory obligations include all visible records owned by this branch in these categories:

- Tasks not marked completed, preserving their objectives, dependencies, and canonical status references.
- Unproved claims, preserving their statements, assumptions, and canonical status references.
- Blocked or rejected verification attempts, preserving their canonical status, diagnostic message/code, and evidence record reference.

These records remain in the scientific core even when `evidence_ids=[]`. In particular, selecting less history or writing an optimistic summary cannot erase a failed proof attempt or an unresolved assumption.

`approach`, caller-supplied `unresolved_obligations`, and optional `summary` are separate annotations attributed to the authenticated actor and explicitly labeled `unverified`. Model-authored text belongs in these annotation fields. It never overrides the canonical core, invents a verified claim, or confers publication status. Restoration validates these labels; even rehashed storage corruption cannot turn a summary into a verified field.

## Size bounds and history selection

The service measures the UTF-8 byte length of the actual serialized checkpoint. The token estimate is explicitly `ceil(utf8_bytes / 4)`; it is a reproducible planning estimate, **not** a provider tokenizer or a hard model token guarantee. The configured byte limit is exact. Runtime limits must additionally budget the surrounding prompt and provider-specific tokenization.

The mandatory scientific core cannot be silently truncated. If it exceeds either configured bound, checkpointing fails with `SCIENTIFIC_CORE_TOO_LARGE` and the measured core size. If selected history or annotations make the full checkpoint too large, it fails with `CONTEXT_ENVELOPE_EXCEEDED`. No shortened checkpoint is issued. Defaults are 65,536 bytes and 16,384 estimated tokens; the implementation supports a byte bound up to 8 MiB.

Historical references are explicitly selected by canonical record IDs. Each reference includes the record's ID, kind, revision, digest and evidence-status fields; artifact references also bind content hashes, and their bytes are integrity-checked. An accepted status requires actual canonical acceptance bindings, not a status-shaped annotation. The history manifest always declares selection and never claims completeness. Selecting no optional history is valid because the mandatory scientific core remains present.

`history_page(branch_id, actor, kind=..., limit=50, after=None)` returns `items` and `next_cursor` for artifacts, claims, tasks, verification records, sources, or programs. Continue until the cursor is `None`. A page may be empty while still returning a cursor if it contained only private runtime/checkpoint artifacts, which portable history excludes. Canonical records and artifact bytes remain retained regardless of selection.

## Visibility, fencing, and restoration

Both creation and restoration construct an assigned-branch reader, even when invoked by an operator. Agent callers must possess that exact branch identity. They cannot use another branch's checkpoint lineage, scientific history, or native sessions. The only special review lookup is the exact canonical review of the worker's already-visible target. Other record access uses the service's real sharing rules.

For a running task, pass all three of `task_id`, `holder`, and `fence` to `checkpoint`. The service checks the branch/task association and current lease within the checkpoint transaction. Agent holders must match the authenticated worker ID. Partial lease tuples and stale fences fail. Without a lease tuple, a caller may explicitly save a branch-level checkpoint; this does not complete a task or mutate its state.

Checkpoint issuance stores a private `checkpoint` artifact with a versioned format and canonical issuance metadata. A regular artifact that merely copies its JSON cannot impersonate an issued checkpoint. Issuance uses the service's authority-aware idempotency and atomic record/event transaction. Content storage is immutable and hash-checked.

`restore` checks:

- The artifact's canonical issuance marker, byte/content digests, measured envelope, version, and branch/experiment association.
- Every predecessor ID, content hash, branch scope, and generation, rejecting cycles and missing or changed ancestors. Lineage depth is bounded at 256 checkpoints; a caller can explicitly begin a new root while earlier history remains retained.
- The current exact target, review, environment, assumptions, definitions, information policy, and mandatory open/failed records.
- Each selected historical reference against its current canonical record, including evidence status and artifact integrity.

If current science or evidence differs, restoration fails with `CONTEXT_STALE` rather than silently rewriting an old checkpoint. Create a fresh checkpoint with a new key and the previous checkpoint ID. Ancestor snapshots remain historical: their integrity and lineage are checked, while current-state freshness is required for the restored head. This permits new compaction after a task or evidence status changes.

## Cross-model handoff and limits

The restored payload is a portable brief suitable for a different model/runtime. It always reports `portable=True` and `native_continuation="not_included"`. Native provider state, session IDs, native checkpoints, runtime events, and failure artifacts cannot be inserted as portable history. Continuing an opaque native session remains the responsibility of the corresponding runtime adapter and its same-runtime continuation contract.

The module exposes operations for worker/API integration; it does not automatically replace worker prompts or trigger runtime continuation. Freshness is checked at restoration time, so callers should restore immediately before constructing a generation input. Scientific verification still uses the independent acceptance pipeline.

Validation: 17 real-service tests cover crucial assumptions and definitions, failed attempts, unproved claims, envelopes, selectable history, idempotency, stale reviews/statuses, native-state exclusion, cross-branch access, lease fencing, corrupt bytes, rehashed invented status, forged issuance, and ancestor hash changes. A combined memory/sharing/authority/orchestration run passed 51 tests. Ruff passed. These tests use local canonical services and controlled corruption fixtures, with no LLM calls; they provide no live model, containment, proof-checker, or scientific-success qualification.
