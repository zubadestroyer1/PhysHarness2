# S1 live-run audit (2026-09-26)

Start with [AUDIT.md](AUDIT.md), which consolidates the whole audit: the bottlenecks, what worked, and a ranked roadmap for scaling. The five dimension reports behind it are:

| Report | Question |
|---|---|
| [timecost.md](timecost.md) | Where wall-clock time, tokens and money went; infrastructure and harness overhead |
| [society.md](society.md) | Coordination mechanics (task economy, commons, communication, critical path) and their value |
| [tools.md](tools.md) | Tool friction and the agent–harness interface |
| [proofpath.md](proofpath.md) | How the proofs were actually found; dead ends; implications for harder problems |
| [scaffolding.md](scaffolding.md) | Fixed scaffolding overhead and a proposed lean configuration |

The run results are in [../results-2026-09-26/REPORT.md](../results-2026-09-26/REPORT.md).

## Reproducing

The audit reads the private run state (`.state/s1/arms/<arm>/`: databases and exports), which is not in the repository. From a checkout that has that state:

1. `python scripts/extract.py` builds the normalized per-arm dataset: sessions, turns, tool calls, tasks, messages and workspace operations. It reconciles tokens and cost exactly with each arm's budget ledger.
2. The `scripts/*.py` files compute the numbers in each report.

When the scripts ran, they read the dataset from `.superpowers/live-run/audit/data/`, a private, git-ignored directory. Some report paths refer to that location.

All run data was read read-only, and no credentials were read. Text taken from transcripts passes through a redactor that removes local paths and secret-like strings.
