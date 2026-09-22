# Formal environment implementation evidence — 2026-09-15

Worktree: `/Users/kieranpi/Desktop/Projects/PhysHarnessV2/.worktrees/formal-research-loop`.
All Lean compilation occurred in the dedicated aarch64 Linux Colima VM, using
`DOCKER_HOST=unix:///private/tmp/physharness-colima/default/docker.sock`.
No candidate Lean executed on the Mac, no fake Landrun was used, and no production
containment check was disabled.

## Verified dependency selection

Public upstream repository API/raw files and codeload archives were retrieved on 2026-09-15.
Current Physlib (`405848179db6375f814021e804a37dc0dda66d91`) includes both Physlib and
QuantumInfo and declares Lean 4.33.0. Its Lake manifest pins Mathlib
`db584cd6d46c92f209a44c0f1c829460d327499d` and 13 other dependencies. All 19 source archives
(checker sources plus full Physlib Lake dependency closure) were downloaded and SHA256-hashed.
The full URLs, revisions and hashes are committed in `formal/environment.lock.json`.

Comparator HEAD uses 4.34.0. Its toolchain history identified the matching 4.33.0 revision
`3927ad383f208ae977c340a91c48ac9b497d2097`; that exact commit pins exporter
`15f6055e299ad5b89345e533cc2192f4cc00f659`. No cross-version port was invented.
Landrun and nanoda sources are pinned at the actual revisions in the lock.

GitHub's release asset metadata supplied the Lean Linux archive SHA256 values; the real
arm64 image build downloaded and verified the 575,937,537-byte archive. The resulting
compiler reports Lean 4.33.0, commit `d8b18978322de05a8f3dba51ef03cf5461676c17`.
Both amd64 and arm64 asset pins are recorded; amd64 has not been built here.
Official Docker Registry manifest responses supplied the pinned Rust and Go image digests.
The apt repository is the signed Debian snapshot `20260901T000000Z`.

## Commands and outcomes

1. Added source-provenance tests before the utility existed, then ran:

   `.venv/bin/python -m pytest tests/test_formal_environment.py -q`

   Initial result: 12 failures for the absent utility/lock. Subsequent regression additions
   reproduced the OS-directory-alias issue, non-idempotent Lake preparation, and shared
   partial-download-file collision before their fixes. Current result: **21 passed** (22 including the infrastructure metadata regression).

2. Checked actual toolchain manifests for every pinned dependency. No conflicting resolved
   revision was found across their committed Lake manifests.

3. Ran:

   `.venv/bin/ruff check tools/formal_environment.py formal/prepare_lake.py formal/record_build.py tests/test_formal_environment.py`

   Result: **All checks passed** after formatting/fixes.

4. Generated and reproduced the declaration inventory:

   ```sh
   .venv/bin/python tools/formal_environment.py audit \
     --cache /tmp/physharness-formal-sources --output formal/declarations.audit.json
   .venv/bin/python tools/formal_environment.py audit \
     --cache /tmp/physharness-formal-sources --output .state/formal/declarations.audit.reproduced.json
   cmp formal/declarations.audit.json .state/formal/declarations.audit.reproduced.json
   ```

   Result: both commands inventoried 27 requested declarations in five actual source modules;
   `cmp` returned 0. Hash verification occurs before fresh archive extraction. The source
   inventory explicitly records semantic review, kernel check, sandbox qualification and
   transitive axiom closure as unperformed.

