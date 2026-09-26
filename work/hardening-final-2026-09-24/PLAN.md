# Harder physics and long-horizon qualification

User authorized implementation, audit, qualification, and a final live test on 24 September 2026. GPT-6 Sol agents implement; root owns design, scientific review, integration and acceptance decisions. The existing dirty worktree and historical evidence are preserved. No source commit, push, publication, new cloud deployment, or fleet claim is part of this run.

## Intent and success criteria

Address observed causes, not merely suppress their errors. A helper must be able to run while roots remain active; valid tools and recipient IDs must be discoverable without disclosing private records; repeated handoffs must have durable, checkable lineage; compaction/recovery must preserve exact scientific state and avoid duplicated external effects. The physics target must involve materially more mathematics than the scalar decay bound. A complete private reference and perturbed-statement controls must pass independent verification before a model receives the target. Actual difficulty is an empirical finding, not guaranteed by the target's name or length.

## Design decisions

- Keep model choice of method, collaborators, decomposition and whether to yield. Do not force a proof outline or dummy work to inflate time.
- Use the existing portfolio and opt-in research-directory contracts to publish minimal root routing profiles. Do not silently publish private objectives, transcripts or helper findings.
- New cooperative test: two roots, four maximum active workers, shared experiment budget. Reserve the two extra slots for model-requested work by seeding only two roots. Existing wait-for-tasks can release a parent's slot when capacity is full; describe this behavior accurately and test it.
- Hide tools that cannot succeed for a task's immutable role/sharing contract. Retain server-side checks for stale or malicious tool calls. Detached work must know how it can publish evidence and when it cannot return a joined result.
- Add immutable per-ordinal continuation evidence with atomic issue, consumption and first-successor binding. Preserve canonical checkpoints and artifacts; validate complete chains instead of accepting `handed_off` as a success label. Historical one-handoff records remain attributable and readable.
- Test interrupted compaction at real persistence boundaries with deterministic provider fixtures. Recover only provably local, settled operations; never resend an uncertain billed request. Distinguish replay tests from live provider compaction and never count simulated activity as live science.
- New target: arbitrary finite nonlinear Duffing network with non-diagonal symmetric coercive stiffness, heterogeneous mass/damping, nonnegative quartic potential and bounded vector forcing. Prove a uniform exponential energy bound plus forcing remainder. Physical ODEs and coercivity are assumptions; the target or its Lyapunov estimates are not assumptions. A private reference is withheld from all worker stores/images/retrieval.

## Work and acceptance ledger

- [x] A — Task-aware tools and timely helpers. Owner exponential_science_audit. Files: research_worker.py tool/prompt section after CanonicalRuntimeStore, relevant workforce/collaboration feedback, focused tests. Reproduce invalid return/message affordances and helper starvation. Prove helper execution before root completion with spare capacity and optional yielding at full capacity; inspect visibility under all sharing policies. No new scheduler unless a reproducible scheduler fault requires it.
- [x] B — Durable repeated continuation and compaction recovery. Owner exponential_runner. Files: continuation.py, CanonicalRuntimeStore portion of research_worker.py, execution/responses.py when evidence justifies it, new lineage module, surgical service export/access rules and tests. Prove at least three same-task handoffs, multiple tasks, stale/cross-scope rejection, pre/post-consumption crash recovery, no duplicate provider/tool effects and scientific context retention. Generalize export/audit with exact lineage evidence.
- [x] C — Hard target and reference. Owner exponential_reference. Private evaluator files only; safe target-design note. Independently derive constants, probe pinned library APIs, compile complete proof without holes/extra axioms, and run positive plus altered-statement/hidden-hole controls through Comparator and independent kernel. Root reviews target semantics separately.
- [x] D — Integration and root audit. Inspect actual diffs against this round's baseline, targeted regressions, full suite, authority/cost checks, real VM multi-workspace restore and capacity checks. Refresh source-bound qualification only after source stabilization. Resolve substantive findings before paid work.
- [x] E — Fresh live experiments. Prepare isolated stores and explicit budgets; first difficulty calibration, then cooperative trial if target qualification and runtime gates pass. Record actual collaboration timing, model/Lean errors, compaction vs handoff, target binding, first proof time, costs and useful partial results. Do not label an easy result as hard or skip failed/unsolved trials.
- [x] F — Final audit and shutdown. Hash-check exports, reconcile every live/retired ledger and external operation, verify all worker containers removed, stop the dedicated VM and pause the monitor. Report limits, failures and remaining scale gates.

