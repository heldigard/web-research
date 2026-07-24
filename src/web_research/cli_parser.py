"""Argument-parser construction for the web-research CLI.

Separated from ``cli.py`` to respect the 250-LOC vertical-slice budget.
Subcommand handlers are injected by the caller to avoid a circular import.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

try:
    from importlib.metadata import version as _version

    _pkg_version = _version("web-research")
    if _pkg_version == "0.0.0":
        from web_research._version import __version__ as _pkg_version
except Exception:  # pragma: no cover
    from web_research._version import __version__ as _pkg_version


def build_parser(handlers: dict[str, Callable]) -> argparse.ArgumentParser:
    """Construct the top-level parser.

    Args:
        handlers: maps subcommand name (search/research/read/status/capabilities)
            to its mode function. Injected by the caller so this module does not
            import the modes (no cycle).
    """
    # vs-soft-allow  — one cohesive argparse builder. The depth is a flat
    # sequence of subparser declarations (common flags + one block per
    # subcommand); splitting would scatter a single declarative concern across
    # files and make the CLI surface harder to read in one pass.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--no-cache", action="store_true", help="bypass disk cache")
    common.add_argument("--timeout", type=int, help="HTTP timeout (sec); default 30")
    common.add_argument("--verbose", action="store_true", help="emit backend diagnostics to stderr")

    p = argparse.ArgumentParser(
        description="Local web research engine (SearXNG+Firecrawl+Ollama+opt-in cloud fallback).",
    )
    p.add_argument("--version", action="version", version=f"web-research {_pkg_version}")
    sub = p.add_subparsers(dest="cmd", required=True)

    capabilities = sub.add_parser(
        "capabilities",
        help="emit machine-readable capability metadata without network probes",
    )
    capabilities.add_argument(
        "--json",
        action="store_true",
        help="accepted for uniform router invocation; output is always JSON",
    )
    capabilities.set_defaults(func=handlers["capabilities"])

    status = sub.add_parser(
        "status",
        parents=[common],
        help="probe local SearXNG/Firecrawl/Ollama + report models, keys, cache.",
    )
    status.add_argument(
        "--json",
        action="store_true",
        help="emit the status envelope as JSON instead of a human report.",
    )
    status.set_defaults(func=handlers["status"])

    ps = sub.add_parser(
        "search", parents=[common], help="SearXNG search -> clean markdown results."
    )
    ps.add_argument("query")
    ps.add_argument("-n", type=int, default=8)
    ps.add_argument(
        "--engine",
        default="searxng",
        choices=["searxng", "minimax", "zai", "duckduckgo"],
    )
    ps.add_argument("--cat", default="general")
    ps.add_argument("--lang", default="en")
    ps.add_argument("--time", default="", help="day|week|month|year")
    ps.add_argument("--rerank", action="store_true", help="Ollama semantic rerank + dedup.")
    ps.add_argument(
        "--smart",
        action="store_true",
        help="Profile query, score sources, summarize results.",
    )
    ps.add_argument(
        "--summary",
        action="store_true",
        help="smart only: synthesize a structured answer from snippets.",
    )
    ps.add_argument(
        "--allow-cloud-fallback",
        action="store_true",
        help="opt in to PAYG cloud synthesis only if both local Ollama models fail",
    )
    ps.add_argument("--json", action="store_true", help="emit results as JSON.")
    ps.set_defaults(func=handlers["search"])

    pr = sub.add_parser(
        "research",
        parents=[common],
        help="Search -> scrape top K -> Ollama synthesis (opt-in cloud) w/ citations.",
    )
    pr.add_argument("query")
    pr.add_argument("-n", type=int, default=6, help="search results to pull")
    pr.add_argument("--scrape", type=int, default=3, help="how many to fully scrape")
    pr.add_argument("--max-chars", type=int, default=12000, dest="max_chars")
    pr.add_argument(
        "--engine",
        default="searxng",
        choices=["searxng", "minimax", "zai", "duckduckgo"],
    )
    pr.add_argument("--time", default="")
    pr.add_argument("--answer", action="store_true", help="direct Q&A style instead of report")
    pr.add_argument(
        "--allow-cloud-fallback",
        action="store_true",
        help="opt in to PAYG cloud synthesis only if both local Ollama models fail",
    )
    pr.add_argument(
        "--smart",
        action="store_true",
        help="profile, focused extract, structured synthesis",
    )
    pr.add_argument(
        "--no-robots",
        action="store_true",
        help="skip robots.txt check before scraping result pages.",
    )
    pr.add_argument(
        "--code-analyze",
        action="store_true",
        help="opt-in: look up query identifiers in the local repo via codeq and "
        "append a 'Local code context' section to each scraped doc before "
        "synthesis. No-op when codeq is absent or no symbol resolves locally.",
    )
    pr.add_argument(
        "--no-follow-up",
        action="store_true",
        help="with --smart: skip the automatic single follow-up search hop "
        "suggested by structured synthesis (recommended_next_search).",
    )
    pr.add_argument("--json", action="store_true", help="emit structured research evidence")
    pr.set_defaults(func=handlers["research"])

    prd = sub.add_parser(
        "read",
        parents=[common],
        help="Read one URL -> markdown via Firecrawl, Z.AI, or stdlib HTML.",
    )
    prd.add_argument("url")
    prd.add_argument(
        "--engine",
        default="firecrawl",
        choices=["firecrawl", "zai", "html"],
    )
    prd.add_argument(
        "--no-robots",
        action="store_true",
        help="skip robots.txt check before fetching the URL.",
    )
    prd.add_argument(
        "--wait",
        type=int,
        default=0,
        help="milliseconds to wait for JS rendering before Firecrawl scrapes.",
    )
    prd.add_argument("--zai-timeout", type=int, default=20, help="Z.AI reader timeout")
    prd.add_argument("--max-chars", type=int, default=12000)
    prd.set_defaults(func=handlers["read"])

    return p
