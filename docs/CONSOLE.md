# Research console

The console is a private React/TypeScript workstation for the PhysHarness v1 API. It displays canonical server records and never substitutes sample successes when the API is empty or unavailable.

## Run locally

The frontend requires Node.js 22.22.2+, 24.15.0+, or 26+ and npm. Odd-numbered Node 25 is outside the Vitest/jsdom support range. From `console/`:

```bash
npm ci
VITE_API_URL=http://127.0.0.1:8000 npm run dev
```

The local API runs on port 8000 and Vite runs on a separate origin. Set `VITE_API_URL` as above, or enter `http://127.0.0.1:8000` in the connection screen's API URL field. An API URL saved in this tab takes precedence over the environment default. With no value, requests use relative paths on the Vite origin, which requires an explicitly configured reverse proxy.

For a same-origin deployment, route `/v1/*` and `/healthz` to the FastAPI service. For a separate origin, add the console origin to the backend CORS configuration.

The connection screen asks for an operator-issued bearer token. The token is stored in `sessionStorage` under `physharness.token`, remains scoped to the browser tab session, and is never compiled into the bundle. Disconnect removes it.

## Behavior

On connection, the console captures the event watermark **before** loading the authenticated collection snapshot (campaigns, problems, experiments, branches, tasks, claims, artifacts, reviews, sessions and programs) and service status. This ordering ensures writes during snapshot loading are observed by later polls. Collection reads follow every continuation cursor, including empty filtered pages. Pagination loops or excessive inventories produce a visible error; partial inventories are not committed as complete.

Every five seconds, a non-overlapping read cycle requests one forward event page (up to 100 visible events), service status and the selected experiment's ledger. Unchanged event pages do not reload record collections. Ordinary canonical events refresh their individual record; target review and branch checkpoint events also fetch their linked review or artifact. Verification events refresh all claim pages scoped to the affected experiment. Unknown event families use a complete collection snapshot as a correctness fallback. Failed sibling reads are allowed to finish before another cycle starts.

A forward event page is committed with its cursor only after the associated canonical refresh succeeds. Empty visible pages still advance using the server cursor. Additional pages wait for subsequent cycles, and the sidebar and Activity page show when catch-up is pending. Activity starts with up to 100 recent visible events, then retains events observed during this connection; it explicitly states that earlier history is not loaded. Problems, experiments, claims, branches and experiment-owned artifacts are displayed within the chosen campaign; unscoped artifacts remain visible.

Selected record details and transition revisions come from refreshed canonical records. The selected experiment ledger refreshes on selection and every poll. Loaded immutable artifact content remains bound to its artifact ID while metadata refreshes. Session, selection and request guards prevent late ledger, artifact, export, mutation and collection completions from replacing a newer view or repopulating a disconnected session. Closing or reopening an export invalidates the earlier export request.

A failed initial load or read refresh leaves the structured error visible with its code, HTTP status, operation ID, retryability and remediation, with an explicit stale-record warning. A successful read clears only the read error. Mutation failures remain visible independently until another mutation begins; polling never automatically retries a mutation. Read retry controls repeat reads only.

Each explicit mutation generates one UUID `Idempotency-Key`. Experiment transitions send the revision shown in the canonical experiment as `expected_revision`. Revision conflicts remain visible operator decisions; the console never retries them automatically with a new revision or key. List and detail controls share these transitions:

| Canonical status | Available actions |
| --- | --- |
| `created` | Start, Cancel |
| `queued`, `running` | Pause, Cancel |
| `paused`, `blocked` | Resume, Cancel |
| Terminal or unrecognized | None |

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

Vitest and React Testing Library cover authentication, evidence separation, mutation inputs and idempotency, canonical transitions and revisions, persistent mutation errors, event watermark ordering and pagination, scoped refresh, overlapping cycles, and stale session, ledger, artifact, mutation and export completions. All test fixtures live in `console/tests/`.

Incremental refresh uses the API contract's individual record routes. Artifact content comes from `GET /v1/artifacts/{id}/content`; it is fetched when that artifact is selected.
