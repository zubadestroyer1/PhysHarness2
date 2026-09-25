# Purity attempt postmortem

Read-only diagnosis after both trials ended. No new model calls, no VM startup, no production-code changes and no modification of historical receipts. Tool calls, tool results, model-authored final research reports, canonical records, source contracts and offline fixture evidence were inspected. Opaque compaction contents and private reasoning were not reproduced in this report. The previously hidden reference proof was inspected only for this postmortem, after the live attempt; it was never supplied to that attempt.

## Conclusion

The evidence supports a formalization/tooling/collaboration failure, not an impossible physics theorem or a demonstrated model capability ceiling. The model identified the correct mathematical route. The run gave it inadequate library discovery, an awkward exploration interface, incompatible collaboration settings, very aggressive compaction and no effective response to repeated unproductive reads. These are meaningful harness/configuration shortcomings even though the acceptance boundary correctly rejected incomplete proofs and resource accounting stopped safely.

An existing 19-line reference file proves the identical formal statement using the same library environment. The proof extracts off-diagonal conjugacy using `ρ.Hermitian`, simplifies finite matrix arithmetic with existing declarations, and closes a polynomial identity with `ring`. No new mathematical lemma or external axiom is needed. The statement is a finite-dimensional algebra regression target, not a difficult open physics question; discovering the correct Lean interfaces is still real work.

## Feasibility evidence

The live `Challenge.lean`, `lean-toolchain`, `lakefile.toml` and `lake-manifest.json` are byte-identical to the selected-target fixture. Challenge SHA-256: `9d67036429d2fa386e403b21d35ad2839115267f4fb2281f511d6d54d27417ba`. Environment digest: `0c46de2450bd5a9b2584d513d3ad02a963a300c3b0e3510a3a22efbc5a11341f`.

`../pilot-qualification-2026-09-23/attempt-01/selected-targets-independent.json` records the purity fixture as `verified`, `kernel_checked`, `independent_kernel`; candidate hash `fb8df58561af32499b6a370f887aa7a71600d3eefd316080c259727493ce8b60`. A separate kernel-only fixture report also passed. The fixture's target metadata digest differs from the live revision, despite identical formal challenge/environment bytes. This diagnosis did not resubmit the reference proof against the live revision; it establishes formal feasibility, not a new live success receipt.

The live root report independently described the right calculation: a Hermitian 2×2 matrix has conjugate off-diagonal entries; equal mixing with Pauli-Z removes those entries; the trace-square difference is twice the squared off-diagonal magnitude. It accurately labeled the Lean proof unverified.

## Confirmed issues

### 1. The run had no interactive Lean development workspace

`pilot_ops.run_attempt` used `workspace_factory=None`. `research_tools` registers workspace tools only when a workspace is supplied. The agents therefore had no shell/source-tree search or direct exploratory Lean tool in this run. They could submit full candidates, wait for acceptance diagnostics, retrieve artifacts and query previously accepted claims.

Agents improvised `#print`/`#check` requests inside candidate files and submitted them to the final acceptance path. Six of nine candidate files explicitly contained `sorry`; eight contained interface probes. These were largely library-discovery experiments, not nine serious complete-proof attempts. The checker correctly withheld proof status. A separate exploratory elaboration/type/goal interface would provide this feedback without pretending the snippets are final submissions.

The actual missing knowledge included the available Hermitian-state interface and matrix simplification declarations. The environment contained these declarations; the agent could not efficiently browse them. Installing the library in a checker image is not equivalent to giving the researcher usable library access.

### 2. Knowledge retrieval had a scope and filter mismatch

All three `search_knowledge` calls returned no items. The tool only indexes canonical accepted claims (`research.py:search_knowledge`); it does not search the installed Mathlib/QuantumInfo declaration corpus. The agent was querying it for library APIs.

There is also a reproduced interface trap: `type_query` is a strict token-subset filter on the statement. The agent supplied `lemma`, `lean`, and a broad library description. Those tokens do not occur in the two accepted projection statements. Replaying the exact three queries read-only under an agent principal returns zero hits. Changing only `type_query` to the empty string returns two hits for each. The schema requires the field but the tool description does not explain this strict conjunction or how to disable it.

This is not evidence that the accepted store is corrupt: empty-filter retrieval works and receipt/claim bindings validate. The returned projection results could help with dephasing arithmetic, but they do not replace access to the wider library or guarantee completion of purity.

### 3. The collaboration configuration blocked useful communication

The experiment used `sharing=verified`. All three cross-branch messages returned `SHARING_POLICY`. Two contained concrete findings about `MState`, `HermitianMat`, `Qubit.Z`, existing lemma signatures and nonexistent names. They were labeled unverified by the sender but still prohibited by the experiment policy.

That policy is useful for an independent-results experiment, but unsuitable as the default for the requested cooperative research team. Allowing attributed unverified ideas does not require changing proof acceptance rules.

