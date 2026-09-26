# Research workbench v2 derived from the measured physics image. Build this only on
# the dedicated Linux Docker endpoint, then record and use the resulting digest.
#
# Workbench v2 is a definition only: rebuild and qualification are pending user
# approval. formal/workbench.Dockerfile (v1) stays the qualified definition until
# then. The build context is exactly this file plus workbench-requirements.lock (see
# docs/FORMAL_ENVIRONMENT.md, "Workbench v2 (pending rebuild)"). Replace every
# TODO(pin-at-rebuild) in this file and in the lock first. The pin gate below fails
# the build while any placeholder or malformed pin remains.
ARG BASE_IMAGE=sha256:84deccc518a7aa5ce916d15236dac5ae416a5288449bd8620a2c8bb374c24b67
FROM ${BASE_IMAGE}
USER root
# The leanprover-community/repl commit whose lean-toolchain is exactly the image's
# leanprover/lean4:v4.33.0, and the SHA256 of that commit's codeload tarball.
# Edit these defaults instead of passing --build-arg, so this file identifies the image.
ARG LEAN_REPL_REVISION="TODO(pin-at-rebuild)"
ARG LEAN_REPL_SHA256="TODO(pin-at-rebuild)"
COPY workbench-requirements.lock /opt/workbench/requirements.lock
RUN if grep -v '^[[:space:]]*#' /opt/workbench/requirements.lock | grep 'TODO(pin-at-rebuild)'; then \
        echo 'Unpinned workbench-requirements.lock: resolve every TODO(pin-at-rebuild).' >&2; \
        exit 1; \
    fi && \
    if ! printf '%s\n' "$LEAN_REPL_REVISION" | grep -Eqx '[0-9a-f]{40}' || \
       ! printf '%s\n' "$LEAN_REPL_SHA256" | grep -Eqx '[0-9a-f]{64}'; then \
        echo 'Unpinned Lean REPL: LEAN_REPL_REVISION/LEAN_REPL_SHA256 need exact values.' >&2; \
        exit 1; \
    fi
# The base image uses the immutable 2026-09-01 Debian snapshot. Package versions
# are resolved from that snapshot; the resulting image digest pins actual bytes.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-numpy python3-scipy python3-sympy python3-mpmath ripgrep \
    python3-networkx python3-matplotlib python3-z3 python3-pip && \
    rm -rf /var/lib/apt/lists/*
# Wheels the snapshot does not package, pinned by exact version and SHA256. --no-deps:
# every runtime dependency is a Debian package above or its own pinned lock line, and
# pip check proves it. --only-binary forbids source builds. --target keeps these files
# apart from Debian's; the .pth appends them after Debian's dist-packages on sys.path.
RUN python3 -m pip install --no-cache-dir --no-deps --require-hashes --only-binary=:all: \
        --target /opt/workbench/site-packages -r /opt/workbench/requirements.lock && \
    echo /opt/workbench/site-packages > /usr/lib/python3/dist-packages/physharness-workbench.pth && \
    python3 -m pip check
# Lean REPL from the exact commit tarball, hash-verified and path-checked by the base
# image's formal_environment helpers, then built by the image's own lake. LeanSession
# expects the binary at /opt/lean-repl/.lake/build/bin/repl.
RUN python3 -c 'import sys; sys.path.insert(0, "/opt/verifier"); from pathlib import Path; from formal_environment import download_verified, extract_verified; revision, digest = sys.argv[1:3]; archive = Path("/tmp/lean-repl.tar.gz"); download_verified("https://codeload.github.com/leanprover-community/repl/tar.gz/" + revision, digest, archive); extract_verified(archive, digest, Path("/opt/lean-repl")); archive.unlink()' \
        "$LEAN_REPL_REVISION" "$LEAN_REPL_SHA256" && \
    if [ "$(cat /opt/lean-repl/lean-toolchain)" != "leanprover/lean4:v4.33.0" ]; then \
        echo 'Lean REPL commit does not declare the image toolchain leanprover/lean4:v4.33.0.' >&2; \
        exit 1; \
    fi
WORKDIR /opt/lean-repl
RUN lake --offline build repl && test -x /opt/lean-repl/.lake/build/bin/repl
RUN python3 -c 'import numpy,scipy,sympy,mpmath,flint,cvxpy,clarabel,scs,osqp,z3,networkx,matplotlib; print(numpy.__version__,scipy.__version__,sympy.__version__,mpmath.__version__,cvxpy.__version__,networkx.__version__,matplotlib.__version__,z3.get_version_string())'
# Headless plotting without per-import warnings about an unwritable home directory.
ENV MPLBACKEND=Agg MPLCONFIGDIR=/tmp/matplotlib
USER 65532:65532
WORKDIR /work
