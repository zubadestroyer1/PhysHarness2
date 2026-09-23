# Project management

PhysHarnessV2 tracks executable engineering work alongside scientific qualification. GitHub
issues and pull requests are the shared work queue; immutable artifacts and the harness records
remain the source of scientific evidence. Public issues must not contain private research
transcripts, credentials, or unreviewed publication claims.

The [roadmap](ROADMAP.md) organizes the waves. The [approved plan](IMPLEMENTATION_PLAN.md)
defines scope and exit criteria; the [implementation evidence ledger](IMPLEMENTATION_STATUS.md)
states what has actually been demonstrated. When they appear inconsistent, investigate and
correct the record rather than silently treating a roadmap item as complete.

## Turn an idea into a completed change

1. Open an issue with a concrete outcome, current evidence, dependencies, and a way to verify
   completion. Use a bug, engineering, research, or qualification form as appropriate.
2. Triage the issue: choose one primary type, relevant areas, a priority when justified, and the
   wave whose exit criterion it advances. Link blocking issues explicitly.
3. Keep large objectives in tracking issues labeled `type:epic`. Split implementation into
   independently reviewable tasks and link each child in the parent checklist.
4. Work on a `codex/` branch and open a small PR. A draft PR can expose work in progress without
   suggesting that its checks or review are complete.
5. Run relevant checks, record skips and limitations, and obtain the required review. Merge only
   after the change's acceptance criteria and review requirements are satisfied.
6. Close completed tasks and link the merged PR or evidence. Leave unfinished gates open and
   update the tracking issue with what remains.

Use `Closes #…` for a completed task and `Refs #…` for partial progress. A wave epic stays open
until its complete exit criterion is supported by evidence. Closing an engineering task does not
mean a scientific claim has been proved.

## Labels

Labels describe work; they do not grant authority or certify a result.

| Group | Labels | Use |
|---|---|---|
| Type | `type:bug`, `type:feature`, `type:task`, `type:research`, `type:qualification`, `type:epic` | Choose the primary kind of work. Research explores a target; qualification demonstrates a stated capability. |
| Area | `area:core`, `area:verification`, `area:agents`, `area:infrastructure`, `area:knowledge`, `area:science`, `area:console`, `area:evaluation`, `area:docs` | Select the affected subsystems; more than one may apply. |
| Priority | `priority:p0`, `priority:p1`, `priority:p2` | P0: current integrity/security failure or critical outage; P1: next critical dependency; P2: ordinary planned work. Untriaged work may have none. |
| Waiting | `status:blocked`, `status:needs-review` | Link the dependency or identify the review needed. Remove the label when the condition changes. |
| Review | `trust-boundary` | Changes to acceptance, trusted definitions, credentials, or result promotion need independent review. |
| Participation | `good first issue`, `help wanted` | Bounded newcomer work with clear checks, or work seeking an additional contributor. |

Do not use a priority label to imply a deadline, and do not use `status:needs-review` as evidence
that review occurred. Keep labels few enough that a contributor can find useful work quickly.
The checked-in taxonomy documents the intended convention; inspect the repository's live labels
and settings before claiming they have been applied.

## Wave milestones and qualification

Use one milestone per implementation wave, numbered 0–11, with no invented completion dates.
An issue belongs to the earliest wave it must satisfy; later-wave dependencies can be linked
without duplicating the task. Wave tracking issues link their prerequisites, child issues, and
qualification evidence.

The manifest's milestone dependencies identify prerequisites for **full wave qualification**;
they do not require every earlier wave to finish before implementation or a bounded pilot can
begin. The [approved plan](IMPLEMENTATION_PLAN.md) and [roadmap](ROADMAP.md) put a reviewed,
safe live Wave 0–2 proof-and-reuse pilot first, with Wave 3 recovery and reconciliation work in
parallel. Selected Wave 4–5 checkpoints and accepted-lemma retrieval then support 2–8-agent
comparisons, while selected Wave 6 matched-cost and matched-time measurements can start early.
Scale through 8, 32, and 128 active workers as evidence supports it; Wave 8 retains its full
72-hour, 128-worker gate. Kubernetes, self-hosting, and 1,000-worker work in Wave 9 depend on
measured need, with existing lifecycle controllers evaluated before custom Firecracker work;
Wave 7 and 10 work is likewise demand-driven. A Wave 11 open-problem pilot can begin with
expert-reviewed targets, safe independent acceptance, and reliable small teams. Full sustained
Wave 11 qualification still depends on Wave 8 durability and its scientific gate.

