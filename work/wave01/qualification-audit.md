# Independent qualification evidence audit

Final audit status: the two P2 findings and the lower-priority approval-field observation below were fixed by the implementation owner and independently retested. No actionable findings remain from this bounded review. Original observations are preserved for provenance.

Scope: read-only review of the Wave 1 qualification implementation against `docs/superpowers/plans/2026-09-15-wave01-qualification.md`. Reviewed `src/physharness/verification/qualification.py`, `formal/qualification-matrix.json`, `infra/run_qualified_lean.py`, `infra/probe_verifier_boundary.py`, `tests/test_verifier_qualification.py`, `tests/test_verifier_boundary_probe.py`, `tests/test_qualification_diagnostics.py`, the relevant acceptance/checkpoint tests and `docs/VERIFIER_QUALIFICATION.md`. The acceptance agent was consulted because the fixed-probe integration and its final tests were being completed during review.

This is an independent AI engineering audit. It grants no scientific review, deployment approval, live isolation qualification or proof acceptance. No Docker, VM, Lean or real syscall probe was executed for this audit. The proof manifests were not changed.

## Findings

### P2: Parse the exact Lean version instead of accepting a substring

At initial review, `capture_scope` in `src/physharness/verification/qualification.py:358` checks whether the locked version string occurs anywhere in the reported Lean version. With the lock at `v4.33.0`, metadata claiming `Lean (version 4.33.01, ...)` is accepted. This is internally inconsistent provenance even before considering whether the metadata collector is authentic.

A pure reproduction copied the current repository inputs using the existing `deployment` test fixture, changed only `metadata['checker_versions']['lean']` from `4.33.0` to `4.33.01`, recomputed the metadata file hash and called `capture_scope`. The result was an accepted scope carrying the wrong version:

```text
Lean (version 4.33.01, aarch64-unknown-linux-gnu,
      commit d8b18978322de05a8f3dba51ef03cf5461676c17, Release)
```

The same binary hashes and source-lock claim do not justify treating this contradictory version field as matching. Parse the exact version token from the known Lean banner and compare it to the lock; add a near-prefix mutation such as `4.33.01` or `4.33.0-rc1` to scope tests. This finding concerns a consistency check, not authentication or an approval escalation.

### P2: The engineering report producer can label downgraded publication evidence passed

At initial review, `check_case_outcome` in `infra/run_qualified_lean.py:68` checks status/code, exit status and negative diagnostic markers, but it does not check requested kernel assurance or positive completion markers. `_run_engineering(publication=True)` can therefore finish with `status='passed'` when the positive outcomes report only `assurance='kernel'` and their output contains no nanoda completion.

The pure reproduction used the real runner and bundle construction with a fake `EngineeringVerifier` returning valid synthetic core-suite outcomes from the existing tests. The report requested independent replay, but every positive had only ordinary kernel assurance:

```json
{
  "producer_status": "passed",
  "independent_requested": true,
  "positive_assurances": ["kernel", "kernel"],
  "offline_packet_status": "invalid"
}
```

The final offline assessor correctly rejects this report; the acceptance boundary is not bypassed. Nevertheless, the producer's standalone pass classification is misleading and can conceal a future verifier/transport regression until a later tool is run. Pass the requested mode into producer validation and require the matching positive assurance plus the same Lean/nanoda completion markers used by `_suite_report`. Add a producer regression that checks both the raised error and the checkpointed blocked report. No real verifier was weakened or executed in this reproduction.

### Lower-priority consistency observation: regression records accept approval-shaped extras

`_regressions` rejects `production_qualified=true` but initially accepts extra `expert_review='approved'`, `deployment_approval='approved'` and `scientific_review='approved'` fields. A complete synthetic input set with those fields still produces `mechanical_status='satisfied'`. The output packet correctly retains `deployment_approval='pending'` and `scientific_review='not_provided'`; no authority is acquired.

Rejecting those contradictory fields, as the suite and fixed-boundary evidence validators already do for approval fields, would make the evidence contract consistent. This is not an approval bypass and should not be reported as one.

All findings were sent to the acceptance agent and root before this report was written. The acceptance agent owns any implementation changes and associated new regression tests. Resolution and fresh validation should be recorded below rather than deleting these original observations.

## Checks that held under review

