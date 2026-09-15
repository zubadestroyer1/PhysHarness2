# Self-hosted path: unqualified

The local Compose stack is an executable development path, not a production deployment. A later
self-hosted deployment retains PostgreSQL as canonical storage, an S3-compatible artifact store
whose conditional-write and version semantics have been tested, and a separately operated
Temporal service. Kubernetes/Ray coordinate workers; neither replaces authoritative storage,
project authorization, experiment budgets, or independent proof acceptance.

No Kubernetes, KubeRay, Firecracker, snapshot portability or live scaling implementation is claimed
here. `qualification.json` records these as not implemented/not run. A deployable VM adapter must
first demonstrate a dedicated KVM host boundary, network restrictions, credential isolation,
artifact transfer integrity, independently identified forks, snapshot compatibility and process
cancellation. A scheduler must demonstrate fencing, orphan reconciliation and descendant cost
accounting under fault injection before 128-worker or 1,000-worker capacity is asserted.

The existing `RuntimeAdapter` and `SandboxExecutor` interfaces are the replacement boundary.
Deploy the actual qualified Comparator acceptance worker separately; running the Python API or
research worker in a container is not proof of a qualified Lean/kernel isolation boundary.
