# Formal environment and fixtures

`Dockerfile` builds real Lean 4.33.0, Comparator, lean4export, Landrun and nanoda from
`environment.lock.json`; no separately invented qualified base image is required.
A real aarch64 core build completed on 2026-09-15. Its measured hashes are in
`build-observations.aarch64.json`. Build evidence is separate from sandbox qualification
and expert semantic review.

The optional `physics` Docker target builds selected Mathlib, Physlib and QuantumInfo
imports from pinned source. Physlib and QuantumInfo share one repository and toolchain.
`declarations.audit.json` inventories 27 real declarations in five modules, with exact
source hashes, locations, imports and lexical risk markers. It grants no semantic approval.
A successful physics build also runs the explicit `DeclarationAudit.lean` axiom audit.

See [FORMAL_ENVIRONMENT.md](../docs/FORMAL_ENVIRONMENT.md) for the version matrix,
rebuild commands, source provenance and audit limits; see
[VERIFICATION.md](../docs/VERIFICATION.md) for the acceptance boundary and qualification.
`qualification.json` tracks observed status without fabricating qualification authority.

The classical and quantum smoke fixtures are tiny algebraic engineering examples,
not accepted scientific claims. Live engineering results, when present, are separate
from domain-expert review and full containment qualification.


## PR correction compatibility

Scientific submission and request validation share a 2,000,000-character candidate limit; larger
submissions fail before queueing. Persisted oversized candidates, unavailable candidate bytes and
incompatible legacy receipts receive explicit blocked diagnostics. Scientific receipts bind the
current review, exact UTF-8 source hash and selected theorem, including during evidence reuse.
Engineering requests remain separate and do not acquire a manufactured semantic review.

The combined PR corrections change host/driver bytes. Earlier recorded engineering results remain
evidence for their recorded image and code hashes; they do not validate this combined source.
Rebuild and rerun genuine engineering/qualification checks before supplying new deployment pins.
