#!/bin/bash
# Stream IMU into a running Renode and wait until gyro bias calib passes.
# Terminal 1: RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh
# Terminal 2: ./scripts/check_calib.sh [port] [--timeout 120] [--hz 200]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-${RENODE_MONITOR_PORT:-9999}}"
shift || true
exec "${ROOT}/inject_imu_stream.py" "${PORT}" --wait-calib --hz "${IMU_HZ:-200}" "$@"
