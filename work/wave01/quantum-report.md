# Quantum benchmark author report — Wave 0/1

Status: twenty positive targets and ten altered cases authored. Scientific review remains pending. Difficulty is uncalibrated. No model runs or expert approvals are represented here.

The collection uses the pinned complex `Ket`, `MState`, `HermitianMat`, unitary, and CPTP representations. All Lean files are self-contained through the already-built `QuantumInfo.States.Pure.Qubit` import closure. There are no additional support modules or build-root requests. Each target and reference is included verbatim in the JSON; each altered case includes its own exact challenge and attempted proof.

## Scope and design

There are nine families: gates, effects, pure-state geometry, composite states, cloning, channels, decoherence, unitary dynamics, and Bell states. Whole families determine splits: eleven development targets and nine holdout targets. Holdout means excluded from a particular development export, not unpublished or unknown to a model. The collection and imported proofs are public and cannot support an unseen-data claim.

The distribution is four foundation, fourteen intermediate, and two stretch author estimates. These describe expected proof work under the displayed import environment, not the historical depth of the physics theorem. In particular, purification is foundation because a direct witness exists; no-cloning and the pure-state entanglement characterization are intermediate compositions because their core theorems are already imported. The matrix tactic can automate several finite calculations. Every target lists these shortcuts.

The stretch references are dephasing purity loss and the Bell marginal. They require connecting assumptions or definitions across matrix, complex, trace, and state APIs. The commuting-unitary conservation proof also composes trace cyclicity, commutation and unitarity; independent AI review led to an intermediate estimate because that composition is short. A compiler or model could discover shorter proofs; none is claimed intrinsically difficult. The set is a finite-dimensional quantum-information and operator-algebra benchmark. It does not cover unbounded Hamiltonians, continuum wavefunctions, scattering, field theory, or many-body limiting arguments. The dynamics tasks concern a specified unitary step; no Schrodinger evolution equation is derived.

The standard effects use Loewner order and real Born expectations. Positivity, Hermiticity and trace one are bundled in `MState`; these are meaningful physical assumptions, not redundant scalar inequalities. Some reference identities need weaker algebraic hypotheses, which is explicitly disclosed while keeping the physical input type. Tensor and trace directions follow the library: `traceLeft` discards the left factor; `traceRight` discards the right factor. The local-channel task explicitly assumes a product input and does not claim the full no-signalling theorem on entangled inputs. Cloning compares density states and therefore respects global phase; overlap strictly between zero and one excludes identical and orthogonal rays.

The author-defined `dephase` is the exact matrix formula `(rho + Z rho Z)/2`. It is a mixture of two unitary actions and returns a matrix. The targets establish its matrix behavior but do not introduce a separately bundled CPTP certificate. This distinction, the trace-purity convention, and all new descriptions remain reviewable human decisions.

## Target inventory

