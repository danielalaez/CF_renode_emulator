#!/usr/bin/env python3
"""Poll motor_stats from Renode; optional --force for open-loop ratios."""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from renode_monitor import RenodeClient  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Poll Renode motor_stats")
    p.add_argument("port", nargs="?", type=int, default=int(os.environ.get("RENODE_MONITOR_PORT", "9999")))
    p.add_argument("--hz", type=float, default=5.0)
    p.add_argument("--force", type=float, nargs=4, metavar=("M1", "M2", "M3", "M4"),
                   help="Set motorPowerSet override ratios (0..65535) once, then poll")
    p.add_argument("--clear", action="store_true", help="Clear motor override and exit")
    p.add_argument("--once", action="store_true")
    args = p.parse_args()

    client = RenodeClient(args.port)
    try:
        if args.clear:
            print(client.query("motor_force_clear") or "(ok)")
            return 0
        if args.force is not None:
            m1, m2, m3, m4 = args.force
            print(client.query(f"motor_force {m1} {m2} {m3} {m4}") or "(ok)", flush=True)
        period = 1.0 / args.hz if args.hz > 0 else 0.2
        while True:
            out = client.query("motor_stats")
            print(f"{time.time():.3f}  {out or '(empty)'}", flush=True)
            if args.once:
                return 0
            time.sleep(period)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
