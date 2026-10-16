# Minimum I/O for basic Crazyflie operation (init → arm → fly)

This document lists the **smallest set of sensors and actuators** the Crazyflie 2.1 firmware (`cf2.elf`) needs so Renode can pass initialization, arming, and a simple hover-style flight — without decks, radio hardware, or USB.

Phase 1 (canned samples) already boots the firmware. This doc is the contract for **phase 2** (Webots closed loop).

## Pipeline that must not fail

```text
Init / self-test → gyro bias calib → estimator → arm → setpoints → motors
     BMI088+BMP3      continuous IMU     attitude    auto*   CRTP/WDT   TIM PWM
```

\*Default firmware build often has motor arming requirement disabled → **auto-arm** after preflight (not tumbled, no deck fault).

---

## 1. Sensors (inputs into firmware)

### 1.1 Hard — required for init / self-test

| Sensor | Renode name | Bus / addr | Firmware role | Feed notes |
|--------|-------------|------------|---------------|------------|
| BMI088 gyro | `sysbus.i2c3.bmi_gyro` | I2C3 `0x69` | Chip ID, self-test, rate loop | Self-test **fails if x=y=z are all 0**. Need at least one non-zero sample for self-test. |
| BMI088 accel | `sysbus.i2c3.bmi_accel` | I2C3 `0x18` | Chip ID, attitude, tumble check | Upright ≈ **1 g on Z** (model units; often ~1000). |
| BMP388 baro | `sysbus.i2c3.bmp_baro` | I2C3 `0x77` | Baro present flag, altitude path | Static `101325 Pa`, `25 °C` enough for init. |

Monitor methods (Bitcraze models):

```text
sysbus.i2c3.bmi_gyro  FeedGyroSample <x> <y> <z> [<count>]
sysbus.i2c3.bmi_accel FeedAccSample  <x> <y> <z> [<count>]
sysbus.i2c3.bmp_baro  FeedPTSample   <Pa> <°C> [<count>]
```

### 1.2 Hard — required after self-test (calibration + rate loop)

| Requirement | Why |
|-------------|-----|
| Continuous gyro + accel samples | Stabilizer waits until **gyro bias found**; then runs ~1 kHz fusion. |
| Data-ready IRQ (DRDY) | Gyro `Int3 → exti@14`. `Feed*Sample` alone does **not** raise DRDY. Sensor socket **:3456** (`WriteChar` path) triggers interrupt. Without DRDY, `sensorsTask` starves. |

Target stream: **~1 kHz** IMU (gyro + accel), low noise at rest after a short non-zero self-test burst.

### 1.3 Soft / optional for “simplest hover”

| Input | Role | Required for v1? |
|-------|------|------------------|
| BMP388 continuous | Altitude / Z-hold | Soft for “motors + attitude”; **yes** for altHold |
| Flow deck (PMW3901) | XY velocity | No |
| ToF / Z-ranger (VL53) | Height | No (nice later) |
| Magnetometer | Absolute yaw | Not on CF2.1 BMI088 path |
| Battery via syslink | Voltage | Soft — PM seeds ~3.7 V |
| Decks I2C1 `0x41`/`0x42` | Deck discovery | No — “no slave” is OK |
| USB OTG | Host link | No — log noise only |
| Crazyradio / nRF | CRTP transport | Soft for boot; **need some setpoint path** to fly |

---

## 2. Command / arming inputs (not IMU)

| Input | Hard for flight? | Notes |
|-------|------------------|-------|
| Setpoints (thrust + attitude or high-level) | **Yes** | Via CRTP over radiolink → **syslink** (USART6 ↔ `CF_Syslink`). |
| Commander watchdog refresh | **Yes** | ~500 ms warning, **~2 s** without update → motors shut off. |
| Emergency-stop CRTP | Soft until first packet | Inactive until first watchdog notification. |
| Arm switch / arming CRTP | Soft if auto-arm | Preflight: upright accel, no tumble. |

**No physical radio required** if a host bridge injects CRTP/syslink frames or a temporary firmware patch refreshes hover setpoints with live timestamps.

---

## 3. Actuators (outputs from firmware)

### 3.1 Hard — motors (brushed default map)

