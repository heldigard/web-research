#!/usr/bin/env python3
"""Local dev shim — run the package from the source tree without installing.

  python3 shim.py search "query" -n 3

Production entry points:
  - Wired ecosystem shim: ~/.claude/scripts/web-research.py (skills call this)
  - PATH symlink: ~/.local/bin/web-research -> the shim above
  - Console script (after `pip install -e .`): `web-research`

This file exists only for quick local iteration from ~/web-research/.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from web_research.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
