#!/bin/bash
# Poll Renode monitor socket for guest CPU activity (persistent connection).
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/monitor_cpu.py" "$@"
