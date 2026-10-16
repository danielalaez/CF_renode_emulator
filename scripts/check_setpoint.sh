#!/usr/bin/env bash
# Inject a hover setpoint and print setpoint_stats + motor_stats.
set -euo pipefail
PORT="${1:-9999}"
THRUST="${2:-35000}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT}/scripts:${PYTHONPATH:-}"
python3 - <<PY
from renode_monitor import RenodeClient
c = RenodeClient(int("${PORT}"))
print(c.query("setpoint_hover ${THRUST}") or "")
print(c.query("setpoint_stats") or "")
print(c.query("motor_stats") or "")
print(c.query("preflight_status") or "")
c.close()
PY
