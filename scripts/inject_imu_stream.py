#!/usr/bin/env python3
"""
Phase 2a: stream IMU (+ optional baro) + DRDY into Renode from the host.

Default mode starts a background feeder *inside* Renode (imu_stream_start)
so sample rate is not capped by monitor TCP round-trips.

Requires Renode started with:
  RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh

This process owns the monitor socket — do not run monitor_cpu.sh at the same time.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from renode_monitor import RenodeClient  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Inject continuous IMU/baro + DRDY into Renode")
    p.add_argument("port", nargs="?", type=int, default=int(os.environ.get("RENODE_MONITOR_PORT", "9999")))
    p.add_argument("--hz", type=float, default=float(os.environ.get("IMU_HZ", "100")),
                   help="IMU sample rate (default 100; raise toward 1000 when stable)")
    p.add_argument("--baro-hz", type=float, default=float(os.environ.get("BARO_HZ", "50")),
                   help="Baro sample rate (default 50; 0 disables)")
    p.add_argument("--selftest-n", type=int, default=int(os.environ.get("IMU_SELFTEST_N", "10")),
                   help="Non-zero gyro samples at start for BMI088 self-test")
    p.add_argument("--gx", type=float, default=10.0, help="Self-test gyro X")
    p.add_argument("--gy", type=float, default=20.0, help="Self-test gyro Y")
    p.add_argument("--gz", type=float, default=30.0, help="Self-test gyro Z")
    p.add_argument("--ax", type=float, default=0.0)
    p.add_argument("--ay", type=float, default=0.0)
    p.add_argument("--az", type=float, default=1000.0, help="Hover accel Z (~1g model units)")
    p.add_argument("--pressure", type=float, default=101325.0)
    p.add_argument("--temp", type=float, default=25.0)
    p.add_argument(
        "--mode",
        choices=("stream", "burst", "tick"),
        default=os.environ.get("IMU_INJECT_MODE", "stream"),
        help="stream=ClockSource feeder (fast); burst=batched monitor cmds; tick=1 sample/RTT (slow)",
    )
    p.add_argument("--burst-n", type=int, default=int(os.environ.get("IMU_BURST_N", "20")),
                   help="Samples per monitor command in burst mode")
    p.add_argument("--status-every", type=float, default=2.0, help="Print status every N seconds")
    p.add_argument("--wait-calib", action="store_true",
                   help="Exit 0 when calib_status reports calibrated=1")
    p.add_argument("--wait-preflight", action="store_true",
                   help="Exit 0 when preflight_status reports preflight_ok=1 "
                        "(supervisor past PreFlChecksNotPassed)")
    p.add_argument("--timeout", type=float, default=float(os.environ.get("IMU_CALIB_TIMEOUT", "180")),
                   help="With --wait-*, fail after N wall seconds (default 180)")
    return p.parse_args()


def run_stream_mode(client: RenodeClient, args: argparse.Namespace) -> int:
    """Self-test burst, then background feeder inside Renode."""
    if args.selftest_n > 0:
        print(f"Self-test: imu_burst {args.selftest_n} (non-zero gyro)…", flush=True)
        out = client.query(
            f"imu_burst {args.selftest_n} {args.gx} {args.gy} {args.gz} "
            f"{args.ax} {args.ay} {args.az}"
        )
        if out:
            print(f"  {out}", flush=True)

    print(
        f"Starting in-Renode stream at {args.hz} Hz "
        f"(baro={args.baro_hz} Hz)…",
        flush=True,
    )
    out = client.query(
        f"imu_stream_start {args.hz} 0 0 0 {args.ax} {args.ay} {args.az} "
        f"{args.baro_hz} {args.pressure} {args.temp}"
    )
    if out:
        print(f"  {out}", flush=True)
    if "error=" in (out or ""):
        print("ERROR: imu_stream_start failed; try --mode burst", file=sys.stderr)
        return 1

    waiting = args.wait_calib or args.wait_preflight
    if args.wait_preflight:
        print(
            f"Waiting for preflight (preflight_ok=1), timeout={args.timeout:.0f}s ...\n",
            flush=True,
        )
    elif args.wait_calib:
        print(
            f"Waiting for sensor calib (calibrated=1), timeout={args.timeout:.0f}s ...\n",
            flush=True,
        )
    else:
        print("Streaming... (Ctrl+C to stop; this will quit Renode)\n", flush=True)

    def _stop_stream() -> None:
        try:
            client.query("imu_stream_stop")
        except ConnectionError:
            pass

    t0 = time.time()
    try:
        while True:
            time.sleep(args.status_every)
            status = client.query("imu_stream_status")
            calib = client.query("calib_status")
            preflight = client.query("preflight_status")
            now = time.time()
            print(f"{now:.3f}  {status or '(no status)'}", flush=True)
            print(f"{now:.3f}  {calib or '(no calib_status)'}", flush=True)
            print(f"{now:.3f}  {preflight or '(no preflight_status)'}", flush=True)
            if status and "streaming=0" in status:
                print("ERROR: background stream died", file=sys.stderr)
                return 1
            if args.wait_preflight and preflight and "preflight_ok=1" in preflight:
                print("\nPASS: supervisor past pre-flight checks.", flush=True)
                print(f"  {preflight}", flush=True)
                _stop_stream()
                return 0
            if args.wait_calib and not args.wait_preflight and calib and "calibrated=1" in calib:
                print("\nPASS: firmware past gyro bias calibration.", flush=True)
                _stop_stream()
                return 0
            if waiting and (now - t0) >= args.timeout:
                what = "preflight" if args.wait_preflight else "calib"
                print(
                    f"\nFAIL: {what} not reached after {args.timeout:.0f}s wall time.\n"
                    f"  Last calib: {calib}\n"
                    f"  Last preflight: {preflight}",
                    file=sys.stderr,
                )
                _stop_stream()
                return 2
    except KeyboardInterrupt:
        try:
            out = client.query("imu_stream_stop")
            if out:
                print(f"\n{out}")
        except ConnectionError:
            print("\nStopped (Renode closed).")
        return 0


def run_burst_mode(client: RenodeClient, args: argparse.Namespace) -> int:
    """Host-paced bursts: many samples per monitor RTT."""
    period = args.burst_n / args.hz
    baro_every = 0
    if args.baro_hz > 0:
        baro_every = max(1, int(round(args.hz / args.baro_hz)))

    print(
        f"Burst mode: {args.burst_n} samples/cmd ≈ {args.hz} Hz "
        f"(period {period:.3f}s)",
        flush=True,
    )
    print("Streaming… (Ctrl+C to stop; this will quit Renode)\n", flush=True)

    n = 0
    t0 = time.time()
    last_status = t0
    next_tick = t0

    try:
        while True:
            now = time.time()
            if now < next_tick:
                time.sleep(min(0.002, next_tick - now))
                continue
            next_tick += period
            if next_tick < time.time() - 1.0:
                next_tick = time.time()

            if n < args.selftest_n:
                gx, gy, gz = args.gx, args.gy, args.gz
                count = min(args.burst_n, args.selftest_n - n)
            else:
                gx = gy = gz = 0.0
                count = args.burst_n

            client.run(
                f"imu_burst {count} {gx} {gy} {gz} {args.ax} {args.ay} {args.az}"
            )
            if baro_every and (n % baro_every) < count:
                client.run(f"baro_tick {args.pressure} {args.temp}")

            n += count
            if now - last_status >= args.status_every:
                elapsed = now - t0
                rate = n / elapsed if elapsed > 0 else 0.0
                mode = "selftest" if n <= args.selftest_n else "hover"
                print(
                    f"{now:.3f}  n={n}  out_hz={rate:.1f}  mode={mode}  "
                    f"g=({gx},{gy},{gz}) a=({args.ax},{args.ay},{args.az})",
                    flush=True,
                )
                last_status = now
    except KeyboardInterrupt:
        print(f"\nStopped after {n} samples.")
        return 0


def run_tick_mode(client: RenodeClient, args: argparse.Namespace) -> int:
    """Legacy: one imu_tick per monitor RTT (slow; for debugging only)."""
    period = 1.0 / args.hz
    baro_every = max(1, int(round(args.hz / args.baro_hz))) if args.baro_hz > 0 else 0

    print("Tick mode (slow — prefer --mode stream).", flush=True)
    print("Streaming… (Ctrl+C to stop; this will quit Renode)\n", flush=True)

    n = 0
    t0 = time.time()
    last_status = t0
    next_tick = t0

    try:
        while True:
            now = time.time()
            if now < next_tick:
                time.sleep(min(0.001, next_tick - now))
                continue
            next_tick += period
            if next_tick < time.time() - 1.0:
                next_tick = time.time()

            if n < args.selftest_n:
                gx, gy, gz = args.gx, args.gy, args.gz
            else:
                gx = gy = gz = 0.0

            client.run(f"imu_tick {gx} {gy} {gz} {args.ax} {args.ay} {args.az}")
            if baro_every and (n % baro_every == 0):
                client.run(f"baro_tick {args.pressure} {args.temp}")

            n += 1
            if now - last_status >= args.status_every:
                elapsed = now - t0
                rate = n / elapsed if elapsed > 0 else 0.0
                mode = "selftest" if n <= args.selftest_n else "hover"
                print(
                    f"{now:.3f}  n={n}  out_hz={rate:.1f}  mode={mode}  "
                    f"g=({gx},{gy},{gz}) a=({args.ax},{args.ay},{args.az})",
                    flush=True,
                )
                last_status = now
    except KeyboardInterrupt:
        print(f"\nStopped after {n} samples.")
        return 0


def main() -> int:
    args = parse_args()
    if args.hz <= 0:
        print("ERROR: --hz must be > 0", file=sys.stderr)
        return 1

    print(f"IMU injector → monitor :{args.port}  hz={args.hz}  baro_hz={args.baro_hz}  mode={args.mode}")
    print("Owns Renode -P socket (do not run monitor_cpu.sh in parallel).")
    print("Wait until Renode shows Machine started. before connecting.\n")

    try:
        client = RenodeClient(args.port, cmd_timeout=5.0)
    except (ConnectionError, TimeoutError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Connected.", flush=True)
    try:
        if args.mode == "stream":
            return run_stream_mode(client, args)
        if args.mode == "burst":
            return run_burst_mode(client, args)
        return run_tick_mode(client, args)
    except ConnectionError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