5. Built the core image:

   ```sh
   COPYFILE_DISABLE=1 tar --no-xattrs -cf - formal tools/formal_environment.py \
     src/physharness/verification/container_driver.py |
     DOCKER_HOST=unix:///private/tmp/physharness-colima/default/docker.sock \
       docker-buildx build --progress=plain --load -f formal/Dockerfile \
         --target verifier -t physharness-formal:lean433 -
   ```

   Result: Go module checksum verification and real Landrun build passed; Cargo `--locked`
   release build of nanoda passed; offline Comparator/exporter Lake build passed all 20 jobs.
   Full original log: `/tmp/physharness-formal-build.log`.
   Observed image: `sha256:cadb65787cb75657516379dc91f3870c6c473e3df11b907428f522ceff360eca`.
   `formal/build-observations.aarch64.json` contains the measured binary hashes, versions,
   prepared Lake manifest hashes and actual image identity.

   Initial invocation using `docker build --progress=plain` failed because the Docker CLI
   did not discover the installed Buildx plugin. A legacy tar attempt then failed on macOS
   `com.apple.provenance` xattrs. Direct `docker-buildx` with a stripped context succeeded.
   The committed `formal/build-image.sh` uses Python tarfile to avoid xattrs and excludes
   irrelevant workspace files from the context.

6. Extracted the actual image metadata with a read-only, networkless container, appended the
   measured image ID from `docker image inspect`, and compared its driver SHA256 to the
   current repository driver. Both were
   `a5df1f833fa05d5a172f1285ad40a0c5e3100944ff36a2d539355ce3bbe919a7`.
   Sent this metadata to the acceptance agent for live engineering checks.

7. The acceptance agent ran both core engineering suites: **9/9 kernel and 9/9 independent
   nanoda** cases passed. The stable reports are
   `work/acceptance-evidence/engineering-kernel-report.json` and
   `work/acceptance-evidence/engineering-independent-report.json`.
   These tests are engineering evidence, not a production qualification signoff.

8. Started the physics target with the same isolated endpoint and source-only context,
   `--target physics -t physharness-formal:physics433`.
   Log: `/tmp/physharness-physics-build.log`. Source compilation completed successfully:
   **8,790/8,790 jobs in 2,515 seconds**, including the requested Physlib and QuantumInfo
   roots. Final image/audit/proof outcomes are recorded below.

   The first image export exhausted the dedicated VM's 60 GiB disk while unpacking a
   compiled Mathlib layer. The successful compilation log and the failed unpack diagnostic
   are preserved at `.state/formal/physics-source-build.log`. Docker retained the image
   manifest `sha256:7b64cd4c6371e872f58207c4913cbafb46dc958a5b7b66a38f3e63fed5944c35`;
   this observation alone does not establish a runnable image or passed proof test.

9. Root expanded the same isolated VM data disk from 60 GiB to 160 GiB (6 CPUs,
   12 GiB RAM, aarch64 VZ), preserving the compiled image. Ran the fixed declaration
   audit in a small recovery layer:

   ```sh
   DOCKER_HOST=unix:///private/tmp/physharness-colima/default/docker.sock \
     docker-buildx build --network=none --progress=plain --load \
       -f .state/formal/physics-audit/Dockerfile \
       -t physharness-formal:physics433-audited .state/formal/physics-audit
   ```

   Result: all 27 qualified `#check`/`#print axioms` commands passed in 12.7 seconds.
   `Qubit` depends on no axioms; the other 26 declarations report only `propext`,
   `Classical.choice`, and `Quot.sound`. Image: `sha256:b8cef3506481cd9ce3b278c304e345d9d1db704269400123714cc6ecc666b6ec`.
   An earlier stdin-tar invocation was rejected by Buildx before execution: Python's
   leading PAX metadata header did not fit Buildx's short archive recognition peek.
   Added a failing regression, switched the reusable context to USTAR, and verified:

   ```sh
   .venv/bin/python tools/formal_environment.py build-context |
     DOCKER_HOST=unix:///private/tmp/physharness-colima/default/docker.sock \
       docker-buildx build --check --file formal/Dockerfile -
   ```

   Result: `Check complete, no warnings found.` The build wrapper is mode 0644;
   documentation invokes it with `bash` so GitHub content-API publication preserves usage.

