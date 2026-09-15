# Formal verification fixtures

These are **unreviewed, uncompiled smoke fixtures**, not accepted scientific claims.
`qualification.json` records the actual blocked qualification status. The two fixtures
exercise a bit-flip identity for two-basis vectors and discrete translation composition.

The root `lean-toolchain` pins the upstream Comparator toolchain observed during implementation.
Other checker sources and build artifacts remain unprovisioned: there is no complete pinned
kernel build in this repository yet. Do not run candidate sources directly on the Mac.

See [the verification deployment and reproduction instructions](../docs/VERIFICATION.md)
for the immutable bundle schema, fixed container runner, required source/binary/image/launcher/seccomp pins,
expert review, attack cases and qualification evidence. `Dockerfile` is the final image layer
on an independently provisioned and audited toolchain base; it intentionally cannot invent one.

## Protocol-v2 qualification inputs

An operator-created manifest must use `physharness-comparator-v2` and bind the canonical
`problem_revision_id`, metadata `target_digest`, `challenge_sha256` of the exact UTF-8
`formal_statement`, `environment_digest`, and exactly `[target_theorem]`. Keep the source bytes
unchanged when assembling `Challenge.lean`; line-ending normalization changes the source identity.

Every operator-pinned case consumed by `infra/run_qualified_lean.py` must include
`challenge_sha256` and the required reviewed `target_theorem` in its VerificationRequest, alongside
the canonical metadata digest and existing identity/review fields. Old cases and manifests must
be regenerated from canonical records and repinned; no compatibility aliases are accepted.
Launcher/driver changes require a rebuilt image, fresh qualification evidence, and new pins.
The qualification status here remains blocked; synthetic protocol tests do not qualify it.
