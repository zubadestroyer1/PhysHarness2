# Source search/read repair — 2026-09-24

Search now returns a canonical `path` (`mathlib/...` or `physlib/...`) that can be passed unchanged to `lookup_library_source`. The absolute VM location is retained separately as `guest_path`. Read results preserve the canonical path on success and missing-file errors, so their path can also be reused.

Both tool descriptions explain the contract. Invalid paths produce `UNSAFE_PATH` with a usable example. Absolute paths, traversal, empty components, bare module paths, non-Lean suffixes and embedded NUL are rejected before execution. Existing historical absolute paths require a fresh search or an explicitly canonical path; the reader does not silently broaden its accepted paths. The pinned, read-only library trust boundary is unchanged.

GPT-6 Sol implemented the bounded fix with failing regressions first; root reviewed the exact before/after diff and tests, replaced a brittle proposed VM test query with pinned declaration queries, and independently ran verification. No unrelated code was reformatted or reset. See `fix.patch`, the baseline snapshot, and `source-hashes.json`.

Validation:

- Full Python suite with local Temporal enabled: **1,097 passed, 8 opt-in skips, 21 upstream warnings** (`full-suite.log`). Skips concern separately configured PostgreSQL and VM endpoints; this run does not claim to rerun those unrelated database/VM checks.
- Dedicated pinned VM search/read test plus its host regressions: **13 passed** (`real-roundtrip.log`). The test searched both actual Physlib and Mathlib source trees, passed returned paths unchanged to lookup and repeated lookup, and checked content/hash consistency. This covers the new opt-in skip from the full suite.
- Ruff lint for both changed files and `git diff --check` passed.
- No paid model calls or new experiments were launched. Frozen pilot results and their source manifest remain historical evidence; this repair is a newer source revision, not retroactive qualification of that run or a fresh full acceptance-boundary qualification.

The harder-problem assessment is separate: see `../next-physics-problem-2026-09-24/RECOMMENDATION.md`. A proposed problem is not empirically calibrated or accepted merely because its mathematical statement is written.

After testing, Docker listed no remaining containers and `colima list --json` confirmed the dedicated `physharness-pilot` VM is **Stopped**. The prior monitor remains paused.
