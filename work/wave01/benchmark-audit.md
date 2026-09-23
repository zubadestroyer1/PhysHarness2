# Independent benchmark workflow audit

Audit scope: `src/physharness/science/physics_benchmarks.py`, `src/physharness/science/benchmark_artifacts.py`, and `tests/test_physics_benchmarks.py`, against Task 4 and the manifest contract in `docs/superpowers/plans/2026-09-15-wave01-qualification.md`. This was a read-only implementation audit: no implementation or test files were edited, no Lean or Docker was run, and no scientific approval is issued. Temporary probe packages used the tests' explicitly synthetic report fixtures.

The initial snapshot had two package/identity integrity findings and one malformed-input robustness finding. Root implemented fixes during the audit; the fresh recheck below closes the three reproduced defects and the mutable-container observation. The final targeted recheck also closes strict rejection of unexpected manifest keys. No actionable finding remains open within this bounded audit scope. There is no demonstrated path that changes the assessment's returned scientific review from pending to approved.

## Initial findings and reproductions

### P2 — Bind the family field to the task-ID family

Location: `physics_benchmarks.py:98` and `physics_benchmarks.py:104`.

The manifest contract specifies `program.family.slug`, but the validator only verifies the program prefix. Holdout isolation uses the independently supplied `family` field. Consequently a task named `quantum.gates.other` with `family="gates_alias"` and `split="holdout"` is accepted beside `quantum.gates.involution`, `family="gates"`, `split="development"`. A family-label typo or inconsistent author metadata therefore bypasses the promised family split check while preserving the same ID namespace.

Reproduced with the test collection, a deep copy of its positive task, a new ID, a distinct target-source comment, and the changed family/split. Construction returned both tasks without an error:

```text
FAMILY_MISMATCH_ACCEPTED [('quantum.gates.involution', 'gates', 'development'),
                         ('quantum.gates.other', 'gates_alias', 'holdout')]
```

Recommendation: validate the positive ID structure and require its family component to equal a suitably constrained `family` value, then retain the existing split check. Add separate tests for inconsistent ID/family metadata and a genuine same-family cross-split pair. This cannot discover two differently named but mathematically related families; that remains scientific review.

### P2 — Reject modified status fields in the evaluator manifest

Location: `benchmark_artifacts.py:224` through the manifest/file checks at `benchmark_artifacts.py:237`.

Assessment reconstructs every hashed artifact, which is useful, but only checks three fields of `manifest.json`: schema, benchmark digest, and files. The manifest itself is outside its file hash mapping. Changing its generated `scientific_review` to `"approved"` and `production_qualified` to `true` still yields `mechanical_status="expected_outcomes_observed_in_both_kernel_modes"`. Additional manifest keys are likewise not checked. This lets a modified packet with contradictory approval labels pass the packet-integrity assessment.

Reproduction: prepare the synthetic package/reports, mutate only those two manifest fields, and call `assess_benchmark_reports` with unchanged sources and reports. The call succeeds. The returned assessment still correctly says `scientific_review="pending"`; the defect concerns accepted artifact integrity and contradictory exported metadata, not an unauthorized scientific approval in the returned object.

Recommendation: validate the entire manifest against an explicit strict schema or compare it with the full reconstructed generated manifest, including literal pending/false authority fields. Add tests for both changed authority fields and an unexpected manifest field.

### P3 — Malformed nested fixture data escapes the coded-error boundary

Location: `benchmark_artifacts.py:234`.

Changing `cases.json` to contain `"project_files": []` causes an `AttributeError` at `.items()` before artifact hash mismatch validation. The public function catches `KeyError`, `TypeError`, `ValueError`, and `OSError`, but not this exception. The malformed packet is not accepted, but callers receive an unhandled implementation exception rather than the documented `physics_benchmark_evidence_invalid` `HarnessError`.

Reproduced output:

```text
MALFORMED_NESTED_FIXTURE_ERROR AttributeError 'list' object has no attribute 'items'
```

Recommendation: validate JSON object/list shapes before invoking mapping methods, preferably using a strict fixture schema. Add malformed nested-shape tests that assert the stable `HarnessError` code. Merely catching `AttributeError` would hide this instance but is less clear than validating the expected input type.

