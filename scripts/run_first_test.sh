#!/bin/bash
# Phase 1: run Crazyflie firmware in Bitcraze Renode with canned sensor feeds.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RENODE_DIR="${RENODE_DIR:-${ROOT}/build/renode-cf}"
ELF="${ELF:-${ROOT}/firmware/cf2.elf}"
AUTO_START="${AUTO_START:-1}"
USE_DOCKER="${DOCKER:-0}"
RENODE_MONITOR_PORT="${RENODE_MONITOR_PORT:-}"
RENODE_DOCKER_IMAGE="${RENODE_DOCKER_IMAGE:-renode-cf-runner:22.04}"

check_ports() {
  # Note: do NOT reserve 1234 — Webots <extern> controllers use that by default.
  local ports=(3333 3456)
  if [ -n "${RENODE_MONITOR_PORT}" ]; then
    ports+=("${RENODE_MONITOR_PORT}")
  fi
  local busy=()
  local p

  for p in "${ports[@]}"; do
    if ss -tln 2>/dev/null | awk '{print $4}' | grep -q ":${p}$"; then
      busy+=("${p}")
    fi
  done

  if [ "${#busy[@]}" -eq 0 ]; then
    return 0
  fi

  echo "Ports already in use: ${busy[*]}"
  echo "A previous Renode run is probably still active."
  echo "Try:"
  echo "  docker ps"
  echo "  docker stop <container-id>    # ubuntu:22.04 running ./renode"
  echo "  pkill -f 'renode.*crazyflie_canned'"
  return 1
}

prepare_renode_runtime() {
  local renode_lib="${RENODE_DIR}/output/bin/Release"
  local libdl_target="/lib/x86_64-linux-gnu/libdl.so.2"

  if [ ! -d "${renode_lib}" ]; then
    echo "ERROR: ${renode_lib} missing — run ./scripts/setup_renode_cf.sh"
    exit 1
  fi

  # Mono DllImport("dl") expects libdl.so; Ubuntu ships only libdl.so.2.
  if [ ! -e "${renode_lib}/libdl.so" ] && [ -f "${libdl_target}" ]; then
    ln -sf "${libdl_target}" "${renode_lib}/libdl.so"
  fi

  # ROS/Gazebo LD_LIBRARY_PATH can shadow system libs and break native CPU models.
  export LD_LIBRARY_PATH="${renode_lib}"
}

check_mono_deps() {
  if dpkg -s mono-complete >/dev/null 2>&1 && dpkg -s libzmq5 >/dev/null 2>&1; then
    return 0
  fi

  local missing=()
  dpkg -s mono-complete >/dev/null 2>&1 || missing+=(mono-complete)
  dpkg -s libzmq5 >/dev/null 2>&1 || missing+=(libzmq5)

  echo "Renode needs the full Mono runtime (System.Drawing, Mono.Posix, etc.), not just mono-runtime."
  echo "Missing packages: ${missing[*]}"
  echo "Install with:"
  echo "  sudo apt-get install -y mono-complete libzmq5"
  echo "Or run without installing Mono on the host:"
  echo "  DOCKER=1 ./scripts/run_first_test.sh"
  return 1
}

