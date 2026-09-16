#!/bin/bash
# Build Crazyflie STM32 firmware (cf2.elf) with Bitcraze Docker builder.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FW_SRC="${FW_SRC:-${ROOT}/build/crazyflie-firmware}"
FW_OUT="${ROOT}/firmware"
FW_REF="${FW_REF:-master}"

mkdir -p "${ROOT}/build" "${FW_OUT}"

if [ "${FW_CLEAN:-0}" = "1" ] && [ -d "${FW_SRC}" ]; then
  echo "FW_CLEAN=1: removing ${FW_SRC}"
  rm -rf "${FW_SRC}"
fi

if [ ! -d "${FW_SRC}/.git" ]; then
  echo "Cloning crazyflie-firmware (${FW_REF}) → ${FW_SRC}"
  git clone --recursive --branch "${FW_REF}" \
    https://github.com/bitcraze/crazyflie-firmware.git "${FW_SRC}"
fi

echo "Ensuring git submodules are populated ..."
git -C "${FW_SRC}" submodule sync --recursive
git -C "${FW_SRC}" submodule update --init --recursive

FREERTOS_H="${FW_SRC}/vendor/FreeRTOS/include/FreeRTOS.h"
CMSIS_CORE="${FW_SRC}/vendor/CMSIS/CMSIS/Core/Include/core_cm4.h"
if [ ! -f "${FREERTOS_H}" ] || [ ! -f "${CMSIS_CORE}" ]; then
  echo "ERROR: vendor submodules incomplete (missing FreeRTOS/CMSIS headers)."
  echo "  FreeRTOS: ${FREERTOS_H}"
  echo "  CMSIS:    ${CMSIS_CORE}"
  echo "Try: FW_CLEAN=1 ./scripts/build_firmware.sh"
  exit 1
fi

echo "Building cf2 firmware via bitcraze/builder ..."
docker run --rm \
  -v "${FW_SRC}:/module" \
  bitcraze/builder \
  /bin/bash -c "make cf2_defconfig && make -j\$(nproc)"

ELF="${FW_SRC}/build/cf2.elf"
if [ ! -f "${ELF}" ]; then
  # older layouts
  ELF="$(find "${FW_SRC}" -name 'cf2.elf' | head -n1 || true)"
fi
if [ -z "${ELF}" ] || [ ! -f "${ELF}" ]; then
  echo "ERROR: cf2.elf not found after build"
  exit 1
fi

cp -f "${ELF}" "${FW_OUT}/cf2.elf"
# also hex/bin if present
cp -f "${FW_SRC}/build/cf2.hex" "${FW_OUT}/cf2.hex" 2>/dev/null || true
cp -f "${FW_SRC}/build/cf2.bin" "${FW_OUT}/cf2.bin" 2>/dev/null || true

echo
echo "Firmware ready: ${FW_OUT}/cf2.elf"
file "${FW_OUT}/cf2.elf"
