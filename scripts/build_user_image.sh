#!/usr/bin/env bash
# Build the DreamAgent per-user workspace Docker image.
#
# Idempotent. Run on the worker VPS (requires Docker daemon access).
# Result: dreamagent/user-workspace:latest (+ :git-sha tag for rollback).
#
# Usage:
#   ./scripts/build_user_image.sh                      # default versions
#   CLAUDE_CODE_VERSION=2.1.85 ./scripts/build_user_image.sh
#   PYTHON_VERSION=3.12.3 NODE_MAJOR=22 ./scripts/build_user_image.sh
#
# See docs/container_isolation.md §13 for the full hardening list applied
# at `docker run` time (NOT here — this script only builds the image).

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────
# Config (env-overridable)
# ─────────────────────────────────────────────────────────────────────
CLAUDE_CODE_VERSION="${CLAUDE_CODE_VERSION:-2.1.83}"
NODE_MAJOR="${NODE_MAJOR:-22}"
# Python comes from the python:3.12-slim base image — no build-from-source.

IMAGE_NAME="dreamagent/user-workspace"
IMAGE_TAG_LATEST="${IMAGE_NAME}:latest"

# Resolve repo root regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DOCKERFILE_PATH="${REPO_ROOT}/docker/Dockerfile.user"
CONTEXT_DIR="${REPO_ROOT}"

# ─────────────────────────────────────────────────────────────────────
# Preconditions
# ─────────────────────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker CLI not found. Install Docker CE first." >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "ERROR: docker daemon not reachable. Start dockerd or add user to docker group." >&2
    exit 1
fi

if [[ ! -f "${DOCKERFILE_PATH}" ]]; then
    echo "ERROR: Dockerfile not found at ${DOCKERFILE_PATH}" >&2
    exit 1
fi

if [[ ! -f "${REPO_ROOT}/docker/claude.settings.json" ]]; then
    echo "ERROR: docker/claude.settings.json not found (Dockerfile COPYs it in)." >&2
    exit 1
fi

# ─────────────────────────────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────────────────────────────
GIT_SHA="$(git -C "${REPO_ROOT}" rev-parse --short=12 HEAD 2>/dev/null || echo "unknown")"
BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "=============================================="
echo " Building ${IMAGE_TAG_LATEST}"
echo "=============================================="
echo " Claude CLI : @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"
echo " Node       : ${NODE_MAJOR}.x"
echo " Python     : 3.12 (from python:3.12-slim base)"
echo " Git SHA    : ${GIT_SHA}"
echo " Build date : ${BUILD_DATE}"
echo " Context    : ${CONTEXT_DIR}"
echo "=============================================="
echo

docker build \
    --file "${DOCKERFILE_PATH}" \
    --tag "${IMAGE_TAG_LATEST}" \
    --tag "${IMAGE_NAME}:${GIT_SHA}" \
    --build-arg CLAUDE_CODE_VERSION="${CLAUDE_CODE_VERSION}" \
    --build-arg NODE_MAJOR="${NODE_MAJOR}" \
    --label "org.opencontainers.image.title=${IMAGE_NAME}" \
    --label "org.opencontainers.image.version=${GIT_SHA}" \
    --label "org.opencontainers.image.created=${BUILD_DATE}" \
    --label "dreamagent.claude_code_version=${CLAUDE_CODE_VERSION}" \
    --label "dreamagent.node_major=${NODE_MAJOR}" \
    "${CONTEXT_DIR}"

# ─────────────────────────────────────────────────────────────────────
# Verify
# ─────────────────────────────────────────────────────────────────────
echo
echo "=============================================="
echo " Build complete"
echo "=============================================="
docker images "${IMAGE_NAME}" --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}"

echo
echo "Quick smoke test (claude --version inside the image):"
docker run --rm --user 1001:1001 "${IMAGE_TAG_LATEST}" claude --version

echo
echo "Next steps:"
echo "  1. Create the dreamagent-net bridge network (one-time):"
echo "     docker network create dreamagent-net 2>/dev/null || true"
echo "  2. Prepare the shared cache dir (one-time):"
echo "     mkdir -p /srv/cache/npm /srv/cache/pip"
echo "     chown -R 1001:1001 /srv/cache"
echo "  3. ContainerManager picks up the image automatically on next ensure_container() call."
