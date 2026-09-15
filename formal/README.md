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
