# Orchestration, probes, and Renode performance

Notes for automating process bring-up and inspecting the data path between
**Renode / Crazyflie firmware**, the **host bridge**, and **Webots**.

---

## 1. Process topology

```text
┌─────────────────┐   monitor :9999    ┌──────────────────────┐
│ run_first_test  │◄──────────────────►│ webots_renode_bridge │
│ (Docker Renode) │                    │ (host Python)        │
│  cf2.elf        │                    └──────────┬───────────┘
│  virt-time IMU  │                               │ <extern>
└─────────────────┘                               ▼
                                         ┌─────────────────┐
                                         │ Webots cf_hover │
                                         │ Crazyflie PROTO │
                                         └─────────────────┘
```

| Process | How to start | Owns |
|---------|--------------|------|
| Renode | `RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh` | Guest FW, virt-time, `:9999`, `:3456`, `:3333` |
| Webots | `run_hover_demo.sh` or `webots --mode=realtime …/cf_hover.wbt` | Physics, props, sensors |
| Bridge | same demo script / `python3 -m bridge.webots_renode_bridge …` | Monitor client, motor apply, IMU set, setpoints |

Suggested orchestration order:

1. Free ports `9999` / `3456` / `3333` (and Webots `1234` if needed).
2. Start Renode; wait for log line `Machine started.` **and** TCP accept on `:9999`.
3. Start Webots (skip if `FAKE=1`).
4. Start bridge with `--wait-preflight`.
5. On exit: bridge clears setpoints; stop Webots; `docker stop` Renode.

Ready-made: `./scripts/run_hover_demo.sh` already does (2)+(3)+(4).

---

## 2. Hard constraint: one monitor client

Renode `-P 9999` allows **one** telnet client. Whoever connects owns all
`cpu_stats` / `motor_stats` / `imu_stream_*` / `setpoint_*` traffic.

| During | Who should own `:9999` |
|--------|-------------------------|
| Flight / closed-loop | **Bridge only** |
| Renode-only CPU profiling | `./scripts/monitor_cpu.sh 9999` |
| Motor force experiments | `./scripts/monitor_motors.sh` (not with bridge) |

**Do not** attach a second `nc`/`monitor_cpu` while the bridge flies — it will
steal or kill the session.

For concurrent inspection, use the bridge **telemetry JSONL** tap (below) or
extend the bridge to multiplex stats into that stream.

---

## 3. Data-flow probe points

### 3.1 Signals on the wire (logical)

```text
Host setpoint_rpyt(roll,pitch,yaw,thrust)
        │
        ▼  monitor
Renode commander queue ──► FW attitude + mixer
        │
        ▼  motor_stats
motor_ratios[4] ──bridge──► Webots Motor.setVelocity (signed ω)
        │
        ▼  physics
pose / ω_body / alt
        │
        ▼  bridge read_sensors
gyro, accel, pressure ──► imu_stream_set ──► BMI088 / BMP388 models
GPS alt ──► host altitude PD ──► thrust (next setpoint)
```

| Tap | Source today | Fields |
|-----|--------------|--------|
| A. Setpoint out | Bridge → `setpoint_rpyt` / `setpoint_stats` | roll, pitch, yaw_rate, thrust, mode.z |
| B. Motors FW→plant | `motor_stats` / bridge `last_motors` | m1..m4 ratios 0..1 |
| C. Props commanded | `WebotsPlant.motor_velocities()` | ω rad/s (signed) |
| D. Plant state | `SensorSample` / GPS | alt, vz (derived), ax/ay/az, gx/gy/gz, P |
| E. IMU into FW | `imu_stream_set` / `imu_stream_status` | sample + virt_hz / out_hz |
| F. Renode perf | `cpu_stats` | rate, util%, **sim_speed**, virt, host |

### 3.2 Bridge JSONL telemetry (recommended for automation)

```bash
python3 -m bridge.webots_renode_bridge --mode closed-loop --alt-hold \
  --wait-preflight --telemetry /tmp/cf_bridge.jsonl --seconds 45
```

Each control cycle appends one JSON object (see `bridge/telemetry.py`), e.g.:

```json
{
  "t_wall": 1710000000.12,
  "sim": 3.84,
  "alt": 0.55,
  "vz": 0.01,
  "thrust": 29880,
  "u": -0.08,
  "motors": [0.55, 0.55, 0.55, 0.55],
  "omega": [-55, 55, -55, 55],
  "gyro": [0.0, 0.0, 0.0],
  "accel": [0, 0, 1000],
  "pressure": 101318.2
}
```

Orchestrators can `tail -f` this file or parse it post-run without touching `:9999`.

### 3.3 Renode performance (`cpu_stats`)

When the bridge is **not** connected:

```bash
./scripts/monitor_cpu.sh 9999
# ins  rate/s  util%  mips_cap  sim_speed  pc  virt_s  host_s
```

| Field | Meaning |
|-------|---------|
| `sim_speed` | Guest virt-time / wall (`1.0` = realtime) |
| `rate` | Instructions / wall second |
| `util` | vs configured MIPS cap |
| `virt` / `host` | Accumulated times |

During flight, either:

- Sample `cpu_stats` **inside** the bridge on a slow timer and write into JSONL, or
- Stop the bridge briefly (not ideal), or
- Add a second Renode monitor port later (upstream limitation today).

`run_hover_demo` / bridge status lines already print `sim=` (Webots time) and
motor/IMU fields for a quick live check.

---

## 4. Timing model (not hard lockstep)

- Renode guest advances on **virtual time**; IMU feeder uses `ClockSource` (`virt_hz`).
- Webots runs `--mode=realtime`.
- Bridge wall loop ≈ 12 Hz (`--loop-hz`); after each Renode RTT it **catch-up**
  steps Webots so `sim_time ≈ wall_elapsed` (burst capped at +0.25 s).

There is **no** shared discrete timestep between Renode and Webots. Probes should
log both `t_wall` and Webots `sim` (and optionally Renode `virt` from `cpu_stats`).

---

## 5. Extension hooks (code)

| Goal | Where to hook |
|------|----------------|
| Extra logged fields | `bridge/telemetry.py` + emit site in `webots_renode_bridge.py` |
| Alternate plant | Implement same API as `WebotsPlant` / `FakePlant` (`read_sensors`, `apply_motors`, `step`) |
| Alternate commander | Replace `_inject_closed_loop` / `_host_alt_thrust` |
| Monitor commands | Append to `scripts/monitor_cf.py` (re-patched into Renode `monitor.py` at each `run_first_test` / `run_hover_demo`) |
| Orchestration wrapper | Call `run_hover_demo.sh` or compose Docker + Webots + bridge yourself |

`RenodeBridge` (`bridge/renode_io.py`) is the stable Python API for monitor I/O:

- `set_imu_sample`, `read_motors`, `inject_setpoint_rpyt`, `inject_setpoint_zdist`
- `calib_ok`, `preflight_ok`, `setpoint_stats`

---

## 6. Environment variables (`run_hover_demo.sh`)

| Variable | Default | Role |
|----------|---------|------|
| `FAKE` | `0` | `1` = FakePlant, no Webots |
| `ALT` | `0.5` | Altitude target (m) |
| `ALT_HOLD` | `1` | Host thrust PD |
| `FW_ZDIST` | `0` | Experimental FW Absolute-Z |
| `SECONDS_RUN` | `45` | Bridge duration |
| `HOVER_THRUST` | `30000` | Thrust bias for alt-hold |
| `ROLL` / `PITCH` / `YAW_RATE` | `0` | Attitude setpoints |
| `RENODE_MONITOR_PORT` | `9999` | Monitor TCP port |
| `WEBOTS_HOME` | `~/.local/webots-R2025a` | Webots install |
| `TELEMETRY` | (unset) | Path for bridge JSONL probe file |

---

## 7. Checklist for a probed demo run

- [ ] Renode up, `Machine started.`, `:9999` listening  
- [ ] Bridge started with `--telemetry /tmp/cf_bridge.jsonl`  
- [ ] Status shows `calib` / `preflight` then `alt` approaching target  
- [ ] JSONL grows; `motors` become non-zero; `omega` opposite signs on diagonals  
- [ ] Optional offline: parse JSONL for alt RMSE, motor spread, gyro noise  
- [ ] Separate session: Renode-only `monitor_cpu.sh` for baseline `sim_speed`  