run_docker() {
  if ! docker image inspect "${RENODE_DOCKER_IMAGE}" >/dev/null 2>&1; then
    echo "Docker image ${RENODE_DOCKER_IMAGE} not found — building once (Mono install, ~2–5 min) ..."
    "${SCRIPT_DIR}/build_docker_runner.sh"
  fi

  local renode_cli=(./renode --disable-xwt)
  if [ -n "${RENODE_MONITOR_PORT}" ]; then
    # -P and --console are exclusive in Renode; socket monitor needs no --console.
    renode_cli+=(-P "${RENODE_MONITOR_PORT}")
  else
    renode_cli+=(--console)
  fi
  renode_cli+=(crazyflie_canned.resc)

  local container_name="${RENODE_DOCKER_NAME:-renode-cf}"
  # Detach when stdin is not a TTY (log redirect / CI / agent), or RENODE_DETACH=1.
  local detach=0
  if [ "${RENODE_DETACH:-0}" = "1" ] || [ ! -t 0 ]; then
    detach=1
  fi

  echo "Running Renode in Docker (${RENODE_DOCKER_IMAGE}, --net=host for GDB :3333) ..."
  if [ -n "${RENODE_MONITOR_PORT}" ]; then
    echo "  monitor:  nc localhost ${RENODE_MONITOR_PORT}   (or ./scripts/monitor_cpu.sh ${RENODE_MONITOR_PORT})"
  fi

  docker rm -f "${container_name}" >/dev/null 2>&1 || true

  local docker_flags=(--name "${container_name}" --net=host)
  if [ "${detach}" = "1" ]; then
    docker_flags+=(-d --rm)
    echo "  container: ${container_name} (detached; logs: docker logs -f ${container_name})"
  else
    docker_flags+=(-it --rm)
  fi

  docker run "${docker_flags[@]}" \
    -v "${RENODE_DIR}:/renode-cf:rw" \
    -w /renode-cf \
    "${RENODE_DOCKER_IMAGE}" \
    /bin/bash -c "set -euo pipefail
      ln -sf /lib/x86_64-linux-gnu/libdl.so.2 output/bin/Release/libdl.so 2>/dev/null || true
      export LD_LIBRARY_PATH=/renode-cf/output/bin/Release
      exec ${renode_cli[*]}
    "

  if [ "${detach}" = "1" ]; then
    # Follow logs until Machine started, then leave container running.
    local i
    for i in $(seq 1 60); do
      if docker logs "${container_name}" 2>&1 | grep -q "Machine started"; then
        echo "Renode ready (detached)."
        docker logs "${container_name}" 2>&1 | tail -20
        return 0
      fi
      if ! docker ps --filter "name=^${container_name}$" --format '{{.Names}}' | grep -q .; then
        echo "ERROR: Renode container exited early:" >&2
        docker logs "${container_name}" 2>&1 | tail -40 >&2
        return 1
      fi
      sleep 1
    done
    echo "WARNING: timed out waiting for Machine started; container may still be booting."
    docker logs "${container_name}" 2>&1 | tail -20
  fi
}

if [ ! -f "${ELF}" ]; then
  echo "Missing ${ELF}"
  echo "Run: ./scripts/build_firmware.sh"
  exit 1
fi

if [ ! -x "${RENODE_DIR}/renode" ] && [ ! -f "${RENODE_DIR}/renode" ]; then
  # built layouts vary: output/bin/Release/... or ./renode wrapper
  if [ -x "${ROOT}/bin/renode-cf" ]; then
    RENODE_BIN="${ROOT}/bin/renode-cf"
  else
    echo "Renode-CF not found at ${RENODE_DIR}/renode"
    echo "Run: ./scripts/setup_renode_cf.sh"
    exit 1
  fi
else
  RENODE_BIN="${RENODE_DIR}/renode"
fi

if [ ! -f "${RENODE_DIR}/platforms/boards/cf2.repl" ]; then
  echo "ERROR: ${RENODE_DIR}/platforms/boards/cf2.repl missing"
  echo "Need Bitcraze renode branch crazyflie (./scripts/setup_renode_cf.sh)"
  exit 1
fi

# Run from Renode root so @platforms/... resolves; put ELF where @cf2.elf finds it.
# Docker bind-mounts only build/renode-cf — a symlink to firmware/cf2.elf breaks inside the container.
patch_monitor_py() {
  local monitor_py="${RENODE_DIR}/scripts/monitor.py"
  local backup="${monitor_py}.swarm_orig"
  local marker="# --- swarm monitor_cf patch ---"

  if [ ! -f "${backup}" ]; then
    cp -f "${monitor_py}" "${backup}"
  fi

  cp -f "${backup}" "${monitor_py}"
  {
    echo ""
    echo "${marker}"
    cat "${ROOT}/scripts/monitor_cf.py"
  } >> "${monitor_py}"
}

cp -f "${ELF}" "${RENODE_DIR}/cf2.elf"
cp -f "${ROOT}/resc/crazyflie_canned.resc" "${RENODE_DIR}/crazyflie_canned.resc"
patch_monitor_py

