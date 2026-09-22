# Local Temporal integration evidence

- Date: 2026-09-14; Darwin arm64; Python 3.12.13; temporalio Python SDK 1.32.0.
- Pinned official Temporal CLI: v1.8.3. Release source: https://github.com/temporalio/cli/releases/tag/v1.8.3
- Command: `PHYSHARNESS_RUN_TEMPORAL_TESTS=1 .venv/bin/python -m pytest tests/test_temporal_integration.py -q`
- Result: **1 passed in 3.38 seconds** against a real local Temporal dev server with SQLite persistence.
- Executed TaskWorkflow and VerificationWorkflow through an actual worker and engine, with scripted test-only activities.
- The scripted verification outcome stayed blocked with `verifier_unavailable`.
- Default sandbox attempt failed fetching the official binary; network/loopback permission was then granted and the test passed.
- This was **not** a hosted-model, Lean-kernel, managed-cloud, fleet, recovery-endurance, or scientific-success trial.
- Default unit suite explicitly skips this integration test unless opted in. A skip is not a qualification pass.

Final rerun, 2026-09-15 UTC: the same pinned real local server test passed in 6.52 seconds using
the new explicit sandbox runner. The OpenHands/Beartype compatibility regressions separately
prove that workflow reload and file/socket/wall-clock restrictions remain enforced. The default
aggregate still skips this opt-in engine test and the unavailable live PostgreSQL test.
