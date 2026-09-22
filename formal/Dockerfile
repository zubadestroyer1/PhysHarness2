# Build context is the repository root. The output is NOT a qualified verifier.
# Source hashes/versions are in formal/environment.lock.json; no untrusted candidate
# source enters any build stage. Publication qualification is a separate operation.
FROM golang:1.25.1-bookworm@sha256:c423747fbd96fd8f0b1102d947f51f9b266060217478e5f9bf86f145969562ee AS go-toolchain
FROM rust:1.90.0-bookworm@sha256:3914072ca0c3b8aad871db9169a651ccfce30cf58303e5d6f2db16d1d8a7e58f AS builder
COPY --from=go-toolchain /usr/local/go /usr/local/go
ENV PATH="/opt/verifier/bin:/opt/lean/bin:/usr/local/go/bin:${PATH}" GOTOOLCHAIN=local
# Freeze apt repository contents as well as base image. Signed Release metadata is
# still verified; Check-Valid-Until is disabled only because this is an old snapshot.
RUN rm -f /etc/apt/sources.list.d/debian.sources && \
    printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20260901T000000Z/ bookworm main\ndeb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/20260901T000000Z/ bookworm-security main\n' > /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends python3 zstd && \
    rm -rf /var/lib/apt/lists/*
COPY formal/environment.lock.json /opt/verifier/metadata/environment.lock.json
COPY tools/formal_environment.py /opt/verifier/formal_environment.py
COPY formal/prepare_lake.py formal/record_build.py /opt/verifier/
RUN python3 /opt/verifier/formal_environment.py --lock /opt/verifier/metadata/environment.lock.json validate
ARG TARGETARCH
RUN python3 -c 'import json,sys;sys.path.insert(0,"/opt/verifier");from formal_environment import download_verified;from pathlib import Path;a=json.load(open("/opt/verifier/metadata/environment.lock.json"))["lean"]["archives"][sys.argv[1]];download_verified(a["url"],a["sha256"],Path("/tmp/lean.tar.zst"))' "${TARGETARCH:-$(dpkg --print-architecture)}" && \
    mkdir -p /opt/lean && tar --zstd -xf /tmp/lean.tar.zst --strip-components=1 -C /opt/lean && rm /tmp/lean.tar.zst
RUN python3 /opt/verifier/formal_environment.py --lock /opt/verifier/metadata/environment.lock.json fetch --cache /opt/archives --packages comparator lean4export landrun nanoda && \
    python3 /opt/verifier/formal_environment.py --lock /opt/verifier/metadata/environment.lock.json extract --cache /opt/archives --sources /opt/sources --packages comparator lean4export landrun nanoda && \
    python3 /opt/verifier/prepare_lake.py
WORKDIR /opt/sources/landrun
RUN go mod download && go mod verify && go build -mod=readonly -trimpath -o /opt/verifier/bin/landrun ./cmd/landrun
WORKDIR /opt/sources/nanoda
RUN cargo build --locked --release && install -m 0555 target/release/nanoda_bin /opt/verifier/bin/nanoda_bin
WORKDIR /opt/sources/comparator
# --offline prohibits Lake downloads. Archive hashes and manifest revisions were
# checked before rewriting source locations to immutable image-local paths.
RUN lake --offline build comparator lean4export && \
    install -m 0555 .lake/build/bin/comparator /opt/verifier/bin/comparator && \
    install -m 0555 /opt/sources/lean4export/.lake/build/bin/lean4export /opt/verifier/bin/lean4export
RUN python3 /opt/verifier/record_build.py

# Optional physics source-build target. No olean cache is fetched. The selected
# imports include their transitive source dependencies, which can be a long build.
FROM builder AS physics-builder
RUN python3 /opt/verifier/formal_environment.py --lock /opt/verifier/metadata/environment.lock.json fetch --cache /opt/archives && \
    python3 /opt/verifier/formal_environment.py --lock /opt/verifier/metadata/environment.lock.json extract --cache /opt/archives --sources /opt/sources --packages physlib mathlib doc-gen4 plausible LeanSearchClient importGraph proofwidgets aesop Qq batteries leansqlite Cli UnicodeBasic BibtexQuery MD4Lean && \
    python3 /opt/verifier/prepare_lake.py
WORKDIR /opt/sources/physlib
RUN lake --offline build Physlib.ClassicalMechanics.HarmonicOscillator.Basic QuantumInfo.States.Pure.Qubit QuantumInfo.States.Mixed.MState
RUN python3 /opt/verifier/record_build.py
FROM physics-builder AS physics
COPY formal/DeclarationAudit.lean /opt/verifier/DeclarationAudit.lean
RUN lake --offline env lean /opt/verifier/DeclarationAudit.lean > /opt/verifier/metadata/declarations-kernel.txt
COPY src/physharness/verification/container_driver.py /opt/physharness/container_driver.py
RUN chmod 0555 /opt/physharness/container_driver.py
USER 65532:65532
WORKDIR /work
ENTRYPOINT ["/usr/bin/python3", "/opt/physharness/container_driver.py"]

# Default image contains real checkers and Lean's standard library. Build the
# physics target explicitly to include the selected Mathlib/Physlib/QuantumInfo set.
FROM builder AS verifier
COPY src/physharness/verification/container_driver.py /opt/physharness/container_driver.py
RUN chmod 0555 /opt/physharness/container_driver.py
USER 65532:65532
WORKDIR /work
ENTRYPOINT ["/usr/bin/python3", "/opt/physharness/container_driver.py"]
