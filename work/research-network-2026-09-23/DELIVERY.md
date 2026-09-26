# Research network implementation delivery

The six approved communication and delegation proposals are implemented in the local
`formal-research-loop` worktree. GPT-6 Sol agents implemented the service, runtime and
evaluation changes; the coordinating agent planned, reviewed integration, directed
fixes and ran the final checks. Existing uncommitted work was preserved. Nothing was
committed or pushed in this implementation round.

The [operator guide](../../docs/RESEARCH_NETWORK.md) explains setup and model-visible
tools. The [implementation plan](../../docs/superpowers/plans/2026-09-23-research-network.md)
and [source manifest](source-manifest.json) record scope and exact local source hashes.

## Delivered behavior

| Proposal | Implementation and boundary |
|---|---|
| Independent approaches | Operator portfolio seeding atomically queues separately instructed roots with explicit model selection, rollback and idempotency. Seeding does not itself start model calls. |
| Useful autonomous recruitment | Models can atomically recruit helpers, collaborators or competing approaches with objectives and exact source references. Joined and detached work preserve lineage and share the original resource authority. Initial and compacted context explains available tools. |
| Flexible teams and discovery | Opt-in profiles publish interests and assignments; voluntary team labels aid discovery. Neither membership nor subscription grants access to private work. |
| Durable discourse | Topics, attributed posts, objections, replies, source references, subscriptions, addressed messages and exact retrieval use canonical records. One bounded, acknowledged inbox per branch survives successor sessions. |
| Cross-pollination and synthesis | Optional cross-topic synthesis creates ordinary queued tasks with exact source IDs and explicit bounded-sample coverage. Sources and objections remain inspectable. Synthesis cannot confer proof status. |
| Central allocation and fair dispatch | Portfolio, recruit, synthesis and legacy task creation share admission limits. The finite runner rotates ready work across approach roots, preserves active work, and uses the existing ledger, leases and fences. Capacity requests signal demand without granting workers or money. |

The same application services back HTTP, the Python client, MCP and native model tools.
Responses automatically injects updates at settled boundaries and checkpoints them
before acknowledgement. Other runtime adapters currently use manual inbox tools.
Delivery is explicitly at least once; bounded identity and payload-digest tracking
prevents ordinary duplicate injection and preserves changed withdrawal notices.

## Audits and repaired faults

The [independent audit](AUDIT.md) records its original findings and final resolutions.
Important fixes during implementation were:

- Unreadable attachments could poison a recipient inbox. Direct sends now reject them;
  child returns explicitly omit inaccessible attachments while retaining task evidence.
- Revoked sharing could block all newer updates. The inbox now delivers a privacy-safe
  withdrawal notice; only operators/admins can inspect its internal audit source link.
  Generic record, mailbox, event and export paths enforce the corresponding access rules.
- Access changing between delivery and acknowledgement now produces `DELIVERY_CHANGED`.
  Responses performs one bounded reread and checkpoints the withdrawal before retrying.
  Missing or corrupt canonical sources remain loud faults.
- Runtime factories accepting `**kwargs` were missing automatic inbox hooks. A real
  runner replay exposed this wiring defect; forwarding and regression coverage now exist.
- New broad metadata indexes slowed unrelated receipt lookups. Partial discussion
  indexes restored the original performance bound without weakening the test.
- Synthesis sampling now progresses past long single-topic backlogs, retains cross-topic
  sources, and identifies its sample size rather than implying complete coverage.

## Fresh validation

| Check | Observed result |
|---|---|
| Full Python suite with real PostgreSQL and Temporal enabled | **1,044 passed, 3 skipped**, 21 upstream warnings; [log](final-python.log) |
| Final frozen network/service/runtime/API/replay/PostgreSQL suite | **50 passed**; includes concurrent duplicate acknowledgements; [log](final-network.log) |
| Three opt-in real VM tests, which were skipped in the aggregate | **3 passed**: scientific workbench/checkpoint, public-factory deadline and fresh restore, streamed artifact restoration; [log](real-workbench.log) |
| Ruff and formatting | Passed for the checked Python source/test/runner files; [lint](ruff.log), [format](format.log) |
| Database migrations and recovery | Real PostgreSQL 16.15 migration/admission/delivery/acceptance locks and real local Temporal recovery exercised; [initial infrastructure log](infrastructure-integration.log) and final suite above |
| Real verifier controls | **24/24 expected core/library outcomes** across Lean and the independent kernel; **16/16 fixed boundary checks** |
| Verifier assessment | All **10 mechanical checks satisfied** for scope `665d5178f9bcc726135a5912c855b3708d2e1cc9136554367b4989cb311da6db`; [review packet](../pilot-qualification-2026-09-23/attempt-network-01/QUALIFICATION_REVIEW.md) |

The full-suite skips were deliberately run separately against the dedicated VM. Counts
from overlapping suites are not additive. The warnings concern upstream Starlette and
OpenHands deprecations. The verifier packet still says `production_qualified=false` and
`deployment_approval=pending`; mechanical evidence is not deployment or scientific approval.

## What the replay actually demonstrated

The reusable [replay runner](../../infra/evaluate_research_network.py) compares independent
roots, addressed messaging and subscribed discussions using the same synthetic resource
envelope and mocked provider. The [final author run](replay-results-author.json) reports
two completed tasks per condition, 0/1/1 deliveries and acknowledgements, and 0/1/1 actual
agent tool calls retrieving the exact source. No proof was attempted or accepted.
An additional deterministic concurrent test has one running agent create an artifact and
send a message, then another receive it and read both the message and linked artifact.
Existing joined-delegation regressions cover child return and single-slot recovery.

The logical queue probe admitted **128 tasks**, executed **eight** with a measured peak
of **two mock workers**, and retained **120 queued tasks**. This checks queue and runner
behavior. It is not a 128-worker endurance run. Fixed mocked token usage and observed
wall times do not support efficiency or scientific-performance comparisons.

Reproduce the offline comparison with:

```sh
PYTHONPATH=src .venv/bin/python infra/evaluate_research_network.py \
  --output .state/network-replay.json --load-roots 128
```

## Remaining qualification and operating state

No live research model API calls were made in this round. Improved probability of
solving hard physics problems, SOTA performance, long-lived discourse quality and live
fleet capacity remain unmeasured. The finite supervisor retains its existing concurrency
ceiling. Automatic delivery outside Responses, distributed fair scheduling, production
endurance and large-scale latency qualification remain future work.

The next scientific step is a small matched-budget comparison on reviewed problems:
independent approaches versus shared verified artifacts versus attributed discussions,
using identical acceptance rules. Enable synthesis as a separate experimental factor.
Do not infer mathematical benefit from message count, acknowledgement, or agent count.

The temporary PostgreSQL container and its local credential file were removed. The
dedicated 12 GiB VM is **Stopped**, confirmed in [shutdown.json](shutdown.json). Existing
proof packets and previous paid experiments were left intact. One coding agent reached
its usage limit after reporting its code frozen; the coordinating agent completed the
remaining integrated validation and shutdown.
