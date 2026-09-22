# Documentation

PhysHarnessV2 is a development implementation. **All waves remain unqualified.** Start with the
[evidence ledger](IMPLEMENTATION_STATUS.md) for observed results, integration gaps, and the
remaining qualification gates. The [repository README](../README.md) provides the local quickstart.

## Start here

| I want to… | Read |
|---|---|
| Understand the system and run the local laboratory | [Repository overview and quickstart](../README.md) |
| Find the next implementation goals | [Roadmap](ROADMAP.md) and [approved specification](IMPLEMENTATION_PLAN.md) |
| Distinguish implemented code from qualified capability | [Implementation evidence ledger](IMPLEMENTATION_STATUS.md) |
| Contribute or manage an issue | [Contributing](../CONTRIBUTING.md) and [project management](PROJECT_MANAGEMENT.md) |
| Integrate a model, tool, or client | [API contract](API_CONTRACT.md) and [execution subsystem](EXECUTION.md) |
| Prepare a reviewed target, launch a model, and reuse a lemma | [First live run](FIRST_LIVE_RUN.md) |
| Rebuild the pinned proof and physics environment | [Formal environment](FORMAL_ENVIRONMENT.md) |
| Review the 40 physics targets and 20 altered cases | [Benchmark review and calibration](PHYSICS_BENCHMARK_REVIEW.md) |
| Collect exact-scope verifier qualification evidence | [Verifier qualification](VERIFIER_QUALIFICATION.md) |
| Assess scientific evidence and acceptance | [Verification](VERIFICATION.md), [science](SCIENCE.md), and [evaluation](EVALUATION.md) |
| Deploy, diagnose, or operate the system | [Deployment](DEPLOYMENT.md), [operations](OPERATIONS.md), and [security](../SECURITY.md) |

## Scientific and execution contracts

| Guide | Scope |
|---|---|
| [API contract](API_CONTRACT.md) | Versioned operations, identity scopes, revisions, idempotency, and artifacts |
| [Verification](VERIFICATION.md) | Trusted targets, Comparator isolation, proof dependencies, receipts, and independent-kernel qualification |
| [Execution](EXECUTION.md) | Model/runtime adapters, capability differences, tool dispatch, checkpointing, and JavaScript research programs |
| [Claude runtime](CLAUDE_RUNTIME.md) | Native Claude SDK behavior, authority, continuation, and budget limitations |
| [OpenHands runtime](OPENHANDS_RUNTIME.md) | Remote execution, native capabilities, and pinned SDK/Temporal compatibility |
| [VM workspaces](VM_WORKSPACES.md) | Canonical allocation, provider lifecycle, isolation requirements, artifact transfer, and recovery gaps |
| [Collaboration](COLLABORATION.md) | Helpers, collaborators, competing branches, sharing policies, and resource authority |
| [Memory](MEMORY.md) | Evidence-preserving context, retained history, checkpoint validity, and handoff boundaries |
| [Science](SCIENCE.md) | Source correspondence, lemma retrieval, exact certificates, numerical evidence, and benchmark limitations |
| [Evaluation](EVALUATION.md) | Experiment comparisons, budgets, holdouts, datasets, learned retrieval, and promotion criteria |

## Interfaces and operations

| Guide | Scope |
|---|---|
| [Research console](CONSOLE.md) | Local setup, authentication, scientific status, inspection views, and UI validation |
| [Deployment](DEPLOYMENT.md) | Pinned dependencies, local Compose, managed infrastructure inputs, and unqualified components |
| [Operations](OPERATIONS.md) | Health and failures, evidence handling, recovery, upgrades, and release qualification |
| [Security policy](../SECURITY.md) | Credential boundaries, private research data, and vulnerability reporting |
| [Formal package](../formal/README.md) | Lean inputs, smoke fixtures, and qualification prerequisites |
| [Benchmark inventory](../benchmarks/README.md) | Program families, reference expectations, provenance, and pending expert review |
| [Self-hosted execution](../infra/selfhost/README.md) | Future provider requirements and explicit qualification gates |

## Planning and evidence

- [Roadmap](ROADMAP.md): wave goals, dependencies, and the next qualification work.
- [Implementation specification](IMPLEMENTATION_PLAN.md): the approved end-to-end scope and
  acceptance targets. These targets are not measured capacity claims.
- [Implementation evidence ledger](IMPLEMENTATION_STATUS.md): observed validation and remaining
  engineering, environment, and scientific blockers.
- [Project management](PROJECT_MANAGEMENT.md): issue organization, ownership, review, and
  completion semantics.
- [Contribution guidance](../CONTRIBUTING.md) and [changelog](../CHANGELOG.md): development workflow
  and released or recorded changes.
- [Physics harness research](../outputs/2026-09-14-physics-harness-research.md) and
  [coding-harness comparison](../outputs/2026-09-14-coding-harness-comparison.md): dated background
  research that informed the architecture.
- [Engineering evidence archive](../work/): dated investigations, validation, and audits.
  Historical observations do not replace a fresh release or qualification run.

Keep operational secrets and private research transcripts out of documentation and public issues.
New capability claims should link to their recorded evidence and state the limits of that evidence.
