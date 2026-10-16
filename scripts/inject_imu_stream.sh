#!/bin/bash
# Phase 2a: continuous IMU + DRDY into Renode (host → Docker ports).
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/inject_imu_stream.py" "$@"
