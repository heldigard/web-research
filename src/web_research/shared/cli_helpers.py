"""CLI helpers shared across the search/read/research mode commands."""

from __future__ import annotations

from argparse import Namespace

from web_research.shared import config


def apply_common(args: Namespace) -> None:
    """Push global CLI overrides (``--timeout``, ``--verbose``) into module config."""
    if getattr(args, "timeout", None):
        config.TIMEOUT = args.timeout
    if getattr(args, "verbose", False):
        config.VERBOSE = True
