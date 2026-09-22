#!/usr/bin/env bash
# Build only fixed toolchain inputs. Call from repository root.
set -euo pipefail
if [ -z "${DOCKER_HOST:-}${DOCKER_CONTEXT:-}" ]; then
    echo 'Set DOCKER_HOST or DOCKER_CONTEXT explicitly to the isolated Linux builder.' >&2
    exit 2
fi
target=${1:-verifier}
image_tag=${2:-physharness-formal:lean433}
case "$target" in verifier|physics) ;; *) echo 'Target must be verifier or physics.' >&2; exit 2 ;; esac
if command -v docker-buildx >/dev/null 2>&1; then
    set -- docker-buildx
else
    set -- docker buildx
fi
# The tested context allowlist excludes generated state and unrelated files.
python3 tools/formal_environment.py build-context | "$@" build --progress=plain --load \
    --file formal/Dockerfile --target "$target" --tag "$image_tag" -