# Ensure resc uses @cf2.elf (cwd = RENODE_DIR)
cat > "${RENODE_DIR}/crazyflie_canned.resc" << 'EOF'
:description: Crazyflie 2.1 + canned sensors (phase 1)

mach create "CF2.1"
machine LoadPlatformDescription @platforms/boards/cf2.repl

sysbus.otp WriteString 0x7800 "0;CF21"
# Avoid showAnalyzer -- it can block when Renode has no console/TTY (-P mode).
sysbus LoadELF @cf2.elf

emulation CreateUARTHub "syslink"
connector Connect sysbus.usart6 syslink
connector Connect sysbus.nrf syslink
syslink Start

machine StartGdbServer 3333
emulation CreateServerSocketTerminal 3456 "sensors"
connector Connect sysbus.i2c3.bmi_gyro sensors

sysbus.i2c3.bmi_gyro FeedGyroSample 10 20 30 2
sysbus.i2c3.bmi_gyro FeedGyroSample 0 0 0 20
sysbus.i2c3.bmi_accel FeedAccSample 0 0 1000 20
sysbus.i2c3.bmp_baro FeedPTSample 101325 25 20

echo "Phase 1 loaded. GDB :3333  sensor socket :3456"
echo "Monitor tips: pause | cpu_stats | imu_stream_start | quit"
echo "Feed more: sysbus.i2c3.bmi_gyro FeedGyroSample 0 0 0 10"
EOF

if [ "${AUTO_START}" = "1" ]; then
  # Quiet USB/unhandled WARNING spam AFTER start so "Machine started." still logs.
  {
    echo 'start'
    echo 'logLevel 3'
  } >> "${RENODE_DIR}/crazyflie_canned.resc"
fi

echo "=== Crazyflie Renode first test ==="
echo "  renode: ${RENODE_BIN}"
echo "  elf:    ${ELF}"
echo "  gdb:    target remote localhost:3333"
echo "  sensors socket: localhost:3456"
echo "  quit:   type quit in the Renode monitor to exit"
if [ -n "${RENODE_MONITOR_PORT}" ]; then
  echo "  monitor: nc localhost ${RENODE_MONITOR_PORT}"
  echo "  stats:   ./scripts/monitor_cpu.sh ${RENODE_MONITOR_PORT}"
  echo "  imu:     ./scripts/inject_imu_stream.sh ${RENODE_MONITOR_PORT}   # phase 2a (exclusive with stats)"
fi
echo
echo "Monitor (via -P socket / nc — not the Docker log TTY):"
echo "  pause | start | quit | cpu_stats | calib_status | preflight_status | motor_stats | imu_stream_*"
echo "  Wrong: exit, Ctrl+C, tui — use quit"
echo
echo "Phase 2 (wait for Renode log: Machine started):"
echo "  ./scripts/inject_imu_stream.sh ${RENODE_MONITOR_PORT:-9999}"
echo "  calib:     ./scripts/check_calib.sh ${RENODE_MONITOR_PORT:-9999}"
echo "  preflight: ./scripts/check_preflight.sh ${RENODE_MONITOR_PORT:-9999}"
echo "  motors:    ./scripts/monitor_motors.sh ${RENODE_MONITOR_PORT:-9999} --force 20000 20000 20000 20000"
echo "  setpoint:  ./scripts/check_setpoint.sh ${RENODE_MONITOR_PORT:-9999} 35000"
echo "  bridge:    python3 -m bridge.webots_renode_bridge --fake --mode closed-loop --wait-preflight --thrust 35000"
echo



cd "${RENODE_DIR}"
check_ports
prepare_renode_runtime

RENODE_ARGS=(--disable-xwt)
if [ -n "${RENODE_MONITOR_PORT}" ]; then
  RENODE_ARGS+=(-P "${RENODE_MONITOR_PORT}")
else
  RENODE_ARGS+=(--console)
fi

if [ "${USE_DOCKER}" = "1" ]; then
  run_docker
elif check_mono_deps; then
  exec "${RENODE_BIN}" "${RENODE_ARGS[@]}" crazyflie_canned.resc
elif command -v docker >/dev/null 2>&1; then
  echo "Falling back to DOCKER=1 ..."
  run_docker
else
  exit 1
fi
