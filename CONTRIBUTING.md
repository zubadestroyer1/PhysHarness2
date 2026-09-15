# Contributing

PhysHarness is developed in implementation waves whose exit criteria are recorded in
`docs/IMPLEMENTATION_PLAN.md`. Read the implementation evidence ledger before assuming a
feature or deployment is qualified.

Use Python 3.12 and `uv sync --frozen --group dev --extra codex --extra e2b`. Run
`uv run ruff check src tests`, `uv run pytest`, and, for frontend changes,
`cd console && npm ci && npm run typecheck && npm test -- --run && npm run build`.
Live-model runs need explicit manifests, exact models, configured prices, and an experiment
resource envelope. Use `PHYSHARNESS_RUN_TEMPORAL_TESTS=1` for the separately labeled local
Temporal integration suite. Never replace missing verifiers or providers with a success fixture
outside tests.

Use small branches and reviewable commits. PR descriptions explain behavior, validation,
limitations, and migrations. Acceptance, trusted definitions, credential boundaries, and result
promotion need independent review; substantial runtime/coordination changes also need a second
reviewer. Do not merge those changes based on the implementer's tests alone.

Keep private transcripts, credentials, unreviewed novelty claims, generated caches, and live
experiment workspaces out of Git. Curate reusable code and scientifically reviewed results.
Errors should retain an operation identifier, a clear diagnosis and a useful remediation.
Do not convert infrastructure failure into proof rejection, an empty success, or a fabricated result.

New project code is Apache-2.0. Preserve upstream attribution and licenses. Record source
provenance and permissible use before adding papers, benchmark examples or training data.