## Lower-priority hardening observations

### Mutable containers can bypass the already-run identity validator

`PhysicsBenchmark` inherits a frozen Pydantic model, but its collection/task lists remain mutable. `release.collections[0].tasks.append(release.collections[0].tasks[0])` succeeds and `discovery_tasks("development")` then returns duplicate IDs. Canonical revision hashing does see the mutation; this is not a stale-hash bypass. The risk is an in-process caller assuming that a validated frozen object retains its identity invariants. The normal CLI path that loads and immediately consumes a fresh collection does not expose this through JSON alone. Consider immutable tuple fields or revalidation at export/package boundaries; add a post-construction mutation regression if immutability is intended as an API guarantee.

### Symlink checks omit the supplied root or a loader's parent alias

`load_physics_benchmarks([alias / "quantum.json"])` accepts a directory symlink `alias` pointing at a real directory containing a regular file. `assess_benchmark_reports(..., bundle_link, ...)` also accepts a symlink used as its bundle root. The imported `safe_read` checks descendant path components but does not inspect its `root` argument; the existing verifier `_PinnedRunner._bundle` performs its own root check before using that helper. The new tests cover only a symlink at the final collection filename.

Both aliases were reproduced with temporary directories. Exact artifact bytes and source hashes are still checked, so these probes do not demonstrate altered-source acceptance. Clarify the intended filesystem policy and, if trusted roots must be real directories, check/canonicalize them explicitly before calls to `safe_read`. Add root/parent symlink coverage consistent with that policy; avoid inadvertently rejecting standard platform aliases such as macOS `/tmp` without an explicit policy decision.

## Checks and positive observations

Fresh command:

```sh
PYTHONPATH=src .venv/bin/pytest -q tests/test_physics_benchmarks.py
```

Observed result: **24 passed in 0.13s**. This agrees with the supplied `benchmark-evidence-green.log` count. These tests and all custom probes use synthetic evidence; they establish validator behavior, not execution of any prover.

The custom probes imported only the test fixtures with `importlib.util`, created disposable directories with `tempfile.TemporaryDirectory`, made the explicit mutations above, and called the public model/assessment APIs. No persistent evaluator package, implementation source, or original evidence report was changed.

The reviewed code keeps author-supplied approval fields out of typed tasks, reconstructs and compares exact challenge/reference/discovery/review artifact bytes, binds outcomes to target/source/environment hashes and checker versions, checks both requested kernel modes and assurance, rejects duplicate/missing report rows, requires ordinary nonzero comparator exits and expected negative diagnostics, and checks cleanup statuses. The returned inventory consistently leaves scientific review pending, production qualification false, difficulty uncalibrated, and contamination unresolved. The discovery allowlist omits references, outlines, shortcuts and negative cases; its export is a copy. The full evaluator package explicitly warns that keeping a target-only JSON file alongside references does not isolate a discovery worker.

Negative causality is checked through operator-supplied comparator logs and expected substrings, with a candidate-construction marker. This is scoped report consistency, not report authentication or a proof that arbitrary log text is trustworthy. The helper is documented as consuming operator-supplied observations and does not claim deployment qualification; a trusted evidence-production path remains required. No claim of mathematical review or universal verifier soundness follows from this audit.

## Audited source identities

| File | SHA-256 |
| --- | --- |
| `src/physharness/science/physics_benchmarks.py` | `34189cdb53e414de2fb1628410bd50f2ae943bce07f07f379c30e4705ce0063f` |
| `src/physharness/science/benchmark_artifacts.py` | `608e1f251903539a24d4c99feb514910c5ebf6aa5a5e185f0bba2d2c7150895a` |
| `tests/test_physics_benchmarks.py` | `4832eeda3189fd4493724d21d64d3a597ceb3f1d161671ea69bae7e7fb6f6f23` |

These hashes identify the inspected snapshot. Root may change the implementation during its independent work; fixes require a fresh check before closing the findings.


## Fix recheck and CLI extension