| ID | Estimate | Split | Reference mechanism |
| --- | --- | --- | --- |
| quantum.gates.hadamard_basis_exchange | foundation | development | Compose a gate intertwining lemma with involution; Track multiplication order. |
| quantum.gates.pauli_commutator | intermediate | development | Expand operator products in a finite basis; Handle complex phases and commutator sign. |
| quantum.gates.controlled_involution | foundation | development | Lift an algebraic invariant through a controlled construction. |
| quantum.effects.binary_normalization | foundation | development | Translate operator positivity to Born probabilities; Use trace normalization and complement linearity. |
| quantum.effects.observable_interval | intermediate | development | Transfer Loewner bounds to measurement averages; Normalize scalar multiples of the identity. |
| quantum.effects.zero_subeffect_support | intermediate | development | Infer a zero expectation by order sandwich; Convert zero expectation to a support/kernel relation. |
| quantum.geometry.orthogonal_projectors | intermediate | holdout | Contract rank-one operators; Match bra-ket overlap with dotProduct. |
| quantum.geometry.global_phase_measurement | intermediate | holdout | Use physical equivalence under global phase; Transport equality through the Born expectation map. |
| quantum.composites.product_pure_iff | intermediate | development | Relate ket representability to purity; Use tensor multiplicativity and probability endpoints. |
| quantum.composites.entanglement_reduced_purity | intermediate | development | Distinguish pure-state from mixed-state entanglement; Compose separability, product-ket, and reduced-purity equivalences. |
| quantum.composites.purification_with_pure_global | foundation | development | Construct an extension using spectral purification; Certify the extension is globally pure. |
| quantum.cloning.nonorthogonal_no_common_cloner | intermediate | holdout | Exclude simultaneous unitary cloning; Translate Hilbert-Schmidt pure-state overlap to squared bra-ket norm; Use strict bounds to contradict zero overlap. |
| quantum.channels.sequential_heisenberg | intermediate | holdout | Track composable input and output Hilbert spaces; Cycle the trace; Apply dual maps in reverse temporal order. |
| quantum.channels.replacement_absorbs_history | intermediate | holdout | Prove equality of channels by action on every density state; Compose deterministic erasure with arbitrary prior processing. |
| quantum.channels.independent_outputs_marginal | intermediate | holdout | Preserve product structure under local channel tensor products; Certify separability; Compute the marginal after local processing. |
| quantum.decoherence.complete_dephasing_projection | intermediate | development | Translate random unitary conjugation into a matrix formula; Compute retained populations and removed coherences; Prove idempotence of a measurement channel. |
| quantum.decoherence.purity_loss | stretch | development | Extract conjugate symmetry from density-matrix Hermiticity; Expand quadratic matrix traces; Isolate lost coherence as a squared complex magnitude. |
| quantum.dynamics.commuting_energy_conservation | intermediate | holdout | Translate a commuting symmetry into conservation; Cycle a trace without commuting arbitrary factors; Cancel U-adjoint U. |
| quantum.dynamics.unitary_purity_conservation | intermediate | holdout | Relate purity to self-overlap; Use unitary invariance; Transport the pure-state characterization. |
| quantum.bell.entangled_with_mixed_marginal | stretch | holdout | Distinguish joint entanglement from locally mixed statistics; Compute a partial trace with explicit normalization; Control basis ordering in a tensor product. |

## Altered cases

Five mathematical mutations are expected to fail mechanical proof checking: the Pauli commutator sign, a wrong Hadamard-conjugated observable, duplicated POVM outcomes, an omitted mixture weight, and an unnormalized Bell marginal. Their rationales give simple matrix, trace, or zero-effect counterexamples. These do not amount to a universal proof that every false theorem is rejected; they test exact submitted proof attempts against exact targets.

Five valid mutations are intentionally `semantic_hold`: restricting phase equivalence to identical kets, restricting dynamics to identity, assuming the support conclusion, broadening physical density inputs to arbitrary matrices, and replacing dephasing by identity while dropping diagonalization. The unrestricted-matrix identity is valid algebra and could be separately approved as such. It is held when offered under the physical-state interpretation of the parent. Kernel success on these cases is expected and does not issue scientific approval.

## Provenance

