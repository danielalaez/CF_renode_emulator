#!/bin/bash
# One-time build of the Renode-CF Docker runtime (Mono + libzmq5).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE="${RENODE_DOCKER_IMAGE:-renode-cf-runner:22.04}"

echo "Building ${IMAGE} ..."
docker build -t "${IMAGE}" -f "${ROOT}/docker/Dockerfile.runner" "${ROOT}/docker"
echo "Done. Run: DOCKER=1 ./scripts/run_first_test.sh"
