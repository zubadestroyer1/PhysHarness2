# Task D — replay coordination evidence

The reusable runner is `infra/evaluate_research_network.py`. It uses the real canonical service, PostgreSQL/SQLite compatible command patterns, `ResearchTeamRunner`, the Responses runtime, and the OpenAI SDK over `httpx.MockTransport`. It performs no paid model call, VM action, or scientific verification. The output from this run is `work/research-network-2026-09-23/replay-results-author.json`; command: `PYTHONPATH=src .venv/bin/python infra/evaluate_research_network.py --output work/research-network-2026-09-23/replay-results-author.json --load-roots 128`.

All three comparison cases use the same synthetic target, two root tasks, `$1` experiment ceiling, two worker slots, 600-second runtime ceiling and fixed mock model price/usage. The source evidence differs: independent roots, an addressed message, or a subscribed discussion post. The fake provider asks the agent to retrieve the exact source in the latter two cases. Actual recorded results:

| Case | Completed tasks | Provider requests | Delivery IDs | Acks | Agent exact-source tool reads | Pending after |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Independent | 2 | 2 | 0 | 0 | 0 | 0 |
| Addressed | 2 | 3 | 1 | 1 | 1 | 0 |
| Subscribed | 2 | 3 | 1 | 1 | 1 | 0 |

The extra provider request is the scripted exact-source tool turn. Provider input retains the delivery context on that next request; this is counted separately as one context repetition per communicating case, while duplicate delivered IDs remain zero. Fixed mock token usage means the recorded 30 versus 45 tokens cannot support an efficiency claim. Wall times are recorded in JSON but are machine scheduling observations, not a controlled latency comparison. Every output remains explicitly unverified.

The logical queue probe admitted 128 canonical root tasks, executed 8 through at most 2 concurrent mock workers, and left 120 queued. Its observed peak was 2 and active workers returned to zero. This is a queue/admission test, not qualification of 128 active workers or mathematical effectiveness. Provider start order and elapsed time are in the JSON artifact.

Focused tests add a deterministic concurrent runner exchange: agent A stores an artifact and sends an addressed message during execution; agent B waits on an async barrier, receives the update at its next settled request, calls `read_research_message`, and reads the linked artifact. Existing joined-delegation tests cover child return and single-slot terminal recovery. Runtime tests cover checkpoint-before-ack, crash redelivery, changed-withdrawal reinjection, and a bounded reread after `DELIVERY_CHANGED` at the poll/ack race. The HTTP success path follows the same service through post, subscribe, delivery, exact read and ack.

Two opt-in isolated-schema PostgreSQL tests cover concurrent same-key portfolio admission and concurrent polls plus duplicate acknowledgements for one reader. They skip without `PHYSHARNESS_TEST_DATABASE_URL`; the root agent ran the earlier poll version on PostgreSQL successfully and will rerun the strengthened duplicate-ack case. Local final focused run: **15 passed, 2 skipped** for Task C/D runtime/API/evaluation/PostgreSQL files; Ruff check and format pass. No effectiveness or proof outcome is inferred from these synthetic results.
