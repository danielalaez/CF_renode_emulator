#!/bin/bash
# Stream IMU into a running Renode until supervisor past pre-flight checks.
# Terminal 1: RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh
# Terminal 2: ./scripts/check_preflight.sh [port] [--timeout 180] [--hz 200]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-${RENODE_MONITOR_PORT:-9999}}"
shift || true
exec "${ROOT}/inject_imu_stream.py" "${PORT}" --wait-preflight --hz "${IMU_HZ:-200}" "$@"