| Motor | GPIO | Timer channel | Renode peripheral |
|-------|------|---------------|-------------------|
| M1 | PA1 | TIM2_CH2 | `sysbus.timer2` |
| M2 | PB11 | TIM2_CH4 | `sysbus.timer2` |
| M3 | PA15 | TIM2_CH1 | `sysbus.timer2` |
| M4 | PB9 | TIM4_CH4 | `sysbus.timer4` |

Firmware: `power_distribution_quadrotor` → `motorsSetRatio` → PWM CCR.

For phase 2: **read PWM duty / CCR** (or ratio logs) and map to Webots propeller thrust. No ESC telemetry required for stock brushed config.

### 3.2 Soft — status only

| Output | Role |
|--------|------|
| LEDs (GPIOC/D) | Heartbeat / status — already modeled |
| USART3 console | Debug logs |
| Syslink TX | Battery/radio ACKs — optional to model fully |

---

## 4. What Renode CF2 already provides

From `platforms/boards/cf2.repl` + `stm32f405.repl`:

- BMI088 gyro/accel, BMP388, EEPROM, LEDs  
- `CF_Syslink` + USART6 hub  
- TIM2 / TIM4 (motor PWM capable)  
- EXTI wiring for gyro DRDY  
- GDB `:3333`, sensor socket `:3456`, optional monitor `-P`

**Gaps that block “fake flying” today**

1. Sustained IMU + DRDY (not just canned FIFO counts)  
2. Setpoint / CRTP injection without radio  
3. Motor PWM → external physics (Webots)  
4. Webots → IMU/baro sample stream  

---

## 5. Minimal contract for phase 2 (Webots)

### Host → Renode (firmware inputs)

| Channel | Rate (target) | Payload |
|---------|---------------|---------|
| Gyro | ~1 kHz | ωx, ωy, ωz (+ DRDY pulse) |
| Accel | ~1 kHz | ax, ay, az (level ≈ 1 g Z) |
| Baro | ~50–100 Hz | pressure Pa, temp °C |
| Setpoints | ≥20 Hz (≫ WDT) | thrust + roll/pitch/yaw (or HL commander) |

### Renode → Host (firmware outputs)

| Channel | Rate | Payload |
|---------|------|---------|
| Motor PWM / ratios | ~100–500 Hz (or on change) | m1..m4 ∈ [0,1] or CCR |
| Optional: attitude / state | debug | not required if Webots integrates physics |

### Explicit non-goals for first closed loop

- Flow / ToF / mag / lighthouse decks  
- Full Crazyradio RF  
- USB device stack  
- Battery chemistry / ADC  

---

## 6. Sanity checks (firmware “thinks it’s alive”)

| Stage | Pass signal |
|-------|-------------|
| Self-test | Log / LED path past BMI088+BMP3 tests (non-zero gyro once) |
| Calibration | `calib_status` → `calibrated=1` (`gyroBiasFound` / BiasObj) |
| Pre-flight | `preflight_status` → `preflight_ok=1` (state ≥ `PreFlChecksPassed`) |
| Armed / ready | `isArmed=1` / `state=ReadyToFly` / `canFly=1` (auto-arm in this build) |
| Flying | Motor ratios > idle while setpoints refresh; no commander timeout |
| Hover-ish | Accel upright; gyro near rest; thrust steady; baro slowly changing only if climbing |

```bash
# Terminal 1
RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh
# Terminal 2 — IMU until gyro bias found
./scripts/check_calib.sh 9999
# Terminal 2 — IMU until supervisor past pre-flight (often ReadyToFly with auto-arm)
./scripts/check_preflight.sh 9999
```

## 7. Phase 2a — inject from outside Renode (no Webots yet)

```bash
RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh   # terminal 1
./scripts/inject_imu_stream.sh 9999                             # terminal 2
```

- First samples: non-zero gyro (self-test), then gyro≈0 / accel≈1g Z / static baro.
- Default mode: `imu_stream_start` adds a **Machine.ClockSource** feeder (virtual-time Hz; not a host thread).
- Expect `streaming=1` and `virt_hz≈target`; wall `out_hz` tracks `sim_speed` (often &lt; target).
- Do **not** feed from a host/`System.Threading` thread — that races Renode and can `CPU abort`.
- DRDY via `TriggerDataInterrupt` each sample.

See [WEBOTS_BRIDGE.md](WEBOTS_BRIDGE.md) for the full Webots plan.