10. The first genuine library test failed closed before proof acceptance because upstream
    Physlib enables Lake's local artifact cache. Lake tried to chmod imported `.olean`
    files in the read-only dependency tree. The original failed report is retained as
    `formal/evidence/physics/before-cache-fix-report.json`; it is not counted as an attack pass.

    Both formal and acceptance agents independently inspected the pinned Lake source.
    The supported package setting has precedence over workspace/environment defaults.
    Added a tested, idempotent preparation overlay preserving `lakefile.upstream.toml`
    and changing only `enableArtifactCache = true` to `false`. Unexpected upstream
    configuration fails closed. Upstream SHA256 is
    `903e753340d0af869d1527225256464ef208e2c19b42a6171eb3a59ae82acaea`;
    prepared SHA256 is `1aaa5325ab697e777d5a1af163dfd79b2ee1bf8353797751cbfe587474b023da`.
    Compiler options, Lean declaration sources and the verification driver are unchanged.

    ```sh
    DOCKER_HOST=unix:///private/tmp/physharness-colima/default/docker.sock \
      docker-buildx build --network=none --progress=plain --load \
        -f .state/formal/physics-runtime/Dockerfile \
        -t physharness-formal:physics433-final .state/formal/physics-runtime
    ```

    This layer required `lake --offline --no-build build` for the three selected roots.
    Result: **All targets up-to-date (8790 jobs)**, followed by another successful
    declaration audit. Final image: `sha256:6179eb7308aaba0ee8287f24857cd122efede0fb9acf8b9fa217ed030e386a68`.

11. Extracted actual metadata and input hashes using read-only, networkless trusted
    Python containers. Verified the driver SHA against the repository, then ran:

    ```sh
    export DOCKER_HOST=unix:///private/tmp/physharness-colima/default/docker.sock
    export TMPDIR="$PWD/.state/tmp"
    PYTHONPATH=src .venv/bin/python infra/run_qualified_lean.py \
      --engineering-image-metadata .state/formal/physics-image-metadata.json \
      --fixtures formal/library-cases.json \
      --output .state/formal/library-engineering-kernel.json
    PYTHONPATH=src .venv/bin/python infra/run_qualified_lean.py \
      --engineering-image-metadata .state/formal/physics-image-metadata.json \
      --fixtures formal/library-cases.json --publication \
      --output .state/formal/library-engineering-independent.json
    ```

    Result: **3/3 kernel and 3/3 independent nanoda cases passed**. Both the harmonic
    oscillator identity and Pauli-X involution verified; the sorried quantum theorem was
    rejected with the required causal `Illegal axiom detected: 'sorryAx'` diagnostic.
    The independent positive logs explicitly report both nanoda and Lean acceptance.
    No production sandbox controls were relaxed and no optional attack probes rerun.

12. Archived measured metadata, declaration output, both final reports, initial failure,
    exact recovery Dockerfiles and small build logs under `formal/evidence/physics/`.
    `index.json` binds their hashes, source lock, fixture inputs, embedded helper hashes,
    VM size, image identities and local full-build log hash. The measured image came from
    the original source build plus two recovery layers; it retains the original recursive
    chmod layer. The consolidated current full Dockerfile has passed `--check`, but was
    not rebuilt end to end after the recovery changes. This distinction is explicit in
    the public provenance. Root owns persistent image export and VM shutdown.

## Scope and remaining trust requirements

Included reusable definitions are harmonic oscillator/Hamilton equations, Pauli gates,
density states/partial traces, and positive matrices. PhyslibAlpha is excluded from selected
roots. The fixed `DeclarationAudit.lean` uses qualified names and `#print axioms`; it is
executed only after the physics imports build. `formal/library-cases.json` adds actual
Physlib and QuantumInfo import tests (two positive claims and a sorry case).

No library is granted expert approval by the source lock, source audit or build artifact.
The published upstream category is not the harness's semantic review. A new physics target
still requires review of the specific definitions, assumptions, units and conventions.
Production qualification additionally requires the full scoped Linux attack campaign and
an operator-approved report pinned to the runtime, image, launcher, driver and policy.