- Suite and mode coverage are explicit. Both `core` and `library` are required in ordinary and independent-kernel modes; missing cases, duplicated case IDs, repeated run IDs, reused container identities and duplicate modes cannot fill absent requirements.
- Report and per-outcome identities bind image, runtime observation, runner, launcher, driver, seccomp, fixture, target, challenge, candidate and environment. The assessor rechecks current scoped inputs before and after all evidence reads. Stale source or report bytes invalidate the packet.
- Per-outcome assurance is checked in the assessor, including independent-mode positives. Ordinary comparator failure must have a bounded positive exit code and the exact fixture's causal output; generic syntax, preflight, timeout or cleanup failure cannot substitute for the expected fixture observation.
- Positive assessor checks require Lean completion diagnostics and nanoda completion for independent mode. The reporter gap above is distinct from this correct downstream validation.
- The fixed benign probe requires every named check and writable positive controls, permitted denial errno values, exact provenance and unique cleanup/run observations. It checks the actual container configuration and matching inner binary/driver bytes. Omission is an explicit missing requirement.
- Cleanup checks require removal of the exact named container or a successful empty exact-name listing. A failed daemon inspection alone is not treated as proof of absence.
- Missing/skipped required regression nodes, duplicate JUnit test identities, explicit child failures, XML entity/document-type input, symlink evidence, duplicate JSON keys and hash changes are rejected or marked incomplete.
- Even a complete synthetic mechanically satisfied packet remains `production_qualified=false`, `deployment_approval='pending'`, `scientific_review='not_provided'`. It has no verifier/approval method or automatic promotion to `LinuxQualification`.
- Reports are not cryptographically authenticated by these hashes. A wholly fabricated but internally consistent report can satisfy the mechanical parser, as the documented synthetic tests intentionally demonstrate. The explicit provenance/human-review gate is therefore essential; this review does not treat hash matching as evidence that a real execution occurred.
- The process-exit probe remains an explicit incomplete gap and was not retried. Fixed probe checks do not establish exhaustive Landlock/seccomp isolation, resource exhaustion behavior, current database concurrency or fleet capacity.

## Scoped validation

Executed from the isolated worktree:

```sh
.venv/bin/python -m pytest -q \
  tests/test_verifier_qualification.py \
  tests/test_verifier_boundary_probe.py \
  tests/test_qualification_diagnostics.py
```

Result at the first stable review checkpoint: **65 passed in 0.84s**. These are host tests with synthetic transports, not live boundary observations.

The three independent mutation checks ran with:

```sh
PYTHONPATH=src .venv/bin/python /tmp/audit_qualification_mutations.py
```

The temporary script loaded the existing test helper module, constructed three independent temporary deployment copies, and exercised only Python parsing, bundle creation and a fake verifier. It returned the three outcomes quoted above and exited zero. The output was retained at `/tmp/qualification-audit-checks.json`; this is synthetic audit evidence, not a qualification report. No production file or proof source was mutated by those checks.

## Resolution checkpoint

The implementation owner fixed all three observations:

- `capture_scope` parses the Lean banner's version token and compares it exactly to the lock. Added tests reject `4.33.01`, `14.33.0` and `4.33.0-rc1`.
- `check_case_outcome` validates positive assurance and completion diagnostics; both real runner paths pass `request.publication` through `_append_result`. The producer now checkpoints a blocked report on a downgrade or missing Lean/nanoda/success marker. Tests cover each missing marker and full synthetic runner propagation.
- `_regressions` rejects contradictory expert, scientific and deployment approval fields. All three field mutations have regressions.

The audit independently reran the original three reproductions using the same temporary-fixture/mock-verifier mechanism:

```sh
PYTHONPATH=src .venv/bin/python /tmp/audit_qualification_followup.py
```

Fresh outcomes:

```json
[
  {"probe":"wrong_lean_patch_version","result":"rejected"},
  {"probe":"publication_assurance_downgrade","producer_status":"blocked",
   "offline_packet_status":"invalid"},
  {"probe":"approval_shaped_regression_record","mechanical_status":"invalid",
   "packet_approval":"pending","packet_scientific_review":"not_provided"}
]
```

The script asserted all three fail-closed outcomes and exited zero; its output is retained at `/tmp/qualification-audit-followup-checks.json`. Repeating the same three-file pytest command above after the fixes produced **77 passed in 1.05s**.

The follow-up reviewed these source identities:

| File | SHA256 |
| --- | --- |
| `src/physharness/verification/qualification.py` | `a4c4c156f764c5fa8170c2e805620a49025f25c41455c119762f6034806f3dd4` |
| `infra/run_qualified_lean.py` | `9717278932fc768b3a7d22bd4d5ceda77fda8a467acc94db444196d7f1be4476` |
| `tests/test_verifier_qualification.py` | `0b74d9d7de15ad60193df87e77b55b6ca2adbf47923a91ea4496e032afb9afc7` |

