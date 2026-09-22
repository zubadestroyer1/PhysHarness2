# Console implementation report

## Delivered

Implemented a responsive React/TypeScript/Vite private research console in `console/` and operator documentation in `docs/CONSOLE.md`.

The workstation includes campaign selection, overview, campaign, problem, experiment, claim/branch, artifact, and activity views. It reads canonical API data, refreshes at five-second intervals, and keeps any initial or polling error visible with error code, HTTP status, operation ID, retryability, remediation, and an explicit retry control. There is no fabricated success or demonstration-data path.

Mutating workflows include campaign creation, problem proposal, exact experiment creation, experiment start/pause/resume/cancel with the displayed revision, and reviewer-gated semantic decisions with rationale. Each command sends a new UUID `Idempotency-Key`. Experiment export and resource-ledger inspection use server responses directly. Artifact selection loads stored UTF-8 source/log content from `GET /v1/artifacts/{id}/content`.

Scientific state remains separated in the interface: service/process checks, infrastructure qualification, execution status, semantic review, formal proof status, assumptions, claim evidence, and novelty status each have their own label. Execution completion or health never produces a solved/proved indicator. Decimal money strings and active-worker counts come from the server ledger without client-side estimation.

## API integration

The client uses `VITE_API_URL`, defaulting to a relative origin, and a user-entered bearer token held in `sessionStorage`. It reads the v1 collections and status/events routes defined in `docs/API_CONTRACT.md`. It also uses the backend's implemented artifact-content route noted above. Individual entity detail routes now exist in the backend; the console does not currently need another undefined detail call.

The implemented backend narrows two contract fields, and the console follows those concrete validators:

- Experiment `mode` is one of `research`, `discovery`, `literature_assisted`, or `replay`.
- Problem `environment_digest` is a 64-character lowercase SHA-256 digest, and definition values are strings.

## Automated checks

Fresh checks on September 14, 2026:

- `npm run typecheck`: passed with no TypeScript errors.
- `npm test -- --reporter=dot`: 2 test files passed, 8 tests passed.
- `npm run build`: passed; Vite emitted a 260.53 kB JavaScript bundle (78.39 kB gzip) and 20.03 kB stylesheet (5.25 kB gzip).

Tests cover the token connection and actionable empty state, visible status and evidence separation, mutation authorization/idempotency, exact runtime/model/decimal budget input, cancellation with `expected_revision`, visible revision-conflict remediation, generic network failure preservation, and an explicit unprivileged reviewer 403 with operation ID. Fixtures exist only under `console/tests/`.

## Remaining integration concerns

The host provides Node 25.9.0. Vitest 5.0.0 and jsdom 30.0.1 intentionally support even-numbered Node lines (22.22.2+, 24.15.0+, or 26+) and emit an engine warning for Node 25. All checks completed successfully on the host, but CI and routine development should use one of the supported Node versions declared in `console/package.json`.

The test suite validates the browser/API boundary with controlled HTTP responses. A live signed-in browser audit against the integrated FastAPI process remains for the parent integration pass, as requested in the console brief. A missing or unavailable collection route deliberately fails the refresh loudly and retains the prior records under the visible error rather than silently claiming fresh state.
