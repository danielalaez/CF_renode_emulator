"""Coordinate frame helpers: Webots ENU <-> Crazyflie body / NED-ish IMU."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Vec3:
    x: float
    y: float
    z: float


def quat_rotate(q: tuple[float, float, float, float], v: Vec3) -> Vec3:
    """Rotate vector by quaternion (x,y,z,w) — Webots convention."""
    x, y, z, w = q
    # t = 2 * cross(q.xyz, v)
    tx = 2.0 * (y * v.z - z * v.y)
    ty = 2.0 * (z * v.x - x * v.z)
    tz = 2.0 * (x * v.y - y * v.x)
    # v + w*t + cross(q.xyz, t)
    return Vec3(
        v.x + w * tx + (y * tz - z * ty),
        v.y + w * ty + (z * tx - x * tz),
        v.z + w * tz + (x * ty - y * tx),
    )


def enu_accel_to_cf_body(
    lin_acc_world: Vec3,
    gravity_world: Vec3,
    orientation_xyzw: tuple[float, float, float, float],
) -> Vec3:
    """
    Specific force in body frame for BMI088-style accel (includes gravity).
    Webots: world ENU, +Z up. CF body: +Z up when upright (approx).
    """
    # specific force in world = a - g  (accelerometer measures proper acceleration)
    # For "at rest upright": expect ~ (0,0,+g) in body if Z-up body.
    fx = lin_acc_world.x - gravity_world.x
    fy = lin_acc_world.y - gravity_world.y
    fz = lin_acc_world.z - gravity_world.z
    # rotate world->body: use conjugate quaternion
    x, y, z, w = orientation_xyzw
    q_conj = (-x, -y, -z, w)
    return quat_rotate(q_conj, Vec3(fx, fy, fz))


def enu_gyro_to_cf_body(
    ang_vel_world: Vec3,
    orientation_xyzw: tuple[float, float, float, float],
) -> Vec3:
    x, y, z, w = orientation_xyzw
    q_conj = (-x, -y, -z, w)
    return quat_rotate(q_conj, ang_vel_world)


def m_s2_to_bmi_accel_units(a: Vec3, g: float = 9.81) -> Vec3:
    """Map m/s^2 to Renode BMI088 FeedAccSample units (~1000 ~= 1 g on Z)."""
    scale = 1000.0 / g
    return Vec3(a.x * scale, a.y * scale, a.z * scale)


def rad_s_to_bmi_gyro_units(w: Vec3) -> Vec3:
    """
    Map rad/s to Renode FeedGyroSample model units.
    Bitcraze model typically uses deg/s-ish raw scale; start 1:1 deg/s.
    """
    r2d = 180.0 / math.pi
    return Vec3(w.x * r2d, w.y * r2d, w.z * r2d)


def altitude_m_to_pressure_pa(alt_m: float, p0: float = 101325.0) -> float:
    """Simple barometric formula (ISA troposphere approx)."""
    return p0 * (1.0 - 2.25577e-5 * alt_m) ** 5.25588
