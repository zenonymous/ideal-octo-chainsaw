#!/usr/bin/env python3
"""Backwards-compatible entry point: `./gopoll.py` polls once, like the original script.

Any arguments are passed to the gotracker CLI, e.g. `./gopoll.py report`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gotracker.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
