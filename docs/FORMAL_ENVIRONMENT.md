# Pinned formal environment

The repository can build real Linux Lean, Comparator, lean4export, Landrun and nanoda
from pinned inputs. The first aarch64 core image was built on 2026-09-15. Its measured
binary hashes are in `formal/build-observations.aarch64.json`; this is build evidence,
not approval to accept a scientific result. Sandbox attack tests and expert review
remain separate requirements in [VERIFICATION.md](VERIFICATION.md).
The current consolidated physics image is
`sha256:84deccc518a7aa5ce916d15236dac5ae416a5288449bd8620a2c8bb374c24b67`.
Its final 8 GiB scope and control results are in the
[current Wave 0/1 delivery](../work/wave01/DELIVERY-2026-09-22.md). Both physics
modes completed with their expected engineering outcomes. The current and historical
images were archived with an integrity check, and the dedicated VM was observed
stopped. Fresh-VM restore and human review remain pending.

## Version matrix

| Component | Pinned version / source commit | Compatibility evidence |
| --- | --- | --- |
| Lean | 4.33.0; `d8b18978322de05a8f3dba51ef03cf5461676c17` | Real aarch64 release reports this commit; both Linux archive hashes pinned |
| Comparator | `3927ad383f208ae977c340a91c48ac9b497d2097` | Upstream declares Lean 4.33.0; built with that release |
| lean4export | `15f6055e299ad5b89345e533cc2192f4cc00f659` | Exact dependency in Comparator's upstream Lake manifest; built |
| Mathlib | `db584cd6d46c92f209a44c0f1c829460d327499d` | Physlib's exact resolved 4.33.0 dependency; source compilation passed |
| Physlib | `405848179db6375f814021e804a37dc0dda66d91` | Selected roots compiled; classical library proof passed contained verification |
| QuantumInfo | Same Physlib commit | Same source tree and Lake project; quantum library proof passed contained verification |
| Landrun | `811cfff51ceaf3d9843708aa6d22e9b84ccac8b4` | Real Go binary built; requires live kernel qualification |
| nanoda | `4c544ed4099c8227f07d5de77ad1e69fb0740a27` | Built with Cargo `--locked`; replay compatibility is tested separately |

The current Comparator head declared 4.34.0 when inspected. This environment deliberately
uses its 4.33.0 revision so the physics libraries and checkers share a release. Physlib and
QuantumInfo require no cross-toolchain bridge at the chosen revision. QuantumInfo retains
its own conventions and review norms upstream. PhyslibAlpha is outside the selected import
roots; no dependency is automatically granted semantic approval by its upstream category.