A second routing issue is visible in the attempted messages: `recipient_id` was the parent's worker/actor ID, while `send_message` expects a branch ID. Policy rejection occurred before recipient validation. Merely switching to ideas sharing would therefore leave an address error to fix. Tools should expose stable parent/sibling mailbox addresses and state the required ID type clearly, or provide a reply-to-parent operation.

### 4. Child findings were not integrated into a continuing parent

With two slots, the root and first helper occupied both. The library-interface collaborator was queued at 09:44:41 UTC and only started at 09:47:37, immediately after the root finished. The root never used `wait_for_tasks`, did not retrieve a mailbox, and did not resume after the collaborator's report. The collaborator finished at 09:51:53; the first helper continued until 09:58:54.

The scheduler honored its capacity limit; this is not an observed scheduler deadlock. However, delegation did not become effective collaboration. The system needs a clear child-result return/resumption contract for work the parent intends to integrate, while retaining the option for deliberately independent branches. Task completion currently means the model returned, not that the parent incorporated useful child work.

### 5. The run stagnated while compaction remained extremely frequent

There were 102 generations, 77 compactions and 100 completed tool operations. The first helper accounted for 61 generations and 54 compactions. No `checkpoint_research_notes`, `checkpoint_context`, `wait_for_tasks`, `request_handoff` or mailbox retrieval calls occurred. Canonical evidence persisted, but no explicit evolving research notes or fresh-session recovery strategy was used live.

Of 48 receipt inspections, 47 returned already-blocked results and one returned queued. One unchanged 708-byte Lean source artifact was read 16 times; source retrieval returned base64 rather than directly readable Lean text. Base64 is byte-exact but adds unnecessary friction for text-only agents without decoding tools. No truncation occurred in those reads, so missing bytes are not the explanation.

The final new candidate was submitted at 09:48:33. After it, 56 generations consumed 3,215,529 input tokens, 3,012 output tokens and $6.461178—about 82% of the entire $7.878868 attempt. No later candidate was produced. The runtime issued distinct tool operation IDs; this was not accidental replay of one cached operation.

The 8,192-token compaction threshold was deliberately chosen to exercise compaction in a short test, and was too aggressive to treat as a validated research default. The trace establishes frequent compaction and stagnation, but does not prove that compaction caused the stagnation. Base64 friction, lack of library tools, failed collaboration, prompt design and stochastic model behavior are confounded. The root and collaborator did produce sensible final reports, so universal memory loss is not supported either.

### 6. The configured token guard ended the run before the dollar budget

The attempt had $25 available but a separate 4,000,000 cumulative-token allowance. It stopped at 3,876,074 tokens because the next conservative request reservation needed 144,384 tokens. Active context and cumulative allowance are different quantities. This was a trial configuration choice, not the model's intrinsic context limit.

The guard worked. Its initial `PROVIDER_FAILED` label was incorrect and was repaired with specific token/cost admission errors and operation IDs, with regression coverage and no historical receipt rewriting. The labeling defect did not cause the preceding unsuccessful proof development. Increasing the limit alone would likely prolong the observed loop; that prediction should not substitute for a controlled trial.

## What the evidence does not support

- Mathematical impossibility or a missing mathematical foundation for this exact target.
- A RAM shortage, OOM, checker crash, unknown provider billing operation, or lost proof artifact.
- A valid finished candidate being rejected merely because the checker was too strict.
- A conclusion that GPT-6 Sol cannot solve this problem or that native compaction necessarily degrades all reasoning.
- A claim that passing infrastructure tests establishes effective autonomous scientific collaboration.

## Recommended corrections and comparison

1. Supply an isolated Lean research workspace with readable pinned source, declaration/type search, scratch compilation and goal feedback. Preserve independent final verification. Keep hidden target solutions out of the worker image/search corpus.
2. Split library retrieval from accepted research-result retrieval. Clarify/relax the opaque type-token filter, allow an empty filter by default, and return structured reasons for empty results. Return UTF-8 text for textual artifacts alongside hashes and exact-byte access.
3. Use attributed-idea sharing within cooperative teams, with stable branch mailbox IDs and an explicit child-result return path. Keep a separate independent/verified-only experiment mode and unchanged acceptance authority.
4. Use a substantially less aggressive, context-aware compaction threshold; retain the active source, last diagnostics and exact open obligations in an easily readable working view. Detect repeated identical terminal reads and expose stagnation with options to change approach or hand off, without prescribing a proof method.
5. Align the cumulative guard with the authorized dollar/time envelope and report every active stopping constraint before launch.
6. Re-run controlled comparisons that separate richer tools, collaboration and compaction settings. Use additional analogous held-out targets because this postmortem now knows the reference proof. Report exact proof success, repeated reads, cost and time—not just agent count or successful compactions.

The first three changes address directly demonstrated obstacles. The compaction/performance changes require comparative evaluation. No new paid trial or source-code fix was performed during this diagnosis; the VM remains stopped.
