#!/usr/bin/env bash
# End-to-end hover demo: Renode (Docker) + optional Webots + bridge.
# Conservative CPU defaults to avoid locking the laptop.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAKE="${FAKE:-0}"
SECONDS_RUN="${SECONDS_RUN:-45}"
ALT="${ALT:-0.5}"
# closed-loop: FW Absolute-Z + attitude mixer → Webots m1..m4 1:1
MODE="${MODE:-closed-loop}"
# ALT_HOLD=1 (default): host PD altitude via thrust; FW attitude mixer -> props
# FW_ZDIST=1: FW Absolute-Z setpoint (experimental; needs working baro fusion)
ALT_HOLD="${ALT_HOLD:-1}"
FW_ZDIST="${FW_ZDIST:-0}"
PORT="${RENODE_MONITOR_PORT:-9999}"

export WEBOTS_HOME="${WEBOTS_HOME:-$HOME/.local/webots-R2025a}"
export PYTHONPATH="${WEBOTS_HOME}/lib/controller/python${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="${WEBOTS_HOME}/lib/controller:${WEBOTS_HOME}/lib/webots${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export DISPLAY="${DISPLAY:-:0}"

echo "== hover demo =="
echo "  FAKE=$FAKE MODE=$MODE ALT_HOLD=$ALT_HOLD FW_ZDIST=$FW_ZDIST ALT=${ALT}m SECONDS=$SECONDS_RUN"
echo "  World uses official Bitcraze Crazyflie PROTO (props + motors)."

# --- Renode ---
if ! ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":${PORT}$"; then
  echo "Starting Renode on :${PORT} ..."
  cp -f build/renode-cf/scripts/monitor.py.swarm_orig build/renode-cf/scripts/monitor.py
  { echo; echo "# --- swarm monitor_cf patch ---"; cat scripts/monitor_cf.py; } >> build/renode-cf/scripts/monitor.py
  cp -f firmware/cf2.elf build/renode-cf/cf2.elf
  docker rm -f renode-cf >/dev/null 2>&1 || true
  docker run -d --name renode-cf --net=host \
    -v "${ROOT}/build/renode-cf:/renode-cf:rw" -w /renode-cf \
    renode-cf-runner:22.04 \
    /bin/bash -c 'ln -sf /lib/x86_64-linux-gnu/libdl.so.2 output/bin/Release/libdl.so; export LD_LIBRARY_PATH=/renode-cf/output/bin/Release; exec ./renode --disable-xwt -P '"${PORT}"' crazyflie_canned.resc'
  for i in $(seq 1 40); do
    if docker logs renode-cf 2>&1 | grep -q "Machine started" && ss -ltn | grep -q ":${PORT}"; then
      echo "Renode ready."
      break
    fi
    sleep 1
  done
else
  echo "Renode already listening on :${PORT}"
fi

BRIDGE_ARGS=(
  --mode "$MODE"
  --wait-preflight
  --imu-hz 80
  --loop-hz 12
  --seconds "$SECONDS_RUN"
  --status-every 2
  --port "$PORT"
  --gyro-sign "${GYRO_SIGN:-1,1,1}"
  --gyro-lpf-tau "${GYRO_LPF_TAU:-0.02}"
)
if [[ -n "${TELEMETRY:-}" ]]; then
  BRIDGE_ARGS+=(--telemetry "$TELEMETRY")
fi
if [[ "$MODE" == "closed-loop" ]]; then
  BRIDGE_ARGS+=(
    --thrust "${THRUST:-30500}"
    --hover-thrust "${HOVER_THRUST:-30000}"
    --roll "${ROLL:-0}" --pitch "${PITCH:-0}" --yaw-rate "${YAW_RATE:-0}"
    --alt-target "$ALT"
    --alt-kp "${ALT_KP:-0.40}" --alt-kd "${ALT_KD:-1.10}" --alt-ki "${ALT_KI:-0.04}"
  )
  if [[ "$FW_ZDIST" == "1" ]]; then
    BRIDGE_ARGS+=(--fw-zdist --no-alt-hold)
  elif [[ "$ALT_HOLD" == "1" ]]; then
    BRIDGE_ARGS+=(--alt-hold)
  else
    BRIDGE_ARGS+=(--no-alt-hold)
  fi
else
  BRIDGE_ARGS+=(--force-ratio 0 --alt-target "$ALT"
    --alt-kp "${ALT_KP:-0.40}" --alt-kd "${ALT_KD:-0.90}")
fi

WEBOTS_PID=""
cleanup() {
  if [[ -n "$WEBOTS_PID" ]]; then
    kill "$WEBOTS_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ "$FAKE" == "1" ]]; then
  echo "Running FakePlant hover..."
  python3 -m bridge.webots_renode_bridge --fake "${BRIDGE_ARGS[@]}"
else
  if [[ ! -x "${WEBOTS_HOME}/webots" ]]; then
    echo "Webots not found at WEBOTS_HOME=$WEBOTS_HOME" >&2
    echo "Set FAKE=1 for plant-only, or install Webots R2025a." >&2
    exit 1
  fi
  echo "Starting Webots (mode=realtime, low bridge rate) ..."
  "${WEBOTS_HOME}/webots" --mode=realtime --stdout --stderr \
    "${ROOT}/webots/worlds/cf_hover.wbt" > /tmp/webots_hover.log 2>&1 &
  WEBOTS_PID=$!
  sleep 5
  echo "Running WebotsPlant hover (watch the 3D window)..."
  python3 -m bridge.webots_renode_bridge "${BRIDGE_ARGS[@]}"
fi
