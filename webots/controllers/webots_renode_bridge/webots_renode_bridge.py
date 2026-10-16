#!/usr/bin/env python3
"""
Thin Webots controller entrypoint.

Webots looks for controllers/<name>/<name>.py. This forwards to the host
bridge package so the same code runs as `python3 -m bridge.webots_renode_bridge`
when using controller "<extern>".

World default uses <extern>; to use this in-tree controller instead, set:
  controller "webots_renode_bridge"
and ensure PYTHONPATH includes renode_test/ (or WEBOTS_HOME project dir).
"""
from __future__ import annotations

import os
import sys

# renode_test/ is three levels up from this file:
#   webots/controllers/webots_renode_bridge/webots_renode_bridge.py
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Default closed-loop when launched from Webots GUI
if "--mode" not in sys.argv:
    sys.argv.extend(["--mode", "closed-loop", "--thrust", "35000"])

from bridge.webots_renode_bridge import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
