# Renode ↔ Webots closed loop (design reference)

> **Status (2026-10):** Level closed-loop hover works. Prefer
> [README.md](README.md) + [PURE_FW_LOOP.md](PURE_FW_LOOP.md) for the as-built
> demo, and [ORCHESTRATION.md](ORCHESTRATION.md) for probes / automation.
> This file remains the detailed design and bring-up history.

Goal: make Crazyflie firmware running in **Renode (Docker)** believe it is flying a quadrotor whose plant lives in **Webots on the host** (or another container). Sensors in Webots drive Renode IMU/baro; motor commands from Renode drive Webots props.

Prerequisites: phase 1 smoke test works (`bootstrap.sh` + `DOCKER=1 run_first_test`). Minimum I/O contract: [FLIGHT_MIN.md](FLIGHT_MIN.md).

---

## 1. Target architecture

```text
┌──────────────────────────────┐         ┌──────────────────────────────────┐
│ Webots (host)                │         │ Renode CF2.1 (Docker, --net=host)│
│  quadrotor PROTO + physics   │         │  cf2.elf on STM32F405            │
│                              │         │                                  │
│  sensors:                    │  IMU/   │  BMI088 gyro/accel  (I2C3)       │
│    IMU, baro (from pose)     │─baro──►│  BMP388              (I2C3)       │
│                              │  +DRDY  │  EXTI14 data-ready               │
│                              │         │                                  │
│  actuators:                  │◄─PWM───│  TIM2 / TIM4 motor channels       │
│    4 propellers              │         │                                  │
│                              │         │  CF_Syslink / USART6             │
│  (optional) setpoint UI      │─CRTP──►│  commander setpoints              │
└──────────────────────────────┘  TCP    └──────────────────────────────────┘
         ▲                                        ▲
         │              bridge process            │
         └──────────── (Python on host) ──────────┘
```

**Bridge process** (recommended on host, not inside Renode image):

- Reads Webots supervisor / robot devices  
- Writes Renode via monitor socket (`-P`) and/or sensor TCP **:3456**  
- Reads motor outputs via monitor queries or a small Renode hook  
- Optionally injects CRTP/setpoints  

Keep Renode container focused on firmware; keep Webots + bridge on the host (simpler graphics, one Webots install).

---

## 2. Data flows (minimum)

| Direction | Signal | Rate | Mechanism (proposed) |
|-----------|--------|------|----------------------|
| Webots → Renode | Gyro ω | ~1 kHz* | `FeedGyroSample` + DRDY via `:3456` or `TriggerDataInterrupt` |
| Webots → Renode | Accel a | ~1 kHz* | `FeedAccSample` + same DRDY cadence |
| Webots → Renode | Baro P,T | ~50–100 Hz | `FeedPTSample` |
| Renode → Webots | Motor ratios m1..m4 | ~100–500 Hz | Poll `timer2`/`timer4` CCR or custom `motor_stats` monitor cmd |
| Host → Renode | Hover / RC setpoints | ≥20 Hz | Fake CRTP over syslink **or** monitor/Python poke **or** firmware hover patch |

\*Firmware wants ~1 kHz IMU. If host/Webots cannot sustain 1 kHz, start at 100–250 Hz for bring-up, then raise; document timing skew (`sim_speed` from `cpu_stats`).

Coordinate frames: convert Webots NED/ENU ↔ Crazyflie body frame explicitly in the bridge (one place, unit tests).

---

## 3. Renode / container side

### 3.1 Launch profile (Docker)

Reuse phase 1 runner with host networking so Webots bridge can reach ports:

```bash
RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh
```

| Port | Use |
|------|-----|
| **9999** | Monitor: `Feed*Sample`, motor readback, `cpu_stats` |
| **3456** | Sensor socket (gyro `WriteChar` → DRDY) — keep connected for IRQs |
| **3333** | GDB (debug only) |

`--net=host` (already used) is required so the host bridge hits these ports.

### 3.2 Changes inside / next to Renode scripts

| Work item | Purpose |
|-----------|---------|
| Continuous feed path | Replace finite canned `Feed* … 20` with bridge-driven samples |
| DRDY pulsing | After each IMU sample batch, trigger gyro interrupt (socket byte or monitor method) |
| `motor_stats` (IronPython, like `cpu_stats`) | Print m1..m4 ratios / CCR so bridge can poll without fragile register spelunking |
| Optional `setpoint_stats` / inject helper | Accept thrust+RPY from bridge if CRTP not ready yet |
| Resc variant `crazyflie_webots.resc` | No auto canned-only life; wait for bridge; still OTP `CF21`, GDB, ports |
| Do **not** put Webots inside Renode image | Keeps Mono image small; Webots stays on host |

