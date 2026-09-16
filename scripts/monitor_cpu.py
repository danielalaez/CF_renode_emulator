#!/usr/bin/env python3
"""Poll Renode monitor socket for guest CPU stats (cpu_stats command)."""
from __future__ import annotations

import os
import re
import socket
import sys
import time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
INTERVAL = float(os.environ.get("INTERVAL", "1"))
MACHINE = os.environ.get("MACHINE", "CF2.1")
TIMEOUT = float(os.environ.get("MONITOR_TIMEOUT", "5"))
CONNECT_TIMEOUT = float(os.environ.get("MONITOR_CONNECT_TIMEOUT", "60"))
DEBUG = os.environ.get("MONITOR_DEBUG", "") == "1"

TELNET_HANDSHAKE = bytes(
    [255, 251, 0, 255, 253, 1, 255, 253, 3]
)

PROMPT_RE = re.compile(r"\((?:monitor|CF2\.1)\)")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
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


def clean_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").replace("\x00", "")
    return ANSI_RE.sub("", text)


class RenodeClient:
    def __init__(self, port: int) -> None:
        try:
            self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        except OSError as exc:
            raise ConnectionError(
                f"Cannot connect to localhost:{port} ({exc}).\n"
                "Start Renode first:\n"
                "  RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh"
            ) from exc

        self.sock.settimeout(0.2)
        self.buf = b""
        self.text = ""
        self.machine_selected = False

        self.sock.sendall(TELNET_HANDSHAKE)
        self._wait_for_prompt(CONNECT_TIMEOUT)
        self._select_machine()

    def _read_available(self) -> None:
        while True:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                return
            if not chunk:
                raise ConnectionError(
                    "Renode closed the monitor connection. "
                    "Stopping the monitor script or the Docker container will do this."
                )
            self.buf += chunk
            self.text = clean_text(self.buf)
            if DEBUG:
                print(f"[debug] recv +{len(chunk)} bytes", file=sys.stderr)

    def _wait_for_prompt(self, deadline_s: float) -> None:
        end = time.time() + deadline_s
        while time.time() < end:
            self._read_available()
            if PROMPT_RE.search(self.text):
                return
        tail = self.text[-400:].replace("\n", "\\n")
        raise TimeoutError(
            "Timed out waiting for Renode monitor prompt "
            f"(last bytes: {tail!r}). Is Renode still loading?"
        )

    def _select_machine(self) -> None:
        if self.machine_selected:
            return
        self.query(f'mach set "{MACHINE}"', expect_prompt=True)
        self.machine_selected = True

    def _tail_since(self, marker: int) -> str:
        return clean_text(self.buf[marker:])

    def query(self, cmd: str, expect_prompt: bool = True) -> str:
        marker = len(self.buf)
        self.sock.sendall(f"{cmd}\n".encode("utf-8"))

        end = time.time() + TIMEOUT
        while time.time() < end:
            self._read_available()
            chunk = self._tail_since(marker)
            if expect_prompt and not PROMPT_RE.search(chunk):
                continue
            lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
            body: list[str] = []
            for ln in lines:
                if ln == cmd or ln.startswith("("):
                    continue
                if "Renode" in ln or "Monitor available" in ln:
                    continue
                if ln.startswith(("Phase ", "Feed ", "Machine started", "Monitor tips")):
                    continue
                body.append(ln)
            if body:
                return "\n".join(body)
            if expect_prompt and PROMPT_RE.search(chunk):
                return ""
        return ""

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


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