The implementation owner's `work/wave01/verifier-report.md` was not yet present at the last follow-up read, so its eventual handoff text is outside this audit. No broader test count reported by another agent is claimed as independently executed here. Final qualification still requires the root's real exact-scope reports and separately authorized human decisions; the audit's synthetic fixtures cannot supply either.

## Final delta follow-up after upstream 470a286 synchronization

The root requested a second bounded follow-up after probe diagnostic hardening, exact parameterized manifest-guard requirements and the upstream driver synchronization. This review covered the final delta in the probe, matrix, qualification parser and synthetic test metadata. The owner's report is now present and was read; its 221 passed/1 skipped result is accurately labeled owner-run evidence, not independently reproduced here. This supersedes the earlier handoff-text exclusion above.

No new actionable finding was identified. In particular:

- Returned probe exit/output is recorded before validation, so a nonzero process exit or malformed inner JSON remains inspectable in the blocked checkpoint. Inspection errors record the object kind and exit status with bounded sanitized context. Successful container/image inspection objects are not copied into the report. Configuration-validation errors use generic messages without environment values.
- The fixed inner probe emits only its fixed observations and source/binary hashes. The newly retained `probe_process.output` is therefore separate from the successful Docker inspection objects, whose `Config.Env` values remain absent.
- The matrix parser permits a bounded optional parameter suffix, while JUnit matching retains the exact full test name including brackets. It never strips a suffix or compares only the base test function. Duplicate full JUnit identities remain invalid.
- Tests adapt only copied synthetic metadata to the current driver digest, with an explicit synthetic-only comment. The added historical-metadata test rejects the old real image as a current scope. A direct byte comparison confirmed the current `container_driver.py` exactly matches `git show 470a286:src/physharness/verification/container_driver.py`; this follow-up did not modify it or any image evidence.

The same focused command was independently rerun:

```sh
.venv/bin/python -m pytest -q \
  tests/test_verifier_qualification.py \
  tests/test_verifier_boundary_probe.py \
  tests/test_qualification_diagnostics.py
```

Result: **87 passed in 1.30s**. These include the new exit/output preservation, failed-inspection context, successful-inspection environment withholding, exact parameterized-node and historical-driver rejection regressions.

Additional independent pure mutations ran with:

```sh
PYTHONPATH=src .venv/bin/python /tmp/audit_qualification_final_delta.py
```

The script substituted the required `[protocol]` JUnit case with the unparameterized name, a near sibling `[protocol_extra]`, and an already present sibling `[target_digest]`. Results were `incomplete`, `incomplete`, and `invalid`, respectively; none satisfied the missing exact guard. It also fed successful synthetic container/image inspection JSON containing an ordinary environment sentinel, then forced a read-only-configuration failure. The report was blocked, synthetic cleanup was recorded as removed, and the environment sentinel was absent from every persisted report byte. The script asserted each result, exited zero, and retained its synthetic output at `/tmp/qualification-final-delta-audit.json`.

Source identities at this final follow-up:

| File | SHA256 |
| --- | --- |
| `src/physharness/verification/qualification.py` | `e161b0730b44deb41edceccba937ee4860816c9c5c67ebe656ae50dd249dabc1` |
| `formal/qualification-matrix.json` | `081ed6158b06bdfc6ac80906ab2e6427790fa0d16beeb25221c4158fe1346bcb` |
| `infra/run_qualified_lean.py` | `9717278932fc768b3a7d22bd4d5ceda77fda8a467acc94db444196d7f1be4476` |
| `infra/probe_verifier_boundary.py` | `e77b80d7edc8460fbec3cb0434b1c36eac5c5d9f5410c103082ea05072314aeb` |
| `tests/test_verifier_qualification.py` | `7f58eeabb1779f75e6627142ceb12ee3cef0188866b996f40628a62c9c3b5a40` |
| `tests/test_verifier_boundary_probe.py` | `ff9679798d8e24a6b507635c171ed61197f82320f657758853d70c86b8c892b7` |
| `src/physharness/verification/container_driver.py` | `0aa043a827abe8dd79960b59e3fcd3d249f5b0600e5e2c68aeb6dfb69e34445f` |
| `work/wave01/verifier-report.md` | `0d18ceb3f49292cdc9bbf0ec8c1cef971eaa701108fc6f2e44d1b0be47a57803` |

No Docker command, VM action, real syscall probe or Lean execution was performed in this follow-up. Real aggregate/build evidence and human qualification remain the root/operator's separate work.
