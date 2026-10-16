#!/usr/bin/env python3
"""
Host bridge: plant (Webots or FakePlant) <-> Renode Crazyflie.

Modes:
  sensors-only     — plant IMU -> Renode; motors ignored
  motors-open-loop — force motor ratios; plant integrates thrust; IMU from plant
  closed-loop      — inject RPYT setpoint; FW motors -> plant; IMU back

With --alt-target, a host P+D loop modulates force/thrust to hold altitude (hover).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bridge.motor_map import MotorRatios, ThrustMap  # noqa: E402
from bridge.renode_io import RenodeBridge  # noqa: E402
from bridge.webots_io import FakePlant, open_plant  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Webots <-> Renode CF bridge")
    p.add_argument("--port", type=int, default=int(os.environ.get("RENODE_MONITOR_PORT", "9999")))
    p.add_argument(
        "--mode",
        choices=("sensors-only", "motors-open-loop", "closed-loop"),
        default="sensors-only",
    )
    p.add_argument("--fake", action="store_true", help="Use FakePlant (no Webots)")
    p.add_argument("--imu-hz", type=float, default=100.0)
    p.add_argument("--baro-hz", type=float, default=50.0)
    p.add_argument("--loop-hz", type=float, default=20.0, help="Bridge loop rate (wall)")
    p.add_argument("--seconds", type=float, default=0.0, help="Stop after N seconds (0=forever)")
    p.add_argument(
        "--force-ratio",
        type=float,
        default=0.0,
        help="motors-open-loop base ratio (0=use ThrustMap.hover_ratio)",
    )
    p.add_argument(
        "--thrust",
        type=float,
        default=29000.0,
        help="closed-loop base RPYT thrust (0..60000); ~29k ≈ hover for this map",
    )
    p.add_argument("--roll", type=float, default=0.0)
    p.add_argument("--pitch", type=float, default=0.0)
    p.add_argument("--yaw-rate", type=float, default=0.0)
    p.add_argument(
        "--alt-target",
        type=float,
        default=-1.0,
        help="If >=0, host P+D holds this altitude (m). Use 0.5 for hover demo.",
    )
    p.add_argument("--alt-kp", type=float, default=0.25, help="Altitude P gain on ratio/thrust")
    p.add_argument("--alt-kd", type=float, default=0.55, help="Altitude D gain")
    p.add_argument("--status-every", type=float, default=2.0)
    p.add_argument("--wait-calib", action="store_true")
    p.add_argument("--wait-preflight", action="store_true")
    return p.parse_args()


def _push_sensors(renode: RenodeBridge, sample, zero_gyro: bool = False) -> None:
    # Optional ground gyro mute (legacy); default path feeds real Webots gyro
    # so the FW attitude loop can work like Bitcraze's controller.
    if zero_gyro:
        gx = gy = gz = 0.0
    else:
        gx, gy, gz = sample.gx, sample.gy, sample.gz
    renode.set_imu_sample(
        gx, gy, gz,
        sample.ax, sample.ay, sample.az,
        sample.pressure, sample.temp,
    )


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def main() -> int:
    args = parse_args()
    print(
        f"bridge mode={args.mode} port={args.port} fake={args.fake} "
        f"imu_hz={args.imu_hz} loop_hz={args.loop_hz} alt_target={args.alt_target}",
        flush=True,
    )

    thrust_map = ThrustMap()
    hover_r = thrust_map.hover_ratio()
    base_ratio = args.force_ratio if args.force_ratio > 0 else hover_r

    print(f"Connecting Renode monitor :{args.port} ...", flush=True)
    renode = RenodeBridge.connect(args.port, imu_hz=args.imu_hz, baro_hz=args.baro_hz)
    print("Renode connected.", flush=True)

    plant = (
        FakePlant(timestep_s=1.0 / args.loop_hz, thrust_map=thrust_map)
        if args.fake
        else open_plant(prefer_webots=True, thrust_map=thrust_map)
    )
    if isinstance(plant, FakePlant):
        print("Using FakePlant (no Webots controller module).", flush=True)
    else:
        print("Using WebotsPlant (connected to Webots).", flush=True)

    period = 1.0 / args.loop_hz if args.loop_hz > 0 else 0.05
    # Cap Renode monitor traffic — each query can take tens–hundreds of ms and
    # otherwise starves Webots (sim crawls at ~0.01× realtime).
    imu_period = 1.0 / min(args.imu_hz, 40.0) if args.imu_hz > 0 else 0.025
    hold_alt = args.alt_target >= 0.0
    prev_alt = 0.0
    prev_t = time.time()
    use_webots = not isinstance(plant, FakePlant)
    sim_dt = float(getattr(plant, "timestep_s", 0.008))

    def _sim_time() -> float:
        robot = getattr(plant, "robot", None)
        if robot is None:
            return 0.0
        return float(robot.getTime())

    def _catch_up(wall_origin: float, sim_origin: float, n_steps: list[int]) -> bool:
        """Advance Webots toward wall clock so Renode I/O latency does not stall physics."""
        if not use_webots:
            return True
        target = sim_origin + (time.time() - wall_origin)
        # Cap one burst so a huge lag does not freeze the UI for seconds.
        deadline = _sim_time() + 0.25
        while _sim_time() < min(target, deadline):
            if last_motors is not None:
                plant.apply_motors(last_motors)
            if plant.step() == -1:
                return False
            n_steps[0] += 1
        return True

    try:
        if use_webots:
            for _ in range(5):
                plant.step()

        renode.feed_imu_burst(10, 10, 20, 30, 0, 0, 1000)
        renode.set_imu_sample(0.0, 0.0, 0.0, 0.0, 0.0, 1000.0, 101325.0, 25.0)
        print("IMU stream started (hover rest for calib).", flush=True)

        last_motors = None
        if args.wait_calib or args.wait_preflight:
            print(
                "Waiting for firmware gates (Webots paused — avoid floor-contact lock)...",
                flush=True,
            )
            gate_t0 = time.time()
            last_gate_print = 0.0
            # Do NOT step Webots here. Advancing ~20–30 s of contact settles the
            # craft into the floor so later propeller thrust cannot lift it.
            while True:
                now = time.time()
                if (now - last_gate_print) >= 2.0:
                    # Keep Renode IMU at rest for calib (ClockSource stream).
                    renode.set_imu_sample(0.0, 0.0, 0.0, 0.0, 0.0, 1000.0, 101325.0, 25.0)
                    ok_c = renode.calib_ok()
                    ok_p = renode.preflight_ok()
                    st = (renode.client.query("imu_stream_status") or "").strip().replace("\n", " ")
                    print(f"  calib={int(ok_c)} preflight={int(ok_p)} {st}", flush=True)
                    last_gate_print = now
                    if args.wait_preflight and ok_p:
                        break
                    if args.wait_calib and not args.wait_preflight and ok_c:
                        break
                if (now - gate_t0) > max(args.seconds, 180.0):
                    print("TIMEOUT waiting for gates", file=sys.stderr)
                    return 2
                time.sleep(0.05)

        if args.mode == "motors-open-loop":
            print(
                f"Open-loop base_ratio={base_ratio:.3f} (hover_map={hover_r:.3f})"
                + (f" alt_target={args.alt_target:.2f}m" if hold_alt else ""),
                flush=True,
            )
            r0 = MotorRatios(base_ratio, base_ratio, base_ratio, base_ratio)
            renode.force_motors(r0)
            plant.apply_motors(r0)
            last_motors = r0
        elif args.mode == "closed-loop":
            renode.clear_motor_force()
            print(
                f"Closed-loop base_thrust={args.thrust:.0f}"
                + (f" alt_target={args.alt_target:.2f}m" if hold_alt else ""),
                flush=True,
            )
            renode.inject_setpoint_rpyt(args.roll, args.pitch, args.yaw_rate, args.thrust)

        t0 = time.time()
        sim0 = _sim_time()
        last_status = t0
        last_control = 0.0
        last_imu = 0.0
        last_thrust = args.thrust
        n_box = [0]
        u = 0.0
        sample = plant.read_sensors()
        while True:
            loop_t0 = time.time()
            if use_webots and not _catch_up(t0, sim0, n_box):
                print("Webots quit.", flush=True)
                break

            now = time.time()
            sample = plant.read_sensors()
            alt = float(getattr(sample, "altitude_m", 0.0))
            dt = max(1e-3, now - prev_t)
            vz = (alt - prev_alt) / dt
            prev_alt, prev_t = alt, now

            if (now - last_imu) >= imu_period:
                _push_sensors(renode, sample, zero_gyro=False)
                last_imu = now

            if (now - last_control) >= period:
                if hold_alt:
                    # Clamp sensor glitches so a bad GPS spike cannot cut thrust to 0.
                    alt_err = _clamp(args.alt_target - alt, -1.0, 1.0)
                    vz_c = _clamp(vz, -2.0, 2.0)
                    u = args.alt_kp * alt_err - args.alt_kd * vz_c
                else:
                    u = 0.0

                if args.mode == "sensors-only":
                    pass
                elif args.mode == "motors-open-loop":
                    ratio = _clamp(base_ratio + u, 0.05, 0.9)
                    force = MotorRatios(ratio, ratio, ratio, ratio)
                    renode.force_motors(force)
                    if use_webots and hasattr(plant, "unstick_for_takeoff") and ratio > 0.4:
                        plant.unstick_for_takeoff()
                    plant.apply_motors(force)
                    last_motors = force
                else:  # closed-loop — mirror Bitcraze crazyflie.c motor path:
                    #   wb_motor_set_velocity(m1, -power); m2 +power; m3 -; m4 +
                    # Host only adjusts the injected RPYT thrust setpoint; the FW
                    # attitude mixer owns the four motor ratios applied to Webots.
                    # Gravity (mg) vs thrust is enough to climb/descend — no drag
                    # required; if T≈mg with upward speed you coast until T is cut.
                    thrust = _clamp(args.thrust + u * 12000.0, 18000.0, 55000.0)
                    renode.inject_setpoint_rpyt(
                        args.roll, args.pitch, args.yaw_rate, thrust
                    )
                    last_thrust = thrust
                    motors = renode.read_motors()
                    if motors is not None:
                        if (
                            use_webots
                            and hasattr(plant, "unstick_for_takeoff")
                            and motors.mean() > 0.4
                        ):
                            plant.unstick_for_takeoff()
                        # Per-motor FW ratios → signed ω inside apply_motors
                        plant.apply_motors(motors)
                        last_motors = motors
                last_control = now

            if not use_webots:
                plant.step()
                n_box[0] += 1

            n = n_box[0]
            if now - last_status >= args.status_every:
                motors = last_motors
                mtxt = (
                    f"m=({motors.m1:.3f},{motors.m2:.3f},{motors.m3:.3f},{motors.m4:.3f})"
                    if motors
                    else "m=(?)"
                )
                wv = ""
                if use_webots and hasattr(plant, "motor_velocities"):
                    v = plant.motor_velocities()
                    wv = f" ω=({v[0]:.0f},{v[1]:.0f},{v[2]:.0f},{v[3]:.0f})"
                print(
                    f"{now:.3f} n={n} sim={_sim_time():.2f} alt={alt:.3f} vz={vz:.2f} "
                    f"u={u:+.3f} {mtxt}{wv} a=({sample.ax:.0f},{sample.ay:.0f},{sample.az:.0f})",
                    flush=True,
                )
                last_status = now

            if args.seconds > 0 and (now - t0) >= args.seconds:
                print(f"Done after {args.seconds:.0f}s. final_alt={alt:.3f}m", flush=True)
                break

            if not use_webots:
                slept = time.time() - loop_t0
                if slept < period:
                    time.sleep(period - slept)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        try:
            if args.mode == "closed-loop":
                renode.clear_setpoint()
            renode.clear_motor_force()
        except Exception:
            pass
        renode.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
