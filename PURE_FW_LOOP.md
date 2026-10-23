# Pure FW → Webots props (closed loop)

Goal: Renode `cf2.elf` attitude mixer drives Webots `m1..m4` directly; sensors
from Webots close the FW loops; altitude is held at a commanded height.

## Architecture (current default)

```
Host commander
  alt PD ──► RPYT.thrust          roll/pitch/yaw setpoints
                 │                         │
                 └──────────┬──────────────┘
                            ▼
                   Renode cf2.elf
              attitude PID + mixer ──► motor_ratios[4]
                            │
                            ▼
              Webots m1..m4 (Bitcraze ω signs, 1:1)
                            │
         gyro / accel / baro(pressure←alt) / GPS alt
                            │
              └─► Feed*Sample + host alt PD feedback
```

- **Individual motors:** FW mixer only — host never rewrites plant ratios.
- **Sensor feedback:** Webots IMU/baro → Renode; GPS alt → host altitude PD.
- **Altitude:** host thrust setpoint (CRTP-commander style). Optional `--fw-zdist`
  uses FW Absolute-Z (`setpoint_zdist`); needs a trustworthy baro Z estimate
  (Kalman in this build does not enable `KALMAN_USE_BARO_UPDATE`).

## Smoke results

| Test | Result |
|------|--------|
| FakePlant alt-hold 0.5 m | Holds near target (tail err ≲ 0.1 m) |
| Webots level alt-hold 0.5 m | **PASS** — settled ≈ 0.55 m, equal motors, gyro≈0 |
| Webots + small roll | Per-motor deltas present; keep roll modest while tuning |

## CLI

```bash
# Default: altitude hold + FW attitude mixer → props
FAKE=0 ALT=0.5 ./scripts/run_hover_demo.sh

# With JSONL probe stream (for orchestration / offline analysis)
TELEMETRY=/tmp/cf_bridge.jsonl FAKE=0 ALT=0.5 ./scripts/run_hover_demo.sh

# FakePlant (no Webots GUI)
FAKE=1 ALT=0.5 SECONDS_RUN=50 ./scripts/run_hover_demo.sh

# Experimental FW Absolute-Z (baro fusion limited in this ELF)
FW_ZDIST=1 ALT=0.5 ./scripts/run_hover_demo.sh
```

## Monitor additions

- `setpoint_zdist roll pitch yaw z` — Absolute-Z + attitude (mode.z=Abs)
- `setpoint_stats` — includes `z=` and mode bits

## Related

- [ORCHESTRATION.md](ORCHESTRATION.md) — ports, single-client monitor, probe taps
- [README.md](README.md) — quick start
