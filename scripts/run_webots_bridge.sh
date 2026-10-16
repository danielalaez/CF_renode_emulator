#!/usr/bin/env bash
# Launch Webots (3D) + Renode bridge as <extern> controller.
#
# Prerequisites:
#   Terminal A: RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh
#   Wait for "Machine started."
#
# Usage (from renode_test/):
#   ./scripts/run_webots_bridge.sh                  # closed-loop default
#   ./scripts/run_webots_bridge.sh --mode motors-open-loop --force-ratio 0.55
#   WEBOTS_ONLY=1 ./scripts/run_webots_bridge.sh    # open GUI only; bridge later
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORLD="${WORLD:-$ROOT/webots/worlds/cf_hover.wbt}"
MODE_ARGS=("${@:-}")
if [[ ${#MODE_ARGS[@]} -eq 0 || "${MODE_ARGS[0]:-}" == "" ]]; then
  # Conservative defaults — high loop-hz + Webots realtime can freeze a laptop.
  MODE_ARGS=(--mode motors-open-loop --force-ratio 0.55 --wait-preflight --imu-hz 100 --loop-hz 20 --seconds 60)
fi

find_webots() {
  if [[ -n "${WEBOTS_HOME:-}" && -x "${WEBOTS_HOME}/webots" ]]; then
    echo "${WEBOTS_HOME}/webots"
    return
  fi
  if command -v webots >/dev/null 2>&1; then
    command -v webots
    return
  fi
  for c in \
    "$HOME/.local/webots-R2025a/webots" \
    "$HOME/.local/webots/webots" \
    /usr/local/webots/webots \
    /usr/local/bin/webots; do
    [[ -x "$c" ]] && { echo "$c"; return; }
  done
  return 1
}

WEBOTS_BIN="$(find_webots)" || {
  echo "Webots not found. Install R2025a (Ubuntu 24.04):" >&2
  echo "  curl -L -o /tmp/webots_2025a_amd64.deb \\" >&2
  echo "    https://github.com/cyberbotics/webots/releases/download/R2025a/webots_2025a_amd64.deb" >&2
  echo "  sudo apt install -y /tmp/webots_2025a_amd64.deb" >&2
  exit 1
}

# Python controller lib for <extern>
if [[ -z "${WEBOTS_HOME:-}" ]]; then
  for d in \
    "$HOME/.local/webots-R2025a" \
    "$HOME/.local/webots" \
    /usr/local/webots \
    /usr/share/webots; do
    if [[ -d "$d" && -x "$d/webots" ]]; then
      export WEBOTS_HOME="$d"
      break
    fi
  done
fi
if [[ -n "${WEBOTS_HOME:-}" ]]; then
  # Prefer versioned python controller package if present
  PYCTRL="${WEBOTS_HOME}/lib/controller/python"
  export PYTHONPATH="${PYCTRL}${PYTHONPATH:+:$PYTHONPATH}"
  export LD_LIBRARY_PATH="${WEBOTS_HOME}/lib/controller:${WEBOTS_HOME}/lib/webots${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

PORT="${RENODE_MONITOR_PORT:-9999}"
if ! (echo >/dev/tcp/127.0.0.1/"$PORT") 2>/dev/null; then
  echo "WARNING: nothing listening on :${PORT}. Start Renode first:" >&2
  echo "  RENODE_MONITOR_PORT=${PORT} DOCKER=1 ${ROOT}/scripts/run_first_test.sh" >&2
fi

echo "Webots:  $WEBOTS_BIN"
echo "World:   $WORLD"
echo "WEBOTS_HOME=${WEBOTS_HOME:-unset}"
echo "Bridge:  python3 -m bridge.webots_renode_bridge ${MODE_ARGS[*]}"

# Start Webots GUI. Prefer --mode=run (not realtime) to avoid pegging the CPU.
# Override with WEBOTS_MODE=realtime if you need wall-clock sync.
WEBOTS_MODE="${WEBOTS_MODE:-run}"
echo "Webots mode: $WEBOTS_MODE (set WEBOTS_MODE=realtime only if needed)"
"$WEBOTS_BIN" --mode="$WEBOTS_MODE" --stdout --stderr "$WORLD" &
WEBOTS_PID=$!

# Give Webots time to load the world and accept the extern controller
sleep 5

if [[ "${WEBOTS_ONLY:-0}" == "1" ]]; then
  echo "WEBOTS_ONLY=1 — Webots running (pid $WEBOTS_PID). Start bridge manually:"
  echo "  cd $ROOT && WEBOTS_HOME=$WEBOTS_HOME python3 -m bridge.webots_renode_bridge ${MODE_ARGS[*]}"
  wait "$WEBOTS_PID"
  exit 0
fi

cd "$ROOT"
echo "Bridge connecting (Webots pid=$WEBOTS_PID stays open on exit)..."
set +e
python3 -m bridge.webots_renode_bridge "${MODE_ARGS[@]}"
rc=$?
set -e
echo "Bridge exited rc=$rc — Webots still running (pid $WEBOTS_PID). Close the GUI when done."
exit "$rc"
