# Four-arm operator helper

`pilot_ops.py` is an explicit one-shot launcher. It reads a private JSON config with exactly the fields in `launcher-brief.md`, plus `private_directory/operator.token` and `private_directory/auth.json` for an issued operator identity. It does not prepare targets, review them, create schemas, or start work unless called with `launch`. The model key must be supplied externally as `OPENAI_API_KEY`.

Invocation from the worktree:

```sh
PYTHONPATH=src .venv/bin/python work/parallel-pilot-2026-09-24/pilot_ops.py launch --config .state/parallel-pilot-2026-09-24/config.json
PYTHONPATH=src .venv/bin/python work/parallel-pilot-2026-09-24/pilot_ops.py status --config .state/parallel-pilot-2026-09-24/config.json
```

The helper validates four unique canonical experiments, the exact quantum/classical independent/collaborating pairs, model parameters, runtime limits, two-worker envelopes, conservative gpt-6-sol prices, and the $99.80 arms plus $0.20 probe ceiling. It refuses prior result files or any arm already started. It uses a stable private `flock`, preflights each arm at concurrency two, then configures the 128-task workforce cap, seeds via canonical Activities, and runs a 24-hour TeamRunManifest with 128 verification slots. It stops on a blocked preflight, a failed supervisor, or uncertain ledger usage. Results stay in the private results directory; the atomic status file contains only counts, ledger totals, receipt metadata, and safe error codes. `status` reads that file without connecting to the service.

Validation: `75 passed, 1 skipped` for helper, preflight, timeout, settlement, CLI, core, and workspace-service tests. Ruff passes on the edited Python paths. The CLI `--help` completed. No live model, Docker VM, or verifier execution was run.

Limitations: the helper intentionally does not resume any partially started arm or reconcile unknown cost. An operator must inspect the durable records and approve any subsequent recovery. The status file is a metadata snapshot updated every 10 seconds while the supervisor runs, so the canonical database remains authoritative after a process crash.

## Post-run reporting correction

After the four-arm live run finished, the status-only `delegation_count` calculation was corrected to count canonical `delegated_from_task_id` or `reply_to_parent_task_id` once per task. The prior calculation used a nonexistent `parent_task_id` field. This changes future status snapshots only; it did not alter the completed run, canonical database, or supervisor results. The focused regression covers a root, attached child, and detached child; `8 passed` and Ruff passed.
