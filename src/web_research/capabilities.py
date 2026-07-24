"""Machine-readable capabilities for routers and cross-CLI orchestration."""

from __future__ import annotations

import argparse
import json
from typing import Any

from web_research._version import __version__
from web_research.shared.config import SCHEMA_VERSION

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
        "options": {
            "cache": {"flag": "--no-cache", "default": False, "effect": "bypass_disk_cache"},
            "timeout": {"flag": "--timeout", "type": "integer", "unit": "seconds"},
            "verbose": {"flag": "--verbose", "default": False},
            "count": {"flag": "-n", "type": "integer", "default": 8},
            "engine": {"flag": "--engine", "default": "searxng"},
            "category": {"flag": "--cat", "default": "general"},
            "language": {"flag": "--lang", "default": "en"},
            "time": {"flag": "--time", "values": ("day", "week", "month", "year")},
            "rerank": {"flag": "--rerank", "default": False},
            "smart": {"flag": "--smart", "default": False},
            "summary": {"flag": "--summary", "default": False},
            "cloud_fallback": {
                "flag": "--allow-cloud-fallback",
                "default": False,
                "lane": "payg",
            },
            "json": {"flag": "--json", "default": False, "structured_output": True},
        },
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
        "options": {
            "cache": {"flag": "--no-cache", "default": False, "effect": "bypass_disk_cache"},
            "timeout": {"flag": "--timeout", "type": "integer", "unit": "seconds"},
            "verbose": {"flag": "--verbose", "default": False},
            "engine": {"flag": "--engine", "default": "firecrawl"},
            "robots": {"default": "enforce", "bypass_flag": "--no-robots"},
            "wait": {
                "flag": "--wait",
                "type": "integer",
                "unit": "milliseconds",
                "default": 0,
                "note": "passed unconverted to Firecrawl waitFor (ms)",
            },
            "zai_timeout": {
                "flag": "--zai-timeout",
                "type": "integer",
                "unit": "seconds",
                "default": 20,
            },
            "max_chars": {"flag": "--max-chars", "type": "integer", "default": 12000},
        },
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
        "options": {
            "cache": {"flag": "--no-cache", "default": False, "effect": "bypass_disk_cache"},
            "timeout": {"flag": "--timeout", "type": "integer", "unit": "seconds"},
            "verbose": {"flag": "--verbose", "default": False},
            "count": {"flag": "-n", "type": "integer", "default": 6},
            "scrape": {"flag": "--scrape", "type": "integer", "default": 3},
            "max_chars": {"flag": "--max-chars", "type": "integer", "default": 12000},
            "engine": {"flag": "--engine", "default": "searxng"},
            "time": {"flag": "--time", "values": ("day", "week", "month", "year")},
            "answer": {"flag": "--answer", "default": False},
            "smart": {"flag": "--smart", "default": False},
            "robots": {"default": "enforce", "bypass_flag": "--no-robots"},
            "code_analyze": {
                "flag": "--code-analyze",
                "default": False,
                "dependency": "codeq",
                "unavailable": "no_op",
                "structured_output": "local_code_context",
            },
            "follow_up": {
                "flag": "--no-follow-up",
                "default": True,
                "when": "smart",
                "effect": "disable_single_follow_up_search_hop",
                "description": (
                    "With --smart, run at most one extra search+scrape hop from "
                    "structured recommended_next_search, then re-synthesize."
                ),
            },
            "cloud_fallback": {
                "flag": "--allow-cloud-fallback",
                "default": False,
                "lane": "payg",
            },
            "json": {"flag": "--json", "default": False, "structured_output": True},
        },
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
        "options": {
            "json": {"flag": "--json", "default": False, "structured_output": True},
        },
    },
    {
        "name": "status",
        "purpose": "Probe local SearXNG/Firecrawl/Ollama and report service, "
        "model, key, cache, and cloud-fallback health.",
        "read_only": True,
        "destructive": False,
        "idempotent": True,
        "open_world": False,
        "structured_json": True,
        "engines": tuple(),
        "cost": "cheap",
        "options": {
            "cache": {"flag": "--no-cache", "default": False, "effect": "bypass_disk_cache"},
            "timeout": {"flag": "--timeout", "type": "integer", "unit": "seconds"},
            "verbose": {"flag": "--verbose", "default": False},
            "json": {"flag": "--json", "default": False, "structured_output": True},
        },
    },
)


def capabilities_payload() -> dict[str, Any]:
    """Return the stable tool-card envelope consumed by routers."""
    return {
        "command": "capabilities",
        "schema_version": SCHEMA_VERSION,
        "tool": "web-research",
        "version": __version__,
        "capabilities": [dict(item) for item in CAPABILITIES],
    }


def mode_capabilities(_args: argparse.Namespace) -> int:
    """Print the compact capability manifest without probing external services."""
    print(json.dumps(capabilities_payload(), ensure_ascii=False, separators=(",", ":")))
    return 0
