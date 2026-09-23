# Wave 0/1 delivery documentation edit report

Updated for the observed final 8 GiB control evidence while the two full physics
reports continue to run. The current [delivery](DELIVERY-2026-09-22.md) is the
operator handoff; [DELIVERY.md](DELIVERY.md) remains a dated historical snapshot.

## Files edited

- `work/wave01/DELIVERY-2026-09-22.md` — current image, final scope, completed
  control and host checks, automatic assessment, pending physics/retention/human gates.
- `work/wave01/DELIVERY.md` — historical notice links the current report.
- `docs/IMPLEMENTATION_STATUS.md` — current Wave 0/1 status and handoff link.
- `docs/README.md` — navigation link to the current handoff.
- `docs/VERIFICATION.md` — current controls and assessment alongside historical runs.
- `docs/VERIFIER_QUALIFICATION.md` — replaces the obsolete claim that no 8 GiB run exists.
- `docs/FORMAL_ENVIRONMENT.md` — identifies the consolidated image and pending operations.
- `docs/ROADMAP.md` — updates Wave 0/1 evidence and remaining gates.
- `formal/README.md` — identifies current controls and image from the formal entry point.
- `work/wave01/delivery-docs-report.md` — this edit record.

## Evidence and limits

The completed control set is 24 expected core/library outcomes across two modes,
16 fixed boundary observations, and 224 passed scoped regressions with one
conditional PostgreSQL skip. The separate ordinary suite recorded 809 passed
and four conditional skips. The independent control assessment mechanically
satisfied all 10 checks. The 40 positive physics targets, 11 mechanical altered
controls, and nine valid semantic-hold controls remain distinct populations.

The two serial 60-case physics reports and their final assessment were still
running or pending when these edits were made. Final image archive and VM shutdown
were also pending. Human scientific and deployment gates remain open. No physics
score, production approval, model calibration, paid model run, fleet qualification,
or novel scientific result is claimed. Historical 2 GiB evidence remains scoped
to its original image and source.

No production source, tests, fixtures, matrix, operator helper, evidence JSON, or
root-owned execution ledger was edited for this documentation task. No Docker,
Lean, GitHub or live process operation was performed here.

## Final documentation update

After the earlier draft, both 60-case physics reports completed and an independent
audit found no identity or outcome discrepancies. The current delivery and linked
status pages now report each mode's 40 positive verifications, 11 mechanical
blocks and nine mechanically verified semantic holds, with the stored combined
assessment matching the fresh assessor. The current and historical images were
archived with integrity and manifest checks; the dedicated VM was observed
stopped. A fresh-VM restore and the human gates remain pending. The historical
snapshot above remains a record of what was pending at the earlier edit.

This final update edited `work/wave01/DELIVERY-2026-09-22.md`,
`work/wave01/evidence-8g/README.md`, `docs/IMPLEMENTATION_STATUS.md`,
`docs/VERIFICATION.md`, `docs/VERIFIER_QUALIFICATION.md`,
`docs/FORMAL_ENVIRONMENT.md`, `docs/ROADMAP.md`, `formal/README.md`, and this
report. It did not change source, frozen evidence, helpers, or the root ledger.
