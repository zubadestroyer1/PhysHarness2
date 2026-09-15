# PhysHarnessV2

A private research laboratory for model-directed mathematical physics, with durable records,
independent proof acceptance, and explicit resource accounting. Models choose their methods and
collaborators. The harness controls authority, execution, provenance and acceptance.

**Status: development implementation; no production or scientific qualification yet.** Local
contract tests, a real local Temporal integration test, and a synthetic ledger stress run have
been executed. No hosted model run, live E2B fleet, Lean kernel qualification, expert-reviewed
benchmark suite, or open-problem solution is claimed. See the
[implementation evidence ledger](docs/IMPLEMENTATION_STATUS.md) for the distinction between
implemented components, integration gaps and wave exit criteria.

## Local laboratory

Requires Python 3.12, `uv`, and Node 22/24/26 for the console. Dependency versions are committed
in `uv.lock` and `console/package-lock.json`.

```sh
UV_CACHE_DIR=.cache/uv uv sync --locked --all-extras
uv run phys init
uv run phys serve
```

`phys init` creates a local SQLite database and separate researcher, reviewer, operator and
publisher identity files under `.state/`, with private file permissions. It refuses to overwrite
existing identities. This command does not invent scientific targets, expert reviews or proofs.
The API binds to loopback by default. Open `/docs` at `http://127.0.0.1:8000` for the generated API
schema. `/healthz` is only a process probe; authenticated `/v1/status` reports missing services.

In another terminal:

```sh
cd console
npm ci
npm run dev
```

Connect the console to `http://127.0.0.1:8000` using the researcher token from the local private
file. The console has campaign, target, experiment, branch, claim, artifact, review, ledger and
event views. It shows errors and evidence status from the API, without fabricated fallback data.

The CLI and MCP server use `PHYSHARNESS_URL` and `PHYSHARNESS_TOKEN`. Inject the token through a
private environment or secret manager. `phys request` reads endpoints or submits an exact JSON
file with a stable idempotency key; `phys export` downloads hash-checked experiment artifacts.
`phys validate-export` checks local export integrity without claiming kernel replay.
`phys doctor` deliberately exits nonzero when required services are missing. `phys-mcp` exposes
research operations through the same API authority.

## Implemented components

- Canonical scientific records, immutable content-addressed artifacts, exact target revisions,
  role/project/branch scopes, idempotent commands and optimistic revisions.
- Separate proof, semantic review, assumption, numerical and novelty status. Only the independent
  acceptance worker can promote a proof. Missing checkers produce blocked receipts.
- Comparator/Linux acceptance boundary, axiom policy, nanoda publication path, and adversarial
  contract tests. Running this boundary requires separately qualified pinned Linux inputs.
- Responses model/tool loop; explicit-capability Codex, Claude and OpenHands SDK adapters;
  canonical E2B VM tools and a VM-only JavaScript orchestration runner. Native adapters have
  documented limits; configuration is not qualification.
- Temporal workflows, transactional outbox, renewable fenced leases, nested delegation, sharing
  policies, reservations and reconciliation of uncertain external work.
- Portable, evidence-preserving context checkpoints, bounded history retrieval and explicit
  stale-context refusal. Native continuation remains runtime-specific.
- Lossless Markdown/LaTeX ingestion, canonical accepted-premise retrieval and source bundles,
  exact arithmetic certificate checks, and reproducible numerical evidence records.
- Portfolio/evaluation primitives, family holdouts, licensed verified datasets, and an evaluated
  retriever training/rollback pipeline. These are components, not measured solver improvements.
- React console, Python client, MCP tools, Alembic migrations, pinned CI, Compose and AWS Terraform.

The distributed worker currently integrates the Responses runtime and optional E2B tools.
Codex/Claude/OpenHands and standalone search/scientific modules still need controller integration
and live qualification. State-level tactic search, certified Lean numerical checkers,
Firecracker/Kubernetes deployment,
large-scale training and sustained open-problem campaigns remain roadmap work.

## Validation

```sh
uv run ruff check src tests tools infra migrations
uv run pytest -q
uv run python infra/validate_metadata.py
```

Run `npm test` and `npm run build` in `console`. Test transports and synthetic evidence fixtures
are confined to tests; they are never production verification authorities. Default tests skip
unconfigured live PostgreSQL and opt-in local Temporal integration. See
[deployment](docs/DEPLOYMENT.md), [operations](docs/OPERATIONS.md),
[verification](docs/VERIFICATION.md), [execution](docs/EXECUTION.md),
[collaboration](docs/COLLABORATION.md), [science](docs/SCIENCE.md), and
[evaluation](docs/EVALUATION.md) for focused commands and limitations.

The complete ambition and acceptance gates remain in the
[implementation specification](docs/IMPLEMENTATION_PLAN.md). In particular, a 128-worker
72-hour live endurance trial and a separate 1,000-worker qualification must precede corresponding
capacity claims. Synthetic replay does not establish scientific throughput.

Apache-2.0 for new project code; upstream materials retain their own licenses and provenance.
See [contribution guidance](CONTRIBUTING.md) and [security boundaries](SECURITY.md).