## Resources and isolation

Historical conservative spending is $43.762893 against the original $100 authorization. New work receives at most $52 in aggregate model reservations/spend, leaving additional headroom; all new failures and probes count. An initial single-agent calibration may use up to $14; the main cooperative trial can use only the unspent balance of the new $52 envelope. Reconcile provider uncertainty before reserving a subsequent trial. There is no lifetime token limit; retain 256k active context/64k maximum output and appropriate native compaction policy. Use up to two hours per research attempt within its budget rather than an artificial short timeout.

Host read-only audit found 64 GiB RAM and 18 logical CPUs. Dedicated `physharness-pilot` VM is configured with 20 GiB and 12 CPUs for four 2-GiB/2-CPU workspaces, one 8-GiB/4-CPU verifier and overhead. Preflight must check actual daemon capacity and strict isolation. This does not qualify cloud execution or 128/1000 workers. Stop the VM when testing finishes.

## Review focus

1. Repeated or branched lineage, missing checkpoints, stale target/review, orphan successor, unfinished child and wrong worker fence must remain loud failures.
2. Sharing-none/verified policies and detached tasks must not gain cross-branch privileges through tool filtering, directory publication, return messages or compacted summaries.
3. A helper slot is actual capacity, not a label; test scheduling while both roots are still alive and account for detached work continuing after parent proof.
4. Resuming after a saved response/usage boundary must neither bill a second time nor replay a non-idempotent tool. Pending external outcomes stay uncertain.
5. Target fairness: fixed definitions and explicit physical assumptions, no reference leakage, no hidden holes, no claimed runtime/novelty from an uncalibrated target, no theorem-specific solution scaffold in worker instructions.

## Root audit updates

Task-aware tools and helper capacity received independent source review. Root reran `tests/test_research_tool_contracts.py`: 6 passed. These tests cover opted-in peer routing, sharing-none/verified restrictions, backend rejection of invalid calls, helper execution while both roots remain active, and optional parent yielding. This is deterministic integration evidence, not measured live collaboration benefit.

The continuation audit identified additional cases to close before launch: every terminal session must have a checked checkpoint, stale compaction markers must not reference earlier responses, the original pre-marker crash window must be reachable through controller recovery, and malformed or over-limit provider responses must remain blocked. Implementation and regressions are in progress.

Current-source verifier qualification `attempt-hardening-20260924-01` exited 0 with all ten mechanical checks satisfied, scope SHA256 `080a8bb7662311045687352c355c8cfdebe55342d49251c1b51970419dcd94cf`. This is private-pilot engineering evidence; production qualification remains false and the new scientific target still needs its separate complete-reference checks.

Root independently reran the combined context/continuation/tool suites: 96 passed. Full-suite attempt 01 stopped at collection because the in-progress pilot test imported a launcher file not yet written; preserve the log and rerun after package completion. The reference compiler also revealed real proof elaboration errors when its running process was finally awaited; earlier partial status was corrected, and no paid launch is authorized until the complete proof passes.

Read-only budget recheck reopened all ten historical attempts: total prior conservative spending remains $43.762893, all reservations settled, zero active workers/reserved tokens, all experiments stopped without budget reconciliation flags. Details: historical-budget-recheck.json.

Full-suite attempt 03 completed successfully after fixing the schema-only API probe: **1,170 passed, 13 skipped, 21 warnings**, exit 0. Attempt 02 is retained with its four genuine probe-compatibility failures. Root also checked the current verifier scope after the final lineage binding change; the verifier-specific scope remains an exact match. Pilot wrapper dry-runs and probe regressions independently passed 15 tests before the full run. Real four-worker capacity/restore and scientific-reference qualification remain separate pending gates.

## Live launch gates completed

The complete reference and hole control passed `target-independent-01.json`. All three altered-statement/definition controls passed `target-controls-independent-02.json` with independent-kernel verification of the positive anchor. The first controls report is retained: all attacks were rejected, but one expected diagnostic was incorrect; only the fixture diagnostic was corrected. No target or proof was changed.

The four-worker VM observation passed with overlapping real worker commands and verifier activity, fifth-worker admission rejection, three archive/restores with exact file preservation and fresh identities, stale-identity rejection, cancellation cleanup, zero observed OOM events and no remaining containers. This qualifies only the measured local setup.

