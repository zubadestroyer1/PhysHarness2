# Research console

The console is a private React/TypeScript workstation for the PhysHarness v1 API. It displays canonical server records and never substitutes sample successes when the API is empty or unavailable.

## Run locally

The frontend requires Node.js 22.22.2+, 24.15.0+, or 26+ and npm. Odd-numbered Node 25 is outside the Vitest/jsdom support range. From `console/`:

```bash
npm install
npm run dev
```

Set `VITE_API_URL` when the API is hosted on another origin. With no value, requests use relative paths on the Vite origin:

```bash
VITE_API_URL=http://127.0.0.1:8000 npm run dev
```

For a same-origin deployment, route `/v1/*` and `/healthz` to the FastAPI service. For a separate origin, add the console origin to the backend CORS configuration.

The connection screen asks for an operator-issued bearer token. The token is stored in `sessionStorage` under `physharness.token`, remains scoped to the browser tab session, and is never compiled into the bundle. Disconnect removes it.

## Behavior

The console loads authenticated collections for campaigns, problems, experiments, branches, tasks, claims, artifacts, reviews, sessions, programs, events, and service status. It refreshes every five seconds. A failed initial load or refresh leaves the structured error visible with its code, HTTP status, operation ID, retryability, and remediation; stale records are never presented as a successful refresh.

Mutation requests create a fresh UUID `Idempotency-Key`. Experiment transitions send the revision shown in the selected canonical experiment as `expected_revision`. A revision conflict therefore remains a visible operator decision instead of being retried against a newer record automatically.

The interface supports:

- campaign creation with quantum and classical program scope;
- problem proposals with informal/formal statements, theorem name, assumptions, definitions, source, and a 64-character SHA-256 environment digest;
- experiments with an exact runtime/model/parameter tuple and decimal-string cost, concurrency, and duration limits;
- start, pause, resume, and cancel transitions allowed by the displayed execution status;
- semantic target review with rationale, with reviewer role enforcement left to the API;
- experiment ledger inspection and reproducibility export;
- claims and branches in table and graph views; and
- artifact metadata plus source/log content loaded from `GET /v1/artifacts/{id}/content`.

## Evidence semantics

Execution status, service health, semantic review, formal proof status, assumptions, claim evidence, novelty review, and deployment qualification appear as separate fields. `running`, `completed`, compilation success, and a healthy API are never rendered as formal acceptance. Missing fields are shown as `not reported`, `unavailable`, or `not implied` according to their meaning.

The status strip uses `GET /v1/status` verbatim. A configured verifier, workflow engine, or worker provider remains distinct from qualification evidence. Costs and active-worker counts use the values returned by the ledger; the browser does not estimate either value.

## Verification

```bash
npm run typecheck
npm test
npm run build
```

Vitest and React Testing Library cover authentication/empty state, structured errors, evidence separation, mutation inputs and idempotency, exact experiment configuration, cancellation, and revision-conflict remediation. All test fixtures live in `console/tests/`.

The API contract defines individual record routes for the implementation, and the current backend also exposes artifact content at `GET /v1/artifacts/{id}/content`. No additional detail call is currently required by the console.
