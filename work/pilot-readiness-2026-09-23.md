# Pilot readiness handoff — 2026-09-23 UTC

The engineering preparation below is complete. The live experiment is **not launched**;
selected-target review, scoped deployment approval, and acceptance of the proposed
spending envelope remain human decisions. No paid generation calls or scientific
verification receipts were created. Every implementation wave remains unqualified.

## Prepared experiment

The [review packet](first-pilot-review.md) contains the exact two quantum development
targets, definitions, assumptions, provenance, immutable identifiers, and review commands.
They concern qubit dephasing: diagonalization/idempotence, then exact purity loss.
These are known results, intended to test proof acceptance and subsequent lemma reuse.
The second attempt can also solve its target directly; its success alone does not prove reuse.

The active v2 experiments use GPT-6 Sol through Responses, high reasoning, one worker,
24 turns, 96,000 aggregate tokens, 16,384 output tokens per response, and a proposed
$5 allocation and 30-minute runtime limit per attempt. The pair's proposed API allocation
is $10. In-flight external checks still have their own bounded deadlines. Earlier v1
experiments were cancelled, preserving their records.

## Fresh evidence

- Saved API key authentication/model lookup succeeded; the Responses input-token endpoint
  accepted all 13 research tool schemas. Generation and billing eligibility remain untested.
- Current host suite: 830 passed, one skipped, three integration/Lean deselections.
  CI-scope lint and formatting passed. This is separate from the qualification regression run.
- Current-source [qualification](pilot-qualification-2026-09-23/README.md): ten mechanical
  checks satisfied; 24/24 core/library expected outcomes across both kernel modes; 16/16
  fixed boundary observations. Scoped regression results: 226 passed, one conditional
  PostgreSQL skip; all 56 required test identities passed.
- The exact two selected reference proofs and one negative control produced 3/3 expected
  outcomes in each kernel mode. These six observations are engineering fixtures, not model
  discoveries. The [independent audit](pilot-qualification-2026-09-23/independent-audit.md)
  rechecked source identities, diagnostics, independent-kernel markers and cleanup.
- The image archive's complete SHA-256 matched, restoration into a fresh VM succeeded,
  and a subsequent restart retained the exact image and checked runtime configuration.
  The [final shutdown record](pilot-qualification-2026-09-23/retention-and-shutdown.json)
  confirms the dedicated VM is stopped, its Docker endpoint unavailable, and its host agent absent.

Scope: `f13defb821a8043a16978a83058abd1e6f7cbed8a60bd36549fb647efe3cd70f`.
The 61 scoped inputs still match. A proposed two-target verifier registry was constructed
and structurally validated, but deliberately not activated. Its drafting helper now checks
current source freshness and reproduces the evidence assessment before proposing configuration.

## Corrections and retention

The documented Colima setup omitted creation of `COLIMA_HOME`; Colima 0.10.3 fell back
to its default directory. The first restore failed before executing any proofs. The default
VM started by this task was stopped, and the successful test used the explicitly named
`physharness-pilot` profile in persistent `~/.colima` storage. Instructions are corrected;
both failed and successful observations are retained.

A subagent audit accidentally printed the initial pilot role tokens. All four were rotated
before live use; the preparation audit checked that old tokens no longer authorize. Current
token files match the active store and have mode 0600. A scan of the proposed public evidence
found no current role token or OpenAI key. The OpenAI key was not involved in that exposure.

Private plans, SQLite records, identities, artifacts and inactive proposed registry remain
under `.state/runs/first-pilot`. The saved OpenAI key remains outside the repository.
The existing image archive was retained unchanged. No credentials or private state were pushed.

## Decisions required before launch

1. Review both exact statements and their physical interpretation in the target packet;
   approve them with rationale, or identify a reviewer or corrections.
2. Review the evidence and approve this particular isolated local pilot boundary. This
   decision does not qualify production deployment or fleets. An unsigned decision template
   and the exact proposed registry are ready in the private pilot directory.
3. Authorize the proposed $10 API allocation for the pair.

The key-loaded canonical preflights currently report only `TARGET_REVIEW_REQUIRED` and
`VERIFIER_REQUIRED`; they intentionally remain blocked. After the decisions, record the
reviews, activate the prepared registry, restart the named VM, recheck relevant pins and
preflight, and perform a bounded live attempt. Launch the reuse attempt only after the first
has an independently accepted proof. Stop the VM again when testing finishes.
