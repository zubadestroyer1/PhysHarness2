# Wave 01 retained real-evidence audit

Historical scope notice: the original evidence assessment below predates the resource-policy changes. It does not qualify the current 8 GiB implementation. The build-wording finding is closed in the dated follow-up at the end.

Audited 2026-09-15 by the classical-benchmark agent, independently of the evidence producer. This is an AI engineering audit of retained files, not human scientific review or deployment approval. No Docker command, VM operation, Lean execution or physics-report mutation was performed. The concurrently running full physics benchmark reports are outside this audit.

The retained qualification packet is mechanically consistent with the current scoped inputs: the independent call to `assess_qualification` returned `satisfied`, all nine checks were `observed`, and both its JSON model and rendered Markdown exactly matched the retained packet. One build-description wording finding was identified below. No source/hash/case/assurance/cleanup mismatch was found in the audited completed reports.

## Scope and method

Repository: `<repo>`; inspected HEAD `9f05c71eff3626967a10c2af5dd6095606532a8d`.

Evidence directory: `work/wave01/evidence/`. The audited scope has canonical digest `de7476c9d13aab9bd3654a613fd63d147e42efe24926ce48a0577604a0ddec40` and image digest `sha256:82497fa412f10a76e515ddc8590f1c387a8383c8b99b1cd215261f6a11151246`. The canonical scope digest differs from the byte hash of the formatted `scope.json`, as expected.

Actual audit command:

```sh
PYTHONPATH=src .venv/bin/python /tmp/audit_real_wave01_evidence.py
```

The read-only verification script independently hashed every one of the 56 scoped current input files; constructed new `EvidenceFile` references from the bytes read; called `assess_qualification` with the four completed core/library reports, fixed probe and regression sidecar; compared the returned packet and rendered review exactly; parsed every outcome, cleanup, declaration and JUnit entry; and compared the two build-context tar inventories with current source and `build-inputs.json`. It exited zero. Its diagnostic summary was written only to `/tmp/real-wave01-evidence-audit.json`. It did not execute the commands quoted inside the evidence. The actual run summaries below are observations from retained execution logs, not newly executed proofs or tests.

The bound identities include fixture manifests and exact target/challenge/candidate hashes, trusted Lake configuration, image and measured runtime metadata, launcher, container driver, seccomp policy, suite runner, source revisions, and six checker binary hashes. The observed runtime records Linux kernel `6.8.0-117-generic`, Ubuntu `24.04.4 LTS`, architecture `aarch64`, Docker `29.5.2` and cgroup v2. The exact Lean banner reports `4.33.0` and commit `d8b18978322de05a8f3dba51ef03cf5461676c17`. Hash agreement demonstrates internal identity consistency; it cannot authenticate the collector or independently establish the live runtime.

## Actual outcomes and cleanup

| Completed report | Accepted proofs | Expected causal rejections | Positive assurance |
| --- | ---: | ---: | --- |
| `core-kernel.json` | 2 | 7 | `kernel` |
| `core-independent.json` | 2 | 7 | `independent_kernel` |
| `library-kernel.json` | 2 | 1 | `kernel` |
| `library-independent.json` | 2 | 1 | `independent_kernel` |

Thus all 24 expected case outcomes are supported: eight proof acceptances and sixteen blocked rejections. Each acceptance has Comparator exit zero, the ordinary Lean acceptance diagnostic and final success marker; the four independent acceptances additionally have the Nanoda acceptance diagnostic. Each rejection has exit one, `comparator_failed`, assurance `none`, and its exact required causal marker. No timeout, syntax error or unrelated crash is counted as a successful rejection.

Manual log inspection confirmed the illegal `sorryAx`, extra `shortcut` axiom, changed `neutral` dependency, and generated native-decide axiom diagnostics. The forged-receipt case prints its fake success JSON before the real illegal-axiom rejection and remains blocked. The overwrite probes report the expected read-only filesystem or permission-denied failure on the intended Challenge/configuration path. Warnings that the trusted Challenge template uses `sorry` also appear in positive runs; they are followed by successful verification of the separate completed Solution.

All 24 case cleanup records say `removed`, exit zero, and return the exact unique `physharness-check-<32 hexadecimal characters>` container name. The fixed probe supplies one additional distinct removed container. Across the four suites and probe there are five distinct run UUIDs and 25 distinct removed-container records. This audit verifies the recorded removal evidence; it did not query Docker for current absence.

