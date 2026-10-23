# Crazyflie on Renode ↔ Webots (closed-loop hover)

Run **real Crazyflie firmware** (`cf2.elf`) in Bitcraze Renode (Docker) against a
**Webots** Crazyflie plant on the host. A Python bridge closes the loop:

| Direction | Data |
|-----------|------|
| Renode → Webots | Per-motor ratios → propeller ω (Bitcraze spin signs) |
| Webots → Renode | Gyro / accel / baro samples (+ DRDY via IMU stream) |
| Host → Renode | RPYT setpoint (thrust stick for altitude; R/P/Y = 0 by default) |

Firmware **attitude** stabilization uses the IMU. The host only trims **thrust**
like a radio stick to hold height (~0.5 m). See [PURE_FW_LOOP.md](PURE_FW_LOOP.md).

**Orchestration:** To bring up the demo and/or wiring orchestration /
probes (see [ORCHESTRATION.md](ORCHESTRATION.md)).

---

## Prerequisites

| Need | Notes |
|------|--------|
| Linux host | Verified Ubuntu 22.04 / 24.04 |
| Docker | User in `docker` group; image `renode-cf-runner:22.04` |
| Webots R2025a | Optional for FakePlant-only; required for 3D plant |
| Ports free | `3333` GDB, `3456` sensors, `9999` monitor |
| Disk | ~20–40 GB for first bootstrap (`build/` is gitignored) |

---

## Quick start — closed-loop hover

```bash
cd renode_test
chmod +x scripts/*.sh

# One-time (firmware + Renode + Docker runner)
./scripts/bootstrap.sh
```

**One command** (starts Renode if needed, then Webots + bridge):

```bash
FAKE=0 ALT=0.5 SECONDS_RUN=45 ./scripts/run_hover_demo.sh
```

Expect the craft to lift and settle near `ALT` (≈0.5–0.6 m). Bridge status lines
show `alt=…`, equal `m=(…)` when level, and `g≈0`.

**FakePlant** (no Webots GUI — good for CI / headless):

```bash
FAKE=1 ALT=0.5 SECONDS_RUN=50 ./scripts/run_hover_demo.sh
```

**Manual two-terminal** flow:

```bash
# Terminal 1 — Renode
RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh
# wait for: Machine started.

# Terminal 2 — bridge (Webots must be available, or use --fake)
FAKE=0 ALT=0.5 ./scripts/run_hover_demo.sh
# or:
python3 -m bridge.webots_renode_bridge --mode closed-loop --alt-hold \
  --alt-target 0.5 --wait-preflight --imu-hz 80 --loop-hz 12 --seconds 45
```

---

## What works / what does not

| Capability | Status |
|------------|--------|
| Per-motor FW → Webots props | Done |
| IMU/baro from plant → FW | Done |
| FW attitude hold (gyro) | Done |
| Host thrust stick → altitude | Done (~0.5 m hover) |
| Soft wall-clock sync (not hard lockstep) | Done |
| FW Absolute-Z (`--fw-zdist`) | Experimental (baro fusion limited in this ELF) |
| Full CRTP / Crazyradio | Out of scope (monitor setpoint poke) |

---

## Documentation map

| Doc | Purpose |
|-----|---------|
| [PURE_FW_LOOP.md](PURE_FW_LOOP.md) | Closed-loop architecture & smoke results |
| [ORCHESTRATION.md](ORCHESTRATION.md) | Ports, processes, **probe points**, `cpu_stats`, extension hooks |
| [WEBOTS_BRIDGE.md](WEBOTS_BRIDGE.md) | Detailed bridge design & bring-up phases |
| [FLIGHT_MIN.md](FLIGHT_MIN.md) | Minimum sensors/actuators for CF on Renode |
| [bridge/README.md](bridge/README.md) | Bridge CLI & package layout |
| [webots/README.md](webots/README.md) | World / PROTO notes |

---

## Layout

```text
renode_test/
├── bridge/                 # Host bridge (Webots ↔ Renode)
│   ├── webots_renode_bridge.py
│   ├── webots_io.py / renode_io.py / frames.py / setpoint.py
│   └── telemetry.py        # optional JSONL probe stream
├── scripts/
│   ├── bootstrap.sh / run_first_test.sh / run_hover_demo.sh
│   ├── monitor_cf.py       # IronPython: imu/motors/setpoint/cpu_stats
│   ├── monitor_cpu.sh      # host poller for Renode performance
│   └── monitor_motors.sh
├── webots/worlds/cf_hover.wbt
├── firmware/               # cf2.elf after build (gitignored binaries)
└── build/                  # Renode + FW trees (gitignored, large)
```

---

## Phase 1 — Renode-only smoke (no Webots)

```bash
RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh
./scripts/monitor_cpu.sh 9999          # keep open — exclusive -P client
```

See older phase-1 detail below and in [FLIGHT_MIN.md](FLIGHT_MIN.md).

### Renode monitor commands (summary)

| Command | Purpose |
|---------|---------|
| `cpu_stats` | Guest rate / util / **sim_speed** / virt vs host time |
| `imu_stream_start` / `set` / `status` | Virtual-time IMU+baro feeder |
| `motor_stats` / `motor_force` | Read / override motor ratios |
| `setpoint_rpyt` / `setpoint_zdist` / `setpoint_stats` | Commander setpoints |
| `calib_status` / `preflight_status` | Arming gates |

**Important:** monitor port `-P` is a **single client**. The bridge owns it during
flight. Do not also run `monitor_cpu.sh` or short-lived `nc` at the same time.
For concurrent probes, use bridge `--telemetry` JSONL (see ORCHESTRATION.md).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Ports in use | `docker ps`; stop leftover Renode; `pkill -f renode` |
| Craft stuck on floor | Bridge auto-unsticks; or restart Webots world |
| `cpu_stats` unknown | Restart Renode so `monitor_cf.py` is patched into `monitor.py` |
| Monitor kills Renode | One persistent client only |
| Webots missing | Install R2025a or use `FAKE=1` |

## License / upstream

Scripts here are for your team. Firmware and Renode come from Bitcraze / Antmicro
under their licenses. Runner builds [bitcraze/renode](https://github.com/bitcraze/renode/tree/crazyflie) `crazyflie` branch.
