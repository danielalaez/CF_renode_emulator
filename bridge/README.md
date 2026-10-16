# Webots ↔ Renode Crazyflie bridge

Host process that connects:

- **Webots** (or `FakePlant` dry-run) — physics / sensors / props  
- **Renode CF2.1** in Docker (`--net=host`) — `cf2.elf` via monitor `:9999`

See [../WEBOTS_BRIDGE.md](../WEBOTS_BRIDGE.md) for architecture.

## Prerequisites

```bash
# Terminal 1
cd renode_test
RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh
```

Phase 2a tools still work: `inject_imu_stream.sh`, `check_calib.sh`, `check_preflight.sh`.

## Phase 2b — motor observability

```bash
# While Renode runs (owns -P — exclusive with inject_imu_stream)
./scripts/monitor_motors.sh 9999 --once
./scripts/monitor_motors.sh 9999 --force 20000 20000 20000 20000 --hz 2
./scripts/monitor_motors.sh 9999 --clear
```

Monitor commands: `motor_stats`, `motor_force m1 m2 m3 m4`, `motor_force_clear`.

## Setpoint injection (Option C)

No Crazyradio / CRTP stack required. The bridge (or monitor) overwrites the
FreeRTOS `setpointQueue` storage and refreshes `timestamp` from `xTickCount`
so the supervisor commander WDT stays satisfied.

```bash
# After calib/preflight
./scripts/check_setpoint.sh 9999 35000
# Or via monitor: setpoint_hover 35000 | setpoint_rpyt 0 0 0 35000 | setpoint_stats
```

| Command | Role |
|---------|------|
| `setpoint_rpyt roll pitch yaw thrust` | Level RPYT blob into commander queue |
| `setpoint_hover [thrust]` | Zero attitude + thrust (default 35000) |
| `setpoint_stats` | Dump thrust / modes / tick age |
| `setpoint_clear` | Null setpoint + disable priority |

Refresh ≥ ~20 Hz (bridge `--loop-hz 50` does this).

## Bridge dry-run (no Webots)

```bash
# Terminal 2 — sensors only into Renode
python3 -m bridge.webots_renode_bridge --fake --mode sensors-only --wait-calib --seconds 60

# Open-loop motors into FakePlant + IMU feedback
python3 -m bridge.webots_renode_bridge --fake --mode motors-open-loop \
  --force-ratio 0.4 --wait-preflight --seconds 30

# Setpoint-driven motors (firmware mixer) + FakePlant
python3 -m bridge.webots_renode_bridge --fake --mode closed-loop \
  --wait-preflight --thrust 35000 --seconds 45
```

Expect `motor_stats` / status `m=(…)` to leave zero after setpoints land and
motors are allowed to run (armed / ReadyToFly).

## Webots plant (phase 2c / 2d)

1. Install Webots R2023b+ and open `webots/worlds/cf_hover.wbt`  
   (`CrazyflieSimple` PROTO, controller `<extern>`, supervisor on)  
2. Start Renode (terminal 1)  
3. From `renode_test/`:

```bash
# First lift: open-loop force into Webots props
python3 -m bridge.webots_renode_bridge --mode motors-open-loop \
  --force-ratio 0.55 --wait-preflight --seconds 30

# Closed-loop: FW setpoints -> motor_stats -> Webots forces -> IMU back
python3 -m bridge.webots_renode_bridge --mode closed-loop \
  --thrust 35000 --wait-preflight --imu-hz 200 --loop-hz 50
```

Optional in-tree controller: set world `controller "webots_renode_bridge"`
(see `webots/controllers/webots_renode_bridge/`).

Tune thrust scaling in `bridge/motor_map.py` (`ThrustMap.k`; hover ≈ ratio 0.5).

## Sync notes

- Renode IMU feeder runs on **virtual time** (`imu_stream_*`, `virt_hz`).  
- Bridge updates samples with `imu_stream_set` (no clock restart).  
- Wall `loop-hz` can be lower than guest IMU Hz; guest still gets `imu-hz` virt samples.  
- Setpoint path is **monitor poke** (Option C), not syslink CRTP — swap later for Option B.  