`fixed-boundary.json` has all 15 required observations true. Its retained successful inner-process output contains the matching 14 in-container checks, probe/driver hashes, all six binary hashes, and the same causal errno observations as the outer report: sockets `1`, trusted and candidate writes `13`, root write `30`. Writable `/work` and `/tmp` positive controls pass. The fifteenth check records host-inspected container configuration. Successful raw inspection JSON, including `Env`, is not persisted in this report; the report therefore preserves the configuration conclusion and pinned producer identity, not an independently inspectable full configuration dump.

The retained regression XML contains 167 distinct test identities: **166 passed and one skipped**, with no failures or errors. All 35 exact required regression nodes passed, including the parameterized manifest-identity cases. A sibling parameter does not substitute for a required identity. The skipped case is `test_postgresql_review_update_cannot_cross_acceptance_commit`; it provides no current PostgreSQL concurrency evidence. These are host regression results, including synthetic transport checks, and remain distinct from the real Linux fixture/probe outcomes.

## Declaration inventory

The retained `declarations-kernel.txt` contains exactly **27 unique selected declarations** and matches all 27 `#print axioms` directives in the current `formal/DeclarationAudit.lean` and the selected declaration count. There are 26 axiom-dependent declarations; every printed closure is exactly the set `{propext, Classical.choice, Quot.sound}`. `Qubit` is the single declaration reported as depending on no axioms. The inventory spans ten classical, seven qubit, eight mixed-state and two matrix declarations.

This is an audit of the printed closure for those selected imported declarations. It is not an inventory of every imported theorem, a claim that the policy upper-bound axiom fields on fixture receipts are minimal, or an approval of physical assumptions.

## Build evidence and wording finding

Both retained build-log hashes match `build-inputs.json`. Both build-context tar hashes match their recorded identities. The final tar has 36 file entries, each matching the final input inventory and current corresponding source. Comparing tar contents shows exactly one change: `src/physharness/verification/container_driver.py`, from `a5df1f833fa05d5a172f1285ad40a0c5e3100944ff36a2d539355ce3bbe919a7` to `0aa043a827abe8dd79960b59e3fcd3d249f5b0600e5e2c68aeb6dfb69e34445f`. The Dockerfile is identical in both contexts and current source. The final log exports the exact scoped image digest.

**P3 — initial cache-description wording.** At the inspected snapshot, `build-inputs.json:73` says “physics-builder and physics stages rebuilt; unchanged checker builder stages reused.” The referenced initial source log actually records cached stages 7–9, then execution of builder stages 10–21: Lean archive extraction, source preparation, Go landrun build, Cargo Nanoda build, and a successful Comparator/lean4export build of 20 jobs. The same log records the complete physics build finishing with **8,790 jobs**, followed by the declaration audit. The subsequent final-image log reuses these checker/physics/declaration stages and executes the driver COPY/chmod and WORKDIR stages. The field should distinguish that actual initial rebuild from the cached final overlay. This affects build-history accuracy, not the passing scoped report identities; it was sent to root for correction, and no evidence file was edited by this reviewer.

The logs support a consolidated recipe build followed by a driver-only source-context change after the upstream fix. They do not establish a newly created VM or an entirely uncached base/toolchain build. The build-time metadata values `sandbox_qualification: not_run`, `independent_kernel_compatibility: not_run` and `semantic_review: not_reviewed` remain build observations; later fixture evidence is recorded separately and supplies no human approval.

## Remaining limits and authority

The packet correctly keeps `production_qualified: false`, `deployment_approval: pending` and `scientific_review: not_provided`. All three human review gates remain open. The consolidated-build gate requires a human to judge whether the actual build/recovery and environment evidence satisfy the intended deployment requirement; this audit does not silently equate the observed build with a fresh VM.

The five stated coverage gaps remain material: the security-filtered optional process-exit probe is incomplete; fixed observations do not establish universal host containment; actual runtime resource-exhaustion coverage is incomplete; current database race testing was skipped; and the driver independently enforces a 110-second/100,000-byte Comparator boundary. Larger host limits do not remove that driver limit. Prior failed or contended runs must remain historical failure evidence, not be replaced by these completed reports. No full physics benchmark result is inferred from the small fixture suites.

## Audited identities