Calibration launched with a $14 ceiling and exact source freeze over 132 files. A subsequent live check found all hashes matching. The model receives the target and ordinary library access, with no evaluator derivation or reference solution. The cooperative trial remains contingent on calibration settlement, complete export/lineage audit, and the remaining balance of the aggregate $52 round allocation.

## Live fault findings and corrective follow-up

Calibration ended after 274.49 seconds with unverified partial findings and no receipt, despite remaining resources. Its $1.47013 spending and 224 exported artifacts reconciled. Runtime/task completion is explicitly not scientific completion. The cooperative phase retains the same exploratory objective; it is not a matched-budget experiment.

The cooperative trial demonstrated live helper execution while both roots were active and acknowledged pre-submission idea exchange, then revealed request-validation failures. `run_command` with `cwd=/work` was rejected before dispatch but incorrectly terminalized a root session as uncertain. A helper used an absolute path with `read_workspace_file`; this path was rejected only after a workspace-operation marker, causing unnecessary workspace reconciliation. Preserve the frozen trial; correct the common pre-dispatch validation boundary and model-facing path guidance, with regressions proving continued valid use and unchanged treatment of genuine external uncertainty. Coding tests may be prepared while remaining workers execute; core changes wait until the frozen trial ends. A fresh retry requires exact source-amendment review, all failed attempts retained/reconciled, and only the remaining balance of the round's $52 envelope.

## Fresh retry admitted

The original cooperative run independently proved the reviewed target, but its supervisor remained blocked by two path faults. All historical evidence is retained. Operator retirement reconciled the known rejected read and destroyed VM; actual pending costs are zero. A separate review binds abandonment of the first native session without resuming or relabeling it. Both old attempts were exported and all worker containers removed.

Root reviewed and froze the corrective five-file source delta plus isolated retry launcher and tests. Two launcher issues found before paid calls were fixed: preparation now allows pending target review, and locked launch recaptures the current verifier qualification scope. Superseded prelaunch amendment/manifest bytes are retained; attempt identity and budget did not change. Twenty focused tests and independent audit passed.

Fresh retry experiment `7cb2963a-2219-4016-928a-6a27ed562339` launched at approximately 23:51 UTC, 24 September. State: `.state/hardening-final-2026-09-24-retry-1`. Exact ceiling $8.796745; same scientific target, independent fresh contexts, two roots/four slots, no previous solution imported. The monitor includes this state. This smaller remaining-budget retry is primarily a post-fix operational observation; it cannot be reported as an equal-budget comparison with the original cooperative run. Final audit/shutdown remains pending.

## Explicit user budget amendment during retry

At approximately 23:57 UTC, the user authorized raising the budget back to $100. Root explicitly interpreted this as a $100 total ceiling for the current retry, including its already spent funds; prior attempts remain separately visible. A tested operator-only transaction raised both canonical experiment and accounting ceilings from $8.796745 to $100 at revision 3, with $6.944340 spent, $1.28 reserved, four active workers and zero uncertainty at the subsequent read. No usage was reset and no source was hot-patched. The original launch manifest is historical and unchanged; `.state/hardening-final-2026-09-24-retry-1/budget-amendment-usd100.json` and the canonical `experiment.budget.amended` event record the explicit runtime amendment. The earlier $52 round ceiling is superseded for this retry by the new authorization, not silently recycled. Maximum combined accounting is now $186.966148 if the whole newly authorized retry envelope is used.

The standalone helper uses existing service transaction/idempotency/authority and accounting locks. Root inspected it, ran an independent fixture proving outstanding accounting preservation and idempotency, and reran two focused tests covering stale/cross-project/agent/excess-cap/key-reuse rejection. The running model, prompt, scientific target, worker count and environment remain unchanged.

## Completed outcome

Fresh retry supervisor exited 0. All six tasks/sessions completed; one exact-target proof passed Comparator, Lean and Nanoda at experiment +1,022.623 seconds. Conservative spending was $49.102475 under the explicitly amended $100 ceiling. Export validates 3,246 unique artifacts and exact token reconciliation. There were no native compactions/handoffs in this retry; the earlier original run had one real native compaction before its accepted proof. All three current attempts' final ledgers are quiescent; historical abandoned native uncertainty is retained explicitly. All worker containers were absent, Colima shutdown exited 0 and its status is Stopped, and the monitor is PAUSED. Full details and remaining scale gates are in REPORT.md and final-reconciliation.json.