### 3.3 Reading motors

Preferred order:

1. Firmware log group / parameters if already exposed  
2. New monitor command reading motor driver ratios (cleanest for bridge)  
3. Raw TIM2/TIM4 CCR via sysbus (brittle across Renode versions)

Map ratio ∈ [0, UINT16_MAX] or [0,1] → Webots propeller thrust/torque with a simple quadratic model first.

### 3.4 Setpoints without Crazyradio

Pick **one** for v1 (document choice in bridge README):

| Option | Pros | Cons |
|--------|------|------|
| **A. Firmware auto-hover patch** | Fast bring-up | Diverges from stock `cf2.elf` |
| **B. Inject CRTP over CF_Syslink UART hub** | Closest to real radio path | Protocol work |
| **C. Monitor/Python writes into commander** | No FW rebuild | May need FW symbols / hooks |

Recommend **A for first motion**, then **B** for “real” stack.

### 3.5 Timing

- Renode `sim_speed` often &lt; 1.0 on a laptop — bridge should use **Renode virtual time** (`currentTime` / `cpu_stats virt`) or wall clock with awareness of lag.  
- Prefer: Webots step → publish sensors stamped with wall or virt time → Renode consumes ASAP → read motors → apply before next Webots step (lockstep later).

---

## 4. Webots side

### 4.1 World / robot

| Piece | Recommendation |
|-------|------------------|
| Robot | Simple quadrotor PROTO (4 props, IMU-capable body) — Bitcraze CF PROTO if available, else generic quad |
| Physics | Default ODE; mass/inertia roughly CF2.1-ish (refine later) |
| Sensors | Gyro, accelerometer, optional GPS/alt from supervisor pose → derive baro pressure |
| Actuators | 4× `Propeller` or `RotationalMotor` + thrust plugins |
| Controller | Prefer **Supervisor + external bridge** over heavy in-Webots controller: Webots only exposes devices; bridge owns Renode I/O |

### 4.2 Webots → bridge API

Bridge each step (or each sensor tick):

1. Read body angular velocity → gyro (rad/s → BMI088 model units)  
2. Read linear acceleration in body frame → accel (include gravity)  
3. Read world Z / atmospheric model → pressure for `FeedPTSample`  
4. Publish to Renode  

### 4.3 Bridge → Webots API

1. Receive m1..m4  
2. Set propeller thrust (and optional torque for yaw)  
3. `robot.step(timestep)`  

Start with **open mapping** (thrust = k · ratio²), then tune k so hover thrust ≈ mg / 4.

### 4.4 Controllers / files to add (proposed tree)

```text
renode_test/
  webots/
    worlds/cf_hover.wbt
    protos/   # or use upstream CF proto
    controllers/  # optional thin stubs
  bridge/
    README.md
    webots_renode_bridge.py   # main process
    frames.py                 # ENU/NED/body conversions
    renode_client.py          # telnet monitor + :3456
    motor_map.py
```

---

## 5. Bridge process design

### 5.1 Responsibilities

```text
loop:
  sensors = webots.read_imu_baro()
  renode.feed_imu(sensors)      # Feed*Sample + DRDY
  renode.feed_baro(...)
  motors = renode.read_motors() # motor_stats
  webots.apply_motors(motors)
  maybe renode.inject_setpoint(hover)
  webots.step()
```

### 5.2 Connection details

- **Monitor client**: persistent TCP to `:9999`, telnet handshake (see `monitor_cpu.py`), never disconnect casually.  
- **Sensor socket `:3456`**: keep open; send pacing bytes for DRDY as required by BMI088 Renode model.  
- **Reconnect policy**: if Renode dies, exit bridge cleanly; do not half-close monitor.

### 5.3 Bring-up modes

| Mode | Behavior |
|------|----------|
| `sensors-only` | Webots pose → IMU; motors ignored / zero thrust — prove calib + estimator |
| `motors-open-loop` | Fixed setpoint in FW or bridge; motors → Webots; IMU from Webots — first “lift” |
| `closed-loop` | Host RPYT setpoint only; FW mixer → props 1:1 (see `PURE_FW_LOOP.md`) |

---

## 6. Implementation phases (ordered)

### Phase 2a — Sensor stream from host (no Webots yet)