Root implemented ID/family binding, fresh model snapshots/revalidation at read/export/package boundaries, manifest authority-field validation, and explicit nested project-mapping shape checks. The repeated original probes now reject the family mismatch, reject mutable duplicate IDs at digest/inventory/discovery boundaries, and return `physics_benchmark_evidence_invalid` for the changed standard authority fields and malformed nested mapping. These close the originally demonstrated P2/P3 defects and mutable-container observation. Adding an unexpected manifest key still succeeded in this specific recheck, so full strict manifest-key validation remained a follow-up recommendation; no value from that extra field was promoted into the returned assessment.

Root clarified that input/output roots are operator-chosen local paths and the package tools do not claim to be a hostile-filesystem sandbox. The symlink probes demonstrated aliases only, with exact bytes still checked, and no traversal beyond authorized operator input. Accordingly, root/parent aliases are documented as a filesystem-scope limitation rather than an open vulnerability. Descendant symlink checks and exclusive output creation remain applicable.

The audit was extended briefly to `tools/physics_benchmark.py` and `tests/test_physics_benchmark_cli.py`. `write_fresh` uses exclusive `xb` creation; the duplicate-export test confirms an existing file's bytes are preserved. Preparation remains exclusive through `prepare_benchmark`. Inventory, export, preparation and assessment output retain pending scientific review, with no new approval command. The target export uses the same evaluator-free allowlist and explicitly notes the separate storage/network isolation requirement. No additional CLI finding was found in this bounded review.

Fresh command:

```sh
PYTHONPATH=src .venv/bin/pytest -q tests/test_physics_benchmarks.py tests/test_physics_benchmark_cli.py
```

Observed result: **33 passed in 0.85s**. Original reproductions were rerun independently of those new tests and produced the rejection behavior above. No real verifier execution occurred during this code audit.

| Rechecked file | SHA-256 |
| --- | --- |
| `src/physharness/science/physics_benchmarks.py` | `236adb43dfd8036cdcb314240348dc63af3665378052f059d3e5f4d0537cc44d` |
| `src/physharness/science/benchmark_artifacts.py` | `8b22deba054a9d81ddd1508857cb59db9ed4df5ef4dbd53d62bffeba457e534f` |
| `tests/test_physics_benchmarks.py` | `2c434dae334941c9bab06d968b0dda7a08474578da11dbf9630566bf79a6f525` |
| `tools/physics_benchmark.py` | `1eeb2f7a9a5301a0a893067bf947ed72c9c00e297c039110616a7a63245d8961` |
| `tests/test_physics_benchmark_cli.py` | `61107fb65a78fb27857ac9f8a928b33e2490867a3d0444b4a2cf6f11f8970e9c` |


## Final manifest-key closure

Root added an exact expected-key-set check for `manifest.json` and a `manifest_extra` regression. Independent source inspection confirms that any unexpected key is rejected before package assessment, including extra fields that purport to carry an approval decision. The earlier manifest-extra hardening note is **closed**.

Fresh targeted command:

```sh
PYTHONPATH=src .venv/bin/pytest -q tests/test_physics_benchmarks.py -k malformed_package_metadata
```

Observed independent result: **4 passed, 26 deselected in 0.23s**. A separate temporary-package probe inserted `untrusted_extra_approval="approved"` into an otherwise valid synthetic manifest; `assess_benchmark_reports` rejected it with the expected `physics_benchmark_evidence_invalid` `HarnessError`. Root's `.state/wave01/benchmark-final-unit.log` was also inspected and records **34 passed in 0.77s** for its broader run. That broader count is root's recorded run; the independent final execution was the targeted four-case set plus the separate probe.

Final inspected SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `src/physharness/science/benchmark_artifacts.py` | `b0931cff158e0b9f7f6a41237eab34e5437b238c8f05c7e645d4cf52fab70d62` |
| `tests/test_physics_benchmarks.py` | `0dadec8b14775dbd971067bb04e86ae37463a0edf18cd910d98a9589479eff43` |

All concrete findings from this bounded code audit are now closed or, for operator-chosen root aliases, explicitly scoped as a limitation without a demonstrated unauthorized traversal. This conclusion is an engineering audit result; no scientific approval, prover acceptance, or deployment qualification is issued. No implementation, benchmark source, Docker state, or original evidence was changed in this final recheck.
