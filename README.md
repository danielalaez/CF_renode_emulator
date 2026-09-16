# renode_test — Crazyflie STM32 firmware on Renode (Docker-first)

Run **real Crazyflie firmware** (`cf2.elf`) on Bitcraze’s Renode CF2.1 platform with **canned IMU/baro samples**. No Webots/Gazebo, no radio, no decks.

**Audience:** colleagues replicating the phase-1 smoke test on Linux with Docker.

## Prerequisites

| Need | Notes |
|------|--------|
| Linux host (or WSL2) | Verified on Ubuntu 22.04 / 24.04 |
| Docker | Engine or Desktop; user in `docker` group |
| Disk / time | ~20–40 GB free; first bootstrap ~30–60 min |
| Ports free | `3333` (GDB), `3456` (sensors), `9999` (optional monitor) |

You do **not** need Mono on the host if you always use `DOCKER=1`.

## Quick start (Docker)

```bash
git clone <THIS_REPO_URL> renode_test
cd renode_test
chmod +x scripts/*.sh

# One-time: firmware + Renode build + runner image
./scripts/bootstrap.sh
```

### Terminal 1 — start emulation

```bash
RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh
```

Wait until you see `Machine started.` and ongoing `timer7` / `rtc` / LED log lines.

### Terminal 2 — guest CPU stats (optional)

```bash
./scripts/monitor_cpu.sh 9999
```

Leave this running. Closing the monitor socket **stops Renode** (single telnet client).

Example:

```text
ins=115081833  rate=22092/s  util=0.0%  mips_cap=100  sim=0.626x  pc=0x802c6c2  virt=4.94s  host=17.49s
```

Low `util` + PC stuck at `0x802c6c2` is **normal** (FreeRTOS idle hook). Rising `ins` and `virt` mean the guest is executing.

### Stop

In the Renode monitor socket: `quit`  
Or: `docker ps` → stop the `renode-cf-runner` / ubuntu container.

## What this proves

| Check | Expected |
|-------|----------|
| CF2 platform loads | No “peripheral not found” for BMI088 / CF_Syslink |
| `cf2.elf` runs | `Machine started.`, LED / timer activity |
| GDB | `target remote localhost:3333` |
| Sensor feeds | `FeedGyroSample` / `FeedAccSample` / `FeedPTSample` accepted |
| `cpu_stats` | Instruction rate / util / sim speed via monitor |

It does **not** prove closed-loop flight, radio, or decks.

## Layout

```text
renode_test/
├── scripts/
│   ├── bootstrap.sh          # one-shot colleague setup
│   ├── build_firmware.sh     # → firmware/cf2.elf (Docker bitcraze/builder)
│   ├── setup_renode_cf.sh    # clone+build Bitcraze Renode (DOCKER=1 recommended)
│   ├── build_docker_runner.sh
│   ├── run_first_test.sh     # launch Renode
│   ├── monitor_cf.py         # IronPython: cpu_stats
│   ├── monitor_cpu.py / .sh  # host poller for cpu_stats
├── docker/Dockerfile.runner  # Ubuntu 22.04 + mono-complete
├── resc/crazyflie_canned.resc
├── sensors/README.md
├── firmware/                 # cf2.elf appears after build (gitignored)
└── build/                    # Renode + FW sources (gitignored, large)
```

## Manual steps (instead of bootstrap)

```bash
./scripts/build_firmware.sh
DOCKER=1 ./scripts/setup_renode_cf.sh
./scripts/build_docker_runner.sh
RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh
```

## Renode monitor commands

With `RENODE_MONITOR_PORT=9999`, commands go over TCP (`nc localhost 9999` or `monitor_cpu.sh`). Firmware **logs** still print in terminal 1.

| Command | Purpose |
|---------|---------|
| `pause` / `start` | Pause / resume emulation |
| `cpu_stats` | Guest instruction rate, util %, sim speed |
| `cpu_stats_reset` | Reset rate baseline |
| `sysbus.cpu PC` | Program counter |
| `currentTime` | Virtual + host time |
| `quit` | Exit Renode |

**Wrong:** `exit`, bare `cpu PC`, casual `nc` connect/disconnect (kills Renode).

### Extra sensor feeds

```text
pause
sysbus.i2c3.bmi_gyro FeedGyroSample 0 0 0 10
sysbus.i2c3.bmi_accel FeedAccSample 0 0 1000 10
sysbus.i2c3.bmp_baro FeedPTSample 101325 25 10
start
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Ports in use | `docker ps`; stop leftover Renode containers; `pkill -f renode` |
| Mono reinstall every run | Build runner once: `./scripts/build_docker_runner.sh` |
| `STM32_Basic_Timer` / BMI088 missing | Re-run `DOCKER=1 ./scripts/setup_renode_cf.sh` |
| `cpu_stats` unknown | Restart after bootstrap; `run_first_test.sh` patches `monitor.py` |
| Monitor kills Renode | Keep one persistent client (`monitor_cpu.sh`); do not short-lived `nc` probes |
| Firmware build fails | `FW_CLEAN=1 ./scripts/build_firmware.sh` |

## Expected log noise (not failures)

- `USB_OTG_FS` — USB not fully modeled  
- `PWR` / `FLASH_INTERFACE` / `ADC` — tag-only  
- `i2c1: No slave 0x41/0x42` — no decks  
- Partial `dma` / `rtc` / `timer7` warnings  

## Why Bitcraze Renode

Stock Antmicro Renode packages lack Crazyflie models (`BMI088_*`, `BMP388`, `CF_Syslink`). This project builds [bitcraze/renode](https://github.com/bitcraze/renode/tree/crazyflie) branch `crazyflie` with pinned Infrastructure / resources commits (see `setup_renode_cf.sh`).

## Non-goals

- Webots / Gazebo closed-loop flight  
- Full Crazyradio / nRF stack  
- Expansion decks  
- PX4 / QEMU swarm work  

## License / upstream

Scripts in this repo are for your team. Firmware and Renode come from Bitcraze / Antmicro under their respective licenses.
