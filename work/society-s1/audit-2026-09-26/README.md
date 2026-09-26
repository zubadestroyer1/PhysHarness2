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

The audit reads the private run state (`.state/s1/arms/<arm>/`: databases and exports), which is not in the repository. The scripts are archived exactly as they ran, in the git-ignored layout `.superpowers/live-run/audit/{extract.py,scripts/}`, and their paths assume that layout: they do not run from this directory. From the root of a checkout that has the run state:

```sh
A=.superpowers/live-run/audit
mkdir -p $A/scripts/tools_out
cp -R work/society-s1/audit-2026-09-26/scripts/. $A/scripts/
mv $A/scripts/extract.py $A/extract.py
export PYTHONPATH=src:tests:$A/scripts/scaffold
ARMS="calibration-doeblin-r2 calibration-aperiodic pilot-doeblin S-r2 I-01 I-02 I-03 I-04 I-05 I-06 I-07 I-08 single"
python $A/extract.py                         # dataset: $A/data/<arm>/*.jsonl, data/sanity.json
python $A/scripts/extract_calls.py $ARMS     # call cache for the society and proof-path scripts
python $A/scripts/proofpath_proofs.py $ARMS  # accepted proofs: $A/scripts/out/proofs/
```

Then run each report's scripts in the order its method section lists:
- society.md §6, whose scripts take arm names;
- timecost.md §12;
- tools.md §8, running `tools_shell.py` before `tools_misc.py`;
- proofpath.md;
- scaffolding.md, which needs `tiktoken` and its o200k_base vocabulary.

`extract.py` is deterministic and reconciles tokens and cost exactly with each arm's budget ledger. A re-run reproduces every output byte for byte, except:

- `out/checkpoints.json`: CPU timings are re-measured.
- `tools_out/search_rows.json` (search_library hit counts) came from an inline pass that was not kept (tools.md §8).
- Scaffold outputs: one calibration-aperiodic session is now split differently. The re-run gives 17.3% fixed ($96.1), a 2.5% problem share and an $80.8 saving, against the reports' 17.2%, 2.4% and $80.6.
- Some figures came from inline queries that were not kept:
  - the $56.46 of root spend after the last contribution (`proofpath_idle.py` gives $67.37 by first-compile dating);
  - the 57 "platform glitch" calls;
  - check-ins acted on (49 of 250);
  - the 91 failed local compiles and $22 of node turns;
  - the 92% `rg` hit rate.

All run data was read read-only, and no credentials were read. Transcript text passes through a redactor that replaces the repository path, `/Users/<name>` and `/home/<name>` segments, and `org-`, `sk-` and `Bearer` tokens.
