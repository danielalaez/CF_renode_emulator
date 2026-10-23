# Webots plant for Renode CF bridge

Uses the **official Bitcraze [Crazyflie PROTO](https://cyberbotics.com/doc/guide/crazyflie)** (mesh, 4× `Propeller`, `m1_motor`…`m4_motor`), not a gray box.

World: `worlds/cf_hover.wbt` (`controller "<extern>"`, `supervisor TRUE`).

## Control loop

```text
Webots gyro/GPS  ──IMU/baro──►  Renode cf2.elf (BMI088 + commander)
Webots props     ◄──m1..m4────  FW motor_ratios (via monitor)
Host bridge      ──RPYT(+alt)─►  setpoint injection (no Crazyradio)
```

- **Actuators:** FW ratios → motor ω with Bitcraze signs; Propeller `thrustConstants` produce lift/torque in Webots physics.
- **Sensors:** Webots gyro (+ derived accel from GPS/attitude) → Renode `imu_stream_set`.
- **Commands:** `closed-loop` injects RPYT; default `--alt-hold` trims thrust like a
  throttle stick to hold `ALT` (FW attitude mixer still owns m1..m4).

See [../README.md](../README.md) and [../ORCHESTRATION.md](../ORCHESTRATION.md).

## Hover demo

```bash
cd renode_test
export WEBOTS_HOME=$HOME/.local/webots-R2025a

# FW-driven props + official model (default closed-loop + alt-hold)
FAKE=0 ALT=0.5 SECONDS_RUN=45 ./scripts/run_hover_demo.sh

# JSONL probes for orchestration
TELEMETRY=/tmp/cf_bridge.jsonl FAKE=0 ALT=0.5 ./scripts/run_hover_demo.sh

# Bypass FW mixer (debug plant only)
MODE=motors-open-loop SECONDS_RUN=40 ALT=0.5 ./scripts/run_hover_demo.sh

# No GUI
FAKE=1 ALT=0.5 SECONDS_RUN=50 ./scripts/run_hover_demo.sh
```

## Manual

```bash
# T1
RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh

# T2
export WEBOTS_HOME=$HOME/.local/webots-R2025a
export PYTHONPATH=$WEBOTS_HOME/lib/controller/python
export LD_LIBRARY_PATH=$WEBOTS_HOME/lib/controller:$WEBOTS_HOME/lib/webots
$WEBOTS_HOME/webots --mode=realtime webots/worlds/cf_hover.wbt &
python3 -m bridge.webots_renode_bridge --mode closed-loop \
  --wait-preflight --thrust 32000 --alt-target 0.5 \
  --imu-hz 80 --loop-hz 12 --seconds 70
```