A milestone's GitHub completion percentage measures closed issues. It does **not** measure
scientific success or automatically satisfy a wave gate. Close a wave milestone only when its
exit criteria have been reviewed against reproducible evidence and the implementation ledger
is updated. Keep a dedicated open qualification issue when code is implemented but a live test,
independent checker, expert assessment, or deployment prerequisite is still missing.

Qualification reports should identify:

- The exact gate, commit, environment revisions, and inputs tested.
- Whether the run used scripted/replayed activity, real infrastructure, real proof checkers,
  live models, or expert assessment.
- Results, resource use where relevant, failures, skips, and known limitations.
- Reproduction instructions and hash-addressed evidence that can be shared safely.
- The reviewer, decision, and unresolved conditions required for promotion.

Missing evidence means the gate remains open. A failed run is useful evidence when its cause is
clear; it must not be replaced by a passing summary of an earlier run.

## Coordination as the team grows

Issues and milestones work without a GitHub Projects board. If a board is configured, use it as
a view of the same issues, with Backlog, Ready, In progress, In review, Blocked, and Done states.
Avoid a second, conflicting task list. Mark work ready only when the objective, dependencies,
and validation are clear. Keep blocked issues linked to their actual blocker and preserve
promising scientific approaches even when they do not produce a short-term implementation.

Triage new issues regularly and before starting a new wave. Revisit shared blockers across the
quantum and classical programs, review capacity, verifier throughput, and infrastructure needs.
Assign ownership only to contributors who have agreed to take it. Separate a research target's
mathematical owner from its engineering and qualification tasks when different people are needed.

Record major design decisions in `docs/` with context, alternatives, the decision, consequences,
and links to the deciding issue or PR. Update the existing decision when superseding it and
preserve its history. Use incident reports for failures affecting acceptance, retained evidence,
credentials, or recovery, with a redacted public summary when appropriate.

## Review, repository settings, and releases

The current `CODEOWNERS` lists the initial maintainer. It does not create independent review
capacity. An author cannot approve their own work as an independent reviewer. Acceptance logic,
trusted definitions, credential boundaries, result promotion, and substantial runtime or
coordination changes remain pending until another qualified human reviews them. Do not invent a
reviewer or substitute an automated review for that requirement.

Repository administrators configure branch rules and required checks separately. The intended
policy is PR-based changes to `main`, passing relevant CI, resolved review findings, and the
independent review described above. Exact required-check names must match observed GitHub runs.
Templates, `CODEOWNERS`, and this document are not evidence that protection or a Projects board
is active. Keep self-hosted qualification runners restricted to reviewed trusted revisions.

The [management manifest](../.github/project-management.json) records the label taxonomy,
milestone gates, repository metadata and proposed main-branch policy. Reconcile changes against
the live repository before applying them; preserve existing unrelated settings and never infer
that a checked-in policy has been enabled. Administration permissions are distinct from content,
issue and pull-request permissions.

[Dependabot configuration](../.github/dependabot.yml) schedules weekly GitHub Actions, `uv` and
console npm update PRs, with bounded open queues and grouped patch updates. It becomes effective
after reaching the default branch. There is no automatic merge policy. Review SDK/toolchain
compatibility, regenerate affected locks and qualification evidence, and retain immutable action
and image pins. Lean environments and the custom image manifest still need deliberate updates.

Before releasing, check the following against the actual release commit:

- Relevant CI and required human review are complete; outstanding limitations are visible.
- Dependency locks, environment manifests, public contracts, and migration guidance agree.
- [CHANGELOG.md](../CHANGELOG.md), the implementation ledger, and reproduction instructions
  describe the delivered behavior and distinguish development evidence from qualification.
- Sensitive artifacts are excluded, upstream attribution is preserved, and published scientific
  packages have the required meaning, proof, and novelty reviews.

Use explicit prerelease versions while the platform is under development. A software tag or
release is not a wave certificate, a throughput qualification, or a scientific result.
