#!/usr/bin/env python3
"""Poll Renode monitor socket for guest CPU stats (cpu_stats command)."""
from __future__ import annotations

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from renode_monitor import RenodeClient  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
INTERVAL = float(os.environ.get("INTERVAL", "1"))
DEBUG = os.environ.get("MONITOR_DEBUG", "") == "1"

STATS_RE = re.compile(
    r"ins=(?P<ins>\d+)\s+"
    r"rate=(?P<rate>[-\d.]+)\s+"
    r"util=(?P<util>[-\d.]+)%\s+"
    r"mips_cap=(?P<mips>\d+)\s+"
    r"sim_speed=(?P<sim>[-\d.]+)x\s+"
    r"pc=(?P<pc>0x[0-9a-fA-F]+)\s+"
    r"virt=(?P<virt>[-\d.]+)s\s+"
    r"host=(?P<host>[-\d.]+)s"
)
ERROR_RE = re.compile(r"No such command or device|Command .* failed", re.IGNORECASE)


def parse_stats(raw: str) -> dict[str, str] | None:
    if ERROR_RE.search(raw):
        return None
    match = STATS_RE.search(raw.replace("\n", " "))
    if not match:
        return None
    return match.groupdict()


def main() -> int:
    print(f"Renode guest CPU monitor (port {PORT}, every {INTERVAL}s)")
    print("Keep this running — closing it disconnects Renode's only monitor client.")
    print("Do not run inject_imu_stream.sh at the same time (also needs -P).")
    print(
        "Columns: wall_s  ins  rate/s  util%  mips_cap  sim_speed  pc  virt_s  host_s\n"
    )

    client: RenodeClient | None = None
    try:
        print("Connecting (telnet handshake)...", flush=True)
        client = RenodeClient(PORT)
        print("Connected. First sample may show rate=n/a until baseline exists.\n", flush=True)
    except (ConnectionError, TimeoutError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        while True:
            wall = time.time()
            raw = client.query("cpu_stats")
            stats = parse_stats(raw)

            if stats:
                print(
                    f"{wall:.3f}  ins={stats['ins']}  rate={stats['rate']}/s  "
                    f"util={stats['util']}%  mips_cap={stats['mips']}  "
                    f"sim={stats['sim']}x  pc={stats['pc']}  "
                    f"virt={stats['virt']}s  host={stats['host']}s"
                )
            else:
                print(f"{wall:.3f}  parse_error  raw={raw!r}")
                if DEBUG:
                    print(f"[debug] raw={raw!r}", file=sys.stderr)
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except ConnectionError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