1. Python script feeds continuous IMU/baro + DRDY over existing Renode Docker ports.  
2. Confirm self-test, bias, estimator ticking (`cpu_stats`, logs).  
**Exit:** stabilizer past calibration without canned-only FIFO exhaustion.

### Phase 2b — Motor observability ✅

1. `motor_stats` / `motor_force` / `motor_force_clear` in `scripts/monitor_cf.py` (reads `motor_ratios` + TIM CCR).  
2. Host: `./scripts/monitor_motors.sh 9999 --force …`.  
**Exit:** forced ratios visible in `motor_stats` (`n1..n4`).

### Phase 2c — Webots plant (open loop) ✅ scaffold

1. `webots/worlds/cf_hover.wbt` + `CrazyflieSimple.proto` + `bridge/` package.  
2. Dry-run: `python3 -m bridge.webots_renode_bridge --fake --mode motors-open-loop`.  
3. With Webots: open world (`controller <extern>`), run bridge `--mode motors-open-loop`.  
**Exit:** craft leaves ground briefly / spins props coherently; firmware does not disarm from WDT.

### Phase 2d — Closed-loop hover (in progress)

1. **Setpoint source (Option C):** monitor `setpoint_rpyt` / `setpoint_hover` overwrites
   FreeRTOS `setpointQueue` storage + refreshes timestamp (beats commander WDT).  
2. Bridge `--mode closed-loop` clears `motor_force`, injects RPYT each loop, reads
   `motor_stats`, applies **per-motor** FW ratios to Webots/FakePlant, feeds IMU/baro.  
3. Default `--alt-hold`: host PD on plant altitude → thrust setpoint; FW attitude
   mixer owns m1..m4. Optional `--fw-zdist` for FW Absolute-Z. See `PURE_FW_LOOP.md`.  
**Exit:** hover near `--alt-target` with FW per-motor mix and live IMU feedback.

```bash
# Webots altitude hold (FW motors 1:1)
FAKE=0 ALT=0.5 ./scripts/run_hover_demo.sh

# FakePlant
FAKE=1 ALT=0.5 SECONDS_RUN=50 ./scripts/run_hover_demo.sh
```

### Phase 2e — Hardening (later)

- Lockstep / virt-time sync  
- ToF or flow deck models if needed  
- Multi-drone  

---

## 7. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Renode sim_speed ≪ 1 | Lower Webots rate; scale thrust; monitor `sim=` |
| DRDY not wired | Validate with `:3456` / TriggerDataInterrupt early (2a) |
| Commander WDT | Always refresh setpoints; or FW patch timestamps |
| Monitor single-client | One bridge owns `:9999`; stats via bridge API, not second `nc` |
| Frame / unit errors | Central `frames.py` + unit tests with known hover pose |
| Docker networking | Stick to `--net=host` on Linux |

---

## 8. Success criteria (phase 2 done)

1. Renode runs stock (or minimally patched) `cf2.elf` in Docker.  
2. Webots shows a quadrotor whose motion is driven by Renode motor outputs.  
3. IMU/baro in Renode come from Webots pose/physics, not canned constants.  
4. Firmware completes init, calibrates, arms, and sustains flight mode without init/arm errors.  
5. Bridge is documented so a colleague can run: Webots + `DOCKER=1` Renode + `bridge/webots_renode_bridge.py`.

---

## 9. Non-goals (still)

- Pixel-perfect CF aerodynamics  
- Full Crazyradio stack  
- Deck ecosystem  
- Replacing PX4/`qemu_test` work  

---

## 10. Phase 2a status — external IMU injector (done)

Host script streams hover-like IMU/baro into Docker Renode and pulses DRDY:

```bash
# Terminal 1
RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh

# Terminal 2 (after Machine started.)
./scripts/inject_imu_stream.sh 9999
# optional: ./scripts/inject_imu_stream.sh 9999 --hz 200
```

| Piece | Role |
|-------|------|
| `imu_stream_start` / `stop` / `status` | ClockSource feeder (virtual-time Hz; avoids monitor RTT + thread races) |
| `imu_burst` / `imu_tick` / `baro_tick` | Batched or single-sample feeds |
| `scripts/inject_imu_stream.py` | Host control; self-test then stream (default `--mode stream`) |

**Constraint:** injector owns `-P` — do not run `monitor_cpu.sh` at the same time.

**Next:** 2b motor observability, then Webots plant (2c). See [FLIGHT_MIN.md](FLIGHT_MIN.md).