Primary formal provenance is the exact Physlib/QuantumInfo source at commit `405848179db6375f814021e804a37dc0dda66d91`, with declaration locators per target. Mathlib is pinned at `db584cd6d46c92f209a44c0f1c829460d327499d`. Supplementary domain references are [John Watrous's author-hosted *Theory of Quantum Information*](https://cs.uwaterloo.ca/~watrous/TQI/TQI.pdf), sections 2.1.3, 2.2, and 2.3, and [Wootters–Zurek's original no-cloning paper](https://www.nature.com/articles/299802a0), Nature 299 (1982), 802–803. No text or expert endorsement has been fabricated; formal hypotheses, not bibliographic labels, determine what each claim actually says.

## Verification record

Host-only static Python inspection passed: JSON parses, there are exactly 20 unique positive IDs and 10 altered cases, required positive fields are present, all parents exist, each family has one split, all positive references have exactly one target theorem, and no positive reference contains `sorry` or an added axiom. This is not Lean elaboration evidence.

Root owns all Linux execution. The initial Comparator batch was affected by infrastructure setup and resource contention with the consolidated source build. The parent reported a 110-second timeout for the first task under concurrent compilation, followed by verified cleanup and a switch to lighter contained direct-Lean diagnostics. No successful elaboration, Comparator acceptance, or independent replay is inferred from that attempt. Exact root-generated `.state/wave01/quantum-draft-*` reports retain the actual outcomes and input snapshots. Successful final evidence, when available, belongs in the separately generated evidence records; no compiler/reviewer status is embedded in this author manifest.

The first full contained diagnostic batch, `.state/wave01/quantum-elaboration-1.jsonl`, returned 16 successful positive elaborations and four failures: orthogonal-projector multiplication lacked the final zero outer-product simplification; both dephasing proofs left matrix row/dot products unexpanded; the Bell reduction left outer-product applications unexpanded. Those references and the corresponding altered proof attempts were corrected. Retry batch 2 is recorded in `.state/wave01/quantum-elaboration-2.jsonl`. All five mathematical mutations exited with elaboration errors; the duplicate-outcome attempt specifically reported `linarith failed to find a contradiction`, and its required diagnostic was updated accordingly. Four semantic-held proofs elaborated initially, while the arbitrary-matrix semantic variant initially shared the dephasing expansion issue. These outputs are compiler diagnostics only, not Comparator or independent-kernel acceptance.

The classical benchmark agent completed independent review of all twenty quantum targets and ten altered cases. The review found no mathematical scope, counterexample, negative-classification, or family-split defects. The sole calibration suggestion, lowering commuting-unitary conservation to intermediate, was adopted. This AI review is engineering feedback, not human scientific approval. This author independently inspected all twenty classical targets and ten altered sources. No mathematical scope or negative-classification defects were found; difficulty-estimate inconsistencies and wording that implied discovery of a supplied invariant were reported and corrected by the classical author. That agent review is not expert scientific approval. Root must attach final exact-source compilation and acceptance evidence before claiming mechanical coverage; a named authorized human must separately approve scientific use.


## Final scoped elaboration check

The exact current sources were matched by SHA-256 against the union of the two contained diagnostic batches. All **20 positive references elaborate**, all **5 semantic-held candidates elaborate**, and all **5 false altered candidates fail** with their required diagnostics. The complete per-source mapping is `.state/wave01/quantum-elaboration-summary.json`; this result is not Comparator acceptance or independent replay. The fresh positive controls use the same repaired component simplifications as the associated false variants. In the repaired omitted-mixture-weight case the remaining obligation incorrectly forces arbitrary diagonal entries to zero; in the repaired Bell mutation the remaining diagonal obligations are `False`.

The authorized retry used the unchanged root diagnostic runner with the existing `physharness-formal:physics433-final` image, network disabled, read-only root and input mount, UID/GID 65532, all capabilities dropped, no-new-privileges, the root-provided seccomp profile, one CPU, 2 GiB memory, 128 PID limit, and a 256 MiB temporary filesystem. The snapshot and runner are `.state/wave01/quantum-compile-2/`; logs preserve an initial sandbox socket-denial attempt separately as `quantum-elaboration-2-socket-denied.err`. The automatic approval path then allowed the authorized contained run. No candidate Lean was executed on macOS. The run exited zero as a diagnostic orchestrator, and a subsequent successful Docker listing returned no container named `physharness-quantum-elaboration-2`, confirming removal after `--rm`.

Final Comparator boundary execution, independent nanoda replay, image qualification, and human scientific approval remain the root task's separate work. No source or approval result from those stages is inferred here.
