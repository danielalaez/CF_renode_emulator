# Phase 1 checklist — Crazyflie + Renode + canned sensors

## Goal

Boot `cf2.elf` on Bitcraze Renode CF2.1 with canned gyro/accel/baro. No Webots.

## Colleague path (Docker)

```bash
./scripts/bootstrap.sh
RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh
# second terminal:
./scripts/monitor_cpu.sh 9999
```

## Verify

- [ ] `Machine started.`
- [ ] No missing-type errors for BMI088 / CF_Syslink / STM32_Basic_Timer
- [ ] LED / timer / rtc activity in logs
- [ ] GDB: `gdb-multiarch firmware/cf2.elf` → `target remote :3333`
- [ ] `cpu_stats` shows rising `ins` / `virt` (low util + idle PC is OK)

## Not in phase 1

Webots bridge, Gazebo, radio, decks — see README Non-goals.
