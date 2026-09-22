# Wave01 progress — docs/superpowers/plans/2026-09-15-wave01-qualification.md

> Historical progress snapshot; current work is tracked in
> [RESUME-2026-09-22.md](RESUME-2026-09-22.md). Statements below about running
> tests describe the earlier execution, not the current process state.

Base60e8254c02e8cbfce08201bac1ff2b7ce2224a1c; branch codex/benchmark-verifier-qualification.
Approved scope: implement the preceding Wave0/Wave1 workstreams autonomously, with careful fair physics tasks and independent audits.

During implementation PR20 advanced to470a286bc2e42d839c9d3a51a885bad703e9f67e.
The work branch incorporated those upstream acceptance/VM/console corrections by fast-forward,
preserving local work. Only the driver changed among formal-image build inputs; the final
image must include that new driver. Historical image evidence was not rewritten.

| Interface or task | Preflight |
|---|---|
| Quantum → schema | Version1 manifest contract above; quantum owns only quantum.json |
| Classical → schema | Same contract; classical owns only classical.json |
| Verifier → benchmark evidence | Existing engineering reports; no authority transfer from fixtures |
| VM across tasks | Root owns lifecycle/scheduling; no competing image mutations |
| Human review | Reports remain pending; no model-generated expert approval |
| Task1/2 consistency | Reference proofs and estimates required; measured difficulty not claimed |
| Task3 consistency | Coverage evidence separate from operator signoff; unchanged driver unless reviewed |
| Task4 consistency | Target-only export omits reference/evaluator data; immutable source IDs |
| Task5/6 consistency | Actual Linux checks, scoped review and stopped VM before handoff |

## Current implementation and evidence

- Baseline:525 tests passed,1 explicit infrastructure skip,3 integration/Lean deselections.
- Integrated source9f05c71:747 Python tests passed,1 infrastructure skip,3 deselections;
  36 console tests and production build passed; Ruff passed. GitHub run35024092733 passed
  all five jobs (Python,PostgreSQL,console,Terraform,container).
- Task1/2:40 physics targets and20 altered cases authored across19 families. All40 reference
  sources elaborate in the pinned Linux image. Nine valid semantic mutations also elaborate;
  ten false altered candidates fail with the expected diagnostics. The remaining proof-hole
  candidate elaborates with a warning and still needs final illegal-axiom rejection.
- Task3: exact-scope qualification matrix/assessment and fixed benign containment probe
  implemented; independent audit is checking report/version/assurance behavior. Fresh real
  boundary executions remain pending.
- Task4: strict inventory, source-bound evaluator packages, target-only exports and CLI
  implemented. Independent audit reproduced family relabeling, malformed metadata and
  approval-shaped manifest inconsistencies; regression tests and fixes were added. These
  tools never issue human approval.
- Task5: consolidated source/image rebuild active inside the dedicated Linux VM. Final
  Comparator and nanoda runs will use the new image serially to avoid the observed110-second
  checker deadline under build contention.
- Task6: agent-authored physics collections received mutual mathematical AI review. Code
  audits are independent of authors; reproduced findings were fixed and independently
  rechecked. Seven reviewable commits were created through GitHub MCP and draft PR21 opened,
  stacked on PR20. Final scoped reports, image retention and VM shutdown remain pending.

Initial draft container-mount failures and a contended checker timeout are retained under
`.state/wave01`. They are failed diagnostics, not counted successful acceptance evidence.
Difficulty remains uncalibrated, human scientific review remains pending, and no live model
calls, production deployment or fleet-capacity claims have been made.
