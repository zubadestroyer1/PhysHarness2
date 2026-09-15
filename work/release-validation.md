# Development release validation

2026-09-15 UTC, macOS arm64, Python 3.12.13. This is an integrated development implementation;
all twelve wave qualification gates remain outstanding as specified in the implementation ledger.

| Check | Observed outcome |
|---|---|
| `.venv/bin/python -m pytest -q --junitxml=.state/checks/python-tests.xml` | 368 passed, 2 skipped, 21 upstream deprecation warnings, 13.86 s |
| Ruff lint and formatting across source/tests/tools/infra/migrations | Passed; 93 Python files formatted |
| Console tests | 10 passed |
| TypeScript checks and Vite production build | Passed |
| Opt-in real local Temporal integration | 1 passed, 6.52 s, pinned official CLI 1.8.3 |
| Terraform 1.16.2 validation in `infra/terraform/aws` | Valid with AWS provider 6.10.0; no plan/apply |
| Docker Compose 5.5.0, app and worker profiles, private generated environment | Configuration valid; no container start |
| Deployment metadata validation | Passed; no execution qualification implied |
| Browser against restarted actual API | Authenticated connection, retained campaign and scoped activity visible; all waves unqualified |
| Bounded independent audits | Reproduced faults corrected and rechecked; provenance and scope retained in the corresponding reports |

Default Python skips are the opt-in local Temporal engine and the absent dedicated PostgreSQL
endpoint. The separate Temporal invocation above closes only the local engine check. Warnings
come from Starlette/AnyIO compatibility and internal OpenHands deprecated fields; they remain
visible rather than being filtered into a warning-free claim.

The final regressions include exact target/receipt authority, branch sharing, native-state
privacy, interrupted/uncertain allocations, failed VM cancellation, shared-slot accounting,
late artifact-upload fencing, default workspace directories, SDK import order with preserved
workflow restrictions, safe configuration errors and local export permissions/FIFO refusal.

No live hosted model, E2B VM, accepted Lean proof, independent kernel, expert scientific review,
managed cloud deployment, fleet endurance test, trained solver improvement or new physics
result was produced in these checks. The local synthetic ledger replay is separately labeled;
it is not a live 128-worker qualification. See `docs/IMPLEMENTATION_STATUS.md` for remaining
engineering work as well as environmental and scientific prerequisites.
