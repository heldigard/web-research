"""``read`` subcommand: fetch one URL into markdown via Firecrawl or Z.AI reader."""

from __future__ import annotations

import argparse
import sys
from typing import cast

from web_research.features.read.engine import firecrawl_scrape, zai_reader
from web_research.shared.cache import get as cache_get
from web_research.shared.cache import set as cache_set
from web_research.shared.cli_helpers import apply_common
from web_research.shared.config import ZAI_API_KEY
from web_research.shared.http import _debug


def _fetch_markdown(args: argparse.Namespace) -> str:
    """Try the requested engine first, then Firecrawl, then Z.AI if a key is set."""
    engines = [args.engine]
    if args.engine != "firecrawl":
        engines.append("firecrawl")
    if "zai" not in engines and ZAI_API_KEY:
        engines.append("zai")
    for eng in engines:
        md = _fetch_one(eng, args)
        if md:
            return md
    return ""


def _fetch_one(eng: str, args: argparse.Namespace) -> str:
    if eng == "zai":
        return zai_reader(args.url, timeout=args.zai_timeout)
    return firecrawl_scrape(args.url, wait=args.wait)


def mode_read(args: argparse.Namespace) -> int:
    """Read one URL into markdown."""
    apply_common(args)
    cache_params = {"url": args.url, "engine": args.engine, "wait": args.wait}
    cached = None if args.no_cache else cache_get("read", cache_params)
    if cached:
        _debug("cache", "read hit")
        md = cast(str, cached["markdown"])
    else:
        _debug("cache", "read miss")
        md = _fetch_markdown(args)
        if md and not args.no_cache:
            cache_set("read", cache_params, {"markdown": md})

    if not md:
        print(f"[error] no markdown from {args.url}", file=sys.stderr)
        return 1
    if args.max_chars and len(md) > args.max_chars:
        md = md[: args.max_chars] + f"\n\n..._[truncated {len(md) - args.max_chars} chars]_"
    print(f"# {args.url}\n")
    print(md)
    return 0
