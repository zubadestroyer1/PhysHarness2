# Registry resource-source repair

The registry now requires an absolute `resource_profile` file path per entry. Its shared constructor reads the bounded, non-symlink source, strictly parses it, and compares the actual raw SHA-256 and canonical profile digest with both the entry's `ComparatorConfig` and its `LinuxQualification`. Direct construction and `from_file` therefore share this startup boundary. Existing bundle, selector, policy-source and qualification checks remain in place. Legacy registry JSON without the path fails validation; operators must add the path to each entry.

Tests use temporary profile files. They cover valid routes, legacy and relative paths, whitespace-only byte changes, changed values with and without updated raw hashes, symlinks, missing files, oversized files and duplicate keys. Invalid input fails during construction before a route is exposed. The qualification matrix now includes the source-binding regressions.

Verification from this worktree:

- `.venv/bin/pytest -q tests/test_verifier_registry.py tests/test_verifier_resource_bootstrap.py`: 32 passed.
- `.venv/bin/pytest -q tests/test_verifier_registry.py tests/test_verifier_resource_bootstrap.py tests/test_verifier_qualification.py`: 94 passed.
- `.venv/bin/pytest -q tests`: 809 passed, 4 skipped; existing dependency deprecation warnings.
- `.venv/bin/ruff check src/physharness/verification/registry.py tests/test_verifier_registry.py`: all checks passed after formatting correction.
- `.venv/bin/python -m json.tool formal/qualification-matrix.json >/dev/null`: passed.
- `.venv/bin/python -m py_compile .state/wave01/capture_final_scope_8g.py .state/wave01/assess_evidence_8g.py`: passed.
- `git diff --check`: passed.

Tracked files changed: `src/physharness/verification/registry.py`, `tests/test_verifier_registry.py`, `formal/qualification-matrix.json`, `docs/VERIFICATION.md`, `docs/FIRST_LIVE_RUN.md`, and this report. Ignored local operator helpers changed: new `.state/wave01/capture_final_scope_8g.py` and updated `.state/wave01/assess_evidence_8g.py`.

The new helper writes `scope-final.json`, `regressions-final.xml`, `regressions-final.json` and `scoped-regressions-final-8g.log` with exclusive creation; the assessor reads the final scope and regressions. Neither helper was executed. The earlier `scope.json` and `regressions.xml`/`regressions.json` remain intact as historical evidence and are superseded for the final source. No Docker, Lean, GitHub, or live checker execution was performed here. Root controls the final Linux evidence capture and assessment.