[Comparator pin](https://github.com/leanprover/comparator/tree/3927ad383f208ae977c340a91c48ac9b497d2097),
[exporter pin](https://github.com/leanprover/lean4export/tree/15f6055e299ad5b89345e533cc2192f4cc00f659),
[Physlib and QuantumInfo pin](https://github.com/leanprover-community/physlib/tree/405848179db6375f814021e804a37dc0dda66d91),
[Mathlib pin](https://github.com/leanprover-community/mathlib4/tree/db584cd6d46c92f209a44c0f1c829460d327499d),
[Landrun pin](https://github.com/Zouuup/landrun/tree/811cfff51ceaf3d9843708aa6d22e9b84ccac8b4),
[nanoda pin](https://github.com/ammkrn/nanoda_lib/tree/4c544ed4099c8227f07d5de77ad1e69fb0740a27).

## Rebuild

Use an isolated Linux Docker builder. Source compilation may execute build tools and
upstream metaprograms; do not send candidate sources to the builder or run them on the Mac.
The build wrapper requires an explicit Docker endpoint/context. It sends only formal inputs,
the source utility and the driver, excluding the workspace's credentials, state and venv.

From the repository root, with an explicit endpoint for your isolated Linux builder:

On Apple Silicon macOS, this creates a dedicated Colima VM with only the current
worktree mounted. Another isolated Linux Docker builder is also acceptable. Keep this
profile separate from personal containers; these commands do not activate its context,
forward an SSH agent, edit SSH configuration, or enable port forwarding.

```sh
export COLIMA_HOME="$HOME/.local/share/physharness-colima"
mkdir -p "$COLIMA_HOME"
colima start --arch aarch64 --vm-type vz --cpus 6 --memory 12 --disk 160 \
  --mount "$PWD:w" --activate=false --ssh-config=false --ssh-agent=false \
  --port-forwarder=none
export DOCKER_HOST="unix://$COLIMA_HOME/default/docker.sock"
export TMPDIR="$PWD/.state/tmp"
mkdir -p "$TMPDIR"
```

```sh
.venv/bin/python tools/formal_environment.py validate
bash formal/build-image.sh verifier physharness-formal:lean433
bash formal/build-image.sh physics physharness-formal:physics433
```

The second command builds the selected physics modules and their transitive imports from
source. At this pin, QuantumInfo.ForMathlib.Filter and Majorization import the entire
Mathlib root; the observed source build completed 8,790 jobs. It is
significantly larger than the core checker build. The default `verifier`
target supports Lean's standard library. Only the `physics` target includes the selected
Mathlib, Physlib and QuantumInfo build artifacts. Neither target is named "qualified".
The final image uses UID/GID 65532 and the fixed container driver entrypoint.
The observed build used an aarch64 VM with 6 CPUs, 12 GiB RAM and a 160 GiB data disk.
The original 60 GiB disk ran out of space during Docker layer unpacking after compilation;
expanding that same VM preserved the completed build.

New VMs must keep `COLIMA_HOME` in persistent user-owned storage as above. With Colima 0.10.3,
the directory must exist before `colima start`; otherwise Colima silently uses its default
`~/.colima` home, and the `DOCKER_HOST` path shown above will point to a nonexistent socket.
Historical evidence
and commands identify the earlier dedicated VM at `/private/tmp/physharness-colima`; do not
migrate or recreate that VM merely to rewrite its provenance. In the current recovery incident,
temporary Colima metadata disappeared while the VM or Docker endpoint could still exist, so
`colima status` alone was misleading. Verify the actual Docker socket/endpoint and the Colima
host agent before deciding whether the runtime is present or recoverable.

`formal/environment.lock.json` pins 19 source archives by full revision and SHA256, Lean
4.33.0 Linux amd64/arm64 release archives by SHA256, the official Rust 1.90.0 and Go 1.25.1
builder image digests, and Debian's signed package snapshot at `20260901T000000Z`.
Source archives were downloaded and hashed during implementation. Lean archive hashes came
from GitHub release asset metadata and were checked against actual downloaded bytes during
the aarch64 build. The amd64 archive remains unbuilt here.

The builder verifies archive hashes before extraction, rejects escaping paths and links,
uses Cargo's lockfile and Go's checksum manifest, and uses `lake --offline build`.
`prepare_lake.py` checks every resolved revision and preserves the original Lake manifest
before changing dependency locations to `/opt/sources/<package>`. The preparation also
preserves Physlib's `lakefile.upstream.toml` and changes only `enableArtifactCache` to
`false`: its upstream setting otherwise attempts to chmod/cache imported oleans during
checking, which fails against the read-only image. The original and prepared configuration
hashes are recorded; Lean declarations and compiler options are preserved. No Mathlib
olean cache is downloaded by this build recipe. The lock records source-resolution status; later build and engineering results live in
separate evidence records so they do not rewrite the source identity. The build remains
subject to compiler/toolchain trust and hardware variation; reproducible pinned inputs are
not a claim that independently rebuilt binaries must be bit-for-bit identical.

The recorded image paths are:

- `/opt/lean/bin/lean` and `/opt/lean/bin/lake`
- `/opt/verifier/bin/comparator`, `lean4export`, `landrun`, `nanoda_bin`
- `/opt/verifier/metadata/environment.lock.json`, `build.json`, `dpkg-packages.txt`
- `/opt/sources/<package>` with original and prepared Lake manifests
- `/opt/verifier/metadata/declarations-kernel.txt` in a successful `physics` image

Export `build.json` from the finished image using a trusted metadata read, and append the
actual `docker image inspect --format '{{.Id}}' IMAGE` digest. The acceptance runner consumes
this JSON using `--engineering-image-metadata`. Never replace a measured digest with a guessed
one. Record the final driver's hash too; editing the driver requires rebuilding the image.
`formal/build-observations.aarch64.json` identifies the observed local image, not a published
registry artifact that other machines can pull.

The measured physics image is `physharness-formal:physics433-final`, digest
`sha256:6179eb7308aaba0ee8287f24857cd122efede0fb9acf8b9fa217ed030e386a68`.
It was completed through two small recovery layers after the original source build:
the fixed declaration audit, then the Physlib cache setting correction. The latter passed
`lake --offline --no-build build` for all 8,790 targets, and reran the declaration audit.
The original base includes an earlier recursive read-only chmod layer. The current full
Dockerfile includes the cache preparation and audit directly and omits that redundant
chmod; it has passed Buildx's nonexecuting check but was not rebuilt end to end after
these changes. Exact observed recovery Dockerfiles, their inputs and evidence hashes are
in [physics evidence](../formal/evidence/physics/index.json).

## Use the selected physics libraries

For a fresh trusted challenge bundle, use `formal/lakefile.physics.toml` as `lakefile.toml`,
`formal/lake-manifest.physics.json` as `lake-manifest.json`, and `formal/lean-toolchain`.
Hash those exact files into the bundle's environment manifest. They reference prebuilt
`/opt/sources/physlib` and its pinned dependencies; these image paths stay read-only at
verification time. The only writable Lake build directory for challenge/candidate modules
is the fresh `/work/.lake` created by the trusted runner. A metadata-only bundle cannot
silently enable physics imports in the smaller core image.

Only the selected import closure is built, not every declaration in the upstream monorepo.
If a challenge imports another module, extend the builder's explicit roots, rebuild, audit
that closure, and separately qualify the changed image. Never allow Lake to retrieve a
missing dependency during checking.

## Declaration audit

`formal/declarations.selection.json` chooses 27 actual declarations across five modules:
Hamilton's equations, harmonic oscillator energy and dynamics, qubit gates, density
operators and partial traces, and positive (semi)definite matrices. Names are source
spellings; the accompanying `DeclarationAudit.lean` records their qualified names.

The committed `formal/declarations.audit.json` is an inventory generated from fresh
extractions of the hash-verified Mathlib and Physlib archives. It records source SHA256,
line numbers, direct imports, declaration kind, lock/selection digests, and risk tokens.
Nested comments and strings are masked to avoid reporting documentation as declarations.
The scan is deliberately labeled `lexical_source_inventory`: it is not a Lean parser,
full import-closure audit, axiom-closure computation, or semantic review.

Reproduce without executing Lean:

```sh
.venv/bin/python tools/formal_environment.py fetch --cache .state/formal/archives
.venv/bin/python tools/formal_environment.py audit \
  --cache .state/formal/archives --output .state/formal/declarations.audit.json
cmp formal/declarations.audit.json .state/formal/declarations.audit.json
```

A wrong hash, missing declaration, unsafe path, or existing output file fails closed.
The `physics` image additionally runs the fixed `DeclarationAudit.lean` after building
its imports. `#check` validates qualified declarations and `#print axioms` reports their
actual Lean axiom closures in `declarations-kernel.txt`. This audit output is build evidence,
not a Comparator acceptance receipt and not an expert assessment of the physics model.
If the image build fails, no compiled declaration audit is claimed.
The observed final image passed all 27 checks. `Qubit` reported no axioms; the other
26 declarations reported only `propext`, `Classical.choice`, and `Quot.sound`.
The exact output is [archived here](../formal/evidence/physics/declarations-kernel.txt).

Before scientific use, review the actual definition bodies, hypotheses, units and conventions,
record the named expert's approval against the immutable target revision, and verify the
candidate with the separately qualified Comparator boundary. In particular, a smoothness
hypothesis, finite-dimensional Hilbert-space model, or idealized oscillator is part of the
claim being reviewed, not an assumption an inventory may hide.

The additional `formal/library-cases.json` suite imports the actual library model. It checks
the harmonic oscillator identity `ω² = k/m`, the Pauli-X involution, and nonacceptance of
a sorried quantum theorem. Run it against the physics image's measured metadata:

```sh
PYTHONPATH=src .venv/bin/python infra/run_qualified_lean.py \
  --engineering-image-metadata .state/formal/physics-image-metadata.json \
  --fixtures formal/library-cases.json --output .state/formal/library-engineering.json
```

The archived core checker engineering results are
[Lean-kernel cases](../work/acceptance-evidence/engineering-kernel-report.json) and
[independent nanoda cases](../work/acceptance-evidence/engineering-independent-report.json).
Those core fixtures exercise the standard-library environment; the library suite has
its own result and does not inherit a pass from them.
The final physics image passed **3/3 kernel cases and 3/3 independent nanoda cases**.
Both positive library proofs were accepted by Lean and nanoda in the independent run;
the negative case was rejected specifically for `sorryAx`. The reports and measured
image identity are in [physics evidence](../formal/evidence/physics/index.json).