| File | SHA256 |
| --- | --- |
| `scope.json` | `03b65cce709547ec67846df783d1dbeb4fef4a886ac29d2825ca3ff69c1c9eca` |
| `qualification-review.json` | `19e3f8b69596927393391eb2378d2f512467e53725366eef3e14f4e5be7d7f8f` |
| `QUALIFICATION_REVIEW.md` | `36df0e7b63810a51c69d9acf0b8e54486a2656774a32017c8989d41cabc14937` |
| `core-kernel.json` | `3334631bb7185043bcb8550b1e6efeb53f2454a65c25da6c6db9e0f74f92e1d4` |
| `core-independent.json` | `5e7e86256cb44f76e3c03ee51cbdebf6d5ff71ac5b2bce21f56002456c0d435f` |
| `library-kernel.json` | `071ba77355a37bd016a7ee4ba0605c542d7b7e5fcce6c7585d47c383a25b4364` |
| `library-independent.json` | `cd9124b6f7de592fd2fcfdc5ef21d21f4733636f956677f1914781bf5c3fd58d` |
| `fixed-boundary.json` | `db3915dd583c527f10c67a40fd8c30ee474094fcd1c484b121df5f5ef72afbe6` |
| `regressions.json` | `89e2dc04e98a4fa8ae95788009c174c5c17672444cdb36ec90823f039d77cacc` |
| `regressions.xml` | `5e4736bb90ae9862565fb50da8133914044914d7ea7f827ff5b42f61607588aa` |
| `declarations-kernel.txt` | `a1b350d2820424bdc368dfaa2c4bdceef122394b9a67767c8e36b097c3a91ae8` |
| `image-metadata.json` | `75be3be77a1ca65a153fb594d7e71ec72a5ec27b3aabe1e5e75323c580b9f573` |
| `runtime-identity.json` | `6d45b4cc785e74c75883e6c2bdb42ef3ba50639b7c89bb0614c990d0142474e5` |
| `build-inputs.json` (initial audit snapshot) | `683ff4f615fc3a50ffc9812eebe63475acfd5ee597b4f10b14fd1210712f3545` |
| `.state/wave01/fresh-image-build.log` | `2c2cd1ab5062160ec36b349bde9fe25e2f1d4de1925a773c35850451853b647d` |
| `.state/wave01/final-image-build.log` | `8099807e61c3481f27391b12bae51488e50fc2fd50af2a4a135edf8944b19315` |
| `src/physharness/verification/qualification.py` | `e161b0730b44deb41edceccba937ee4860816c9c5c67ebe656ae50dd249dabc1` |
| `formal/qualification-matrix.json` | `081ed6158b06bdfc6ac80906ab2e6427790fa0d16beeb25221c4158fe1346bcb` |
| `infra/run_qualified_lean.py` | `9717278932fc768b3a7d22bd4d5ceda77fda8a467acc94db444196d7f1be4476` |
| `infra/probe_verifier_boundary.py` | `e77b80d7edc8460fbec3cb0434b1c36eac5c5d9f5410c103082ea05072314aeb` |
| `src/physharness/verification/container_driver.py` | `0aa043a827abe8dd79960b59e3fcd3d249f5b0600e5e2c68aeb6dfb69e34445f` |

## Build wording closure and historical scope

Root corrected the P3 cache-description field on 2026-09-15. The corrected `build-inputs.json` has SHA256 `8a6431634b3f3812147b00d8688fd8d229c3449e2e26d31e3faf3cb4643aef8b`. A separate Python check reconstructed the original bytes by restoring only `source_build_cache_policy`, recovering the original audited SHA256 exactly. Both referenced build-log hashes remain unchanged. The check confirmed that only source-log stages 7–9 are marked `CACHED`, that the log contains the actual 20-job checker build and 8,790-job physics build, and exited zero. The corrected description matches these observations, so the P3 finding is closed. The original finding and initial file hash above are retained for provenance.

The original mechanically satisfied assessment above is now **historical**, tied to its recorded 2 GiB implementation and scope. Resource-policy implementation changes invalidate application of that packet to current source; its stored `satisfied` value is not a new assessment of those changes. The historical `evidence/README.md` (SHA256 `f8cbfcb8f89e1b6134e4f5a06f8baf9058c5140ed58f4935c83eb37a98ae9e69`) records that subsequent full-physics runs encountered memory-limit kills. That README reports VM `CONSTRAINT_MEMCG` observations; this closure does not independently recount them as current cgroup-stress qualification. New profile evidence belongs in the separate `work/wave01/evidence-8g` directory, with new scope/report identities. No old report was rewritten or promoted by this reviewer.
