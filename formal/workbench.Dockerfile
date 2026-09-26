# Research workbench derived from the measured physics image. Build this only on
# the dedicated Linux Docker endpoint, then record and use the resulting digest.
ARG BASE_IMAGE=sha256:84deccc518a7aa5ce916d15236dac5ae416a5288449bd8620a2c8bb374c24b67
FROM ${BASE_IMAGE}
USER root
# The base image uses the immutable 2026-09-01 Debian snapshot. Package versions
# are resolved from that snapshot; the resulting image digest pins actual bytes.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-numpy python3-scipy python3-sympy python3-mpmath ripgrep && \
    rm -rf /var/lib/apt/lists/* && \
    python3 -c 'import numpy,scipy,sympy,mpmath; print(numpy.__version__,scipy.__version__,sympy.__version__,mpmath.__version__)'
USER 65532:65532
WORKDIR /work
