#!/bin/bash
# Clone Bitcraze Renode (crazyflie branch) and build — required for CF sensor models.
#
# Modes:
#   NATIVE=1  (default if mono present) ./build.sh
#   DOCKER=1  build inside Ubuntu 22.04 with mono + git
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RENODE_DIR="${RENODE_DIR:-${ROOT}/build/renode-cf}"
RENODE_REPO="${RENODE_REPO:-https://github.com/bitcraze/renode.git}"
RENODE_BRANCH="${RENODE_BRANCH:-crazyflie}"
USE_DOCKER="${DOCKER:-0}"
# Bitcraze fork (2021) still references Lucene.Net.dll; upstream removed it later.
RENODE_RESOURCES_REF="${RENODE_RESOURCES_REF:-7b7d316924cb20ec887472252b373f31066e0c6d}"
RENODE_RESOURCES_URL="${RENODE_RESOURCES_URL:-https://github.com/renode/renode-resources.git}"
# Parent repo pins Infrastructure @ master; CF models live on this branch.
RENODE_INFRA_BRANCH="${RENODE_INFRA_BRANCH:-crazyflie}"
RENODE_INFRA_REF="${RENODE_INFRA_REF:-c9c51b2d80d92507f07018d7559a9621892c8ff3}"

mkdir -p "${ROOT}/build"

ensure_infrastructure_crazyflie() {
  local infra="${RENODE_DIR}/src/Infrastructure"
  local marker="${infra}/src/Emulator/Peripherals/Peripherals/Sensors/BMI088_Gyroscope.cs"

  if [ -f "${marker}" ]; then
    return 0
  fi

  echo "Checking out renode-infrastructure (${RENODE_INFRA_BRANCH}) for CF sensor/timer models ..."
  git -C "${infra}" fetch origin "${RENODE_INFRA_BRANCH}" --depth=1
  git -C "${infra}" checkout -f "${RENODE_INFRA_REF}"

  if [ ! -f "${marker}" ]; then
    echo "ERROR: CF Infrastructure models missing at ${marker}"
    exit 1
  fi
}

ensure_renode_resources() {
  local res="${RENODE_DIR}/lib/resources"
  local lucene="${res}/libraries/Lucene.Net.dll"

  if [ -f "${lucene}" ]; then
    return 0
  fi

  echo "Fetching renode-resources @ ${RENODE_RESOURCES_REF} (Lucene.Net.dll required by Bitcraze fork) ..."
  rm -f "${RENODE_DIR}/.renode_libs_fetched"

  if [ -d "${res}/.git" ]; then
    git -C "${res}" fetch origin "${RENODE_RESOURCES_REF}" --depth=1
    git -C "${res}" checkout -f "${RENODE_RESOURCES_REF}"
  else
    rm -rf "${res}"
    git clone "${RENODE_RESOURCES_URL}" "${res}"
    git -C "${res}" fetch origin "${RENODE_RESOURCES_REF}" --depth=1
    git -C "${res}" checkout -f "${RENODE_RESOURCES_REF}"
  fi

  touch "${RENODE_DIR}/.renode_libs_fetched"
  if [ ! -f "${lucene}" ]; then
    echo "ERROR: ${lucene} missing after resources checkout"
    exit 1
  fi
}

if [ ! -d "${RENODE_DIR}/.git" ]; then
  echo "Cloning ${RENODE_REPO} (${RENODE_BRANCH}) → ${RENODE_DIR}"
  echo "(recursive submodules — this takes a while)"
  git clone --recursive --branch "${RENODE_BRANCH}" "${RENODE_REPO}" "${RENODE_DIR}"
else
  echo "Using existing ${RENODE_DIR}"
  echo "Ensuring git submodules are populated ..."
  git -C "${RENODE_DIR}" submodule sync --recursive
  git -C "${RENODE_DIR}" submodule update --init --recursive
fi

ensure_infrastructure_crazyflie

build_native() {
  ensure_infrastructure_crazyflie
  ensure_renode_resources
  cd "${RENODE_DIR}"
  if [ ! -x ./build.sh ]; then
    echo "ERROR: ${RENODE_DIR}/build.sh missing"
    exit 1
  fi
  echo "Building Renode (native). Requires Mono — see Renode docs."
  ./build.sh --no-gui
  echo "Build done. Runner: ${RENODE_DIR}/renode"
}

build_docker() {
  local host_uid host_gid
  host_uid="$(id -u)"
  host_gid="$(id -g)"

  echo "Building Bitcraze Renode inside Ubuntu 22.04 (mono + git) — can take 10–20 min ..."
  docker run --rm \
    -v "${RENODE_DIR}:/renode-cf:rw" \
    -w /renode-cf \
    ubuntu:22.04 \
    /bin/bash -c "set -euo pipefail
      export DEBIAN_FRONTEND=noninteractive
      export RENODE_RESOURCES_REF=${RENODE_RESOURCES_REF}
      export RENODE_INFRA_BRANCH=${RENODE_INFRA_BRANCH}
      export RENODE_INFRA_REF=${RENODE_INFRA_REF}
      apt-get update -qq
      apt-get install -y --no-install-recommends \
        git mono-complete python3 ca-certificates gcc libc6-dev
      git config --global --add safe.directory '*'
      git submodule sync --recursive
      git submodule update --init --recursive
      git -C src/Infrastructure fetch origin ${RENODE_INFRA_BRANCH} --depth=1
      git -C src/Infrastructure checkout -f ${RENODE_INFRA_REF}
      if [ ! -f lib/resources/libraries/Lucene.Net.dll ]; then
        rm -f .renode_libs_fetched
        git -C lib/resources fetch origin ${RENODE_RESOURCES_REF} --depth=1
        git -C lib/resources checkout -f ${RENODE_RESOURCES_REF}
        touch .renode_libs_fetched
      fi
      ./build.sh --no-gui
      chown -R ${host_uid}:${host_gid} /renode-cf
    "
}

if [ "${USE_DOCKER}" = "1" ]; then
  build_docker
else
  if command -v mono >/dev/null 2>&1 || command -v dotnet >/dev/null 2>&1; then
    build_native
  elif command -v docker >/dev/null 2>&1; then
    echo "Mono/dotnet not found; falling back to DOCKER=1"
    USE_DOCKER=1 build_docker
  else
    echo "ERROR: need Mono/dotnet to build Renode, or Docker."
    echo "  sudo apt-get install -y mono-complete"
    echo "  # or: DOCKER=1 ./scripts/setup_renode_cf.sh"
    exit 1
  fi
fi

RENODE_BIN="${RENODE_DIR}/output/bin/Release/Renode.exe"
if [ ! -f "${RENODE_BIN}" ]; then
  echo "ERROR: Renode build output missing at ${RENODE_BIN}"
  echo "Check build logs above; try DOCKER=1 ./scripts/setup_renode_cf.sh"
  exit 1
fi

# Convenience wrapper
mkdir -p "${ROOT}/bin"
cat > "${ROOT}/bin/renode-cf" << EOF
#!/bin/bash
exec "${RENODE_DIR}/renode" "\$@"
EOF
chmod +x "${ROOT}/bin/renode-cf"

echo
echo "Renode-CF ready:"
echo "  ${RENODE_DIR}/renode"
echo "  wrapper: ${ROOT}/bin/renode-cf"
echo
echo "Verify CF platform exists:"
ls -la "${RENODE_DIR}/platforms/boards/cf2.repl"
