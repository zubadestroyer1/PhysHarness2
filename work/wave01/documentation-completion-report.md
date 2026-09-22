# Operator documentation completion report

Date: 2026-09-22

## Outcome

The bounded operator documentation correction is complete. No implementation, test, proof,
Docker, Lean, GitHub or historical evidence file was changed. The current image build and real
8 GiB evidence collection remain pending; this report makes no completion or qualification claim.

## Files and changes

- `docs/VERIFICATION.md`: documents the required explicit trusted resource-profile input;
  distinguishes canonical profile, exact profile-file and shared policy-source hashes; explains
  fail-closed old pins and rerun requirements; scopes the local checker lock; records OOM evidence
  rules; gives the distinct single-bundle path and per-entry registry contracts; and marks 2 GiB
  evidence historical.
- `docs/VERIFIER_QUALIFICATION.md`: replaces stale 110-second/100,000-byte limits with the
  repository-default 8 GiB / 4 CPU / 600-second / 256,000-byte / one-slot bounded profile, and
  records resource identity, OOM, lock-scope and pending-evidence qualification rules without
  implying that all pinned profiles must use those default values.
- `docs/FORMAL_ENVIRONMENT.md`: makes persistent user-owned `COLIMA_HOME` the default for new VMs,
  preserves the old `/private/tmp` location as historical provenance, and explains why endpoint
  and host-agent checks were needed when temporary metadata vanished.
- `formal/README.md`: adds the current resource envelope, separate hash identities and explicit
  statement that no 8 GiB evidence directory exists yet.
- `docs/IMPLEMENTATION_STATUS.md`: updates the ledger date and separates the 40 proposed real
  physics targets plus 20 altered cases (11 mechanical nonacceptance controls and nine valid
  semantic-hold controls) from tiny algebra controls; records pending human review, calibration,
  current-image benchmarking, qualification and deployment gates; adds VM guidance.
- `docs/ROADMAP.md`: aligns Wave 0/1 status with the proposed benchmark inventory and pending
  current-image and human gates.

## Consistency checks

- Read `work/wave01/resource-completion-report.md`, `formal/verifier-resources.json`, relevant
  bootstrap/resource/qualification/runner source and current operator docs before editing.
- Confirmed the profile values are 8 GiB, 4 CPUs, 600 seconds, 256,000 output bytes and one slot.
- Confirmed the single-bundle resource path is required with a complete single-bundle verifier,
  is mutually exclusive with registry mode, and is checked against all three qualification pins.
  Confirmed registry entries carry explicit canonical resources and the raw profile-source hash,
  checked with the policy hash against each entry's qualification.
- Clarified that absent positive OOM evidence leaves a negative exit blocked with uncertain cause,
  and that missing required cgroup observations prevent qualification without treating every
  unavailable optional Docker-state observation as failure of a successful kernel result.
- Searched the six edited operator documents for stale limits, resource/qualification wording,
  temporary Colima paths, OOM/137 wording and pending `evidence-8g` status.
- `git diff --check` passed after the edits.

## Unresolved facts and gates

- `work/wave01/evidence-8g` does not exist. The current image build and real 8 GiB engineering,
  fixed-boundary, benchmark and qualification runs must finish before status can be reconciled.
- Existing evidence under `work/wave01/evidence` used the historical 2 GiB profile and cannot be
  promoted to current qualification.
- Wave 0 target meaning, fidelity, difficulty/calibration, contamination and holdout decisions
  still require human review.
- Wave 1 still requires complete current-image reports, deployment review and human approval.
- Recovery of the historical dedicated VM cannot be inferred from `colima status` alone after its
  temporary metadata vanished; actual endpoint and host-agent observations remain authoritative
  for that incident. The documentation does not direct migration or recreation of that VM.
