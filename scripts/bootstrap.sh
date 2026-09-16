#!/bin/bash
# One-shot bootstrap for colleagues: firmware + Bitcraze Renode + Docker runner image.
# Requires: Docker, ~20–40 GB free disk, ~30–60 min first run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT}"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: Docker is required. Install Docker Desktop / engine, then re-run."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker daemon not reachable. Start Docker and re-run."
  exit 1
fi

echo "=== 1/3 Build Crazyflie firmware (bitcraze/builder) ==="
./scripts/build_firmware.sh

echo
echo "=== 2/3 Build Bitcraze Renode (crazyflie branch) via Docker ==="
echo "This is slow the first time (clone + Mono build)."
DOCKER=1 ./scripts/setup_renode_cf.sh

echo
echo "=== 3/3 Build Renode runtime image (mono-complete, cached) ==="
./scripts/build_docker_runner.sh

echo
echo "Bootstrap complete."
echo
echo "Run the smoke test:"
echo "  RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh"
echo
echo "In a second terminal (after Machine started.):"
echo "  ./scripts/monitor_cpu.sh 9999"
