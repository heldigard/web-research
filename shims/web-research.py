#!/usr/bin/env python3
"""Compatibility shim for the historical Claude ecosystem path.

Copy or symlink this file to ``~/.claude/scripts/web-research.py``. It avoids
depending on user-site editable installs, so workers with an isolated ``HOME``
can still import the graduated package from ``~/web-research/src``.
"""
# ruff: noqa: E402,I001

from __future__ import annotations

import os
import sys
from pathlib import Path


def _default_project() -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parent.parent]
    try:
        candidates.append(here.parents[2] / "web-research")
    except IndexError:
        pass
    for candidate in candidates:
        if (candidate / "src" / "web_research").exists():
            return candidate
    return Path.home() / "web-research"


project_src = Path(os.environ.get("WEB_RESEARCH_HOME", str(_default_project()))) / "src"
sys.path.insert(0, str(project_src))

from web_research.cli import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
