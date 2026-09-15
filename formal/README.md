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
