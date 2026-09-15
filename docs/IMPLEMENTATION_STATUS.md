# Implementation evidence ledger

Plan: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)

## Current work

- Repository initialized on `codex/foundation`; no prior implementation existed.
- Building canonical records, service/API, artifact integrity, verification boundary and local execution first.
- All waves remain unqualified until their acceptance evidence is recorded here.

## Rulings and environment

- Ruling: use the dedicated new project directory on an implementation branch instead of creating a second empty worktree; no pre-existing checkout requires isolation.
- Ruling: implement and test locally without pretending unavailable infrastructure is live. Docker daemon is not running, Lean has no default toolchain, and GitHub authentication is currently invalid. Continue code and local verification; do not fabricate deploy, expert, kernel, or fleet evidence.
- Ruling: Python 3.12.13 is installed; use it with project-local caches. Cloud configuration and experiment spending remain explicit operator inputs.
- Ruling: tests may use controlled fake external transports, but production acceptance has no fake-success mode.

## Integration ownership

| Subsystem | Producer | Consumer | Contract |
|---|---|---|---|
| Records and application services | Main implementation | API/client/verification | Pydantic immutable records, typed errors, actor-scoped operations |
| Verification | Independent implementation task | Application service | Typed request/outcome, configured trusted environment; never trusts submitted receipt fields |
| Runtime providers | Runtime implementation task | Research controller | Capabilities and explicit unsupported outcomes |
| Console | Console implementation task | HTTP API | Read server evidence; no invented demonstration success |

Implementation evidence and review findings are appended as work proceeds.
