# First live pilot operator helpers

These commands operate on the two existing reviewed-target identities documented in
`work/first-pilot-review.md`. They create **new experiments only**. Repeating one target and
attempt name returns the same experiment through the canonical idempotency service. Use a new
attempt name after a failure or crash to obtain a fresh experiment, branch, task and model
context. Earlier experiments and receipts remain intact. There is no budget amendment command.
Preparation requires the existing target's canonical review to remain approved and bound to
the same target revision. It checks 24 turns, 16,384 output tokens per response, 96,000 total
tokens, and 1,800 seconds in both the central envelope and runtime limits.

The operator, in their own shell, sources the private `.state/runs/first-pilot/operator-env.sh`
and selects `pilot_role operator`. Run it from the repository worktree with the private pilot
environment loaded. The `prepare` command resolves the operator through the canonical
`local_authority` service, which may read its configured private auth store. The helper does
not open credential files directly or print configuration:

Failures print only the command stage and a fixed diagnostic code such as
`CONTRACT_MISMATCH`, `REVIEW_MISMATCH`, or `CAMPAIGN_MISMATCH`; raw exception values are omitted.

```sh
uv run python work/live-pilot-2026-09-23/operator_helpers.py prepare projection --attempt attempt-01
uv run python work/live-pilot-2026-09-23/operator_helpers.py prepare purity --attempt attempt-01
```

The output includes each new experiment ID. For each ID, run `uv run phys check-run ID`
before `uv run phys run-team ID --concurrency 1 --max-tasks 1 --timeout-seconds 1800`.
Keep a run-team JSON stdout file in the private pilot run directory; it can include detailed
run data and should not be placed in `work/` or a commit. Run the second target only after
checking whether the projection has an independent-kernel verified receipt and reusable source.

The snapshot command uses SQLite URI read-only mode and writes an allowlisted `status.json`.
Supply the explicit private pilot database path and the **new** experiment IDs:

```sh
uv run python work/live-pilot-2026-09-23/operator_helpers.py snapshot \
  --database .state/runs/first-pilot/private/PILOT_DATABASE_FILE \
  --projection-experiment PROJECTION_NEW_ID --purity-experiment PURITY_NEW_ID \
  --output .state/runs/first-pilot/status.json
```

It records a UTC `captured_at` timestamp and reports status and counts, cumulative saved-session
input/output tokens, central ledger amounts, receipt IDs/status/codes/assurance and allowlisted
checker versions, and output/report artifact IDs. It omits source, artifact bodies, model prompts, native context, diagnostics,
configuration and credentials. Do not treat a snapshot as a proof decision; inspect canonical
receipts and exact artifact/review bindings through the authorized console before claiming a
verified result.

The run-report extractor accepts **only JSON stdout** from `phys run-team` and writes a safe
summary with the report artifact reference, output artifact references, receipt IDs/status/codes,
and central accounting:

```sh
uv run python work/live-pilot-2026-09-23/operator_helpers.py report \
  --input .state/runs/first-pilot/PRIVATE_RUN_TEAM_STDOUT.json \
  --output .state/runs/first-pilot/report-summary.json
```

These helpers never call a model, verifier, VM or external provider. The operator controls
launch, private credentials, the proposed verifier registry activation, crash audit and any
fresh retry.
