# Canned sensors (phase 1)

Bitcraze Renode Crazyflie models accept samples via Monitor methods:

```text
sysbus.i2c3.bmi_gyro   FeedGyroSample <x> <y> <z> [<count>]
sysbus.i2c3.bmi_accel  FeedAccSample <x> <y> <z> [<count>]
sysbus.i2c3.bmp_baro   FeedPTSample <pressure_Pa> <temp_C> [<count>]
```

`run_first_test.sh` feeds a few samples at start (gyro/accel/baro) so sensor init can proceed.

## Hover-ish canned set

| Sensor | Approx meaning | Example feed |
|--------|----------------|--------------|
| Gyro | at rest | `0 0 0` |
| Accel | ~1 g on Z while level | `0 0 1000` (model units; often mg-ish) |
| Baro | static pressure | `101325 25` |

Phase 1 only needs **enough samples for init/self-test**, not a flight trajectory.

## Later: RESD / Webots

Renode supports [RESD](https://renode.readthedocs.io/en/latest/basic/resd.html) for file-based streams. A Webots bridge would either:

1. Call `Feed*Sample` over Renode’s monitor socket (`renode -P`), or  
2. Push into the sensor terminal on port **3456**.

Do not implement that until phase 1 boots cleanly on every machine.
