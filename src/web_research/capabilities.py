"""Machine-readable capabilities for routers and cross-CLI orchestration."""

from __future__ import annotations

import argparse
import json
from typing import Any

from web_research._version import __version__

CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "name": "search",
        "purpose": "Search local-first backends and return ranked results.",
        "read_only": True,
        "destructive": False,
        "idempotent": False,
        "open_world": True,
        "structured_json": True,
        "engines": ("searxng", "minimax", "zai", "duckduckgo"),
        "cost": "cheap",
    },
    {
        "name": "read",
        "purpose": "Read one URL through Firecrawl, Z.AI, or stdlib HTML.",
        "read_only": True,
        "destructive": False,
        "idempotent": False,
        "open_world": True,
        "structured_json": False,
        "engines": ("firecrawl", "zai", "html"),
        "cost": "moderate",
    },
    {
        "name": "research",
        "purpose": "Search, scrape, rank, and synthesize cited evidence.",
        "read_only": True,
        "destructive": False,
        "idempotent": False,
        "open_world": True,
        "structured_json": True,
        "engines": ("searxng", "minimax", "zai", "duckduckgo"),
        "cost": "expensive",
    },
    {
        "name": "capabilities",
        "purpose": "Emit this local capability manifest without network access.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": True,
        "engines": tuple(),
        "cost": "cheap",
    },
)


def capabilities_payload() -> dict[str, Any]:
    """Return the stable tool-card envelope consumed by routers."""
    return {
        "command": "capabilities",
        "schema_version": 1,
        "tool": "web-research",
        "version": __version__,
        "capabilities": [dict(item) for item in CAPABILITIES],
    }


def mode_capabilities(_args: argparse.Namespace) -> int:
    """Print the compact capability manifest without probing external services."""
    print(json.dumps(capabilities_payload(), ensure_ascii=False, separators=(",", ":")))
    return 0
